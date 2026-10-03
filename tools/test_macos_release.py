"""Test Mac update publication with authored archives and mocked external services."""
import base64
from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from tools import macos_release as release


PUBLIC_KEY = base64.b64encode(b"p" * 32).decode()
REPOSITORY = "owner/halo-ce-universal"
SETTINGS = {"github_repository": REPOSITORY, "channel_tag": "macos-updates",
            "feed_url": f"https://github.com/{REPOSITORY}/releases/download/macos-updates/appcast.xml",
            "public_update_key": PUBLIC_KEY}


class MacReleaseTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_public_config_is_repository_scoped_and_requires_a_key(self):
        self.assertEqual(release.release_configuration(SETTINGS, REPOSITORY), REPOSITORY)
        for change in ({"public_update_key": None}, {"feed_url": None},
                       {"feed_url": SETTINGS["feed_url"].replace("owner/", "other/")},
                       {"feed_url": "https://name:secret@example.com/feed.xml"},
                       {"feed_url": SETTINGS["feed_url"] + "?token=value"},
                       {"channel_tag": "launcher-v1.8"}):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                release.release_configuration({**SETTINGS, **change})
        with self.assertRaises(RuntimeError):
            release.release_configuration(SETTINGS, "another/repository")
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": REPOSITORY,
                                    "GITHUB_REF": "refs/heads/main"}):
            self.assertEqual(release.release_configuration(SETTINGS), REPOSITORY)
            for variable, value in (("GITHUB_REF", "refs/pull/1/merge"), ("GITHUB_REPOSITORY", "fork/repo")):
                with patch.dict(os.environ, {variable: value}), self.assertRaises(RuntimeError):
                    release.release_configuration(SETTINGS)

    def test_archive_and_feed_require_signatures_and_preserve_supported_older_updates(self):
        old = self.record(build="1.1")
        new = self.record(build="2.1")
        feed = release.appcast(new, release.appcast(old))
        items = ET.fromstring(feed).findall("channel/item")
        self.assertEqual([item.findtext("{" + release.NAMESPACE + "}version") for item in items], ["2.1", "1.1"])
        self.assertEqual(items[0].findtext("{" + release.NAMESPACE + "}hardwareRequirements"), "arm64")
        self.assertEqual(items[0].find("enclosure").get("{" + release.NAMESPACE + "}edSignature"), new["signature"])
        self.assertEqual(len(ET.fromstring(release.appcast(new, feed)).findall("channel/item")), 2)
        with self.assertRaisesRegex(RuntimeError, "older Mac build"):
            release.appcast(old, feed)
        with self.assertRaisesRegex(RuntimeError, "different signed archive"):
            release.appcast({**new, "signature": "different"}, feed)
        for value in ("../1", "1-test", "1.2.3.4.5", "", None):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                release.release_tag(value)

    def record(self, build="3.1"):
        data = b"authored disk image fixture"
        filename = "Halo-CE-Universal-0.1.0-macos-arm64.dmg"
        return {"version": "0.1.0", "build": build, "filename": filename,
                "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                "signature": base64.b64encode(b"s" * 64).decode(), "public_update_key": PUBLIC_KEY,
                "repository": REPOSITORY, "feed_url": SETTINGS["feed_url"],
                "url": f"https://github.com/{REPOSITORY}/releases/download/macos-build-{build}/{filename}",
                "source_revision": "a" * 40, "minimum_macos": "26.0",
                "published_at": "Fri, 02 Oct 2026 12:00:00 +0000",
                "notarization": {"app": "authored-app-submission", "dmg": "authored-dmg-submission"},
                "distributable": True}

    def fixture(self, directory):
        record = self.record()
        (directory / record["filename"]).write_bytes(b"authored disk image fixture")
        (directory / "release.json").write_text(json.dumps(record))
        return record

    def test_prepared_record_rejects_changed_bytes_and_unverified_manifests(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            original = self.fixture(directory)
            for changes in ({"distributable": False}, {"notarization": {"dmg": "only-one"}},
                            {"filename": "../Halo.dmg"}, {"repository": "other/repo"},
                            {"source_revision": "main"}, {"public_update_key": "other"},
                            {"size": original["size"] + 1}, {"sha256": "0" * 64}):
                (directory / "release.json").write_text(json.dumps({**original, **changes}))
                with self.subTest(changes=changes), patch.object(release, "setup_sparkle") as setup, \
                        self.assertRaises(RuntimeError):
                    release.verified_record(directory, SETTINGS, REPOSITORY)
                setup.assert_not_called()
            (directory / "release.json").write_text(json.dumps(original))
            (directory / original["filename"]).write_bytes(b"different archive")
            with patch.object(release, "setup_sparkle") as setup, self.assertRaises(RuntimeError):
                release.verified_record(directory, SETTINGS, REPOSITORY)
            setup.assert_not_called()

    def service(self, directory, record):
        events, releases, assets, downloads = [], {}, {}, {}
        latest = {"tag_name": "launcher-v1.8", "id": 99}
        api_root = "repos/" + REPOSITORY

        def api(endpoint, *, data=None, method=None, missing=False):
            events.append(("api", endpoint, deepcopy(data)))
            if endpoint == api_root:
                return {"private": False, "archived": False}
            if endpoint == api_root + "/releases/latest":
                return deepcopy(latest)
            if "/releases/tags/" in endpoint:
                return deepcopy(releases.get(endpoint.rsplit("/", 1)[1]))
            if "/commits/" in endpoint:
                return {"sha": record["source_revision"]}
            if endpoint == api_root + "/releases" and data is not None:
                item = {"id": len(releases) + 1, "assets": [], **deepcopy(data)}
                releases[data["tag_name"]] = item
                return deepcopy(item)
            if "/releases/" in endpoint and method == "PATCH":
                item = next(item for item in releases.values() if item["id"] == int(endpoint.rsplit("/", 1)[1]))
                item.update(data)
                if not item["draft"]:
                    for asset in item["assets"]:
                        url = f"https://github.com/{REPOSITORY}/releases/download/{item['tag_name']}/{asset['name']}"
                        downloads[url] = assets[(item["tag_name"], asset["name"])]
                return deepcopy(item)
            raise AssertionError((endpoint, data, method, missing))

        def command(*arguments, capture=False):
            events.append(("run", tuple(map(str, arguments))))
            if arguments[:3] == ("gh", "release", "upload"):
                tag, path = str(arguments[3]), Path(arguments[4])
                item = releases[tag]
                content = path.read_bytes()
                asset = {"name": path.name, "id": 10, "size": len(content), "state": "uploaded",
                         "digest": "sha256:" + hashlib.sha256(content).hexdigest()}
                item["assets"] = [old for old in item["assets"] if old["name"] != path.name] + [asset]
                assets[(tag, path.name)] = content
                if not item["draft"]:
                    downloads[f"https://github.com/{REPOSITORY}/releases/download/{tag}/{path.name}"] = content
            return "" if capture else None

        def download(url, limit):
            events.append(("download", url))
            content = downloads[url]
            if len(content) > limit:
                raise RuntimeError("oversize download")
            return content

        def sign(*arguments, capture=False):
            events.append(("sign", tuple(map(str, arguments))))
            path = Path(arguments[1])
            if path.suffix == ".xml":
                if arguments[0] == "-p":
                    path.write_bytes(path.read_bytes() + b"\n<!-- authored signed-feed fixture -->")
                elif not path.read_bytes().endswith(b"<!-- authored signed-feed fixture -->"):
                    raise RuntimeError("Feed signature verification failed")
            return "" if capture else None

        return SimpleNamespace(events=events, releases=releases, assets=assets, downloads=downloads,
                               latest=latest, api=api, command=command, download=download, sign=sign)

    def publish_fixture(self, directory, service):
        with patch.object(release, "config", return_value=SETTINGS), \
                patch.object(release, "setup_sparkle"), patch.object(release, "signing_key", return_value=PUBLIC_KEY), \
                patch.object(release, "run", side_effect=service.command), \
                patch.object(release, "sparkle_sign", side_effect=service.sign), \
                patch.object(release, "github_api", side_effect=service.api), \
                patch.object(release, "public_download", side_effect=service.download), redirect_stdout(io.StringIO()):
            release.publish(SimpleNamespace(directory=directory, repository=REPOSITORY))

    def test_publishes_verified_archive_before_signed_feed_and_never_changes_latest(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            record = self.fixture(directory)
            service = self.service(directory, record)
            self.publish_fixture(directory, service)
            tag = release.release_tag(record["build"])
            archive_check = service.events.index(("download", record["url"]))
            feed_upload = next(i for i, event in enumerate(service.events)
                               if event[0] == "run" and event[1][:4] == ("gh", "release", "upload", "macos-updates"))
            self.assertLess(archive_check, feed_upload)
            self.assertEqual(service.latest["tag_name"], "launcher-v1.8")
            writes = [event[2] for event in service.events if event[0] == "api" and event[2] is not None]
            self.assertTrue(writes)
            self.assertTrue(all(write["make_latest"] == "false" for write in writes))
            self.assertTrue(service.releases["macos-updates"]["prerelease"])
            self.assertFalse(service.releases[tag]["draft"])
            self.assertEqual(service.downloads[SETTINGS["feed_url"]], (directory / "appcast.xml").read_bytes())
            service.events.clear()
            self.publish_fixture(directory, service)
            self.assertFalse(any(event[0] == "run" and event[1][:4] == ("gh", "release", "upload", tag)
                                 for event in service.events))
            self.assertEqual(len(service.releases), 2)

    def test_public_archive_mismatch_never_creates_or_changes_the_feed(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            record = self.fixture(directory)
            service = self.service(directory, record)
            download = service.download
            service.download = lambda url, limit: b"tampered" if url == record["url"] else download(url, limit)
            with self.assertRaisesRegex(RuntimeError, "Public archive verification"):
                self.publish_fixture(directory, service)
            self.assertNotIn("macos-updates", service.releases)

    def test_retry_recovers_signed_feed_from_interrupted_draft_channel(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            record = self.fixture(directory)
            service = self.service(directory, record)
            previous = release.appcast(self.record("2.1")) + b"\n<!-- authored signed-feed fixture -->"
            service.releases["macos-updates"] = {"id": 1, "tag_name": "macos-updates", "draft": True, "prerelease": True,
                "assets": [{"id": 11, "name": "appcast.xml", "size": len(previous)}]}
            with patch.object(release.subprocess, "run", return_value=
                    subprocess.CompletedProcess([], 0, stdout=previous, stderr=b"")) as download:
                self.publish_fixture(directory, service)
            download.assert_called_once_with(["gh", "api", "repos/" + REPOSITORY + "/releases/assets/11",
                "-H", "Accept: application/octet-stream"], capture_output=True)
            self.assertFalse(service.releases["macos-updates"]["draft"])
            items = ET.fromstring(service.downloads[SETTINGS["feed_url"]]).findall("channel/item")
            self.assertEqual([item.findtext("{" + release.NAMESPACE + "}version") for item in items], ["3.1", "2.1"])
            self.assertEqual(service.latest["tag_name"], "launcher-v1.8")

    def test_newer_or_unsigned_previous_feed_fails_before_any_remote_write(self):
        for newer in (True, False):
            with self.subTest(newer=newer), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                record = self.fixture(directory)
                service = self.service(directory, record)
                service.releases["macos-updates"] = {"id": 1, "draft": False, "prerelease": True,
                    "assets": [{"name": "appcast.xml"}]}
                previous = release.appcast(self.record("4.1" if newer else "2.1"))
                service.downloads[SETTINGS["feed_url"]] = previous + (b"\n<!-- authored signed-feed fixture -->" if newer else b"")
                with self.assertRaises(RuntimeError):
                    self.publish_fixture(directory, service)
                self.assertFalse(any(event[0] == "api" and event[2] is not None for event in service.events))
                self.assertFalse(any(event[0] == "run" and event[1][0] == "gh" for event in service.events))

    def test_existing_archive_with_different_digest_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            record = self.fixture(directory)
            service = self.service(directory, record)
            service.releases[release.release_tag(record["build"])] = {
                "id": 1, "draft": True, "prerelease": False, "target_commitish": record["source_revision"],
                "assets": [{"name": record["filename"], "size": record["size"], "digest": "sha256:" + "0" * 64,
                            "state": "uploaded"}]}
            with self.assertRaisesRegex(RuntimeError, "different or unverified"):
                self.publish_fixture(directory, service)
            self.assertFalse(any(event[0] == "run" and event[1][0] == "gh" for event in service.events))
            self.assertFalse(any(event[0] == "api" and event[2] is not None for event in service.events))

    def test_secret_tool_errors_do_not_expose_stderr_or_arguments(self):
        failed = subprocess.CompletedProcess([], 1, stdout="private-seed", stderr="private-seed")
        with patch.object(release.subprocess, "run", return_value=failed), self.assertRaises(RuntimeError) as failure:
            release.secret_command("security", "-p", "private-password", private_input="private-seed")
        self.assertEqual(str(failure.exception), "Signing credential setup failed in security")

    def test_cleanup_attempts_all_keychain_operations_and_removes_raw_secrets_on_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            state_file = directory / "keychain-state.json"
            state_file.write_text(json.dumps({"default": "original-default", "search": ["original-search"]}))
            (directory / "signing.keychain-db").touch()
            for name in ("certificate.p12", "notary.p8", "sparkle-private.txt"):
                (directory / name).write_text("authored secret fixture")
            with patch.object(release, "secret_command", side_effect=[RuntimeError("fixture"), None, None]) as command, \
                    self.assertRaisesRegex(RuntimeError, "rerun cleanup"):
                release.cleanup_ci_signing(directory)
            self.assertEqual([call.args[1] for call in command.call_args_list],
                             ["default-keychain", "list-keychains", "delete-keychain"])
            self.assertTrue(state_file.exists())
            self.assertFalse(any((directory / name).exists() for name in
                                 ("certificate.p12", "notary.p8", "sparkle-private.txt")))
            with patch.object(release, "secret_command"):
                release.cleanup_ci_signing(directory)
            self.assertFalse(state_file.exists())

    def test_ci_seed_is_only_passed_to_tools_over_stdin_and_must_match_public_key(self):
        seed = base64.b64encode(b"s" * 32).decode()
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true", "SPARKLE_PRIVATE_KEY": seed}), \
                patch.object(release, "secret_command", return_value=PUBLIC_KEY + "\n") as command:
            self.assertEqual(release.signing_key(SETTINGS), PUBLIC_KEY)
            self.assertNotIn(seed, command.call_args.args)
            self.assertEqual(command.call_args.kwargs["private_input"], seed)
            release.sparkle_sign("-p", Path("authored.dmg"), capture=True)
            self.assertNotIn(seed, command.call_args.args)
            self.assertEqual(command.call_args.args[1:3], ("--ed-key-file", "-"))
            command.return_value = "different public key\n"
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                release.signing_key(SETTINGS)
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true", "SPARKLE_PRIVATE_KEY": "invalid-private-text"}), \
                patch.object(release, "secret_command") as command, self.assertRaises(RuntimeError) as failure:
            release.signing_key(SETTINGS)
        command.assert_not_called()
        self.assertNotIn("invalid-private-text", str(failure.exception))


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Prepare signed Mac updates and publish them to a separate GitHub channel.

Ordinary DMGs need no credentials. Publishing is an explicit command, verifies
the notarized archive before updating the signed feed, and never marks a Mac
release as GitHub's latest. No game data, private keys or env files are packaged.
"""
import argparse
import base64
from datetime import datetime, timezone
from email.utils import format_datetime
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import secrets
import shlex
import subprocess
import sys
import tempfile
from urllib.parse import urlparse
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.macos_build import APP_VERSION, github_repository, update_configuration
from tools.macos_sparkle import setup_sparkle, DIRECTORY as SPARKLE

CONFIG = ROOT / "port/macos/release-config.json"
APP = ROOT / "build/macos/Halo CE Universal.app"
ACCOUNT = "local.halo.ce-universal"
NAMESPACE = "http://www.andymatuschak.org/xml-namespaces/sparkle"
CHANNEL_TAG = "macos-updates"
BUILD_TAG_PREFIX = "macos-build-"
ET.register_namespace("sparkle", NAMESPACE)


def run(*command, capture=False):
    return subprocess.run([str(part) for part in command], cwd=ROOT, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None).stdout


def config():
    return json.loads(CONFIG.read_text())


def https_url(value):
    url = urlparse(value or "")
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise RuntimeError("Release URLs must be public HTTPS URLs without credentials, queries or fragments")
    return value.rstrip("/")


def release_configuration(settings, repository=None):
    repository = github_repository(settings, repository, release=True)
    expected_feed = f"https://github.com/{repository}/releases/download/{CHANNEL_TAG}/appcast.xml"
    if not update_configuration(settings) or settings.get("feed_url") != expected_feed:
        raise RuntimeError("Configure the repository's macos-updates/appcast.xml feed and public update key first")
    if settings.get("channel_tag", CHANNEL_TAG) != CHANNEL_TAG:
        raise RuntimeError("The Mac update channel must use the dedicated macos-updates tag")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        if os.environ.get("GITHUB_REPOSITORY", "").lower() != repository.lower():
            raise RuntimeError("The workflow repository does not match the committed release configuration")
        if os.environ.get("GITHUB_REF") != "refs/heads/main":
            raise RuntimeError("Signed Mac releases run only from main")
    return repository


def build_number(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,3}", value):
        raise RuntimeError("Use a numeric build number with at most four components")
    numbers = tuple(int(part) for part in value.split("."))
    return numbers + (0,) * (4 - len(numbers))


def release_tag(build):
    build_number(build)
    return BUILD_TAG_PREFIX + build


def signing_key(settings):
    """CI supplies an existing 32-byte seed on stdin, never in process arguments."""
    seed = os.environ.get("SPARKLE_PRIVATE_KEY")
    if seed is None:
        key = run(SPARKLE / "bin/generate_keys", "--account", ACCOUNT, "-p", capture=True).strip()
    else:
        if os.environ.get("GITHUB_ACTIONS") != "true":
            raise RuntimeError("Use the Keychain for local signing; secret environment input is CI-only")
        try:
            if len(base64.b64decode(seed.strip(), validate=True)) != 32:
                raise ValueError("Invalid seed")
        except (ValueError, TypeError):
            raise RuntimeError("SPARKLE_PRIVATE_KEY must be an exported Sparkle 2.10 base64 32-byte seed") from None
        # CryptoKit derives the public key from the supplied seed; no new key
        # is generated and no private material is written to disk or logged.
        script = '''import Foundation
import CryptoKit
let input = FileHandle.standardInput.readDataToEndOfFile()
do {
    guard let text = String(data: input, encoding: .utf8),
          let seed = Data(base64Encoded: text.trimmingCharacters(in: .whitespacesAndNewlines)) else { exit(1) }
    let key = try Curve25519.Signing.PrivateKey(rawRepresentation: seed)
    print(key.publicKey.rawRepresentation.base64EncodedString())
} catch { exit(1) }
'''
        key = secret_command("swift", "-e", script, private_input=seed, capture=True).strip()
    if key != settings["public_update_key"]:
        raise RuntimeError("The signing key does not match the committed public update key")
    return key


def sparkle_sign(*arguments, capture=False):
    seed = os.environ.get("SPARKLE_PRIVATE_KEY")
    if seed is None:
        return run(SPARKLE / "bin/sign_update", "--account", ACCOUNT, *arguments, capture=capture)
    # signing_key has validated the seed and its public key before this call.
    output = secret_command(SPARKLE / "bin/sign_update", "--ed-key-file", "-", *arguments,
                            private_input=seed, capture=True)
    return output if capture else None


def audit_bundle(app):
    """An explicit package boundary, not a license clearance for compiled code."""
    allowed = {"Info.plist", "MacOS", "Frameworks", "Resources", "_CodeSignature"}
    contents = app / "Contents"
    if {path.name for path in contents.iterdir()} - allowed:
        raise RuntimeError("Unexpected top-level content in the app")
    resources = contents / "Resources"
    if {path.name for path in resources.iterdir()} - {"AppIcon.icns", "Helmet.pdf", "halo_guest.elf", "BuildInfo.txt", "Licenses"}:
        raise RuntimeError("Release resources must contain only the compiled engine, icons, build record and licenses")
    if {path.name for path in (contents / "MacOS").iterdir()} != {"halo"}:
        raise RuntimeError("Release executables must contain only the native host")
    if {path.name for path in (contents / "Frameworks").iterdir()} != {"Sparkle.framework", "libSDL3.0.dylib", "libEGL.dylib", "libGLESv2.dylib"}:
        raise RuntimeError("Unexpected bundled runtime dependency")
    for path in app.rglob("*"):
        if path.suffix.lower() in {".iso", ".xiso", ".map", ".xbe", ".pdb", ".p12", ".mobileprovision"}:
            raise RuntimeError("Restricted or private input in app: " + str(path.relative_to(app)))
        if path.is_symlink() and not path.resolve().is_relative_to(app.resolve()):
            raise RuntimeError("External symlink in the signed app")
    return True


def audit_adhoc_signing(app):
    """Check all bundled code without exposing unexpected signing metadata."""
    with (app / "Contents/Info.plist").open("rb") as stream:
        if plistlib.load(stream)["CFBundleIdentifier"] != ACCOUNT:
            raise RuntimeError("Unexpected app bundle identifier")
    # Inspect every real Mach-O, including nested Sparkle helpers. Vendor
    # capability entitlements remain intact; no signing certificate or team
    # identity is allowed, even on a secondary architecture in a fat binary.
    magic = {bytes.fromhex(value) for value in (
        "feedface", "cefaedfe", "feedfacf", "cffaedfe",
        "cafebabe", "bebafeca", "cafebabf", "bfbafeca",
    )}
    checked = 0
    for path in app.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open("rb") as stream:
            if stream.read(4) not in magic:
                continue
        architectures = subprocess.check_output(["lipo", "-archs", str(path)], text=True).split()
        if not architectures:
            raise RuntimeError("No Mach-O architectures found: " + str(path.relative_to(app)))
        for architecture in architectures:
            result = subprocess.run(
                ["codesign", "-d", "--verbose=4", "--arch", architecture, str(path)],
                capture_output=True, text=True, check=True)
            fields = result.stderr.splitlines()
            if ("Signature=adhoc" not in fields or "TeamIdentifier=not set" not in fields
                    or any(field.startswith("Authority=") for field in fields)):
                raise RuntimeError("Expected ad-hoc signing without a certificate or team: "
                                   + str(path.relative_to(app)) + " (" + architecture + ")")
        checked += 1
    if not checked:
        raise RuntimeError("No signed Mach-O code found in app")
    print(f"Verified {checked} code objects: ad-hoc signing, no certificate authorities or team identifiers")
    return checked


def appcast(record, previous=None):
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Halo CE Universal Updates"
    entry = ET.SubElement(channel, "item")
    ET.SubElement(entry, "title").text = "Halo " + record["version"]
    ET.SubElement(entry, "{" + NAMESPACE + "}version").text = record["build"]
    ET.SubElement(entry, "{" + NAMESPACE + "}shortVersionString").text = record["version"]
    ET.SubElement(entry, "{" + NAMESPACE + "}hardwareRequirements").text = "arm64"
    if record.get("published_at"):
        ET.SubElement(entry, "pubDate").text = record["published_at"]
    if record.get("repository"):
        ET.SubElement(entry, "link").text = f"https://github.com/{record['repository']}/releases/tag/{release_tag(record['build'])}"
    ET.SubElement(entry, "{" + NAMESPACE + "}minimumSystemVersion").text = record["minimum_macos"]
    ET.SubElement(entry, "enclosure", {"url": record["url"], "length": str(record["size"]),
        "type": "application/octet-stream",
        "{" + NAMESPACE + "}edSignature": record["signature"]})
    if previous:
        try:
            old = ET.fromstring(previous)
        except ET.ParseError:
            raise RuntimeError("The previous signed update feed contains invalid XML") from None
        if old.tag != "rss" or old.find("channel") is None:
            raise RuntimeError("The previous update feed is not an appcast")
        for item in old.findall("channel/item"):
            version = item.findtext("{" + NAMESPACE + "}version")
            if build_number(version) > build_number(record["build"]):
                raise RuntimeError("Refusing to replace the feed with an older Mac build")
            if build_number(version) == build_number(record["build"]):
                enclosure = item.find("enclosure")
                if (enclosure is None or any(enclosure.get(name) != value for name, value in {
                        "url": record["url"], "length": str(record["size"]),
                        "{" + NAMESPACE + "}edSignature": record["signature"]}.items())):
                    raise RuntimeError("This Mac build already refers to a different signed archive")
                continue
            if len(channel.findall("item")) < 10:
                channel.append(item)
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)


def notarize(path, profile):
    result = json.loads(run("xcrun", "notarytool", "submit", path, "--keychain-profile", profile,
                            "--wait", "--output-format", "json", capture=True))
    if result.get("status") != "Accepted":
        raise RuntimeError("Apple did not accept notarization; submission " + str(result.get("id")))
    return result["id"]


def create_dmg(app, destination):
    if destination.exists():
        raise RuntimeError("Disk image output already exists; choose a new filename")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="halo-dmg-") as temporary:
        layout = Path(temporary)
        run("ditto", app, layout / app.name)
        (layout / "Applications").symlink_to("/Applications")
        run("hdiutil", "create", "-volname", "Halo CE Universal", "-srcfolder", layout,
            "-format", "UDZO", destination)


def local_dmg(args):
    audit_bundle(APP)
    run("codesign", "--verify", "--deep", "--strict", APP)
    with (APP / "Contents/Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    destination = args.output or ROOT / "build/macos" / ("Halo-" + info["CFBundleShortVersionString"] + "-local.dmg")
    create_dmg(APP, destination.resolve())
    print("Prepared ad-hoc DMG (not notarized; automatic updates disabled): " + str(destination))


def build_release(args):
    settings = config()
    repository = release_configuration(settings, args.repository)
    build_number(args.build_number)
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,2}", args.version):
        raise RuntimeError("Use numeric version and build numbers")
    if not args.sign_identity.startswith("Developer ID Application:"):
        raise RuntimeError("Select an explicit Developer ID Application identity")
    if run("git", "status", "--porcelain", capture=True).strip():
        raise RuntimeError("Build public releases from a clean, committed tree")
    destination = ROOT / "build/macos/releases" / args.build_number
    if destination.exists():
        raise RuntimeError("Release output already exists; use a new build number")
    setup_sparkle()
    key = signing_key(settings)
    destination.mkdir(parents=True)
    run(sys.executable, "tools/macos_build.py", "--release", "--no-data-path", "--sign-identity", args.sign_identity,
        "--version", args.version, "--build-number", args.build_number, "--repository", repository)
    audit_bundle(APP)
    run("codesign", "--verify", "--deep", "--strict", APP)
    with (APP / "Contents/Info.plist").open("rb") as stream:
        minimum_macos = plistlib.load(stream)["LSMinimumSystemVersion"]
    app_zip = destination / "notarize-app.zip"
    run("ditto", "-c", "-k", "--keepParent", APP, app_zip)
    app_notary = notarize(app_zip, args.notary_profile)
    run("xcrun", "stapler", "staple", APP)
    run("spctl", "--assess", "--type", "execute", APP)
    dmg = destination / ("Halo-CE-Universal-" + args.version + "-macos-arm64.dmg")
    create_dmg(APP, dmg)
    run("codesign", "--sign", args.sign_identity, "--timestamp", dmg)
    dmg_notary = notarize(dmg, args.notary_profile)
    run("xcrun", "stapler", "staple", dmg)
    signature = sparkle_sign("-p", dmg, capture=True).strip()
    sparkle_sign("--verify", dmg, signature)
    record = {"version": args.version, "build": args.build_number, "filename": dmg.name,
              "size": dmg.stat().st_size, "sha256": hashlib.sha256(dmg.read_bytes()).hexdigest(),
              "signature": signature, "public_update_key": key,
              "repository": repository,
              "url": f"https://github.com/{repository}/releases/download/{release_tag(args.build_number)}/{dmg.name}",
              "feed_url": settings["feed_url"], "source_revision": run("git", "rev-parse", "HEAD", capture=True).strip(),
              "minimum_macos": minimum_macos,
              "published_at": format_datetime(datetime.now(timezone.utc)),
              "notarization": {"app": app_notary, "dmg": dmg_notary}, "distributable": True}
    (destination / "release.json").write_text(json.dumps(record, indent=2) + "\n")
    (destination / "appcast.xml").write_bytes(appcast(record))
    sparkle_sign("-p", destination / "appcast.xml")
    sparkle_sign("--verify", destination / "appcast.xml")
    (destination / "SHA256SUMS").write_text(record["sha256"] + "  " + dmg.name + "\n")
    print("Prepared release: " + str(destination))


def github_api(endpoint, *, data=None, method=None, missing=False):
    command = ["gh", "api", endpoint]
    if data is not None:
        command += ["--method", method or "POST", "--input", "-"]
    result = subprocess.run(command, input=json.dumps(data) if data is not None else None,
                            capture_output=True, text=True, cwd=ROOT)
    if result.returncode:
        if missing and "HTTP 404" in result.stderr:
            return None
        raise RuntimeError("GitHub API request failed: " + endpoint)
    return json.loads(result.stdout)


def public_download(url, limit):
    https_url(url)
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError("The public download is larger than expected")
    return data


def verified_record(directory, settings, repository):
    record = json.loads((directory / "release.json").read_text())
    if (not record.get("distributable") or not record.get("notarization", {}).get("app")
            or not record.get("notarization", {}).get("dmg")):
        raise RuntimeError("Only verified notarized releases can be published")
    filename = record.get("filename", "")
    if not re.fullmatch(r"Halo-CE-Universal-[0-9]+(?:\.[0-9]+){0,2}-macos-arm64\.dmg", filename):
        raise RuntimeError("Unexpected Mac release filename")
    if filename != "Halo-CE-Universal-" + str(record.get("version")) + "-macos-arm64.dmg":
        raise RuntimeError("The Mac display version does not match its archive name")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,2}", record.get("minimum_macos", "")):
        raise RuntimeError("The Mac release must identify its minimum system version")
    expected_url = f"https://github.com/{repository}/releases/download/{release_tag(record['build'])}/{filename}"
    if (record.get("repository") != repository or record.get("url") != expected_url
            or record.get("feed_url") != settings["feed_url"]
            or record.get("public_update_key") != settings["public_update_key"]):
        raise RuntimeError("Release repository, feed or signing key differs from the committed configuration")
    if not re.fullmatch(r"[0-9a-f]{40}", record.get("source_revision", "")):
        raise RuntimeError("The release must identify its full source commit")
    dmg = directory / filename
    if dmg.is_symlink() or dmg.stat().st_size != record.get("size") or hashlib.sha256(dmg.read_bytes()).hexdigest() != record.get("sha256"):
        raise RuntimeError("The release disk image has changed")
    setup_sparkle()
    signing_key(settings)
    run("codesign", "--verify", "--strict", dmg)
    run("xcrun", "stapler", "validate", dmg)
    sparkle_sign("--verify", dmg, record["signature"])
    return record


def upload_archive_assets(repository, tag, release, paths):
    """Immutable asset names: retries accept only bytes GitHub already hashed."""
    existing = {asset["name"]: asset for asset in release.get("assets", [])}
    missing = []
    for path in paths:
        digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        if path.name in existing:
            asset = existing[path.name]
            if asset.get("state") != "uploaded" or asset.get("size") != path.stat().st_size or asset.get("digest") != digest:
                raise RuntimeError("A different or unverified asset already exists: " + path.name)
        else:
            missing.append(path)
    for path in missing:
        run("gh", "release", "upload", tag, path, "--repo", repository)


def publish(args):
    settings = config()
    repository = release_configuration(settings, args.repository)
    directory = args.directory.resolve()
    record = verified_record(directory, settings, repository)
    api = f"repos/{repository}"
    metadata = github_api(api)
    if metadata.get("private") or metadata.get("archived"):
        raise RuntimeError("The Mac update repository must be public and active")
    channel = github_api(api + "/releases/tags/" + CHANNEL_TAG, missing=True)
    if channel and not channel.get("prerelease"):
        raise RuntimeError("Refusing to reuse a non-prerelease tag as the Mac feed channel")
    previous = None
    if channel and any(asset["name"] == "appcast.xml" for asset in channel.get("assets", [])):
        if channel.get("draft"):
            asset = next(asset for asset in channel["assets"] if asset["name"] == "appcast.xml")
            if asset.get("size", 0) > 1024 * 1024:
                raise RuntimeError("The previous update feed is too large")
            response = subprocess.run(["gh", "api", api + "/releases/assets/" + str(asset["id"]),
                "-H", "Accept: application/octet-stream"], capture_output=True)
            if response.returncode or len(response.stdout) > 1024 * 1024:
                raise RuntimeError("Could not recover the draft Mac feed")
            previous = response.stdout
        else:
            previous = public_download(settings["feed_url"], 1024 * 1024)
        previous_file = directory / "previous-appcast.xml"
        previous_file.write_bytes(previous)
        sparkle_sign("--verify", previous_file)
    # Check ordering and signatures before making any remote change.
    feed = directory / "appcast.xml"
    feed.write_bytes(appcast(record, previous))
    sparkle_sign("-p", feed)
    sparkle_sign("--verify", feed)
    tag = release_tag(record["build"])
    release = github_api(api + "/releases/tags/" + tag, missing=True)
    if release:
        if release.get("prerelease"):
            raise RuntimeError("The versioned Mac archive tag is already used by a prerelease")
        source = (release.get("target_commitish") if release.get("draft")
                  else github_api(api + "/commits/" + tag).get("sha"))
        if source != record["source_revision"]:
            raise RuntimeError("The Mac release tag points to a different source commit")
    else:
        release = github_api(api + "/releases", data={
            "tag_name": tag, "target_commitish": record["source_revision"], "draft": True,
            "prerelease": False, "make_latest": "false", "name": "macOS " + record["version"] + " (" + record["build"] + ")",
            "body": "Apple Silicon macOS build. Supply your own Xbox game data.\n\n"
                    + f"Source: https://github.com/{repository}/commit/{record['source_revision']}\n"
                    + "Developer ID signed, notarized, and signed for Sparkle updates.\n"})
    checksum = directory / "SHA256SUMS"
    checksum.write_text(record["sha256"] + "  " + record["filename"] + "\n")
    upload_archive_assets(repository, tag, release,
                          [directory / record["filename"], directory / "release.json", checksum])
    if release.get("draft"):
        github_api(api + "/releases/" + str(release["id"]), method="PATCH",
                   data={"draft": False, "make_latest": "false"})
    downloaded = public_download(record["url"], record["size"])
    if len(downloaded) != record["size"] or hashlib.sha256(downloaded).hexdigest() != record["sha256"]:
        raise RuntimeError("Public archive verification failed; the update feed was not changed")
    latest = github_api(api + "/releases/latest", missing=True)
    if latest and latest.get("tag_name") in (tag, CHANNEL_TAG):
        raise RuntimeError("A Mac release became GitHub latest unexpectedly; the feed was not changed")
    if not channel:
        channel = github_api(api + "/releases", data={
            "tag_name": CHANNEL_TAG, "target_commitish": record["source_revision"], "draft": True,
            "prerelease": True, "make_latest": "false", "name": "macOS update feed",
            "body": "Signed Sparkle appcast for Mac builds. Versioned archives use macos-build-* tags. "
                    "This channel never replaces the repository's latest release."})
    # Only this mutable feed is replaced, after the immutable archive is public.
    run("gh", "release", "upload", CHANNEL_TAG, feed, "--clobber", "--repo", repository)
    if channel.get("draft"):
        github_api(api + "/releases/" + str(channel["id"]), method="PATCH",
                   data={"draft": False, "prerelease": True, "make_latest": "false"})
    if public_download(settings["feed_url"], 1024 * 1024) != feed.read_bytes():
        raise RuntimeError("Feed uploaded, but public verification did not match; retry this same release")
    print("Published and verified " + record["url"])


def secret_command(*command, capture=False, private_input=None):
    """Credential setup tools may echo malformed secrets; never forward output."""
    result = subprocess.run([str(part) for part in command], input=private_input, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("Signing credential setup failed in " + Path(str(command[0])).name)
    return result.stdout if capture else None


def cleanup_ci_signing(directory):
    state_file = directory / "keychain-state.json"
    failed = False
    try:
        if state_file.exists():
            state = json.loads(state_file.read_text())
            commands = [("security", "default-keychain", "-d", "user", "-s", state["default"]),
                        ("security", "list-keychains", "-d", "user", "-s", *state["search"])]
            keychain = directory / "signing.keychain-db"
            if keychain.exists():
                commands.append(("security", "delete-keychain", keychain))
            for command in commands:
                try:
                    secret_command(*command)
                except (RuntimeError, OSError):
                    failed = True
            if not failed:
                state_file.unlink()
    finally:
        for name in ("certificate.p12", "notary.p8", "sparkle-private.txt"):
            (directory / name).unlink(missing_ok=True)
    if failed:
        raise RuntimeError("Could not completely restore the temporary signing keychain; rerun cleanup")


def prepare_ci_signing(args):
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("CI credential import is only supported on an ephemeral GitHub Actions runner")
    release_configuration(config(), args.repository)
    required = ("MACOS_CERTIFICATE_BASE64", "MACOS_CERTIFICATE_PASSWORD", "MACOS_SIGN_IDENTITY",
                "MACOS_NOTARY_KEY_ID", "MACOS_NOTARY_ISSUER_ID", "MACOS_NOTARY_PRIVATE_KEY", "SPARKLE_PRIVATE_KEY")
    if any(not os.environ.get(name) for name in required):
        raise RuntimeError("Configure all signing secrets listed in docs/macos-releases.md before a signed release")
    if not os.environ["MACOS_SIGN_IDENTITY"].startswith("Developer ID Application:"):
        raise RuntimeError("MACOS_SIGN_IDENTITY must identify a Developer ID Application certificate")
    try:
        certificate = base64.b64decode(os.environ["MACOS_CERTIFICATE_BASE64"], validate=True)
    except (ValueError, TypeError):
        raise RuntimeError("A signing secret has invalid encoding") from None
    signing_key(config())
    directory = args.directory.resolve()
    if directory.exists():
        raise RuntimeError("CI signing directory already exists; do not overwrite it")
    directory.mkdir(mode=0o700, parents=True)
    keychain = directory / "signing.keychain-db"
    state = {"default": shlex.split(secret_command("security", "default-keychain", "-d", "user", capture=True))[0],
             "search": shlex.split(secret_command("security", "list-keychains", "-d", "user", capture=True))}
    (directory / "keychain-state.json").write_text(json.dumps(state))
    try:
        for name, data in (("certificate.p12", certificate),
                           ("notary.p8", os.environ["MACOS_NOTARY_PRIVATE_KEY"].encode())):
            with (directory / name).open("xb") as stream:
                os.chmod(stream.name, 0o600)
                stream.write(data)
        password = secrets.token_urlsafe(32)
        secret_command("security", "create-keychain", "-p", password, keychain)
        secret_command("security", "set-keychain-settings", "-lut", "21600", keychain)
        secret_command("security", "unlock-keychain", "-p", password, keychain)
        secret_command("security", "list-keychains", "-d", "user", "-s", keychain, *state["search"])
        secret_command("security", "default-keychain", "-d", "user", "-s", keychain)
        secret_command("security", "import", directory / "certificate.p12", "-k", keychain,
                       "-P", os.environ["MACOS_CERTIFICATE_PASSWORD"], "-T", "/usr/bin/codesign")
        secret_command("security", "set-key-partition-list", "-S", "apple-tool:,apple:,codesign:",
                       "-s", "-k", password, keychain)
        secret_command("xcrun", "notarytool", "store-credentials", "halo-macos-release", "--keychain", keychain,
                       "--key", directory / "notary.p8", "--key-id", os.environ["MACOS_NOTARY_KEY_ID"],
                       "--issuer", os.environ["MACOS_NOTARY_ISSUER_ID"])
    except BaseException:
        cleanup_ci_signing(directory)
        raise
    finally:
        for name in ("certificate.p12", "notary.p8", "sparkle-private.txt"):
            (directory / name).unlink(missing_ok=True)
    print("Signing credentials imported into the temporary CI keychain")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check-config", help="Validate public GitHub release configuration without signing or publishing")
    check.add_argument("--repository")
    prepare = commands.add_parser("prepare-ci-signing", help="Import existing CI signing credentials into a temporary keychain")
    prepare.add_argument("directory", type=Path)
    prepare.add_argument("--repository")
    cleanup = commands.add_parser("cleanup-ci-signing", help="Restore the runner's keychain settings and delete temporary credentials")
    cleanup.add_argument("directory", type=Path)
    local = commands.add_parser("local-dmg", help="Package a verified asset-free local app without hosting or Developer ID")
    local.add_argument("--output", type=Path)
    build = commands.add_parser("build")
    build.add_argument("--version", default=APP_VERSION)
    build.add_argument("--build-number", required=True)
    build.add_argument("--sign-identity", required=True)
    build.add_argument("--notary-profile", required=True)
    build.add_argument("--repository")
    upload = commands.add_parser("publish-github", help="Publish a prepared, verified release and then its signed appcast")
    upload.add_argument("directory", type=Path)
    upload.add_argument("--repository")
    args = parser.parse_args()
    if args.command == "check-config":
        release_configuration(config(), args.repository)
        print("GitHub Mac update configuration is valid")
    elif args.command == "prepare-ci-signing":
        prepare_ci_signing(args)
    elif args.command == "cleanup-ci-signing":
        cleanup_ci_signing(args.directory.resolve())
    elif args.command == "local-dmg":
        local_dmg(args)
    elif args.command == "build":
        build_release(args)
    else:
        publish(args)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print("Release failed: " + str(error), file=sys.stderr)
        sys.exit(1)

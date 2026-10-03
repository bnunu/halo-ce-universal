#!/usr/bin/env python3
"""Exercise native preferences/imports and the release boundary using synthetic data.

Creates tiny authored XDVDFS/map-header fixtures; contains no game assets.
"""
import base64
from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import plistlib
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.macos_build import update_configuration, minimum_macos_version, SDL
from tools.macos_release import audit_adhoc_signing, audit_bundle, appcast, NAMESPACE
from tools.macos_sparkle import setup_sparkle


def map_header(name, version=5, build="01.01.14.2342"):
    header = bytearray(2048)
    struct.pack_into("<4sII", header, 0, b"daeh", version, 2048)
    header[32:32 + len(name)] = name.encode()
    header[64:64 + len(build)] = build.encode()
    header[-4:] = b"toof"
    return bytes(header)


def disc_image(ui, opening):
    image = bytearray(44 * 2048)
    magic = b"MICROSOFT*XBOX*MEDIA"
    image[32 * 2048:32 * 2048 + 20] = magic
    image[33 * 2048 - 20:33 * 2048] = magic
    struct.pack_into("<II", image, 32 * 2048 + 20, 40, 20)
    root = struct.pack("<HHIIBB", 0, 0, 41, 48, 0x10, 4) + b"maps"
    image[40 * 2048:40 * 2048 + len(root)] = root
    for offset, right, sector, name in ((0, 6, 42, b"ui.map"), (24, 0, 43, b"a10.map")):
        entry = struct.pack("<HHIIBB", 0, right, sector, 2048, 0, len(name)) + name
        image[41 * 2048 + offset:41 * 2048 + offset + len(entry)] = entry
    image[42 * 2048:43 * 2048] = ui
    image[43 * 2048:44 * 2048] = opening
    return image


def native_preferences():
    output = ROOT / "build/macos/tests/menu"
    output.mkdir(parents=True, exist_ok=True)
    flags = ["-arch", "arm64", "-mmacosx-version-min=14.0", "-O2", "-Wall", "-Wextra",
             "-DHALO_MACOS=1", "-Iport/macos/native", "-Iport/linux/src"]
    sources = ["port/macos/tests/menu_preferences.m", "port/macos/native/HaloPreferences.m",
               "port/linux/src/xiso.c", "port/macos/host/posix_files.c"]
    objects = []
    for source in sources:
        obj = output / (Path(source).name + ".o")
        subprocess.run(["clang", *flags, *(["-fobjc-arc"] if source.endswith(".m") else []),
                        "-c", source, "-o", obj], cwd=ROOT, check=True)
        objects.append(obj)
    executable = output / "preferences"
    subprocess.run(["clang", *objects, "-framework", "Foundation", "-o", executable], check=True)
    with tempfile.TemporaryDirectory(prefix="fixtures-", dir=output) as temporary:
        directory = Path(temporary)
        ui, opening = map_header("ui"), map_header("a10")
        for name, ui_data, opening_data in (("valid", ui, opening), ("pc", map_header("ui", version=7), opening),
                ("mixed", ui, map_header("a10", build="01.10.12.2276")),
                ("missing", ui, None), ("truncated", ui[:100], opening)):
            maps = directory / name / "maps"
            maps.mkdir(parents=True)
            (maps / "ui.map").write_bytes(ui_data)
            if opening_data:
                (maps / "a10.map").write_bytes(opening_data)
        (directory / "disc.iso").write_bytes(disc_image(ui, opening))
        (directory / "pc.iso").write_bytes(disc_image(map_header("ui", version=7), opening))
        (directory / "broken.iso").write_bytes(b"invalid disc image")
        mixed = directory / "mixed-custom/maps"
        mixed.mkdir(parents=True)
        for name in ("ui", "a10", "bloodgulch"):
            (mixed / (name + ".map")).write_bytes(map_header(name))
        (mixed / "hugeass.map").write_bytes(map_header("hugeass", version=609))
        (mixed / "beavercreek_halo3.yelo").write_bytes(map_header("beavercreek_halo3", version=609))
        for name in ("bitmaps", "sounds", "loc"):
            (mixed / (name + ".map")).write_bytes(b"authored resource fixture")
        for name, replacement in (
                ("ce-ui", ("ui", map_header("ui", version=609))),
                ("ce-a10", ("a10", map_header("a10", version=609))),
                ("pc-retail", ("bloodgulch", map_header("bloodgulch", version=7))),
                ("mixed-retail", ("bloodgulch", map_header("bloodgulch", build="01.10.12.2276"))),
                ("invalid-retail", ("bloodgulch", b"truncated"))):
            maps = directory / name / "maps"
            maps.mkdir(parents=True)
            for base in ("ui", "a10"):
                (maps / (base + ".map")).write_bytes(map_header(base))
            (maps / (replacement[0] + ".map")).write_bytes(replacement[1])
        missing = directory / "missing-ui-with-ce/maps"
        missing.mkdir(parents=True)
        (missing / "a10.map").write_bytes(opening)
        (missing / "hugeass.map").write_bytes(map_header("hugeass", version=609))
        command = [executable, directory]
        if (ROOT / "assets/maps/ui.map").exists():
            command.append(ROOT / "assets")
        subprocess.run(command, check=True, timeout=20)


def build_ui_test():
    """Reuse a built host and bundle its real menu/SDL code under a test identity."""
    output = ROOT / "build/macos/tests/menu-ui"
    app = output / "HaloMenuTest.app"
    original = ROOT / "build/macos/Halo CE Universal.app/Contents"
    frameworks = original / "Frameworks"
    output.mkdir(parents=True, exist_ok=True)
    flags = ["-arch", "arm64", "-mmacosx-version-min=14.0", "-O2", "-DHALO_MACOS=1", "-D_DARWIN_C_SOURCE",
             "-I.", "-Iport/macos/host", "-Iport/macos/native", "-Iport/android/include", f"-I{SDL / 'include'}"]
    for source, extra, obj in (("port/macos/tests/menu_ui.m", ["-fobjc-arc", "-fblocks"], "ui.o"),
                               ("port/macos/host/host_main.c", ["-Dmain=halo_game_main"], "main.o")):
        subprocess.run(["clang", *flags, *extra, "-c", source, "-o", output / obj], cwd=ROOT, check=True)
    if app.exists():
        shutil.rmtree(app)
    executable = app / "Contents/MacOS/menu-ui"
    executable.parent.mkdir(parents=True)
    objects = [p for p in (ROOT / "build/macos/host-obj").glob("*.o") if p.name != "host_main.c.o"]
    subprocess.run(["clang", "-mmacosx-version-min=14.0", output / "ui.o", output / "main.o", *objects,
        *[frameworks / name for name in ("libSDL3.0.dylib", "libEGL.dylib", "libGLESv2.dylib")],
        f"-F{frameworks}", "-framework", "Sparkle", "-framework", "Cocoa",
        "-Wl,-rpath,@executable_path/../Frameworks", "-o", executable], check=True)
    shutil.copytree(frameworks, app / "Contents/Frameworks", symlinks=True)
    resources = app / "Contents/Resources"
    resources.mkdir()
    for name in ("Helmet.pdf", "AppIcon.icns"):
        shutil.copy2(original / "Resources" / name, resources / name)
    with (original / "Info.plist").open("rb") as stream:
        minimum = plistlib.load(stream)["LSMinimumSystemVersion"]
    info = {"CFBundleExecutable":"menu-ui", "CFBundleIdentifier":"local.halo.ce.menu-tests", "CFBundleName":"HaloMenuTest",
            "CFBundlePackageType":"APPL", "CFBundleVersion":"1", "CFBundleShortVersionString":"1.0",
            "CFBundleIconFile":"AppIcon.icns", "LSMinimumSystemVersion":minimum}
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
    subprocess.run(["codesign", "--force", "--sign", "-", app], check=True)
    saves = output / "saves"
    saves.mkdir(exist_ok=True)
    print("Built isolated UI test:", executable)
    print("Run with arguments:", saves, ROOT / "assets")


def native_menu_loop():
    """Compile the shipped menu and SDL bridge without SDK headers or game data."""
    output = ROOT / "build/macos/tests/menu-loop"
    output.mkdir(parents=True, exist_ok=True)
    sparkle = setup_sparkle().parent
    egl = ROOT / "build/macos/angle/dist/EGL.xcframework/macos-arm64"
    flags = ["-arch", "arm64", "-mmacosx-version-min=14.0", "-O2", "-Wall", "-Wextra",
             "-DHALO_MACOS=1", "-D_DARWIN_C_SOURCE", "-I.", "-Iport/macos/host",
             "-Iport/macos/native", "-Iport/linux/src", "-Iport/android/include",
             "-Ibuild/macos/toolchain/gl", f"-I{SDL / 'include'}", f"-F{sparkle}"]
    sources = ("port/macos/tests/menu_ui.m", "port/macos/tests/menu_support.c",
               "port/macos/native/host_menu.m", "port/macos/native/HaloPreferences.m",
               "port/macos/host/host_sdl.c", "port/macos/host/host_invite.c",
               "port/macos/host/posix_files.c", "port/linux/src/xiso.c")
    objects = []
    for source in sources:
        obj = output / (Path(source).name + '.o')
        subprocess.run(["clang", *flags, *(["-fobjc-arc", "-fblocks"] if source.endswith('.m') else []),
                        "-c", source, "-o", obj], cwd=ROOT, check=True)
        objects.append(obj)
    app = output / "HaloMenuLoop.app"
    executable = app / "Contents/MacOS/menu-loop"
    executable.parent.mkdir(parents=True, exist_ok=True)
    (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({
        'CFBundleExecutable': 'menu-loop', 'CFBundleIdentifier': 'local.halo.ce.menu-loop-tests',
        'CFBundleName': 'HaloMenuLoop', 'CFBundlePackageType': 'APPL',
        'CFBundleVersion': '1', 'CFBundleShortVersionString': '1.0'}))
    subprocess.run(["clang", *objects, f"-L{SDL / 'lib'}", "-lSDL3", f"-F{egl}",
                    "-framework", "libEGL", f"-F{sparkle}", "-framework", "Sparkle", "-framework", "Cocoa",
                    f"-Wl,-rpath,{egl}", f"-Wl,-rpath,{sparkle}", "-o", executable], check=True)
    subprocess.run(['codesign', '--force', '--sign', '-', app], check=True)
    with tempfile.TemporaryDirectory(prefix="fixtures-", dir=output) as temporary:
        directory = Path(temporary)
        maps = directory / 'data/maps'
        maps.mkdir(parents=True)
        for name in ('ui', 'a10'):
            (maps / (name + '.map')).write_bytes(map_header(name))
        image = directory / 'disc.iso'
        image.write_bytes(disc_image(map_header('ui'), map_header('a10')))
        environment = {k: v for k, v in os.environ.items() if not k.startswith('HALO_')}
        environment['HALO_WINDOWED'] = '1'
        subprocess.run([executable, directory / 'saves', maps.parent, image],
                       env=environment, check=True, timeout=20)


class ReleaseBoundary(unittest.TestCase):
    def signing_fixture(self, directory, identifier="local.halo.ce-universal"):
        app = Path(directory) / "Halo.app"
        contents = app / "Contents"
        (contents / "MacOS").mkdir(parents=True)
        (contents / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": identifier}))
        (contents / "MacOS/halo").write_bytes(bytes.fromhex("cffaedfe"))
        return app

    def test_adhoc_audit_checks_nested_code_and_every_architecture(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = self.signing_fixture(temporary)
            helper = app / "Contents/Frameworks/Sparkle.framework/Versions/B/Autoupdate"
            helper.parent.mkdir(parents=True)
            helper.write_bytes(bytes.fromhex("cafebabe"))
            (helper.parent / "Alias").symlink_to(helper.name)
            (helper.parent / "LICENSE").write_text("Synthetic non-code fixture")
            checked = []

            def signatures(command, **options):
                checked.append((Path(command[-1]).relative_to(app).as_posix(),
                                command[command.index("--arch") + 1]))
                self.assertTrue(options["capture_output"])
                return subprocess.CompletedProcess(command, 0, stdout="", stderr=(
                    "Signature=adhoc\nTeamIdentifier=not set\nIdentifier=org.sparkle-project.fixture\n"))

            with patch("tools.macos_release.subprocess.check_output", return_value="x86_64 arm64\n"), \
                    patch("tools.macos_release.subprocess.run", side_effect=signatures), \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(audit_adhoc_signing(app), 2)
            self.assertCountEqual(checked, [(path, architecture) for path in (
                "Contents/MacOS/halo", "Contents/Frameworks/Sparkle.framework/Versions/B/Autoupdate"
            ) for architecture in ("x86_64", "arm64")])

    def test_adhoc_audit_rejects_identity_in_secondary_architecture_without_exposing_it(self):
        forbidden = ("Authority=Developer ID Application: Private Person (PRIVATE123)",
                     "TeamIdentifier=PRIVATETEAM", "Signature=certificate")
        with tempfile.TemporaryDirectory() as temporary:
            app = self.signing_fixture(temporary)
            for field in forbidden:
                with self.subTest(field=field.split("=")[0]):
                    checked = []

                    def signatures(command, **options):
                        architecture = command[command.index("--arch") + 1]
                        checked.append(architecture)
                        metadata = "Signature=adhoc\nTeamIdentifier=not set\n"
                        if architecture == "arm64":
                            key = field.split("=")[0]
                            metadata = "\n".join(line for line in metadata.splitlines()
                                                  if not line.startswith(key + "=")) + "\n" + field + "\n"
                        return subprocess.CompletedProcess(command, 0, stdout="", stderr=metadata)

                    output, errors = io.StringIO(), io.StringIO()
                    with patch("tools.macos_release.subprocess.check_output", return_value="x86_64 arm64\n"), \
                            patch("tools.macos_release.subprocess.run", side_effect=signatures), \
                            redirect_stdout(output), redirect_stderr(errors), \
                            self.assertRaises(RuntimeError) as failure:
                        audit_adhoc_signing(app)
                    self.assertEqual(checked, ["x86_64", "arm64"])
                    self.assertIn("Contents/MacOS/halo (arm64)", str(failure.exception))
                    reported = str(failure.exception) + output.getvalue() + errors.getvalue()
                    for value in ("Private Person", "PRIVATE123", "PRIVATETEAM", field):
                        self.assertNotIn(value, reported)

    def test_adhoc_audit_rejects_non_generic_bundle_identifier_without_exposing_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = self.signing_fixture(temporary, "private.person.halo")
            with self.assertRaisesRegex(RuntimeError, "Unexpected app bundle identifier") as failure:
                audit_adhoc_signing(app)
            self.assertNotIn("private.person.halo", str(failure.exception))

    def test_adhoc_audit_rejects_bundle_without_macho_code(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = self.signing_fixture(temporary)
            (app / "Contents/MacOS/halo").write_bytes(b"\x7fELFsynthetic guest")
            with patch("tools.macos_release.subprocess.check_output") as lipo, \
                    patch("tools.macos_release.subprocess.run") as codesign, \
                    self.assertRaisesRegex(RuntimeError, "No signed Mach-O code"):
                audit_adhoc_signing(app)
            lipo.assert_not_called()
            codesign.assert_not_called()

    def test_adhoc_audit_rejects_empty_architecture_list(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = self.signing_fixture(temporary)
            with patch("tools.macos_release.subprocess.check_output", return_value="\n"), \
                    patch("tools.macos_release.subprocess.run") as codesign, \
                    self.assertRaises(RuntimeError):
                audit_adhoc_signing(app)
            codesign.assert_not_called()

    def test_os_requirement_ignores_linker_tool_and_source_versions(self):
        output = "Load command 1\n cmd LC_BUILD_VERSION\n minos 14.0\n tool 3\n version 27037.1\nLoad command 2\n cmd LC_SOURCE_VERSION\n version 1000.0\nLoad command 3\n cmd LC_VERSION_MIN_MACOSX\n version 15.0\n"
        with patch("tools.macos_build.subprocess.check_output", return_value=output):
            self.assertEqual(minimum_macos_version([]), "15.0")

    def test_update_config_requires_matching_key_and_https(self):
        key = base64.b64encode(bytes(32)).decode()
        self.assertEqual(update_configuration({}), {})
        self.assertEqual(update_configuration({"feed_url":"https://example.com/feed.xml", "public_update_key":key})["SUPublicEDKey"], key)
        for config in ({"feed_url":"https://example.com/feed.xml"}, {"public_update_key":key},
                       {"feed_url":"http://example.com/feed.xml", "public_update_key":key},
                       {"feed_url":"https://name:secret@example.com/feed.xml", "public_update_key":key}):
            with self.assertRaises(RuntimeError):
                update_configuration(config)

    def test_release_excludes_local_assets_and_external_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary) / "Halo.app"
            contents = app / "Contents"
            for name in ("Resources", "MacOS", "Frameworks"):
                (contents / name).mkdir(parents=True)
            (contents / "Info.plist").touch()
            (contents / "MacOS/halo").touch()
            for name in ("Sparkle.framework", "libSDL3.0.dylib", "libEGL.dylib", "libGLESv2.dylib"):
                (contents / "Frameworks" / name).touch()
            self.assertTrue(audit_bundle(app))
            for name in ("GameDataPath.txt", "game.iso", "GameData", "ui.map"):
                path = contents / "Resources" / name
                path.touch()
                with self.assertRaises(RuntimeError):
                    audit_bundle(app)
                path.unlink()
            (contents / "Resources/halo_guest.elf").symlink_to("/tmp")
            with self.assertRaises(RuntimeError):
                audit_bundle(app)

    def test_appcast_carries_verified_archive_and_actual_os_requirement(self):
        record = {"version":"0.3.0", "build":"8", "url":"https://example.com/mac/8/Halo.dmg",
                  "size":123, "signature":"test-signature", "minimum_macos":"26.0"}
        item = ET.fromstring(appcast(record)).find("channel/item")
        self.assertEqual(item.find("{" + NAMESPACE + "}minimumSystemVersion").text, "26.0")
        self.assertEqual(item.find("enclosure").get("{" + NAMESPACE + "}edSignature"), record["signature"])
        self.assertEqual(item.find("enclosure").get("url"), record["url"])


if __name__ == "__main__":
    if sys.argv[1:] == ["--build-ui"]:
        build_ui_test()
    elif sys.argv[1:] == ["--check-ui"]:
        native_menu_loop()
    else:
        native_preferences()
        unittest.main(argv=[sys.argv[0]])

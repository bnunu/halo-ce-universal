"""Exercise Mac build selection and package boundaries without SDKs or game data."""
import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import plistlib
import re
import runpy
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import android_build, macos_build, macos_guest_cc, macos_setup, ninja_syntax

ROOT = Path(__file__).resolve().parents[1]


@contextlib.contextmanager
def working_directory(directory):
    previous = Path.cwd()
    os.chdir(directory)
    try:
        yield
    finally:
        os.chdir(previous)


class MacBuildTests(unittest.TestCase):
    def assertIn(self, member, container, msg=None):
        # Ninja graphs can be hundreds of kilobytes; keep failures actionable.
        if isinstance(container, str) and len(container) > 2000:
            self.assertTrue(member in container, msg or f"Missing generated fragment: {member!r}")
        else:
            super().assertIn(member, container, msg)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="halo-mac-build-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.configuration = {"github_repository": "bnunu/halo-ce-universal",
                              "feed_url": None, "public_update_key": None}
        self.config_file = self.root / "port/macos/release-config.json"
        self.config_file.parent.mkdir(parents=True)
        self.save_configuration()

    def save_configuration(self):
        self.config_file.write_text(json.dumps(self.configuration))

    def test_repository_validation_and_signed_channel(self):
        self.assertEqual(macos_build.github_repository(self.configuration), "bnunu/halo-ce-universal")
        self.assertEqual(macos_build.github_repository(self.configuration, "a-fork/Halo.CE_Universal"),
                         "a-fork/Halo.CE_Universal")
        for bad in ("", "https://github.com/a/b", "a/b/c", "a/..", "a/.", "a b/c", "a/b?x=1", "a/b\n"):
            with self.subTest(repository=bad), self.assertRaises(RuntimeError):
                macos_build.github_repository(self.configuration, bad)
        with self.assertRaisesRegex(RuntimeError, "Signed releases"):
            macos_build.github_repository(self.configuration, "a-fork/halo", release=True)
        self.assertEqual(macos_build.github_repository(self.configuration, "BNUNU/HALO-CE-UNIVERSAL", release=True),
                         "BNUNU/HALO-CE-UNIVERSAL")

    def test_default_cli_prompts_for_data_and_never_installs(self):
        with patch.object(macos_build, "ROOT", self.root), patch.object(macos_build.os, "chdir"), \
                patch.object(macos_build, "build_host") as host, patch.object(macos_build, "package") as package, \
                patch("sys.argv", ["macos_build.py", "--host-only", "--repository", "a-fork/halo"]):
            macos_build.main()
        host.assert_called_once_with()
        self.assertIsNone(package.call_args.args[0])
        self.assertFalse(package.call_args.kwargs["release"])
        self.assertEqual(package.call_args.kwargs["repository"], "a-fork/halo")
        self.assertFalse((self.root / "Applications").exists())

    def test_release_refuses_missing_update_key_before_packaging(self):
        with patch.object(macos_build, "ROOT", self.root), patch.object(macos_build, "package_into") as package:
            with self.assertRaisesRegex(RuntimeError, "update feed"):
                macos_build.package(None, release=True, sign_identity="Developer ID Application: Fixture")
            package.assert_not_called()

    def test_package_copies_only_runtime_and_records_download_origin(self):
        self.configuration.update(feed_url="https://example.org/appcast.xml",
                                  public_update_key=base64.b64encode(b"x" * 32).decode())
        self.save_configuration()
        build = self.root / "build/macos"
        build.mkdir(parents=True)
        for name in ("halo", "halo_guest.elf", "private.map"):
            (build / name).write_bytes(b"authored fixture")
        sdl = self.root / "sdl"
        (sdl / "lib").mkdir(parents=True)
        (sdl / "lib/libSDL3.0.dylib").write_bytes(b"authored library")
        angle = self.root / "angle"
        for name in ("EGL", "GLESv2"):
            library = angle / f"{name}.xcframework/macos-arm64/lib{name}.framework/lib{name}"
            library.parent.mkdir(parents=True)
            library.write_bytes(b"authored library")
        sparkle = self.root / "sparkle/Sparkle.framework"
        (sparkle / "Versions/B").mkdir(parents=True)
        (sparkle / "Sparkle").write_bytes(b"authored framework")
        data = self.root / "private-data/maps"
        data.mkdir(parents=True)
        (data / "ui.map").write_bytes(b"authored private fixture")
        app = self.root / "Halo.app"
        fonts = self.root / "port/assets/fonts"
        fonts.mkdir(parents=True)
        for name in ("Overpass-OFL.txt", "OpenCE-OFL.txt", "Newtown-LICENSE.txt"):
            (fonts / name).write_text("authored license: " + name)
        with contextlib.ExitStack() as stack:
            for name, value in (("ROOT", self.root), ("BUILD", build), ("SDL", sdl), ("ANGLE", angle)):
                stack.enter_context(patch.object(macos_build, name, value))
            stack.enter_context(patch.object(macos_build, "setup_sparkle", return_value=sparkle))
            stack.enter_context(patch.object(macos_build, "package_icon"))
            stack.enter_context(patch.object(macos_build, "render_menu_icon"))
            stack.enter_context(patch.object(macos_build, "minimum_macos_version", return_value="14.0"))
            stack.enter_context(patch.object(macos_build.subprocess, "check_output", return_value="fixture-revision\n"))
            commands = stack.enter_context(patch.object(macos_build, "run"))
            macos_build.package_into(app, None, sign_identity="-", release=False,
                                     version="0.1.0", build="1", repository="a-fork/halo")
            info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
            resources = app / "Contents/Resources"
            self.assertNotIn("SUFeedURL", info)
            self.assertNotIn("SUPublicEDKey", info)
            self.assertNotIn("SUEnableAutomaticChecks", info)
            self.assertEqual(info["HaloMacDownloadsURL"],
                             "https://github.com/a-fork/halo/actions/workflows/macos-dmg.yml")
            self.assertIn("Repository: a-fork/halo\n", (resources / "BuildInfo.txt").read_text())
            self.assertFalse((resources / "GameDataPath.txt").exists())
            self.assertEqual(list(app.rglob("*.map")), [])
            for name in ("Overpass-OFL.txt", "OpenCE-OFL.txt", "Newtown-LICENSE.txt"):
                self.assertEqual((resources / "Licenses" / name).read_bytes(), (fonts / name).read_bytes())
            commands.assert_any_call("codesign", "--verify", "--deep", "--strict", app)
            # Explicit development data is a path reference, never copied.
            macos_build.package_into(app, data.parent, sign_identity="-", release=False,
                                     version="0.1.0", build="2")
            self.assertEqual((resources / "GameDataPath.txt").read_text(), str(data.parent.resolve()) + "\n")
            macos_build.package_into(app, data.parent, sign_identity="Developer ID Application: Fixture",
                                     release=True, version="0.1.0", build="3")
            info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
            self.assertEqual(info["SUFeedURL"], self.configuration["feed_url"])
            self.assertTrue(info["SUVerifyUpdateBeforeExtraction"])
            self.assertTrue(info["SURequireSignedFeed"])
            self.assertFalse((resources / "GameDataPath.txt").exists())
            self.assertEqual(list(app.rglob("*.map")), [])

    def test_failed_package_preserves_previous_bundle(self):
        build = self.root / "build/macos"
        app = build / "Halo CE Universal.app"
        app.mkdir(parents=True)
        (app / "previous").write_text("keep")
        with patch.object(macos_build, "ROOT", self.root), patch.object(macos_build, "BUILD", build), \
                patch.object(macos_build, "package_into", side_effect=RuntimeError("authored failure")):
            with self.assertRaisesRegex(RuntimeError, "authored failure"):
                macos_build.package(None)
        self.assertEqual((app / "previous").read_text(), "keep")
        self.assertEqual(list(build.iterdir()), [app])

    def test_setup_checksum_and_cached_download(self):
        destination = self.root / "dependency"
        payload = b"authored public dependency"
        entry = {"url": "https://example.org/dependency", "sha256": hashlib.sha256(payload).hexdigest()}
        with patch.object(macos_setup.urllib.request, "urlopen", return_value=io.BytesIO(payload)) as fetch:
            macos_setup.download(entry, destination)
            macos_setup.download(entry, destination)
            fetch.assert_called_once()
        with patch.object(macos_setup.urllib.request, "urlopen", return_value=io.BytesIO(b"bad")):
            with self.assertRaisesRegex(RuntimeError, "Checksum mismatch"):
                macos_setup.download({**entry, "sha256": "0" * 64}, destination)
        self.assertEqual(destination.read_bytes(), payload)

    def test_angle_loader_link_uses_the_current_dependency_tree(self):
        angle = self.root / "angle/dist"
        for name in ("EGL", "GLESv2"):
            library = angle / f"{name}.xcframework/macos-arm64/lib{name}.framework/lib{name}"
            library.parent.mkdir(parents=True)
            library.write_bytes(b"authored library")
        companion = angle / "EGL.xcframework/macos-arm64/libEGL.framework/libGLESv2.dylib"
        gles = angle / "GLESv2.xcframework/macos-arm64/libGLESv2.framework/libGLESv2"
        macos_setup.prepare_angle_distribution(angle)
        self.assertFalse(companion.readlink().is_absolute())
        self.assertEqual(companion.resolve(), gles.resolve())
        macos_setup.prepare_angle_distribution(angle)  # Setup remains repeatable.
        companion.unlink()
        companion.symlink_to(self.root / "stale-checkout/libGLESv2")
        macos_setup.prepare_angle_distribution(angle)
        self.assertEqual(companion.resolve(), gles.resolve())
        self.assertFalse(companion.readlink().is_absolute())

    def test_guest_adapter_applies_rebase_before_machine_code(self):
        with patch("sys.argv", ["macos_guest_cc.py", "-S", "fixture.c", "-o", "fixture.s"]), \
                patch.object(macos_guest_cc.subprocess, "run") as run:
            self.assertEqual(macos_guest_cc.main(), 0)
        compile_ir, rebase, emit_asm = [call.args[0] for call in run.call_args_list]
        self.assertIn("-DHALO_MACOS=1", compile_ir)
        self.assertIn("-emit-llvm", compile_ir)
        self.assertIn("-passes=halo-rebase,verify", rebase)
        self.assertIn("-mtriple=arm64_32-apple-watchos", emit_asm)
        self.assertIn("fixture.rebased.ll", emit_asm)

    def test_configure_keeps_desktop_gles_and_selects_macos_guest(self):
        captured = []
        def generate(writer, settings):
            captured.append(settings)
            writer.build("macos_guest", "phony")
        with working_directory(self.root), \
                patch("sys.argv", [str(ROOT / "configure.py"), "--macos", "--gles", "--pgo", "off"]), \
                patch("tools.linux_build.generate_linux_build"), \
                patch("tools.windows_build.generate_windows_build"), \
                patch("tools.android_build.generate_android_build", side_effect=generate):
            runpy.run_path(str(ROOT / "configure.py"), run_name="__main__")
        self.assertTrue(captured[0].port_gles)
        self.assertTrue(captured[0].android_guest_only)
        self.assertEqual(captured[0].android_guest_cc, "tools/macos_guest_cc.py")
        self.assertIn("default macos_guest", (self.root / "build.ninja").read_text())

    def test_desktop_configuration_retains_compiler_and_gles_options(self):
        captured = []
        def generate(writer, settings):
            captured.append(settings)
            writer.build("linux", "phony")
        with working_directory(self.root), \
                patch("sys.argv", [str(ROOT / "configure.py"), "--gles", "--portable", "--lto", "thin",
                                   "--linux-cc", "fixture-clang", "--android-guest-cc", "fixture-arm-clang"]), \
                patch("tools.linux_build.generate_linux_build", side_effect=generate), \
                patch("tools.windows_build.generate_windows_build") as windows, \
                patch("tools.android_build.generate_android_build") as android:
            runpy.run_path(str(ROOT / "configure.py"), run_name="__main__")
        settings = captured[0]
        self.assertTrue(settings.port_gles)
        self.assertTrue(settings.port_portable)
        self.assertEqual(settings.port_lto, "thin")
        self.assertEqual(settings.linux_cc, "fixture-clang")
        self.assertEqual(settings.android_guest_cc, "fixture-arm-clang")
        self.assertFalse(settings.macos)
        self.assertFalse(settings.android_guest_only)
        # All generators receive the same preserved configuration.
        self.assertIs(windows.call_args.args[1], settings)
        self.assertIs(android.call_args.args[1], settings)
        self.assertNotIn("default macos_guest", (self.root / "build.ninja").read_text())

    def test_android_graph_keeps_ndk_host_and_runtime_library(self):
        ndk = self.root / "ndk"
        ndk.mkdir()
        settings = SimpleNamespace(android_ndk=ndk, android_guest_cc="fixture-arm-clang", port_pgo="off")
        for platform, toolchain in (("linux", "linux-x86_64"), ("darwin", "darwin-x86_64")):
            output = io.StringIO()
            with self.subTest(platform=platform), working_directory(ROOT), \
                    patch.object(android_build, "fetch_third_party"), \
                    patch.object(android_build.sys, "platform", platform), \
                    patch.object(android_build, "_musl_sources", return_value=[]), \
                    patch.object(android_build, "game_sources", return_value=[Path("source/game/game.c")]):
                android_build.generate_android_build(ninja_syntax.Writer(output), settings)
                graph = re.sub(r"\$\n\s*", "", output.getvalue())
                self.assertIn(f"{ndk}/toolchains/llvm/prebuilt/{toolchain}/bin/aarch64-linux-android28-clang", graph)
                self.assertIn("android_guest_cc = fixture-arm-clang", graph)
                self.assertIn("rule android_host_link", graph)
                self.assertIn("rule android_sdl3", graph)
                self.assertIn("$$($android_host_cc -print-libgcc-file-name)", graph)
                self.assertIn("build android: phony", graph)
                self.assertNotIn("macos_rebase_plugin", graph)
                self.assertNotIn("tools/macos_guest_cc.py", graph)

    def test_macos_graph_uses_upstream_game_headers_without_ndk_host(self):
        llvm = self.root / "llvm"
        headers = self.root / "headers"
        for path in (llvm / "llvm-ar", llvm / "ld.lld", headers / "GLES3/gl32.h",
                     headers / "GLES2/gl2ext.h", headers / "KHR/khrplatform.h"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        settings = SimpleNamespace(macos=True, android_guest_only=True,
                                   android_guest_llvm_bin=llvm, android_guest_gl_include=headers,
                                   android_guest_cc="tools/macos_guest_cc.py", port_pgo="off")
        output = io.StringIO()
        with working_directory(ROOT), patch.object(android_build, "fetch_third_party"), \
                patch.object(android_build, "_find_ndk", return_value=None), \
                patch.object(android_build, "_musl_sources", return_value=[]), \
                patch.object(android_build, "game_sources", return_value=[Path("source/game/game.c")]):
            android_build.generate_android_build(ninja_syntax.Writer(output), settings)
        graph = re.sub(r"\$\n\s*", "", output.getvalue())
        self.assertIn("build macos_guest: phony build/macos/halo_guest.elf", graph)
        self.assertIn("-iquote port/linux/game", graph)
        self.assertIn("-DHALO_ANDROID=1", graph)
        self.assertIn("tools/macos_guest_cc.py", graph)
        self.assertIn("port/macos/compiler/guest_rebase.cpp", graph)
        self.assertNotIn("rule android_host_link", graph)
        self.assertNotIn("rule android_sdl3", graph)
        self.assertNotIn("port/ios", graph)
        self.assertNotIn("-print-libgcc-file-name", graph)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Build the native Apple Silicon host, rebased game, and local .app bundle."""
import argparse
from datetime import datetime, timezone
import hashlib
import base64
import json
import os
from pathlib import Path
import plistlib
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.linux_build import MINIUPNPC_DEFINES, MINIUPNPC_DIR, miniupnpc_sources
from tools.macos_menu_icon import render as render_menu_icon
from tools.macos_setup import prepare_angle_distribution
from tools.macos_sparkle import setup_sparkle, DIRECTORY as SPARKLE_DIRECTORY
BUILD = ROOT / "build/macos"
LLVM = Path(os.environ.get("HALO_MACOS_LLVM_BIN", "/opt/homebrew/opt/llvm@22/bin"))
SDL = Path(os.environ.get("HALO_MACOS_SDL_PREFIX", "/opt/homebrew/opt/sdl3"))
ANGLE = Path(os.environ.get("HALO_MACOS_ANGLE_DIR", str(BUILD / "angle/dist")))
GL = BUILD / "toolchain/gl"
APP_ICON = "AppIcon.icns"
APP_VERSION = "0.1.0"
APP_BUILD = "1"


def run(*args):
    subprocess.run([str(arg) for arg in args], cwd=ROOT, check=True)


def require(path):
    if not path.exists():
        raise RuntimeError(f"Missing build dependency: {path}. See port/macos/README.md.")
    return path


def build_plugin():
    BUILD.mkdir(parents=True, exist_ok=True)
    require(LLVM / "llvm-config")
    flags = shlex.split(subprocess.check_output(
        [LLVM / "llvm-config", "--cxxflags", "--ldflags", "--libs", "core", "passes"], text=True))
    run(LLVM / "clang++", "-shared", "-fPIC", "port/macos/compiler/guest_rebase.cpp",
        "-o", BUILD / "guest_rebase.dylib", *flags)


def build_host():
    sparkle = setup_sparkle()
    prepare_angle_distribution(ANGLE)
    obj_dir = BUILD / "host-obj"
    obj_dir.mkdir(parents=True, exist_ok=True)
    frameworks = [ANGLE / f"{name}.xcframework/macos-arm64" for name in ("EGL", "GLESv2")]
    for name, directory in zip(("libEGL", "libGLESv2"), frameworks):
        require(directory / f"{name}.framework" / name)
    flags = ["-arch", "arm64", "-mmacosx-version-min=14.0", "-O2", "-g", "-DHALO_MACOS=1", "-D_DARWIN_C_SOURCE",
             "-Wall", "-Wextra", "-Wno-unused-function", "-Wno-unused-parameter",
             "-I.", "-Iport/macos/host", "-Iport/macos/native", "-Iport/android/include", "-Iport/linux/src",
             f"-I{SDL / 'include'}", f"-I{GL}",
             f"-I{MINIUPNPC_DIR / 'include'}", f"-I{MINIUPNPC_DIR / 'src'}", *MINIUPNPC_DEFINES]
    sources = sorted((ROOT / "port/macos/host").glob("*.c"))
    sources += sorted((ROOT / "port/macos/native").glob("*.m"))
    sources += [ROOT / "port/linux/src/xiso.c"]
    sources += miniupnpc_sources()
    sources += [BUILD / "host/host_import_table.c", ROOT / "port/macos/host/entry.s"]
    objects = []
    for source in sources:
        obj = obj_dir / (source.name + ".o")
        native_flags = ["-fobjc-arc", "-fblocks", f"-F{sparkle.parent}"] if source.suffix == ".m" else []
        run("clang", *flags, *native_flags, "-c", source, "-o", obj)
        objects.append(obj)
    run("clang", "-arch", "arm64", "-mmacosx-version-min=14.0", *objects, f"-L{SDL / 'lib'}", "-lSDL3",
        *(f"-F{directory}" for directory in frameworks),
        "-framework", "libEGL", "-framework", "libGLESv2",
        f"-F{sparkle.parent}", "-framework", "Sparkle", "-framework", "Cocoa",
        f"-Wl,-rpath,{sparkle.parent}",
        *(f"-Wl,-rpath,{directory}" for directory in frameworks), "-o", BUILD / "halo")


def package_icon(resources):
    source = require(ROOT / "port/macos/AppIcon.png")
    with tempfile.TemporaryDirectory(prefix="halo-macos-icon-") as temporary:
        iconset = Path(temporary) / "AppIcon.iconset"
        iconset.mkdir()
        images = {}
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                pixels = size * scale
                suffix = "@2x" if scale == 2 else ""
                target = iconset / f"icon_{size}x{size}{suffix}.png"
                subprocess.run(["/usr/bin/sips", "-z", str(pixels), str(pixels),
                                str(source), "--out", str(target)],
                               check=True, stdout=subprocess.DEVNULL)
                images[(size, scale)] = target.read_bytes()
        # PNG-backed ICNS representations avoid iconutil's rejection of valid
        # RGB-only iconsets on some macOS SDKs; keep the existing icon artwork.
        types = {(16, 1): b"icp4", (16, 2): b"ic11", (32, 1): b"icp5", (32, 2): b"ic12",
                 (128, 1): b"ic07", (128, 2): b"ic13", (256, 1): b"ic08", (256, 2): b"ic14",
                 (512, 1): b"ic09", (512, 2): b"ic10"}
        chunks = b"".join(types[size] + struct.pack(">I", len(png) + 8) + png for size, png in images.items())
        (resources / APP_ICON).write_bytes(b"icns" + struct.pack(">I", len(chunks) + 8) + chunks)


def minimum_macos_version(binaries):
    output = subprocess.check_output(["otool", "-l", *map(str, binaries)], text=True)
    versions = []
    for command in re.split(r"Load command \d+", output):
        field = "minos" if "cmd LC_BUILD_VERSION" in command else "version" if "cmd LC_VERSION_MIN_MACOSX" in command else None
        if field:
            match = re.search(r"^\s+" + field + r" (\d+(?:\.\d+){1,2})\s*$", command, re.MULTILINE)
            if match:
                versions.append(match[1])
    return max(["14.0", *versions], key=lambda value: tuple(map(int, value.split("."))))


def update_configuration(config):
    feed, key = config.get("feed_url"), config.get("public_update_key")
    if not feed and not key:
        return {}
    url = urlparse(feed or "")
    try:
        valid_key = len(base64.b64decode(key or "", validate=True)) == 32
    except (ValueError, TypeError):
        valid_key = False
    if url.scheme != "https" or not url.hostname or url.username or url.password or not valid_key:
        raise RuntimeError("Configure an HTTPS feed and its matching 32-byte public Ed25519 key together")
    return {"SUFeedURL": feed, "SUPublicEDKey": key, "SUEnableAutomaticChecks": True,
            "SUVerifyUpdateBeforeExtraction": True, "SURequireSignedFeed": True,
            "SUScheduledCheckInterval": 86400}


def github_repository(configuration, repository=None, *, release=False):
    """Choose a public repository slug without allowing URLs or path traversal."""
    configured = configuration.get("github_repository")
    selected = repository if repository is not None else configured
    if (not isinstance(selected, str) or not re.fullmatch(
            r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_.-]{1,100}", selected)
            or selected.split("/", 1)[1] in (".", "..")):
        raise RuntimeError("Set a GitHub repository as owner/name")
    if release and (not isinstance(configured, str) or selected.lower() != configured.lower()):
        raise RuntimeError("Signed releases must use the repository in port/macos/release-config.json")
    return selected


def package(data_root, *, sign_identity="-", release=False, version=APP_VERSION, build=APP_BUILD, repository=None):
    configuration = json.loads((ROOT / "port/macos/release-config.json").read_text())
    repository = github_repository(configuration, repository, release=release)
    if release:
        if not update_configuration(configuration):
            raise RuntimeError("Set Halo's update feed and public key before creating a release")
        if not sign_identity.startswith("Developer ID Application:"):
            raise RuntimeError("A release needs an explicit Developer ID Application signing identity")
    destination = BUILD / "Halo CE Universal.app"
    with tempfile.TemporaryDirectory(prefix=".halo-package-", dir=BUILD) as temporary:
        staged = Path(temporary) / destination.name
        package_into(staged, data_root, sign_identity=sign_identity, release=release, version=version, build=build, repository=repository)
        # A fresh bundle prevents old development resources entering a release.
        # Preserve the previous build, including a running executable's inode.
        backup = None
        if destination.exists():
            backup = BUILD / "app-backups.noindex" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
            backup.mkdir(parents=True)
            destination.rename(backup / (destination.name + ".backup"))
        try:
            staged.rename(destination)
        except OSError:
            if backup:
                (backup / (destination.name + ".backup")).rename(destination)
            raise
    print(f"Built {destination}")


def package_into(app, data_root, *, sign_identity, release, version, build, repository=None):
    configuration = json.loads((ROOT / "port/macos/release-config.json").read_text())
    repository = github_repository(configuration, repository, release=release)
    contents = app / "Contents"
    macos = contents / "MacOS"
    frameworks = contents / "Frameworks"
    resources = contents / "Resources"
    for directory in (macos, frameworks, resources):
        directory.mkdir(parents=True, exist_ok=True)
    executable = macos / "halo"
    # Keep a running copy's executable inode intact during a local rebuild.
    if executable.exists():
        executable.unlink()
    shutil.copy2(BUILD / "halo", executable)
    shutil.copy2(BUILD / "halo_guest.elf", resources / "halo_guest.elf")
    sdl = frameworks / "libSDL3.0.dylib"
    if sdl.exists():
        sdl.unlink()
    shutil.copy2(require(SDL / "lib/libSDL3.0.dylib"), sdl)
    run("install_name_tool", "-change", str(SDL / "lib/libSDL3.0.dylib"),
        "@rpath/libSDL3.0.dylib", executable)
    run("install_name_tool", "-id", "@rpath/libSDL3.0.dylib", sdl)
    for name in ("EGL", "GLESv2"):
        directory = ANGLE / f"{name}.xcframework/macos-arm64"
        source = directory / f"lib{name}.framework"
        old_framework = frameworks / source.name
        if old_framework.exists():
            shutil.rmtree(old_framework)
        target = frameworks / f"lib{name}.dylib"
        if target.exists():
            target.unlink()
        shutil.copy2(source / f"lib{name}", target)
        target.chmod(0o755)
        run("install_name_tool", "-change", f"@rpath/lib{name}.framework/lib{name}",
            f"@rpath/lib{name}.dylib", executable)
        run("install_name_tool", "-id", f"@rpath/lib{name}.dylib", target)
        run("install_name_tool", "-delete_rpath", str(directory), executable)
    run("install_name_tool", "-add_rpath", "@executable_path/../Frameworks", executable)
    sparkle_source = setup_sparkle()
    sparkle = frameworks / "Sparkle.framework"
    if sparkle.exists():
        shutil.rmtree(sparkle)
    shutil.copytree(sparkle_source, sparkle, symlinks=True)
    run("install_name_tool", "-delete_rpath", str(sparkle_source.parent), executable)
    # Store the independently supplied data location as a configuration file;
    # external symlinks would invalidate a strictly signed app bundle.
    data_link = resources / "GameData"
    if data_link.is_symlink():
        data_link.unlink()
    legacy_path = resources / "GameDataPath.txt"
    if data_root is not None and not release:
        legacy_path.write_text(str(require(data_root.resolve())) + "\n")
    elif legacy_path.exists():
        legacy_path.unlink()
    render_menu_icon(ROOT / "port/macos/Helmet.svg", resources / "Helmet.pdf")
    package_icon(resources)
    info = {
        "CFBundleExecutable": "halo", "CFBundleIdentifier": "local.halo.ce-universal",
        "CFBundleName": "Halo CE Universal", "CFBundleDisplayName": "Halo CE Universal",
        "CFBundleIconFile": APP_ICON,
        "CFBundlePackageType": "APPL", "CFBundleShortVersionString": version,
        "CFBundleVersion": build, "LSMinimumSystemVersion": minimum_macos_version([
            executable, sdl, frameworks / "libEGL.dylib", frameworks / "libGLESv2.dylib", sparkle / "Sparkle"]),
        "CFBundleURLTypes": [{"CFBundleURLName": "Halo multiplayer invite",
                              # Match the shared discord.application_id default.
                              "CFBundleURLSchemes": ["halo", "discord-1553978809840050229"],
                              "CFBundleTypeRole": "Viewer"}],
        "NSLocalNetworkUsageDescription": "Connect to players hosting Halo multiplayer games.",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "Local experimental Apple Silicon port",
    }
    configuration = json.loads((ROOT / "port/macos/release-config.json").read_text())
    info["HaloMacDownloadsURL"] = f"https://github.com/{repository}/actions/workflows/macos-dmg.yml"
    if release:
        updates = update_configuration(configuration)
        if not updates:
            raise RuntimeError("Set Halo's update feed and public key before creating a release")
        if sign_identity == "-":
            raise RuntimeError("A release needs an explicit Developer ID Application signing identity")
        info.update(updates)
    with (contents / "Info.plist").open("wb") as stream:
        plistlib.dump(info, stream)
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                           text=True, stderr=subprocess.DEVNULL).strip()
        if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip():
            revision += " (local changes)"
    except (OSError, subprocess.CalledProcessError):
        revision = "unknown"
    guest_hash = hashlib.sha256((resources / "halo_guest.elf").read_bytes()).hexdigest()
    (resources / "BuildInfo.txt").write_text(
        f"Halo CE Universal {version} (build {build})\n"
        f"Repository: {repository}\nSource: {revision}\nGuest SHA-256: {guest_hash}\n")
    licenses = resources / "Licenses"
    licenses.mkdir(exist_ok=True)
    for source, name in (
        (ROOT / "LICENSE.md", "Project.txt"),
        (ROOT / "port/assets/fonts/Overpass-OFL.txt", "Overpass-OFL.txt"),
        (ROOT / "port/assets/fonts/OpenCE-OFL.txt", "OpenCE-OFL.txt"),
        (ROOT / "port/assets/fonts/Newtown-LICENSE.txt", "Newtown-LICENSE.txt"),
        (ROOT / "port/macos/licenses/ANGLE.txt", "ANGLE.txt"),
        (SDL / "share/licenses/SDL3/LICENSE.txt", "SDL3.txt"),
        (ROOT / "build/android/third_party/musl-1.2.5/COPYRIGHT", "musl.txt"),
        (ROOT / "port/third_party/kcp/LICENSE", "KCP.txt"),
        (ROOT / "port/third_party/miniupnpc/LICENSE", "miniupnpc.txt"),
        (ROOT / "port/third_party/extract-xiso/LICENSE.TXT", "extract-xiso.txt"),
        (ROOT / "port/third_party/tomlc17/LICENSE", "tomlc17.txt"),
        (ROOT / "port/third_party/mbedtls/LICENSE", "mbedtls.txt"),
        (SPARKLE_DIRECTORY / "LICENSE", "Sparkle.txt"),
    ):
        if source.exists():
            shutil.copy2(source, licenses / name)
    # Sign nested helpers before the framework and app. Development stays ad-hoc.
    signing = ["--force", "--sign", sign_identity]
    if release:
        signing += ["--options", "runtime", "--timestamp"]
    sparkle_version = sparkle / "Versions/B"
    for helper in ("XPCServices/Installer.xpc", "XPCServices/Downloader.xpc", "Autoupdate", "Updater.app"):
        run("codesign", *signing, "--preserve-metadata=entitlements", sparkle_version / helper)
    run("codesign", *signing, sparkle)
    for binary in (sdl, frameworks / "libGLESv2.dylib", frameworks / "libEGL.dylib"):
        run("codesign", *signing, binary)
    app_signing = [*signing]
    if release:
        app_signing += ["--entitlements", ROOT / "port/macos/host.entitlements"]
    run("codesign", *app_signing, app)
    run("codesign", "--verify", "--deep", "--strict", app)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin-only", action="store_true")
    parser.add_argument("--host-only", action="store_true")
    parser.add_argument("--data-root", type=Path, help="Development-only external game data directory; never copied into the app")
    parser.add_argument("--no-data-path", action="store_true", help="First launch asks for independently supplied game data")
    parser.add_argument("--release", action="store_true", help="Developer ID signed, hardened runtime build; does not notarize or publish")
    parser.add_argument("--sign-identity", default="-")
    parser.add_argument("--version", default=APP_VERSION)
    parser.add_argument("--build-number", default=APP_BUILD)
    parser.add_argument("--repository", help="GitHub owner/name for download links (default: checked-in release configuration)")
    parser.add_argument("--jobs", type=int, default=min(os.cpu_count() or 4, 6))
    args = parser.parse_args()
    os.chdir(ROOT)
    repository = github_repository(json.loads((ROOT / "port/macos/release-config.json").read_text()),
                                   args.repository, release=args.release)
    if args.release:
        if not update_configuration(json.loads((ROOT / "port/macos/release-config.json").read_text())):
            raise RuntimeError("Choose release hosting and configure the public update key first")
        if not args.sign_identity.startswith("Developer ID Application:"):
            raise RuntimeError("A release needs an explicit Developer ID Application signing identity")
    if args.plugin_only:
        build_plugin()
        return
    if not args.host_only:
        llvm_bin = BUILD / "toolchain/bin"
        require(llvm_bin / "llvm-ar")
        require(llvm_bin / "ld.lld")
        require(GL / "GLES3/gl32.h")
        run(sys.executable, "configure.py", "--macos", "--android-guest-llvm-bin", llvm_bin,
            "--android-guest-gl-include", GL, "--pgo", "off")
        ninja = shutil.which("ninja") or str(BUILD / "toolchain/venv/bin/ninja")
        run(ninja, "-j", args.jobs, "macos_guest")
    build_host()
    package(None if args.no_data_path or args.release else args.data_root,
            sign_identity=args.sign_identity, release=args.release, version=args.version, build=args.build_number,
            repository=repository)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f"macOS build failed: {error}", file=sys.stderr)
        sys.exit(1)

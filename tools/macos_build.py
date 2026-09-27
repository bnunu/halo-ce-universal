#!/usr/bin/env python3
"""Build the native Apple Silicon host, rebased game, and local .app bundle."""
import argparse
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build/macos"
LLVM = Path(os.environ.get("HALO_MACOS_LLVM_BIN", "/opt/homebrew/opt/llvm/bin"))
SDL = Path(os.environ.get("HALO_MACOS_SDL_PREFIX", "/opt/homebrew/opt/sdl3"))
ANGLE = Path(os.environ.get("HALO_MACOS_ANGLE_DIR", str(BUILD / "angle/dist")))
GL = BUILD / "toolchain/gl"


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
    obj_dir = BUILD / "host-obj"
    obj_dir.mkdir(parents=True, exist_ok=True)
    frameworks = [ANGLE / f"{name}.xcframework/macos-arm64" for name in ("EGL", "GLESv2")]
    for name, directory in zip(("libEGL", "libGLESv2"), frameworks):
        require(directory / f"{name}.framework" / name)
    # EGL's loader also uses this name beside the EGL binary.
    companion = frameworks[0] / "libEGL.framework/libGLESv2.dylib"
    if companion.is_symlink():
        companion.unlink()
    if not companion.exists():
        companion.symlink_to(frameworks[1] / "libGLESv2.framework/libGLESv2")
    flags = ["-arch", "arm64", "-O2", "-g", "-DHALO_MACOS=1", "-D_DARWIN_C_SOURCE",
             "-Wall", "-Wextra", "-Wno-unused-function", "-Wno-unused-parameter",
             "-I.", "-Iport/macos/host", "-Iport/android/include", "-Iport/linux/src",
             f"-I{SDL / 'include'}", f"-I{GL}"]
    sources = sorted((ROOT / "port/macos/host").glob("*.c"))
    sources += [BUILD / "host/host_import_table.c", ROOT / "port/macos/host/entry.s"]
    objects = []
    for source in sources:
        obj = obj_dir / (source.name + ".o")
        run("clang", *flags, "-c", source, "-o", obj)
        objects.append(obj)
    run("clang", *objects, f"-L{SDL / 'lib'}", "-lSDL3",
        *(f"-F{directory}" for directory in frameworks),
        "-framework", "libEGL", "-framework", "libGLESv2",
        *(f"-Wl,-rpath,{directory}" for directory in frameworks), "-o", BUILD / "halo")


def package(data_root):
    app = BUILD / "Halo CE Universal.app"
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
    # Store the independently supplied data location as a configuration file;
    # external symlinks would invalidate a strictly signed app bundle.
    data_link = resources / "GameData"
    if data_link.is_symlink():
        data_link.unlink()
    (resources / "GameDataPath.txt").write_text(str(require(data_root.resolve())) + "\n")
    info = {
        "CFBundleExecutable": "halo", "CFBundleIdentifier": "local.halo.ce-universal",
        "CFBundleName": "Halo CE Universal", "CFBundleDisplayName": "Halo CE Universal",
        "CFBundlePackageType": "APPL", "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "1", "LSMinimumSystemVersion": "14.0",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "Local experimental Apple Silicon port",
    }
    with (contents / "Info.plist").open("wb") as stream:
        plistlib.dump(info, stream)
    licenses = resources / "Licenses"
    licenses.mkdir(exist_ok=True)
    for source, name in (
        (ROOT / "LICENSE.md", "Project.txt"),
        (ROOT / "libs/d3d8/LICENSE.GPL-3.0", "D3D8-GPL-3.0.txt"),
        (ROOT / "port/macos/licenses/ANGLE.txt", "ANGLE.txt"),
        (SDL / "share/licenses/SDL3/LICENSE.txt", "SDL3.txt"),
        (ROOT / "build/android/third_party/musl-1.2.5/COPYRIGHT", "musl.txt"),
    ):
        if source.exists():
            shutil.copy2(source, licenses / name)
    # Local ad-hoc signing requires neither an account nor an entitlement.
    for binary in (sdl, frameworks / "libGLESv2.dylib", frameworks / "libEGL.dylib"):
        run("codesign", "--force", "--sign", "-", binary)
    run("codesign", "--force", "--sign", "-", app)
    run("codesign", "--verify", "--deep", "--strict", app)
    print(f"Built {app}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin-only", action="store_true")
    parser.add_argument("--host-only", action="store_true")
    parser.add_argument("--data-root", type=Path, default=ROOT / "assets")
    parser.add_argument("--jobs", type=int, default=min(os.cpu_count() or 4, 6))
    args = parser.parse_args()
    os.chdir(ROOT)
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
    package(args.data_root)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f"macOS build failed: {error}", file=sys.stderr)
        sys.exit(1)

#!/usr/bin/env python3
"""Run compiled ABI probes on Apple Silicon after building macos_guest."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/macos/tests"
LLVM = Path(os.environ.get("HALO_MACOS_LLVM_BIN", "/opt/homebrew/opt/llvm/bin"))


def run(*args):
    subprocess.run([str(arg) for arg in args], cwd=ROOT, check=True, timeout=60)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    run(sys.executable, "tools/macos_guest_cc.py", "--target=arm64_32-apple-watchos",
        "-mcpu=cortex-a53", "-O2", "-fno-stack-protector", "-fno-unwind-tables",
        "-fno-asynchronous-unwind-tables", "-S", "port/macos/tests/guest_memory.c",
        "-o", OUT / "guest.darwin.s")
    run(sys.executable, "tools/android_asm_convert.py", OUT / "guest.darwin.s", OUT / "guest.s")
    run(LLVM / "clang", "--target=aarch64-linux-android", "-c", OUT / "guest.s", "-o", OUT / "guest.o")
    run("build/macos/toolchain/bin/ld.lld", "-m", "aarch64linux", "-static", "-nostdlib",
        "-Ttext=0x88000000", "-e", "guest_test", OUT / "guest.o",
        "build/macos/guest/libguestc.a", "-o", OUT / "guest.elf")
    run("clang", "-arch", "arm64", "-O2", "-Wall", "port/macos/tests/memory_host.c",
        "-o", OUT / "memory_host")
    run(OUT / "memory_host", OUT / "guest.elf")
    run("clang", "-arch", "arm64", "-O2", "-Wall", "-DHALO_MACOS=1",
        "-I.", "-Iport/macos/host", "-Iport/android/include",
        "port/macos/tests/host_memory.c", "port/macos/host/host_memory.c",
        "port/macos/host/host_syscall.c", "port/macos/host/host_errno.c",
        "-o", OUT / "host_memory")
    run(OUT / "host_memory")
    sdl = Path(os.environ.get("HALO_MACOS_SDL_PREFIX", "/opt/homebrew/opt/sdl3"))
    angle = Path(os.environ.get("HALO_MACOS_ANGLE_DIR", str(ROOT / "build/macos/angle/dist")))
    egl = angle / "EGL.xcframework/macos-arm64"
    run("clang", "-arch", "arm64", "-O2", "-Wall", "-DHALO_MACOS=1",
        "-Iport/macos/host", "-Iport/android/include", f"-I{sdl / 'include'}",
        "-Ibuild/macos/toolchain/gl", "port/macos/tests/audio_bridge.c",
        "port/macos/host/host_sdl.c", f"-L{sdl / 'lib'}", "-lSDL3",
        f"-F{egl}", "-framework", "libEGL", f"-Wl,-rpath,{egl}", "-o", OUT / "audio_bridge")
    run(OUT / "audio_bridge")


if __name__ == "__main__":
    main()

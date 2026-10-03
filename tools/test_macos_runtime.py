#!/usr/bin/env python3
"""Run compiled ABI probes on Apple Silicon after building macos_guest."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.linux_build import MINIUPNPC_DEFINES, MINIUPNPC_DIR, miniupnpc_sources

OUT = ROOT / "build/macos/tests"
LLVM = Path(os.environ.get("HALO_MACOS_LLVM_BIN", "/opt/homebrew/opt/llvm@22/bin"))


def run(*args):
    subprocess.run([str(arg) for arg in args], cwd=ROOT, check=True, timeout=60)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--standalone', action='store_true',
                        help='Use authored memory routines instead of the full game libc (source-only CI)')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    run(sys.executable, "tools/macos_guest_cc.py", "--target=arm64_32-apple-watchos",
        "-mcpu=cortex-a53", "-O2", "-fno-stack-protector", "-fno-unwind-tables",
        "-fno-asynchronous-unwind-tables", "-S", "port/macos/tests/guest_memory.c",
        "-o", OUT / "guest.darwin.s")
    run(sys.executable, "tools/android_asm_convert.py", OUT / "guest.darwin.s", OUT / "guest.s")
    run(LLVM / "clang", "--target=aarch64-linux-android", "-c", OUT / "guest.s", "-o", OUT / "guest.o")
    libc = ROOT / 'build/macos/guest/libguestc.a'
    if args.standalone:
        run(sys.executable, "tools/macos_guest_cc.py", "--target=arm64_32-apple-watchos",
            "-mcpu=cortex-a53", "-O2", "-ffreestanding", "-fno-stack-protector", "-S",
            "port/macos/tests/guest_libc.c", "-o", OUT / "libc.darwin.s")
        run(sys.executable, "tools/android_asm_convert.py", OUT / "libc.darwin.s", OUT / "libc.s")
        run(LLVM / "clang", "--target=aarch64-linux-android", "-c", OUT / "libc.s", "-o", OUT / "libc.o")
        libc = OUT / 'libc.o'
    run("build/macos/toolchain/bin/ld.lld", "-m", "aarch64linux", "-static", "-nostdlib",
        "-Ttext=0x88000000", "-e", "guest_test", OUT / "guest.o",
        libc, "-o", OUT / "guest.elf")
    run("clang", "-arch", "arm64", "-O2", "-Wall", "port/macos/tests/memory_host.c",
        "-o", OUT / "memory_host")
    run(OUT / "memory_host", OUT / "guest.elf")
    run("clang", "-arch", "arm64", "-O2", "-Wall", "-DHALO_MACOS=1",
        "-I.", "-Iport/macos/host", "-Iport/android/include",
        "port/macos/tests/host_memory.c", "port/macos/host/host_memory.c",
        "port/macos/host/host_syscall.c", "port/macos/host/host_errno.c",
        "-o", OUT / "host_memory")
    run(OUT / "host_memory")
    run("clang", "-arch", "arm64", "-O2", "-Wall", "-I.", "-Iport/linux/src",
        "port/macos/tests/host_network.c", "port/macos/host/posix_net.c",
        "port/macos/host/host_discord.c",
        "-o", OUT / "host_network")
    run(OUT / "host_network")
    run("clang", "-arch", "arm64", "-O2", "-Wall", "-DHALO_MACOS=1", "-D_DARWIN_C_SOURCE",
        "-I.", "-Iport/linux/src", f"-I{MINIUPNPC_DIR / 'include'}", f"-I{MINIUPNPC_DIR / 'src'}",
        *MINIUPNPC_DEFINES, "port/macos/tests/upnp_port.c", "port/macos/host/posix_net.c",
        "port/macos/host/host_discord.c", *miniupnpc_sources(), "-o", OUT / "upnp_port")
    run(OUT / "upnp_port")
    run("clang", "-arch", "arm64", "-O2", "-Wall", "-Wextra", "-I.", "-Iport/linux/src",
        "port/macos/tests/discord_bridge.c", "port/macos/host/posix_net.c",
        "port/macos/host/host_discord.c", "-o", OUT / "discord_bridge")
    run(OUT / "discord_bridge")
    run("clang", "-arch", "arm64", "-O2", "-Wall", "-Wextra",
        "-Iport/macos/host", "-Iport/android/include",
        "port/macos/tests/invite_bridge.c", "port/macos/host/host_invite.c",
        "-o", OUT / "invite_bridge")
    run(OUT / "invite_bridge")
    sdl = Path(os.environ.get("HALO_MACOS_SDL_PREFIX", "/opt/homebrew/opt/sdl3"))
    angle = Path(os.environ.get("HALO_MACOS_ANGLE_DIR", str(ROOT / "build/macos/angle/dist")))
    egl = angle / "EGL.xcframework/macos-arm64"
    run("clang", "-arch", "arm64", "-O2", "-Wall", "-DHALO_MACOS=1",
        "-Iport/macos/host", "-Iport/android/include", f"-I{sdl / 'include'}",
        "-Ibuild/macos/toolchain/gl", "port/macos/tests/audio_bridge.c",
        "port/macos/host/host_sdl.c", "port/macos/host/host_invite.c", f"-L{sdl / 'lib'}", "-lSDL3",
        f"-F{egl}", "-framework", "libEGL", f"-Wl,-rpath,{egl}", "-o", OUT / "audio_bridge")
    run(OUT / "audio_bridge")


if __name__ == "__main__":
    main()

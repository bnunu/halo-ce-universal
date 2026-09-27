#!/usr/bin/env python3
"""Prepare public Mac build dependencies; never downloads game data or the XDK."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build/macos"


def download(entry, destination):
    if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() == entry["sha256"]:
        return
    print(f"Downloading {destination.name}", flush=True)
    with urllib.request.urlopen(entry["url"], timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise RuntimeError(f"Checksum mismatch for {destination.name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)


def main():
    manifest = json.loads((ROOT / "port/macos/dependencies.json").read_text())
    llvm = Path(os.environ.get("HALO_MACOS_LLVM_BIN", "/opt/homebrew/opt/llvm/bin"))
    version = subprocess.check_output([llvm / "llvm-config", "--version"], text=True).strip()
    if version.split(".")[0] != str(manifest["llvm_major"]):
        raise RuntimeError("The compiler pass requires LLVM 22")
    toolchain = BUILD / "toolchain"
    binary = toolchain / "bin"
    binary.mkdir(parents=True, exist_ok=True)
    ar = binary / "llvm-ar"
    if not ar.exists():
        ar.symlink_to(llvm / "llvm-ar")
    linker = binary / "ld.lld"
    lld = shutil.which("ld.lld")
    if not lld and Path("/opt/homebrew/opt/lld/bin/ld.lld").exists():
        lld = "/opt/homebrew/opt/lld/bin/ld.lld"
    if not linker.exists():
        if lld:
            linker.symlink_to(lld)
        else:
            uv = shutil.which("uv")
            if not uv:
                raise RuntimeError("Install Homebrew lld and ninja, or uv for the local Zig/LLD fallback")
            venv = toolchain / "venv"
            if not (venv / "bin/python").exists():
                subprocess.run([uv, "venv", str(venv)], check=True)
            subprocess.run([uv, "pip", "install", "--python", str(venv / "bin/python"),
                            "ninja==1.13.2", "ziglang==0.16.0"], check=True)
            zig = next(venv.glob("lib/python*/site-packages/ziglang/zig"))
            linker.write_text(f'#!/bin/sh\nexec {shlex.quote(str(zig))} ld.lld "$@"\n')
            linker.chmod(0o755)
    if not shutil.which("ninja") and not (toolchain / "venv/bin/ninja").exists():
        raise RuntimeError("Install ninja (for example: brew install ninja)")
    for entry in manifest["headers"]:
        download(entry, toolchain / "gl" / entry["path"])
    archive = BUILD / "angle/angle.zip"
    download(manifest["angle"], archive)
    if not (BUILD / "angle/dist/BUILD_INFO.txt").exists():
        with zipfile.ZipFile(archive) as package:
            package.extractall(BUILD / "angle")
    print(f"Mac build dependencies ready (LLVM {version})")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Setup failed: {error}", file=sys.stderr)
        sys.exit(1)

#!/usr/bin/env python3
"""Execute the signed-image ABI probe on Apple Silicon; no iPhone profile needed."""
import os
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/ios/probe'
LLVM = Path(os.environ.get('HALO_MACOS_LLVM_BIN', '/opt/homebrew/opt/llvm/bin'))
def run(*args):
    subprocess.run([str(a) for a in args], cwd=ROOT, check=True, timeout=60)
def main():
    OUT.mkdir(parents=True, exist_ok=True)
    objects = []
    for source in ('port/macos/tests/guest_memory.c', 'port/ios/tests/guest_libc.c'):
        base = OUT / Path(source).stem
        run(sys.executable, 'tools/ios_guest_cc.py', '--target=arm64_32-apple-watchos',
            '-mcpu=cortex-a53', '-O2', '-ffreestanding', '-fno-stack-protector', '-fno-unwind-tables',
            '-fno-asynchronous-unwind-tables', '-S', source, '-o', str(base) + '.darwin.s')
        run(sys.executable, 'tools/android_asm_convert.py', str(base) + '.darwin.s', str(base) + '.s')
        run(LLVM / 'clang', '--target=aarch64-linux-android', '-c', str(base) + '.s', '-o', str(base) + '.o')
        objects.append(str(base) + '.o')
    run('build/macos/toolchain/bin/ld.lld', '-m', 'aarch64linux', '-static', '-nostdlib',
        '-Ttext=0x88000000', '-e', 'guest_test', *objects, '-o', OUT / 'guest.elf')
    run(sys.executable, 'tools/ios_embed.py', OUT / 'guest.elf', OUT / 'embed')
    run('clang', '-arch', 'arm64', '-O2', f'-I{OUT / "embed"}',
        'port/ios/tests/signed_image.c', OUT / 'embed/guest_image.s', '-o', OUT / 'signed_image')
    run('codesign', '--force', '--sign', '-', OUT / 'signed_image')
    run(OUT / 'signed_image')
if __name__ == '__main__':
    main()

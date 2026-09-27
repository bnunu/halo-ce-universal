#!/usr/bin/env python3
"""Compile ILP32 game code for a separately signed iOS instruction image."""
import os
from pathlib import Path
import subprocess
import sys

def main():
    llvm = Path(os.environ.get('HALO_MACOS_LLVM_BIN', '/opt/homebrew/opt/llvm/bin'))
    args = sys.argv[1:]
    if '-S' not in args:
        return subprocess.call([str(llvm / 'clang'), *args])
    output_index = args.index('-o') + 1
    output = Path(args[output_index])
    ir = output.with_suffix('.ll')
    args[output_index] = str(ir)
    subprocess.run([llvm / 'clang', *args, '-emit-llvm', '-femulated-tls', '-DHALO_MACOS=1', '-DHALO_IOS=1'], check=True)
    rebased = ir.with_suffix('.rebased.ll')
    subprocess.run([llvm / 'opt', '-load-pass-plugin=build/ios/guest_rebase.dylib',
                    '-emulated-tls', '-passes=lower-emutls,halo-rebase-ios,verify', '-S', ir, '-o', rebased], check=True)
    subprocess.run([llvm / 'llc', '-O2', '-mtriple=arm64_32-apple-watchos',
                    '-aarch64-neon-syntax=generic', '-emulated-tls', rebased, '-o', output], check=True)
    return 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as error:
        sys.exit(error.returncode)

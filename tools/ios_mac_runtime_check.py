#!/usr/bin/env python3
"""Build the iOS signed-image runtime against Mac SDL for local diagnostics.

This validates the game ABI independently of UIKit and device signing.
It does not replace simulator or hardware validation.
"""
import os
from pathlib import Path
import subprocess
ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build/ios/mac-runtime-check'
def main():
    os.chdir(ROOT)
    BUILD.mkdir(parents=True, exist_ok=True)
    sources = [p for p in (ROOT / 'port/macos/host').glob('*.c') if p.name != 'host_loader.c']
    sources += [ROOT / 'port/ios/host/host_loader.c', ROOT / 'port/macos/host/entry.s',
                ROOT / 'build/ios/host/host_import_table.c', ROOT / 'build/ios/embed/guest_image.s']
    flags = ['-arch', 'arm64', '-O2', '-g', '-DHALO_MACOS=1', '-DHALO_IOS=1', '-DHALO_IOS_MAC_CHECK=1', '-D_DARWIN_C_SOURCE',
             '-I.', '-Iport/macos/host', '-Iport/android/include', '-Iport/linux/src',
             '-I/opt/homebrew/opt/sdl3/include', '-Ibuild/macos/toolchain/gl', '-Ibuild/ios/embed']
    objects = []
    for source in sources:
        obj = BUILD / (source.name + '.o')
        subprocess.run(['clang', *flags, '-c', str(source), '-o', str(obj)], check=True)
        objects.append(str(obj))
    link = ['clang', *objects, '-L/opt/homebrew/opt/sdl3/lib', '-lSDL3']
    for name in ('EGL', 'GLESv2'):
        directory = ROOT / f'build/macos/angle/dist/{name}.xcframework/macos-arm64'
        link += [f'-F{directory}', '-framework', f'lib{name}', f'-Wl,-rpath,{directory}']
    subprocess.run([*link, '-o', str(BUILD / 'halo')], check=True)
    subprocess.run(['codesign', '--force', '--sign', '-', str(BUILD / 'halo')], check=True)
    print(BUILD / 'halo')
if __name__ == '__main__':
    main()

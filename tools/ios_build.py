#!/usr/bin/env python3
"""Build the signed-code iOS port; game and SDK inputs remain local."""
import argparse
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build/ios'
LLVM = Path(os.environ.get('HALO_MACOS_LLVM_BIN', '/opt/homebrew/opt/llvm/bin'))
os.environ.setdefault('DEVELOPER_DIR', '/Applications/Xcode.app/Contents/Developer')

def run(*args, **kwargs):
    subprocess.run([str(a) for a in args], cwd=ROOT, check=True, **kwargs)

def build_plugin():
    BUILD.mkdir(parents=True, exist_ok=True)
    flags = shlex.split(subprocess.check_output([LLVM / 'llvm-config', '--cxxflags', '--ldflags', '--libs', 'core', 'passes'], text=True))
    run(LLVM / 'clang++', '-shared', '-fPIC', 'port/macos/compiler/guest_rebase.cpp', '-o', BUILD / 'guest_rebase.dylib', *flags)

def build_app(platform, args):
    directory = BUILD / platform
    sdk = 'iphonesimulator' if platform == 'simulator' else 'iphoneos'
    cmake = shutil.which('cmake') or '/opt/homebrew/bin/cmake'
    run(cmake, '-S', 'port/ios', '-B', directory, '-G', 'Xcode',
        '-DCMAKE_SYSTEM_NAME=iOS', f'-DCMAKE_OSX_SYSROOT={sdk}',
        '-DCMAKE_OSX_ARCHITECTURES=arm64', '-DCMAKE_OSX_DEPLOYMENT_TARGET=26.0',
        f'-DHALO_BUNDLE_MAPS={"OFF" if args.no_bundle_maps else "ON"}',
        f'-DHALO_BUNDLE_IDENTIFIER={args.bundle_id}',
        f'-DHALO_DEVELOPMENT_TEAM={args.team or ""}')
    settings = ['-jobs', str(args.jobs)]
    if not args.sign or platform == 'simulator':
        settings += ['CODE_SIGNING_ALLOWED=NO']
    else:
        settings += ['-allowProvisioningUpdates']
    run(cmake, '--build', directory, '--config', 'Release', '--target', 'Halo', '--', *settings)
    app = directory / f'Release-{sdk}' / 'Halo.app'
    if platform == 'simulator':
        for framework in sorted((app / 'Frameworks').glob('*.framework')):
            run('codesign', '--force', '--sign', '-', framework)
        run('codesign', '--force', '--sign', '-', app)
        run('codesign', '--verify', '--deep', '--strict', app)
    print(f'Built {app}')
    if platform == 'device' and not args.sign:
        print('Device app is unsigned. Open HaloIOS.xcodeproj, choose your development team, and run on the phone.')

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plugin-only', action='store_true')
    p.add_argument('--guest-only', action='store_true')
    p.add_argument('--host-only', action='store_true', help='Reuse the compiled game image')
    p.add_argument('--platform', choices=['simulator', 'device', 'both'], default='simulator')
    p.add_argument('--no-bundle-maps', action='store_true', help='Install game files separately through Files/Finder')
    p.add_argument('--team', help='Apple development team ID for device signing')
    p.add_argument('--bundle-id', default='local.halo.ce-universal.ios',
                   help='Unique reverse-DNS app identifier registered to your development team')
    p.add_argument('--sign', action='store_true', help='Use Xcode automatic device signing')
    p.add_argument('--jobs', type=int, default=6)
    args = p.parse_args()
    if args.sign and args.platform != 'simulator' and not args.team:
        p.error('--sign requires --team YOUR_TEAM_ID for a device build')
    os.chdir(ROOT)
    if args.plugin_only:
        build_plugin()
        return
    if not args.host_only:
        run(sys.executable, 'configure.py', '--ios', '--android-guest-llvm-bin', 'build/macos/toolchain/bin',
            '--android-guest-gl-include', 'build/macos/toolchain/gl', '--pgo', 'off')
        ninja = shutil.which('ninja') or ROOT / 'build/macos/toolchain/venv/bin/ninja'
        if not Path(ninja).is_file():
            raise RuntimeError('Install Ninja and run tools/macos_setup.py first; see docs/apple-build.md')
        run(ninja, f'-j{args.jobs}', 'ios_guest')
        run(sys.executable, 'tools/ios_embed.py', BUILD / 'halo_guest.elf', BUILD / 'embed')
    if not args.guest_only:
        for platform in (['simulator', 'device'] if args.platform == 'both' else [args.platform]):
            build_app(platform, args)

if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f'iOS build failed: {error}', file=sys.stderr)
        sys.exit(1)

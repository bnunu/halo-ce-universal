# Build and package the Apple Silicon Mac port

Run these commands from the repository root on an Apple Silicon Mac. The Mac
host uses Cocoa, SDL3 and ANGLE's Metal backend. The game remains an ARM64 ILP32
guest, with an LLVM pass rebasing its 32-bit addresses into the host address
space. The shared Android compiler and ABI tools supply the guest runtime;
an Android NDK or Android device is not required.

## Public build dependencies

Install Xcode Command Line Tools and the public tools below. The compiler pass
requires LLVM **22**; Apple's clang builds the native host.

```sh
xcode-select --install
brew install python cmake llvm@22 lld@22 sdl3 ninja
export HALO_MACOS_LLVM_BIN="$(brew --prefix llvm@22)/bin"
export PATH="$(brew --prefix lld@22)/bin:$PATH"
python3 tools/macos_setup.py
```

Use Python 3.10 or newer. Keep these exports in the shell used for later builds.
Do not place LLVM's entire `bin` directory before Apple's compiler on `PATH`.
The LLVM default is `/opt/homebrew/opt/llvm@22/bin`; `HALO_MACOS_SDL_PREFIX`
selects a different SDL3 installation if needed. Setup accepts `ld.lld` on
`PATH`; an existing `uv` installation can supply the local Zig/LLD fallback.

[dependencies.json](../port/macos/dependencies.json) pins ANGLE, Sparkle and the
Khronos headers with checksums. Guest configuration fetches SDL3 3.4.16 and musl
1.2.5 using the existing Android dependency tools. No game data, private Xbox
SDK, developer account or signing key is needed for a local app build. The
native ports use the checked-in declarations in
[port/include/xdk](../port/include/xdk/README.md).

## Build the app

```sh
python3 tools/macos_build.py
open "build/macos/Halo CE Universal.app"
```

The first launch asks for independently supplied original Xbox game data. A
build never copies that data into the app. The import dialog accepts a disc
image or extracted game/maps directory. Header validation accepts Xbox cache
version 5 from PAL build `01.01.14.2342` or USA build `01.10.12.2276`; keep one
complete set rather than mixing disc versions. A valid header alone does not
establish full gameplay compatibility.

An optional header-only check is available for extracted data:

```sh
python3 tools/macos_preflight.py --data-root "/path/to/your/game"
```

For a local development app, `--data-root /path/to/your/game` records only an
external path. The default and `--no-data-path` record no path. Signed release
builds also exclude that development path. Preferences and saves live outside
the app; replacing a bundle does not replace game data or saves.

`--host-only` rebuilds and packages the host after an initial complete build.
`ninja macos_guest` rebuilds the guest after configuration. `--jobs N` controls
guest build parallelism. The scripts leave the app under `build/macos`; copy it
to Applications yourself if desired. Existing generated app bundles are kept
under `build/macos/app-backups.noindex` when packaging replaces them.

## Distribution and updates

Local builds are ad-hoc signed and verified with `codesign`. The bundle includes
the native host, guest image, runtime libraries, icons and available dependency
licenses. `BuildInfo.txt` records the source revision, guest hash and repository.
The declared minimum macOS version is the highest deployment target among the
packaged binaries, so a newer SDL3 build may raise it above the host's 14.0 target.

`--repository owner/name` selects the GitHub download link embedded in an ad-hoc
artifact; CI passes the actual build repository. Signed releases must match the
repository in [release-config.json](../port/macos/release-config.json). Ordinary
ad-hoc packages keep automatic updating disabled even when that file contains
an update feed and public key.

See [Mac releases](macos-releases.md) for DMG creation, bundle auditing and the
separate signed/notarized update workflow. Building an app does not notarize,
install or publish it.

## Checks without game data

```sh
python3 -m unittest tools.test_macos_build tools.test_macos_preflight tools.test_macos_clock
python3 tools/macos_build.py --plugin-only
python3 tools/test_macos_runtime.py --standalone
```

The first command uses authored fixtures and does not build the app. The
standalone runtime tests compile small guest/host probes for memory rebasing,
syscalls, network structures, invite parsing, UPnP and audio transfer. They need
the public setup dependencies but no game files. These checks establish the
covered interfaces; a full game build and live gameplay remain separate checks.

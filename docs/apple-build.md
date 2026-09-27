# Build on Apple Silicon

Start here for both macOS and iPhone. All commands run on an Apple Silicon Mac
from the repository root unless stated otherwise. The Mac game runs natively;
the iPhone build also uses native ARM code and ANGLE's Metal renderer.

## 1. Clone and install public dependencies

```sh
git clone https://github.com/zimm3rmann/halo-ce-universal.git
cd halo-ce-universal
```

Install Xcode Command Line Tools for a Mac-only build, or full Xcode 26 or later
for iPhone. Open Xcode once to accept its license and install the iOS platform
support. For simulator testing, also install an iOS 26+ simulator runtime in
Xcode's Settings → Components. Physical-device builds do not need a simulator.

Using [Homebrew](https://brew.sh/):

```sh
brew install python cmake llvm@22 lld@22 sdl3 ninja
export HALO_MACOS_LLVM_BIN="$(brew --prefix llvm@22)/bin"
export PATH="$(brew --prefix lld@22)/bin:$PATH"

# For iPhone builds; adjust if Xcode is installed elsewhere:
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer

python3 tools/macos_setup.py
```

The compiler adapter requires **LLVM 22** (tested with 22.1.8), not Apple clang
or a newer LLVM major. [Homebrew's LLVM 22 formula](https://formulae.brew.sh/formula/llvm@22)
provides that version; LLD is a separate formula. Keep the exports in the shell
used for later builds. Do not put LLVM's entire `bin` directory ahead of the
system compiler: the host builds with Apple's clang, while
`HALO_MACOS_LLVM_BIN` selects the game compiler. Python 3.10+ and CMake 3.28+
are required.

Already have LLVM 22 at `/opt/homebrew/opt/llvm`? Use that keg for
`HALO_MACOS_LLVM_BIN` instead. Setup accepts an ELF-capable `ld.lld` on `PATH`;
if unavailable, installing `uv` enables its local Zig/LLD fallback. Ninja can
come from Homebrew or that fallback environment.

Setup downloads only public dependencies. ANGLE and Khronos headers have pinned
URLs and SHA-256 checksums in [dependencies.json](../port/macos/dependencies.json).
The build also fetches SDL3 3.4.16 and musl 1.2.5. No Android NDK is required.

## 2. Supply the game and SDK locally

Neither input is included or downloaded by these build scripts:

- **Original Xbox Halo: Combat Evolved maps**, extracted from your retail disc
  image. Supported Xbox version-5 headers are PAL `01.01.14.2342` and USA
  `01.10.12.2276`. Use one complete set; do not mix regions or builds. Halo PC,
  Custom Edition, Anniversary and MCC maps are not substitutes.
- **August 2001 Xbox XDK (3911) headers**, from the SDK installation's
  `XDK/xbox/include` folder. A recovery-only ISO does not contain the SDK.
  Copy the complete include directory, retaining its subdirectories. Mac and
  iPhone builds do not use the Windows compiler or need `cachebeta.exe`.

The checkout should look like this:

```text
halo-ce-universal/
  assets/
    maps/
      ui.map
      a10.map
      a30.map
      ...                  # all remaining campaign and multiplayer maps
  xbox/
    include/
      XTL.h                # filename case may differ
      D3D8.h
      ...                  # the complete SDK header tree
```

To extract an existing XISO, one option is the open-source
[XboxDev/extract-xiso utility](https://github.com/XboxDev/extract-xiso#building).
Build it under the ignored build directory, then copy only the maps into place:

```sh
git clone https://github.com/XboxDev/extract-xiso.git build/tools/extract-xiso
cmake -S build/tools/extract-xiso -B build/tools/extract-xiso/build
cmake --build build/tools/extract-xiso/build
build/tools/extract-xiso/build/extract-xiso \
  -x "/path/to/your/Halo.xiso.iso" -d build/game-extracted
mkdir -p assets
cp -R build/game-extracted/maps assets/

mkdir -p xbox
cp -R "/path/to/your/extracted/XDK/xbox/include" xbox/
```

Use the actual paths and filename case from your extraction. If you already
have an extracted `maps/` folder, copy it directly; extraction is unnecessary.
Archives/installers vary, so extract the SDK separately before the final copy.
Keep the SDK archives and disc image outside the repository.

Validate the inputs before compiling:

```sh
python3 tools/macos_preflight.py --output build/macos/preflight.json
```

This checks map headers and the SDK, not actual gameplay. It reports any missing
campaign maps separately; supply the full set to play the full campaign. The
expected `D3D8.h` SHA-256 is
`7f7f603e1b2fa13ef36a05923eaa36d0d7094302522edbac9855b28f0909f1a1`.
Do not bypass a mismatched SDK hash: the header overlays depend on this version.
The generated report includes local paths and stays under ignored `build/`.

## 3. Build and play

- [macOS: compile, launch, controls and performance](../port/macos/README.md#build).
  No Apple development account or special entitlement is needed.
- [iPhone: compile, sign and install](../port/ios/README.md#build).
  Use your own paid Apple development team, a unique bundle identifier and a
  phone in Developer Mode. A Personal Team could not provision the required
  Extended Virtual Addressing entitlement in testing.
- [iOS simulator](../port/ios/README.md#simulator): useful for menu and touch
  checks without device signing; it does not establish device performance.

The tested devices are an M5 Mac on macOS 26.5.1 and an iPhone 17 Pro Max on
iOS 26.6.2. The Mac bundle declares macOS 14+, and the iPhone build targets
iOS 26+, but other OS/device combinations have not been exhaustively tested.

## Source-only sharing

`assets/`, `xbox/`, `original/` and `build/` are ignored, along with disc images,
map files, SDK archives, Apple signing material and generated Xcode projects.
SDK-derived overlays and all generated game binaries stay under `build/`.
Do not force-add those files or upload them as release assets.

Device signing settings belong in your local Xcode account and ignored build
directory. Pass your team ID and bundle identifier on the command line; do not
hardcode your team, certificate name, device IDs or provisioning profile into
source files. The checked-in entitlement file contains only a capability flag,
not an identity or secret.

iPhone apps bundle your maps by default. `--no-bundle-maps` leaves them out,
but does not turn a locally built app into an approved redistributable package.
Keep compiled apps, logs and provisioning profiles local. When contributing
source, inspect `git diff --cached --name-only` and `git diff --cached` before
committing; ignore rules cannot prevent an explicit `git add -f`.

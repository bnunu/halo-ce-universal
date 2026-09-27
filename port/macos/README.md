# Native Apple Silicon build

The experimental native Mac build is playable. On 2026-09-27, the main menu,
campaign loading and gameplay, mouse capture, and audible output were confirmed
on an M5 Mac with 16 GB RAM running macOS 26.5.1. This is the phase-one baseline;
it is not a claim that every campaign level or Mac configuration is verified.

The CPU code runs natively on ARM64. The existing GLES renderer uses ANGLE's
Metal backend. No Windows runtime, Xbox emulator, Apple Developer account,
special entitlement, or security-setting change is required for this local build.

## Install with one command

On a Mac with Apple silicon (M1 or later) and macOS 14 or later, open Terminal
and paste:

```sh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/bnunu/halo-ce-universal/macos/port/macos/install.sh)"
```

[install.sh](install.sh) does every step of [Build](#build) for you:

1. Checks the Mac: Apple silicon, macOS 14, 12 GB free.
2. Installs Apple's command line tools (a window asks first) and
   [Homebrew](https://brew.sh/) if they are missing (Homebrew asks for your
   Mac password), then `brew install python cmake llvm@22 lld@22 sdl3 ninja`.
3. Downloads this repository into `~/HaloCEUniversal/game`.
4. Asks for your two files, after looking in Downloads, Desktop and Documents
   by itself: drag each into the Terminal window. The Xbox SDK can be its disc
   image (`XBOXSDK_3911.ISO`), its installer (`XDKSetupEng.exe`), an archive
   holding one, or a folder with `xbox/include`; the game can be the disc image
   (extract-xiso images and full dumps), an archive holding one, or a folder
   with `maps/`. [tools/macos_inputs.py](../../tools/macos_inputs.py) unpacks
   them with macOS's own `tar` and checks them (the SDK by the SHA-256 of
   `D3D8.h`, the maps by their build): the headers go to `game/xbox/include`,
   the maps to `~/HaloCEUniversal/data`.
5. Runs `tools/macos_setup.py`, `tools/macos_preflight.py` and
   `tools/macos_build.py --data-root ~/HaloCEUniversal/data`.
6. Copies `Halo CE Universal.app` to Applications (`~/Applications` when
   `/Applications` isn't writable) and starts it.

Run the same command again to update: it fetches the newest source and
rebuilds what changed. Options go after `--`, for example
`/bin/bash -c "$(curl ...)" -- --xdk ~/Downloads/XBOXSDK_3911.ISO`:
`--xdk PATH` and `--data PATH` choose the files, `--no-open` doesn't start
Halo, and `--uninstall` removes the app and `~/HaloCEUniversal` (saved games
and Homebrew stay). What each run did is in `~/HaloCEUniversal/install.log`.
`HALO_MAC_ROOT`, `HALO_MAC_REPO` and `HALO_MAC_BRANCH` choose the install
folder, the repository and the branch.

## Launch

Open `build/macos/Halo CE Universal.app` in Finder. There is no automatic timeout.
The app includes SDL3, ANGLE, and the compiled game image. Its local game-data
configuration points to this checkout's `assets/` directory; keep that directory
in place. The original downloaded ISO and SDK archive are not used at runtime.

The app defaults to borderless fullscreen at the desktop's aspect ratio, with
Retina output. The 3D field of view widens; the image is not stretched. Rendering
still uses 480 vertical lines internally, scaled to the display. On the tested
display this is 740x480 into a 3420x2214 drawable. Set `HALO_WINDOWED=1` for a
resizable window or `HALO_SCREEN_WIDTH=640` to restore the original 4:3 view.
`HALO_WINDOW_SCALE` controls the initial size in windowed mode.

Saves, cache files, `config.toml`, and `halo.log` are under:

```text
~/Library/Application Support/Halo CE Universal/
```

Keyboard/mouse controls:

| Control | Action |
| --- | --- |
| W A S D / mouse | Move / aim |
| Left / right mouse button | Fire / grenade |
| Space or Enter | Jump / accept |
| E or R | Action / reload |
| F or Backspace | Melee / back |
| Tab or mouse wheel | Change weapon |
| Q | Flashlight |
| C or left Control | Crouch |
| Z or middle mouse button | Zoom |
| Escape | Pause |
| F12 (Fn-F12 on some keyboards) | Release or recapture mouse |

`HALO_DATA_ROOT`, `HALO_SAVE_ROOT`, `HALO_WINDOW_SCALE`, `HALO_VOLUME`, and the
other [shared native settings](../linux/README.md#settings) remain available.
For a command-line run from the repository root:

```sh
build/macos/halo build/macos/halo_guest.elf
```

That development command uses `build/macos/saves/` by default; the app uses the
Mac Application Support location above.

For a Mac-versus-iPhone LAN match, follow [Apple System Link setup](../../docs/apple-multiplayer.md).

## Build

First complete [Apple build setup](../../docs/apple-build.md): clone the fork,
install LLVM 22 and the public dependencies, place your own game maps and XDK
headers locally, and run preflight. Keep the documented environment exports in
the shell used below. From the repository root:

```sh
python3 tools/macos_build.py
open "build/macos/Halo CE Universal.app"
```

The first build compiles the complete game and downloads public SDL/musl source
dependencies. No development team, provisioning profile or paid account is needed;
the local app is ad-hoc signed automatically. For compiler/runtime checks:

```sh
python3 tools/test_macos_runtime.py
python3 -m unittest tools.test_macos_preflight
python3 -m unittest tools.test_visibility_queries
```

The shared settings are read from `config.toml` in the save directory, with
`HALO_*` environment overrides still supported. The Mac host keeps its
`HALO_WINDOWED` setting and 480-line render scale; the upstream desktop-only
F11/menu-pointer path is not yet bridged through the ARM host.

The default LLVM path is `/opt/homebrew/opt/llvm/bin`. `HALO_MACOS_SDL_PREFIX`
and `HALO_MACOS_ANGLE_DIR` can select other dependency locations. SDL's guest
headers and musl sources are fetched by the shared ARM build graph. Existing
Windows/Linux/Android builds keep their own output directories.

`macos_build.py --host-only` rebuilds and packages just the host. After an initial
configuration, `ninja macos_guest` rebuilds the game. Compiler-pass and wrapper
changes are tracked dependencies. `--data-root /path/to/game` records another
local data directory in the app. The bundle is ad-hoc signed and signature
verification is part of packaging. It is a local build, not a notarized release.

## Memory and host architecture

Extra RAM does not solve the original address problem: the game stores pointers
and `long` in 32 bits, while ordinary ARM Mac executables cannot use its original
low addresses. The LLVM pass preserves those layouts and rebases memory access
and indirect calls into a 4 GB **virtual** arena at `0x10000000000`. This address
is not a physical RAM requirement. Memory is committed only as needed.

The pass uses LLVM address space 272 for 64-bit dereferences, explicitly lowers
varargs and memory intrinsics, preserves opaque GL offsets/handles, and translates
host pointer arguments. The Mac image has a distinct ABI version, so it cannot
be accidentally loaded by the Android host. This is an ABI adapter for the
locally compiled game, not an isolation boundary for arbitrary binaries.

The native host translates Linux/musl file, time, synchronization, memory, and
error interfaces to Darwin. Xbox 4 KB allocations share native 16 KB pages;
protection combines their requirements so freeing one allocation cannot remove
access to its neighbors. Texture write tracking therefore has 16 KB granularity.
Fresh heap mappings are explicitly recreated: Darwin's `MADV_DONTNEED` alone
does not guarantee the zero-filled pages expected by musl.

SDL video stays on the real main thread. Audio mixing runs on a guest-stack
worker, with the results returned to SDL's callback thread before submission.
This avoids a cross-thread stream-lock deadlock. Mouse capture is enabled on
macOS even though the renderer shares the Android GLES compilation path.

The old `--probe` preflight option measures the original low-address Android
assumptions and is expected to fail on an ordinary Mac. It is historical
diagnostic evidence, not a prerequisite for this rebased build.

## Validation and remaining work

Completed:

- Full ARM game and Darwin host compile; strictly verified local app signature.
- SDK hash and all 24 test-disc map payloads validated.
- Native execution probes for 32-bit layouts, globals, stacks, indirect calls,
  Xbox addresses, integer/floating varargs, memory routines, and atomics.
- Regression checks for fresh allocation contents, neighboring 4 KB allocations,
  texture write tracking, futex wakeups, clocks, and the SDL audio handoff.
- Real menu rendering, campaign gameplay, mouse capture, sound, and clean timed
  test shutdown; gameplay, audio and input confirmed on the target Mac.

Not yet exhaustively validated: all campaign missions, checkpoint save/reload,
controllers, split screen, system link, other M-series GPUs, and older macOS.
Bink startup videos are skipped by the existing native port. CPU and rendering
correctness still need longer playtesting, especially under memory pressure.

The compiler regression suite includes an unaligned 64-bit read from a guest
stack pointer. ARM64 ILP32 instruction selection could add the arena bias twice
when splitting this load (observed in radar blip drawing). Explicit machine-level
pointer truncation fixes it. The original Xbox stack walker is disabled on Mac
because it cannot safely traverse native Darwin frames during assertion reports.

## Performance investigation (2026-09-27)

A live gameplay session reached 21.1 GB physical footprint: 20.8 GB was graphics
allocations, including 15.9 GB swapped out. The 4 GB guest virtual reservation
was not the source. The renderer now expands misaligned Xbox vertex attributes
only for the vertices in the draw. This avoids ANGLE's conversion of entire
4/16 MB backing buffers for attributes such as SHORT1 at byte 30 of a vertex.
Occlusion queries also use the last completed result instead of spinning on
unfinished Metal work, matching the existing desktop query-buffer behavior.

Seventy-second `a30` tests with a grenade effect every two seconds, starting at
20 seconds, gave these results on the M5 Mac (vsync enabled):

| Build/mode | Median frame | 95th percentile | Peak physical footprint |
| --- | --- | --- | --- |
| Before renderer fixes, 4:3 | 16.67 ms | 17.32 ms | 1181 MB |
| After fixes, 4:3 | 16.67 ms | 17.41 ms | 468 MB |
| After fixes, native aspect fullscreen | 16.67 ms | 17.88 ms | 511 MB |

A final 70-second test requesting an explosion every 0.25 seconds also completed:
16.67 ms median, 17.25 ms p95, 460 MB peak footprint. An earlier high-cadence run
stopped in the Xbox assertion stack walker before preserving the assertion;
the final retest did not reproduce it. Longer stress testing is still needed.

These runs show reduced memory demand, not a measured increase in maximum FPS:
both versions reached the 60 FPS presentation limit. The after runs also captured
periodic screenshots. They do not yet reproduce or rule out the original long
session's 21 GB growth. Campaign screenshots were checked for geometry and HUD
rendering; broader visual and sustained-play comparisons remain necessary.

With other Halo instances closed, reproduce the test using isolated saves:

```sh
python3 tools/macos_benchmark.py --output build/macos/performance/retest --effects --fullscreen
```

`--guest` chooses a comparison image; `--level a10|a30|b30`, `--seconds`, and
`--interval` control the scene and effect cadence. The helper uses the game's
existing local developer console and keeps maps linked and saves separate.
The CSV, console transcript, and game log are under the output directory.
Set `HALO_PERF_LOG=/absolute/path/frames.csv` for profiling an ordinary launch.
Driver draw time includes waits (including drawable/vsync waits); it is not a
GPU timestamp measurement. Normal launches do not enable per-draw profiling.

## Phase two

Use this ANGLE/Metal build as the reference before changing rendering behavior.
Capture repeatable `a10`, `a30`, and `b30` scenes, recording frame-time percentiles,
GPU time, resident memory, loading time, and shader compilation stalls. Then
prioritize measured bottlenecks: shader/pipeline caching, upload and dirty-region
costs, resolution scaling, frame pacing, and CPU hot paths. Preserve the 30 Hz
simulation and validate interpolation separately.

Direct NV2A-to-Metal shader translation is a later experiment, with visual
comparisons for fog, water, shadows, blending, gamma, and render targets. ANGLE
already uses Metal today; a direct renderer should earn its maintenance cost
through measured performance or compatibility improvements.

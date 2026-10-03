# Native Apple Silicon port

This port runs the game’s CPU code natively on Apple Silicon and uses ANGLE’s
Metal backend for graphics. The game retains its 32-bit data layout inside a
64-bit macOS process: an LLVM pass rebases guest memory accesses into a reserved
address range, and native bridges provide Darwin, SDL, graphics, audio and
network services.

See [Mac build setup](../../docs/macos-build.md) for dependencies, build commands,
runtime checks and packaging. This branch is an extraction onto the upstream
engine; verification results from the source fork do not establish that this
new combination is working.

## Launch and game data

The build produces `build/macos/Halo CE Universal.app`. Its first-launch chooser
accepts your own original Xbox Halo disc image or an extracted game folder.
Game data is not included in the app or DMG. The chooser checks the Xbox cache
headers and requires `ui.map` and `a10.map` from one supported disc release.
Every other retail map present must match that release. Additional Custom
Edition/OpenSauce maps and resource files may share the folder; the engine
validates and enables that optional content separately.

Disc imports extract maps into a new directory for each attempt. Failed imports
are removed, and the previous working data selection remains intact. The
native Settings window can choose another disc or maps folder; changing the
selection takes effect the next time the app starts. Upstream Custom Edition
support has separate engine settings and is not a substitute for the Xbox base
data selected here.

The helmet menu provides Show Game, Full Screen, Settings, game-data selection,
the saves folder and the advanced configuration file. Native settings return
control to the game’s event loop so networking can continue while they are open.
The updater is configured separately for the repository distributing the app.

Saves, configuration, the game log and imported data live outside the app:

```text
~/Library/Application Support/Halo CE Universal/
```

`macos-settings.json` stores the selected game-data path and window mode.
`config.toml` contains the engine’s controls and other settings. Existing values
remain in place when replacing the app. This port retains the upstream engine’s
defaults; it does not install an Xbox comparison profile or PB gameplay options.

## Source layout

- `compiler/guest_rebase.cpp` implements the guest pointer transformation.
- `host/` contains native services, the ELF loader and guest-thread support.
- `native/` contains the Cocoa menu, data chooser, preferences and updater hooks.
- `tests/` covers memory, the guest ABI, audio, networking, invitations and native
  preferences. UI checks require a graphical macOS session.
- `dependencies.json` pins downloadable dependencies and their hashes.
- `AppIcon.png` is the app-icon source; `Helmet.svg` is the editable menu icon.

The shared guest ABI and libc live under `port/android/`; this does not require
an Android SDK or Android runtime. The Mac app uses its own icon and ABI test
helper, and does not require the iOS port.

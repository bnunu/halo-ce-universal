#!/bin/bash
# Halo CE Universal for Mac: installs, updates and starts the native Apple
# Silicon build (port/macos/README.md). You supply only the two things that
# can't be downloaded: the Xbox SDK (XDK 3911, August 2001) and your own
# Halo: Combat Evolved for the original Xbox (American or European). Everything
# else comes from its publisher: Apple's command line tools, Homebrew and its
# LLVM 22, lld, SDL3, CMake, ninja and Python, this repository, and the pinned
# downloads of tools/macos_setup.py.
#
# In Terminal:
#
#   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/bnunu/halo-ce-universal/macos/port/macos/install.sh)"
#
# Run the same command again to update. Options (after the command, as
# `/bin/bash -c "$(curl ...)" -- --xdk PATH`):
#   --xdk PATH     the Xbox SDK to use: disc image, XDKSetupEng.exe, archive or folder
#   --data PATH    the game to use: disc image, archive or folder with maps
#   --no-open      don't start Halo at the end
#   --uninstall    remove Halo CE Universal (saved games and Homebrew stay)
#
# HALO_MAC_ROOT (default ~/HaloCEUniversal), HALO_MAC_REPO and HALO_MAC_BRANCH
# choose where it goes and what it builds.

set -u

REPO="${HALO_MAC_REPO:-https://github.com/bnunu/halo-ce-universal.git}"
BRANCH="${HALO_MAC_BRANCH:-macos}"
ROOT="${HALO_MAC_ROOT:-$HOME/HaloCEUniversal}"
GAME="$ROOT/game"
DATA="$ROOT/data"
LOG="$ROOT/install.log"
APP="Halo CE Universal.app"

XDK_INPUT=""
DATA_INPUT=""
OPEN=1
UNINSTALL=0
while [ $# -gt 0 ]; do
	case "$1" in
	--) shift ;;
	--xdk) XDK_INPUT="${2:-}"; shift 2 ;;
	--data) DATA_INPUT="${2:-}"; shift 2 ;;
	--no-open) OPEN=0; shift ;;
	--uninstall) UNINSTALL=1; shift ;;
	*) echo "Unknown option: $1 (see the top of this script)"; exit 2 ;;
	esac
done

bold=$(tput bold 2>/dev/null || true)
plain=$(tput sgr0 2>/dev/null || true)

log() {
	printf '%s\n' "$*" >> "$LOG" 2>/dev/null
}

step() {
	printf '\n%s== %s%s\n' "$bold" "$1" "$plain"
	log "== $1"
}

fail() {
	printf '\n%s!! %s%s\n' "$bold" "$1" "$plain" >&2
	log "!! $1"
	if [ -f "$LOG" ]; then
		printf 'What happened is in %s: send that file when asking for help.\n' "$LOG" >&2
	fi
	exit 1
}

# Runs a command with its output in the log and one line on the screen that
# follows it.
quietly() {
	"$@" 2>&1 | tee -a "$LOG" | while IFS= read -r line; do
		printf '\r\033[K   %s' "${line:0:76}"
	done
	local status=${PIPESTATUS[0]}
	printf '\r\033[K'
	return "$status"
}

halo_running() {
	pgrep -f "$APP/Contents/MacOS/halo" >/dev/null 2>&1
}

installed_app() {
	for folder in /Applications "$HOME/Applications"; do
		if [ -d "$folder/$APP" ]; then
			printf '%s\n' "$folder/$APP"
			return 0
		fi
	done
	return 1
}

if [ "$UNINSTALL" = 1 ]; then
	if halo_running; then
		echo "Quit Halo first, then run this again."
		exit 1
	fi
	printf 'Remove Halo CE Universal (the app and %s)? Saved games and Homebrew stay. [y/N] ' "$ROOT"
	read -r reply
	case "$reply" in
	y|Y|yes|YES) ;;
	*) echo "Nothing was removed."; exit 0 ;;
	esac
	app=$(installed_app) && rm -rf "$app"
	rm -rf "$ROOT"
	echo "Halo CE Universal is removed. Saved games are in ~/Library/Application Support/Halo CE Universal."
	exit 0
fi

mkdir -p "$ROOT" || { echo "Can't create $ROOT."; exit 1; }
log "---- $(date '+%Y-%m-%d %H:%M:%S'), $REPO ($BRANCH)"

step "Checking this Mac"
[ "$(uname -s)" = Darwin ] || fail "This installer is for macOS."
if [ "$(sysctl -in hw.optional.arm64 2>/dev/null)" != 1 ]; then
	fail "This Mac has an Intel processor. The Mac version of Halo CE Universal needs a Mac with Apple silicon (M1 or later)."
fi
if [ "$(uname -m)" != arm64 ]; then
	fail "Terminal is running with Rosetta. Quit Terminal, turn off \"Open using Rosetta\" in its Get Info window, and run this again."
fi
macos=$(sw_vers -productVersion)
if [ "${macos%%.*}" -lt 14 ]; then
	fail "Halo CE Universal needs macOS 14 (Sonoma) or later; this Mac has macOS $macos."
fi
free_gb=$(df -g "$ROOT" | awk 'NR == 2 { print $4 }')
if [ "${free_gb:-0}" -lt 12 ]; then
	fail "About 12 GB of free space is needed and ${free_gb:-0} GB is free. Free up some space, then run this again."
fi
log "macOS $macos, $(sysctl -n machdep.cpu.brand_string 2>/dev/null), ${free_gb} GB free"
echo "   macOS $macos on Apple silicon, ${free_gb} GB free."

step "Apple's command line tools"
if ! xcode-select -p >/dev/null 2>&1; then
	echo "   A window asks to install the command line developer tools: click Install,"
	echo "   agree, and wait until it's done (5 to 15 minutes). This continues by itself."
	xcode-select --install >/dev/null 2>&1
	waited=0
	until xcode-select -p >/dev/null 2>&1; do
		sleep 5
		waited=$((waited + 5))
		if [ "$waited" -ge 3600 ]; then
			fail "Apple's command line tools weren't installed. Run this again to retry."
		fi
	done
fi
echo "   Installed: $(xcode-select -p)"

step "Homebrew"
BREW=/opt/homebrew/bin/brew
if [ ! -x "$BREW" ]; then
	echo "   Halo's build tools come from Homebrew (brew.sh), which isn't on this Mac yet."
	echo "   Installing it needs your Mac password: type it (it doesn't show) and press Return."
	sudo -v || fail "Installing Homebrew needs the password of an administrator of this Mac."
	NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
		|| fail "Installing Homebrew didn't work."
	[ -x "$BREW" ] || fail "Homebrew was installed, but $BREW is missing."
fi
eval "$("$BREW" shellenv)"
echo "   $(brew --version | head -n 1)"

step "Build tools: LLVM 22, lld, SDL3, CMake, ninja and Python (a few minutes the first time)"
quietly brew install python cmake llvm@22 lld@22 sdl3 ninja || fail "Homebrew couldn't install the build tools."
HALO_MACOS_LLVM_BIN="$(brew --prefix llvm@22)/bin"
export HALO_MACOS_LLVM_BIN
PATH="$(brew --prefix lld@22)/bin:$PATH"
export PATH
PYTHON="$(brew --prefix python)/libexec/bin/python3"
[ -x "$PYTHON" ] || PYTHON=$(command -v python3)
log "LLVM: $("$HALO_MACOS_LLVM_BIN/llvm-config" --version 2>&1); Python: $("$PYTHON" --version 2>&1)"

step "Halo's source code"
if [ -d "$GAME/.git" ]; then
	quietly git -C "$GAME" fetch --depth 1 origin "$BRANCH" || fail "Couldn't download Halo's source code. Check the internet connection."
	quietly git -C "$GAME" reset --hard FETCH_HEAD || fail "Couldn't update Halo's source code in $GAME."
else
	rm -rf "$GAME"
	quietly git clone --depth 1 --branch "$BRANCH" "$REPO" "$GAME" || fail "Couldn't download Halo's source code. Check the internet connection."
fi
echo "   $(git -C "$GAME" log -1 --format='%h %s')"

step "Your Xbox development kit and Halo game"
set --
[ -n "$XDK_INPUT" ] && set -- "$@" --xdk "$XDK_INPUT"
[ -n "$DATA_INPUT" ] && set -- "$@" --data "$DATA_INPUT"
"$PYTHON" "$GAME/tools/macos_inputs.py" --xdk-dest "$GAME/xbox/include" --data-dest "$DATA" "$@" \
	|| fail "Halo can't be set up without these two."

cd "$GAME" || fail "$GAME is missing."

step "Graphics libraries and headers (ANGLE, Khronos)"
quietly "$PYTHON" tools/macos_setup.py || fail "Preparing the build didn't work."

step "Checking your files"
"$PYTHON" tools/macos_preflight.py --data-root "$DATA" --output build/macos/preflight.json >> "$LOG" 2>&1 \
	|| fail "Your game files or Xbox development kit didn't pass the check; $GAME/build/macos/preflight.json says why."
echo "   The development kit and the maps are the ones Halo needs."

if halo_running; then
	fail "Halo is running. Quit it, then run this again."
fi

step "Building Halo (the first time takes several minutes)"
quietly "$PYTHON" tools/macos_build.py --data-root "$DATA" || fail "Building Halo didn't work."
[ -d "build/macos/$APP" ] || fail "The build finished, but build/macos/$APP is missing."

step "Adding Halo to Applications"
target_folder=/Applications
if [ ! -w "$target_folder" ]; then
	target_folder="$HOME/Applications"
	mkdir -p "$target_folder"
fi
rm -rf "$target_folder/$APP"
ditto "build/macos/$APP" "$target_folder/$APP" || fail "Couldn't copy Halo to $target_folder."
echo "   $target_folder/$APP"

printf '\n%sHalo CE Universal is installed.%s Start it from Applications or Launchpad.\n' "$bold" "$plain"
echo "Run the same command again to update. Saved games are in ~/Library/Application Support/Halo CE Universal."
if [ "$OPEN" = 1 ]; then
	open "$target_folder/$APP"
fi

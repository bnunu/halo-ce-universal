#!/usr/bin/env python3
"""Put the player's own Xbox SDK headers and Halo maps in place for the Mac build.

Used by port/macos/install.sh; it can also be run on its own. It finds the two
inputs (or asks for them: drag a file or folder into the Terminal window) and
unpacks them:

- the August 2001 XDK (3911): its disc image (XBOXSDK_3911.ISO), its installer
  (XDKSetupEng.exe, which holds the SDK in a cabinet), an archive holding
  either, or a folder with the SDK's xbox/include. The headers go to
  --xdk-dest, checked by the SHA-256 of D3D8.h as libs/d3d8/ does.
- Halo: Combat Evolved for the original Xbox, PAL 01.01.14.2342 or NTSC
  01.10.12.2276: a disc image (extract-xiso images and full dumps), an archive
  holding one, or a folder with the disc's maps/. The maps folders go to
  --data-dest.

Nothing is downloaded or sent anywhere. Archives, disc images and the SDK's
cabinet are read with the system's bsdtar (macOS's tar).
"""

import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile

D3D8_SHA256 = "7f7f603e1b2fa13ef36a05923eaa36d0d7094302522edbac9855b28f0909f1a1"
BUILDS = {"01.01.14.2342": "European (PAL)", "01.10.12.2276": "American (NTSC)"}
XBOX_MAGIC = b"MICROSOFT*XBOX*MEDIA"
# where an image's game partition starts: extract-xiso images, full (redump)
# dumps of the retail discs, and other dump layouts
XISO_OFFSETS = (0, 0x18300000, 0x0FD90000, 0x02080000)
MAPS_FOLDER = re.compile(r"^maps(_[a-z]{2})?$", re.IGNORECASE)
ARCHIVES = (".zip", ".7z", ".rar")
SEARCH_FOLDERS = ("Downloads", "Desktop", "Documents")


class Problem(Exception):
    """a message for the player"""


def say(text=""):
    print(text, flush=True)


def tar():
    for name in ("bsdtar", "tar"):
        found = shutil.which(name)
        if found:
            return found
    raise Problem("tar was not found (it is part of macOS).")


def tar_list(archive):
    result = subprocess.run([tar(), "-tf", str(archive)], capture_output=True, text=True, errors="replace")
    return [line for line in result.stdout.splitlines() if line] if result.returncode == 0 else None


def tar_extract(archive, target, members=None):
    target.mkdir(parents=True, exist_ok=True)
    command = [tar(), "-xf", str(archive), "-C", str(target)] + list(members or [])
    result = subprocess.run(command, capture_output=True, text=True, errors="replace")
    if result.returncode != 0:
        raise Problem("Couldn't unpack %s: %s" % (archive.name, result.stderr.strip()[-300:]))


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def find_file(root, name):
    """the files called name (any case) under root"""
    wanted = name.casefold()
    for folder, _, files in os.walk(root):
        for file in files:
            if file.casefold() == wanted:
                yield Path(folder) / file


# ---------- the Xbox SDK

def valid_include(folder):
    d3d8 = next(find_file_shallow(folder, "d3d8.h"), None)
    return d3d8 is not None and sha256(d3d8) == D3D8_SHA256


def find_file_shallow(folder, name):
    """name in folder itself (any case)"""
    if not folder.is_dir():
        return
    for entry in folder.iterdir():
        if entry.name.casefold() == name.casefold() and entry.is_file():
            yield entry


def include_in(root):
    """the SDK's include folder under root: the folder of the right D3D8.h, or
    None; raises when there is a D3D8.h of another SDK"""
    other = False
    for d3d8 in find_file(root, "d3d8.h"):
        if sha256(d3d8) == D3D8_SHA256:
            return d3d8.parent
        other = True
    if other:
        raise Problem("This is a different version of the Xbox development kit. Halo needs version 3911 from August 2001.")
    return None


def cabinets(path):
    """(offset, size) of the Microsoft cabinets inside a file, largest first"""
    found = []
    size = path.stat().st_size
    with open(path, "rb") as source:
        data = source.read()
    start = 0
    while True:
        at = data.find(b"MSCF", start)
        if at < 0:
            break
        start = at + 4
        if at + 36 > len(data):
            break
        reserved1, cabinet_size, reserved2, files_offset, reserved3, minor, major = struct.unpack_from("<IIIIIBB", data, at + 4)
        if reserved1 == 0 and reserved2 == 0 and major == 1 and minor == 3 and 36 < cabinet_size <= size - at and files_offset < cabinet_size:
            found.append((at, cabinet_size))
    return sorted(found, key=lambda item: -item[1])


def xdk_from_installer(exe, scratch):
    say("Looking for the SDK inside %s" % exe.name)
    for index, (offset, length) in enumerate(cabinets(exe)):
        cab = scratch / ("setup-%d.cab" % index)
        with open(exe, "rb") as source, open(cab, "wb") as target:
            source.seek(offset)
            remaining = length
            while remaining:
                block = source.read(min(remaining, 1 << 22))
                if not block:
                    break
                target.write(block)
                remaining -= len(block)
        unpacked = scratch / ("cab-%d" % index)
        try:
            tar_extract(cab, unpacked)
        except Problem:
            continue
        include = include_in(unpacked)
        if include:
            return include
    return None


def xdk_from(path, scratch, depth=0):
    """the SDK's include folder found in path (a folder, disc image, installer
    or archive), or None"""
    if depth > 2:
        return None
    if path.is_dir():
        return include_in(path)
    name = path.name.casefold()
    if name.endswith(".exe"):
        return xdk_from_installer(path, scratch)
    if name.endswith(".h"):
        return xdk_from(path.parent, scratch, depth)
    entries = tar_list(path)
    if entries is None:
        return None
    say("Looking into %s" % path.name)
    lowered = [entry.casefold() for entry in entries]
    for entry, low in zip(entries, lowered):
        if low.endswith("/d3d8.h"):
            target = scratch / ("xdk-%d" % depth)
            tar_extract(path, target)
            return include_in(target)
    for entry, low in zip(entries, lowered):
        if re.search(r"(^|/)xdksetup[^/]*\.exe$", low) or low.endswith((".iso",) + ARCHIVES):
            target = scratch / ("nested-%d" % depth)
            tar_extract(path, target, [entry])
            found = xdk_from(target / entry, scratch, depth + 1)
            if found:
                return found
    return None


# ---------- the game's maps

class MapFile:
    def __init__(self, folder, name, size, header):
        self.folder, self.name, self.size, self.header = folder, name, size, header
        self.build = None
        if (len(header) >= 0x800 and header[:4] == b"daeh" and header[0x7FC:0x800] == b"toof"
                and struct.unpack_from("<i", header, 4)[0] == 5):
            self.build = header[0x40:0x60].split(b"\0", 1)[0].decode("ascii", "replace")


def problem_with(maps):
    """what is wrong with these maps for the game, or None"""
    if not maps:
        return "No Halo game files were found there. Choose the disc image (.iso), or the folder that has a folder called maps in it."
    broken = [m for m in maps if m.build is None]
    if broken:
        return "%s/%s is damaged or isn't a Halo file. Copy the game from the disc again." % (broken[0].folder, broken[0].name)
    other = [m for m in maps if m.build not in BUILDS]
    if other:
        return ("This is a different version of Halo (build %s). The American (NTSC) and European (PAL) "
                "versions of the original Xbox game work." % other[0].build)
    if len({m.build for m in maps}) > 1:
        return "These game files mix the American and the European version of Halo. Copy the maps folder from one disc only."
    if not any(m.name.casefold() == "ui.map" for m in maps):
        return "ui.map (the main menu) is missing. Copy the whole maps folder from the disc."
    return None


class FolderGame:
    """a folder with maps folders (the disc's files)"""

    def __init__(self, root):
        self.root = root
        self.maps = []
        for folder in sorted(root.iterdir()):
            if folder.is_dir() and MAPS_FOLDER.match(folder.name):
                for file in sorted(folder.iterdir()):
                    if file.is_file() and file.suffix.casefold() == ".map":
                        with open(file, "rb") as source:
                            header = source.read(0x800)
                        self.maps.append(MapFile(folder.name, file.name, file.stat().st_size, header))

    def copy(self, map_file, target):
        shutil.copyfile(self.root / map_file.folder / map_file.name, target)


class ImageGame:
    """an Xbox disc image (XDVDFS)"""

    def __init__(self, path, base):
        self.path, self.base = path, base
        self.maps = []
        self.extents = {}
        with open(path, "rb") as image:
            descriptor = self.read(image, 32 * 2048, 0x1C)
            root_sector, root_size = struct.unpack_from("<II", descriptor, 0x14)
            for name, sector, size, is_folder in self.entries(image, root_sector, root_size):
                if is_folder and MAPS_FOLDER.match(name):
                    for file, file_sector, file_size, file_is_folder in self.entries(image, sector, size):
                        if not file_is_folder and file.casefold().endswith(".map"):
                            header = self.read(image, file_sector * 2048, min(0x800, file_size))
                            self.maps.append(MapFile(name, file, file_size, header))
                            self.extents[(name, file)] = (file_sector, file_size)

    def read(self, image, offset, length):
        image.seek(self.base + offset)
        return image.read(length)

    def entries(self, image, sector, size):
        if size == 0:
            return []
        table = self.read(image, sector * 2048, size)
        found, pending, seen = [], [0], set()
        while pending:
            offset = pending.pop()
            if offset in seen or offset + 14 > len(table):
                continue
            seen.add(offset)
            left, right, start, length, attributes, name_length = struct.unpack_from("<HHIIBB", table, offset)
            if left == 0xFFFF and right == 0xFFFF:
                continue
            name = table[offset + 14:offset + 14 + name_length].decode("latin-1")
            found.append((name, start, length, bool(attributes & 0x10)))
            if left:
                pending.append(left * 4)
            if right:
                pending.append(right * 4)
        return found

    def copy(self, map_file, target):
        sector, size = self.extents[(map_file.folder, map_file.name)]
        with open(self.path, "rb") as image, open(target, "wb") as output:
            image.seek(self.base + sector * 2048)
            remaining = size
            while remaining:
                block = image.read(min(remaining, 1 << 22))
                if not block:
                    raise Problem("The disc image %s is cut short. Copy it again." % self.path.name)
                output.write(block)
                remaining -= len(block)


def open_image(path):
    try:
        with open(path, "rb") as image:
            for base in XISO_OFFSETS:
                image.seek(base + 32 * 2048)
                if image.read(20) == XBOX_MAGIC:
                    return ImageGame(path, base)
    except OSError:
        return None
    return None


def data_roots(folder):
    """folders under folder (itself included) that hold a maps folder"""
    roots = []
    if MAPS_FOLDER.match(folder.name) and folder.parent != folder:
        roots.append(folder.parent)
    for current, subfolders, _ in os.walk(folder):
        depth = Path(current).relative_to(folder).parts
        if len(depth) > 3:
            subfolders[:] = []
            continue
        if any(MAPS_FOLDER.match(sub) for sub in subfolders):
            roots.append(Path(current))
    return roots


def game_from(path, scratch, depth=0):
    """the best game found in path, or None"""
    if depth > 2:
        return None
    if path.is_dir():
        best = None
        for root in data_roots(path):
            game = FolderGame(root)
            if problem_with(game.maps) is None:
                return game
            best = best or (game if game.maps else None)
        for image in sorted(path.rglob("*")):
            if image.suffix.casefold() in (".iso", ".xiso") and image.is_file():
                game = open_image(image)
                if game and problem_with(game.maps) is None:
                    return game
        return best
    if path.suffix.casefold() == ".map":
        return game_from(path.parent.parent, scratch, depth)
    game = open_image(path)
    if game:
        return game
    entries = tar_list(path)
    if entries is None:
        return None
    say("Looking into %s" % path.name)
    maps = [entry for entry in entries if re.search(r"(^|/)maps(_[a-z]{2})?/[^/]+\.map$", entry, re.IGNORECASE)]
    if maps:
        target = scratch / ("game-%d" % depth)
        tar_extract(path, target, maps)
        return game_from(target, scratch, depth + 1)
    for entry in entries:
        if entry.casefold().endswith((".iso", ".xiso")):
            target = scratch / ("image-%d" % depth)
            say("Unpacking the disc image from %s (a few minutes)" % path.name)
            tar_extract(path, target, [entry])
            return game_from(target / entry, scratch, depth + 1)
    return None


def install_maps(game, data_dest):
    total = sum(m.size for m in game.maps)
    say("Copying your game files (%.1f GB)" % (total / 1e9))
    data_dest.mkdir(parents=True, exist_ok=True)
    folders = {m.folder for m in game.maps}
    for existing in data_dest.iterdir():
        if existing.is_dir() and MAPS_FOLDER.match(existing.name) and existing.name not in folders:
            shutil.rmtree(existing)
    for map_file in game.maps:
        folder = data_dest / map_file.folder
        folder.mkdir(exist_ok=True)
        target = folder / map_file.name
        if target.exists() and target.stat().st_size == map_file.size:
            with open(target, "rb") as existing:
                if existing.read(0x800) == map_file.header[:0x800]:
                    continue
        partial = folder / (map_file.name + ".part")
        game.copy(map_file, partial)
        os.replace(partial, target)


# ---------- finding them

def unquote(text):
    """a path typed or dragged into Terminal: quotes, backslash escapes, ~"""
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        text = text[1:-1]
    else:
        text = re.sub(r"\\(.)", r"\1", text)
    return Path(os.path.expanduser(text))


def candidates(kind):
    """likely inputs in the usual folders, most recently changed first"""
    home = Path.home()
    found = []
    for name in SEARCH_FOLDERS:
        folder = home / name
        if not folder.is_dir():
            continue
        for current, subfolders, files in os.walk(folder):
            depth = len(Path(current).relative_to(folder).parts)
            if depth >= 2:
                subfolders[:] = []
            for entry in subfolders + files:
                path = Path(current) / entry
                low = entry.casefold()
                if kind == "xdk":
                    hit = (re.match(r"(xboxsdk|xdk).*\.(iso|zip|7z|rar)$", low) or re.match(r"xdksetup.*\.exe$", low)
                           or (path.is_dir() and low == "include" and next(find_file_shallow(path, "d3d8.h"), None)))
                else:
                    hit = (low.endswith((".iso", ".xiso")) and "halo" in low) or (path.is_dir() and MAPS_FOLDER.match(entry))
                if hit:
                    found.append(path.parent if kind == "game" and path.is_dir() else path)
    unique = list(dict.fromkeys(found))
    return sorted(unique, key=lambda p: -p.stat().st_mtime)


def choose(kind, given, check, what, hint, assume_yes):
    """the input to use: given, a confirmed search result, or one dragged in"""
    if given:
        return given
    for path in candidates(kind)[:12]:
        try:
            ok = check(path)
        except Problem:
            ok = False
        if ok:
            if assume_yes or not sys.stdin.isatty():
                say("Using %s" % path)
                return path
            reply = input("Found %s:\n  %s\nUse it? [Y/n] " % (what, path)).strip().casefold()
            if reply in ("", "y", "yes"):
                return path
    if not sys.stdin.isatty():
        raise Problem("Couldn't find %s. Run this in Terminal, or pass its path." % what)
    say()
    say("Where is %s? %s" % (what, hint))
    say("Drag it into this window, then press Return.")
    while True:
        reply = input("> ").strip()
        if reply:
            path = unquote(reply)
            if path.exists():
                return path
            say("That file or folder doesn't exist. Drag it into this window, then press Return.")


def quick_xdk(path):
    low = path.name.casefold()
    return path.is_dir() and next(find_file_shallow(path, "d3d8.h"), None) is not None or low.endswith((".iso", ".exe") + ARCHIVES)


def quick_game(path):
    if path.is_dir():
        return any(problem_with(FolderGame(root).maps) is None for root in data_roots(path))
    game = open_image(path)
    return game is not None and problem_with(game.maps) is None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--xdk-dest", type=Path, required=True, help="where the SDK's include folder goes (xbox/include)")
    parser.add_argument("--data-dest", type=Path, required=True, help="the game data folder (gets maps/)")
    parser.add_argument("--xdk", type=Path, help="the SDK: disc image, installer, archive or folder")
    parser.add_argument("--data", type=Path, help="the game: disc image, archive or folder")
    parser.add_argument("--yes", action="store_true", help="use what the search finds without asking")
    options = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="halo-inputs-") as temporary:
        scratch = Path(temporary)

        if valid_include(options.xdk_dest) and not options.xdk:
            say("Xbox development kit: already in place.")
        else:
            source = choose("xdk", options.xdk, quick_xdk, "the Xbox development kit (XDK 3911, August 2001)",
                            "It's usually XBOXSDK_3911.ISO or XDKSetupEng.exe.", options.yes)
            include = xdk_from(source, scratch)
            if include is None:
                raise Problem("No Xbox development kit was found in %s. Choose the SDK's disc image, its "
                              "XDKSetupEng.exe, or a folder with xbox/include." % source)
            if options.xdk_dest.exists():
                shutil.rmtree(options.xdk_dest)
            shutil.copytree(include, options.xdk_dest)
            say("Xbox development kit: this is the version Halo needs (XDK 3911).")

        installed = FolderGame(options.data_dest) if options.data_dest.is_dir() else None
        if installed and problem_with(installed.maps) is None and not options.data:
            say("Halo game files: already in place (%s version)." % BUILDS[installed.maps[0].build])
        else:
            source = choose("game", options.data, quick_game, "your Halo game (Halo: Combat Evolved for the original Xbox)",
                            "Usually a disc image ending in .iso, or a folder with a folder called maps in it.", options.yes)
            game = game_from(source, scratch)
            if game is None:
                raise Problem("No Halo game files were found in %s." % source)
            problem = problem_with(game.maps)
            if problem:
                raise Problem(problem)
            say("Halo game files: %d maps, %s version." % (len(game.maps), BUILDS[game.maps[0].build]))
            install_maps(game, options.data_dest)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Problem as problem:
        print("!! %s" % problem, file=sys.stderr, flush=True)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        sys.exit(130)

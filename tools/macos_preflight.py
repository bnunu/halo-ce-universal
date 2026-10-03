#!/usr/bin/env python3
"""Validate Xbox base-map headers without downloading or changing game data.

This checks headers only, not checksums or gameplay compatibility. Exit 0 means
the required menu/opening-level maps and every other present retail map passed;
exit 2 reports missing or incompatible base inputs. Extra files are reported and left to
the engine's own loader. Native Mac builds do not need the private Xbox SDK.
"""

import argparse
import json
from pathlib import Path
import struct
import sys

BUILD = "01.01.14.2342"
NTSC_BUILD = "01.10.12.2276"
SUPPORTED_BUILDS = (BUILD, NTSC_BUILD)
CAMPAIGN = ("a10", "a30", "a50", "b30", "b40", "c10", "c20", "c40", "d20", "d40")
MULTIPLAYER = ("beavercreek", "sidewinder", "damnation", "ratrace", "prisoner",
               "hangemhigh", "chillout", "carousel", "boardingaction", "bloodgulch",
               "wizard", "putput", "longest")
RETAIL_MAPS = frozenset(("ui", *CAMPAIGN, *MULTIPLAYER))


def directory_entries(path):
    """Use Xbox-style case folding, but reject ambiguous extracted names."""
    entries = {}
    for entry in sorted(path.iterdir()):
        key = entry.name.casefold()
        if key in entries:
            raise ValueError(f"ambiguous names: {entries[key].name}, {entry.name}")
        entries[key] = entry
    return entries


def check_map(path):
    """Read only the 0x800-byte Xbox cache header; never execute input files.

    Layout and checks follow source/cache/cache_files.c. File length is the
    decompressed length for compressed Xbox maps, so it must not be compared
    directly with the extracted file's size. This is header validation, not
    a checksum or a gameplay compatibility claim.
    """
    result = {"path": str(path), "valid_header": False, "errors": []}
    try:
        with path.open("rb") as source:
            header = source.read(0x800)
        if len(header) != 0x800:
            raise ValueError("cache header is shorter than 2048 bytes")
        if header[:4] != b"daeh" or header[0x7FC:] != b"toof":
            raise ValueError("not an Xbox cache header (head/foot signatures)")
        version, length = struct.unpack_from("<ii", header, 4)
        name_raw, build_raw = header[0x20:0x40], header[0x40:0x60]
        if b"\0" not in name_raw or b"\0" not in build_raw:
            raise ValueError("unterminated cache name or build string")
        name = name_raw.split(b"\0", 1)[0].decode("ascii")
        build = build_raw.split(b"\0", 1)[0].decode("ascii")
        result.update(name=name, build=build, version=version, declared_length=length)
        if version != 5:
            result["errors"].append(f"cache version {version}; expected Xbox version 5")
        if build not in SUPPORTED_BUILDS:
            result["errors"].append(f"build {build!r}; expected one of {SUPPORTED_BUILDS}")
        if not 0x800 <= length <= 0x11600000:
            result["errors"].append("declared cache length is outside the engine's range")
        if name.casefold() != path.stem.casefold():
            result["errors"].append(f"cache name {name!r} does not match filename")
        result["valid_header"] = not result["errors"]
    except (OSError, ValueError) as error:
        result["errors"].append(str(error))
    return result


def check_data(root):
    result = {"root": str(root), "minimum_maps_ready": False, "maps": [],
              "ignored_extras": [], "errors": []}
    try:
        entries = directory_entries(root)
        maps = root if root.name.casefold() == "maps" else entries.get("maps")
        if maps is None or not maps.is_dir():
            raise ValueError("no maps/ directory; supply an extracted Xbox PAL or USA game directory")
        entries = directory_entries(maps)
        # Match HaloValidateGameData: present retail names must be Xbox maps;
        # additional CE/OpenSauce caches and resource files are not base data.
        # Do not filter retail paths by is_file(): a directory or broken link
        # named after a retail map must fail instead of silently disappearing.
        for path in entries.values():
            if path.suffix.casefold() == ".map" and path.stem.casefold() in RETAIL_MAPS:
                result["maps"].append(check_map(path))
            elif path.suffix.casefold() in (".map", ".yelo"):
                result["ignored_extras"].append({
                    "path": str(path),
                    "reason": "not an Xbox base map; not validated by this check",
                })
        valid = {Path(m["path"]).stem.casefold() for m in result["maps"] if m["valid_header"]}
        result["missing_minimum_maps"] = sorted({"ui", "a10"} - valid)
        result["missing_campaign_maps"] = sorted(set(CAMPAIGN) - valid)
        result["minimum_maps_ready"] = not result["missing_minimum_maps"]
        builds = sorted({m["build"] for m in result["maps"] if m["valid_header"]})
        result["builds"] = builds
        if len(builds) > 1:
            result["minimum_maps_ready"] = False
            result["errors"].append("mixed PAL and NTSC maps; use the maps from one disc")
        for name in result["missing_minimum_maps"]:
            result["errors"].append(f"missing or incompatible {name}.map (required for menu/opening-level testing)")
        if any(not m["valid_header"] for m in result["maps"]):
            result["minimum_maps_ready"] = False
            result["errors"].append("one or more map headers are incompatible; see map details")
    except (OSError, ValueError) as error:
        result["errors"].append(str(error))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True, help="Supplied extracted game directory or maps/ folder")
    parser.add_argument("--output", type=Path, help="also save the JSON report")
    args = parser.parse_args(argv)
    report = {
        "schema_version": 1,
        "gameplay_validated_by_this_check": False,
        "scope": "Xbox base-map header validation only; extra files are not validated",
        "data": check_data(args.data_root.expanduser().resolve()),
    }
    passed = report["data"]["minimum_maps_ready"] and not report["data"]["errors"]
    report["selected_checks_passed"] = bool(passed)
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if passed else 2


if __name__ == "__main__":
    sys.exit(main())

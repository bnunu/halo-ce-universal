#!/usr/bin/env python3
"""Check macOS port prerequisites without downloading or changing game data.

This does not build Halo. Exit 0 means the selected checks passed, 2 means
prerequisites are missing or incompatible. With --probe, compile and run two
small arm64 address-space diagnostics; their output remains under build/.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BUILD = "01.01.14.2342"
NTSC_BUILD = "01.10.12.2276"
SUPPORTED_BUILDS = (BUILD, NTSC_BUILD)
CAMPAIGN = ("a10", "a30", "a50", "b30", "b40", "c10", "c20", "c40", "d20", "d40")
# Same verified SDK input as libs/d3d8/generate_sdk_overlay.py.
D3D8_SHA256 = "7f7f603e1b2fa13ef36a05923eaa36d0d7094302522edbac9855b28f0909f1a1"
SDK_HEADERS = ("xtl.h", "winnt.h", "d3d8.h", "d3d8types.h", "d3d8perf.h", "dsound.h", "xbdm.h")


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
        if not 0 <= length <= 0x11600000:
            result["errors"].append("declared cache length is outside the engine's range")
        if name.casefold() != path.stem.casefold():
            result["errors"].append(f"cache name {name!r} does not match filename")
        result["valid_header"] = not result["errors"]
    except (OSError, ValueError) as error:
        result["errors"].append(str(error))
    return result


def check_data(root):
    result = {"root": str(root), "minimum_maps_ready": False, "maps": [], "errors": []}
    try:
        entries = directory_entries(root)
        maps = root if root.name.casefold() == "maps" else entries.get("maps")
        if maps is None or not maps.is_dir():
            raise ValueError("no maps/ directory; supply an extracted Xbox PAL or USA game directory")
        entries = directory_entries(maps)
        result["maps"] = [check_map(p) for key, p in entries.items() if key.endswith(".map") and p.is_file()]
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
            result["errors"].append("one or more map headers are incompatible; see map details")
    except (OSError, ValueError) as error:
        result["errors"].append(str(error))
    return result


def check_sdk(include):
    result = {"include": str(include), "ready": False, "errors": []}
    try:
        entries = directory_entries(include)
        missing = [name for name in SDK_HEADERS if name not in entries or not entries[name].is_file()]
        if missing:
            result["errors"].append("missing SDK headers: " + ", ".join(missing))
        d3d = entries.get("d3d8.h")
        if d3d and d3d.is_file():
            digest = hashlib.sha256(d3d.read_bytes()).hexdigest()
            result["d3d8_sha256"] = digest
            if digest != D3D8_SHA256:
                result["errors"].append("D3D8.h differs from this repository's verified SDK input")
        result["ready"] = not result["errors"]
    except (OSError, ValueError) as error:
        result["errors"].append(str(error))
    return result


def run_probe(compiler, output):
    result = {"compatible_with_existing_android_memory": False, "variants": [], "errors": []}
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        result["errors"].append("run the probe in a native arm64 process on an Apple Silicon Mac")
        return result
    output.mkdir(parents=True, exist_ok=True)
    for name, flags in (("default", []), ("small-pagezero", ["-Wl,-pagezero_size,0x4000"])):
        executable = (output / f"memory-probe-{name}").resolve()
        command = [compiler, "-arch", "arm64", "-Wall", "-Wextra", "-Werror", *flags,
                   str(ROOT / "port/macos/memory_probe.c"), "-o", str(executable)]
        variant = {"name": name, "command": command}
        result["variants"].append(variant)
        try:
            compiled = subprocess.run(command, capture_output=True, text=True, timeout=30)
            variant["compile_returncode"] = compiled.returncode
            variant["compile_output"] = compiled.stdout + compiled.stderr
            if compiled.returncode:
                continue
            executed = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
            variant["returncode"] = executed.returncode
            variant["stderr"] = executed.stderr
            if executed.returncode < 0:
                variant["signal"] = signal.Signals(-executed.returncode).name
            if executed.stdout:
                variant["measurement"] = json.loads(executed.stdout)
                if executed.returncode == 0 and variant["measurement"]["page_size"] == 4096:
                    result["compatible_with_existing_android_memory"] = True
        except (OSError, subprocess.TimeoutExpired, ValueError) as error:
            variant["error"] = str(error)
    if not result["compatible_with_existing_android_memory"]:
        result["errors"].append("existing Android memory assumptions are not verified: require low-4-GB mappings and 4096-byte pages")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-include", type=Path, default=ROOT / "xbox/include")
    parser.add_argument("--data-root", type=Path, default=Path(os.environ.get("HALO_DATA_ROOT", ROOT / "assets")))
    parser.add_argument("--probe", action="store_true", help="compile/run native address-space diagnostics")
    parser.add_argument("--cc", default="clang", help="host compiler for --probe")
    parser.add_argument("--output", type=Path, help="also save the JSON report")
    args = parser.parse_args(argv)
    report = {
        "schema_version": 1,
        "macos_game_build_available": (ROOT / "build/macos/halo").is_file() and (ROOT / "build/macos/halo_guest.elf").is_file(),
        "gameplay_validated_by_this_check": False,
        "scope": "input checks only; use tools/macos_build.py to build and tools/test_macos_runtime.py for ABI checks",
        "host": {"system": platform.system(), "machine": platform.machine(), "macos": platform.mac_ver()[0]},
        "tools": {name: shutil.which(name) for name in ("clang", "cmake", "ninja", "codesign")},
        "sdk": check_sdk(args.sdk_include.expanduser().resolve()),
        "data": check_data(args.data_root.expanduser().resolve()),
    }
    passed = report["sdk"]["ready"] and report["data"]["minimum_maps_ready"] and not report["data"]["errors"]
    if args.probe:
        try:
            report["memory_probe"] = run_probe(args.cc, ROOT / "build/macos/preflight")
        except OSError as error:
            report["memory_probe"] = {"compatible_with_existing_android_memory": False, "errors": [str(error)]}
        passed = passed and report["memory_probe"]["compatible_with_existing_android_memory"]
    report["selected_checks_passed"] = bool(passed)
    rendered = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if passed else 2


if __name__ == "__main__":
    sys.exit(main())

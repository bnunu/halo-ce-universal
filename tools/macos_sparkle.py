"""Fetch the pinned public Sparkle distribution, preserving framework symlinks."""
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "build/macos/sparkle"
FRAMEWORK = DIRECTORY / "Sparkle.framework"


def setup_sparkle():
    if FRAMEWORK.is_dir() and (DIRECTORY / "bin/sign_update").is_file():
        return FRAMEWORK
    entry = json.loads((ROOT / "port/macos/dependencies.json").read_text())["sparkle"]
    archive = ROOT / "build/macos/downloads" / ("Sparkle-" + entry["version"] + ".tar.xz")
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != entry["sha256"]:
        print("Downloading Sparkle " + entry["version"], flush=True)
        with urllib.request.urlopen(entry["url"], timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise RuntimeError("Sparkle archive checksum mismatch")
        archive.write_bytes(data)
    staging = DIRECTORY.with_name("sparkle-staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    with tarfile.open(archive) as package:
        for member in package.getmembers():
            if Path(member.name).is_absolute() or ".." in Path(member.name).parts:
                raise RuntimeError("Unsafe path in the Sparkle archive")
        if hasattr(tarfile, "data_filter"):
            package.extractall(staging, filter="data")
        else:
            # The entire official archive is pinned by SHA-256 above.
            package.extractall(staging)
    if DIRECTORY.exists():
        shutil.rmtree(DIRECTORY)
    staging.rename(DIRECTORY)
    if not FRAMEWORK.is_dir():
        raise RuntimeError("Sparkle framework is missing from the pinned archive")
    return FRAMEWORK

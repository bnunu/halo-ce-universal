"""Exercise asset intake using synthetic headers, never proprietary assets."""
import contextlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest

from tools import macos_preflight as preflight


def cache_header(name="a10", build=preflight.BUILD, version=5):
    header = bytearray(0x800)
    header[:4] = b"daeh"
    # A compressed map's declared length exceeds the file's actual length.
    struct.pack_into("<ii", header, 4, version, 0x100000)
    header[0x20:0x20 + len(name)] = name.encode("ascii")
    header[0x40:0x40 + len(build)] = build.encode("ascii")
    header[0x7FC:] = b"toof"
    return header


class AssetIntakeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="halo assets ")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_pal_header_and_compressed_length(self):
        path = self.root / "a10.map"
        path.write_bytes(cache_header())
        self.assertTrue(preflight.check_map(path)["valid_header"])

    def test_wrong_build_and_pc_format_rejected(self):
        path = self.root / "a10.map"
        path.write_bytes(cache_header(build="01.00.00.0000", version=7))
        result = preflight.check_map(path)
        self.assertFalse(result["valid_header"])
        self.assertEqual(len(result["errors"]), 2)

    def test_retail_ntsc_header_accepted(self):
        path = self.root / "a10.map"
        path.write_bytes(cache_header(build=preflight.NTSC_BUILD))
        self.assertTrue(preflight.check_map(path)["valid_header"])

    def test_mixed_pal_ntsc_maps_rejected(self):
        maps = self.root / "maps"
        maps.mkdir()
        (maps / "a10.map").write_bytes(cache_header("a10"))
        (maps / "ui.map").write_bytes(cache_header("ui", build=preflight.NTSC_BUILD))
        result = preflight.check_data(self.root)
        self.assertFalse(result["minimum_maps_ready"])
        self.assertIn("mixed PAL and NTSC", result["errors"][0])

    def test_truncated_or_bad_signature_rejected(self):
        path = self.root / "a10.map"
        for content in (b"", cache_header()[:100], b"x" * 0x800):
            with self.subTest(length=len(content)):
                path.write_bytes(content)
                self.assertFalse(preflight.check_map(path)["valid_header"])

    def test_unterminated_strings_rejected(self):
        path = self.root / "a10.map"
        for offset in (0x20, 0x40):
            header = cache_header()
            header[offset:offset + 32] = b"x" * 32
            path.write_bytes(header)
            self.assertFalse(preflight.check_map(path)["valid_header"])

    def test_renamed_map_rejected(self):
        path = self.root / "ui.map"
        path.write_bytes(cache_header("a10"))
        self.assertFalse(preflight.check_map(path)["valid_header"])

    def test_case_insensitive_maps_and_direct_maps_path(self):
        maps = self.root / "MAPS"
        maps.mkdir()
        for name in ("a10", "ui"):
            (maps / f"{name.upper()}.MAP").write_bytes(cache_header(name))
        for root in (self.root, maps):
            result = preflight.check_data(root)
            self.assertTrue(result["minimum_maps_ready"])
            self.assertEqual(len(result["missing_campaign_maps"]), 9)

    def test_empty_maps_not_ready(self):
        (self.root / "maps").mkdir()
        result = preflight.check_data(self.root)
        self.assertFalse(result["minimum_maps_ready"])
        self.assertEqual(result["missing_minimum_maps"], ["a10", "ui"])

    def test_wrong_sdk_rejected(self):
        for name in preflight.SDK_HEADERS:
            (self.root / name).write_bytes(b"not the SDK")
        result = preflight.check_sdk(self.root)
        self.assertFalse(result["ready"])
        self.assertIn("verified SDK input", result["errors"][0])

    def test_missing_inputs_produce_actionable_json_and_nonzero_exit(self):
        output = self.root / "report.json"
        with contextlib.redirect_stdout(io.StringIO()):
            code = preflight.main(["--data-root", str(self.root / "absent"),
                                   "--sdk-include", str(self.root / "absent"),
                                   "--output", str(output)])
        report = json.loads(output.read_text())
        self.assertEqual(code, 2)
        self.assertFalse(report["gameplay_validated_by_this_check"])
        self.assertFalse(report["selected_checks_passed"])
        self.assertTrue(report["sdk"]["errors"])
        self.assertTrue(report["data"]["errors"])


if __name__ == "__main__":
    unittest.main()

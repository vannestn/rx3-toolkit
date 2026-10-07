"""Pre-gig USB preparation tests use disposable folders, never a mounted stick."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scripts import pre_gig


def tag(name, body, header=12):
    out = bytearray(header + len(body))
    out[:4] = name
    out[4:8] = header.to_bytes(4, "big")
    out[8:12] = len(out).to_bytes(4, "big")
    out[header:] = body
    return bytes(out)


def pmai(*tags):
    out = bytearray(28)
    out[:4] = b"PMAI"
    out[4:8] = (28).to_bytes(4, "big")
    out.extend(b"".join(tags))
    out[8:12] = len(out).to_bytes(4, "big")
    return bytes(out)


def fixture_analysis():
    grid = bytearray(24 + 3 * 8)
    grid[:4] = b"PQTZ"
    grid[4:8] = (24).to_bytes(4, "big")
    grid[8:12] = len(grid).to_bytes(4, "big")
    grid[20:24] = (3).to_bytes(4, "big")
    for i in range(3):
        offset = 24 + i * 8
        grid[offset:offset + 2] = (i + 1).to_bytes(2, "big")
        grid[offset + 2:offset + 4] = (12000).to_bytes(2, "big")
        grid[offset + 4:offset + 8] = (i * 500).to_bytes(4, "big")
    phrase = bytearray(32 + 24)
    phrase[:4] = b"PSSI"
    phrase[4:8] = (32).to_bytes(4, "big")
    phrase[8:12] = len(phrase).to_bytes(4, "big")
    phrase[0x10:0x12] = (1).to_bytes(2, "big")
    phrase[0x12:0x14] = (1).to_bytes(2, "big")
    phrase[0x1a:0x1c] = (4).to_bytes(2, "big")
    phrase[0x20:0x22] = (1).to_bytes(2, "big")
    phrase[0x22:0x24] = (1).to_bytes(2, "big")
    phrase[0x24:0x26] = (1).to_bytes(2, "big")
    phrase[0x27] = 1
    return pmai(bytes(grid)), pmai(bytes(phrase))


class FakeResolve:
    @staticmethod
    def load(_path):
        return {7: {"id": 7, "title": "Test", "anlz_path":
                    "/PIONEER/USBANLZ/P001/ANLZ0000.DAT"}}


class PreGigTests(unittest.TestCase):
    def test_phrase_and_grid_extraction_preserves_boundaries(self):
        dat, ext = fixture_analysis()
        result = pre_gig.decode_analysis(dat, ext)
        self.assertEqual(result["phrase_status"], "ready")
        self.assertEqual([x["time_ms"] for x in result["grid"]], [0, 500, 1000])
        self.assertEqual(result["phrases"][0]["end_beat"], 4)
        broken = bytearray(ext)
        broken[-1:] = b""
        broken[8:12] = len(broken).to_bytes(4, "big")
        with self.assertRaisesRegex(ValueError, "section length"):
            pre_gig.decode_analysis(dat, bytes(broken))
        self.assertEqual(pre_gig.decode_analysis(dat, None)["phrase_status"],
                         "missing_pssi")
        bad_pssi = bytearray(ext)
        bad_pssi[28 + 0x10:28 + 0x12] = (2).to_bytes(2, "big")
        self.assertEqual(pre_gig.decode_analysis(dat, bytes(bad_pssi))
                         ["phrase_status"], "invalid_pssi")

    def test_scan_is_read_only_and_confines_export_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "usb"
            out = Path(directory) / "cache"
            pdb = root / "PIONEER/rekordbox/export.pdb"
            pdb.parent.mkdir(parents=True)
            pdb.write_bytes(b"fixture-db")
            dat, ext = fixture_analysis()
            path = root / "PIONEER/USBANLZ/P001/ANLZ0000.DAT"
            path.parent.mkdir(parents=True)
            path.write_bytes(dat)
            path.with_suffix(".EXT").write_bytes(ext)
            before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            with patch.object(pre_gig, "load_tracks", return_value=FakeResolve.load(pdb)):
                summary = pre_gig.scan(root, out)
            self.assertEqual((summary["track_count"], summary["ready"]), (1, 1))
            self.assertEqual(json.loads((out / "analysis/7.json").read_text())
                             ["phrases"][0]["label"], "Intro 1")
            self.assertEqual(before, {str(p.relative_to(root)): p.read_bytes()
                                      for p in root.rglob("*") if p.is_file()})
            for bad in ("/PIONEER/USBANLZ/../../secret", "/other/path.DAT"):
                with self.assertRaises(ValueError):
                    pre_gig.usb_file(root, bad)

    def test_install_requires_matching_audit_and_backs_up_root_only(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root, cache, package = (base / name for name in ("usb", "cache", "package"))
            (root / "PIONEER/rekordbox").mkdir(parents=True)
            (root / "PIONEER/rekordbox/export.pdb").write_bytes(b"fixture-db")
            (root / "autoexec.bin").write_bytes(b"old-image")
            cache.mkdir()
            (cache / "manifest.json").write_text(json.dumps({
                "export_pdb_sha256": hashlib.sha256(b"fixture-db").hexdigest()}))
            (cache / "tracks.json").write_text("{}")
            package.mkdir()
            image = b"new-image"
            (package / "autoexec.bin").write_bytes(image)
            manifest = {"firmware": "1.19", "modules":
                        ["core", "now-playing", "position-diagnostic"],
                        "bytes": len(image), "sha256": hashlib.sha256(image).hexdigest()}
            (package / "rx3-mod-manifest.json").write_text(json.dumps(manifest))
            audit = {"firmware": "1.19", "modules": manifest["modules"],
                     "package_sha256": manifest["sha256"], "unexpected_imports": [],
                     "result": "exact source and independently built hook match; not hardware certification"}
            (package / "package-audit.json").write_text(json.dumps(audit))
            with self.assertRaisesRegex(ValueError, "audit/firmware"):
                pre_gig.install(root, cache, package, "1.20")
            result = pre_gig.install(root, cache, package, "1.19")
            self.assertEqual(result["package_sha256"], manifest["sha256"])
            self.assertEqual((cache / "usb-root-backup/autoexec.bin").read_bytes(), b"old-image")
            self.assertEqual((root / "autoexec.bin").read_bytes(), image)
            self.assertEqual((root / "PIONEER/rekordbox/export.pdb").read_bytes(), b"fixture-db")


if __name__ == "__main__":
    unittest.main()

"""Isolated host tests for the RX3's read-only metadata transport."""
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from remote_metadata import fetch, validate_analysis_path


class MetadataTransportTests(unittest.TestCase):
    def test_path_restrictions_and_read_only_file_service(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "usb"
            pdb = root / "PIONEER/rekordbox/export.pdb"
            dat = root / "PIONEER/USBANLZ/P001/00000001/ANLZ0000.DAT"
            music = root / "MUSIC/song.wav"
            for path, payload in ((pdb, b"export"), (dat, b"analysis"),
                                  (music, b"private-audio")):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
            (root / "PIONEER/USBANLZ/P002").symlink_to(music.parent,
                                                          target_is_directory=True)
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            binary = base / "metadata-server"
            source = Path(__file__).resolve().parents[1] / "mod/lib/metadata_server.c"
            subprocess.run(["clang", "-DLOCAL_TEST", f"-DMETADATA_PORT={port}",
                            "-O2", "-Wall", "-Wextra", "-Werror", str(source),
                            "-o", str(binary)], check=True, capture_output=True)
            process = subprocess.Popen([str(binary), str(root)])
            try:
                for _ in range(50):
                    if process.poll() is not None:
                        self.fail(f"metadata process exited {process.returncode}")
                    try:
                        self.assertEqual(fetch("127.0.0.1", "PDB", 1024, port), b"export")
                        break
                    except OSError:
                        time.sleep(.01)
                else:
                    self.fail("metadata process did not listen")
                self.assertEqual(fetch("127.0.0.1", "ANLZ " +
                                       "/PIONEER/USBANLZ/P001/00000001/ANLZ0000.DAT",
                                       1024, port), b"analysis")
                for request in ("ANLZ /PIONEER/USBANLZ/../../MUSIC/song.wav",
                                "ANLZ /MUSIC/song.wav", "ANLZ /PIONEER/USBANLZ/P001/"
                                "00000001/../../MUSIC/song.wav",
                                "ANLZ /PIONEER/USBANLZ/P002/ANLZ0000.DAT"):
                    with self.assertRaises(OSError):
                        fetch("127.0.0.1", request, 1024, port)
                with self.assertRaises(ValueError):
                    validate_analysis_path("/PIONEER/USBANLZ/../song.wav")
                self.assertEqual(music.read_bytes(), b"private-audio")
            finally:
                process.terminate()
                process.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()

"""Read-only RX3 USB-B metadata client for the isolated on-deck file service.

Only rekordbox export and analysis files are requested. No audio is transferred.
The deck reads USB files in a separate process; Python parses on the computer.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import PurePosixPath
import socket
import threading
import time

from pre_gig import decode_analysis, load_tracks

MAX_PDB = 16 * 1024 * 1024
MAX_ANALYSIS = 4 * 1024 * 1024


def validate_analysis_path(path: str) -> str:
    if not isinstance(path, str) or not path.startswith("/PIONEER/USBANLZ/"):
        raise ValueError("analysis path outside USBANLZ")
    parts = PurePosixPath(path).parts
    if (".." in parts or len(path) > 228 or
            any(not part.replace(".", "").isalnum() for part in parts[1:]) or
            parts[-1] != "ANLZ0000.DAT"):
        raise ValueError("unsafe analysis path")
    return path


def fetch(host: str, request: str, limit: int, port: int = 50131) -> bytes:
    with socket.create_connection((host, port), timeout=3) as sock:
        sock.settimeout(5)
        sock.sendall((request + "\n").encode("ascii"))
        with sock.makefile("rb") as stream:
            if stream.readline(8) != b"OK\n":
                raise OSError("RX3 metadata service refused the request")
            data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("RX3 metadata response exceeds limit")
    return data


class RemoteCatalog:
    def __init__(self, host: str, port: int = 50131):
        self.host, self.port = host, port
        raw = fetch(host, "PDB", MAX_PDB, port)
        # The existing defensive parser accepts a Path. Keep the copy in
        # private host temp storage only long enough to parse it.
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory(prefix="rx3-remote-pdb-") as directory:
            source = Path(directory) / "export.pdb"
            source.write_bytes(raw)
            rows = load_tracks(source)
        if not rows:
            raise ValueError("remote export contains no tracks")
        self.manifest = {"schema": "rx3-remote/1",
                         "export_pdb_sha256": hashlib.sha256(raw).hexdigest()}
        self.tracks = {str(track_id): {"metadata": meta, "asset": None,
                                       "analysis_error": None}
                       for track_id, meta in rows.items()}
        self._pending: set[str] = set()
        self._last_attempt: dict[str, float] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rx3-analysis")

    def request(self, track_id: int | None) -> None:
        key = str(track_id)
        item = self.tracks.get(key)
        if item is None or item.get("asset") is not None:
            return
        with self._lock:
            if (key in self._pending or len(self._pending) >= 2 or
                    time.monotonic()-self._last_attempt.get(key, -1e9) < 30):
                return
            self._pending.add(key)
            self._last_attempt[key] = time.monotonic()
        self._pool.submit(self._download, key)

    def _download(self, key: str) -> None:
        try:
            path = validate_analysis_path(self.tracks[key]["metadata"]["anlz_path"])
            dat = fetch(self.host, "ANLZ " + path, MAX_ANALYSIS, self.port)
            try:
                ext = fetch(self.host, "ANLZ " + path[:-4] + ".EXT",
                            MAX_ANALYSIS, self.port)
            except OSError:
                ext = None
            if hashlib.sha256(fetch(self.host, "PDB", MAX_PDB, self.port)).hexdigest() != \
                    self.manifest["export_pdb_sha256"]:
                raise ValueError("mounted export changed during analysis fetch")
            decoded = decode_analysis(dat, ext)
            asset = {**decoded, "schema": "rx3-analysis/1", "track_id": int(key),
                     "export_pdb_sha256": self.manifest["export_pdb_sha256"],
                     "dat_sha256": hashlib.sha256(dat).hexdigest(),
                     "ext_sha256": hashlib.sha256(ext).hexdigest() if ext else None}
            self.tracks[key] = {**self.tracks[key], "asset": asset,
                                "analysis_error": None}
        except (OSError, ValueError) as exc:
            # Retain the track's PDB identity, but do not assert beat/phrase.
            self.tracks[key] = {**self.tracks[key], "analysis_error": str(exc)[:160]}
        finally:
            with self._lock:
                self._pending.discard(key)

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

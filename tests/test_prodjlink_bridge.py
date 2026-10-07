"""Contract behavior for the host-only RX3 live bridge."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest

from scripts.prodjlink_bridge import BridgeState, musical_position


def asset():
    return {"dat_sha256": "dat-hash", "phrase_status": "ready",
            "grid": [{"beat": i, "time_ms": (i-1)*500,
                      "count_in_bar": i, "bpm_x100": 12000} for i in range(1, 5)],
            "phrases": [{"index": 1, "beat": 1, "end_beat": 3, "label": "Intro 1"},
                        {"index": 2, "beat": 3, "end_beat": 5, "label": "Chorus 1"}]}


def now_message(track_id=7, mode=2, bpm=12000, loaded=True):
    return json.dumps({"type": "now-playing", "version": 1, "sequence": 1,
                       "decks": [{"deck": 1, "loaded": loaded, "onAir": True,
                                  "trackId": track_id, "bpmX100": bpm,
                                  "tempoRaw": 0, "playModeRaw": mode, "title": ""},
                                 {"deck": 2, "loaded": False, "onAir": False,
                                  "trackId": 0, "bpmX100": 0, "tempoRaw": 0,
                                  "playModeRaw": 0, "title": ""}]}).encode()


def pos_message(position=22050, generation=1):
    return json.dumps({"type": "position-diagnostic", "version": 1,
                       "sequence": 1, "units": "unverified", "decks": [
                           {"deck": 1, "readerGeneration": generation,
                            "sample": {"generation": generation,
                                       "observation": 1, "rawPosition": position,
                                       "frames": 512}},
                           {"deck": 2, "readerGeneration": 0,
                            "sample": None}]}).encode()


class BridgeTests(unittest.TestCase):
    def make_state(self):
        return BridgeState({"export_pdb_sha256": "export-hash"},
                           {"7": {"metadata": {"title": "Test", "artist": "Artist",
                                               "duration_s": 100}, "asset": asset()},
                            "8": {"metadata": {"title": "Second", "duration_s": 120},
                                  "asset": asset()}}, "1.19")

    def test_grid_interpolation_and_phrase_boundary(self):
        timing, phrase = musical_position(asset(), 750)
        self.assertEqual(timing["beat_number"], 2)
        self.assertEqual(timing["beat_phase"], 0.5)
        self.assertEqual(timing["fractional_beat"], 2.5)
        self.assertEqual(phrase["section"], "Intro 1")
        self.assertEqual(phrase["progress_01"], 0.75)
        self.assertEqual(phrase["beats_to_boundary"], 0.5)
        timing, phrase = musical_position(asset(), 1000)
        self.assertEqual(phrase["section"], "Chorus 1")
        self.assertEqual(phrase["progress_01"], 0)
        self.assertFalse(musical_position(asset(), -1)[1]["valid"])

    def test_live_join_stale_and_track_change_waits_for_new_reader(self):
        state = self.make_state()
        self.assertTrue(state.ingest("now-playing", now_message(), "169.254.1.2", 10.0))
        self.assertTrue(state.ingest("position-diagnostic", pos_message(), "169.254.1.2", 10.0))
        first = state.snapshot(1, 10.1)
        self.assertEqual(first["track"]["title"], "Test")
        self.assertAlmostEqual(first["timing"]["position_ms"], 500)
        self.assertEqual(first["timing"]["beat_number"], 2)
        self.assertEqual(first["phrase"]["section"], "Intro 1")
        self.assertFalse(first["mixer"]["valid"])
        self.assertTrue(state.snapshot(1, 10.6)["timing"]["valid"] is False)
        self.assertTrue(state.ingest("now-playing", now_message(8), "169.254.1.2", 11))
        self.assertTrue(state.ingest("position-diagnostic", pos_message(44100, 1),
                                     "169.254.1.2", 11))
        waiting = state.snapshot(1, 11.1)
        self.assertEqual(waiting["track"]["title"], "Second")
        self.assertFalse(waiting["timing"]["valid"])
        self.assertTrue(state.ingest("position-diagnostic", pos_message(44100, 2),
                                     "169.254.1.2", 11.2))
        ready = state.snapshot(1, 11.2)
        self.assertAlmostEqual(ready["timing"]["position_ms"], 1000)
        self.assertEqual(ready["track"]["load_generation"], 2)
        self.assertFalse(state.ingest("now-playing", now_message(), "169.254.9.9", 11.3))

    def test_pause_loop_and_unload(self):
        state = self.make_state()
        state.ingest("now-playing", now_message(mode=3), "169.254.1.2", 1)
        state.ingest("position-diagnostic", pos_message(), "169.254.1.2", 1)
        self.assertTrue(state.snapshot(1, 1)["transport"]["loop_active"])
        before_jump = state.snapshot(1, 1)["timing"]["discontinuity_id"]
        state.ingest("position-diagnostic", pos_message(position=90000),
                     "169.254.1.2", 1.1)
        state.ingest("position-diagnostic", pos_message(position=22050),
                     "169.254.1.2", 1.2)
        self.assertGreater(state.snapshot(1, 1.2)["timing"]["discontinuity_id"],
                           before_jump)
        state.ingest("now-playing", now_message(mode=4), "169.254.1.2", 2)
        self.assertFalse(state.snapshot(1, 2)["transport"]["playing"])
        state.ingest("now-playing", now_message(loaded=False), "169.254.1.2", 3)
        self.assertFalse(state.snapshot(1, 3)["track"]["valid"])
        self.assertFalse(state.snapshot(1, 3)["timing"]["valid"])
        state.ingest("now-playing", now_message(), "169.254.1.2", 3.1)
        state.ingest("position-diagnostic", pos_message(generation=1),
                     "169.254.1.2", 3.1)
        self.assertFalse(state.snapshot(1, 3.1)["timing"]["valid"])
        state.ingest("position-diagnostic", pos_message(generation=2),
                     "169.254.1.2", 3.2)
        self.assertTrue(state.snapshot(1, 3.2)["timing"]["valid"])

    def test_local_tcp_port_streams_contract_snapshots(self):
        def free_port(sock_type):
            with socket.socket(socket.AF_INET, sock_type) as sock:
                sock.bind(("127.0.0.1", 0))
                return sock.getsockname()[1]

        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory)
            (catalog / "analysis").mkdir()
            (catalog / "manifest.json").write_text(json.dumps({
                "schema": "rx3-pre-gig/1", "export_pdb_sha256": "export-hash"}))
            (catalog / "tracks.json").write_text(json.dumps({"7": {
                "metadata": {"title": "Test", "duration_s": 100},
                "analysis": "analysis/7.json"}}))
            (catalog / "analysis/7.json").write_text(json.dumps({
                **asset(), "track_id": 7, "export_pdb_sha256": "export-hash"}))
            tcp = free_port(socket.SOCK_STREAM)
            udp_now = free_port(socket.SOCK_DGRAM)
            udp_position = free_port(socket.SOCK_DGRAM)
            command = [sys.executable, str(Path(__file__).resolve().parents[1] /
                                           "scripts/prodjlink_bridge.py"),
                       "--catalog", str(catalog), "--firmware", "1.19",
                       "--port", str(tcp), "--now-port", str(udp_now),
                       "--position-port", str(udp_position), "--source", "127.0.0.1"]
            process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True)
            try:
                self.assertIn("listening", process.stdout.readline())
                with socket.create_connection(("127.0.0.1", tcp), timeout=2) as client:
                    client.settimeout(3)
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
                        sender.sendto(now_message(), ("127.0.0.1", udp_now))
                        sender.sendto(pos_message(), ("127.0.0.1", udp_position))
                    with client.makefile("r", encoding="utf-8") as stream:
                        matched = None
                        for _ in range(20):
                            event = json.loads(stream.readline())
                            if event["deck_index"] == 0 and event["timing"]["valid"]:
                                matched = event
                                break
                        self.assertIsNotNone(matched)
                        self.assertEqual(matched["track"]["title"], "Test")
                        self.assertEqual(matched["phrase"]["section"], "Intro 1")
            finally:
                process.terminate()
                process.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()

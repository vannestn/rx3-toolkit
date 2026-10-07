"""Retention and time-window tests for the passive USB-B recorder."""
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import rolling_diagnostic_listener as rolling


class RollingListenerTests(unittest.TestCase):
    def test_retains_only_fifteen_minutes_and_queries_after_message_time(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'events.sqlite3'
            db = rolling.connect(path)
            now = 1_800_000_000_000_000_000
            old = now-rolling.WINDOW_NS-1
            edge = now-rolling.WINDOW_NS
            rolling.record(db, old, 'now-playing', '169.254.1.2', {'raw': {'sequence': 1}})
            rolling.record(db, edge, 'now-playing', '169.254.1.2', {'raw': {'sequence': 2}})
            rolling.record(db, now-10_000_000_000, 'position-diagnostic', '169.254.1.2',
                           {'raw': {'sequence': 3}})
            # Backfill may arrive after live packets; queries remain time ordered.
            rolling.record(db, now-15_000_000_000, 'status', '169.254.1.2',
                           {'text': 'complete'})
            rolling.prune(db, now)
            db.commit()
            self.assertEqual([r[0] for r in rolling.recent(db, 0, now)],
                             [edge, now-15_000_000_000, now-10_000_000_000])
            self.assertEqual([r[0] for r in rolling.recent(db, now-5_000_000_000, now)], [])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0], 3)
            db.close()
            with sqlite3.connect(path) as reader:
                self.assertEqual(len(rolling.recent(reader, now-20_000_000_000, now)), 2)


if __name__ == '__main__':
    unittest.main()

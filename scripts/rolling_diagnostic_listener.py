#!/usr/bin/env python3
"""Receive-only RX3 USB-B telemetry, retaining a rolling 15-minute SQLite window.

Run this in the background for a test session. It deliberately has no restart
service: rebooting the computer ends it. The database is local and ignored.
"""
import argparse
import ipaddress
import json
import math
from pathlib import Path
import selectors
import signal
import socket
import sqlite3
import time

from position_diagnostic import ObservationAges, validate as validate_position
from startup_report import ReportAssembler
from telemetry_diagnostic import validate as validate_now_playing


PORTS = {50125: 'preflight', 50126: 'status', 50123: 'now-playing',
         50124: 'position-diagnostic'}
WINDOW_NS = 15 * 60 * 1_000_000_000


def connect(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=5)
    db.execute('PRAGMA journal_mode=TRUNCATE')
    db.execute('PRAGMA synchronous=NORMAL')
    db.execute('CREATE TABLE IF NOT EXISTS events ('
               'id INTEGER PRIMARY KEY, wall_ns INTEGER NOT NULL, '
               'event TEXT NOT NULL, source TEXT NOT NULL, payload TEXT NOT NULL)')
    db.execute('CREATE INDEX IF NOT EXISTS events_time ON events(wall_ns)')
    prune(db, time.time_ns())
    db.commit()
    return db


def prune(db, now_ns):
    db.execute('DELETE FROM events WHERE wall_ns < ?', (now_ns-WINDOW_NS,))


def record(db, now_ns, event, source, payload):
    db.execute('INSERT INTO events(wall_ns,event,source,payload) VALUES (?,?,?,?)',
               (now_ns, event, source, json.dumps(payload, ensure_ascii=False)))


def recent(db, since_ns, now_ns):
    lower = max(since_ns, now_ns-WINDOW_NS)
    return list(db.execute('SELECT wall_ns,event,source,payload FROM events '
                           'WHERE wall_ns >= ? AND wall_ns <= ? ORDER BY wall_ns,id',
                           (lower, now_ns)))


def listen(path, source=None, ports=PORTS):
    db = connect(path)
    assemblers = {kind: ReportAssembler() for kind in ('preflight', 'status')}
    ages = ObservationAges()
    last = {}
    stopped = False

    def stop(_signum, _frame):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with selectors.DefaultSelector() as selector:
        for port, kind in ports.items():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.bind(('', port))
                sock.setblocking(False)
                selector.register(sock, selectors.EVENT_READ, kind)
            except BaseException:
                sock.close()
                raise
        print(f'RX3 rolling listener active: {path} (15-minute retention)', flush=True)
        last_maintenance = time.monotonic()
        try:
            while not stopped:
                for key, _ in selector.select(.25):
                    data, address = key.fileobj.recvfrom(4097)
                    peer = address[0]
                    try:
                        if source and peer != source:
                            continue
                        if not source and not ipaddress.IPv4Address(peer).is_link_local:
                            continue
                    except ValueError:
                        continue
                    kind = key.data
                    now_mono = time.monotonic()
                    now_ns = time.time_ns()
                    if kind in assemblers:
                        try:
                            completed = assemblers[kind].accept(data, peer)
                        except (ValueError, UnicodeDecodeError):
                            continue
                        if completed is None:
                            continue
                        payload = {'text': completed.decode('utf-8')}
                        # Reset after a completed report so later insertions can
                        # report again, even when content or length changes.
                        assemblers[kind] = ReportAssembler()
                    else:
                        validator = (validate_position if kind == 'position-diagnostic'
                                     else validate_now_playing)
                        value = validator(data)
                        if value is None:
                            continue
                        payload = {'raw': value}
                        if kind == 'position-diagnostic':
                            payload['observationAgeS'] = ages.update(value, now_mono)
                        last[kind] = now_mono
                    record(db, now_ns, kind, peer, payload)
                now_mono = time.monotonic()
                if now_mono-last_maintenance >= 1:
                    for kind, then in list(last.items()):
                        if then is not None and now_mono-then > 3:
                            record(db, time.time_ns(), 'stale', '', {'stream': kind})
                            last[kind] = None
                    prune(db, time.time_ns())
                    db.commit()
                    last_maintenance = now_mono
        finally:
            db.commit()
            db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path,
                        default=Path('local/captures/rx3-rolling.sqlite3'))
    parser.add_argument('--source', help='Exact USB peer IPv4; default accepts link-local only')
    parser.add_argument('--show-last-seconds', type=float,
                        help='Read records from the last N seconds, without listening')
    parser.add_argument('--since-epoch', type=float,
                        help='Read records since this Unix timestamp, without listening')
    args = parser.parse_args()
    if args.source:
        ipaddress.IPv4Address(args.source)
    if args.show_last_seconds is not None or args.since_epoch is not None:
        if args.show_last_seconds is not None and args.since_epoch is not None:
            parser.error('choose one read interval')
        requested = (args.since_epoch if args.since_epoch is not None
                     else args.show_last_seconds)
        if not math.isfinite(requested) or requested < 0:
            parser.error('read interval must be finite and nonnegative')
        if not args.database.exists():
            parser.error('database does not exist')
        now_ns = time.time_ns()
        since_ns = (int(args.since_epoch*1e9) if args.since_epoch is not None
                    else now_ns-int(args.show_last_seconds*1e9))
        with sqlite3.connect(args.database) as db:
            for wall_ns, event, source, payload in recent(db, since_ns, now_ns):
                print(json.dumps({'wallTime': wall_ns/1e9, 'event': event,
                                  'source': source, **json.loads(payload)},
                                 ensure_ascii=False))
        return
    listen(args.database, args.source)


if __name__ == '__main__':
    main()

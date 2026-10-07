#!/usr/bin/env python3
"""Receive-only raw RX3 position + Now Playing capture; no inferred track-time mapping."""
import argparse
import ipaddress
import json
import math
from pathlib import Path
import selectors
import socket
import time
from telemetry_diagnostic import validate as validate_now_playing


def uint(value):
    return type(value) is int and 0 <= value <= 0xffffffff


def validate(data):
    if len(data) > 4096:
        return None
    try:
        message = json.loads(data)
    except (ValueError, UnicodeError, RecursionError):
        return None
    if not isinstance(message, dict) or message.get('type') != 'position-diagnostic':
        return None
    if type(message.get('version')) is not int or message['version'] != 1:
        return None
    if message.get('units') != 'unverified' or not uint(message.get('sequence')):
        return None
    decks = message.get('decks')
    if not isinstance(decks, list) or len(decks) != 2:
        return None
    for index, deck in enumerate(decks, 1):
        if not isinstance(deck, dict) or type(deck.get('deck')) is not int or deck['deck'] != index:
            return None
        if not uint(deck.get('readerGeneration')) or 'sample' not in deck:
            return None
        sample = deck['sample']
        if sample is None:
            continue
        if not isinstance(sample, dict) or any(not uint(sample.get(k)) for k in ('generation', 'observation', 'frames')):
            return None
        if sample['generation'] == 0 or sample['frames'] == 0:
            return None
        if type(sample.get('rawPosition')) is not int or not -0x80000000 <= sample['rawPosition'] <= 0x7fffffff:
            return None
        # A load can race serialization. Reject association, never silently join it.
        if sample['generation'] != deck['readerGeneration']:
            return None
    return message


class ObservationAges:
    def __init__(self):
        self.seen = {}

    def update(self, message, now):
        result = []
        for deck in message['decks']:
            sample = deck['sample']
            key = deck['deck']
            if sample is None:
                self.seen.pop(key, None)
                result.append(None)
                continue
            identity = (sample['generation'], sample['observation'])
            previous = self.seen.get(key)
            if previous is None or previous[0] != identity:
                self.seen[key] = (identity, now)
            result.append(now - self.seen[key][1])
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, help='Exact IPv4 source filter, not authentication')
    parser.add_argument('--seconds', type=float, default=120)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--now-playing-port', type=int, default=50123)
    parser.add_argument('--position-port', type=int, default=50124)
    args = parser.parse_args()
    try:
        ipaddress.IPv4Address(args.source)
    except ValueError:
        parser.error('source must be IPv4')
    if not math.isfinite(args.seconds) or not 0 < args.seconds <= 3600:
        parser.error('seconds must be finite, >0 and <=3600')
    ports = (args.now_playing_port, args.position_port)
    if len(set(ports)) != 2 or any(not 1 <= p <= 65535 for p in ports):
        parser.error('ports must be distinct, within 1..65535')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    accepted = {'now-playing': 0, 'position-diagnostic': 0}
    rejected = 0
    ages = ObservationAges()
    last = {}
    sequences = {}
    sockets = []
    try:
        with selectors.DefaultSelector() as selector, args.output.open('x') as output:
            for port, kind, validator in ((ports[0], 'now-playing', validate_now_playing),
                                          (ports[1], 'position-diagnostic', validate)):
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sockets.append(sock)
                sock.bind(('', port)); sock.setblocking(False)
                selector.register(sock, selectors.EVENT_READ, (kind, validator))
            start = time.monotonic()
            output.write(json.dumps({'event': 'start', 'wall_time': time.time(),
                                     'mapping': 'unverified; streams not joined'})+'\n')
            while time.monotonic() - start < args.seconds:
                for key, _ in selector.select(.1):
                    data, address = key.fileobj.recvfrom(4097)
                    if address[0] != args.source:
                        continue
                    kind, validator = key.data
                    message = validator(data)
                    if message is None:
                        rejected += 1
                        continue
                    now = time.monotonic()
                    prior = sequences.get(kind)
                    delta = None if prior is None else (message['sequence'] - prior) & 0xffffffff
                    sequences[kind] = message['sequence']
                    record = {'elapsed': now-start, 'raw': message, 'sequence_delta': delta}
                    if kind == 'position-diagnostic':
                        record['observation_age_s'] = ages.update(message, now)
                    output.write(json.dumps(record)+'\n')
                    last[kind] = now
                    accepted[kind] += 1
                now = time.monotonic()
                for kind, timestamp in list(last.items()):
                    if timestamp is not None and now-timestamp > 3:
                        output.write(json.dumps({'elapsed': now-start, 'event': 'stale', 'stream': kind})+'\n')
                        last[kind] = None
                output.flush()
    finally:
        for sock in sockets:
            sock.close()
    print(json.dumps({'accepted': accepted, 'rejected': rejected, 'output': str(args.output)}))


if __name__ == '__main__':
    main()

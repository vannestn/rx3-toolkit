#!/usr/bin/env python3
"""Receive-only RX3 recorder. Never sends commands or treats raw enums as decoded."""
import argparse
import json
import math
import socket
import time
from pathlib import Path


def validate(data):
    if len(data) > 4096:
        return None
    try:
        m = json.loads(data)
    except (ValueError, UnicodeError, RecursionError):
        return None
    if not isinstance(m, dict) or m.get('type') != 'now-playing' or m.get('version') != 1:
        return None
    if type(m.get('sequence')) is not int or not 0 <= m['sequence'] <= 0xffffffff:
        return None
    decks = m.get('decks')
    if not isinstance(decks, list) or len(decks) != 2:
        return None
    for index, d in enumerate(decks, 1):
        if not isinstance(d, dict) or d.get('deck') != index:
            return None
        if any(type(d.get(k)) is not bool for k in ('loaded', 'onAir')):
            return None
        for k in ('trackId', 'bpmX100', 'tempoRaw', 'playModeRaw'):
            if type(d.get(k)) is not int or not -0x80000000 <= d[k] <= 0xffffffff:
                return None
        if not isinstance(d.get('title'), str) or len(d['title']) > 512:
            return None
    return m


def fields(m):
    return [dict(deck=d['deck'], track_id=d['trackId'] if d['loaded'] else None,
                 title=d['title'] or None,
                 effective_bpm=d['bpmX100']/100 if d['loaded'] and 0 < d['bpmX100'] < 65535 else None,
                 tempo_raw=d['tempoRaw'], play_mode_raw=d['playModeRaw'],
                 on_air_raw=d['onAir'], loaded=d['loaded'],
                 position_ms=None, phrase=None, waveform=None,
                 missing_reason='not_exported_by_upstream_now_playing') for d in m['decks']]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True, help='Expected RX3 USB IPv4 address; source filter, not authentication')
    p.add_argument('--port',type=int,default=50123)
    p.add_argument('--seconds',type=float,default=120)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if not math.isfinite(a.seconds) or not 0 < a.seconds <= 3600:
        p.error('seconds must be between 0 and 3600')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive creation prevents accidental loss of a prior test.
    with a.output.open('x') as f, socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as s:
        s.bind(('',a.port));s.settimeout(.25)
        start=time.monotonic();last=None;valid=bad=0;stale=True
        while time.monotonic()-start < a.seconds:
            now=time.monotonic()
            if last is not None and now-last>3 and not stale:
                f.write(json.dumps({'elapsed':now-start,'event':'stale','valid':False})+'\n');f.flush();stale=True
            try:data,addr=s.recvfrom(4097)
            except socket.timeout:continue
            if addr[0]!=a.source:continue
            m=validate(data)
            if m is None:bad+=1;continue
            last=time.monotonic();stale=False;valid+=1
            f.write(json.dumps({'elapsed':last-start,'raw':m,'fields':fields(m)})+'\n');f.flush()
        print(json.dumps({'accepted':valid,'rejected':bad,'output':str(a.output)}))

if __name__=='__main__':main()

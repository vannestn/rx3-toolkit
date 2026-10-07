#!/usr/bin/env python3
"""Receive one RX3 test session: startup/status reports and both telemetry feeds."""
import argparse
import ipaddress
import json
import math
from pathlib import Path
import selectors
import socket
import time
from startup_report import ReportAssembler
from position_diagnostic import ObservationAges, validate as validate_position
from telemetry_diagnostic import validate as validate_now_playing

PORTS={50125:'preflight',50126:'status',50123:'now-playing',50124:'position-diagnostic'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seconds',type=float,default=180)
    p.add_argument('--source',help='Exact USB peer IPv4 filter; not authentication')
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args()
    if not math.isfinite(a.seconds) or not 0<a.seconds<=3600:p.error('invalid duration')
    if a.source:ipaddress.IPv4Address(a.source)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    if a.output.exists():p.error('output already exists')
    counts={kind:0 for kind in PORTS.values()};bad=0
    assemblies={kind:ReportAssembler() for kind in ('preflight','status')}
    ages=ObservationAges();last={};sockets=[];peer=a.source
    with selectors.DefaultSelector() as selector, a.output.open('x') as output:
        try:
            for port,kind in PORTS.items():
                sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
                sock.bind(('',port));sock.setblocking(False);sockets.append(sock)
                selector.register(sock,selectors.EVENT_READ,kind)
            started=time.monotonic()
            output.write(json.dumps({'event':'capture-start','wallTime':time.time(),
                                     'sourceFilter':a.source,'positionUnits':'unverified'})+'\n')
            output.flush()
            print('Listening on RX3 USB-B report and telemetry ports.',flush=True)
            while time.monotonic()-started<a.seconds:
                for key,_ in selector.select(.25):
                    data,address=key.fileobj.recvfrom(4097);source=address[0];kind=key.data
                    try:link_local=ipaddress.IPv4Address(source).is_link_local
                    except ValueError:continue
                    if peer and source!=peer:continue
                    if not peer and not link_local:continue
                    if kind in assemblies:
                        try:complete=assemblies[kind].accept(data,source)
                        except (ValueError,UnicodeDecodeError):bad+=1;continue
                        if complete is None:continue
                        value=complete.decode('utf-8')
                        if peer is None:peer=source
                        record={'event':kind,'elapsed':time.monotonic()-started,
                                'source':source,'text':value}
                        print(f'{kind}: {len(complete)} bytes from {source}',flush=True)
                    else:
                        validator=validate_position if kind=='position-diagnostic' else validate_now_playing
                        value=validator(data)
                        if value is None:bad+=1;continue
                        if peer is None:peer=source
                        record={'event':kind,'elapsed':time.monotonic()-started,
                                'source':source,'raw':value}
                        if kind=='position-diagnostic':
                            record['observationAgeS']=ages.update(value,time.monotonic())
                        last[kind]=time.monotonic()
                    counts[kind]+=1
                    output.write(json.dumps(record,ensure_ascii=False)+'\n')
                    output.flush()
                now=time.monotonic()
                for kind,then in list(last.items()):
                    if then is not None and now-then>3:
                        output.write(json.dumps({'event':'stale','stream':kind,
                                                 'elapsed':now-started})+'\n')
                        output.flush();last[kind]=None
        finally:
            for sock in sockets:sock.close()
    result={'counts':counts,'rejected':bad,'source':peer,'output':str(a.output)}
    print(json.dumps(result),flush=True)
    return 0

if __name__=='__main__':raise SystemExit(main())

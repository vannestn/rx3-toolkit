#!/usr/bin/env python3
"""Receive one bounded RX3 startup report over USB-B UDP 50125. Sends nothing."""
import argparse
import ipaddress
import json
from pathlib import Path
import socket
import struct
import time

LIMIT=8192
CHUNK=1000

class ReportAssembler:
    def __init__(self):
        self.groups={}

    def accept(self, data, source):
        if len(data)<12 or len(data)>1012:
            raise ValueError('packet length')
        magic,version,round_number,index,chunks,total=struct.unpack('!4sBBHHH',data[:12])
        if magic!=b'RX3R' or version!=1 or round_number>=12:
            raise ValueError('header')
        if not 0<total<=LIMIT or chunks!=(total+CHUNK-1)//CHUNK or index>=chunks:
            raise ValueError('bounds')
        expected=min(CHUNK,total-index*CHUNK)
        if len(data)!=12+expected:
            raise ValueError('chunk length')
        key=(source,round_number,chunks,total)
        if key not in self.groups:
            if len(self.groups)>=12:
                raise ValueError('group limit')
            self.groups[key]={}
        group=self.groups[key]
        if index in group and group[index]!=data[12:]:
            raise ValueError('conflicting duplicate')
        group[index]=data[12:]
        if len(group)==chunks:
            result=b''.join(group[i] for i in range(chunks))
            result.decode('utf-8') # Do not render arbitrary binary as text.
            return result
        return None

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seconds',type=float,default=90)
    p.add_argument('--source',help='Optional exact IPv4 filter; not authentication')
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args()
    if not 0<a.seconds<=300:p.error('seconds must be >0 and <=300')
    if a.output.exists():p.error('output already exists')
    if a.source:ipaddress.IPv4Address(a.source)
    assembler=ReportAssembler(); started=time.monotonic();received=rejected=0
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
        sock.bind(('',50125));sock.settimeout(0.5)
        print('Listening receive-only on UDP 50125; insert the report-enabled USB.',flush=True)
        while time.monotonic()-started<a.seconds:
            try:data,address=sock.recvfrom(1013)
            except socket.timeout:continue
            if a.source:
                if address[0]!=a.source:continue
            elif not ipaddress.IPv4Address(address[0]).is_link_local:continue
            received+=1
            try:report=assembler.accept(data,address[0])
            except (ValueError,UnicodeDecodeError):rejected+=1;continue
            if report is not None:
                with a.output.open('xb') as out:out.write(report)
                print(json.dumps({'result':'complete','source':address[0],'bytes':len(report),
                                 'packets':received,'rejected':rejected,'output':str(a.output)}))
                return 0
    print(json.dumps({'result':'timeout','packets':received,'rejected':rejected}))
    return 1
if __name__=='__main__':raise SystemExit(main())

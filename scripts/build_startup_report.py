#!/usr/bin/env python3
"""Build the observation-only USB-B report probe; never installs it."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.firmware.firmware_image import write_autoexec,read_autoexec,autoexec_iso_metadata
from app.runtime.build import compile_report_sender

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--key',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--compiler',default=os.environ.get('CC') or shutil.which('clang'))
    a=p.parse_args()
    if not a.compiler:p.error('Clang and LLD required')
    a.output.mkdir(parents=True,exist_ok=True)
    image=a.output/'autoexec.bin'
    manifest=a.output/'rx3-mod-manifest.json'
    if image.exists() or manifest.exists():p.error('choose a fresh output directory')
    with tempfile.TemporaryDirectory(prefix='rx3-report-') as directory:
        staging=Path(directory)
        shutil.copy2(ROOT/'testing/rx3-1.19/preflight/autoexec.sh',staging/'autoexec.sh')
        binary=staging/'report-send'
        compile_report_sender(ROOT/'mod/lib/report_sender.c',binary,a.compiler)
        binary.chmod(0o755)
        expected={name:(staging/name).read_bytes() for name in ('autoexec.sh','report-send')}
        write_autoexec(staging,image,a.key)
    import pycdlib
    plain=read_autoexec(image,a.key)
    if autoexec_iso_metadata(plain)!='UsbAuto':raise ValueError('volume mismatch')
    iso=pycdlib.PyCdlib();iso.open_fp(io.BytesIO(plain))
    try:
        seen=set()
        for directory,dirs,files in iso.walk(rr_path='/'):
            for name in files:
                if directory!='/':raise ValueError('unexpected directory')
                seen.add(name);data=io.BytesIO();iso.get_file_from_iso_fp(data,rr_path='/'+name)
                if data.getvalue()!=expected.get(name):raise ValueError('content mismatch')
                if iso.get_record(rr_path='/'+name).rock_ridge.get_file_mode()&0o777!=0o755:
                    raise ValueError('executable bit missing')
        if seen!=set(expected):raise ValueError('missing files')
    finally:iso.close()
    result={'format':1,'firmware':'1.19','modules':[],
            'purpose':'observation-only report, finite UDP 50125 USB-B broadcast; no hooks or restart',
            'bytes':image.stat().st_size,'sha256':hashlib.sha256(image.read_bytes()).hexdigest()}
    with manifest.open('x') as out:json.dump(result,out,indent=2);out.write('\n')
    print(json.dumps(result,indent=2))
    return 0
if __name__=='__main__':raise SystemExit(main())

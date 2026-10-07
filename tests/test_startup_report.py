import importlib.util
import json
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('startup_report',ROOT/'scripts/startup_report.py')
receiver=importlib.util.module_from_spec(spec);spec.loader.exec_module(receiver)

def packet(index,total,payload,round_number=0):
    return struct.pack('!4sBBHHH',b'RX3R',1,round_number,index,(total+999)//1000,total)+payload

class ReportTests(unittest.TestCase):
    def test_reordered_chunks_duplicate_and_round_separation(self):
        report=b'x'*1000+b'end'
        a=receiver.ReportAssembler()
        self.assertIsNone(a.accept(packet(1,len(report),report[1000:]),'A'))
        self.assertIsNone(a.accept(packet(0,len(report),report[:1000],1),'A'))
        self.assertIsNone(a.accept(packet(1,len(report),report[1000:]),'A'))
        self.assertEqual(a.accept(packet(0,len(report),report[:1000]),'A'),report)

    def test_bad_bounds_truncated_and_conflicting_packets_refused(self):
        a=receiver.ReportAssembler()
        for data in (b'',packet(0,8193,b'x'*1000),packet(0,10,b'123'),packet(1,10,b'123'),packet(0,10,b'x'*10,12)):
            with self.assertRaises(ValueError):a.accept(data,'A')
        a.accept(packet(0,1001,b'x'*1000),'A')
        with self.assertRaises(ValueError):a.accept(packet(0,1001,b'y'*1000),'A')

    def test_native_sender_exact_round_trip_and_oversize_refusal(self):
        compiler=shutil.which('clang')
        if not compiler:self.skipTest('clang unavailable')
        with tempfile.TemporaryDirectory() as directory:
            executable=Path(directory)/'sender'
            subprocess.run([compiler,'-Wall','-Wextra','-Werror','-O2','-DLOCAL_TEST','-DROUNDS=1',
                            str(ROOT/'mod/lib/report_sender.c'),'-o',str(executable)],check=True)
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
                sock.bind(('127.0.0.1',50125));sock.settimeout(2)
                report=('startup report\n'+'x'*8100).encode()
                result=subprocess.run([str(executable)],input=report,timeout=3)
                self.assertEqual(result.returncode,0)
                a=receiver.ReportAssembler();actual=None
                while actual is None:
                    data,address=sock.recvfrom(1013);actual=a.accept(data,address[0])
                self.assertEqual(actual,report)
                for bad in (b'',b'x'*8193):
                    result=subprocess.run([str(executable)],input=bad,timeout=3)
                    self.assertEqual(result.returncode,2)

    def test_report_arrives_even_when_main_mount_guard_refuses(self):
        compiler=shutil.which('clang')
        if not compiler:self.skipTest('clang unavailable')
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);lib=p/'lib';lib.mkdir()
            shutil.copy2(ROOT/'mod/lib/volatile-guard.sh',lib/'volatile-guard.sh')
            (lib/'startup-report.sh').write_text("#!/bin/sh\nprintf 'guard refusal fixture\\n'\n")
            executable=lib/'report-send'
            subprocess.run([compiler,'-Wall','-Wextra','-Werror','-O2','-DLOCAL_TEST','-DROUNDS=1',
                            str(ROOT/'mod/lib/report_sender.c'),'-o',str(executable)],check=True)
            mounts=p/'mounts';mounts.write_text('/dev/flash / ext4 rw 0 0\n')
            # Execute the real startup prefix through its refusal exit, using
            # only host fixtures. No native player addresses are executed.
            source=(ROOT/'mod/autoexec.sh').read_text()
            prefix=source[:source.index('# Do not inherit a staging destination')]
            prefix=prefix.replace('/mnt/iso',str(p)).replace('/proc/mounts',str(mounts))
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
                sock.bind(('127.0.0.1',50125));sock.settimeout(2)
                result=subprocess.run(['sh','-c',prefix,'test','unused'],capture_output=True,timeout=3)
                self.assertEqual(result.returncode,1)
                data,address=sock.recvfrom(1013)
                report=receiver.ReportAssembler().accept(data,address[0])
                self.assertEqual(report,b'guard refusal fixture\n')

    def test_exit_status_reports_an_early_guard_refusal(self):
        compiler=shutil.which('clang')
        if not compiler:self.skipTest('clang unavailable')
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);lib=p/'lib';lib.mkdir()
            shutil.copy2(ROOT/'mod/lib/volatile-guard.sh',lib/'volatile-guard.sh')
            (lib/'build-id').write_text('a'*32+'\n')
            sender=lib/'report-send-status'
            subprocess.run([compiler,'-Wall','-Wextra','-Werror','-O2','-DLOCAL_TEST',
                            '-DROUNDS=1','-DREPORT_PORT=50126',
                            str(ROOT/'mod/lib/report_sender.c'),'-o',str(sender)],check=True)
            mounts=p/'mounts';mounts.write_text('/dev/flash / ext4 rw 0 0\n')
            source=(ROOT/'mod/autoexec.sh').read_text()
            prefix=source[:source.index('# Do not inherit a staging destination')]
            prefix=prefix.replace('/mnt/iso',str(p)).replace('/proc/mounts',str(mounts))
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
                sock.bind(('127.0.0.1',50126));sock.settimeout(2)
                result=subprocess.run(['sh','-c',prefix,'test','unused'],capture_output=True,timeout=3)
                self.assertEqual(result.returncode,1)
                data,address=sock.recvfrom(1013)
                report=receiver.ReportAssembler().accept(data,address[0])
                self.assertIn(b'buildId='+b'a'*32,report)
                self.assertIn(b'stage=preflight\nexitCode=1\n',report)
                self.assertIn(b'playerAlive=unknown\n',report)

    def test_combined_capture_keeps_reports_and_telemetry_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'session.jsonl'
            with subprocess.Popen([sys.executable,str(ROOT/'scripts/diagnostic_session.py'),
                                   '--source','127.0.0.1','--seconds','.75','--output',str(path)],
                                  stdout=subprocess.PIPE,text=True) as process:
                self.assertIn('Listening',process.stdout.readline())
                now={'type':'now-playing','version':1,'sequence':1,'decks':[
                    {'deck':i,'loaded':i==1,'onAir':False,'trackId':42 if i==1 else 0,
                     'bpmX100':12200,'tempoRaw':0,'playModeRaw':2,'title':''}
                    for i in (1,2)]}
                position={'type':'position-diagnostic','version':1,'sequence':1,
                          'units':'unverified','decks':[
                              {'deck':1,'readerGeneration':1,'sample':{'generation':1,
                               'observation':1,'rawPosition':44100,'frames':512}},
                              {'deck':2,'readerGeneration':0,'sample':None}]}
                with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
                    for port,payload in ((50125,packet(0,4,b'boot')),
                                         (50126,packet(0,6,b'status')),
                                         (50123,json.dumps(now).encode()),
                                         (50124,json.dumps(position).encode())):
                        sock.sendto(payload,('127.0.0.1',port))
                self.assertEqual(process.wait(timeout=3),0)
            rows=[json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual({r['event'] for r in rows[1:]},
                             {'preflight','status','now-playing','position-diagnostic'})
            self.assertEqual(next(r for r in rows if r['event']=='position-diagnostic')['observationAgeS'],[0,None])

    def test_iso_preserves_explicit_executable_mode(self):
        import io
        import pycdlib
        from app.firmware.firmware_image import build_autoexec_iso
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory);(p/'autoexec.sh').write_text('#!/bin/sh\nexit 0\n')
            binary=p/'report-send';binary.write_bytes(b'fixture');binary.chmod(0o755)
            iso=pycdlib.PyCdlib();iso.open_fp(io.BytesIO(build_autoexec_iso(p)))
            try:
                record=iso.get_record(rr_path='/report-send')
                self.assertEqual(record.rock_ridge.get_file_mode()&0o777,0o755)
            finally:iso.close()

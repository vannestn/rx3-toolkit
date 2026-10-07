"""Host-only diagnostic tests. None execute a firmware address."""
import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import position_diagnostic as receiver
from tests import test_framework as harness


class PositionTests(unittest.TestCase):
    run_units = harness.FrameworkTests.run_units

    def test_mailbox_invalidation_contention_and_transport_jumps(self):
        self.run_units(r'''
#include "position-diagnostic/rx3_position_snapshot.h"
int main(void) {
    struct position_slot slot={0}; struct position_value out={0};
    int reader=0, other=0;
    assert(!position_read(&slot,&out));
    position_observe(&slot,&reader,44100,512);
    assert(!position_read(&slot,&out));
    position_loading(&slot);position_loaded(&slot,&reader);
    position_observe(&slot,&other,3,512);assert(!position_read(&slot,&out));
    position_observe(&slot,&reader,44100,512);
    assert(position_read(&slot,&out)&&out.raw==44100&&out.generation==1);
    assert(position_take(&slot));
    position_observe(&slot,&reader,999,512);assert(!position_read(&slot,&out));
    position_release(&slot);assert(position_read(&slot,&out)&&out.raw==44100);
    position_observe(&slot,&reader,100,512); /* loop/cue jump: no smoothing */
    assert(position_read(&slot,&out)&&out.raw==100);
    position_observe(&slot,&reader,-2147483647-1,512);
    assert(position_read(&slot,&out)&&out.raw==(-2147483647-1));
    position_loading(&slot);assert(!position_read(&slot,&out));
    position_loaded(&slot,&other);assert(!position_read(&slot,&out));
    position_observe(&slot,&reader,7,512);assert(!position_read(&slot,&out));
    position_observe(&slot,&other,8,512);
    assert(position_read(&slot,&out)&&out.raw==8&&out.generation==2);
    return 0;
}
''', [])

    def message(self):
        return dict(type='position-diagnostic', version=1, sequence=0, units='unverified',
                    decks=[dict(deck=1, readerGeneration=1, sample=dict(generation=1, observation=1, rawPosition=-1, frames=512)),
                           dict(deck=2, readerGeneration=0, sample=None)])

    def test_packet_validation(self):
        message=self.message()
        self.assertEqual(receiver.validate(json.dumps(message).encode()), message)
        for field, value in [('rawPosition', True), ('rawPosition', 2**31), ('rawPosition', float('nan')),
                             ('generation', 2), ('frames', 0), ('observation', -1)]:
            bad=copy.deepcopy(message);bad['decks'][0]['sample'][field]=value
            self.assertIsNone(receiver.validate(json.dumps(bad).encode()))
        for data in (b'null', b'[]', b'['*2000, b' '*4097, b'\xff'):
            self.assertIsNone(receiver.validate(data))

    def test_repeated_sample_age_and_invalidation(self):
        ages=receiver.ObservationAges(); message=self.message()
        self.assertEqual(ages.update(message,1),[0,None])
        self.assertEqual(ages.update(message,3),[2,None])
        message['decks'][0]['sample']['observation']=2
        self.assertEqual(ages.update(message,4),[0,None])
        message['decks'][0]['sample']=None
        self.assertEqual(ages.update(message,5),[None,None])


    def test_concurrent_mailbox_never_tears_payload(self):
        self.run_units(r'''
#include "position-diagnostic/rx3_position_snapshot.h"
static struct position_slot slot;
static int reader=0;
static unsigned finished;
static void *writer(void *unused) {
    (void)unused;
    for(unsigned i=1;i<=100000;i++) {
        if(i%1000==1) {position_loading(&slot);position_loaded(&slot,&reader);}
        position_observe(&slot,&reader,(int)i,i+3);
    }
    __atomic_store_n(&finished,1u,__ATOMIC_RELEASE);return 0;
}
int main(void) {
    pthread_t thread; assert(!pthread_create(&thread,0,writer,0));
    while(!__atomic_load_n(&finished,__ATOMIC_ACQUIRE)) {
        struct position_value v={0};
        if(position_read(&slot,&v)) assert(v.frames==(unsigned)v.raw+3);
    }
    assert(!pthread_join(thread,0));return 0;
}
''', [], flags=('-pthread',))

    def test_module_fault_cleanup_and_audio_unchanged(self):
        self.run_units(r'''
#define socket fake_socket
#define setsockopt fake_setsockopt
#define sendto fake_sendto
#define close fake_close
#define pthread_create fake_create
#define pthread_join fake_join
static int fake_close(int);
static int fake_create(pthread_t *,const void *,void *(*)(void *),void *);
static int fake_join(pthread_t,void **);
#include "position-diagnostic/rx3_position_diagnostic_module.c"
static int fail_socket,fail_options,fail_claim,fail_thread,closes,claims,releases,joins;
static rx3_deck_stream_fn observer;
static char packet[1024];
int fake_socket(int a,int b,int c){assert(a==2&&b==2&&c==0);return fail_socket?-1:9;}
int fake_setsockopt(int fd,int l,int o,const void *v,unsigned n) {
 assert(fd==9&&l==1&&o==6&&*(const int *)v==1&&n==sizeof(int));return fail_options?-1:0;
}
ssize_t fake_sendto(int fd,const void *p,size_t n,int flags,const void *dest,unsigned len) {
 assert(fd==9&&n<sizeof(packet)&&flags==0x40&&len==16);
 const struct position_address *a=dest;assert(a->address==0xfffffea9u);
 memcpy(packet,p,n);packet[n]=0;return (ssize_t)n;
}
static int fake_close(int fd){assert(fd==9);closes++;return 0;}
static int fake_create(pthread_t *t,const void *attr,void *(*f)(void *),void *arg) {
 (void)t;(void)attr;(void)f;(void)arg;return fail_thread?1:0;
}
static int fake_join(pthread_t t,void **result){(void)t;(void)result;joins++;return 0;}
static int claim(const void *who,rx3_deck_stream_fn fn) {
 assert(who);claims++;if(fail_claim)return 0;observer=fn;return 1;
}
static void release(const void *who){assert(who&&observer);observer=0;releases++;}
static void log_message(const char *s){assert(s);}
int main(void) {
 struct rx3_audio_service audio={.claim_deck_stream=claim,.release_deck_stream=release};
 struct rx3_services services={.audio=&audio,.log_line=log_message};
 fail_socket=1;assert(!start(&services));stop();assert(!closes&&!claims);
 fail_socket=0;fail_options=1;assert(!start(&services));stop();assert(closes==1&&!claims);
 fail_options=0;fail_claim=1;assert(!start(&services));stop();assert(closes==2&&claims==1&&!releases);
 fail_claim=0;fail_thread=1;assert(!start(&services));stop();assert(closes==3&&releases==1&&!joins);
 fail_thread=0;assert(start(&services));assert(observer);
 int reader=0;struct rx3_stereo pcm[2]={{.25f,-.5f},{1,-1}},saved[2];memcpy(saved,pcm,sizeof(pcm));
 loading(0,&reader,0);loaded(0,&reader,0);observer(0,&reader,-2147483647-1,pcm,2);
 assert(!memcmp(pcm,saved,sizeof(pcm)));
 emit(0xffffffffu);assert(strstr(packet,"\"sequence\":4294967295"));
 assert(strstr(packet,"\"rawPosition\":-2147483648"));
 assert(strstr(packet,"\"sample\":null"));assert(strstr(packet,"\"units\":\"unverified\""));
 loading(0,&reader,0);emit(1);assert(!strstr(packet,"rawPosition"));
 stop();stop();assert(closes==4&&releases==2&&joins==1&&!observer);
 return 0;
}
''', [])


    def test_dual_stream_capture_over_localhost(self):
        import socket
        import subprocess
        import tempfile
        import time
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            output=Path(temporary)/'capture.jsonl'
            sockets=[socket.socket(socket.AF_INET,socket.SOCK_DGRAM) for _ in range(2)]
            for sock in sockets: sock.bind(('127.0.0.1',0))
            ports=[sock.getsockname()[1] for sock in sockets]
            for sock in sockets: sock.close()
            process=subprocess.Popen([sys.executable,str(root/'scripts/position_diagnostic.py'),
                '--source','127.0.0.1','--seconds','1.2','--output',str(output),
                '--now-playing-port',str(ports[0]),'--position-port',str(ports[1])],
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            now=dict(type='now-playing',version=1,sequence=0,decks=[
                dict(deck=i,loaded=True,onAir=True,trackId=i,bpmX100=12000,tempoRaw=0,playModeRaw=2,title='Synthetic') for i in (1,2)])
            try:
                with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sender:
                    for n in range(15):
                        time.sleep(.05)
                        now['sequence']=n
                        position=self.message();position['sequence']=n
                        sender.sendto(json.dumps(now).encode(),('127.0.0.1',ports[0]))
                        sender.sendto(json.dumps(position).encode(),('127.0.0.1',ports[1]))
                        sender.sendto(b'null',('127.0.0.1',ports[1]))
                stdout,stderr=process.communicate(timeout=5)
                self.assertEqual(process.returncode,0,stderr)
                report=json.loads(stdout)
                self.assertGreater(report['accepted']['now-playing'],0)
                self.assertGreater(report['accepted']['position-diagnostic'],0)
                self.assertGreater(report['rejected'],0)
                records=[json.loads(line) for line in output.read_text().splitlines()]
                positions=[r for r in records if r.get('raw',{}).get('type')=='position-diagnostic']
                self.assertGreater(positions[-1]['observation_age_s'][0],.2)
            finally:
                if process.poll() is None: process.kill();process.wait()


if __name__=='__main__':unittest.main()

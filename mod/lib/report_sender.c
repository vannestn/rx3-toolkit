/* SPDX-License-Identifier: MPL-2.0 */
/* Separate, finite, outbound-only process. Reads stdin, never opens files. */
#ifdef __arm__
typedef unsigned int size_t;
static long call6(long n,long a,long b,long c,long d,long e,long f) {
    register long r0 __asm__("r0")=a, r1 __asm__("r1")=b, r2 __asm__("r2")=c;
    register long r3 __asm__("r3")=d, r4 __asm__("r4")=e, r5 __asm__("r5")=f;
    register long r7 __asm__("r7")=n;
    __asm__ volatile("svc 0" : "+r"(r0) : "r"(r1),"r"(r2),"r"(r3),"r"(r4),"r"(r5),"r"(r7) : "memory","cc");
    return r0;
}
#define READ(b,n) call6(3,0,(long)(b),n,0,0,0)
#define SOCKET() call6(281,2,2,0,0,0,0)
#define OPTION(fd,p) call6(294,fd,1,6,(long)(p),4,0)
#define SEND(fd,b,n,to) call6(290,fd,(long)(b),n,0x40,(long)(to),16)
#define CLOSE(fd) call6(6,fd,0,0,0,0,0)
static void wait_second(void) { long ts[2]={1,0}; (void)call6(162,(long)ts,0,0,0,0,0); }
#else
#include <stddef.h>
#include <unistd.h>
#include <sys/socket.h>
#define READ(b,n) read(0,b,n)
#define SOCKET() socket(2,2,0)
#define OPTION(fd,p) setsockopt(fd,SOL_SOCKET,SO_BROADCAST,p,sizeof(int))
#define SEND(fd,b,n,to) sendto(fd,b,n,MSG_DONTWAIT,(const struct sockaddr *)(to),16)
#define CLOSE(fd) close(fd)
static void wait_second(void) { sleep(1); }
#endif
#define LIMIT 8192u
#define CHUNK 1000u
#ifndef ROUNDS
#define ROUNDS 12u
#endif
static unsigned char report[LIMIT+1u];
static unsigned char packet[12u+CHUNK];
static void put16(unsigned char *p,unsigned int n) { p[0]=(unsigned char)(n>>8);p[1]=(unsigned char)n; }
int report_main(void) {
    unsigned int total=0;
    while(total<sizeof(report)) {
        long n=READ(report+total,sizeof(report)-total);
        if(n==0) break;
        if(n<0) return 1;
        total+=(unsigned int)n;
    }
    /* Never silently truncate a report. Read and reject one byte over limit. */
    if(!total || total>LIMIT) return 2;
    int fd=(int)SOCKET(),on=1;
    if(fd<0) return 3;
    if(OPTION(fd,&on)<0) { CLOSE(fd);return 4; }
    /* sockaddr_in little-endian ARM: fixed USB link-local broadcast:50125. */
    unsigned char to[16]={2,0,0xc3,0xcd,169,254,255,255,0,0,0,0,0,0,0,0};
#ifdef LOCAL_TEST
    to[4]=127;to[5]=0;to[6]=0;to[7]=1;
#ifdef __APPLE__
    to[0]=16;to[1]=2; /* BSD sockaddr length/family for host tests only. */
#endif
#endif
    unsigned int chunks=(total+CHUNK-1u)/CHUNK, sent=0;
    for(unsigned int round=0;round<ROUNDS;round++) {
        for(unsigned int index=0;index<chunks;index++) {
            unsigned int offset=index*CHUNK, length=total-offset;
            if(length>CHUNK)length=CHUNK;
            packet[0]='R';packet[1]='X';packet[2]='3';packet[3]='R';packet[4]=1;packet[5]=(unsigned char)round;
            put16(packet+6,index);put16(packet+8,chunks);put16(packet+10,total);
            for(unsigned int j=0;j<length;j++)packet[12+j]=report[offset+j];
            if(SEND(fd,packet,12u+length,to)==(long)(12u+length))sent++;
        }
        if(round+1u<ROUNDS)wait_second();
    }
    CLOSE(fd);return sent?0:5;
}
#ifdef __arm__
__asm__(".global _start\n_start:\nmov r11, #0\nbl report_main\nmov r7, #1\nsvc 0\n");
#else
int main(void) { return report_main(); }
#endif

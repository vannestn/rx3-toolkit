/* SPDX-License-Identifier: MPL-2.0
 * RX3 read-only metadata transport. Separate process; never preloaded into rbp.
 * One request per TCP connection: PDB\n or ANLZ /PIONEER/USBANLZ/.../ANLZ0000.EXT\n.
 * Replies OK\n<file bytes> or ERR\n. The connection closes after each reply.
 */
#ifdef __arm__
typedef unsigned int size_t;
typedef int ssize_t;
static long call6(long n,long a,long b,long c,long d,long e,long f) {
    register long r0 __asm__("r0")=a, r1 __asm__("r1")=b, r2 __asm__("r2")=c;
    register long r3 __asm__("r3")=d, r4 __asm__("r4")=e, r5 __asm__("r5")=f;
    register long r7 __asm__("r7")=n;
    __asm__ volatile("svc 0" : "+r"(r0) : "r"(r1),"r"(r2),"r"(r3),"r"(r4),"r"(r5),"r"(r7) : "memory","cc");
    return r0;
}
#define OPEN(p,f) call6(5,(long)(p),f,0,0,0,0)
#define OPENAT(d,p,f) call6(322,d,(long)(p),f,0,0,0)
#define READ(d,p,n) call6(3,d,(long)(p),n,0,0,0)
#define WRITE(d,p,n) call6(4,d,(long)(p),n,0,0,0)
#define SEND(d,p,n) call6(290,d,(long)(p),n,0x4000,0,0)
#define CLOSE(d) call6(6,d,0,0,0,0,0)
#define SEEK(d,n,w) call6(19,d,n,w,0,0,0)
#define SOCKET() call6(281,2,1,0,0,0,0)
#define BIND(d,p) call6(282,d,(long)(p),16,0,0,0)
#define LISTEN(d) call6(284,d,4,0,0,0,0)
#define ACCEPT(d,p,l) call6(285,d,(long)(p),(long)(l),0,0,0)
#define OPTION(d,level,name,p,n) call6(294,d,level,name,(long)(p),n,0)
#define PACE() do { long ts[2]={0,4000000};(void)call6(162,(long)ts,0,0,0,0,0); } while(0)
#else
#include <stddef.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <netinet/in.h>
#define OPEN(p,f) open(p,f)
#define OPENAT(d,p,f) openat(d,p,f)
#define READ(d,p,n) read(d,p,n)
#define WRITE(d,p,n) write(d,p,n)
#define SEND(d,p,n) send(d,p,n,0)
#define CLOSE(d) close(d)
#define SEEK(d,n,w) lseek(d,n,w)
#define SOCKET() socket(AF_INET,SOCK_STREAM,0)
#define BIND(d,p) bind(d,(const struct sockaddr *)(p),16)
#define LISTEN(d) listen(d,4)
#define ACCEPT(d,p,l) accept(d,(struct sockaddr *)(p),(socklen_t *)(l))
#define OPTION(d,level,name,p,n) setsockopt(d,level,name,p,n)
#define PACE() do { struct timespec ts={0,4000000};(void)nanosleep(&ts,0); } while(0)
#include <time.h>
#endif

#ifdef __arm__
#define O_RDONLY_ 0
/* ARM uses different open-flag bits from asm-generic/x86. See
 * arch/arm/include/uapi/asm/fcntl.h in the Linux kernel. */
#define O_DIRECTORY_ (1 << 14)
#define O_NOFOLLOW_ (1 << 15)
#else
#define O_RDONLY_ O_RDONLY
#define O_DIRECTORY_ O_DIRECTORY
#define O_NOFOLLOW_ O_NOFOLLOW
#endif
#define MAX_REQUEST 240u
#define MAX_PDB (16u*1024u*1024u)
#define MAX_ANALYSIS (4u*1024u*1024u)
#ifndef METADATA_PORT
#define METADATA_PORT 50131u
#endif
static unsigned char buffer[4096];

static size_t length(const char *s) { size_t n=0; while(s[n]) n++; return n; }
static int equal(const char *a,const char *b) {
    size_t i=0; while(a[i] && b[i] && a[i]==b[i]) i++; return a[i]==0 && b[i]==0;
}
static int prefix(const char *a,const char *b) {
    size_t i=0; while(b[i]) { if(a[i]!=b[i]) return 0; i++; } return 1;
}
static int suffix(const char *a,const char *b) {
    size_t al=length(a),bl=length(b); return al>=bl && equal(a+al-bl,b);
}
static int send_all(int fd,const unsigned char *data,size_t count) {
    while(count) { long n=SEND(fd,data,count); if(n<=0) return 0; data+=n;count-=(size_t)n; }
    return 1;
}

/* Walk each path component with O_NOFOLLOW: no symlink can escape the USB.
 * Analysis paths may come from a PDB row, so never trust them as filesystem paths. */
static int open_relative(int root,const char *path) {
    char component[64];
    int parent=root,owned=0;
    const char *cursor=path;
    for (;;) {
        size_t n=0;
        while(cursor[n] && cursor[n]!='/') {
            char c=cursor[n];
            if(n+1>=sizeof(component) ||
               !((c>='A'&&c<='Z')||(c>='a'&&c<='z')||
                 (c>='0'&&c<='9')||c=='.')) goto bad;
            component[n]=c;n++;
        }
        if(!n || (n==1 && component[0]=='.') ||
           (n==2 && component[0]=='.' && component[1]=='.')) goto bad;
        component[n]=0;
        int more=cursor[n]=='/';
        int next=(int)OPENAT(parent,component,O_RDONLY_|O_NOFOLLOW_|
                             (more?O_DIRECTORY_:0));
        if(next<0) goto bad;
        if(owned) CLOSE(parent);
        parent=next;owned=1;
        if(!more) return parent;
        cursor+=n+1;
    }
bad:
    if(owned) CLOSE(parent);
    return -1;
}

static int allowed(const char *request,const char **relative,unsigned int *limit) {
    if(equal(request,"PDB")) {
        *relative="PIONEER/rekordbox/export.pdb";
        *limit=MAX_PDB;return 1;
    }
    if(!prefix(request,"ANLZ /PIONEER/USBANLZ/")) return 0;
    const char *path=request+5;
    size_t n=length(path);
    if(n<35 || n>MAX_REQUEST-5 ||
       !(suffix(path,"/ANLZ0000.DAT") || suffix(path,"/ANLZ0000.EXT"))) return 0;
    *relative=path+1;*limit=MAX_ANALYSIS;return 1;
}

static void serve_client(int client,int root) {
    char request[MAX_REQUEST+1];size_t count=0;
    while(count<MAX_REQUEST) {
        long n=READ(client,request+count,1);
        if(n!=1) return;
        if(request[count++]=='\n') break;
    }
    if(!count || request[count-1]!='\n') return;
    request[count-1]=0;
    const char *relative=0;unsigned int limit=0;
    if(!allowed(request,&relative,&limit)) { send_all(client,(const unsigned char *)"ERR\n",4);return; }
    int file=open_relative(root,relative);
    if(file<0) { send_all(client,(const unsigned char *)"ERR\n",4);return; }
    long size=SEEK(file,0,2);
    if(size<0 || (unsigned long)size>limit || SEEK(file,0,0)<0) {
        CLOSE(file);send_all(client,(const unsigned char *)"ERR\n",4);return;
    }
    /* Never read a content byte before confirming the peer accepts the header.
     * Even on huge/corrupt files, no more than the fixed limit is transmitted. */
    if(send_all(client,(const unsigned char *)"OK\n",3)) {
        unsigned int total=0;
        for (;;) {
            long n=READ(file,buffer,sizeof(buffer));
            if(n<=0) break;
            if((unsigned int)n>limit-total) break;
            if(!send_all(client,buffer,(size_t)n)) break;
            total+=(unsigned int)n;
            PACE(); /* at most roughly 1 MiB/s, independently of the host */
        }
    }
    CLOSE(file);
}

static int run(const char *root_path) {
#ifndef LOCAL_TEST
    if(!(prefix(root_path,"/media/usb1/") || prefix(root_path,"/media/usb2/"))) return 2;
#endif
    int root=(int)OPEN(root_path,O_RDONLY_|O_DIRECTORY_|O_NOFOLLOW_);
    if(root<0) return 3;
    int listener=(int)SOCKET();
    if(listener<0) { CLOSE(root);return 4; }
    int reuse=1;
    (void)OPTION(listener,1,2,&reuse,4);
    unsigned char address[16]={2,0,(unsigned char)(METADATA_PORT>>8),
                               (unsigned char)METADATA_PORT,
                               0,0,0,0,0,0,0,0,0,0,0,0};
#ifdef LOCAL_TEST
    address[4]=127;address[5]=0;address[6]=0;address[7]=1;
#ifdef __APPLE__
    address[0]=16;address[1]=2;
#endif
#endif
    if(BIND(listener,address)<0 || LISTEN(listener)<0) {
        CLOSE(listener);CLOSE(root);return 5;
    }
    for (;;) {
        unsigned char peer[16]={0};unsigned int peer_length=sizeof(peer);
        int client=(int)ACCEPT(listener,peer,&peer_length);
        if(client<0) continue;
#ifndef LOCAL_TEST
        if(peer_length<8 || peer[4]!=169 || peer[5]!=254) { CLOSE(client);continue; }
#endif
        /* A silent or stalled client cannot trap this process indefinitely. */
        long timeout[2]={2,0};
        (void)OPTION(client,1,20,timeout,sizeof(timeout));
        (void)OPTION(client,1,21,timeout,sizeof(timeout));
#if defined(LOCAL_TEST) && defined(__APPLE__)
        { int no_sigpipe=1;(void)OPTION(client,SOL_SOCKET,SO_NOSIGPIPE,&no_sigpipe,4); }
#endif
        serve_client(client,root);
        CLOSE(client);
    }
}

#ifdef __arm__
__attribute__((used)) static int entry(long *stack) {
    return stack[0]==2?run(((char **)(stack+1))[1]):1;
}
__asm__(".global _start\n_start:\nmov r0, sp\nbl entry\nmov r7, #1\nsvc 0\n");
#else
int main(int argc,char **argv) { return argc==2?run(argv[1]):1; }
#endif

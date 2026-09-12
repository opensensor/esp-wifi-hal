#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <linux/filter.h>
#include <linux/if_ether.h>
#include <linux/if_packet.h>
#include <net/if.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#include "filter.h"
static volatile sig_atomic_t stopped;
static void stop(int sig) { (void)sig; stopped = 1; }
static void fail(const char *what) { perror(what); exit(1); }
static double mono(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t)) fail("monotonic");
    return t.tv_sec + t.tv_nsec / 1e9;
}
static void output(const void *p, size_t n) {
    if (fwrite(p, 1, n, stdout) != n || fflush(stdout)) fail("pcap output");
}
int main(int argc, char **argv) {
    if (argc != 5) {
        fprintf(stderr, "usage: capture IFACE IPV4 SECONDS STOPFILE\n"); return 2;
    }
    struct in_addr ip;
    if (inet_pton(AF_INET, argv[2], &ip) != 1) return 2;
    char *end;
    unsigned long seconds = strtoul(argv[3], &end, 10);
    if (*end || seconds < 1 || seconds > 3600) return 2;
    unsigned int index = if_nametoindex(argv[1]);
    if (!index) fail("interface");
    for (size_t i=0; i<sizeof(rules)/sizeof(rules[0]); i++)
        if (rules[i].k == 0xc0000201) rules[i].k = ntohl(ip.s_addr);
    int fd = socket(AF_PACKET, SOCK_RAW, 0);
    if (fd < 0) fail("socket");
    struct sock_fprog filter = {sizeof(rules)/sizeof(rules[0]), rules};
    if (setsockopt(fd, SOL_SOCKET, SO_ATTACH_FILTER, &filter, sizeof(filter))) fail("filter");
    int one = 1, size = 4*1024*1024;
    if (setsockopt(fd, SOL_SOCKET, SO_TIMESTAMPNS, &one, sizeof(one))) fail("timestamp");
    if (setsockopt(fd, SOL_SOCKET, SO_RCVBUF, &size, sizeof(size))) fail("receive buffer");
    socklen_t optlen = sizeof(size);
    if (getsockopt(fd, SOL_SOCKET, SO_RCVBUF, &size, &optlen)) fail("get receive buffer");
    struct sockaddr_ll address = {.sll_family=AF_PACKET, .sll_protocol=htons(ETH_P_ALL), .sll_ifindex=(int)index};
    if (bind(fd, (struct sockaddr *)&address, sizeof(address))) fail("bind");
    signal(SIGINT, stop); signal(SIGTERM, stop); signal(SIGPIPE, SIG_IGN);
    uint32_t header[] = {0xa1b2c3d4, 0x00040002, 0, 0, 1600, 1};
    output(header, sizeof(header));
    fprintf(stderr, "{\"ready\":true,\"pid\":%d,\"rcvbuf\":%d}\n", getpid(), size);
    fflush(stderr);
    double deadline = mono() + seconds;
    unsigned long count=0, truncated=0, missing_timestamp=0, types[8]={0};
    while (!stopped && mono() < deadline && access(argv[4], F_OK)) {
        struct pollfd pfd={.fd=fd,.events=POLLIN};
        int ready=poll(&pfd, 1, 200);
        if (ready<0) { if (errno==EINTR) continue; fail("poll"); }
        if (!ready) continue;
        unsigned char buf[1600];
        union { struct cmsghdr align; unsigned char bytes[CMSG_SPACE(sizeof(struct timespec))]; } control;
        struct sockaddr_ll peer;
        struct iovec iov={buf,sizeof(buf)};
        struct msghdr msg={.msg_name=&peer,.msg_namelen=sizeof(peer),.msg_iov=&iov,.msg_iovlen=1,
            .msg_control=control.bytes,.msg_controllen=sizeof(control.bytes)};
        ssize_t got=recvmsg(fd,&msg,MSG_TRUNC);
        if (got<0) { if(errno==EINTR) continue; fail("receive"); }
        struct timespec ts={0,0};
        for (struct cmsghdr *c=CMSG_FIRSTHDR(&msg); c; c=CMSG_NXTHDR(&msg,c))
            if(c->cmsg_level==SOL_SOCKET && c->cmsg_type==SCM_TIMESTAMPNS)
                memcpy(&ts,CMSG_DATA(c),sizeof(ts));
        if(!ts.tv_sec) { missing_timestamp++; clock_gettime(CLOCK_REALTIME,&ts); }
        uint32_t captured=(size_t)got>sizeof(buf)?sizeof(buf):(size_t)got;
        if(captured!=(uint32_t)got) truncated++;
        uint32_t record[]={ts.tv_sec,ts.tv_nsec/1000,captured,(uint32_t)got};
        output(record,sizeof(record)); output(buf,captured);
        count++; if(peer.sll_pkttype<8) types[peer.sll_pkttype]++;
    }
    struct tpacket_stats stats;
    optlen=sizeof(stats);
    if(getsockopt(fd,SOL_PACKET,PACKET_STATISTICS,&stats,&optlen)) fail("statistics");
    fprintf(stderr,"{\"written\":%lu,\"socket_packets\":%u,\"socket_drops\":%u,\"truncated\":%lu,\"missing_kernel_timestamp\":%lu,\"packet_types\":[%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu]}\n",
        count,stats.tp_packets,stats.tp_drops,truncated,missing_timestamp,
        types[0],types[1],types[2],types[3],types[4],types[5],types[6],types[7]);
    close(fd);
    return stats.tp_drops || truncated || missing_timestamp ? 3 : 0;
}

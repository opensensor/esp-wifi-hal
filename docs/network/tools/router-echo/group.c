#define _DEFAULT_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

/* Labeled broadcast + administratively scoped multicast, confined to one LAN. */
int main(int argc, char **argv) {
    if (argc != 3) { fputs("usage: router-group LOCAL_IPV4 COUNT\n", stderr); return 2; }
    struct in_addr local;
    if (inet_pton(AF_INET, argv[1], &local) != 1) return 2;
    char *end; errno=0; unsigned long count=strtoul(argv[2], &end, 10);
    if (errno || !*argv[2] || *end || count<1 || count>600) return 2;
    int fd=socket(AF_INET, SOCK_DGRAM, 0), one=1;
    unsigned char ttl=1, loop=0;
    if (fd<0 || setsockopt(fd,SOL_SOCKET,SO_BROADCAST,&one,sizeof(one)) ||
        setsockopt(fd,IPPROTO_IP,IP_MULTICAST_IF,&local,sizeof(local)) ||
        setsockopt(fd,IPPROTO_IP,IP_MULTICAST_TTL,&ttl,sizeof(ttl)) ||
        setsockopt(fd,IPPROTO_IP,IP_MULTICAST_LOOP,&loop,sizeof(loop))) { perror("socket"); return 2; }
    struct sockaddr_in source={.sin_family=AF_INET,.sin_addr=local};
    if (bind(fd,(struct sockaddr *)&source,sizeof(source))) { perror("bind"); return 2; }
    struct sockaddr_in to[2]={{.sin_family=AF_INET,.sin_port=htons(5005)},
                              {.sin_family=AF_INET,.sin_port=htons(5005)}};
    inet_pton(AF_INET,"255.255.255.255",&to[0].sin_addr);
    inet_pton(AF_INET,"239.255.42.99",&to[1].sin_addr);
    unsigned sent[2]={0};
    for (unsigned seq=1; seq<=count; seq++) {
        for (unsigned kind=0; kind<2; kind++) {
            unsigned char data[128]; memcpy(data,"OGTK",4);
            data[4]=kind; data[5]=1; data[6]=seq>>8; data[7]=seq;
            for (unsigned j=8;j<sizeof(data);j++) data[j]=(unsigned char)(j^seq^kind);
            if (sendto(fd,data,sizeof(data),0,(struct sockaddr *)&to[kind],sizeof(to[kind])) != sizeof(data)) {
                perror("sendto"); close(fd); return 1;
            }
            sent[kind]++;
        }
        struct timespec delay={.tv_sec=0,.tv_nsec=500000000};
        while (nanosleep(&delay,&delay) && errno==EINTR) {}
    }
    close(fd);
    printf("{\"broadcast_sent\":%u,\"multicast_sent\":%u}\n",sent[0],sent[1]);
    return 0;
}

#define _POSIX_C_SOURCE 200809L
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <poll.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#define PAYLOAD 512
#define MAX_COUNT 6000
static uint64_t now_us(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts)) { perror("clock_gettime"); exit(2); }
    return (uint64_t)ts.tv_sec * 1000000 + ts.tv_nsec / 1000;
}
static unsigned get16(const unsigned char *p) { return ((unsigned)p[0] << 8) | p[1]; }
static void put16(unsigned char *p, unsigned n) { p[0] = n >> 8; p[1] = n; }
static unsigned checksum(const unsigned char *p, size_t n) {
    uint32_t sum = 0;
    while (n >= 2) { sum += get16(p); p += 2; n -= 2; }
    if (n) sum += (unsigned)p[0] << 8;
    while (sum >> 16) sum = (sum & 65535) + (sum >> 16);
    return (~sum) & 65535;
}
static unsigned number(const char *s, unsigned min, unsigned max) {
    char *end; errno = 0; unsigned long n = strtoul(s, &end, 10);
    if (errno || !*s || *end || n < min || n > max) { fputs("invalid numeric argument\n", stderr); exit(2); }
    return n;
}
int main(int argc, char **argv) {
    if (argc != 4) { fputs("usage: router-echo IPv4 COUNT INTERVAL_MS\n", stderr); return 2; }
    struct sockaddr_in peer = {.sin_family = AF_INET};
    if (inet_pton(AF_INET, argv[1], &peer.sin_addr) != 1) return 2;
    unsigned count = number(argv[2], 1, MAX_COUNT), interval = number(argv[3], 10, 1000);
    int fd = socket(AF_INET, SOCK_RAW, IPPROTO_ICMP);
    if (fd < 0) { perror("socket"); return 2; }
    int flags = fcntl(fd, F_GETFL, 0);
    if (flags < 0 || fcntl(fd, F_SETFL, flags | O_NONBLOCK)) { perror("fcntl"); return 2; }
    uint64_t sent_at[MAX_COUNT] = {0}, received_at[MAX_COUNT] = {0};
    unsigned sent = 0, received = 0, duplicate = 0, invalid = 0, send_errors = 0;
    unsigned ident = (unsigned)getpid() & 65535;
    unsigned char request[8 + PAYLOAD] = {8,0}, response[2048];
    put16(request + 4, ident);
    uint64_t start = now_us(), next = start, deadline = start + (uint64_t)(count - 1)*interval*1000 + 5000000;
    setvbuf(stdout, NULL, _IOLBF, 0);
    while (now_us() < deadline && (sent < count || received < sent)) {
        uint64_t t = now_us();
        if (sent < count && t >= next) {
            put16(request + 6, sent + 1);
            for (unsigned j = 0; j < PAYLOAD; j++) request[8+j] = (unsigned char)(j ^ (sent+1) ^ (ident >> 8));
            memcpy(request + 8, &t, sizeof(t));
            put16(request + 2, 0); put16(request + 2, checksum(request, sizeof(request)));
            ssize_t n = sendto(fd, request, sizeof(request), 0, (struct sockaddr *)&peer, sizeof(peer));
            if (n != (ssize_t)sizeof(request)) { send_errors++; break; }
            sent_at[sent++] = t;
            next = start + (uint64_t)sent * interval * 1000;
        }
        t = now_us();
        int wait = sent < count ? (int)((next > t ? next - t : 0) / 1000) : 100;
        if (wait > 100) wait = 100;
        struct pollfd pollfd = {.fd = fd, .events = POLLIN};
        int ready = poll(&pollfd, 1, wait);
        if (ready < 0 && errno != EINTR) { perror("poll"); close(fd); return 2; }
        for (;;) {
            struct sockaddr_in from; socklen_t length = sizeof(from);
            ssize_t n = recvfrom(fd, response, sizeof(response), 0, (struct sockaddr *)&from, &length);
            if (n < 0) { if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) break; perror("recvfrom"); close(fd); return 2; }
            t = now_us();
            if (from.sin_addr.s_addr != peer.sin_addr.s_addr || n < 28 || response[0] >> 4 != 4) continue;
            unsigned hlen = (response[0] & 15)*4, total = get16(response+2);
            if (hlen < 20 || total != hlen + sizeof(request) || n < (ssize_t)total || get16(response+6)&0x3fff) continue;
            unsigned char *icmp = response + hlen;
            if (icmp[0] != 0 || icmp[1] != 0 || get16(icmp+4) != ident) continue;
            unsigned seq = get16(icmp+6);
            if (!seq || seq > sent || checksum(icmp, sizeof(request))) { invalid++; continue; }
            uint64_t echoed; memcpy(&echoed, icmp+8, sizeof(echoed));
            bool good = echoed == sent_at[seq-1];
            for (unsigned j = sizeof(echoed); j < PAYLOAD; j++)
                if (icmp[8+j] != (unsigned char)(j ^ seq ^ (ident >> 8))) good = false;
            if (!good) { invalid++; continue; }
            if (received_at[seq-1]) { duplicate++; continue; }
            received_at[seq-1] = t; received++;
            printf("{\"sequence\":%u,\"rtt_us\":%" PRIu64 "}\n", seq, t-sent_at[seq-1]);
        }
    }
    close(fd);
    printf("{\"sent\":%u,\"received\":%u,\"duplicate\":%u,\"invalid\":%u,\"send_errors\":%u,\"missing\":[", sent, received, duplicate, invalid, send_errors);
    bool comma = false;
    for (unsigned j = 0; j < sent; j++) if (!received_at[j]) { printf("%s%u", comma ? "," : "", j+1); comma = true; }
    puts("]}");
    return sent == count && received == count && !invalid && !send_errors ? 0 : 1;
}

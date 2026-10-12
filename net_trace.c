#include "shim_lock.h"
/* UDP receive safety net and tracing.
 *
 * Roblox's network threads wait for socket readiness with kqueue, using
 * edge-triggered EV_CLEAR events (Asio). Darling emulates kqueue on top of
 * epoll, and a lost "data arrived" edge leaves the reader asleep: the socket
 * buffer fills, the kernel drops every further datagram, so no new edge ever
 * comes and the game connection dies with AckTimeout after 20 s. Observed:
 * RakNet socket with a full 512 KB receive queue and thousands of drops.
 *
 * kevent() is therefore wrapped: UDP sockets registered for EVFILT_READ are
 * remembered, waits are split into 50 ms slices, and between slices those
 * sockets are checked with a direct poll (receive_ready). Pending data
 * without an event gets a synthesized EVFILT_READ event, i.e.
 * level-triggered behaviour for UDP. Closing a socket forgets its watches
 * (close() is wrapped as well): Asio closes sockets without EV_DELETE, and a
 * watch left behind reported the next socket with that number to the old
 * socket's owner.
 *
 * A watchdog thread (every 100 ms) also kicks reader threads that leave
 * queued datagrams unread (see check_stalls) and mutex waits that take too
 * long (thread_kick.c).
 *
 * MACOBLOX_TRACE_UDP=1 also prints socket activity every two seconds;
 * MACOBLOX_TRACE_UDP=2 also logs the first 6000 UDP packets one by one (time,
 * size, peer), to see where a handshake waits. */
typedef unsigned int socklen_t;
typedef long ssize_t;
typedef unsigned long size_t;
extern char *getenv(const char *);
extern int getsockopt(int, int, int, void *, socklen_t *);
extern ssize_t recvfrom(int, void *, size_t, int, void *, socklen_t *);
extern ssize_t recvmsg(int, void *, int);
extern ssize_t sendto(int, const void *, size_t, int, const void *, socklen_t);
extern ssize_t sendmsg(int, const void *, int);
extern int poll(void *, unsigned int, int);
extern int kevent(int, const void *, int, void *, int, const void *);
extern int pthread_create(void **, const void *, void *(*)(void *), void *);
extern int snprintf(char *, size_t, const char *, ...);
extern ssize_t write(int, const void *, size_t);
extern int *__error(void);

#define DYLD_INTERPOSE(_replacement, _replacee) \
    __attribute__((used)) static struct { const void *replacement; const void *replacee; } \
    _interpose_##_replacee __attribute__((section("__DATA,__interpose"))) = \
        {(const void *)(unsigned long)&_replacement, (const void *)(unsigned long)&_replacee};

extern unsigned long long mach_absolute_time(void);
#define MSG_PEEK 0x2
#define MSG_DONTWAIT 0x80

static int enabled = -1;
static volatile long udp_recv_calls, udp_recv_ok, udp_recv_bytes, udp_recv_eagain;
static volatile long udp_send_calls, udp_send_ok, udp_send_fail;
static volatile long poll_calls, kevent_calls;
extern long macoblox_thread_id(void);
extern int macoblox_kick(long, int);
extern int macoblox_located(long, char *, size_t);
extern void macoblox_kick_stuck_waiters(unsigned long long);
extern int macoblox_kicks_enabled(void);
extern long macoblox_lock_kick_count(void);
extern void macoblox_sleep_us(unsigned int);
static volatile long reader_tid[1024];
static volatile unsigned long long last_read_time[1024];
static volatile long synthesized_events;
static volatile long emulated_blocking_receives;
static volatile int last_send_errno;

static int trace_enabled(void) {
    if (enabled < 0) {
        const char *value = getenv("MACOBLOX_TRACE_UDP");
        enabled = value && value[0] && value[0] != '0' ? (value[0] == '2' ? 2 : 1) : 0;
    }
    return enabled;
}

static volatile long packets_logged;
static void log_connected(const char *direction, int fd, long result, int error);
static unsigned long long trace_start;

/* One line per packet: ms since the first logged packet, direction, fd,
 * bytes (or -errno) and the peer from a sockaddr_in. */
static void log_packet(const char *direction, int fd, long result, int error, const void *peer) {
    /* Only network packets: Roblox's threads wake each other with one-byte
     * datagrams on a local socket pair, thousands per second. */
    const unsigned char *family = peer;
    if (trace_enabled() != 2 || !family || family[1] != 2 /* AF_INET */ ||
        __sync_add_and_fetch(&packets_logged, 1) > 6000)
        return;
    unsigned long long now = mach_absolute_time();
    if (!trace_start)
        trace_start = now;
    const unsigned char *address = peer;
    char where[40] = "";
    if (address && address[1] == 2 /* AF_INET */)
        snprintf(where, sizeof where, " %u.%u.%u.%u:%u", address[4], address[5], address[6],
                 address[7], (unsigned)(address[2] << 8 | address[3]));
    char line[160];
    int length = snprintf(line, sizeof line, "[Cider PKT] %7.1fms %s fd=%d %ld%s\n",
                          (now - trace_start) / 1e6, direction, fd,
                          result < 0 ? -(long)error : result, where);
    if (length > 0)
        write(2, line, (size_t)length);
}

/* An integer socket option read with a direct Linux getsockopt (these run
 * for every received packet), -1 if `fd` is not a socket. */
static long linux_socket_option(int fd, long name) {
    int value = 0;
    unsigned int length = sizeof value;
    long result;
    register long address __asm__("r10") = (long)&value;
    register long size __asm__("r8") = (long)&length;
    __asm__ volatile("syscall"
                     : "=a"(result)
                     : "a"(55L /* Linux getsockopt */), "D"((long)fd), "S"(1L /* SOL_SOCKET */), "d"(name),
                       "r"(address), "r"(size)
                     : "rcx", "r11", "memory");
    return result < 0 ? -1 : value;
}

/* Any datagram socket, local socket pairs included. */
static int is_udp(int fd) {
    return linux_socket_option(fd, 3 /* SO_TYPE */) == 2 /* SOCK_DGRAM */;
}

/* A datagram socket on the network (IPv4 or IPv6), not a local socket pair:
 * Roblox's threads wake each other with one-byte datagrams on local pairs,
 * and such a byte may wait while its thread is busy elsewhere. */
static int is_network_udp(int fd) {
    if (!is_udp(fd))
        return 0;
    long family = linux_socket_option(fd, 39 /* SO_DOMAIN */);
    return family == 2 /* AF_INET */ || family == 10 /* Linux AF_INET6 */;
}

/* Would a receive on `fd` return at once: 1 when data (or end of stream) is
 * queued or an error is pending, 0 when there is nothing, -1 when `fd` is
 * not open.
 *
 * MSG_DONTWAIT does not work in Darling: it passes the receive flags to
 * Linux as they are, and macOS MSG_DONTWAIT (0x80) is Linux MSG_EOR, so a
 * "non-blocking" receive on a blocking socket sleeps until data arrives
 * (checked in Darling). A direct Linux poll with no timeout asks instead. It
 * used to be a MSG_PEEK receive, but any receive, even a peek, takes a
 * socket's pending error (ICMP "port unreachable" on a connected UDP socket)
 * away from the real receive, which then blocked or never learned of it. */
static int receive_ready(int fd) {
    struct { int fd; short events, revents; } entry = {fd, 0x1 /* POLLIN */, 0};
    long result;
    __asm__ volatile("syscall"
                     : "=a"(result)
                     : "a"(7L /* Linux poll */), "D"(&entry), "S"(1L), "d"(0L)
                     : "rcx", "r11", "memory");
    if (result < 0 || (entry.revents & 0x20 /* POLLNVAL */))
        return -1;
    return (entry.revents & (0x1 /* POLLIN */ | 0x8 /* POLLERR */ | 0x10 /* POLLHUP */)) != 0;
}

/* Bytes queued for reading (for a datagram socket: the size of the next
 * datagram), with a direct Linux ioctl(FIONREAD). */
static long queued_bytes(int fd) {
    int bytes = 0;
    long result;
    __asm__ volatile("syscall"
                     : "=a"(result)
                     : "a"(16L /* Linux ioctl */), "D"((long)fd), "S"(0x541BL /* FIONREAD */), "d"(&bytes)
                     : "rcx", "r11", "memory");
    return result < 0 ? 0 : bytes;
}

/* The socket's inode (st_ino from a direct Linux fstat), which tells a
 * watched socket from a later one that got the same number; 0 if `fd` is
 * not open. */
static unsigned long socket_inode(int fd) {
    unsigned long status[18]; /* Linux x86_64 struct stat: 144 bytes, st_ino at 8 */
    long result;
    __asm__ volatile("syscall"
                     : "=a"(result)
                     : "a"(5L /* Linux fstat */), "D"((long)fd), "S"(status)
                     : "rcx", "r11", "memory");
    return result < 0 ? 0 : status[1];
}

/* Stall watchdog. A datagram that waits unread for 300 ms means a stalled
 * reader: the thread is kicked (thread_kick.c), and again 0.6, 1.2, 2.4 and
 * 4.8 s later while the stall lasts. The wait counts from the first check
 * that saw the data, not from the last read: a quiet socket that just got a
 * datagram is not stalled (counting from the last read, most "stalls" in
 * game were such sockets). The old watchdog kicked once, after 2 s, from a
 * check every second. The first stalls are logged with the place the reader
 * was kicked from. Sockets unread for over 30 s are left alone: such a
 * socket may belong to a reader that has exited. */
#define WATCHDOG_TICK_US 100000
#define STALL_NS 300000000ULL
#define STALL_MAX_NS 30000000000ULL
#define STALL_KICKS 5
static unsigned long long pending_since[1024]; /* first check that saw unread data, 0 = none */
static unsigned long long stall_since[1024]; /* last read before the stall, 0 = none */
static unsigned long long stall_next_kick[1024];
static int stall_kicks[1024], stall_locating[1024];
static long stall_tid[1024];
static long stalls_seen;

/* Write what snprintf put in `line` (`length` as it returned). */
static void say(const char *line, size_t size, int length) {
    if (length > 0)
        write(2, line, (size_t)length < size ? (size_t)length : size - 1);
}

static void check_stalls(unsigned long long now) {
    for (int fd = 0; fd < 1024; fd++) {
        unsigned long long last = last_read_time[fd];
        if (!reader_tid[fd] || !last) { /* not read yet, or closed (forget_fd) */
            stall_since[fd] = pending_since[fd] = 0;
            stall_locating[fd] = 0;
            continue;
        }
        if (stall_since[fd]) {
            char where[1200], line[1400];
            if (stall_locating[fd] && macoblox_located(stall_tid[fd], where, sizeof where)) {
                stall_locating[fd] = 0;
                say(line, sizeof line,
                    snprintf(line, sizeof line, "[Cider UDP] fd=%d reader thread was at: %s\n", fd, where));
            }
            if (last != stall_since[fd]) {
                say(line, sizeof line,
                    snprintf(line, sizeof line,
                             "[Cider UDP] fd=%d read again ~%llu ms after its data came (%d kick(s))\n", fd,
                             last > pending_since[fd] ? (last - pending_since[fd]) / 1000000ULL : 0ULL,
                             stall_kicks[fd]));
                stall_since[fd] = 0;
                stall_locating[fd] = 0;
                pending_since[fd] = 0;
                continue;
            }
            if (stall_kicks[fd] < STALL_KICKS && now >= stall_next_kick[fd] && now - last <= STALL_MAX_NS) {
                macoblox_kick(stall_tid[fd], 0);
                stall_next_kick[fd] = now + (STALL_NS << stall_kicks[fd]);
                stall_kicks[fd]++;
            }
            continue;
        }
        /* A read recorded after `now` was taken (another thread) gives a
         * negative age; a socket idle for long may belong to a reader thread
         * that has exited. */
        if (last > now || now - last < STALL_NS / 3 || now - last > STALL_MAX_NS || receive_ready(fd) <= 0) {
            pending_since[fd] = 0;
            continue;
        }
        if (!pending_since[fd] || pending_since[fd] < last) { /* data seen for the first time */
            pending_since[fd] = now;
            continue;
        }
        /* The number may belong to another file by now. Only network sockets
         * count: a local wakeup socket's byte may wait for a busy thread, and
         * a kick would interrupt whatever that thread is doing. */
        if (now - pending_since[fd] < STALL_NS || !is_network_udp(fd))
            continue;
        long seen = ++stalls_seen;
        stall_since[fd] = last;
        stall_tid[fd] = reader_tid[fd];
        stall_kicks[fd] = 1;
        stall_next_kick[fd] = now + 2 * STALL_NS;
        stall_locating[fd] = seen <= 30 || seen % 50 == 0;
        char line[160];
        say(line, sizeof line,
            snprintf(line, sizeof line,
                     "[Cider UDP] STALL fd=%d: data unread for %llu ms (last read %llu ms ago), %s thread %ld\n",
                     fd, (now - pending_since[fd]) / 1000000ULL, (now - last) / 1000000ULL,
                     macoblox_kicks_enabled() ? "kicking" : "not kicking (MACOBLOX_NO_KICK)", stall_tid[fd]));
        macoblox_kick(stall_tid[fd], stall_locating[fd]);
    }
}

static void *watchdog(void *unused) {
    (void)unused;
    long previous[9] = {0};
    for (unsigned long tick = 1;; tick++) {
        macoblox_sleep_us(WATCHDOG_TICK_US); /* not usleep: see darling_fixes.c */
        unsigned long long now = mach_absolute_time();
        check_stalls(now);
        macoblox_kick_stuck_waiters(now);
        if (!trace_enabled() || tick % 20)
            continue;
        long current[9] = {udp_recv_calls, udp_recv_ok, udp_recv_bytes, udp_recv_eagain,
                           udp_send_calls, udp_send_ok, udp_send_fail, poll_calls, kevent_calls};
        char line[360];
        int length = snprintf(line, sizeof line,
            "[Cider UDP] t=%lus recv calls=%ld ok=%ld bytes=%ld eagain=%ld | "
            "send calls=%ld ok=%ld fail=%ld errno=%d | poll=%ld kevent=%ld | synthesized=%ld emulated=%ld "
            "| stalls=%ld lock kicks=%ld\n",
            tick / 10, current[0] - previous[0], current[1] - previous[1], current[2] - previous[2],
            current[3] - previous[3], current[4] - previous[4], current[5] - previous[5],
            current[6] - previous[6], last_send_errno, current[7] - previous[7], current[8] - previous[8],
            synthesized_events, emulated_blocking_receives, stalls_seen, macoblox_lock_kick_count());
        if (length > 0)
            write(2, line, (size_t)length);
        for (int index = 0; index < 9; index++)
            previous[index] = current[index];
    }
    return 0;
}

__attribute__((constructor)) static void start_watchdog(void) {
    void *thread;
    pthread_create(&thread, 0, watchdog, 0);
}


static void count_receive(int fd, ssize_t result) {
    if (!is_network_udp(fd))
        return;
    if (trace_enabled())
        __sync_add_and_fetch(&udp_recv_calls, 1);
    if (fd >= 0 && fd < 1024) {
        reader_tid[fd] = macoblox_thread_id();
        if (result > 0)
            last_read_time[fd] = mach_absolute_time();
    }
    if (!trace_enabled())
        return;
    if (result > 0) {
        __sync_add_and_fetch(&udp_recv_ok, 1);
        __sync_add_and_fetch(&udp_recv_bytes, result);
    } else if (result < 0 && (*__error() == 35 /* EAGAIN */)) {
        __sync_add_and_fetch(&udp_recv_eagain, 1);
    }
}

static void count_send(int fd, ssize_t result) {
    if (!trace_enabled() || !is_udp(fd))
        return;
    __sync_add_and_fetch(&udp_send_calls, 1);
    if (result >= 0) {
        __sync_add_and_fetch(&udp_send_ok, 1);
    } else {
        __sync_add_and_fetch(&udp_send_fail, 1);
        last_send_errno = *__error();
    }
}

/* Darling's blocking receive can stay asleep while datagrams are queued: the
 * RakNet receive thread blocked in recvfrom() on a socket with a full 512 KB
 * queue and never returned. For blocking UDP sockets, wait with poll() in
 * 50 ms slices and receive only once a datagram is queued (receive_ready),
 * honouring SO_RCVTIMEO. A caller's MSG_DONTWAIT is made to work the same
 * way (see receive_ready). */
extern int fcntl(int, int, ...);
struct darwin_pollfd { int fd; short events, revents; };
struct darwin_timeval { long tv_sec; int tv_usec; };
#define DARWIN_O_NONBLOCK 0x4
#define DARWIN_EAGAIN 35
#define DARWIN_EINTR 4

static int wait_readable_or_timeout(int fd, unsigned long long start, long long timeout_ns) {
    struct darwin_pollfd entry = {fd, 1 /* POLLIN */, 0};
    int slice = 50;
    if (timeout_ns > 0) {
        long long left = timeout_ns - (long long)(mach_absolute_time() - start);
        if (left <= 0)
            return 0;
        if (left < 50000000LL)
            slice = (int)(left / 1000000LL) + 1;
    }
    poll(&entry, 1, slice);
    return 1;
}

static int emulate_blocking(int fd, int flags, long long *timeout_ns) {
    if (flags & MSG_DONTWAIT)
        return 0;
    int status = fcntl(fd, 3 /* F_GETFL */);
    if (status < 0 || (status & DARWIN_O_NONBLOCK) || !is_udp(fd))
        return 0;
    struct darwin_timeval timeout = {0, 0};
    socklen_t length = sizeof timeout;
    *timeout_ns = 0;
    if (getsockopt(fd, 0xffff, 0x1006 /* SO_RCVTIMEO */, &timeout, &length) == 0)
        *timeout_ns = timeout.tv_sec * 1000000000LL + timeout.tv_usec * 1000LL;
    return 1;
}

/* Socket timeouts: Darling hands the SO_SNDTIMEO/SO_RCVTIMEO value to Linux
 * as it is. A macOS struct timeval (long, int) has four bytes of padding
 * where Linux's (long, long) has the upper half of tv_usec; callers seldom
 * clear it, so Linux saw a huge tv_usec and failed with EDOM ("RakNet: failed
 * to set send timeout on socket: Numerical argument out of domain" in every
 * game join). Pass the Linux layout with the padding cleared instead. */
extern int setsockopt(int, int, int, const void *, socklen_t);

static int macoblox_setsockopt(int fd, int level, int name, const void *value, socklen_t length) {
    if (level == 0xffff /* SOL_SOCKET */ && (name == 0x1005 /* SO_SNDTIMEO */ || name == 0x1006 /* SO_RCVTIMEO */) &&
        value && length == sizeof(struct darwin_timeval)) {
        const struct darwin_timeval *timeout = value;
        struct { long tv_sec, tv_usec; } clean = {timeout->tv_sec, timeout->tv_usec};
        return setsockopt(fd, level, name, &clean, sizeof clean);
    }
    return setsockopt(fd, level, name, value, length);
}
DYLD_INTERPOSE(macoblox_setsockopt, setsockopt)

static ssize_t traced_recvfrom(int fd, void *buffer, size_t size, int flags, void *from,
                               socklen_t *from_length) {
    long long timeout_ns;
    if (emulate_blocking(fd, flags, &timeout_ns)) {
        __sync_add_and_fetch(&emulated_blocking_receives, 1);
        unsigned long long start = mach_absolute_time();
        socklen_t length_in = from_length ? *from_length : 0;
        for (;;) {
            if (from_length)
                *from_length = length_in;
            if (receive_ready(fd)) {
                ssize_t result = recvfrom(fd, buffer, size, flags, from, from_length);
                int saved = *__error();
                if (trace_enabled() == 2)
                    log_packet("recv", fd, result, saved, from);
                count_receive(fd, result);
                *__error() = saved;
                return result;
            }
            if (!wait_readable_or_timeout(fd, start, timeout_ns)) {
                *__error() = DARWIN_EAGAIN;
                return -1;
            }
        }
    }
    if ((flags & MSG_DONTWAIT) && receive_ready(fd) == 0) {
        *__error() = DARWIN_EAGAIN;
        return -1;
    }
    ssize_t result = recvfrom(fd, buffer, size, flags & ~MSG_DONTWAIT, from, from_length);
    int saved = *__error();
    if (!(result < 0 && saved == DARWIN_EAGAIN) && trace_enabled() == 2 && is_udp(fd))
        log_packet("recv", fd, result, saved, from);
    count_receive(fd, result);
    *__error() = saved;
    return result;
}
DYLD_INTERPOSE(traced_recvfrom, recvfrom)

static ssize_t traced_recvmsg(int fd, void *message, int flags) {
    long long timeout_ns;
    if (emulate_blocking(fd, flags, &timeout_ns)) {
        __sync_add_and_fetch(&emulated_blocking_receives, 1);
        unsigned long long start = mach_absolute_time();
        /* struct msghdr: name length at offset 8 is updated on return. */
        socklen_t name_length = *(socklen_t *)((char *)message + 8);
        for (;;) {
            *(socklen_t *)((char *)message + 8) = name_length;
            if (receive_ready(fd)) {
                ssize_t result = recvmsg(fd, message, flags);
                int saved = *__error();
                if (trace_enabled() == 2 && is_udp(fd)) {
                    if (*(void **)message)
                        log_packet("recv", fd, result, saved, *(void **)message);
                    else
                        log_connected("recv", fd, result, saved);
                }
                count_receive(fd, result);
                *__error() = saved;
                return result;
            }
            if (!wait_readable_or_timeout(fd, start, timeout_ns)) {
                *__error() = DARWIN_EAGAIN;
                return -1;
            }
        }
    }
    if ((flags & MSG_DONTWAIT) && receive_ready(fd) == 0) {
        *__error() = DARWIN_EAGAIN;
        return -1;
    }
    ssize_t result = recvmsg(fd, message, flags & ~MSG_DONTWAIT);
    int saved = *__error();
    if (!(result < 0 && saved == DARWIN_EAGAIN) && trace_enabled() == 2 && is_udp(fd)) {
        if (*(void **)message)
            log_packet("recv", fd, result, saved, *(void **)message);
        else
            log_connected("recv", fd, result, saved);
    }
    count_receive(fd, result);
    *__error() = saved;
    return result;
}
DYLD_INTERPOSE(traced_recvmsg, recvmsg)

static ssize_t traced_sendto(int fd, const void *buffer, size_t size, int flags,
                             const void *to, socklen_t to_length) {
    ssize_t result = sendto(fd, buffer, size, flags, to, to_length);
    int saved = *__error();
    if (trace_enabled() == 2 && is_udp(fd))
        log_packet("send", fd, result, saved, to);
    count_send(fd, result);
    *__error() = saved;
    return result;
}
DYLD_INTERPOSE(traced_sendto, sendto)

static ssize_t traced_sendmsg(int fd, const void *message, int flags) {
    ssize_t result = sendmsg(fd, message, flags);
    int saved = *__error();
    if (trace_enabled() == 2 && is_udp(fd)) {
        const void *name = message ? *(void *const *)message : 0;
        if (name)
            log_packet("send", fd, result, saved, name);
        else
            log_connected("send", fd, result, saved);
    }
    count_send(fd, result);
    *__error() = saved;
    return result;
}
DYLD_INTERPOSE(traced_sendmsg, sendmsg)

/* Connected UDP sockets (the QUIC transport) use send()/recv(), which do
 * not go through sendto()/recvfrom(); log them with the connected peer. */
extern ssize_t send(int, const void *, size_t, int);
extern ssize_t recv(int, void *, size_t, int);
extern int getpeername(int, void *, socklen_t *);

static void log_connected(const char *direction, int fd, long result, int error) {
    if (trace_enabled() != 2 || (result < 0 && error == DARWIN_EAGAIN) || !is_udp(fd))
        return;
    unsigned char peer[128];
    socklen_t length = sizeof peer;
    if (getpeername(fd, peer, &length) == 0)
        log_packet(direction, fd, result, error, peer);
}

static ssize_t traced_send(int fd, const void *buffer, size_t size, int flags) {
    ssize_t result = send(fd, buffer, size, flags);
    int saved = *__error();
    log_connected("send", fd, result, saved);
    count_send(fd, result);
    *__error() = saved;
    return result;
}
DYLD_INTERPOSE(traced_send, send)

static ssize_t traced_recv(int fd, void *buffer, size_t size, int flags) {
    if ((flags & MSG_DONTWAIT) && receive_ready(fd) == 0) {
        *__error() = DARWIN_EAGAIN;
        return -1;
    }
    ssize_t result = recv(fd, buffer, size, flags & ~MSG_DONTWAIT);
    int saved = *__error();
    log_connected("recv", fd, result, saved);
    count_receive(fd, result);
    *__error() = saved;
    return result;
}
DYLD_INTERPOSE(traced_recv, recv)

static int traced_poll(void *fds, unsigned int count, int timeout) {
    if (trace_enabled())
        __sync_add_and_fetch(&poll_calls, 1);
    return poll(fds, count, timeout);
}
DYLD_INTERPOSE(traced_poll, poll)

struct darwin_kevent {
    unsigned long ident;
    short filter;
    unsigned short flags;
    unsigned int fflags;
    long data;
    void *udata;
};
struct darwin_timespec { long tv_sec, tv_nsec; };
#define EVFILT_READ (-1)
#define EV_ADD 0x0001
#define EV_DELETE 0x0002
#define EV_ENABLE 0x0004
#define EV_DISABLE 0x0008
#define EV_ONESHOT 0x0010
#define EV_RECEIPT 0x0040
#define EV_DISPATCH 0x0080
#define MAX_WATCHED 256
#define MAX_MISSED 64
static struct {
    int queue, fd, enabled;
    unsigned short flags;
    unsigned long inode; /* which socket had the number when it was added */
    void *udata;
} watched[MAX_WATCHED];
static volatile unsigned int watched_lock;
static volatile int watched_count;

static volatile long synthesized_by_fd[1024];

static void lock_watched(void) {
    macoblox_lock(&watched_lock);
}
static void unlock_watched(void) { macoblox_unlock(&watched_lock); }

static void drop_watch(int slot) { /* with the lock held */
    watched[slot].fd = 0;
    watched_count--;
}

static void record_changes(int queue, const struct darwin_kevent *changes, int count) {
    for (int index = 0; index < count; index++) {
        const struct darwin_kevent *change = &changes[index];
        if (change->filter != EVFILT_READ || change->ident >= 1024)
            continue;
        int fd = (int)change->ident;
        if (!(change->flags & (EV_ADD | EV_DELETE | EV_ENABLE | EV_DISABLE)))
            continue;
        /* Another kind of socket added under the number of a watched one
         * (closed without being seen here) replaces that watch. */
        int watch = !(change->flags & EV_ADD) || is_udp(fd);
        unsigned long inode = (change->flags & EV_ADD) && watch ? socket_inode(fd) : 0;
        lock_watched();
        int slot = -1, free_slot = -1;
        for (int i = 0; i < MAX_WATCHED; i++) {
            if (watched[i].fd > 0 && watched[i].queue == queue && watched[i].fd == fd) slot = i;
            else if (watched[i].fd <= 0 && free_slot < 0) free_slot = i;
        }
        if ((change->flags & EV_DELETE) || !watch) {
            if (slot >= 0)
                drop_watch(slot);
        } else if (change->flags & EV_ADD) {
            if (slot < 0 && free_slot >= 0) {
                slot = free_slot;
                watched_count++;
            }
            if (slot >= 0) {
                watched[slot].queue = queue;
                watched[slot].fd = fd;
                watched[slot].flags = change->flags & ~(EV_ADD | EV_ENABLE | EV_DISABLE | EV_RECEIPT);
                watched[slot].inode = inode;
                watched[slot].udata = change->udata;
                watched[slot].enabled = !(change->flags & EV_DISABLE);
            }
        } else if (slot >= 0) {
            watched[slot].enabled = (change->flags & EV_ENABLE) != 0;
        }
        unlock_watched();
    }
}

/* A closed descriptor: forget its reader and its watches, and the watches of
 * a kqueue that is closed. A real kqueue drops a closed descriptor's events by
 * itself, so Asio closes sockets without EV_DELETE. */
static void forget_fd(int fd) {
    if (fd < 0)
        return;
    if (fd < 1024) {
        reader_tid[fd] = 0;
        last_read_time[fd] = 0;
    }
    if (!watched_count)
        return;
    lock_watched();
    for (int i = 0; i < MAX_WATCHED; i++)
        if (watched[i].fd > 0 && (watched[i].fd == fd || watched[i].queue == fd))
            drop_watch(i);
    unlock_watched();
}

/* Roblox closes with close$NOCANCEL, Darling's frameworks with close. */
extern int close(int);
extern int close_nocancel(int) __asm__("_close$NOCANCEL");

static int macoblox_close(int fd) {
    forget_fd(fd);
    return close(fd);
}
DYLD_INTERPOSE(macoblox_close, close)

static int macoblox_close_nocancel(int fd) {
    forget_fd(fd);
    return close_nocancel(fd);
}
DYLD_INTERPOSE(macoblox_close_nocancel, close_nocancel)

/* Read events for watched UDP sockets of this queue that have data waiting,
 * up to `capacity`, written to `found` (not to the caller's array: that may
 * be the change list, which is applied after this). */
static int find_missed_events(int queue, struct darwin_kevent *found, int capacity) {
    int fds[MAX_WATCHED], slots[MAX_WATCHED];
    unsigned short flags[MAX_WATCHED];
    unsigned long inodes[MAX_WATCHED];
    void *udata[MAX_WATCHED];
    int count = 0, missed = 0;
    lock_watched();
    for (int i = 0; i < MAX_WATCHED; i++) {
        if (watched[i].fd > 0 && watched[i].queue == queue && watched[i].enabled) {
            fds[count] = watched[i].fd;
            slots[count] = i;
            flags[count] = watched[i].flags;
            inodes[count] = watched[i].inode;
            udata[count] = watched[i].udata;
            count++;
        }
    }
    unlock_watched();
    for (int i = 0; i < count && missed < capacity; i++) {
        int ready = receive_ready(fds[i]);
        /* A closed socket, or another one with the same number now: the
         * watch is stale. The event would go to the old socket's owner. */
        int stale = ready < 0 || (ready && socket_inode(fds[i]) != inodes[i]);
        int once = !stale && ready && (flags[i] & (EV_ONESHOT | EV_DISPATCH));
        if (stale || once) {
            lock_watched();
            if (watched[slots[i]].fd == fds[i] && watched[slots[i]].queue == queue &&
                watched[slots[i]].inode == inodes[i]) {
                if (stale || (flags[i] & EV_ONESHOT))
                    drop_watch(slots[i]);
                else
                    watched[slots[i]].enabled = 0; /* EV_DISPATCH: off until EV_ENABLE */
            }
            unlock_watched();
        }
        if (stale || !ready)
            continue;
        struct darwin_kevent *event = &found[missed++];
        event->ident = (unsigned long)fds[i];
        event->filter = EVFILT_READ;
        event->flags = flags[i];
        event->fflags = 0;
        event->data = queued_bytes(fds[i]);
        event->udata = udata[i];
    }
    return missed;
}

/* Add the found events to the `returned` events in `out`, except for sockets
 * that already have one there. */
static int add_missed_events(struct darwin_kevent *out, int returned, int capacity,
                             const struct darwin_kevent *found, int count) {
    for (int i = 0; i < count && returned < capacity; i++) {
        int reported = 0;
        for (int j = 0; j < returned && !reported; j++)
            reported = out[j].filter == EVFILT_READ && out[j].ident == found[i].ident;
        if (reported)
            continue;
        out[returned++] = found[i];
        __sync_add_and_fetch(&synthesized_events, 1);
        __sync_add_and_fetch(&synthesized_by_fd[found[i].ident], 1);
    }
    return returned;
}

static int queue_has_watched(int queue) {
    if (!watched_count)
        return 0;
    int found = 0;
    lock_watched();
    for (int i = 0; i < MAX_WATCHED && !found; i++)
        found = watched[i].fd > 0 && watched[i].queue == queue && watched[i].enabled;
    unlock_watched();
    return found;
}

static int traced_kevent(int queue, const void *changes, int change_count, void *events,
                         int event_count, const void *timeout) {
    if (trace_enabled())
        __sync_add_and_fetch(&kevent_calls, 1);
    if (change_count > 0 && changes)
        record_changes(queue, (const struct darwin_kevent *)changes, change_count);
    if (event_count <= 0 || !events || !queue_has_watched(queue))
        return kevent(queue, changes, change_count, events, event_count, timeout);

    const struct darwin_timespec *limit = (const struct darwin_timespec *)timeout;
    unsigned long long start = mach_absolute_time();
    long long budget = limit ? limit->tv_sec * 1000000000LL + limit->tv_nsec : -1;
    struct darwin_kevent *out = (struct darwin_kevent *)events;
    struct darwin_kevent found[MAX_MISSED];
    int first = 1;
    for (;;) {
        /* Data already waiting without an event: report it right away. */
        int missed = find_missed_events(queue, found, event_count < MAX_MISSED ? event_count : MAX_MISSED);
        if (missed > 0) {
            int returned = 0;
            if (first && change_count > 0) {
                /* Apply the change list without waiting; its receipts and
                 * errors, and any events, come first. */
                struct darwin_timespec zero = {0, 0};
                returned = kevent(queue, changes, change_count, out, event_count, &zero);
                if (returned < 0)
                    return returned;
            }
            return add_missed_events(out, returned, event_count, found, missed);
        }
        long long slice = 50000000LL;
        if (budget >= 0) {
            long long left = budget - (long long)(mach_absolute_time() - start);
            if (left <= 0) left = 0;
            if (left < slice) slice = left;
        }
        struct darwin_timespec wait = {slice / 1000000000LL, slice % 1000000000LL};
        int result = kevent(queue, first ? changes : 0, first ? change_count : 0,
                            events, event_count, &wait);
        first = 0;
        if (result != 0)
            return result;
        if (budget >= 0 && (long long)(mach_absolute_time() - start) >= budget)
            return 0;
    }
}
DYLD_INTERPOSE(traced_kevent, kevent)

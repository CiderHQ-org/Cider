// Fixture: does a blocked kevent() notice work posted by another thread, and does QUADRA_KEVENT_POLL_MS cut
// an idle wait short on a thread named like Roblox's I/O loops (and only on those)? Each wake case blocks the
// "RBX IoEvLoop 0" thread in kevent() with a long timeout, posts work from a second thread after 200 ms and reports
// how long the waiter took; then an empty kqueue is waited on under that name and under another one. argv[1] is
// the cap in milliseconds the shim was told (0 or absent: none). Built as Mach-O, run in a disposable Darling
// prefix. The shim ends the process without flushing stdio, so every line is flushed.
typedef unsigned long long u64;
typedef unsigned long size_t;
typedef struct _opaque_pthread_t *pthread_t;
struct kev { unsigned long ident; short filter; unsigned short flags; unsigned fflags; long data; void *udata; };
struct tspec { long sec, nsec; };
extern int kqueue(void), kevent(int, const struct kev *, int, struct kev *, int, const struct tspec *);
extern int pipe(int *), close(int), usleep(unsigned), printf(const char *, ...), atoi(const char *), fflush(void *);
extern int fcntl(int, int, ...);
extern long write(int, const void *, size_t), read(int, void *, size_t);
extern int pthread_create(pthread_t *, const void *, void *(*)(void *), void *), pthread_join(pthread_t, void **);
extern u64 clock_gettime_nsec_np(int);
extern int pthread_setname_np(const char *);
extern void *__stdoutp;
#define say(...) do { printf(__VA_ARGS__); fflush(__stdoutp); } while (0)

#define MONO 4
#define EVFILT_READ (-1)
#define EVFILT_TIMER (-7)
#define EVFILT_USER (-10)
#define EV_ADD 1
#define EV_DELETE 2
#define EV_CLEAR 0x20
#define EV_ONESHOT 0x10
#define NOTE_TRIGGER 0x01000000u

static int kq, fds[2];
static int failures;
static u64 now_ms(void) { return clock_gettime_nsec_np(MONO) / 1000000ULL; }

static void report(const char *name, long waited, int events, long limit) {
    int ok = waited <= limit && events > 0;
    say("%s %-46s waited %5ld ms (events %d, limit %ld)\n", ok ? "PASS" : "FAIL", name, waited, events, limit);
    if (!ok) failures++;
}
// One kevent() call, as a caller that treats an empty return as "timed out" sees it.
static int wait_once(long timeout_ms, long *waited) {
    struct kev out[4];
    struct tspec ts = {timeout_ms / 1000, (timeout_ms % 1000) * 1000000L};
    u64 start = now_ms();
    int n = kevent(kq, 0, 0, out, 4, &ts);
    *waited = (long)(now_ms() - start);
    return n;
}
// What an event loop does: wait again after an empty return until the real deadline.
static int wait_for_event(long timeout_ms, long *waited) {
    u64 start = now_ms();
    int n = 0;
    while ((long)(now_ms() - start) < timeout_ms) {
        long left = timeout_ms - (long)(now_ms() - start), ignored;
        n = wait_once(left, &ignored);
        if (n != 0) break;
    }
    *waited = (long)(now_ms() - start);
    return n;
}
static void change(int filter, unsigned flags, unsigned fflags, unsigned long ident, long data) {
    struct kev c = {ident, (short)filter, (unsigned short)flags, fflags, data, 0};
    kevent(kq, &c, 1, 0, 0, 0);
}

static void *post_pipe(void *unused) { (void)unused; usleep(200000); (void)!write(fds[1], "x", 1); return 0; }
static void *post_user(void *unused) { (void)unused; usleep(200000); change(EVFILT_USER, 0, NOTE_TRIGGER, 7, 0); return 0; }
static void *add_timer(void *unused) { (void)unused; usleep(200000); change(EVFILT_TIMER, EV_ADD | EV_ONESHOT, 0, 9, 300); return 0; }
static void *add_pipe_then_write(void *unused) {
    (void)unused; usleep(200000);
    change(EVFILT_READ, EV_ADD, 0, (unsigned long)fds[0], 0);
    usleep(100000);
    (void)!write(fds[1], "y", 1);
    return 0;
}
static void drain(void) {
    char b[16]; struct kev out[4]; struct tspec zero = {0, 0};
    (void)!read(fds[0], b, sizeof b);
    for (int round = 0; round < 8 && kevent(kq, 0, 0, out, 4, &zero) > 0; round++)
        (void)!read(fds[0], b, sizeof b);
}

static void run_case(const char *name, void *(*poster)(void *), long limit) {
    pthread_t thread; long waited;
    pthread_create(&thread, 0, poster, 0);
    int n = wait_for_event(8000, &waited);
    pthread_join(thread, 0);
    report(name, waited, n, limit);
    drain();
}

int main(int argc, char **argv) {
    long cap = argc > 1 ? atoi(argv[1]) : 0;
    pthread_setname_np("RBX IoEvLoop 0");
    kq = kqueue();
    if (kq < 0 || pipe(fds) != 0) { say("FAIL setup\n"); return 1; }
    fcntl(fds[0], 4 /* F_SETFL */, 4 /* O_NONBLOCK */);
    change(EVFILT_READ, EV_ADD | EV_CLEAR, 0, (unsigned long)fds[0], 0);
    run_case("pipe written by another thread", post_pipe, 600);
    change(EVFILT_USER, EV_ADD | EV_CLEAR, 0, 7, 0);
    run_case("EVFILT_USER triggered by another thread", post_user, 600);
    run_case("EVFILT_TIMER added by another thread while blocked", add_timer, 900);
    change(EVFILT_READ, EV_DELETE, 0, (unsigned long)fds[0], 0);
    run_case("EVFILT_READ added by another thread while blocked", add_pipe_then_write, 900);
    long waited;
    int n = wait_once(1000, &waited);
    say("INFO an empty wait of 1000 ms on the I/O loop thread returned after %ld ms with %d events\n", waited, n);
    if (cap > 0) {  // the cap must cut the I/O loop's idle wait short and report no events
        int ok = waited <= cap + 150 && n == 0;
        say("%s the I/O loop's empty wait was capped at %ld ms\n", ok ? "PASS" : "FAIL", cap);
        if (!ok) failures++;
    } else if (waited < 900) {
        say("FAIL an uncapped empty wait returned early\n");
        failures++;
    }
    pthread_setname_np("RBX Worker A");  // any other thread keeps its full wait
    n = wait_once(1000, &waited);
    say("%s an empty wait on another thread lasted %ld ms with %d events\n", waited >= 900 ? "PASS" : "FAIL", waited, n);
    if (waited < 900) failures++;
    say(failures ? "RESULT FAIL %d\n" : "RESULT PASS\n", failures);
    return failures ? 1 : 0;
}

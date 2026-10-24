// Fixture for `quadrahq --watch-stalls`: one thread spins inside nested functions, one waits
// on a pipe and the main thread sleeps; the process ends after argv[1] seconds. Built as
// Mach-O with frame pointers, like the game, so the watcher can name the functions.
typedef struct _opaque_pthread_t *pthread_t;
extern int pthread_create(pthread_t *, const void *, void *(*)(void *), void *);
extern int pipe(int *), atoi(const char *);
extern long read(int, void *, unsigned long), write(int, const void *, unsigned long);
extern unsigned sleep(unsigned);

static int pipe_fds[2];
volatile unsigned long stall_watch_sink;

__attribute__((noinline)) unsigned long stall_watch_inner(unsigned long value) {
    for (int index = 0; index < 4000; index++)
        value = value * 6364136223846793005UL + 1442695040888963407UL;
    return value;
}

__attribute__((noinline)) void stall_watch_outer(void) {
    for (;;)
        stall_watch_sink = stall_watch_inner(stall_watch_sink);
}

__attribute__((noinline)) void stall_watch_wait_for_pipe(void) {
    char byte;
    (void)!read(pipe_fds[0], &byte, 1);
}

static void *spinner(void *unused) {
    (void)unused;
    stall_watch_outer();
    return 0;
}

static void *waiter(void *unused) {
    (void)unused;
    stall_watch_wait_for_pipe();
    return 0;
}

int main(int argc, char **argv) {
    int seconds = argc > 1 ? atoi(argv[1]) : 20;
    pthread_t spin, wait;
    if (pipe(pipe_fds) != 0 || pthread_create(&spin, 0, spinner, 0) != 0 ||
        pthread_create(&wait, 0, waiter, 0) != 0)
        return 1;
    (void)!write(1, "ready\n", 6);
    sleep(seconds);
    return 0;
}

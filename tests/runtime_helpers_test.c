/* clang -O2 -pthread tests/runtime_helpers_test.c worker_wake.c -o /tmp/runtime-test */
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdio.h>
#include <time.h>
#include <unistd.h>
#include "../shim_lock.h"
#include "../worker_wake.h"

static volatile unsigned int lock;
static unsigned long count;
static void *contend(void *unused) {
    (void)unused;
    for (int i = 0; i < 20000; i++) {
        quadra_lock(&lock);
        count++;
        if (i % 5000 == 0) usleep(1000); /* preempted owner */
        quadra_unlock(&lock);
    }
    return 0;
}
int main(void) {
    alarm(20); /* a missed wakeup or a blocking write must fail the test */
    pthread_t threads[12];
    for (int i = 0; i < 12; i++) assert(!pthread_create(&threads[i], 0, contend, 0));
    for (int i = 0; i < 12; i++) assert(!pthread_join(threads[i], 0));
    assert(count == 240000);
    int descriptors[2] = {-1, -1};
    assert(quadra_wake_pipe(descriptors));
    assert(fcntl(descriptors[0], F_GETFD) & FD_CLOEXEC);
    assert(fcntl(descriptors[1], F_GETFD) & FD_CLOEXEC);
    assert(fcntl(descriptors[1], F_GETFL) & O_NONBLOCK);
    /* A stalled worker leaves the pipe full: producers must keep moving. */
    errno = EDOM;
    for (int i = 0; i < 200000; i++) quadra_wake_worker(descriptors[1]);
    assert(errno == EDOM);
    char bytes[4096];
    assert(read(descriptors[0], bytes, sizeof bytes) > 0);
    quadra_wake_worker(descriptors[1]);
    close(descriptors[0]); close(descriptors[1]);
    puts("PASS: contended locks, sleeping owner, full wake pipe, errno and close-on-exec");
}

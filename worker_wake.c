#include "worker_wake.h"
#ifdef __APPLE__
extern int pipe(int[2]);
extern int close(int);
extern long write(int, const void *, unsigned long);
extern int fcntl(int, int, ...);
extern int *__error(void);
#define errno (*__error())
#define EINTR 4
#define F_SETFD 2
#define F_SETFL 4
#define FD_CLOEXEC 1
#define O_NONBLOCK 4
#else
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#endif
int quadra_wake_pipe(int descriptors[2]) {
    if (pipe(descriptors))
        return 0;
    if (fcntl(descriptors[0], F_SETFD, FD_CLOEXEC) < 0 ||
        fcntl(descriptors[1], F_SETFD, FD_CLOEXEC) < 0 ||
        fcntl(descriptors[1], F_SETFL, O_NONBLOCK) < 0) {
        close(descriptors[0]);
        close(descriptors[1]);
        descriptors[0] = descriptors[1] = -1;
        return 0;
    }
    return 1;
}
void quadra_wake_worker(int descriptor) {
    int saved = errno;
    if (descriptor >= 0)
        while (write(descriptor, "w", 1) < 0 && errno == EINTR) {}
    errno = saved;
}

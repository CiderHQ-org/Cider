#ifndef QUADRA_THREAD_STACK_H
#define QUADRA_THREAD_STACK_H

typedef struct { long opaque[8]; } darwin_pthread_attr_t;
extern int pthread_attr_setstacksize(darwin_pthread_attr_t *, unsigned long);
extern int pthread_attr_getstacksize(const darwin_pthread_attr_t *, unsigned long *);
extern int pthread_attr_getstackaddr(const darwin_pthread_attr_t *, void **);
#define MIN_THREAD_STACK (8UL << 20)

/* Darwin attributes contain their settings directly. Keep the caller's
 * const value intact, including when it is shared or in read-only memory. */
static int quadra_larger_stack_attributes(const darwin_pthread_attr_t *attr,
                                           darwin_pthread_attr_t *copy) {
    void *address = 0;
    unsigned long size = 0;
    if (pthread_attr_getstackaddr(attr, &address) != 0 || address ||
        pthread_attr_getstacksize(attr, &size) != 0 || size >= MIN_THREAD_STACK)
        return 0;
    *copy = *attr;
    return pthread_attr_setstacksize(copy, MIN_THREAD_STACK) == 0;
}
#endif

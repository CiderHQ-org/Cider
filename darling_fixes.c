/* Workarounds for Darling runtime bugs that are not specific to one API.
 *
 * Locks and condition variables. Darling implements the waiting part of
 * pthread mutexes and condition variables (psynch) in darlingserver: every
 * contended lock, every condition wait and every signal is a request to that
 * one server (40% of a core in game), and it loses wakeups: the RakNet
 * receive thread slept on a free mutex until the game disconnected. Its
 * condition variables also break: a timed wait that runs out is reported as
 * a wakeup, the bookkeeping goes wrong, and from then on darlingserver
 * refuses every wait on that condition variable ("psync_cvwait; invalid
 * sequence numbers" in its log, thousands a minute in game). So both wait on
 * Linux futexes here, which never involve darlingserver:
 *  - a contended pthread_mutex_lock spins briefly, then sleeps on a futex
 *    chosen by the mutex's address, which pthread_mutex_unlock wakes; the
 *    mutex itself stays Darling's (trylock and unlock);
 *  - condition variables are this file's own: a queue of waiting threads,
 *    each sleeping on its own futex, so a signal wakes exactly one of them
 *    and a broadcast exactly those waiting, never anyone else.
 * MACOBLOX_NATIVE_MUTEX=1 and MACOBLOX_NATIVE_COND=1 give Darling's back.
 *
 * Sleeps: in Darling every usleep and nanosleep is two darlingserver
 * requests (a cancellation check and a semaphore wait): a few threads napping
 * in a loop kept darlingserver above a whole core (124% with four, checked
 * with a test program; 11% with direct sleeps). They are direct Linux sleeps
 * here (macoblox_sleep_us for the shim itself). */
extern int pthread_mutex_lock(void *);
extern int pthread_mutex_trylock(void *);
extern int sched_yield(void);
extern char *getenv(const char *);
extern int macoblox_wait_begin(void);
extern void macoblox_wait_end(int);

#define DYLD_INTERPOSE(_replacement, _replacee) \
    __attribute__((used)) static struct { const void *replacement; const void *replacee; } \
    _interpose_##_replacee __attribute__((section("__DATA,__interpose"))) = \
        {(const void *)(unsigned long)&_replacement, (const void *)(unsigned long)&_replacee};

#include "math_compat.h"
DYLD_INTERPOSE(macoblox_exp10, __exp10)
DYLD_INTERPOSE(macoblox_exp10f, __exp10f)

/* Sleep without darlingserver: a direct Linux nanosleep, where usleep and
 * nanosleep cost two darlingserver requests each (see above). Same interface:
 * -1 with EINTR and the remaining time when a signal comes (Linux and Darwin
 * share the errno values nanosleep can give). Not a cancellation point. */
struct darwin_timespec { long tv_sec; long tv_nsec; };
extern int *__error(void);

#include "ulock_compat.h"
DYLD_INTERPOSE(macoblox_ulock_wait, __ulock_wait)
DYLD_INTERPOSE(macoblox_ulock_wake, __ulock_wake)

static long raw_nanosleep(const struct darwin_timespec *request, struct darwin_timespec *remaining) {
    long result;
    __asm__ volatile("syscall" : "=a"(result) : "a"(35L /* Linux nanosleep */), "D"(request), "S"(remaining)
                     : "rcx", "r11", "memory");
    return result;
}

static int linux_nanosleep(const struct darwin_timespec *request, struct darwin_timespec *remaining) {
    long result = raw_nanosleep(request, remaining);
    if (result < 0) {
        *__error() = (int)-result;
        return -1;
    }
    return 0;
}

/* For the shim's own waits: leaves errno alone (a kick during a nap in
 * pthread_mutex_lock would otherwise leave EINTR behind a successful lock). */
void macoblox_sleep_us(unsigned int microseconds) {
    struct darwin_timespec time = {microseconds / 1000000, (long)(microseconds % 1000000) * 1000};
    raw_nanosleep(&time, 0);
}

/* The game's own sleeps (FMOD's threads, frame pacing, polling loops) cost
 * the same two requests; they get the direct sleep as well. Roblox does not
 * cancel threads, so losing the cancellation point does not matter.
 * MACOBLOX_NATIVE_SLEEP=1 keeps Darling's. */
extern int nanosleep(const struct darwin_timespec *, struct darwin_timespec *);
extern int usleep(unsigned int);

static int native_sleep(void) {
    static int native = -1;
    if (native < 0) {
        const char *value = getenv("MACOBLOX_NATIVE_SLEEP");
        native = value && value[0] && value[0] != '0';
    }
    return native;
}

static int macoblox_nanosleep(const struct darwin_timespec *request, struct darwin_timespec *remaining) {
    return native_sleep() ? nanosleep(request, remaining) : linux_nanosleep(request, remaining);
}
DYLD_INTERPOSE(macoblox_nanosleep, nanosleep)

static int macoblox_usleep(unsigned int microseconds) {
    if (native_sleep())
        return usleep(microseconds);
    struct darwin_timespec request = {microseconds / 1000000, (long)(microseconds % 1000000) * 1000};
    return linux_nanosleep(&request, 0);
}
DYLD_INTERPOSE(macoblox_usleep, usleep)

#define DARWIN_EBUSY 16
#define DARWIN_EINVAL 22
#define DARWIN_ETIMEDOUT 60

static int native_mutex(void) {
    static int native = -1;
    if (native < 0) {
        const char *value = getenv("MACOBLOX_NATIVE_MUTEX");
        native = value && value[0] && value[0] != '0';
    }
    return native;
}

/* Direct Linux system calls: futexes, the monotonic clock, yielding. */
#define FUTEX_WAIT 0
#define FUTEX_WAKE 1
#define FUTEX_WAIT_BITSET 9
#define FUTEX_WAKE_BITSET 10
#define FUTEX_PRIVATE 128
#define FUTEX_CLOCK_REALTIME 256
#define LINUX_ETIMEDOUT 110

static long linux_futex(volatile unsigned int *word, long operation, long value, const void *timeout,
                        long bits) {
    long result;
    register long timeout_register __asm__("r10") = (long)timeout;
    register long other_word __asm__("r8") = 0;
    register long bits_register __asm__("r9") = bits;
    __asm__ volatile("syscall"
                     : "=a"(result)
                     : "a"(202L /* Linux futex */), "D"(word), "S"(operation), "d"(value),
                       "r"(timeout_register), "r"(other_word), "r"(bits_register)
                     : "rcx", "r11", "memory");
    return result;
}

static void linux_monotonic(struct darwin_timespec *now) {
    long result;
    __asm__ volatile("syscall" : "=a"(result) : "a"(228L /* Linux clock_gettime */), "D"(1L /* MONOTONIC */), "S"(now)
                     : "rcx", "r11", "memory");
    (void)result;
}

static void linux_sched_yield(void) {
    long result;
    __asm__ volatile("syscall" : "=a"(result) : "a"(24L /* Linux sched_yield */) : "rcx", "r11", "memory");
    (void)result;
}

/* Threads waiting for a contended mutex sleep on one of these futex words,
 * chosen by the mutex's address; the futex bitset (32 bits, also from the
 * address) keeps an unlock from waking the waiters of other mutexes that
 * share the word. */
#define MUTEX_WAIT_WORDS 2048
static struct mutex_wait {
    volatile unsigned int sequence, waiters;
} mutex_waits[MUTEX_WAIT_WORDS];

static unsigned long mutex_hash(const void *mutex) {
    unsigned long key = (unsigned long)mutex;
    key ^= key >> 21;
    return key * 0x9E3779B97F4A7C15UL;
}
static struct mutex_wait *mutex_wait_for(unsigned long hash) { return &mutex_waits[hash >> 53]; }
static long mutex_wait_bit(unsigned long hash) { return 1L << ((hash >> 16) & 31); }

/* A mutex still busy after 10 s of this goes to the real wait: it is the one
 * that returns EDEADLK for an error-checking mutex the thread already holds,
 * which trylock only reports as busy. */
#define MUTEX_FUTEX_MAX_S 10

/* Try the lock while spinning: `pauses` CPU pause loops, then `yields`
 * sched_yield calls. EBUSY if it stayed taken throughout. */
static int mutex_spin(void *mutex, int pauses, int yields) {
    int result;
    for (int attempt = 0; attempt < pauses; attempt++) {
        __builtin_ia32_pause();
        if ((result = pthread_mutex_trylock(mutex)) != DARWIN_EBUSY)
            return result;
    }
    for (int attempt = 0; attempt < yields; attempt++) {
        linux_sched_yield();
        if ((result = pthread_mutex_trylock(mutex)) != DARWIN_EBUSY)
            return result;
    }
    return DARWIN_EBUSY;
}

/* Spinning before sleeping, measured with test programs in Darling: 50
 * pauses then 64 yields was the fastest mix; a woken waiter spins again
 * (16 yields) as the unlocking thread often takes the lock straight back. */
#define MUTEX_PAUSES 50
#define MUTEX_YIELDS 64
#define MUTEX_WAKE_YIELDS 16

static int macoblox_pthread_mutex_lock(void *mutex) {
    if (native_mutex())
        return pthread_mutex_lock(mutex);
    int result = pthread_mutex_trylock(mutex);
    if (result != DARWIN_EBUSY)
        return result;
    /* Most critical sections are short: spin a little before sleeping. */
    if ((result = mutex_spin(mutex, MUTEX_PAUSES, MUTEX_YIELDS)) != DARWIN_EBUSY)
        return result;
    unsigned long hash = mutex_hash(mutex);
    struct mutex_wait *wait = mutex_wait_for(hash);
    struct darwin_timespec start, deadline;
    linux_monotonic(&start);
    /* Long waits are reported by the watchdog (thread_kick.c), with the
     * place the thread waits from; its kicks only make this loop try again. */
    int watched = macoblox_wait_begin();
    do {
        /* Counted as a waiter before the last try, so an unlock after that
         * try sees the waiter and wakes it (see macoblox_pthread_mutex_unlock). */
        __atomic_add_fetch(&wait->waiters, 1, __ATOMIC_SEQ_CST);
        unsigned int sequence = __atomic_load_n(&wait->sequence, __ATOMIC_SEQ_CST);
        result = pthread_mutex_trylock(mutex);
        if (result == DARWIN_EBUSY) {
            /* At most 5 ms: an unlock that does not come through this file
             * (Darling's own libraries, another process) wakes nobody. */
            linux_monotonic(&deadline);
            deadline.tv_nsec += 5000000;
            if (deadline.tv_nsec >= 1000000000L) {
                deadline.tv_sec++;
                deadline.tv_nsec -= 1000000000L;
            }
            linux_futex(&wait->sequence, FUTEX_WAIT_BITSET | FUTEX_PRIVATE, sequence, &deadline,
                        mutex_wait_bit(hash));
        }
        __atomic_sub_fetch(&wait->waiters, 1, __ATOMIC_SEQ_CST);
        if (result != DARWIN_EBUSY)
            break;
        /* Woken: the thread that unlocked often takes the lock straight back,
         * so spin again before sleeping. */
        if ((result = mutex_spin(mutex, MUTEX_PAUSES, MUTEX_WAKE_YIELDS)) != DARWIN_EBUSY)
            break;
    } while (deadline.tv_sec - start.tv_sec < MUTEX_FUTEX_MAX_S);
    if (result == DARWIN_EBUSY) {
        /* The real (psynch) wait. A kick makes it fail with EINTR and
         * retry: keep errno. */
        int saved_errno = *__error();
        result = pthread_mutex_lock(mutex);
        *__error() = saved_errno;
    }
    macoblox_wait_end(watched);
    return result;
}
DYLD_INTERPOSE(macoblox_pthread_mutex_lock, pthread_mutex_lock)

extern int pthread_mutex_unlock(void *);

static int macoblox_pthread_mutex_unlock(void *mutex) {
    int result = pthread_mutex_unlock(mutex);
    if (result || native_mutex())
        return result;
    unsigned long hash = mutex_hash(mutex);
    struct mutex_wait *wait = mutex_wait_for(hash);
    /* The unlock must be visible before the waiter count is read (a waiter
     * counts itself before its last trylock). Darling's unlock ends with a
     * lock-prefixed compare-and-swap, a full barrier on x86: no fence. */
    __asm__ volatile("" ::: "memory");
    /* The sequence moves on every such unlock, so a waiter that is about to
     * sleep does not; the wakeup goes to a waiter of this mutex. */
    if (__atomic_load_n(&wait->waiters, __ATOMIC_RELAXED)) {
        __atomic_add_fetch(&wait->sequence, 1, __ATOMIC_SEQ_CST);
        linux_futex(&wait->sequence, FUTEX_WAKE_BITSET | FUTEX_PRIVATE, 1, 0, mutex_wait_bit(hash));
    }
    return result;
}
DYLD_INTERPOSE(macoblox_pthread_mutex_unlock, pthread_mutex_unlock)

/* Thread stacks: Darwin gives a thread 512 KB unless its creator asks for
 * more, Linux 8 MB, and host code that runs on these stacks was built for
 * Linux's. Every Darling system call goes through an RPC to darlingserver,
 * which needs much more stack than the macOS kernel call it replaces: FMOD
 * creates its audio threads with small stacks that are enough on macOS, and
 * under Darling one overflowed inside the RPC code
 * (dserver_rpc_hooks_receive_message, stack pointer just below its last
 * page) a few seconds after a game with sound started. NVIDIA's shader
 * compiler (libnvidia-glcore) overflowed a default 512 KB thread compiling
 * Vulkan pipelines for the Metal renderer. So every thread gets at least
 * 8 MB, as on Linux, also those created without attributes (std::thread);
 * that only reserves address space, pages are used as the stack grows.
 * Threads with a caller-provided stack are left alone: the stack is only as
 * large as the caller made it. */
#include "thread_stack.h" /* Darwin attributes are 64 bytes on x86_64. */
extern int pthread_attr_init(darwin_pthread_attr_t *);
extern int pthread_attr_destroy(darwin_pthread_attr_t *);
extern int pthread_create(void **, const darwin_pthread_attr_t *, void *(*)(void *), void *);

static int macoblox_pthread_attr_setstacksize(darwin_pthread_attr_t *attr, unsigned long size) {
    void *address = 0;
    if (size < MIN_THREAD_STACK && pthread_attr_getstackaddr(attr, &address) == 0 && !address)
        size = MIN_THREAD_STACK;
    return pthread_attr_setstacksize(attr, size);
}
DYLD_INTERPOSE(macoblox_pthread_attr_setstacksize, pthread_attr_setstacksize)

static int macoblox_pthread_create(void **thread, const darwin_pthread_attr_t *attr,
                                   void *(*start)(void *), void *argument) {
    if (!attr) {
        /* Defaults (joinable, inherited scheduling), with a Linux-sized stack. */
        darwin_pthread_attr_t larger;
        if (pthread_attr_init(&larger) != 0)
            return pthread_create(thread, attr, start, argument);
        pthread_attr_setstacksize(&larger, MIN_THREAD_STACK);
        int result = pthread_create(thread, &larger, start, argument);
        pthread_attr_destroy(&larger);
        return result;
    }
    darwin_pthread_attr_t larger;
    if (macoblox_larger_stack_attributes(attr, &larger))
        return pthread_create(thread, &larger, start, argument);
    return pthread_create(thread, attr, start, argument);
}
DYLD_INTERPOSE(macoblox_pthread_create, pthread_create)

/* GCD's worker threads do not come from pthread_create: Darling's
 * workq_kernreturn starts them with a fixed 512 KB stack through
 * darling_thread_create, an entry of its ELF loader's function table
 * (elfcalls, reached through the _elfcalls pointer). Metal work on a
 * dispatch queue compiled NVIDIA shaders on such a thread and overflowed
 * it. The entry is wrapped so that threads whose stack Darling allocates
 * (no thread structure passed in) get MIN_THREAD_STACK too; Darling records
 * the size it allocated and frees exactly that when the thread ends.
 * Threads that bring their own stack (libpthread's) pass through. */
typedef void *(*darling_thread_create_function)(unsigned long stack_size, unsigned long thread_object_size,
                                                void *entry, unsigned long arg3, unsigned long arg4,
                                                unsigned long arg5, unsigned long arg6,
                                                const void *callbacks, void *thread_structure);
struct darling_elf_calls { /* the start of mldr's struct elf_calls */
    void *dlopen, *dlclose, *dlsym, *dlerror;
    darling_thread_create_function darling_thread_create;
};
extern void *dlsym(void *, const char *);
static darling_thread_create_function darling_thread_create_original;

static void *macoblox_darling_thread_create(unsigned long stack_size, unsigned long thread_object_size,
                                            void *entry, unsigned long arg3, unsigned long arg4,
                                            unsigned long arg5, unsigned long arg6,
                                            const void *callbacks, void *thread_structure) {
    if (!thread_structure && stack_size < MIN_THREAD_STACK)
        stack_size = MIN_THREAD_STACK;
    return darling_thread_create_original(stack_size, thread_object_size, entry, arg3, arg4, arg5, arg6,
                                          callbacks, thread_structure);
}

__attribute__((constructor)) static void macoblox_wrap_darling_thread_create(void) {
    struct darling_elf_calls **table = dlsym((void *)-2 /* RTLD_DEFAULT */, "_elfcalls");
    if (!table || !*table || !(*table)->darling_thread_create ||
        (*table)->darling_thread_create == macoblox_darling_thread_create)
        return;
    darling_thread_create_original = (*table)->darling_thread_create;
    (*table)->darling_thread_create = macoblox_darling_thread_create;
}

/* A GCD worker thread that finishes its work goes back to Darling's
 * workq_kernreturn, which parks it and, when there is new work, jumps to
 * libpthread's _start_wqthread again (wqueue_entry_point_asm_jump). The
 * macOS kernel restarts such a thread on a fresh stack; Darling does not
 * reset the stack pointer, so every reuse runs on top of the frames of the
 * previous one and a busy worker's stack only grows: with the Metal
 * renderer's completion handlers it overflowed 512 KB in seconds and 8 MB
 * in a minute (the fault shows up in whatever runs at the bottom, usually
 * NVIDIA's shader compiler, whose frames are large). Darling keeps the jump
 * target in a private pointer in libsystem_kernel's data; it is found as
 * the one word in its data sections that holds _start_wqthread and pointed at a
 * trampoline that restarts the stack at its top. A workqueue thread's
 * pthread structure sits right above its stack (in XNU and in Darling), so
 * the top is the thread's own pthread_t, the first argument (rdi); nothing
 * that outlives the jump is on that stack (the thread's exit context is on
 * its native Linux stack). MACOBLOX_NATIVE_WORKQUEUE=1 keeps Darling's. */
__attribute__((visibility("hidden"))) void *macoblox_wqthread_original;
extern void macoblox_start_wqthread(void);
__asm__(".text\n"
        ".p2align 4\n"
        "_macoblox_start_wqthread:\n"
        "    movq %rdi, %rsp\n"
        "    jmpq *_macoblox_wqthread_original(%rip)\n");

extern unsigned int _dyld_image_count(void);
extern const char *_dyld_get_image_name(unsigned int);
extern const void *_dyld_get_image_header(unsigned int);
extern unsigned char *getsectiondata(const void *, const char *, const char *, unsigned long *);
extern long write(int, const void *, unsigned long);

static void macoblox_log(const char *text) {
    unsigned long length = 0;
    while (text[length]) length++;
    write(2, text, length);
}

__attribute__((constructor)) static void macoblox_reset_workqueue_stacks(void) {
    const char *keep = getenv("MACOBLOX_NATIVE_WORKQUEUE");
    if (keep && keep[0] == '1')
        return;
    void *entry = dlsym((void *)-2 /* RTLD_DEFAULT */, "start_wqthread");
    if (!entry)
        return;
    for (unsigned int image = 0; image < _dyld_image_count(); image++) {
        const char *name = _dyld_get_image_name(image);
        unsigned long length = 0;
        while (name && name[length]) length++;
        static const char suffix[] = "/libsystem_kernel.dylib";
        if (length < sizeof suffix - 1) continue;
        int same = 1;
        for (unsigned long i = 0; i < sizeof suffix - 1; i++)
            same &= name[length - (sizeof suffix - 1) + i] == suffix[i];
        if (!same) continue;
        void **found = 0;
        int matches = 0;
        /* It is in __common. Not __bss: under Darling, reading it past
         * its first pages faults. */
        static const char *const sections[] = {"__data", "__common"};
        for (unsigned int s = 0; s < 2; s++) {
            unsigned long size = 0;
            void **words = (void **)getsectiondata(_dyld_get_image_header(image), "__DATA", sections[s], &size);
            for (unsigned long i = 0; words && i < size / sizeof(void *); i++)
                if (words[i] == entry) {
                    found = &words[i];
                    matches++;
                }
        }
        if (matches == 1) {
            macoblox_wqthread_original = entry;
            __atomic_store_n(found, (void *)macoblox_start_wqthread, __ATOMIC_RELEASE);
            macoblox_log("[Cider] GCD worker threads restart on a fresh stack\n");
        } else {
            macoblox_log("[Cider] Darling's workqueue entry not found, GCD worker stacks unchanged\n");
        }
        return;
    }
}

/* Condition variables (see the top of this file). A pthread_cond_t is 48
 * bytes; after its signature they hold a small lock and the queue of
 * waiting threads, whose entries live on the waiters' stacks. Each waiter
 * sleeps on its own futex word until a signal takes it off the queue and
 * sets that word: a signal wakes exactly the oldest waiter, a broadcast
 * exactly the threads waiting at that moment, and nothing else ends a wait
 * but its timeout (signals such as the watchdog's kicks do not). Some of
 * Roblox's untimed waits do not cope with waking early (see thread_kick.c).
 *
 * PTHREAD_COND_INITIALIZER (0x3CB0B1BB, then zeros) is a ready, empty
 * condition variable, and so is one of this file's. Darling's
 * pthread_cond_init writes its own layout and signature ('COND', which
 * becomes 0x434F4E45 once used; checked in Darling): condition variables
 * with any other signature than those two (process-shared ones, which
 * cannot queue entries from another process's stack) stay with Darling's
 * functions. */
#define COND_SIGNATURE 0x3CB0B1BBL /* PTHREAD_COND_INITIALIZER's */
#define DARWIN_PTHREAD_PROCESS_SHARED 1

struct cond_waiter {
    volatile unsigned int signaled; /* the futex word */
    struct cond_waiter *next, *previous;
};
struct futex_cond {
    long signature;
    volatile unsigned int lock; /* 0 free, 1 held, 2 held with waiters */
    unsigned int unused;
    struct cond_waiter *head, *tail;
    long reserved[2];
};
_Static_assert(sizeof(struct futex_cond) == 48, "pthread_cond_t is 48 bytes");

extern int pthread_condattr_getpshared(const void *, int *);
extern int pthread_cond_init(void *, const void *);
extern int pthread_cond_destroy(void *);
extern int pthread_cond_signal(void *);
extern int pthread_cond_broadcast(void *);
extern int pthread_cond_signal_thread_np(void *, void *);
extern int pthread_cond_wait(void *, void *);
extern int pthread_cond_timedwait(void *, void *, const struct darwin_timespec *);
extern int pthread_cond_timedwait_relative_np(void *, void *, const struct darwin_timespec *);
extern int pthread_cond_wait_nocancel(void *, void *) __asm__("_pthread_cond_wait$NOCANCEL");
extern int pthread_cond_timedwait_nocancel(void *, void *, const struct darwin_timespec *)
    __asm__("_pthread_cond_timedwait$NOCANCEL");

static int native_cond(void) {
    static int native = -1;
    if (native < 0) {
        const char *value = getenv("MACOBLOX_NATIVE_COND");
        native = value && value[0] && value[0] != '0';
    }
    return native;
}

/* Darling's own condition variable (native mode, or set up by Darling)? */
static int darling_cond(const void *cond) {
    long signature = ((const struct futex_cond *)cond)->signature;
    return native_cond() || (signature != COND_SIGNATURE && signature != 0);
}

static void cond_lock(struct futex_cond *cond) {
    unsigned int state = 0;
    if (__atomic_compare_exchange_n(&cond->lock, &state, 1, 0, __ATOMIC_ACQUIRE, __ATOMIC_RELAXED))
        return;
    for (int attempt = 0; attempt < 64; attempt++) {
        __builtin_ia32_pause();
        state = 0;
        if (__atomic_load_n(&cond->lock, __ATOMIC_RELAXED) == 0 &&
            __atomic_compare_exchange_n(&cond->lock, &state, 1, 0, __ATOMIC_ACQUIRE, __ATOMIC_RELAXED))
            return;
    }
    while (__atomic_exchange_n(&cond->lock, 2, __ATOMIC_ACQUIRE) != 0)
        linux_futex(&cond->lock, FUTEX_WAIT | FUTEX_PRIVATE, 2, 0, 0);
}

static void cond_unlock(struct futex_cond *cond) {
    if (__atomic_exchange_n(&cond->lock, 0, __ATOMIC_RELEASE) == 2)
        linux_futex(&cond->lock, FUTEX_WAKE | FUTEX_PRIVATE, 1, 0, 0);
}

/* With the lock held: take `waiter` off the queue and wake it. */
static void cond_release(struct futex_cond *cond, struct cond_waiter *waiter) {
    if (waiter->previous)
        waiter->previous->next = waiter->next;
    else
        cond->head = waiter->next;
    if (waiter->next)
        waiter->next->previous = waiter->previous;
    else
        cond->tail = waiter->previous;
    __atomic_store_n(&waiter->signaled, 1, __ATOMIC_RELEASE);
    /* Still under the lock: the waiter takes the lock before it returns, so
     * its entry (on its stack) outlives this call. */
    linux_futex(&waiter->signaled, FUTEX_WAKE | FUTEX_PRIVATE, 1, 0, 0);
}

enum { WAIT_FOREVER, WAIT_UNTIL /* realtime deadline */, WAIT_FOR /* relative */ };

static int futex_cond_wait(void *object, void *mutex, const struct darwin_timespec *time, int kind) {
    struct futex_cond *cond = object;
    struct darwin_timespec deadline;
    if (kind != WAIT_FOREVER) {
        if (!time || time->tv_nsec < 0 || time->tv_nsec >= 1000000000L)
            return DARWIN_EINVAL;
        if (kind == WAIT_FOR) { /* as a monotonic deadline: a wait may be resumed */
            linux_monotonic(&deadline);
            /* A huge interval (wait_for(duration::max())) would overflow into
             * the past and time out at once, every time: wait without one. */
            if (time->tv_sec > 0x7fffffffffffffffL - deadline.tv_sec - 1)
                kind = WAIT_FOREVER;
            deadline.tv_sec += kind == WAIT_FOREVER ? 0 : time->tv_sec;
            deadline.tv_nsec += time->tv_nsec;
            if (deadline.tv_nsec >= 1000000000L) {
                deadline.tv_sec++;
                deadline.tv_nsec -= 1000000000L;
            }
        } else {
            deadline = *time;
        }
    }
    struct cond_waiter waiter = {0, 0, 0};
    cond_lock(cond);
    waiter.previous = cond->tail;
    if (cond->tail)
        cond->tail->next = &waiter;
    else
        cond->head = &waiter;
    cond->tail = &waiter;
    cond_unlock(cond);

    int result = macoblox_pthread_mutex_unlock(mutex);
    if (result) { /* not the owner: leave as if never queued */
        cond_lock(cond);
        if (!waiter.signaled) {
            if (waiter.previous) waiter.previous->next = waiter.next; else cond->head = waiter.next;
            if (waiter.next) waiter.next->previous = waiter.previous; else cond->tail = waiter.previous;
        }
        cond_unlock(cond);
        return result;
    }

    int timed_out = 0;
    while (!__atomic_load_n(&waiter.signaled, __ATOMIC_ACQUIRE)) {
        long waited;
        if (kind == WAIT_FOREVER)
            waited = linux_futex(&waiter.signaled, FUTEX_WAIT | FUTEX_PRIVATE, 0, 0, 0);
        else if (deadline.tv_sec < 0) /* before 1970: Linux refuses it, it is long past */
            waited = -LINUX_ETIMEDOUT;
        else
            waited = linux_futex(&waiter.signaled,
                                 FUTEX_WAIT_BITSET | FUTEX_PRIVATE | (kind == WAIT_UNTIL ? FUTEX_CLOCK_REALTIME : 0),
                                 0, &deadline, 0xffffffffL);
        if (waited == -LINUX_ETIMEDOUT) {
            timed_out = 1;
            break;
        }
    }
    /* Taking the lock also waits for a signaler still busy with the entry. */
    cond_lock(cond);
    if (!waiter.signaled) { /* timed out, not signaled meanwhile */
        if (waiter.previous) waiter.previous->next = waiter.next; else cond->head = waiter.next;
        if (waiter.next) waiter.next->previous = waiter.previous; else cond->tail = waiter.previous;
    } else {
        timed_out = 0;
    }
    cond_unlock(cond);

    result = macoblox_pthread_mutex_lock(mutex);
    if (result)
        return result;
    return timed_out ? DARWIN_ETIMEDOUT : 0;
}

static int macoblox_pthread_cond_init(void *cond, const void *attributes) {
    int shared = 0;
    if (native_cond() ||
        (attributes && pthread_condattr_getpshared(attributes, &shared) == 0 && shared == DARWIN_PTHREAD_PROCESS_SHARED))
        return pthread_cond_init(cond, attributes);
    struct futex_cond *futex = cond;
    futex->signature = COND_SIGNATURE;
    futex->lock = 0;
    futex->unused = 0;
    futex->head = futex->tail = 0;
    futex->reserved[0] = futex->reserved[1] = 0;
    return 0;
}
DYLD_INTERPOSE(macoblox_pthread_cond_init, pthread_cond_init)

static int macoblox_pthread_cond_destroy(void *cond) {
    if (darling_cond(cond))
        return pthread_cond_destroy(cond);
    struct futex_cond *futex = cond;
    cond_lock(futex);
    int busy = futex->head != 0;
    cond_unlock(futex);
    if (busy)
        return DARWIN_EBUSY;
    futex->signature = 0;
    return 0;
}
DYLD_INTERPOSE(macoblox_pthread_cond_destroy, pthread_cond_destroy)

static int macoblox_pthread_cond_signal(void *cond) {
    if (darling_cond(cond))
        return pthread_cond_signal(cond);
    struct futex_cond *futex = cond;
    if (!__atomic_load_n(&futex->head, __ATOMIC_ACQUIRE) && !__atomic_load_n(&futex->lock, __ATOMIC_ACQUIRE))
        return 0; /* nobody waits (a waiter queues itself under the lock) */
    cond_lock(futex);
    if (futex->head)
        cond_release(futex, futex->head);
    cond_unlock(futex);
    return 0;
}
DYLD_INTERPOSE(macoblox_pthread_cond_signal, pthread_cond_signal)

static int macoblox_pthread_cond_broadcast(void *cond) {
    if (darling_cond(cond))
        return pthread_cond_broadcast(cond);
    struct futex_cond *futex = cond;
    if (!__atomic_load_n(&futex->head, __ATOMIC_ACQUIRE) && !__atomic_load_n(&futex->lock, __ATOMIC_ACQUIRE))
        return 0;
    cond_lock(futex);
    while (futex->head)
        cond_release(futex, futex->head);
    cond_unlock(futex);
    return 0;
}
DYLD_INTERPOSE(macoblox_pthread_cond_broadcast, pthread_cond_broadcast)

static int macoblox_pthread_cond_signal_thread_np(void *cond, void *thread) {
    if (darling_cond(cond))
        return pthread_cond_signal_thread_np(cond, thread);
    /* Waking one particular thread: wake them all, the others see a
     * spurious wakeup, which the API allows. Roblox does not use it. */
    return thread ? macoblox_pthread_cond_broadcast(cond) : macoblox_pthread_cond_signal(cond);
}
DYLD_INTERPOSE(macoblox_pthread_cond_signal_thread_np, pthread_cond_signal_thread_np)

static int macoblox_pthread_cond_wait(void *cond, void *mutex) {
    return darling_cond(cond) ? pthread_cond_wait(cond, mutex) : futex_cond_wait(cond, mutex, 0, WAIT_FOREVER);
}
DYLD_INTERPOSE(macoblox_pthread_cond_wait, pthread_cond_wait)

static int macoblox_pthread_cond_wait_nocancel(void *cond, void *mutex) {
    return darling_cond(cond) ? pthread_cond_wait_nocancel(cond, mutex)
                              : futex_cond_wait(cond, mutex, 0, WAIT_FOREVER);
}
DYLD_INTERPOSE(macoblox_pthread_cond_wait_nocancel, pthread_cond_wait_nocancel)

static int macoblox_pthread_cond_timedwait(void *cond, void *mutex, const struct darwin_timespec *deadline) {
    return darling_cond(cond) ? pthread_cond_timedwait(cond, mutex, deadline)
                              : futex_cond_wait(cond, mutex, deadline, WAIT_UNTIL);
}
DYLD_INTERPOSE(macoblox_pthread_cond_timedwait, pthread_cond_timedwait)

static int macoblox_pthread_cond_timedwait_nocancel(void *cond, void *mutex, const struct darwin_timespec *deadline) {
    return darling_cond(cond) ? pthread_cond_timedwait_nocancel(cond, mutex, deadline)
                              : futex_cond_wait(cond, mutex, deadline, WAIT_UNTIL);
}
DYLD_INTERPOSE(macoblox_pthread_cond_timedwait_nocancel, pthread_cond_timedwait_nocancel)

static int macoblox_pthread_cond_timedwait_relative_np(void *cond, void *mutex, const struct darwin_timespec *relative) {
    return darling_cond(cond) ? pthread_cond_timedwait_relative_np(cond, mutex, relative)
                              : futex_cond_wait(cond, mutex, relative, WAIT_FOR);
}
DYLD_INTERPOSE(macoblox_pthread_cond_timedwait_relative_np, pthread_cond_timedwait_relative_np)

/* _availability_version_check (libxpc) backs every `@available(macOS ...)`
 * check. Darling's is a stub that returns false and logs "not implemented"
 * through os_log on every call; Roblox checks availability many times per
 * frame, which cost ~4% of the main thread in logging. Same answer, no log.
 * (Answering truthfully could enable code paths for APIs Darling lacks.) */
typedef struct { unsigned int platform, version; } darwin_build_version_t;
extern _Bool _availability_version_check(unsigned long, darwin_build_version_t *);

static _Bool macoblox_availability_version_check(unsigned long count, darwin_build_version_t *versions) {
    (void)count;
    (void)versions;
    return 0;
}
DYLD_INTERPOSE(macoblox_availability_version_check, _availability_version_check)

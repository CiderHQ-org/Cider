/* Process-private locks for shim bookkeeping. A preempted owner must not
 * leave every input/render thread burning a CPU in a test-and-set loop.
 * Linux x86_64 syscalls are used directly, including in the Darwin build. */
#ifndef QUADRA_SHIM_LOCK_H
#define QUADRA_SHIM_LOCK_H
static inline void quadra_lock_futex(volatile unsigned int *word, long op, long value) {
    long result;
    register long timeout __asm__("r10") = 0;
    __asm__ volatile("syscall" : "=a"(result)
        : "a"(202L), "D"(word), "S"(op), "d"(value), "r"(timeout)
        : "rcx", "r11", "memory");
    (void)result;
}
static inline void quadra_lock(volatile unsigned int *word) {
    unsigned int expected = 0;
    if (__atomic_compare_exchange_n(word, &expected, 1, 0, __ATOMIC_ACQUIRE, __ATOMIC_RELAXED))
        return;
    for (int attempt = 0; attempt < 32; attempt++) {
        __builtin_ia32_pause();
        expected = 0;
        if (!__atomic_load_n(word, __ATOMIC_RELAXED) &&
            __atomic_compare_exchange_n(word, &expected, 1, 0, __ATOMIC_ACQUIRE, __ATOMIC_RELAXED))
            return;
    }
    while (__atomic_exchange_n(word, 2, __ATOMIC_ACQUIRE))
        quadra_lock_futex(word, 128 /* FUTEX_WAIT_PRIVATE */, 2);
}
static inline void quadra_unlock(volatile unsigned int *word) {
    if (__atomic_exchange_n(word, 0, __ATOMIC_RELEASE) == 2)
        quadra_lock_futex(word, 129 /* FUTEX_WAKE_PRIVATE */, 1);
}
#endif

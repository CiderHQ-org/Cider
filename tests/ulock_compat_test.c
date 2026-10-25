#include <assert.h>
#include <stdio.h>
#include "../ulock_compat.h"
static int error_value, error_reads, result_value, original_error, calls;
static unsigned int seen_operation, seen_timeout;
static void *seen_address;
static unsigned long long seen_value;
int *__error(void) { error_reads++; return &error_value; }
int __ulock_wait(unsigned int operation, void *address, unsigned long long value, unsigned int timeout) {
    calls++; seen_operation=operation; seen_address=address; seen_value=value; seen_timeout=timeout;
    error_value=original_error;
    return result_value;
}
int __ulock_wake(unsigned int operation, void *address, unsigned long long value) {
    calls++; seen_operation=operation; seen_address=address; seen_value=value;
    error_value=original_error;
    return result_value;
}
static void reset(int result, int error) {
    error_value=1234; error_reads=calls=0; result_value=result; original_error=error;
}
int main(void) {
    int word;
    const unsigned int flags=0x00040101;
    const unsigned long long value=0xfedcba9876543210ULL;
    reset(-1, 60);
    assert(quadra_ulock_wait(flags, &word, value, 0xffffffffU) == -1);
    assert(calls == 1 && error_reads == 0 && error_value == 60);
    assert(seen_operation == flags && seen_address == &word && seen_value == value && seen_timeout == 0xffffffffU);
    reset(-1, 60);
    assert(quadra_ulock_wait(flags|QUADRA_ULF_NO_ERRNO, &word, value, 0xffffffffU) == -60);
    assert(calls == 1 && error_reads == 1 && error_value == 1234);
    assert(seen_operation == flags && seen_address == &word && seen_value == value && seen_timeout == 0xffffffffU);
    for (int result=0; result<=1; result++) {
        reset(result, 14);
        assert(quadra_ulock_wait(QUADRA_ULF_NO_ERRNO|1, &word, value, 0) == result);
        assert(calls == 1 && error_value == 1234 && seen_timeout == 0 && seen_operation == 1);
        reset(result, 14);
        assert(quadra_ulock_wait(1, &word, value, 0) == result);
        assert(calls == 1 && error_reads == 0 && error_value == 14);
    }
    reset(-1, 22);
    assert(quadra_ulock_wake(flags, &word, value) == -1);
    assert(calls == 1 && error_reads == 0 && error_value == 22 && seen_operation == flags && seen_value == value);
    reset(-1, 22);
    assert(quadra_ulock_wake(flags|QUADRA_ULF_NO_ERRNO, &word, value) == -22);
    assert(calls == 1 && error_reads == 1 && error_value == 1234 && seen_operation == flags && seen_address == &word && seen_value == value);
    reset(0, 16);
    assert(quadra_ulock_wake(QUADRA_ULF_NO_ERRNO|1, &word, 0) == 0);
    assert(calls == 1 && error_value == 1234 && seen_operation == 1);
    reset(0, 16);
    assert(quadra_ulock_wake(1, &word, 0) == 0);
    assert(calls == 1 && error_reads == 0 && error_value == 16);
    puts("PASS: ulock args, ordinary errno, NO_ERRNO conversion/restoration and success values");
}

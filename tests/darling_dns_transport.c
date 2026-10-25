/* SPDX-License-Identifier: MIT
 * Test-only local transport behind the exact production DNS interposer.
 * Synthetic documentation addresses only: no socket or DNS server is used.
 */
#include "../dns_concurrency.h"
extern void *dlsym(void *, const char *);
extern int strcmp(const char *, const char *);
static unsigned int active_queries, maximum_queries, query_count, destroy_count;
struct fixture_state { unsigned int magic, calls; };
static int fixture_initialize(void *opaque) {
    struct fixture_state *state = opaque;
    state->magic = 0xd15ea5e; state->calls = 0;
    return 0;
}
static int fixture_query(void *opaque, const char *name, int dns_class, int type,
                         unsigned char *answer, int capacity) {
    struct fixture_state *state = opaque;
    if (state->magic != 0xd15ea5e || dns_class != 1 || (type != 1 && type != 28)) return -1;
    state->calls++;
    unsigned int count = __atomic_add_fetch(&active_queries, 1, __ATOMIC_RELAXED);
    unsigned int before = __atomic_load_n(&maximum_queries, __ATOMIC_RELAXED);
    while (before < count && !__atomic_compare_exchange_n(&maximum_queries, &before,
        count, 1, __ATOMIC_RELAXED, __ATOMIC_RELAXED)) {}
    struct { long seconds, nanoseconds; } delay = {0, 150000000};
    long ignored;
    __asm__ volatile("syscall" : "=a"(ignored) : "a"(35L), "D"(&delay), "S"(0L)
                     : "rcx", "r11", "memory");
    __atomic_sub_fetch(&active_queries, 1, __ATOMIC_RELAXED);
    __atomic_add_fetch(&query_count, 1, __ATOMIC_RELAXED);
    if (!answer || capacity < 300 || strcmp(name, "fixture.invalid")) return -1;
    for (int i = 0; i < 12; i++) answer[i] = 0;
    answer[0] = 0x12; answer[1] = 0x34; answer[2] = 0x81; answer[3] = 0x80;
    answer[5] = 1; answer[7] = 1;
    int at = 12;
    const char *label = name;
    while (*label) {
        int length = 0; while (label[length] && label[length] != '.') length++;
        answer[at++] = length;
        for (int i = 0; i < length; i++) answer[at++] = label[i];
        label += length; if (*label == '.') label++;
    }
    answer[at++] = 0; answer[at++] = 0; answer[at++] = type;
    answer[at++] = 0; answer[at++] = 1;
    answer[at++] = 0xc0; answer[at++] = 12; /* compressed question name */
    answer[at++] = 0; answer[at++] = type; answer[at++] = 0; answer[at++] = 1;
    answer[at++] = 0; answer[at++] = 0; answer[at++] = 0; answer[at++] = 60;
    answer[at++] = 0; answer[at++] = type == 1 ? 4 : 16;
    if (type == 1) {
        answer[at++] = 192; answer[at++] = 0; answer[at++] = 2; answer[at++] = 123;
    } else {
        const unsigned char address[16] = {0x20, 1, 0x0d, 0xb8, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0x23};
        for (int i = 0; i < 16; i++) answer[at++] = address[i];
    }
    return at;
}
static void fixture_destroy(void *opaque) {
    struct fixture_state *state = opaque;
    if (state->magic == 0xd15ea5e) __atomic_add_fetch(&destroy_count, 1, __ATOMIC_RELAXED);
    state->magic = 0;
}
void *quadra_dns_fixture_symbol(void *handle, const char *name) {
    if (!strcmp(name, "res_9_ninit")) return (void *)fixture_initialize;
    if (!strcmp(name, "res_9_nquery")) return (void *)fixture_query;
    if (!strcmp(name, "res_9_ndestroy")) return (void *)fixture_destroy;
    return dlsym(handle, name);
}
unsigned int quadra_dns_fixture_maximum(void) { return __atomic_load_n(&maximum_queries, __ATOMIC_RELAXED); }
unsigned int quadra_dns_fixture_queries(void) { return __atomic_load_n(&query_count, __ATOMIC_RELAXED); }
unsigned int quadra_dns_fixture_destroys(void) { return __atomic_load_n(&destroy_count, __ATOMIC_RELAXED); }

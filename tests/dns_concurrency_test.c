/* SPDX-License-Identifier: MIT
 * Exercise the exact scoped resolver helpers with deterministic APIs.
 * No DNS, sockets, Darling process or authentication is needed.
 */
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include "../dns_concurrency.h"

struct fake_state { unsigned int id, query_count; void *allocation; };
_Static_assert(sizeof(struct fake_state) <= sizeof(union quadra_resolver_state), "mock fits");
static atomic_int initializations, destructions, legacy_queries, active, maximum;
static atomic_uint next_id;
static pthread_barrier_t starting, querying;
static int failure, synchronize_queries, bypass_interposer, nested_lookup;
static int retry_codes[4], retry_calls, sleep_calls;
static const void *expected_hints;
static const char *expected_service;
static __thread int recursion;
static const struct quadra_resolver_api api;

static long milliseconds(void) {
    struct timespec now;
    assert(clock_gettime(CLOCK_MONOTONIC, &now) == 0);
    return now.tv_sec * 1000 + now.tv_nsec / 1000000;
}
static void sleep_us(unsigned int value) {
    assert(value == 50000);
    sleep_calls++;
}
static void reset(void) {
    assert(!quadra_current_resolver && !quadra_legacy_resolver_depth);
    atomic_store(&initializations, 0); atomic_store(&destructions, 0);
    atomic_store(&legacy_queries, 0); atomic_store(&next_id, 0);
    atomic_store(&active, 0); atomic_store(&maximum, 0);
    __atomic_store_n(&quadra_private_query_proven, 0, __ATOMIC_RELEASE);
    failure = synchronize_queries = bypass_interposer = nested_lookup = 0;
    retry_calls = sleep_calls = 0;
}
static int initialize(void *opaque) {
    struct fake_state *state = opaque;
    assert(state->id == 0 && state->allocation == 0);
    state->id = atomic_fetch_add(&next_id, 1) + 1;
    state->allocation = malloc(16);
    assert(state->allocation);
    atomic_fetch_add(&initializations, 1);
    return failure ? -1 : 0;
}
static int query(void *opaque, const char *name, int dns_class, int type,
                 unsigned char *answer, int capacity) {
    struct fake_state *state = opaque;
    assert(name && dns_class == 1 && (type == 1 || type == 28));
    assert(answer && capacity >= 2 && state->id && state->allocation);
    assert(state->query_count == (unsigned int)(type == 28));
    state->query_count++;
    if (synchronize_queries) {
        int status = pthread_barrier_wait(&querying);
        assert(status == 0 || status == PTHREAD_BARRIER_SERIAL_THREAD);
    }
    answer[0] = state->id; answer[1] = type;
    return 2;
}
static void destroy(void *opaque) {
    struct fake_state *state = opaque;
    assert(state->id && state->allocation);
    assert(failure || state->query_count == 2);
    free(state->allocation); state->allocation = 0;
    atomic_fetch_add(&destructions, 1);
    errno = 99; /* Cleanup must not overwrite getaddrinfo's caller errno. */
}
static const struct quadra_resolver_api api = {initialize, query, destroy};
static int legacy_query(const char *name, int dns_class, int type,
                        unsigned char *answer, int capacity) {
    assert(name && dns_class == 1 && (type == 1 || type == 28) && capacity >= 2);
    atomic_fetch_add(&legacy_queries, 1);
    answer[0] = 0; answer[1] = type;
    return 2;
}
static int original(const char *node, const char *service, const void *hints, void **result) {
    assert(node && hints == expected_hints && service == expected_service);
    int current = atomic_fetch_add(&active, 1) + 1;
    int old = atomic_load(&maximum);
    while (current > old && !atomic_compare_exchange_weak(&maximum, &old, current)) {}
    unsigned char a[2], aaaa[2];
    int (*operation)(quadra_query_function, const char *, int, int, unsigned char *, int) =
        quadra_query_in_scope;
    int first = bypass_interposer ? legacy_query(node, 1, 1, a, 2) :
        operation(legacy_query, node, 1, 1, a, 2);
    if (nested_lookup && !recursion) {
        struct quadra_resolver_scope *outer = quadra_current_resolver;
        assert(outer);
        void *nested = 0;
        long waited = 0;
        recursion++;
        assert(quadra_addrinfo_in_scope(original, &api, "nested.invalid", service,
            hints, &nested, &errno, milliseconds, &waited) == 0);
        recursion--;
        free(nested);
        assert(quadra_current_resolver == outer);
    }
    int second = bypass_interposer ? legacy_query(node, 1, 28, aaaa, 2) :
        operation(legacy_query, node, 1, 28, aaaa, 2);
    assert(first == second);
    if (first >= 0) {
        assert(a[0] == aaaa[0] && a[1] == 1 && aaaa[1] == 28);
        if (result) {
            unsigned int *owned = malloc(sizeof *owned);
            assert(owned); *owned = a[0]; *result = owned;
        }
    }
    if (!synchronize_queries) {
        struct timespec delay = {0, 3000000};
        nanosleep(&delay, 0);
    }
    atomic_fetch_sub(&active, 1);
    errno = 67;
    return first < 0 ? 8 : 0;
}
static int no_queries(const char *node, const char *service, const void *hints, void **result) {
    (void)node; (void)service; (void)hints;
    if (result) *result = 0;
    return 5; /* Invalid family/hints handled by the original API, no state needed. */
}
static int retry_original(const char *node, const char *service, const void *hints, void **result) {
    assert(node && service == expected_service && hints == expected_hints);
    assert(!result || !*result);
    errno = 71;
    return retry_codes[retry_calls++];
}
struct argument { const struct quadra_resolver_api *functions; unsigned int *result; long waited; };
static void *thread(void *opaque) {
    struct argument *argument = opaque;
    int status = pthread_barrier_wait(&starting);
    assert(status == 0 || status == PTHREAD_BARRIER_SERIAL_THREAD);
    assert(quadra_addrinfo_in_scope(original, argument->functions, "fixture.invalid",
        expected_service, expected_hints, (void **)&argument->result, &errno,
        milliseconds, &argument->waited) == 0);
    assert(errno == 67 && !quadra_current_resolver && !quadra_legacy_resolver_depth);
    return 0;
}
static void parallel(const struct quadra_resolver_api *functions) {
    pthread_t threads[4]; struct argument arguments[4] = {{0}};
    assert(pthread_barrier_init(&starting, 0, 4) == 0);
    assert(pthread_barrier_init(&querying, 0, 4) == 0);
    for (int i = 0; i < 4; i++) {
        arguments[i].functions = functions;
        assert(pthread_create(&threads[i], 0, thread, &arguments[i]) == 0);
    }
    for (int i = 0; i < 4; i++) {
        assert(pthread_join(threads[i], 0) == 0);
        assert(arguments[i].result);
        if (synchronize_queries) {
            assert(*arguments[i].result != 0);
            for (int j = 0; j < i; j++)
                assert(*arguments[i].result != *arguments[j].result);
        }
    }
    for (int i = 0; i < 4; i++) free(arguments[i].result);
    assert(pthread_barrier_destroy(&starting) == 0);
    assert(pthread_barrier_destroy(&querying) == 0);
}
int main(void) {
    alarm(5);
    int hints[] = {0, 30, 1, 6}; /* Opaque IPv6 hints must reach original unchanged. */
    expected_hints = hints; expected_service = "https";

    reset(); synchronize_queries = 1;
    parallel(&api); /* First-batch proof must release the old serialization. */
    assert(atomic_load(&maximum) == 4 && atomic_load(&initializations) == 4);
    assert(atomic_load(&destructions) == 4 && atomic_load(&legacy_queries) == 0);
    assert(__atomic_load_n(&quadra_private_query_proven, __ATOMIC_ACQUIRE));

    reset(); bypass_interposer = 1;
    parallel(&api); /* APIs alone do not prove that a runtime uses the hook. */
    assert(atomic_load(&maximum) == 1 && atomic_load(&initializations) == 0);
    assert(atomic_load(&legacy_queries) == 8 && !quadra_private_query_proven);

    for (int missing = 0; missing < 3; missing++) {
        reset(); struct quadra_resolver_api incomplete = api;
        if (missing == 0) incomplete.initialize = 0;
        if (missing == 1) incomplete.query = 0;
        if (missing == 2) incomplete.destroy = 0;
        parallel(&incomplete);
        assert(atomic_load(&maximum) == 1 && atomic_load(&initializations) == 0);
        assert(atomic_load(&legacy_queries) == 8);
    }
    reset(); failure = 1;
    void *result = 0; long waited = 0;
    assert(quadra_addrinfo_in_scope(original, &api, "fixture.invalid", expected_service,
        hints, &result, &errno, milliseconds, &waited) == 8);
    assert(!result && errno == 67 && !quadra_private_query_proven);
    assert(atomic_load(&initializations) == 1 && atomic_load(&destructions) == 1);

    reset(); nested_lookup = 1;
    assert(quadra_addrinfo_in_scope(original, &api, "fixture.invalid", expected_service,
        hints, &result, &errno, milliseconds, &waited) == 0);
    assert(result && errno == 67 && atomic_load(&initializations) == 2);
    assert(atomic_load(&destructions) == 2); free(result);

    reset();
    assert(quadra_addrinfo_in_scope(no_queries, &api, 0, 0, hints, 0,
        &errno, milliseconds, &waited) == 5);
    assert(atomic_load(&initializations) == 0 && !quadra_private_query_proven);
    unsigned char answer[2];
    assert(quadra_query_in_scope(legacy_query, "outside.invalid", 1, 1, answer, 2) == 2);
    assert(atomic_load(&legacy_queries) == 1 && atomic_load(&initializations) == 0);

    for (int code = 0; code <= 12; code++) {
        reset();
        for (int i = 0; i < 4; i++) retry_codes[i] = code;
        int attempts = 0; result = (void *)1;
        assert(quadra_retry_addrinfo(retry_original, &api, "fixture.invalid",
            expected_service, hints, &result, &errno, milliseconds, sleep_us,
            &attempts, &waited) == code);
        int expected = code == 2 || code == 4 || code == 11 ? 4 : 1;
        assert(attempts == expected && retry_calls == expected && sleep_calls == expected - 1);
        assert(!result && errno == 71);
    }
    reset(); retry_codes[0] = 2; retry_codes[1] = 0;
    int attempts = 0;
    assert(quadra_retry_addrinfo(retry_original, &api, "fixture.invalid",
        expected_service, hints, &result, &errno, milliseconds, sleep_us,
        &attempts, &waited) == 0 && attempts == 2 && sleep_calls == 1);
    assert(quadra_retry_addrinfo(0, &api, "fixture.invalid", 0, 0, 0, 0,
        0, 0, &attempts, 0) == -1 && attempts == 0);
    puts("PASS: scoped DNS concurrency, loaded-path proof, missing APIs, cleanup, nesting, hints, allocation, legacy queries and retry policy");
}

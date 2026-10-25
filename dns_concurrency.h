/* SPDX-License-Identifier: MIT
 * Darling's getaddrinfo validates hints and allocates its own addrinfo lists,
 * but its res_9_query transport uses one process-global BIND resolver state.
 * Keep that API and substitute private state only for its internal queries.
 */
#ifndef QUADRA_DNS_CONCURRENCY_H
#define QUADRA_DNS_CONCURRENCY_H
#include "shim_lock.h"

typedef int (*quadra_addrinfo_function)(const char *, const char *, const void *, void **);
typedef int (*quadra_query_function)(const char *, int, int, unsigned char *, int);
struct quadra_resolver_api {
    int (*initialize)(void *);
    int (*query)(void *, const char *, int, int, unsigned char *, int);
    void (*destroy)(void *);
};

/* Public Darwin x86_64 BIND9 res_state ABI: 552 bytes, pointer alignment.
 * This storage is opaque; only the resolver's own APIs access its fields.
 * Libinfo declares the same RES_9_STATE_SIZE in dns.subproj/res_query.c.
 */
union quadra_resolver_state {
    unsigned char bytes[552];
    unsigned long long alignment;
};
_Static_assert(sizeof(void *) == 8 && sizeof(union quadra_resolver_state) == 552,
               "Darwin x86_64 resolver ABI");
struct quadra_resolver_scope {
    union quadra_resolver_state state;
    const struct quadra_resolver_api *api;
    struct quadra_resolver_scope *previous;
    int attempted, initialized, serialized;
};
static __thread struct quadra_resolver_scope *quadra_current_resolver;
static __thread unsigned int quadra_legacy_resolver_depth;
static volatile unsigned int quadra_legacy_resolver_lock;
static unsigned int quadra_private_query_proven;

static inline int quadra_private_resolver_available(const struct quadra_resolver_api *api) {
    return api && api->initialize && api->query && api->destroy;
}

static inline int quadra_query_in_scope(quadra_query_function original,
    const char *name, int dns_class, int type, unsigned char *answer, int capacity) {
    struct quadra_resolver_scope *scope = quadra_current_resolver;
    if (!scope)
        return original ? original(name, dns_class, type, answer, capacity) : -1;
    if (!scope->attempted) {
        scope->attempted = 1;
        scope->initialized = scope->api->initialize(&scope->state) == 0;
    }
    if (!scope->initialized)
        return -1;
    /* Prove that the loaded getaddrinfo path actually reached our query
     * interposer before letting later lookups bypass the legacy lock. */
    __atomic_store_n(&quadra_private_query_proven, 1, __ATOMIC_RELEASE);
    if (scope->serialized && quadra_legacy_resolver_depth == 1) {
        /* Release the proving lookup's gate before its network wait, so
         * already-queued peers can use their private state immediately. */
        scope->serialized = 0;
        quadra_legacy_resolver_depth = 0;
        quadra_unlock(&quadra_legacy_resolver_lock);
    }
    return scope->api->query(&scope->state, name, dns_class, type, answer, capacity);
}

static inline int quadra_addrinfo_in_scope(quadra_addrinfo_function original,
    const struct quadra_resolver_api *api, const char *node, const char *service,
    const void *hints, void **result, int *error_number,
    long (*milliseconds)(void), long *waited_ms) {
    if (!original)
        return -1;
    struct quadra_resolver_scope scope = {0};
    scope.previous = quadra_current_resolver;
    int private_state = quadra_private_resolver_available(api);
    int serialized = !private_state ||
        !__atomic_load_n(&quadra_private_query_proven, __ATOMIC_ACQUIRE);
    if (serialized) {
        /* Older/custom runtimes without the reentrant APIs retain their
         * protected legacy path. A nested callback on the owner must not
         * attempt to acquire its own lock a second time. */
        long started = milliseconds ? milliseconds() : 0;
        int owns_lock = !quadra_legacy_resolver_depth;
        if (owns_lock)
            quadra_lock(&quadra_legacy_resolver_lock);
        if (milliseconds && waited_ms)
            *waited_ms += milliseconds() - started;
        /* Threads queued before the first proof must not hold the lock
         * throughout their query after that proof becomes available. */
        if (private_state &&
            __atomic_load_n(&quadra_private_query_proven, __ATOMIC_ACQUIRE)) {
            if (owns_lock)
                quadra_unlock(&quadra_legacy_resolver_lock);
            serialized = 0;
        } else {
            quadra_legacy_resolver_depth++;
        }
    }
    scope.api = private_state ? api : 0;
    scope.serialized = serialized;
    quadra_current_resolver = private_state ? &scope : 0;
    int status = original(node, service, hints, result);
    int saved_error = error_number ? *error_number : 0;
    quadra_current_resolver = scope.previous;
    if (private_state) {
        /* ninit may allocate an extension before reporting failure. Darling
         * initializes its socket sentinels before any such failure; ndestroy
         * releases both that extension and any query sockets. */
        if (scope.attempted)
            api->destroy(&scope.state);
    }
    if (scope.serialized && !--quadra_legacy_resolver_depth) {
        quadra_unlock(&quadra_legacy_resolver_lock);
    }
    if (error_number)
        *error_number = saved_error;
    return status;
}

static inline int quadra_retry_addrinfo(quadra_addrinfo_function original,
    const struct quadra_resolver_api *api, const char *node, const char *service,
    const void *hints, void **result, int *error_number,
    long (*milliseconds)(void), void (*sleep_us)(unsigned int),
    int *attempts, long *waited_ms) {
    int status = -1, calls = 0;
    while (original && calls < 4) {
        if (calls && sleep_us)
            sleep_us(50000);
        calls++;
        if (result)
            *result = 0;
        status = quadra_addrinfo_in_scope(original, api, node, service, hints,
            result, error_number, milliseconds, waited_ms);
        if (status != 2 /* EAI_AGAIN */ && status != 4 /* EAI_FAIL */ &&
            status != 11 /* EAI_SYSTEM */)
            break;
    }
    if (attempts)
        *attempts = calls;
    return status;
}
#endif

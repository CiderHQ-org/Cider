/* SPDX-License-Identifier: MIT
 * Real Libinfo getaddrinfo/freeaddrinfo with the local diagnostic transport.
 * There is no public DNS or authentication request. Run only in a test prefix.
 */
typedef unsigned long long u64;
struct addrinfo {
    int flags, family, socktype, protocol;
    unsigned int length;
    char *canonical;
    unsigned char *address;
    struct addrinfo *next;
};
extern int getaddrinfo(const char *, const char *, const struct addrinfo *, struct addrinfo **);
extern void freeaddrinfo(struct addrinfo *);
extern int pthread_create(void **, const void *, void *(*)(void *), void *);
extern int pthread_join(void *, void **);
extern void *dlsym(void *, const char *);
extern int res_9_ninit(void *);
extern void res_9_ndestroy(void *);
extern int printf(const char *, ...);
extern void exit(int);
extern unsigned int alarm(unsigned int);
extern int strcmp(const char *, const char *);
static unsigned int waiting, start;
static int failures;
static void require(int yes, const char *message) {
    if (!yes) { printf("FAIL %s\n", message); exit(1); }
}
static void pause_thread(void) {
    struct { long seconds, nanoseconds; } delay = {0, 1000000};
    long ignored;
    __asm__ volatile("syscall" : "=a"(ignored) : "a"(35L), "D"(&delay), "S"(0L)
                     : "rcx", "r11", "memory");
}
static void *resolve(void *unused) {
    (void)unused;
    __atomic_add_fetch(&waiting, 1, __ATOMIC_RELEASE);
    while (!__atomic_load_n(&start, __ATOMIC_ACQUIRE)) pause_thread();
    struct addrinfo hints = {2 /* AI_CANONNAME */, 0, 1, 6, 0, 0, 0, 0};
    struct addrinfo *result = 0;
    int status = getaddrinfo("fixture.invalid", "https", &hints, &result);
    int v4 = 0, v6 = 0;
    for (struct addrinfo *entry = result; entry; entry = entry->next) {
        require(entry->socktype == 1 && entry->protocol == 6, "original socket hints");
        require(entry->address && entry->address[2] == 1 && entry->address[3] == 0xbb,
                "named https service port");
        if (entry->family == 2) {
            require(entry->length == 16 && entry->address[4] == 192 && entry->address[7] == 123,
                    "real Darwin IPv4 result allocation");
            v4++;
        } else if (entry->family == 30) {
            require(entry->length == 28 && entry->address[8] == 0x20 && entry->address[11] == 0xb8,
                    "real Darwin IPv6 result allocation");
            v6++;
        }
        require(!entry->canonical || !strcmp(entry->canonical, "fixture.invalid"), "canonical name");
    }
    if (status || !v4 || !v6) {
        __atomic_add_fetch(&failures, 1, __ATOMIC_RELAXED);
        printf("FAIL lookup return=%d IPv4=%d IPv6=%d\n", status, v4, v6);
    }
    freeaddrinfo(result);
    return 0;
}
int main(void) {
    alarm(15);
    /* The production helper's opaque state must match the actual runtime.
     * Initialization and destruction read config only, and send no query. */
    struct { union { u64 aligned; unsigned char bytes[552]; } state; u64 guard; } guarded = {0};
    guarded.guard = 0x123456789abcdef0ULL;
    require(!res_9_ninit(&guarded.state), "actual resolver private-state initialization");
    require(guarded.guard == 0x123456789abcdef0ULL, "resolver state size after init");
    res_9_ndestroy(&guarded.state);
    require(guarded.guard == 0x123456789abcdef0ULL, "resolver state size after destroy");
    unsigned int (*maximum)(void) = dlsym((void *)-2, "quadra_dns_fixture_maximum");
    unsigned int (*queries)(void) = dlsym((void *)-2, "quadra_dns_fixture_queries");
    unsigned int (*destroys)(void) = dlsym((void *)-2, "quadra_dns_fixture_destroys");
    require(maximum && queries && destroys, "diagnostic transport loaded");
    void *threads[4];
    for (int i = 0; i < 4; i++) require(!pthread_create(&threads[i], 0, resolve, 0), "create resolver thread");
    while (__atomic_load_n(&waiting, __ATOMIC_ACQUIRE) != 4) pause_thread();
    __atomic_store_n(&start, 1, __ATOMIC_RELEASE);
    for (int i = 0; i < 4; i++) require(!pthread_join(threads[i], 0), "join resolver thread");
    require(!failures, "all original getaddrinfo results");
    require(maximum() >= 2 && queries() == 8 && destroys() == 4,
            "loaded query interposition and parallel private transport");
    printf("PASS real Darling DNS scope: parallel=%u queries=%u cleanup=%u IPv4/IPv6/named-service/freeaddrinfo\n",
           maximum(), queries(), destroys());
    return 0;
}

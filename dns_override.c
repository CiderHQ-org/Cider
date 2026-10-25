/* DNS for Roblox only. QUADRA_DNS=127.0.0.1:PORT points at the launcher's
 * local forwarder, which sends the queries over DNS-over-TLS to the server
 * chosen in the launcher (e.g. Quad9). Some Roblox image hosts do not resolve
 * through ISP or system resolvers in some regions, and plain UDP DNS to
 * public resolvers is unreliable there, while the rest of the system keeps
 * its own DNS.
 *
 * quadra_dns_resolve() answers A lookups by asking the forwarder over UDP
 * and builds the addrinfo list itself; anything it cannot handle (IP
 * literals, IPv6-only requests, named services, no answer) falls back to
 * Darling's resolver. The list is allocated the way Darling's own is (the
 * sockaddr and canonical name in blocks of their own), so Darling's
 * freeaddrinfo() frees it. The forwarder answers SERVFAIL when its server
 * cannot be reached; when it does not answer at all, it is skipped for 30 s
 * instead of costing every lookup the 5 s wait. */
typedef unsigned int socklen_t;
typedef long ssize_t;
typedef unsigned long size_t;
struct darwin_sockaddr_in {
    unsigned char len, family;
    unsigned short port;
    unsigned int address;
    char zero[8];
};
/* Darwin struct addrinfo (x86_64). */
struct darwin_addrinfo {
    int flags, family, socktype, protocol;
    socklen_t addrlen;
    char *canonname;
    void *addr;
    struct darwin_addrinfo *next;
};
struct darwin_pollfd { int fd; short events, revents; };
extern char *getenv(const char *);
extern int socket(int, int, int);
extern int connect(int, const void *, socklen_t);
extern ssize_t send(int, const void *, size_t, int);
extern ssize_t recv(int, void *, size_t, int);
extern int close(int);
extern int fcntl(int, int, ...);
extern int poll(struct darwin_pollfd *, unsigned int, int);
extern void *calloc(size_t, size_t);
extern void free(void *);
extern char *strdup(const char *);
extern unsigned long long mach_absolute_time(void);
#define AF_INET_DARWIN 2
#define EAI_NONAME_DARWIN 8
#define MAX_ADDRESSES 16
#define AI_CANONNAME_DARWIN 0x2
#define F_SETFD_DARWIN 2
#define FD_CLOEXEC_DARWIN 1
#define FORWARDER_WAIT_MS 2500
#define FORWARDER_SKIP_NS 30000000000ULL
/* After a forwarder that did not answer at all: skip it until then. */
static volatile unsigned long long forwarder_skipped_until;
static int forwarder_port(unsigned int *address, unsigned short *port) {
    const char *value = getenv("QUADRA_DNS");
    if (!value || !value[0])
        return 0;
    unsigned int parts[4] = {0, 0, 0, 0};
    int part = 0;
    unsigned int number = 0;
    const char *c = value;
    for (; *c && *c != ':'; c++) {
        if (*c == '.') {
            if (part > 3) return 0;
            parts[part++] = number;
            number = 0;
        } else if (*c >= '0' && *c <= '9') {
            number = number * 10 + (unsigned int)(*c - '0');
            if (number > 255)
                return 0;
        } else {
            return 0;
        }
    }
    if (part != 3 || *c != ':')
        return 0;
    parts[3] = number;
    number = 0;
    for (c++; *c >= '0' && *c <= '9'; c++)
        number = number * 10 + (unsigned int)(*c - '0');
    if (!number || number > 65535)
        return 0;
    /* LE-friendly packing: produces correct network-order bytes in memory. */
    *address = parts[0] | parts[1] << 8 | parts[2] << 16 | parts[3] << 24;
    *port = (unsigned short)((number >> 8) | ((number & 255) << 8));
    return 1;
}
static int is_ip_literal(const char *node) {
    int digits_and_dots = 1;
    for (const char *c = node; *c; c++) {
        if (*c == ':')
            return 1; /* IPv6 literal */
        if (!((*c >= '0' && *c <= '9') || *c == '.'))
            digits_and_dots = 0;
    }
    return digits_and_dots;
}
static int parse_port(const char *service, unsigned short *port) {
    unsigned int number = 0;
    if (!service) {
        *port = 0;
        return 1;
    }
    if (!*service)
        return 0;
    for (const char *c = service; *c; c++) {
        if (*c < '0' || *c > '9')
            return 0; /* named service: let the system resolve it */
        number = number * 10 + (unsigned int)(*c - '0');
        if (number > 65535)
            return 0;
    }
    *port = (unsigned short)((number >> 8) | ((number & 255) << 8));
    return 1;
}
/* Skip a possibly compressed DNS name; returns the offset after it or -1. */
static int skip_name(const unsigned char *packet, int length, int offset) {
    int jumps = 0;
    while (offset < length) {
        unsigned char label = packet[offset];
        if (label == 0)
            return offset + 1;
        if ((label & 0xC0) == 0xC0) {
            /* compression pointer — do not follow, just skip the two bytes */
            return offset + 2 <= length ? offset + 2 : -1;
        }
        if ((label & 0xC0) != 0)
            return -1; /* reserved bits */
        offset += label + 1;
        if (++jumps > 128)
            return -1;
    }
    return -1;
}
/* Returns the number of A records found, 0 for none, -1 on failure, and -2
 * for NXDOMAIN. */
static int query_forwarder(const char *node, unsigned int *addresses) {
    unsigned int server;
    unsigned short server_port;
    if (!forwarder_port(&server, &server_port))
        return -1;
    unsigned long long now = mach_absolute_time();
    if (forwarder_skipped_until && now < forwarder_skipped_until)
        return -1;
    unsigned char query[300];
    unsigned short id = (unsigned short)(mach_absolute_time() >> 3);
    int length = 0;
    query[length++] = (unsigned char)(id >> 8);
    query[length++] = (unsigned char)id;
    query[length++] = 0x01; /* recursion desired */
    query[length++] = 0x00;
    query[length++] = 0; query[length++] = 1; /* one question */
    for (int i = 0; i < 6; i++) query[length++] = 0;
    const char *label = node;
    while (*label) {
        const char *end = label;
        while (*end && *end != '.') end++;
        int size = (int)(end - label);
        if (size == 0 || size > 63 || length + size + 6 > (int)sizeof query)
            return -1;
        query[length++] = (unsigned char)size;
        for (int i = 0; i < size; i++) query[length++] = (unsigned char)label[i];
        label = *end ? end + 1 : end;
    }
    query[length++] = 0;
    query[length++] = 0; query[length++] = 1; /* type A */
    query[length++] = 0; query[length++] = 1; /* class IN */
    int fd = socket(AF_INET_DARWIN, 2 /* SOCK_DGRAM */, 0);
    if (fd < 0)
        return -1;
    fcntl(fd, F_SETFD_DARWIN, FD_CLOEXEC_DARWIN); /* not into programs the game starts */
    struct darwin_sockaddr_in address = {sizeof address, AF_INET_DARWIN, server_port, server, {0}};
    int found = -1, silent = 0;
    if (connect(fd, &address, sizeof address) == 0) {
        for (int attempt = 0; attempt < 2 && found == -1; attempt++) {
            if (send(fd, query, (size_t)length, 0) != length)
                break;
            struct darwin_pollfd wait = {fd, 1, 0};
            if (poll(&wait, 1, FORWARDER_WAIT_MS) <= 0) {
                silent++;
                continue;
            }
            unsigned char reply[1500];
            ssize_t got = recv(fd, reply, sizeof reply, 0);
            if (got < 12 || reply[0] != query[0] || reply[1] != query[1])
                continue;
            /* Require a response (QR=1) and opcode 0. */
            if ((reply[2] & 0x80) == 0 || (reply[2] & 0x78) != 0)
                continue;
            int rcode = reply[3] & 15;
            if (rcode == 3) {
                found = -2;
                break;
            }
            if (rcode != 0)
                break;
            int answers = reply[6] << 8 | reply[7];
            int offset = skip_name(reply, (int)got, 12);
            if (offset < 0)
                break;
            offset += 4; /* type + class of the question */
            found = 0;
            for (int i = 0; i < answers && offset >= 0 && offset + 10 <= got; i++) {
                offset = skip_name(reply, (int)got, offset);
                if (offset < 0 || offset + 10 > got)
                    break;
                int type = reply[offset] << 8 | reply[offset + 1];
                int data_length = reply[offset + 8] << 8 | reply[offset + 9];
                offset += 10;
                if (offset + data_length > got)
                    break;
                if (type == 1 && data_length == 4 && found < MAX_ADDRESSES) {
                    /* Same LE-friendly packing used by forwarder_port. */
                    addresses[found++] = (unsigned int)reply[offset] |
                                         (unsigned int)reply[offset + 1] << 8 |
                                         (unsigned int)reply[offset + 2] << 16 |
                                         (unsigned int)reply[offset + 3] << 24;
                }
                offset += data_length;
            }
        }
    }
    close(fd);
    if (silent == 2) /* no reply to either attempt: the forwarder is gone or stuck */
        forwarder_skipped_until = mach_absolute_time() + FORWARDER_SKIP_NS;
    return found;
}
/* Free a partial list we built (Darling freeaddrinfo expects the same shape). */
static void free_partial(struct darwin_addrinfo *head) {
    while (head) {
        struct darwin_addrinfo *next = head->next;
        free(head->addr);
        free(head->canonname);
        free(head);
        head = next;
    }
}
/* 0 on success with *result set, an EAI error, or -1 to use the system resolver. */
int quadra_dns_resolve(const char *node, const char *service, const void *hints_pointer,
                         void **result) {
    const struct darwin_addrinfo *hints = hints_pointer;
    unsigned short port;
    if (!node || !*node || !result || is_ip_literal(node) || !parse_port(service, &port))
        return -1;
    if (hints && hints->family != 0 && hints->family != AF_INET_DARWIN)
        return -1;
    if (hints && (hints->flags & 0x4 /* AI_NUMERICHOST */))
        return -1;
    const char *local = "localhost";
    int is_local = 1;
    for (int i = 0; local[i] || node[i]; i++)
        if (local[i] != node[i]) { is_local = 0; break; }
    if (is_local)
        return -1;
    unsigned int addresses[MAX_ADDRESSES];
    int count = query_forwarder(node, addresses);
    if (count == -2)
        return EAI_NONAME_DARWIN;
    if (count <= 0)
        return -1;
    int socktypes[2] = {1 /* STREAM */, 2 /* DGRAM */};
    int protocols[2] = {6, 17};
    int kinds = 2;
    if (hints && hints->socktype) {
        socktypes[0] = hints->socktype;
        protocols[0] = hints->protocol ? hints->protocol : (hints->socktype == 2 ? 17 : 6);
        kinds = 1;
    }
    /* Separate blocks, as Darling's freeaddrinfo frees ai_addr and
     * ai_canonname on their own before the entry. */
    struct darwin_addrinfo *head = 0, *tail = 0;
    for (int i = 0; i < count; i++) {
        for (int kind = 0; kind < kinds; kind++) {
            struct darwin_addrinfo *entry = calloc(1, sizeof *entry);
            struct darwin_sockaddr_in *address = entry ? calloc(1, sizeof *address) : 0;
            if (!address) {
                free(entry);
                free_partial(head);
                return -1;
            }
            address->len = sizeof *address;
            address->family = AF_INET_DARWIN;
            address->port = port;
            address->address = addresses[i];
            entry->family = AF_INET_DARWIN;
            entry->socktype = socktypes[kind];
            entry->protocol = protocols[kind];
            entry->addrlen = sizeof *address;
            entry->addr = address;
            if (tail) tail->next = entry; else head = entry;
            tail = entry;
        }
    }
    if (!head)
        return -1;
    if (hints && (hints->flags & AI_CANONNAME_DARWIN)) {
        head->canonname = strdup(node); /* no CNAME is followed here */
        /* strdup failure is acceptable; leave canonname NULL */
    }
    *result = head;
    return 0;
}

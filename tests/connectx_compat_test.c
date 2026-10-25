/* Deterministic connectx regression checks, including PR #16's premature
 * success on EINPROGRESS. No Darling or network access is needed:
 *   clang -Wall -Wextra tests/connectx_compat_test.c -o /tmp/connectx-test
 *   /tmp/connectx-test
 */
#include <assert.h>
#include <stdio.h>

#define bind test_bind
#define connect test_connect
#define sendmsg test_sendmsg
#define connectx test_connectx
#define __error test_error
#include "../connectx_compat.c"

static int error_value, connect_error, bind_error, send_error;
static int connect_calls, send_calls;
static ssize_t bytes_to_send;

int *test_error(void) { return &error_value; }
int test_bind(int fd, const void *address, socklen_t length) {
    (void)fd; (void)address; (void)length;
    error_value = bind_error;
    return bind_error ? -1 : 0;
}
int test_connect(int fd, const void *address, socklen_t length) {
    assert(fd == 42 && address && length == 16);
    connect_calls++;
    error_value = connect_error;
    return connect_error ? -1 : 0;
}
ssize_t test_sendmsg(int fd, const struct msghdr *message, int flags) {
    assert(fd == 42 && message->iov && message->iovlen == 1 && flags == 0);
    send_calls++;
    error_value = send_error;
    return send_error ? -1 : bytes_to_send;
}
/* Link target for the unused interposition record in the included source. */
int test_connectx(int fd, const sa_endpoints_t *ep, unsigned int associd,
                  unsigned int flags, const struct iovec *iov, unsigned int count,
                  size_t *sent, unsigned int *connid) {
    return quadra_connectx(fd, ep, associd, flags, iov, count, sent, connid);
}

int main(void) {
    char destination[16] = {0};
    sa_endpoints_t ep = {0, 0, 0, destination, sizeof destination};
    struct iovec initial = {(void *)"hello", 5};
    size_t sent = 99;
    unsigned int connid = 99;

    /* Pending connections must stay pending, with or without initial data.
     * The caller can then wait for completion and retry the unsent bytes. */
    connect_error = EINPROGRESS;
    assert(quadra_connectx(42, &ep, 0, 0, &initial, 1, &sent, &connid) == -1);
    assert(error_value == EINPROGRESS && sent == 0 && connid == 99 && send_calls == 0);
    assert(quadra_connectx(42, &ep, 0, 0, 0, 0, 0, 0) == -1);
    assert(error_value == EINPROGRESS && send_calls == 0);

    connect_error = 61; /* ECONNREFUSED */
    assert(quadra_connectx(42, &ep, 0, 0, &initial, 1, &sent, &connid) == -1);
    assert(error_value == 61 && sent == 0 && connid == 99 && send_calls == 0);

    connect_error = 0;
    assert(quadra_connectx(42, &ep, 0, 0, 0, 0, &sent, &connid) == 0);
    assert(sent == 0 && connid == 1 && send_calls == 0);
    bytes_to_send = 5;
    assert(quadra_connectx(42, &ep, 0, 0, &initial, 1, &sent, &connid) == 0);
    assert(sent == 5 && send_calls == 1);
    bytes_to_send = 2; /* Report partial sends accurately. */
    assert(quadra_connectx(42, &ep, 0, 0, &initial, 1, &sent, &connid) == 0);
    assert(sent == 2 && send_calls == 2);
    send_error = 35; /* EAGAIN */
    assert(quadra_connectx(42, &ep, 0, 0, &initial, 1, &sent, &connid) == -1);
    assert(error_value == 35 && sent == 0 && send_calls == 3);

    int connected = connect_calls;
    ep.srcaddr = destination;
    ep.srcaddrlen = sizeof destination;
    bind_error = 48; /* EADDRINUSE */
    assert(quadra_connectx(42, &ep, 0, 0, 0, 0, &sent, 0) == -1);
    assert(error_value == 48 && connect_calls == connected);
    assert(quadra_connectx(42, 0, 0, 0, 0, 0, &sent, 0) == -1);
    assert(error_value == EINVAL && sent == 0 && connect_calls == connected);
    ep.dstaddr = 0;
    assert(quadra_connectx(42, &ep, 0, 0, 0, 0, &sent, 0) == -1);
    assert(error_value == EINVAL && connect_calls == connected);

    puts("PASS: pending connection, connection failure, initial data, partial send, bind failure, invalid endpoint");
    return 0;
}

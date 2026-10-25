#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include "../thread_stack.h"

static int fail_setter;
int pthread_attr_getstackaddr(const darwin_pthread_attr_t *attr, void **address) {
    *address = (void *)attr->opaque[0]; return 0;
}
int pthread_attr_getstacksize(const darwin_pthread_attr_t *attr, unsigned long *size) {
    *size = (unsigned long)attr->opaque[1]; return 0;
}
int pthread_attr_setstacksize(darwin_pthread_attr_t *attr, unsigned long size) {
    if (fail_setter) return 22;
    attr->opaque[1] = (long)size; return 0;
}
int main(void) {
    darwin_pthread_attr_t *original = mmap(0, 4096, PROT_READ | PROT_WRITE,
                                          MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    assert(original != MAP_FAILED);
    original->opaque[1] = 512 * 1024;
    original->opaque[2] = 1234; /* unrelated caller setting */
    assert(!mprotect(original, 4096, PROT_READ));
    darwin_pthread_attr_t copy;
    assert(quadra_larger_stack_attributes(original, &copy));
    assert(copy.opaque[1] == MIN_THREAD_STACK && copy.opaque[2] == 1234);
    assert(original->opaque[1] == 512 * 1024);
    fail_setter = 1;
    assert(!quadra_larger_stack_attributes(original, &copy));
    fail_setter = 0;
    copy = *original;
    copy.opaque[0] = 1; /* caller owns this stack */
    darwin_pthread_attr_t untouched = copy;
    assert(!quadra_larger_stack_attributes(&copy, &untouched));
    assert(!memcmp(&copy, &untouched, sizeof copy));
    copy.opaque[0] = 0; copy.opaque[1] = 16 * 1024 * 1024;
    assert(!quadra_larger_stack_attributes(&copy, &untouched));
    munmap(original, 4096);
    puts("PASS: read-only thread attributes, settings retained, caller stack and setter failure");
}

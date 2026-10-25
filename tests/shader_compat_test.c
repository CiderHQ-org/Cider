/* clang -O2 tests/shader_compat_test.c shader_compat.c -o /tmp/shader-test */
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
extern char *quadra_fix_shader_indices(char *, unsigned long *);
int main(void) {
    const char *shader = "uint index = ((uint(POSITION.w) >> 8u) & 255u);";
    for (int i = 0; i < 2; i++) {
        char *source = strdup(shader);
        unsigned long length = strlen(source);
        if (i) length--; /* A bounded, incomplete source must be safe too. */
        unsigned long original_length = length;
        char *result = quadra_fix_shader_indices(source, &length);
        assert(result == source && !strcmp(result, shader) && length == original_length);
        free(result);
    }
    char *source = strdup("CB12[((uint(POSITION.w) >> 8u) & 255u) * 1 + 0] + CB12[((uint(POSITION.w) >> 8u) & 255u) * 1 + 0]");
    unsigned long length = strlen(source);
    source = quadra_fix_shader_indices(source, &length);
    assert(!strcmp(source, "CB12[((uint(POSITION.w) >> 8u) & 255u)] + CB12[((uint(POSITION.w) >> 8u) & 255u)]"));
    assert(length == strlen(source));
    char *again = quadra_fix_shader_indices(source, &length);
    assert(again == source); /* Applying the fix twice must not change types. */
    free(source);
    source = strdup("CB3[(_500 & 63u) * 1 + 0] + CB6[_978 * 1 + 0]; uint i = (_500 & 63u) * 1 + 0;");
    length = strlen(source);
    source = quadra_fix_shader_indices(source, &length);
    assert(!strcmp(source, "CB3[(_500 & 63u)] + CB6[_978]; uint i = (_500 & 63u) * 1 + 0;"));
    assert(length == strlen(source));
    free(source);
    puts("PASS: unsigned index arithmetic fixed without changing other expressions");
}

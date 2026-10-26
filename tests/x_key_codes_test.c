#include <assert.h>
#include <stdio.h>
#include "../x_key_codes.h"

int main(void) {
    /* Keys Darling's table lacks map to what a Mac sends for the same key. */
    assert(quadra_x_extra_carbon_key(118) == 114);  /* Insert -> Help */
    assert(quadra_x_extra_carbon_key(108) == 54);   /* Right Alt -> Right Command */
    assert(quadra_x_extra_carbon_key(94) == 10);    /* ISO key */
    assert(quadra_x_extra_carbon_key(135) == 110);  /* Menu */
    assert(quadra_x_extra_carbon_key(125) == 81);   /* keypad = */
    static const int f13_to_f20[] = {105, 107, 113, 106, 64, 79, 80, 90};
    for (unsigned index = 0; index < 8; index++)
        assert(quadra_x_extra_carbon_key(191 + index) == f13_to_f20[index]);
    assert(quadra_x_extra_carbon_key(199) == -1);   /* F21: no Apple key */
    /* Everything Darling already maps, including A (X keycode 38), stays. */
    for (unsigned key = 0; key < 256; key++) {
        int code = quadra_x_extra_carbon_key(key);
        assert(code >= -1 && code < 128);
    }
    assert(quadra_x_extra_carbon_key(38) == -1 && quadra_x_extra_carbon_key(64) == -1 &&
           quadra_x_extra_carbon_key(133) == -1 && quadra_x_extra_carbon_key(107) == -1);
    puts("PASS: X11 keys Darling cannot map get Apple key codes, mapped keys are untouched");
    return 0;
}

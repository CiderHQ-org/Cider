#include <assert.h>
#include <stdio.h>
#include "../x_modifier_state.h"

int main(void) {
    unsigned char masks[256] = {0}, down[256] = {0};
    masks[50] = masks[62] = 1; /* left and right Shift */
    masks[37] = 4; masks[64] = 8; masks[133] = 64; masks[108] = 128;
    masks[66] = 2; /* Caps Lock */
    unsigned int state = 0;
    state = quadra_x_modifier_transition(state, 50, 1, masks, down);
    assert(state == 1);
    state = quadra_x_modifier_transition(state, 62, 1, masks, down);
    assert(state == 1);
    state = quadra_x_modifier_transition(state, 50, 0, masks, down);
    assert(state == 1); /* right Shift remains held */
    state = quadra_x_modifier_transition(state, 62, 0, masks, down);
    assert(state == 0);
    const unsigned int keys[] = {37,64,133,108};
    const unsigned int bits[] = {4,8,64,128};
    for (int i = 0; i < 4; i++) {
        state = quadra_x_modifier_transition(0, keys[i], 1, masks, down);
        assert(state == bits[i]);
        assert(quadra_x_modifier_transition(state, keys[i], 0, masks, down) == 0);
    }
    state = quadra_x_modifier_transition(0, 66, 1, masks, down);
    assert(state == 2);
    assert(quadra_x_modifier_transition(state, 66, 1, masks, down) == 2); /* repeat */
    assert(quadra_x_modifier_transition(state, 66, 0, masks, down) == 2); /* locked */
    assert(quadra_x_modifier_transition(state, 66, 1, masks, down) == 0);
    assert(quadra_x_modifier_transition(5, 300, 1, masks, down) == 5);
    puts("PASS: ordered modifier press/release, paired Shift, Lock toggle and repeat");
}

#include <assert.h>
#include <stdio.h>
#include "../mouse_motion.h"
int main(void) {
    unsigned button;
    const unsigned left=1u<<1, right=1u<<3, middle=1u<<2;
    assert(quadra_mouse_motion_event(right,1,&button)==7 && button==3);
    assert(quadra_mouse_motion_event(right|left,1,&button)==7 && button==3);
    assert(quadra_mouse_motion_event(right|left|middle,1,&button)==7 && button==3);
    assert(quadra_mouse_motion_event(right,1,&button)==7 && button==3); // left released first
    assert(quadra_mouse_motion_event(left,1,&button)==6 && button==1); // right released first
    assert(quadra_mouse_motion_event(0,1,&button)==5 && button==0);
    assert(quadra_mouse_motion_event(right|left,0,&button)==6 && button==1);
    assert(quadra_mouse_motion_event(middle,0,&button)==27 && button==2);
    assert(quadra_mouse_motion_event(1u<<8,0,&button)==27 && button==8);
    puts("PASS: captured RMB+LMB preserves camera motion, both release orders, ordinary drags and extra buttons");
}

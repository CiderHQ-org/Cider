#include <assert.h>
#include <math.h>
#include <stdio.h>
#include "../wayland_coordinates.h"
int main(void) {
    const QuadraWaylandRect windows[] = {
        {{0,0},{954,1032}}, {{200,300},{640,480}},
        {{-1920,-200},{1280,720}}, {{37.5,91.25},{954.5,1032.25}}
    };
    const double heights[] = {1080,1440,2160};
    for (unsigned i=0;i<sizeof windows/sizeof *windows;i++) {
        QuadraWaylandPoint p={123.25,87.5};
        QuadraWaylandPoint cocoa=quadra_wayland_cocoa_point(p,windows[i]);
        assert(cocoa.x-windows[i].origin.x==p.x);
        assert(cocoa.y-windows[i].origin.y==windows[i].size.height-p.y);
        for (unsigned j=0;j<sizeof heights/sizeof *heights;j++) {
            QuadraWaylandPoint local={-1,-1};
            assert(quadra_wayland_local_warp((QuadraWaylandPoint){cocoa.x,heights[j]-cocoa.y},windows[i],heights[j],&local));
            assert(local.x==p.x && local.y==p.y);
        }
    }
    QuadraWaylandPoint local;
    assert(!quadra_wayland_local_warp((QuadraWaylandPoint){NAN,50},windows[0],1080,&local));
    assert(!quadra_wayland_local_warp((QuadraWaylandPoint){1,INFINITY},windows[0],1080,&local));
    assert(!quadra_wayland_local_warp((QuadraWaylandPoint){-1,50},windows[0],1080,&local));
    assert(!quadra_wayland_local_warp((QuadraWaylandPoint){954,50},windows[0],1080,&local));
    puts("PASS: logical Wayland/Cocoa/Quartz coordinates, window origins, fractional values and bounded warps");
}

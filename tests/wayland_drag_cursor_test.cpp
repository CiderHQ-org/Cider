/* Optional native Wayland regression. Uses only its own window and synthetic
 * SDL events, with no desktop input injection or Darling/user prefix.
 * clang++ -std=c++17 -O2 -pthread tests/wayland_drag_cursor_test.cpp \
 *   $(pkg-config --cflags --libs sdl2 wayland-client wayland-egl wayland-cursor) -o /tmp/wayland-drag-cursor
 */
#include <cassert>
#include "../wayland_host.cpp"
static SDL_Event button(unsigned id,unsigned number,bool down) {
    SDL_Event event{};event.type=down?SDL_MOUSEBUTTONDOWN:SDL_MOUSEBUTTONUP;
    event.button.windowID=id;event.button.button=number;event.button.clicks=1;return event;
}
int main() {
    alarm(15);
    auto host=macoblox_wayland_host_api();assert(host);
    unsigned id=host->create(320,240);assert(id);
    host->action(id,MW_TITLE,0,0,"Quadra cursor test");
    bool focused=false;
    for(unsigned i=0;i<100 && !focused;i++) {
        focused=sync([=]{return windows.at(id).focused;});
        if(!focused)std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
    assert(focused);
    unsigned int green[64],blank[64]={0};
    std::fill_n(green,64,0xff00ff00u);
    host->cursor(green,8,8,32,4,5,nullptr);
    host->cursor(blank,8,8,32,0,0,nullptr);
    host->action(0,MW_CURSOR_VISIBLE,0,0,nullptr);
    sync([=]{
        auto &window=windows.at(id);window.x=80;window.y=90;
        assert(visible_cursor_frame.buffer && visible_cursor_frame.opaque && !cursor_frame.opaque);
        capture(window,id,true);assert(window.capture && !window.cursor_mapped);
        translate(button(id,3,true));
        assert(!window.cursor_mapped); // existing Shift Lock is not changed by RMB
        capture(window,id,false);capture(window,id,true);
        assert(window.capture && window.cursor_mapped && window.shown_cursor==visible_cursor_frame.buffer);
        assert(window.cursor_x==76 && window.cursor_y==85);
        SDL_Event motion{};motion.type=SDL_MOUSEMOTION;motion.motion.windowID=id;
        motion.motion.xrel=7;motion.motion.yrel=-9;translate(motion);
        assert(window.anchor_x==80 && window.anchor_y==90);
        translate(button(id,1,true));translate(button(id,1,false));
        assert(window.cursor_mapped); // left-button transitions do not end the override
        translate(button(id,3,false));assert(!window.cursor_mapped);
        capture(window,id,false);
        translate(button(id,3,true));capture(window,id,true);assert(window.cursor_mapped);
        SDL_Event blur{};blur.type=SDL_WINDOWEVENT;blur.window.windowID=id;
        blur.window.event=SDL_WINDOWEVENT_FOCUS_LOST;translate(blur);
        assert(!window.cursor_mapped && !window.capture && !window.drag_cursor.buttons);
    });
    macoblox_wayland_event event{};bool delta=false;
    while(host->poll(&event))if(event.type==MW_MOTION && event.window==id && event.dx==7 && event.dy==-9)delta=true;
    assert(delta);
    host->action(id,MW_DESTROY,0,0,nullptr);sync([]{});
    std::puts("PASS: native Wayland right-drag cursor buffer/hotspot, transparent selection, raw deltas, release and focus loss");
}

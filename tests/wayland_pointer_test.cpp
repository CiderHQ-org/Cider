/* Exercise the real host command/event ordering without a display or desktop
 * input. Only SDL's native capture/warp calls are replaced. */
#include <SDL.h>
#include <cassert>
#include <cmath>
static bool relative_mode;
static int warp_count,warp_x,warp_y;
static int set_relative(SDL_bool enabled){relative_mode=enabled;return 0;}
static void window_size(SDL_Window *,int *width,int *height){*width=320;*height=240;}
static void warp_pointer(SDL_Window *,int x,int y){warp_count++;warp_x=x;warp_y=y;}
#define SDL_SetRelativeMouseMode set_relative
#define SDL_GetWindowSize window_size
#define SDL_WarpMouseInWindow warp_pointer
#include "../wayland_host.cpp"

static void command(unsigned id,int operation,double x=0,double y=0) {
    action(id,operation,x,y,nullptr);
    while(!commands.empty()) {auto next=std::move(commands.front());commands.pop_front();next();}
}
static void focus(unsigned id,bool active) {
    SDL_Event event{};event.type=SDL_WINDOWEVENT;event.window.windowID=id;
    event.window.event=active?SDL_WINDOWEVENT_FOCUS_GAINED:SDL_WINDOWEVENT_FOCUS_LOST;translate(event);
}
static void button(unsigned id,bool down) {
    SDL_Event event{};event.type=down?SDL_MOUSEBUTTONDOWN:SDL_MOUSEBUTTONUP;
    event.button.windowID=id;event.button.button=3;translate(event);
}
static void clear_events(){macoblox_wayland_event event{};while(poll(&event)){};}
int main() {
    const unsigned id=17;
    auto &window=windows.emplace(id,decltype(windows)::mapped_type{}).first->second;
    window.focused=true;window.x=31;window.y=47;
    command(id,MW_LOCK,1);assert(window.capture && relative_mode);clear_events();
    // A queued pre-warp motion must end at the center, with its delta intact.
    SDL_Event motion{};motion.type=SDL_MOUSEMOTION;motion.motion.windowID=id;
    motion.motion.xrel=7;motion.motion.yrel=-9;translate(motion);
    command(id,MW_WARP,160,120);
    macoblox_wayland_event event{};
    assert(poll(&event) && event.type==MW_MOTION && event.x==160 && event.y==120);
    assert(event.dx==7 && event.dy==-9 && !poll(&event));
    assert(window.anchor_x==160 && window.anchor_y==120 && warp_count==1);
    assert(warp_x==160 && warp_y==120);
    command(id,MW_WARP,160,120);assert(warp_count==1 && !poll(&event));
    for(auto point:{std::pair<double,double>{NAN,120},{160,INFINITY},{-1,120},{320,120},{160,240}})
        command(id,MW_WARP,point.first,point.second);
    assert(warp_count==1 && window.anchor_x==160 && window.anchor_y==120);
    // Persistent Shift Lock survives focus without reverting to its old anchor.
    focus(id,false);assert(!window.capture && !relative_mode && window.requested_capture);
    command(id,MW_WARP,80,90);assert(warp_count==1);
    focus(id,true);assert(window.capture && window.anchor_x==160 && window.anchor_y==120);
    command(id,MW_LOCK,0);assert(!window.capture && !relative_mode);clear_events();
    // Warp before lock must also work when Wayland cannot move a visible pointer.
    command(id,MW_WARP,100,110);command(id,MW_LOCK,1);
    assert(window.capture && window.anchor_x==100 && window.anchor_y==110);
    command(id,MW_LOCK,0);
    // Releasing RMB in another window cannot resurrect the old camera drag.
    button(id,true);command(id,MW_LOCK,1);assert(window.drag_cursor.button_capture);
    focus(id,false);assert(!window.requested_capture && !window.capture);
    command(id,MW_LOCK,1);assert(!window.requested_capture); // stale background request
    focus(id,true);assert(!window.capture && !relative_mode);
    // A fresh drag still works; even a release just before blur cancels its intent.
    button(id,true);command(id,MW_LOCK,1);button(id,false);
    focus(id,false);focus(id,true);assert(!window.capture);
    button(id,true);command(id,MW_LOCK,1);assert(window.capture);
    command(id,MW_LOCK,0);
    puts("PASS: Wayland Shift Lock warp ordering, deltas, bounds, focus resume and stale camera-drag cancellation");
}

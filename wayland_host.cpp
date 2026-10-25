/* Native Wayland windows and input. The SDL event thread never calls back
 * into Darwin. Rendering uses the wl_egl_window directly, with no game
 * framebuffer readback and no X11 connection. */
#include "wayland_bridge.h"
#include "cursor_pixels.h"
#include "drag_cursor.h"
#include <SDL.h>
#include <SDL_syswm.h>
#include <wayland-client.h>
#include <wayland-egl.h>
#include <wayland-cursor.h>
#include <sys/mman.h>
#include <unistd.h>
#include <algorithm>
#include <atomic>
#include <condition_variable>
#include <deque>
#include <future>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>
#include <cstdio>
#include <cstring>
#include <cmath>

namespace {
struct Window {
    SDL_Window *window;
    wl_egl_window *surface;
    double x=0, y=0, anchor_x=0, anchor_y=0;
    bool capture=false, requested_capture=false, focused=false;
    bool keys[128]{};
    unsigned key_modifiers=0;
    QuadraDragCursor drag_cursor{};
    wl_surface *wl_surface_handle=nullptr,*cursor_surface=nullptr;
    wl_subsurface *cursor_subsurface=nullptr;
    wl_buffer *shown_cursor=nullptr;
    int cursor_x=0,cursor_y=0;
    bool cursor_mapped=false;
    int background_width=0,background_height=0,pending_width=0,pending_height=0;
    std::vector<unsigned> drawable_stack;
};
struct Subwindow {
    unsigned parent;
    wl_surface *surface;
    wl_subsurface *role;
    wl_egl_window *egl_window;
    int x,y,width,height;
};
std::unordered_map<unsigned, Window> windows;
std::unordered_map<unsigned, Subwindow> subwindows;
unsigned next_subwindow=1;
std::mutex queue_mutex;
std::deque<std::function<void()>> commands;
std::deque<quadra_wayland_event> events;
std::thread ui;
std::atomic<bool> stopping{false};
Uint32 wake_event;
void *native_display;
std::string failure;
int screen_width=1920,screen_height=1080;
double screen_hz=60;
SDL_Cursor *custom_cursor;
bool cursor_visible=true;
wl_compositor *compositor;
wl_subcompositor *subcompositor;
wl_shm *shm;
wl_cursor_theme *cursor_theme;
struct CursorFrame {wl_buffer *buffer=nullptr;int hot_x=0,hot_y=0,width=0,height=0;bool opaque=false;};
CursorFrame cursor_frame,visible_cursor_frame;
struct OwnedBuffer {wl_buffer *buffer;bool released=false,submitted=false;};
std::vector<std::unique_ptr<OwnedBuffer>> owned_buffers;

void cursor_above_children(Window &window) {
    if(!window.cursor_subsurface || window.drawable_stack.empty())return;
    /* A newly created/re-shown child is initially above every sibling. Keep
     * the locked pointer visible above the view's rendered surface. */
    auto top=subwindows.find(window.drawable_stack.back());
    if(top!=subwindows.end() && top->second.role)
        wl_subsurface_place_above(window.cursor_subsurface,top->second.surface);
}

void update_cursor(Window &window) {
    bool right_drag=quadra_drag_cursor_visible(&window.drag_cursor);
    const auto &frame=right_drag && (!cursor_visible || !cursor_frame.opaque)
        ? visible_cursor_frame : cursor_frame;
    bool visible=window.capture && window.focused && (cursor_visible || right_drag) && frame.buffer;
    if(!window.cursor_surface && visible && subcompositor && compositor) {
        window.cursor_surface=wl_compositor_create_surface(compositor);
        window.cursor_subsurface=wl_subcompositor_get_subsurface(subcompositor,window.cursor_surface,window.wl_surface_handle);
        wl_subsurface_set_desync(window.cursor_subsurface);
        auto region=wl_compositor_create_region(compositor);wl_surface_set_input_region(window.cursor_surface,region);wl_region_destroy(region);
        cursor_above_children(window);
    }
    if(!window.cursor_surface)return;
    int x=(int)window.anchor_x-frame.hot_x,y=(int)window.anchor_y-frame.hot_y;
    if(visible && window.cursor_mapped && window.shown_cursor==frame.buffer && window.cursor_x==x && window.cursor_y==y)return;
    if(!visible && !window.cursor_mapped)return;
    if(visible){
        for(auto &owned:owned_buffers)if(owned->buffer==frame.buffer){owned->submitted=true;owned->released=false;}
        wl_subsurface_set_position(window.cursor_subsurface,x,y);
        wl_surface_attach(window.cursor_surface,frame.buffer,0,0);
        wl_surface_damage(window.cursor_surface,0,0,frame.width,frame.height);
    } else wl_surface_attach(window.cursor_surface,nullptr,0,0);
    wl_surface_commit(window.cursor_surface);
    /* Position is parent-synchronized even on a desynchronized subsurface. */
    wl_surface_commit(window.wl_surface_handle);
    wl_display_flush((wl_display *)native_display);
    window.cursor_mapped=visible;window.shown_cursor=visible?frame.buffer:nullptr;window.cursor_x=x;window.cursor_y=y;
}
void refresh_cursors(){for(auto &entry:windows)update_cursor(entry.second);}
void system_cursor(const char *name) {
    auto cursor=cursor_theme?wl_cursor_theme_get_cursor(cursor_theme,name):nullptr;
    if(!cursor || !cursor->image_count)return;
    auto image=cursor->images[0];cursor_frame={wl_cursor_image_get_buffer(image),
        (int)image->hotspot_x,(int)image->hotspot_y,(int)image->width,(int)image->height,true};
    visible_cursor_frame=cursor_frame;
}
void registry_global(void *,wl_registry *registry,uint32_t id,const char *interface,uint32_t version) {
    if(!std::strcmp(interface,"wl_compositor"))compositor=(wl_compositor *)wl_registry_bind(registry,id,&wl_compositor_interface,std::min(version,4u));
    else if(!std::strcmp(interface,"wl_subcompositor"))subcompositor=(wl_subcompositor *)wl_registry_bind(registry,id,&wl_subcompositor_interface,1);
    else if(!std::strcmp(interface,"wl_shm"))shm=(wl_shm *)wl_registry_bind(registry,id,&wl_shm_interface,1);
}
void registry_remove(void *,wl_registry *,uint32_t){}
void custom_cursor_surface(const std::vector<unsigned char> &,int,int,int,int);
void initialize_cursor_surfaces() {
    auto display=(wl_display *)native_display;
    auto registry=wl_display_get_registry(display);
    static const wl_registry_listener listener={registry_global,registry_remove};
    wl_registry_add_listener(registry,&listener,nullptr);
    wl_display_roundtrip(display);wl_registry_destroy(registry);
    if(shm){cursor_theme=wl_cursor_theme_load(getenv("XCURSOR_THEME"),32,shm);system_cursor("left_ptr");}
    if(shm && !cursor_frame.buffer) {
        std::vector<unsigned char> pixels(10*17*4);
        for(unsigned y=0;y<17;y++)for(unsigned x=0;x<10;x++) {
            unsigned word=quadra_drag_cursor_arrow(x,y);
            std::memcpy(pixels.data()+(y*10+x)*4,&word,4);
        }
        custom_cursor_surface(pixels,10,17,0,0);
    }
}
void custom_cursor_surface(const std::vector<unsigned char> &pixels,int width,int height,int hot_x,int hot_y) {
    if(!shm)return;
    int fd=memfd_create("quadra-wayland-cursor",MFD_CLOEXEC);
    size_t size=pixels.size();if(fd<0)return;
    if(ftruncate(fd,size)<0){close(fd);return;}
    void *mapping=mmap(nullptr,size,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);
    if(mapping==MAP_FAILED){close(fd);return;}std::memcpy(mapping,pixels.data(),size);
    auto pool=wl_shm_create_pool(shm,fd,size);
    auto buffer=wl_shm_pool_create_buffer(pool,0,width,height,width*4,WL_SHM_FORMAT_ARGB8888);
    wl_shm_pool_destroy(pool);munmap(mapping,size);close(fd);
    auto owned=std::make_unique<OwnedBuffer>();owned->buffer=buffer;
    static const wl_buffer_listener release={[](void *data,wl_buffer *){((OwnedBuffer *)data)->released=true;}};
    wl_buffer_add_listener(buffer,&release,owned.get());owned_buffers.push_back(std::move(owned));
    bool opaque=false;
    for(size_t offset=3;offset<pixels.size();offset+=4)if(pixels[offset]){opaque=true;break;}
    cursor_frame={buffer,hot_x,hot_y,width,height,opaque};
    if(opaque)visible_cursor_frame=cursor_frame;
}
bool map_background(Window &window,int width,int height) {
    /* The parent needs a buffer to receive focus and to apply SDL's pending
     * xdg window geometry. Game views render independently on desynchronized
     * EGL subsurfaces, so their swaps cannot commit the parent's resize.
     * Keep this opaque background at the configured logical client size.
     * A fresh memfd is zero-filled; XRGB makes those pixels opaque black
     * without touching every page. No game frames pass through SHM. */
    if(!shm || width<1 || height<1 || width>16384 || height>16384)return false;
    if(window.background_width==width && window.background_height==height) {
        wl_surface_commit(window.wl_surface_handle);
        return true;
    }
    int fd=memfd_create("quadra-wayland-background",MFD_CLOEXEC);if(fd<0)return false;
    size_t size=(size_t)width*height*4;if(ftruncate(fd,size)<0){close(fd);return false;}
    auto pool=wl_shm_create_pool(shm,fd,size);
    if(!pool){close(fd);return false;}
    auto buffer=wl_shm_pool_create_buffer(pool,0,width,height,width*4,WL_SHM_FORMAT_XRGB8888);
    wl_shm_pool_destroy(pool);close(fd);
    if(!buffer)return false;
    auto owned=std::make_unique<OwnedBuffer>();owned->buffer=buffer;owned->submitted=true;
    static const wl_buffer_listener release={[](void *data,wl_buffer *){((OwnedBuffer *)data)->released=true;}};
    wl_buffer_add_listener(buffer,&release,owned.get());owned_buffers.push_back(std::move(owned));
    wl_surface_attach(window.wl_surface_handle,buffer,0,0);
    wl_surface_damage(window.wl_surface_handle,0,0,width,height);
    wl_surface_commit(window.wl_surface_handle);
    window.background_width=width;window.background_height=height;
    if(getenv("QUADRA_TRACE_WAYLAND"))std::fprintf(stderr,"[Quadra Wayland] Committed background (%dx%d)\n",width,height);
    return true;
}
void resize_backgrounds() {
    bool committed=false;
    for(auto &entry:windows) {
        auto &window=entry.second;
        if(!window.pending_width || !window.pending_height)continue;
        /* Coalesce all size events in this SDL batch into one allocation. */
        if(!map_background(window,window.pending_width,window.pending_height))
            std::fprintf(stderr,"[Quadra Wayland] Could not resize window background (%dx%d)\n",window.pending_width,window.pending_height);
        else committed=true;
        window.pending_width=window.pending_height=0;
    }
    if(committed)wl_display_flush((wl_display *)native_display);
}

void enqueue(std::function<void()> operation) {
    { std::lock_guard<std::mutex> guard(queue_mutex); commands.push_back(std::move(operation)); }
    SDL_Event wake{};wake.type=wake_event;SDL_PushEvent(&wake);
}
template<class F> auto sync(F operation) -> decltype(operation()) {
    using T=decltype(operation());
    auto result=std::make_shared<std::packaged_task<T()>>(std::move(operation));
    auto future=result->get_future();
    enqueue([result]{(*result)();});
    return future.get();
}
unsigned modifiers(SDL_Keymod value=SDL_GetModState()) {
    return ((value&KMOD_CAPS)?1u<<16:0) | ((value&KMOD_SHIFT)?1u<<17:0) |
           ((value&KMOD_CTRL)?1u<<18:0) | ((value&KMOD_ALT)?1u<<19:0) |
           ((value&KMOD_GUI)?1u<<20:0);
}
unsigned mac_key(SDL_Scancode key) {
    /* USB/SDL physical keys to Apple's virtual key codes. Text is delivered
     * separately through SDL's input method; this table never assumes QWERTY
     * for committed text. */
    static const unsigned short letters[]={0,11,8,2,14,3,5,4,34,38,40,37,46,45,31,35,12,15,1,17,32,9,13,7,16,6};
    if(key>=SDL_SCANCODE_A && key<=SDL_SCANCODE_Z)return letters[key-SDL_SCANCODE_A];
    static const unsigned short digits[]={18,19,20,21,23,22,26,28,25,29};
    if(key>=SDL_SCANCODE_1 && key<=SDL_SCANCODE_0)return digits[key-SDL_SCANCODE_1];
    switch(key) {
    case SDL_SCANCODE_RETURN:return 36;case SDL_SCANCODE_ESCAPE:return 53;
    case SDL_SCANCODE_BACKSPACE:return 51;case SDL_SCANCODE_TAB:return 48;case SDL_SCANCODE_SPACE:return 49;
    case SDL_SCANCODE_MINUS:return 27;case SDL_SCANCODE_EQUALS:return 24;
    case SDL_SCANCODE_LEFTBRACKET:return 33;case SDL_SCANCODE_RIGHTBRACKET:return 30;
    case SDL_SCANCODE_BACKSLASH:return 42;case SDL_SCANCODE_SEMICOLON:return 41;
    case SDL_SCANCODE_APOSTROPHE:return 39;case SDL_SCANCODE_GRAVE:return 50;
    case SDL_SCANCODE_COMMA:return 43;case SDL_SCANCODE_PERIOD:return 47;case SDL_SCANCODE_SLASH:return 44;
    case SDL_SCANCODE_CAPSLOCK:return 57;case SDL_SCANCODE_LSHIFT:return 56;case SDL_SCANCODE_RSHIFT:return 60;
    case SDL_SCANCODE_LCTRL:return 59;case SDL_SCANCODE_RCTRL:return 62;
    case SDL_SCANCODE_LALT:return 58;case SDL_SCANCODE_RALT:return 61;
    case SDL_SCANCODE_LGUI:return 55;case SDL_SCANCODE_RGUI:return 54;
    case SDL_SCANCODE_LEFT:return 123;case SDL_SCANCODE_RIGHT:return 124;
    case SDL_SCANCODE_DOWN:return 125;case SDL_SCANCODE_UP:return 126;
    case SDL_SCANCODE_HOME:return 115;case SDL_SCANCODE_END:return 119;
    case SDL_SCANCODE_PAGEUP:return 116;case SDL_SCANCODE_PAGEDOWN:return 121;case SDL_SCANCODE_DELETE:return 117;
    case SDL_SCANCODE_F1:return 122;case SDL_SCANCODE_F2:return 120;case SDL_SCANCODE_F3:return 99;
    case SDL_SCANCODE_F4:return 118;case SDL_SCANCODE_F5:return 96;case SDL_SCANCODE_F6:return 97;
    case SDL_SCANCODE_F7:return 98;case SDL_SCANCODE_F8:return 100;case SDL_SCANCODE_F9:return 101;
    case SDL_SCANCODE_F10:return 109;case SDL_SCANCODE_F11:return 103;case SDL_SCANCODE_F12:return 111;
    case SDL_SCANCODE_KP_0:return 82;case SDL_SCANCODE_KP_1:return 83;case SDL_SCANCODE_KP_2:return 84;
    case SDL_SCANCODE_KP_3:return 85;case SDL_SCANCODE_KP_4:return 86;case SDL_SCANCODE_KP_5:return 87;
    case SDL_SCANCODE_KP_6:return 88;case SDL_SCANCODE_KP_7:return 89;case SDL_SCANCODE_KP_8:return 91;
    case SDL_SCANCODE_KP_9:return 92;case SDL_SCANCODE_KP_PERIOD:return 65;
    case SDL_SCANCODE_KP_ENTER:return 76;case SDL_SCANCODE_KP_DIVIDE:return 75;
    case SDL_SCANCODE_KP_MULTIPLY:return 67;case SDL_SCANCODE_KP_MINUS:return 78;case SDL_SCANCODE_KP_PLUS:return 69;
    default:return 0xffff;
    }
}
void key_text(SDL_Keycode symbol,char *text) {
    unsigned code=0;
    switch(symbol) {
    case SDLK_UP:code=0xf700;break;case SDLK_DOWN:code=0xf701;break;
    case SDLK_LEFT:code=0xf702;break;case SDLK_RIGHT:code=0xf703;break;
    case SDLK_DELETE:code=0xf728;break;case SDLK_HOME:code=0xf729;break;
    case SDLK_END:code=0xf72b;break;case SDLK_PAGEUP:code=0xf72c;break;
    case SDLK_PAGEDOWN:code=0xf72d;break;case SDLK_KP_ENTER:code='\r';break;
    default:
        if(symbol>=SDLK_F1 && symbol<=SDLK_F12)code=0xf704+symbol-SDLK_F1;
        else if(symbol>0 && !(symbol&SDLK_SCANCODE_MASK))code=(unsigned)symbol;
        break;
    }
    if(!code || code>0x10ffff || (code>=0xd800 && code<=0xdfff))return;
    if(code<0x80){text[0]=code;text[1]=0;}
    else if(code<0x800){text[0]=0xc0|(code>>6);text[1]=0x80|(code&63);text[2]=0;}
    else if(code<0x10000){text[0]=0xe0|(code>>12);text[1]=0x80|((code>>6)&63);text[2]=0x80|(code&63);text[3]=0;}
    else {text[0]=0xf0|(code>>18);text[1]=0x80|((code>>12)&63);text[2]=0x80|((code>>6)&63);text[3]=0x80|(code&63);text[4]=0;}
}
void push(quadra_wayland_event event) {
    std::lock_guard<std::mutex> guard(queue_mutex);
    /* Coalesce only adjacent motions. Button/key/focus transitions retain
     * their ordering, even when the renderer temporarily stalls. */
    if(event.type==MW_MOTION && !events.empty() && events.back().type==MW_MOTION && events.back().window==event.window && events.back().modifiers==event.modifiers) {
        event.dx+=events.back().dx;event.dy+=events.back().dy;events.back()=event;
    } else events.push_back(event);
}
void capture(Window &window,unsigned id,bool enabled) {
    bool next=enabled && window.focused;
    if(next==window.capture)return;
    if(next){window.anchor_x=window.x;window.anchor_y=window.y;}
    if(SDL_SetRelativeMouseMode(next?SDL_TRUE:SDL_FALSE)<0) {
        next=false;
        std::fprintf(stderr,"[Quadra Wayland] Relative pointer unavailable: %s\n",SDL_GetError());
    }
    window.capture=next;
    quadra_drag_cursor_capture(&window.drag_cursor,next);
    update_cursor(window);
    quadra_wayland_event event{};event.type=MW_CAPTURE;event.window=id;event.button=next;
    push(event);
}
void warp(Window &window,unsigned id,double x,double y) {
    int width,height;SDL_GetWindowSize(window.window,&width,&height);
    if(!window.focused || !std::isfinite(x) || !std::isfinite(y) ||
       x<0 || y<0 || x>=width || y>=height)return;
    bool changed=window.capture?(window.anchor_x!=x || window.anchor_y!=y):(window.x!=x || window.y!=y);
    if(!changed)return;
    window.x=x;window.y=y;
    if(window.capture){window.anchor_x=x;window.anchor_y=y;update_cursor(window);}
    /* Relative-mode warps update SDL's logical position without camera
     * motion. Outside capture Wayland may not support a physical warp, but
     * the next capture must still use the requested logical position. */
    SDL_WarpMouseInWindow(window.window,(int)x,(int)y);
    /* Acknowledge after earlier motion/capture events. Updating AppKit's
     * position optimistically let those older events undo Shift Lock's warp. */
    quadra_wayland_event event{};event.type=MW_MOTION;event.window=id;
    event.x=x;event.y=y;event.modifiers=window.key_modifiers;push(event);
}
void translate(const SDL_Event &input) {
    auto found=windows.find(input.window.windowID);
    if(found==windows.end())return;
    auto &window=found->second;
    quadra_wayland_event event{};event.window=found->first;event.modifiers=window.key_modifiers;
    event.x=window.capture?window.anchor_x:window.x;event.y=window.capture?window.anchor_y:window.y;
    switch(input.type) {
    case SDL_MOUSEMOTION:
        event.type=MW_MOTION;event.dx=input.motion.xrel;event.dy=input.motion.yrel;
        if(!window.capture){window.x=event.x=input.motion.x;window.y=event.y=input.motion.y;}
        break;
    case SDL_MOUSEBUTTONDOWN:case SDL_MOUSEBUTTONUP:
        event.type=input.type==SDL_MOUSEBUTTONDOWN?MW_DOWN:MW_UP;
        event.button=input.button.button;event.clicks=input.button.clicks;
        if(event.button>=4)event.button+=4; // match Darling's extra-button numbering
        if(event.button<32) {
            unsigned buttons=window.drag_cursor.buttons;
            if(input.type==SDL_MOUSEBUTTONDOWN)buttons|=1u<<event.button;
            else buttons&=~(1u<<event.button);
            bool previous=quadra_drag_cursor_visible(&window.drag_cursor);
            quadra_drag_cursor_buttons(&window.drag_cursor,buttons);
            if(previous!=quadra_drag_cursor_visible(&window.drag_cursor))update_cursor(window);
        }
        break;
    case SDL_MOUSEWHEEL:
        event.type=MW_SCROLL;event.dx=input.wheel.preciseX;event.dy=input.wheel.preciseY;
        if(input.wheel.direction==SDL_MOUSEWHEEL_FLIPPED){event.dx=-event.dx;event.dy=-event.dy;}
        break;
    case SDL_KEYDOWN:case SDL_KEYUP:
        event.type=input.type==SDL_KEYDOWN?MW_KEY_DOWN:MW_KEY_UP;event.key=mac_key(input.key.keysym.scancode);
        /* SDL pumps a whole batch before we read it. GetModState can already
         * describe a later Ctrl release; the event owns the correct snapshot. */
        event.modifiers=modifiers((SDL_Keymod)input.key.keysym.mod);
        window.key_modifiers=event.modifiers;
        event.repeat=input.key.repeat;
        if(event.key<128)window.keys[event.key]=input.type==SDL_KEYDOWN;
        if((input.key.keysym.scancode>=SDL_SCANCODE_KP_DIVIDE && input.key.keysym.scancode<=SDL_SCANCODE_KP_PERIOD) ||
           (input.key.keysym.scancode>=SDL_SCANCODE_INSERT && input.key.keysym.scancode<=SDL_SCANCODE_UP))event.modifiers|=1u<<21;
        key_text(input.key.keysym.sym,event.text);
        break;
    case SDL_TEXTINPUT:event.type=MW_TEXT;std::snprintf(event.text,sizeof event.text,"%s",input.text.text);break;
    case SDL_WINDOWEVENT:
        switch(input.window.event) {
        case SDL_WINDOWEVENT_SIZE_CHANGED:
            if(input.window.data1<1 || input.window.data2<1 || input.window.data1>16384 || input.window.data2>16384)return;
            wl_egl_window_resize(window.surface,input.window.data1,input.window.data2,0,0);
            if(window.background_width) {
                window.pending_width=input.window.data1;window.pending_height=input.window.data2;
            }
            event.type=MW_RESIZE;event.x=input.window.data1;event.y=input.window.data2;break;
        case SDL_WINDOWEVENT_FOCUS_GAINED:
            window.key_modifiers=event.modifiers=modifiers();
            window.focused=true;event.type=MW_FOCUS;
            capture(window,found->first,window.requested_capture);break;
        case SDL_WINDOWEVENT_FOCUS_LOST:
            /* Releases otherwise go to the newly focused client. Queue them
             * after our last key press so polling cannot retain stuck keys. */
            for(unsigned key=0;key<128;key++)if(window.keys[key]) {
                quadra_wayland_event up{};up.type=MW_KEY_UP;up.window=found->first;up.key=key;
                window.keys[key]=false;push(up);
            }
            /* A release in another window never reaches this SDL window.
             * Do not resurrect a drag's capture when focus comes back.
             * Button-free Shift Lock/first-person intent may resume. */
            if(window.drag_cursor.button_capture)window.requested_capture=false;
            quadra_drag_cursor_buttons(&window.drag_cursor,0);
            window.focused=false;capture(window,found->first,false);event.type=MW_BLUR;
            window.key_modifiers=event.modifiers=0;break;
        case SDL_WINDOWEVENT_CLOSE:event.type=MW_CLOSE;break;
        default:return;
        }
        if(getenv("QUADRA_TRACE_WAYLAND"))std::fprintf(stderr,"[Quadra Wayland] Window event %u for %u\n",event.type,found->first);
        break;
    default:return;
    }
    push(event);
}
unsigned create_window(int width,int height,bool bootstrap=false) {
    if(width<1 || height<1 || width>16384 || height>16384)return 0;
    SDL_Window *window=SDL_CreateWindow("Quadra",SDL_WINDOWPOS_UNDEFINED,SDL_WINDOWPOS_UNDEFINED,
                                      width,height,SDL_WINDOW_RESIZABLE|(bootstrap?SDL_WINDOW_HIDDEN:0));
    SDL_SysWMinfo info{};SDL_VERSION(&info.version);
    if(!window || !SDL_GetWindowWMInfo(window,&info) || info.subsystem!=SDL_SYSWM_WAYLAND || !info.info.wl.surface) {
        failure=SDL_GetError();if(window)SDL_DestroyWindow(window);return 0;
    }
    native_display=info.info.wl.display;
    auto egl_window=wl_egl_window_create(info.info.wl.surface,width,height);
    if(!egl_window){failure="wl_egl_window_create failed";SDL_DestroyWindow(window);return 0;}
    unsigned id=SDL_GetWindowID(window);Window native_window{};
    native_window.window=window;native_window.surface=egl_window;
    windows.emplace(id,std::move(native_window));
    windows.at(id).wl_surface_handle=info.info.wl.surface;
    if(!bootstrap) {
        /* SDL can receive a tiling compositor's initial configure before
         * SDL_CreateWindow returns; use that size for the first parent buffer. */
        int actual_width,actual_height;SDL_GetWindowSize(window,&actual_width,&actual_height);
        auto &entry=windows.at(id);
        if(!map_background(entry,actual_width,actual_height)) {
            failure="Could not map native Wayland window background";
            wl_egl_window_destroy(egl_window);SDL_DestroyWindow(window);windows.erase(id);return 0;
        }
        wl_display_flush((wl_display *)native_display);
    }
    std::fprintf(stderr,"[Quadra Wayland] Created window %u (%dx%d)\n",id,width,height);
    return id;
}
void *display(){return native_display;}
unsigned create(int width,int height){return sync([=]{return create_window(width,height);});}
void *surface(unsigned id){return sync([=]() -> void * {auto found=windows.find(id);return found==windows.end()?nullptr:found->second.surface;});}
bool valid_subwindow_frame(int x,int y,int width,int height) {
    return x>=-32768 && x<=32768 && y>=-32768 && y<=32768 && width>0 && width<=16384 && height>0 && height<=16384;
}
bool show_subwindow(unsigned id,Subwindow &child) {
    auto parent=windows.find(child.parent);
    if(parent==windows.end())return false;
    if(!child.role) {
        child.role=wl_subcompositor_get_subsurface(subcompositor,child.surface,parent->second.wl_surface_handle);
        if(!child.role){failure="wl_subcompositor_get_subsurface failed";return false;}
        /* Render threads commit their own buffers without waiting for the
         * AppKit/SDL parent to repaint on every frame. Position and stacking
         * still need the parent commit below. */
        wl_subsurface_set_desync(child.role);
        wl_subsurface_set_position(child.role,child.x,child.y);
        parent->second.drawable_stack.push_back(id);
        cursor_above_children(parent->second);
        wl_surface_commit(parent->second.wl_surface_handle);
        wl_display_flush((wl_display *)native_display);
    }
    return true;
}
unsigned create_subwindow(unsigned parent_id,int x,int y,int width,int height) {
    return sync([=]() -> unsigned {
        if(!valid_subwindow_frame(x,y,width,height) || !windows.count(parent_id)) {failure="Invalid native Wayland view frame or parent";return 0;}
        if(!compositor || !subcompositor){failure="The compositor does not provide Wayland sub-surfaces";return 0;}
        auto child_surface=wl_compositor_create_surface(compositor);
        if(!child_surface){failure="wl_compositor_create_surface failed";return 0;}
        /* SDL owns input on the toplevel. Without an empty child input region
         * the compositor routes pointer events to a surface SDL cannot map
         * back to a window, dropping mouse movement and button presses. */
        auto region=wl_compositor_create_region(compositor);
        if(!region){wl_surface_destroy(child_surface);failure="wl_compositor_create_region failed";return 0;}
        wl_surface_set_input_region(child_surface,region);wl_region_destroy(region);
        wl_surface_set_buffer_scale(child_surface,1);
        auto egl_window=wl_egl_window_create(child_surface,width,height);
        if(!egl_window){wl_surface_destroy(child_surface);failure="wl_egl_window_create failed for native Wayland view";return 0;}
        unsigned id=next_subwindow++;
        if(!id || subwindows.count(id)){wl_egl_window_destroy(egl_window);wl_surface_destroy(child_surface);failure="Native Wayland view handles exhausted";return 0;}
        auto inserted=subwindows.emplace(id,Subwindow{parent_id,child_surface,nullptr,egl_window,x,y,width,height});
        if(!show_subwindow(id,inserted.first->second)) {
            wl_egl_window_destroy(egl_window);wl_surface_destroy(child_surface);subwindows.erase(id);return 0;
        }
        static unsigned reported;
        if(reported++<24)std::fprintf(stderr,"[Quadra Wayland] Created GL view %u for window %u at %d,%d (%dx%d)\n",id,parent_id,x,y,width,height);
        return id;
    });
}
void *subwindow_surface(unsigned id) {
    return sync([=]() -> void * {auto found=subwindows.find(id);return found==subwindows.end()?nullptr:found->second.egl_window;});
}
void *subwindow_wl_surface(unsigned id) {
    return sync([=]() -> void * {auto found=subwindows.find(id);return found==subwindows.end()?nullptr:found->second.surface;});
}
void subwindow_frame(unsigned id,int x,int y,int width,int height) {
    sync([=]{
        auto found=subwindows.find(id);if(found==subwindows.end() || !valid_subwindow_frame(x,y,width,height))return;
        auto &child=found->second;
        if(child.width!=width || child.height!=height){wl_egl_window_resize(child.egl_window,width,height,0,0);child.width=width;child.height=height;}
        if(child.x==x && child.y==y)return;
        child.x=x;child.y=y;
        auto parent=windows.find(child.parent);
        if(child.role && parent!=windows.end()) {
            wl_subsurface_set_position(child.role,x,y);wl_surface_commit(parent->second.wl_surface_handle);
            wl_display_flush((wl_display *)native_display);
        }
    });
}
void subwindow_visible(unsigned id,int visible) {
    sync([=]{
        auto found=subwindows.find(id);if(found==subwindows.end())return;auto &child=found->second;
        if(visible){show_subwindow(id,child);return;}
        if(child.role) {
            /* Destroying the role unmaps immediately and keeps the native
             * drawable alive. A NULL attach alone would be undone by the next
             * EGL swap from a render thread. Wayland permits giving this same
             * sub-surface role again when the view is shown. */
            wl_subsurface_destroy(child.role);child.role=nullptr;
            auto parent=windows.find(child.parent);
            if(parent!=windows.end()) {
                auto &stack=parent->second.drawable_stack;
                stack.erase(std::remove(stack.begin(),stack.end(),id),stack.end());
            }
            wl_display_flush((wl_display *)native_display);
        }
    });
}
void destroy_subwindow(unsigned id) {
    sync([=]{
        auto found=subwindows.find(id);if(found==subwindows.end())return;auto &child=found->second;
        /* AppKit releases the CGSubWindow after CGLDestroyWindow has released
         * its EGLSurface. Never reuse a parent's native EGL window. */
        if(child.role)wl_subsurface_destroy(child.role);
        auto parent=windows.find(child.parent);
        if(parent!=windows.end()) {
            auto &stack=parent->second.drawable_stack;
            stack.erase(std::remove(stack.begin(),stack.end(),id),stack.end());
        }
        wl_egl_window_destroy(child.egl_window);wl_surface_destroy(child.surface);subwindows.erase(found);
        wl_display_flush((wl_display *)native_display);
    });
}
void action(unsigned id,int operation,double x,double y,const char *text) {
    std::string copy=text?text:"";
    enqueue([=]{
        if(operation==MW_CURSOR_VISIBLE){cursor_visible=x!=0;SDL_ShowCursor(cursor_visible?SDL_ENABLE:SDL_DISABLE);refresh_cursors();return;}
        auto found=windows.find(id);if(found==windows.end())return;auto &window=found->second;
        switch(operation) {
        case MW_SHOW:SDL_ShowWindow(window.window);break;
        case MW_HIDE:capture(window,id,false);SDL_HideWindow(window.window);break;
        case MW_TITLE:SDL_SetWindowTitle(window.window,copy.c_str());break;
        case MW_RESIZE_WINDOW:if(x>0 && y>0 && x<=16384 && y<=16384)SDL_SetWindowSize(window.window,(int)x,(int)y);break;
        case MW_FULLSCREEN:SDL_SetWindowFullscreen(window.window,x?SDL_WINDOW_FULLSCREEN_DESKTOP:0);break;
        case MW_LOCK:
            if(x && !window.focused)break;
            window.requested_capture=x!=0;
            capture(window,id,window.requested_capture);
            break;
        case MW_WARP:
            warp(window,id,x,y);
            break;
        case MW_MINIMIZE:SDL_MinimizeWindow(window.window);break;
        case MW_DESTROY:
            if(window.capture)SDL_SetRelativeMouseMode(SDL_FALSE);
            if(window.cursor_subsurface)wl_subsurface_destroy(window.cursor_subsurface);
            if(window.cursor_surface)wl_surface_destroy(window.cursor_surface);
            /* Closing the toplevel unmaps children, but their EGL drawables
             * remain owned by AppKit until each CGSubWindow is released. */
            for(auto &entry:subwindows)if(entry.second.parent==id)entry.second.parent=0;
            wl_egl_window_destroy(window.surface);SDL_DestroyWindow(window.window);windows.erase(found);break;
        }
    });
}
int poll(quadra_wayland_event *event) {
    std::lock_guard<std::mutex> guard(queue_mutex);
    if(events.empty())return 0;*event=events.front();events.pop_front();return 1;
}
void screen(int *width,int *height,double *hz){*width=screen_width;*height=screen_height;*hz=screen_hz;}
void cursor(const void *pixels,int width,int height,int pitch,int hot_x,int hot_y,const char *name) {
    if(pixels && (width<1 || height<1 || width>1024 || height>1024 || pitch<width*4))return;
    std::vector<unsigned char> copy;
    if(pixels){copy.resize(width*height*4);for(int row=0;row<height;row++)std::memcpy(copy.data()+row*width*4,(const char*)pixels+row*pitch,width*4);}
    std::string shape=name?name:"";
    enqueue([=]{
        SDL_Cursor *next=nullptr;
        if(!copy.empty()) {
            /* SDL's Wayland backend premultiplies its input. Supply straight
             * alpha there; the locked-cursor SHM buffer keeps premultiplied
             * alpha, avoiding a second multiplication at soft edges. */
            std::vector<unsigned char> straight(copy.size());
            for(size_t offset=0;offset<copy.size();offset+=4) {
                unsigned int pixel;std::memcpy(&pixel,copy.data()+offset,4);
                pixel=quadra_cursor_straight_argb(pixel);
                std::memcpy(straight.data()+offset,&pixel,4);
            }
            auto bitmap=SDL_CreateRGBSurfaceWithFormatFrom(straight.data(),width,height,32,width*4,SDL_PIXELFORMAT_ARGB8888);
            if(bitmap){next=SDL_CreateColorCursor(bitmap,std::clamp(hot_x,0,width-1),std::clamp(hot_y,0,height-1));SDL_FreeSurface(bitmap);}
            custom_cursor_surface(copy,width,height,std::clamp(hot_x,0,width-1),std::clamp(hot_y,0,height-1));
        } else {
            SDL_SystemCursor system=SDL_SYSTEM_CURSOR_ARROW;
            if(shape=="pointingHandCursor")system=SDL_SYSTEM_CURSOR_HAND;
            else if(shape=="IBeamCursor")system=SDL_SYSTEM_CURSOR_IBEAM;
            else if(shape=="crosshairCursor")system=SDL_SYSTEM_CURSOR_CROSSHAIR;
            else if(shape=="resizeLeftRightCursor")system=SDL_SYSTEM_CURSOR_SIZEWE;
            else if(shape=="resizeUpDownCursor")system=SDL_SYSTEM_CURSOR_SIZENS;
            next=SDL_CreateSystemCursor(system);
            system_cursor(system==SDL_SYSTEM_CURSOR_HAND?"hand2":system==SDL_SYSTEM_CURSOR_IBEAM?"xterm":system==SDL_SYSTEM_CURSOR_CROSSHAIR?"crosshair":"left_ptr");
        }
        if(next){SDL_SetCursor(next);if(custom_cursor)SDL_FreeCursor(custom_cursor);custom_cursor=next;}
        refresh_cursors();
    });
}
const char *clipboard(const char *text) {
    std::string copy=text?text:"";
    thread_local std::string result;
    result=sync([=]{
        if(text)SDL_SetClipboardText(copy.c_str());
        char *value=SDL_GetClipboardText();std::string output=value?value:"";SDL_free(value);return output;
    });
    return result.c_str();
}
const char *error(){return failure.c_str();}
const quadra_wayland_api api={QUADRA_WAYLAND_ABI,display,create,surface,action,poll,screen,cursor,clipboard,error,
                              create_subwindow,subwindow_surface,subwindow_frame,subwindow_visible,destroy_subwindow,
                              subwindow_wl_surface};
void shutdown() {
    stopping.store(true);
    if(ui.joinable()) {
        SDL_Event wake{};wake.type=wake_event;SDL_PushEvent(&wake);
        ui.join();
    }
}
}
extern "C" const quadra_wayland_api *quadra_wayland_host_api() {
    static std::once_flag once;
    static bool ready;
    std::call_once(once,[]{
        std::promise<bool> initialized;auto result=initialized.get_future();
        ui=std::thread([&initialized]{
            SDL_SetHint("SDL_APP_ID","quadrahq-roblox-window");
            SDL_SetHint("SDL_VIDEO_WAYLAND_WMCLASS","quadrahq-roblox-window");
            SDL_SetHint(SDL_HINT_VIDEO_WAYLAND_PREFER_LIBDECOR,"1");
            SDL_SetHint(SDL_HINT_VIDEO_X11_NET_WM_BYPASS_COMPOSITOR,"0");
            SDL_SetHint(SDL_HINT_MOUSE_RELATIVE_WARP_MOTION,"0");
            /* Selecting Wayland explicitly forbids SDL's X11 fallback. */
            if(SDL_VideoInit("wayland")<0){failure=SDL_GetError();initialized.set_value(false);return;}
            SDL_GL_SetAttribute(SDL_GL_RED_SIZE,8);SDL_GL_SetAttribute(SDL_GL_GREEN_SIZE,8);SDL_GL_SetAttribute(SDL_GL_BLUE_SIZE,8);
            SDL_GL_SetAttribute(SDL_GL_ALPHA_SIZE,0);SDL_GL_SetAttribute(SDL_GL_DOUBLEBUFFER,1);
            SDL_DisplayMode mode{};if(SDL_GetCurrentDisplayMode(0,&mode)==0){screen_width=mode.w;screen_height=mode.h;if(mode.refresh_rate)screen_hz=mode.refresh_rate;}
            wake_event=SDL_RegisterEvents(1);
            unsigned bootstrap=create_window(32,32,true);
            if(!bootstrap){initialized.set_value(false);return;}
            initialize_cursor_surfaces();
            SDL_StartTextInput();initialized.set_value(true);
            std::fprintf(stderr,"[Quadra Wayland] Native Wayland display connected\n");
            while(!stopping.load()) {
                std::deque<std::function<void()>> batch;
                {std::lock_guard<std::mutex> guard(queue_mutex);batch.swap(commands);}
                for(auto &operation:batch)operation();
                SDL_Event event;if(SDL_WaitEventTimeout(&event,10))translate(event);
                /* Bound each batch so a fast mouse cannot starve commands. */
                for(unsigned count=0;count<256 && SDL_PollEvent(&event);count++)translate(event);
                resize_backgrounds();
                wl_display_dispatch_pending((wl_display *)native_display);
                /* A release makes old cursor and background buffers safe to destroy. */
                owned_buffers.erase(std::remove_if(owned_buffers.begin(),owned_buffers.end(),[](auto &buffer){if((buffer->released || !buffer->submitted) && buffer->buffer!=cursor_frame.buffer && buffer->buffer!=visible_cursor_frame.buffer){wl_buffer_destroy(buffer->buffer);return true;}return false;}),owned_buffers.end());
            }
            for(auto &entry:subwindows) {
                if(entry.second.role)wl_subsurface_destroy(entry.second.role);
                wl_egl_window_destroy(entry.second.egl_window);wl_surface_destroy(entry.second.surface);
            }
            subwindows.clear();
            for(auto &entry:windows) {
                if(entry.second.cursor_subsurface)wl_subsurface_destroy(entry.second.cursor_subsurface);
                if(entry.second.cursor_surface)wl_surface_destroy(entry.second.cursor_surface);
                wl_egl_window_destroy(entry.second.surface);
                SDL_DestroyWindow(entry.second.window);
            }
            windows.clear();
            for(auto &buffer:owned_buffers)wl_buffer_destroy(buffer->buffer);
            owned_buffers.clear();
            if(custom_cursor)SDL_FreeCursor(custom_cursor);
            if(cursor_theme)wl_cursor_theme_destroy(cursor_theme);
            SDL_VideoQuit();
        });
        ready=result.get();
        if(ready)std::atexit(shutdown);
        else if(ui.joinable())ui.join();
    });
    return ready?&api:nullptr;
}

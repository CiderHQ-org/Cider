/* Host keyboard regression: synthetic SDL events only, no display or input
 * injection. Compile with the same SDL/Wayland libraries as wayland_host.cpp. */
#include <cassert>
#include "../wayland_host.cpp"

static SDL_Event key(unsigned id, SDL_Scancode scan, SDL_Keycode symbol,
                     SDL_Keymod mods, bool down=true, bool repeat=false) {
    SDL_Event event{};event.type=down?SDL_KEYDOWN:SDL_KEYUP;
    event.key.windowID=id;event.key.keysym.scancode=scan;
    event.key.keysym.sym=symbol;event.key.keysym.mod=mods;
    event.key.repeat=repeat;return event;
}

int main() {
    const unsigned id=17;
    windows.emplace(id,decltype(windows)::mapped_type{});
    SDL_SetModState(KMOD_NONE);
    quadra_wayland_event event{};
    translate(key(id,SDL_SCANCODE_LCTRL,SDLK_LCTRL,KMOD_LCTRL));
    assert(poll(&event) && event.type==MW_KEY_DOWN && event.key==59);
    assert((event.modifiers&(1u<<18)) && !(event.modifiers&(1u<<20)));
    translate(key(id,SDL_SCANCODE_RCTRL,SDLK_RCTRL,KMOD_CTRL));
    assert(poll(&event) && event.key==62 && (event.modifiers&(1u<<18)));
    translate(key(id,SDL_SCANCODE_LCTRL,SDLK_LCTRL,KMOD_RCTRL,false));
    assert(poll(&event) && event.type==MW_KEY_UP && event.key==59 && (event.modifiers&(1u<<18)));
    translate(key(id,SDL_SCANCODE_A,SDLK_a,KMOD_RCTRL));
    assert(poll(&event) && event.key==0 && (event.modifiers&(1u<<18)));
    SDL_Event mouse{};mouse.type=SDL_MOUSEMOTION;mouse.motion.windowID=id;translate(mouse);
    assert(poll(&event) && event.type==MW_MOTION && (event.modifiers&(1u<<18)));
    translate(key(id,SDL_SCANCODE_LGUI,SDLK_LGUI,KMOD_LGUI));
    assert(poll(&event) && event.key==55 && (event.modifiers&(1u<<20)));
    translate(key(id,SDL_SCANCODE_LEFT,SDLK_LEFT,KMOD_NONE));
    assert(poll(&event) && event.key==123 && (event.modifiers&(1u<<21)));
    assert(!std::strcmp(event.text,"\xef\x9c\x82")); // U+F702
    /* Keys outside the main block used to be dropped (key 0xffff). */
    translate(key(id,SDL_SCANCODE_INSERT,SDLK_INSERT,KMOD_NONE));
    assert(poll(&event) && event.key==114 && (event.modifiers&(1u<<21)));
    assert(!std::strcmp(event.text,"\xef\x9d\x86")); // U+F746, Help
    translate(key(id,SDL_SCANCODE_F16,SDLK_F16,KMOD_NONE));
    assert(poll(&event) && event.key==106 && !(event.modifiers&(1u<<21)));
    translate(key(id,SDL_SCANCODE_F20,SDLK_F20,KMOD_NONE));
    assert(poll(&event) && event.key==90 && !std::strcmp(event.text,"\xef\x9c\x97")); // U+F717
    translate(key(id,SDL_SCANCODE_PRINTSCREEN,SDLK_PRINTSCREEN,KMOD_NONE));
    assert(poll(&event) && event.key==105);
    translate(key(id,SDL_SCANCODE_NONUSBACKSLASH,SDLK_LESS,KMOD_NONE));
    assert(poll(&event) && event.key==10);
    translate(key(id,SDL_SCANCODE_APPLICATION,SDLK_APPLICATION,KMOD_NONE));
    assert(poll(&event) && event.key==110);
    translate(key(id,SDL_SCANCODE_KP_EQUALS,SDLK_KP_EQUALS,KMOD_NONE));
    assert(poll(&event) && event.key==81 && (event.modifiers&(1u<<21)));
    translate(key(id,SDL_SCANCODE_A,SDLK_a,KMOD_LSHIFT,true,true));
    assert(poll(&event) && event.repeat && (event.modifiers&(1u<<17)));
    /* The middle and side buttons reach AppKit as buttons 2, 8 and 9 (Darling's numbering). */
    for(auto pair:{std::pair<int,unsigned>{SDL_BUTTON_MIDDLE,2},{SDL_BUTTON_X1,8},{SDL_BUTTON_X2,9}}) {
        SDL_Event click{};click.type=SDL_MOUSEBUTTONDOWN;click.button.windowID=id;click.button.button=pair.first;
        translate(click);
        assert(poll(&event) && event.type==MW_DOWN && event.button==pair.second);
        click.type=SDL_MOUSEBUTTONUP;translate(click);
        assert(poll(&event) && event.type==MW_UP && event.button==pair.second);
    }
    SDL_Event text{};text.type=SDL_TEXTINPUT;text.text.windowID=id;
    std::snprintf(text.text.text,sizeof text.text.text,"%s","é🙂");translate(text);
    assert(poll(&event) && event.type==MW_TEXT && !std::strcmp(event.text,"é🙂"));
    SDL_Event blur{};blur.type=SDL_WINDOWEVENT;blur.window.windowID=id;
    blur.window.event=SDL_WINDOWEVENT_FOCUS_LOST;translate(blur);
    bool released_a=false,released_ctrl=false,blurred=false;
    while(poll(&event)) {
        if(event.type==MW_KEY_UP && event.key==0)released_a=true;
        if(event.type==MW_KEY_UP && event.key==62)released_ctrl=true;
        if(event.type==MW_BLUR){assert(!event.modifiers);blurred=true;}
    }
    assert(released_a && released_ctrl && blurred);
    puts("PASS: Wayland physical modifiers, queued snapshots, Unicode/navigation, extra keys and buttons, repeats and focus releases");
}

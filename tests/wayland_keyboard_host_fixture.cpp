/* Test-only helper exports. Never linked into the installed helper. */
#include "../wayland_host.cpp"
extern "C" void quadra_wayland_keyboard_fixture(unsigned id,int scenario) {
    sync([=]{
        auto key=[=](SDL_Scancode scan,SDL_Keycode symbol,SDL_Keymod mods,bool down=true,bool repeat=false) {
            SDL_Event event{};event.type=down?SDL_KEYDOWN:SDL_KEYUP;event.key.windowID=id;
            event.key.keysym.scancode=scan;event.key.keysym.sym=symbol;event.key.keysym.mod=mods;
            event.key.repeat=repeat;translate(event);
        };
        auto text=[=](const char *value) {
            SDL_Event event{};event.type=SDL_TEXTINPUT;event.text.windowID=id;
            std::snprintf(event.text.text,sizeof event.text.text,"%s",value);translate(event);
        };
        auto focus=[=](bool active) {
            SDL_Event event{};event.type=SDL_WINDOWEVENT;event.window.windowID=id;
            event.window.event=active?SDL_WINDOWEVENT_FOCUS_GAINED:SDL_WINDOWEVENT_FOCUS_LOST;translate(event);
        };
        auto ctrl=[&](SDL_Scancode scan,SDL_Keycode symbol) {
            key(SDL_SCANCODE_LCTRL,SDLK_LCTRL,KMOD_LCTRL);
            key(scan,symbol,KMOD_LCTRL);key(scan,symbol,KMOD_LCTRL,false);
            key(SDL_SCANCODE_LCTRL,SDLK_LCTRL,KMOD_NONE,false);
        };
        auto button=[=](unsigned number,bool down) {
            SDL_Event event{};event.type=down?SDL_MOUSEBUTTONDOWN:SDL_MOUSEBUTTONUP;
            event.button.windowID=id;event.button.button=number;event.button.clicks=1;translate(event);
        };
        auto motion=[=](int dx,int dy) {
            SDL_Event event{};event.type=SDL_MOUSEMOTION;event.motion.windowID=id;
            event.motion.xrel=dx;event.motion.yrel=dy;translate(event);
        };
        SDL_SetModState(KMOD_NONE); // final batch state must not erase snapshots
        switch(scenario) {
        case 1:key(SDL_SCANCODE_A,SDLK_a,KMOD_NONE);text("a");key(SDL_SCANCODE_A,SDLK_a,KMOD_NONE,false);break;
        case 2:
            for(int i=0;i<3;i++){key(SDL_SCANCODE_A,SDLK_a,KMOD_LSHIFT,true,i!=0);text("A");}
            key(SDL_SCANCODE_A,SDLK_a,KMOD_NONE,false);break;
        case 3:
            key(SDL_SCANCODE_APOSTROPHE,SDLK_QUOTE,KMOD_NONE);
            key(SDL_SCANCODE_APOSTROPHE,SDLK_QUOTE,KMOD_NONE,false);
            text("é🙂");break;
        case 4:
            key(SDL_SCANCODE_LCTRL,SDLK_LCTRL,KMOD_LCTRL);
            key(SDL_SCANCODE_A,SDLK_a,KMOD_LCTRL);key(SDL_SCANCODE_A,SDLK_a,KMOD_LCTRL,false);
            key(SDL_SCANCODE_LCTRL,SDLK_LCTRL,KMOD_NONE,false);
            key(SDL_SCANCODE_X,SDLK_x,KMOD_NONE);text("x");key(SDL_SCANCODE_X,SDLK_x,KMOD_NONE,false);break;
        case 5:key(SDL_SCANCODE_BACKSPACE,SDLK_BACKSPACE,KMOD_NONE);key(SDL_SCANCODE_BACKSPACE,SDLK_BACKSPACE,KMOD_NONE,false);break;
        case 6:key(SDL_SCANCODE_LCTRL,SDLK_LCTRL,KMOD_LCTRL);key(SDL_SCANCODE_RCTRL,SDLK_RCTRL,KMOD_CTRL);break;
        case 7:key(SDL_SCANCODE_LCTRL,SDLK_LCTRL,KMOD_RCTRL,false);break;
        case 8:focus(false);break;
        case 9:focus(true);break;
        case 10:
            key(SDL_SCANCODE_TAB,SDLK_TAB,KMOD_NONE);key(SDL_SCANCODE_TAB,SDLK_TAB,KMOD_NONE,false);
            key(SDL_SCANCODE_B,SDLK_b,KMOD_NONE);text("b");key(SDL_SCANCODE_B,SDLK_b,KMOD_NONE,false);break;
        case 11:
            key(SDL_SCANCODE_LEFT,SDLK_LEFT,KMOD_NONE);key(SDL_SCANCODE_LEFT,SDLK_LEFT,KMOD_NONE,false);break;
        case 12:ctrl(SDL_SCANCODE_A,SDLK_a);ctrl(SDL_SCANCODE_C,SDLK_c);break;
        case 13:ctrl(SDL_SCANCODE_X,SDLK_x);break;
        case 14:ctrl(SDL_SCANCODE_V,SDLK_v);break;
        case 15:ctrl(SDL_SCANCODE_LEFT,SDLK_LEFT);break;
        case 16:ctrl(SDL_SCANCODE_RIGHT,SDLK_RIGHT);break;
        case 17:ctrl(SDL_SCANCODE_BACKSPACE,SDLK_BACKSPACE);break;
        case 18:
            focus(true);button(3,true);windows.at(id).requested_capture=true;capture(windows.at(id),id,true);
            button(1,true);motion(7,-9);break;
        case 19:button(1,false);motion(3,4);break;
        case 20:button(3,false);capture(windows.at(id),id,false);motion(1,2);break;
        case 21:
            button(1,true);button(3,true);windows.at(id).requested_capture=true;capture(windows.at(id),id,true);motion(7,-9);break;
        case 22:button(3,false);capture(windows.at(id),id,false);motion(3,4);break;
        case 23:button(1,false);motion(1,2);break;
        case 24:focus(false);focus(true);break;
        case 25:focus(false);break;
        case 26:focus(true);break;
        }
    });
}

/* GPL-3.0-only. Authored native Wayland presentation/occlusion/resize qualification.
 * No client, game assets, shaders, account data or settings are used. */
#define _GNU_SOURCE
#include "../prototype/metal-vulkan/quadra_metal.h"
#include "xdg-shell-client-protocol.h"
#include <wayland-client.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <poll.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

static const qm_api *api;
#define CHECK(c) do { if (!(c)) { fprintf(stderr,"FAIL %d %s: %s\n",__LINE__,#c,api?api->last_error():"Wayland setup");exit(1); } } while(0)
static struct wl_display *display;
static struct wl_compositor *compositor;
static struct wl_subcompositor *subcompositor;
static struct wl_shm *shm;
static struct xdg_wm_base *shell;
static struct wl_surface *parent, *cover;
static struct wl_buffer *background, *cover_buffer;
static atomic_int stopping, phase;
static double started;
enum { VISIBLE, COVERED, RESTORED, RESIZED, PHASES };
static const char *phase_names[PHASES]={"visible","covered","restored","resized"};
static const double phase_seconds=2.5;

static double now(void) {
    struct timespec t; CHECK(!clock_gettime(CLOCK_MONOTONIC,&t));
    return (double)t.tv_sec+(double)t.tv_nsec/1e9;
}
static void ping(void *data,struct xdg_wm_base *base,uint32_t serial) {
    (void)data;xdg_wm_base_pong(base,serial);
}
static const struct xdg_wm_base_listener shell_listener={.ping=ping};
static void registry_global(void *data,struct wl_registry *registry,uint32_t name,const char *interface,uint32_t version) {
    (void)data;
    if(!strcmp(interface,"wl_compositor"))compositor=wl_registry_bind(registry,name,&wl_compositor_interface,version<4?version:4);
    else if(!strcmp(interface,"wl_subcompositor"))subcompositor=wl_registry_bind(registry,name,&wl_subcompositor_interface,1);
    else if(!strcmp(interface,"wl_shm"))shm=wl_registry_bind(registry,name,&wl_shm_interface,1);
    else if(!strcmp(interface,"xdg_wm_base")) {
        shell=wl_registry_bind(registry,name,&xdg_wm_base_interface,1);
        xdg_wm_base_add_listener(shell,&shell_listener,NULL);
    }
}
static void registry_remove(void *data,struct wl_registry *registry,uint32_t name) {
    (void)data;(void)registry;(void)name;
}
static const struct wl_registry_listener registry_listener={registry_global,registry_remove};
static void configured(void *data,struct xdg_surface *surface,uint32_t serial) {
    (void)data;xdg_surface_ack_configure(surface,serial);
}
static const struct xdg_surface_listener surface_listener={.configure=configured};
static void top_configure(void *data,struct xdg_toplevel *top,int32_t width,int32_t height,struct wl_array *states) {
    (void)data;(void)top;(void)width;(void)height;(void)states;
}
static void top_close(void *data,struct xdg_toplevel *top) {
    (void)data;(void)top;atomic_store(&stopping,1);
}
static const struct xdg_toplevel_listener top_listener={.configure=top_configure,.close=top_close};

static struct wl_buffer *solid_buffer(uint32_t color) {
    enum { WIDTH=384,HEIGHT=256,BYTES=WIDTH*HEIGHT*4 };
    int descriptor=memfd_create("quadram2vk-authored-background",MFD_CLOEXEC);CHECK(descriptor>=0);
    CHECK(!ftruncate(descriptor,BYTES));
    uint32_t *memory=mmap(NULL,BYTES,PROT_READ|PROT_WRITE,MAP_SHARED,descriptor,0);CHECK(memory!=MAP_FAILED);
    for(unsigned i=0;i<WIDTH*HEIGHT;i++)memory[i]=color;
    struct wl_shm_pool *pool=wl_shm_create_pool(shm,descriptor,BYTES);CHECK(pool);
    struct wl_buffer *buffer=wl_shm_pool_create_buffer(pool,0,WIDTH,HEIGHT,WIDTH*4,WL_SHM_FORMAT_XRGB8888);CHECK(buffer);
    wl_shm_pool_destroy(pool);close(descriptor);munmap(memory,BYTES);
    return buffer;
}
static void opaque(struct wl_surface *surface) {
    struct wl_region *region=wl_compositor_create_region(compositor);CHECK(region);
    wl_region_add(region,0,0,384,256);wl_surface_set_opaque_region(surface,region);wl_region_destroy(region);
}
static void set_phase(int next) {
    if(next==COVERED) {
        wl_surface_attach(cover,cover_buffer,0,0);wl_surface_damage(cover,0,0,384,256);wl_surface_commit(cover);
    } else if(next==RESTORED) {
        wl_surface_attach(cover,NULL,0,0);wl_surface_commit(cover);
    }
    atomic_store(&phase,next);
}
static void *events(void *unused) {
    (void)unused;
    while(!atomic_load(&stopping)) {
        int next=(int)((now()-started)/phase_seconds);
        if(next>=PHASES)break;
        if(next!=atomic_load(&phase))set_phase(next);
        while(wl_display_prepare_read(display)) {
            if(wl_display_dispatch_pending(display)<0) {atomic_store(&stopping,1);return NULL;}
        }
        wl_display_flush(display);
        struct pollfd descriptor={.fd=wl_display_get_fd(display),.events=POLLIN};
        int ready=poll(&descriptor,1,10);
        if(ready>0 && (descriptor.revents&POLLIN)) {
            if(wl_display_read_events(display)<0) {atomic_store(&stopping,1);return NULL;}
            if(wl_display_dispatch_pending(display)<0) {atomic_store(&stopping,1);return NULL;}
        } else wl_display_cancel_read(display);
    }
    atomic_store(&stopping,1);return NULL;
}

struct observations {unsigned attempts,frames,timeouts,slow;double total_ms,max_ms;};
static void render(void *queue,void *drawable,void *texture) {
    void *command=api->command_buffer_new(queue);CHECK(command);
    qm_render_pass_desc pass={0};pass.color[0].texture=texture;pass.color[0].load_action=2;pass.color[0].store_action=1;
    pass.color[0].clear[0]=0.15;pass.color[0].clear[1]=0.4;pass.color[0].clear[2]=0.8;pass.color[0].clear[3]=1;
    pass.render_target_array_length=1;pass.default_raster_sample_count=1;
    void *encoder=api->render_encoder_new(command,&pass);CHECK(encoder);
    CHECK(api->render_end(encoder));api->release(encoder);
    CHECK(api->command_buffer_present(command,drawable));CHECK(api->command_buffer_commit(command));
    api->release(drawable);api->release(texture);
    CHECK(api->command_buffer_wait(command)==QM_STATUS_COMPLETED);api->release(command);
}

int main(int argc,char **argv) {
    CHECK(argc==2);
    void *library=dlopen(argv[1],RTLD_NOW|RTLD_LOCAL);CHECK(library);
    qm_api_entry entry=(qm_api_entry)dlsym(library,QM_API_SYMBOL);CHECK(entry);
    api=entry(QM_API_VERSION);CHECK(api && api->size==sizeof(qm_api));
    display=wl_display_connect(NULL);CHECK(display);
    struct wl_registry *registry=wl_display_get_registry(display);CHECK(registry);
    wl_registry_add_listener(registry,&registry_listener,NULL);CHECK(wl_display_roundtrip(display)>=0);
    CHECK(compositor && subcompositor && shm && shell);
    parent=wl_compositor_create_surface(compositor);CHECK(parent);
    struct xdg_surface *xdg=xdg_wm_base_get_xdg_surface(shell,parent);CHECK(xdg);
    xdg_surface_add_listener(xdg,&surface_listener,NULL);
    struct xdg_toplevel *top=xdg_surface_get_toplevel(xdg);CHECK(top);
    xdg_toplevel_add_listener(top,&top_listener,NULL);
    xdg_toplevel_set_title(top,"QuadraM2VK presentation qualification");
    xdg_toplevel_set_app_id(top,"org.quadrahq.Quadra.PresentationTest");
    wl_surface_commit(parent);CHECK(wl_display_roundtrip(display)>=0);
    background=solid_buffer(0xff203040);cover_buffer=solid_buffer(0xff809080);
    wl_surface_attach(parent,background,0,0);opaque(parent);wl_surface_damage(parent,0,0,384,256);wl_surface_commit(parent);
    struct wl_surface *child=wl_compositor_create_surface(compositor);CHECK(child);
    struct wl_subsurface *role=wl_subcompositor_get_subsurface(subcompositor,child,parent);CHECK(role);
    wl_subsurface_set_desync(role);wl_subsurface_set_position(role,0,0);opaque(child);
    cover=wl_compositor_create_surface(compositor);CHECK(cover);
    struct wl_subsurface *cover_role=wl_subcompositor_get_subsurface(subcompositor,cover,parent);CHECK(cover_role);
    wl_subsurface_set_desync(cover_role);wl_subsurface_place_above(cover_role,child);opaque(cover);
    wl_surface_commit(parent);CHECK(wl_display_roundtrip(display)>=0);
    void *device=api->device_create(NULL);CHECK(device);
    void *queue=api->queue_new_with_limit(device,8);CHECK(queue);
    qm_surface_target target={.kind=QM_SURFACE_WAYLAND,.wl_display=display,.wl_surface=child};
    void *surface=api->surface_new(device,&target);CHECK(surface);
    qm_surface_config config={.width=320,.height=240,.drawable_width=320,.drawable_height=240,.pixel_format=80,
        .display_sync=1,.maximum_drawable_count=3,.framebuffer_only=1,.visible=1};
    CHECK(api->surface_configure(surface,&config));
    struct observations observations[PHASES]={0};
    started=now();pthread_t thread;CHECK(!pthread_create(&thread,NULL,events,NULL));
    int resized=0;
    while(!atomic_load(&stopping)) {
        int stage=atomic_load(&phase);
        if(stage==RESIZED && !resized) {
            config.width=config.drawable_width=384;config.height=config.drawable_height=256;
            CHECK(api->surface_configure(surface,&config));resized=1;
        }
        double begin=now();void *texture=NULL,*drawable=api->surface_next_drawable(surface,&texture);
        double ms=(now()-begin)*1000;struct observations *row=&observations[stage];
        row->attempts++;row->total_ms+=ms;if(ms>row->max_ms)row->max_ms=ms;if(ms>100)row->slow++;
        if(drawable) {CHECK(texture);render(queue,drawable,texture);row->frames++;} else row->timeouts++;
        double remaining=1.0/120-(now()-begin);
        if(remaining>0) {struct timespec pause={0,(long)(remaining*1e9)};nanosleep(&pause,NULL);}
    }
    CHECK(!pthread_join(thread,NULL));
    qm_diagnostics_entry snapshot=(qm_diagnostics_entry)dlsym(library,QM_DIAGNOSTICS_SYMBOL);CHECK(snapshot);
    uint64_t size=snapshot(device,NULL,0);CHECK(size>1 && size<65536);
    char *json=malloc(size);CHECK(json && snapshot(device,json,size)==size);
    int passed=1;
    printf("{\"phases\":{");
    for(int i=0;i<PHASES;i++) {
        struct observations *row=&observations[i];
        if(row->frames<20 || row->timeouts || row->slow)passed=0;
        printf("%s\"%s\":{\"frames\":%u,\"attempts\":%u,\"acquire_timeouts\":%u,\"acquire_over_100ms\":%u,\"mean_acquire_ms\":%.6f,\"max_acquire_ms\":%.6f}",
            i?",":"",phase_names[i],row->frames,row->attempts,row->timeouts,row->slow,row->attempts?row->total_ms/row->attempts:0,row->max_ms);
    }
    printf("},\"nominal_phase_seconds\":%.1f,\"diagnostics\":%s,\"status\":\"%s\"}\n",phase_seconds,json,passed?"PASS":"SLOW");free(json);
    api->release(surface);api->release(queue);api->release(device);
    /* The compositor connection outlives any driver-owned surface retirement at process exit. */
    return passed?0:2;
}

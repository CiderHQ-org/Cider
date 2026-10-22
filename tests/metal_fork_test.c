/* Authored C ABI regressions: checked host transfers, exact dispatch, sticky failures,
 * and X11 WSI lifetime/cancellation. Run with a timeout and a private Xvfb display. */
#define _GNU_SOURCE
#include "../prototype/metal-vulkan/quadra_metal.h"
#include <X11/Xlib.h>
#include <dlfcn.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

static const qm_api *api;
#define CHECK(c) do { if (!(c)) { fprintf(stderr, "FAIL %d: %s: %s\n", __LINE__, #c, api ? api->last_error() : dlerror()); exit(1); } } while (0)

static void transfers(void *device) {
    const uint64_t formats[] = {125, 252, 70, 130, 134}; /* RGBA32F, Depth32F, RGBA8, BC1, BC3 */
    const uint64_t rows[] = {80, 32, 32, 24, 40}, spans[] = {304, 112, 112, 40, 72};
    for (unsigned f = 0; f < 5; f++) {
        unsigned w = f < 3 ? 4 : 7, h = f < 3 ? 4 : 5;
        qm_texture_desc desc = {.texture_type=2, .pixel_format=formats[f], .width=w, .height=h, .depth=1,
            .mipmap_level_count=1, .sample_count=1, .array_length=1, .usage=1};
        void *texture = api->texture_new(device, &desc);
        CHECK(texture);
        uint64_t span = 0;
        qm_size size = {w,h,1};
        CHECK(api->texture_copy_byte_length(texture, (qm_origin){0}, size, 0, 0, rows[f], 0, &span));
        CHECK(span == spans[f]);
        long page = sysconf(_SC_PAGESIZE);
        unsigned char *source_map = mmap(NULL, page*2, PROT_READ|PROT_WRITE, MAP_PRIVATE|MAP_ANONYMOUS, -1, 0);
        unsigned char *dest_map = mmap(NULL, page*2, PROT_READ|PROT_WRITE, MAP_PRIVATE|MAP_ANONYMOUS, -1, 0);
        CHECK(source_map != MAP_FAILED && dest_map != MAP_FAILED);
        CHECK(!mprotect(source_map+page, page, PROT_NONE) && !mprotect(dest_map+page, page, PROT_NONE));
        unsigned char *source = source_map + page - span, *dest = dest_map + page - span;
        memset(source, 0x37, span); memset(dest, 0xa5, span);
        CHECK(api->texture_replace_region(texture, (qm_origin){0}, size, 0, 0, source, rows[f], 0));
        CHECK(api->texture_get_bytes(texture, dest, span, rows[f], 0, (qm_origin){0}, size, 0, 0));
        unsigned copied_rows = f < 3 ? h : (h+3)/4;
        unsigned row_bytes = f == 0 ? 64 : f < 3 ? 16 : f == 3 ? 16 : 32;
        for (unsigned y=0; y<copied_rows; y++) CHECK(!memcmp(source+y*rows[f], dest+y*rows[f], row_bytes));
        CHECK(!api->texture_get_bytes(texture, dest, span-1, rows[f], 0, (qm_origin){0}, size, 0, 0));
        CHECK(!api->texture_replace_region(texture, (qm_origin){0}, size, 0, 0, NULL, rows[f], 0));
        CHECK(!api->texture_copy_byte_length(texture, (qm_origin){0}, size, 0, 0, UINT64_MAX, 0, &span));
        CHECK(api->texture_replace_region(texture, (qm_origin){0}, (qm_size){0,h,1}, 0, 0, NULL, rows[f], 0));
        CHECK(api->texture_get_bytes(texture, NULL, 0, rows[f], 0, (qm_origin){0}, (qm_size){0,h,1}, 0, 0));
        munmap(source_map,page*2); munmap(dest_map,page*2); api->release(texture);
    }
    puts("PASS: format-correct transfers at guard pages, null/empty and overflowing inputs");
}

static void dispatch(void *device, void *queue, const char *fixture) {
    FILE *file = fopen(fixture,"rb"); CHECK(file);
    CHECK(!fseek(file,0,SEEK_END)); long length=ftell(file); CHECK(length>0); rewind(file);
    void *data=malloc(length); CHECK(data && fread(data,1,length,file)==(size_t)length); fclose(file);
    void *library=api->library_new(device,data,length); free(data); CHECK(library);
    void *function=api->function_new(library,"dispatch_probe"); CHECK(function);
    void *pipeline=api->compute_pipeline_new(device,function,"authored dispatch regression"); CHECK(pipeline);
    void *output=api->buffer_new(device,512,0,NULL); CHECK(output);
    uint32_t *words=api->buffer_contents(output); CHECK(words);
    for (unsigned i=0;i<128;i++) words[i]=0xcafebabe;
    void *command=api->command_buffer_new(queue), *encoder=api->compute_encoder_new(command); CHECK(command && encoder);
    api->compute_set_pipeline(encoder,pipeline); api->compute_set_bytes(encoder,NULL,0,0); api->compute_set_buffer(encoder,output,0,0);
    api->compute_set_threadgroup_memory(encoder,256,0);
    api->compute_dispatch_threads(encoder,(qm_size){65,1,1},(qm_size){64,1,1});
    api->compute_barrier(encoder,1);
    void *fence=api->fence_new(device); CHECK(fence);
    api->encoder_fence(encoder,fence,1,3);
    CHECK(api->compute_end(encoder)); api->release(encoder);
    encoder=api->blit_encoder_new(command); CHECK(encoder); api->encoder_fence(encoder,fence,0,3);
    CHECK(api->blit_end(encoder)); api->release(encoder);
    CHECK(api->command_buffer_commit(command));
    CHECK(api->command_buffer_wait_scheduled(command)>=QM_STATUS_SCHEDULED);
    CHECK(api->command_buffer_wait(command)==QM_STATUS_COMPLETED);
    for (unsigned i=0;i<128;i++) CHECK(words[i] == (i<65 ? i+1 : 0xcafebabe));
    api->release(command);
    command=api->command_buffer_new(queue); encoder=api->compute_encoder_new(command); CHECK(command && encoder);
    api->compute_set_pipeline(encoder,pipeline);
    api->compute_set_buffer(encoder,output,0,31); /* a refused Metal buffer slot */
    api->compute_barrier(encoder,UINT32_MAX); /* must not replace the first failure */
    CHECK(api->compute_end(encoder)); api->release(encoder);
    CHECK(!api->command_buffer_commit(command));
    CHECK(strstr(api->last_error(),"setBuffer"));
    CHECK(api->command_buffer_status(command)==QM_STATUS_ERROR);
    CHECK(api->command_buffer_wait(command)==QM_STATUS_ERROR);
    CHECK(api->command_buffer_wait_scheduled(command)==QM_STATUS_ERROR);
    api->release(command);
    command=api->command_buffer_new(queue); encoder=api->compute_encoder_new(command); CHECK(command && encoder);
    CHECK(!api->command_buffer_commit(command)); /* runtime refusal: encoder still open */
    CHECK(api->command_buffer_status(command)==QM_STATUS_ERROR);
    CHECK(api->command_buffer_wait(command)==QM_STATUS_ERROR);
    CHECK(api->command_buffer_wait_scheduled(command)==QM_STATUS_ERROR);
    CHECK(api->compute_end(encoder)); api->release(encoder); api->release(command);
    api->release(fence); api->release(output); api->release(pipeline); api->release(function); api->release(library);
    puts("PASS: exactly 65 invocations, dynamic threadgroup memory, fence forwarding, scheduled wait and rejected command status");
}

static void bulk_bindings(void *device, void *queue) {
    qm_texture_desc desc={.texture_type=2,.pixel_format=70,.width=4,.height=4,.depth=1,
        .mipmap_level_count=1,.sample_count=1,.array_length=1,.usage=4,.resource_options=2<<4};
    void *target=api->texture_new(device,&desc),*buffer=api->buffer_new(device,64,0,NULL); CHECK(target&&buffer);
    desc.usage=1; void *texture=api->texture_new(device,&desc); CHECK(texture);
    qm_sampler_desc sd={.max_anisotropy=1,.normalized_coordinates=1,.lod_max_clamp=16};
    void *sampler=api->sampler_new(device,&sd); CHECK(sampler);
    void *buffers[31],*textures[128],*samplers[16]; uint64_t offsets[31]={0};
    for (unsigned i=0;i<31;i++) buffers[i]=buffer;
    for (unsigned i=0;i<128;i++) textures[i]=texture;
    for (unsigned i=0;i<16;i++) samplers[i]=sampler;
    void *command=api->command_buffer_new(queue); CHECK(command);
    qm_render_pass_desc pass={0}; pass.color[0].texture=target; pass.color[0].load_action=2; pass.color[0].store_action=1;
    pass.color[0].clear[0]=1; pass.color[0].clear[2]=1; pass.color[0].clear[3]=1;
    pass.render_target_array_length=1; pass.default_raster_sample_count=1;
    void *encoder=api->render_encoder_new(command,&pass); CHECK(encoder);
    for (int stage=0;stage<2;stage++) {
        api->render_set_buffers(encoder,stage,buffers,offsets,0,31);
        api->render_set_textures(encoder,stage,textures,0,128);
        api->render_set_samplers(encoder,stage,samplers,0,16);
        api->render_set_buffers(encoder,stage,NULL,NULL,31,0);
        api->render_set_textures(encoder,stage,NULL,128,0);
        api->render_set_samplers(encoder,stage,NULL,16,0);
    }
    api->encoder_use_resource(encoder,texture,1,3);
    api->render_barrier(encoder,1,1,2);
    CHECK(api->render_end(encoder)); api->release(encoder);
    encoder=api->blit_encoder_new(command); CHECK(encoder);
    api->blit_copy_texture_to_buffer(encoder,target,0,0,(qm_origin){0},(qm_size){4,4,1},buffer,0,16,64);
    CHECK(api->blit_end(encoder)); api->release(encoder);
    CHECK(api->command_buffer_commit(command)); CHECK(api->command_buffer_wait(command)==QM_STATUS_COMPLETED);
    const unsigned char *pixels=api->buffer_contents(buffer);
    for (unsigned i=0;i<64;i+=4) CHECK(pixels[i]==255&&pixels[i+1]==0&&pixels[i+2]==255&&pixels[i+3]==255);
    api->release(command);
    command=api->command_buffer_new(queue); encoder=api->render_encoder_new(command,&pass); CHECK(command&&encoder);
    api->render_set_buffers(encoder,0,NULL,NULL,UINT32_MAX,2);
    CHECK(api->render_end(encoder)); api->release(encoder);
    CHECK(!api->command_buffer_commit(command)); CHECK(api->command_buffer_wait(command)==QM_STATUS_ERROR);
    api->release(command); api->release(sampler); api->release(texture); api->release(buffer); api->release(target);
    puts("PASS: bulk buffer/texture/sampler ABI ranges, residency and render barrier forwarding");
}

static void clear_present(void *queue, void *drawable, void *texture) {
    void *command=api->command_buffer_new(queue); CHECK(command);
    qm_render_pass_desc pass={0};
    pass.color[0].texture=texture; pass.color[0].load_action=2; pass.color[0].store_action=1;
    pass.color[0].clear[0]=0.25; pass.color[0].clear[2]=0.75; pass.color[0].clear[3]=1;
    pass.render_target_array_length=1; pass.default_raster_sample_count=1;
    void *encoder=api->render_encoder_new(command,&pass); CHECK(encoder);
    CHECK(api->render_end(encoder)); api->release(encoder);
    CHECK(api->command_buffer_present(command,drawable)); CHECK(api->command_buffer_commit(command));
    api->release(drawable); api->release(texture); /* only the GPU/presenter hold their image now */
    CHECK(api->command_buffer_wait(command)==QM_STATUS_COMPLETED); api->release(command);
}

static void surfaces(void *device, void *queue) {
    CHECK(XInitThreads()); Display *display=XOpenDisplay(NULL); CHECK(display);
    Window window=XCreateSimpleWindow(display,DefaultRootWindow(display),0,0,64,64,0,0,0); CHECK(window);
    XMapWindow(display,window); XSync(display,False);
    qm_surface_target target={.kind=QM_SURFACE_X11,.x11_parent=window};
    void *surface=api->surface_new(device,&target); CHECK(surface);
    qm_surface_config config={.width=64,.height=64,.drawable_width=64,.drawable_height=64,.pixel_format=80,
        .display_sync=0,.maximum_drawable_count=3,.framebuffer_only=1,.visible=1};
    CHECK(api->surface_configure(surface,&config));
    for (unsigned i=0;i<24;i++) {
        void *texture=NULL, *drawable=api->surface_next_drawable(surface,&texture); CHECK(drawable && texture);
        /* Release without presenting: repeatedly exercising chain cancellation must not exhaust images. */
        if (i%3==0) { api->release(drawable); api->release(texture); }
        else clear_present(queue,drawable,texture);
        if (i==8 || i==16) {
            config.width+=8; config.drawable_width+=8;
            CHECK(api->surface_configure(surface,&config));
        }
    }
    void *texture=NULL,*drawable=api->surface_next_drawable(surface,&texture); CHECK(drawable && texture);
    api->release(surface); api->release(drawable); /* image ownership must keep the external surface alive */
    qm_texture_desc desc={0}; api->texture_describe(texture,&desc); CHECK(desc.width>0); api->release(texture);
    XDestroyWindow(display,window); XCloseDisplay(display);
    puts("PASS: X11 present, unused drawable cancellation, resize and surface/image lifetime");
}

int main(int argc,char **argv) {
    CHECK(argc==3 || (argc==4 && !strcmp(argv[3],"--offscreen"))); void *library=dlopen(argv[1],RTLD_NOW|RTLD_LOCAL); CHECK(library);
    qm_api_entry entry=(qm_api_entry)dlsym(library,QM_API_SYMBOL); CHECK(entry);
    api=entry(QM_API_VERSION); CHECK(api && api->size==sizeof(qm_api));
    void *device=api->device_create(NULL); CHECK(device);
    void *queue=api->queue_new_with_limit(device,32); CHECK(queue);
    transfers(device); dispatch(device,queue,argv[2]); bulk_bindings(device,queue);
    if (argc==3) surfaces(device,queue); else puts("SKIP: display-server presentation (--offscreen)");
    api->release(queue); api->release(device); return 0;
}

/* Authored pipeline preload, live allocation and GPU-retention regressions. */
#define _POSIX_C_SOURCE 200809L
#include "../prototype/metal-vulkan/quadra_metal.h"
#include <dlfcn.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static const qm_api *api;
static qm_diagnostics_entry diagnostics;
_Static_assert(offsetof(qm_api,library_new)==8+18*sizeof(void*),"launcher's ABI 2 library prefix");
#define CHECK(c) do { if (!(c)) { fprintf(stderr,"FAIL %d %s: %s\n",__LINE__,#c,api?api->last_error():dlerror());exit(1); } } while(0)

static void snapshot(void *device, const char *name) {
    uint64_t length=diagnostics(device,NULL,0); CHECK(length>1 && length<65536);
    char *bytes=malloc(length); CHECK(bytes);
    memset(bytes,'?',length);
    CHECK(diagnostics(device,bytes,length-1)==length && bytes[0]=='?');
    CHECK(diagnostics(device,bytes,length)==length && !bytes[length-1]);
    printf("%s %s\n",name,bytes); free(bytes);
}

static void *library(void *device,const char *path) {
    FILE *file=fopen(path,"rb"); CHECK(file);
    CHECK(!fseek(file,0,SEEK_END)); long size=ftell(file); CHECK(size>0); rewind(file);
    void *bytes=malloc(size); CHECK(bytes && fread(bytes,1,size,file)==(size_t)size); fclose(file);
    void *result=api->library_new(device,bytes,size); free(bytes); CHECK(result); return result;
}

static void memory(void *device) {
    uint64_t baseline=api->device_current_allocated_size(device);
    for (unsigned i=0;i<32;i++) {
        void *buffer=api->buffer_new(device,1<<20,0,NULL); CHECK(buffer);
        CHECK(api->device_current_allocated_size(device)>=baseline+(1<<20));
        api->release(buffer);
        CHECK(api->device_current_allocated_size(device)==baseline);
    }
    void *other=api->device_create(NULL); CHECK(other);
    uint64_t other_baseline=api->device_current_allocated_size(other);
    void *buffer=api->buffer_new(device,1<<20,0,NULL); CHECK(buffer);
    CHECK(api->device_current_allocated_size(other)==other_baseline);
    api->release(buffer); api->release(other);
    qm_texture_desc desc={.texture_type=2,.pixel_format=125,.width=16,.height=16,.depth=1,
        .mipmap_level_count=1,.sample_count=1,.array_length=1,.usage=1,.resource_options=2<<4};
    void *texture=api->texture_new(device,&desc); CHECK(texture);
    uint64_t allocated=api->device_current_allocated_size(device);
    CHECK(allocated>=baseline+16*16*16);
    void *view=api->texture_view(texture,125,2,0,1,0,1); CHECK(view);
    CHECK(api->device_current_allocated_size(device)==allocated);
    api->release(texture); CHECK(api->device_current_allocated_size(device)==allocated);
    api->release(view); CHECK(api->device_current_allocated_size(device)==baseline);
    puts("PASS: repeated releases, per-device allocation isolation and shared texture-view ownership");
}

int main(int argc,char **argv) {
    CHECK(argc==4 || (argc==5 && !strcmp(argv[4],"--many-pipelines")));
    const unsigned extra_count=argc==5?96:0;
    void *host=dlopen(argv[1],RTLD_NOW|RTLD_LOCAL); CHECK(host);
    qm_api_entry entry=(qm_api_entry)dlsym(host,QM_API_SYMBOL); CHECK(entry);
    api=entry(QM_API_VERSION); CHECK(api && api->size==sizeof(qm_api));
    diagnostics=(qm_diagnostics_entry)dlsym(host,QM_DIAGNOSTICS_SYMBOL); CHECK(diagnostics);
    qm_preload_device_entry preload=(qm_preload_device_entry)dlsym(host,QM_PRELOAD_DEVICE_SYMBOL); CHECK(preload);
    CHECK(preload(NULL,NULL,NULL,1)==-1);
    void *device=api->device_create(NULL); CHECK(device);
    memory(device); snapshot(device,"BEFORE");
    void *queue=api->queue_new_with_limit(device,8); CHECK(queue);
    void *render_library=library(device,argv[2]),*compute_library=library(device,argv[3]);
    void *vertex=api->function_new(render_library,"bench_vertex");
    void *fragment=api->function_new(render_library,"bench_fragment");
    void *kernel=api->function_new(compute_library,"dispatch_probe"); CHECK(vertex&&fragment&&kernel);
    qm_render_pipeline_desc desc={0}; desc.vertex_function=vertex;desc.fragment_function=fragment;
    desc.color[0].pixel_format=70;desc.color[0].write_mask=15;desc.sample_count=1;desc.rasterization_enabled=1;
    void *render=api->render_pipeline_new(device,&desc),*compute=api->compute_pipeline_new(device,kernel,"authored preload"); CHECK(render&&compute);
    /* Distinct legal blend/write states exceed the old 64-state residency limit. Keep the
     * application's states alive through the snapshot so weak-cache eviction cannot mask reuse. */
    void *extra[96]={0};
    for(unsigned i=0;i<extra_count;i++) {
        qm_render_pipeline_desc variant=desc;
        variant.color[0].blending_enabled=1;
        variant.color[0].write_mask=i%16;
        variant.color[0].source_rgb=1;
        variant.color[0].destination_rgb=i/16;
        variant.color[0].source_alpha=1;
        extra[i]=api->render_pipeline_new(device,&variant); CHECK(extra[i]);
    }
    snapshot(device,"CREATED");
    for(unsigned i=0;i<extra_count;i++) api->release(extra[i]);
    qm_texture_desc td={.texture_type=2,.pixel_format=70,.width=8,.height=8,.depth=1,
        .mipmap_level_count=1,.sample_count=1,.array_length=1,.usage=4,.resource_options=2<<4};
    void *texture=api->texture_new(device,&td); CHECK(texture);
    qm_texture_desc upload_td=td; upload_td.resource_options=0;
    void *upload_texture=api->texture_new(device,&upload_td); CHECK(upload_texture);
    unsigned char uploaded[8*8*4],copied[sizeof uploaded];
    for(unsigned i=0;i<sizeof uploaded;i++) uploaded[i]=(unsigned char)(i*7);
    CHECK(api->texture_replace_region(upload_texture,(qm_origin){0},(qm_size){8,8,1},0,0,uploaded,32,sizeof uploaded));
    CHECK(api->texture_get_bytes(upload_texture,copied,sizeof copied,32,sizeof copied,(qm_origin){0},(qm_size){8,8,1},0,0));
    CHECK(!memcmp(uploaded,copied,sizeof copied));
    api->release(upload_texture);
    float one=1; void *constants=api->buffer_new(device,sizeof one,0,&one); CHECK(constants);
    void *readback=api->buffer_new(device,8*8*4,0,NULL); CHECK(readback);
    uint32_t input[128]; for (unsigned i=0;i<128;i++) input[i]=0xcafebabe;
    void *output=api->buffer_new(device,sizeof input,0,input); CHECK(output);
    void *command=api->command_buffer_new(queue); CHECK(command);
    qm_render_pass_desc pass={0}; pass.color[0].texture=texture;pass.color[0].load_action=2;pass.color[0].store_action=1;
    pass.render_target_array_length=1;pass.default_raster_sample_count=1;
    void *encoder=api->render_encoder_new(command,&pass); CHECK(encoder);
    api->render_set_pipeline(encoder,render);api->render_set_buffer(encoder,0,constants,0,0);
    const double viewport[6]={0,0,8,8,0,1};api->render_set_viewport(encoder,viewport);
    api->render_draw(encoder,3,0,3,1,0);CHECK(api->render_end(encoder));api->release(encoder);
    encoder=api->compute_encoder_new(command);CHECK(encoder);
    api->compute_set_pipeline(encoder,compute);api->compute_set_buffer(encoder,output,0,0);
    api->compute_set_threadgroup_memory(encoder,256,0);
    api->compute_dispatch_threads(encoder,(qm_size){65,1,1},(qm_size){64,1,1});
    CHECK(api->compute_end(encoder));api->release(encoder);
    encoder=api->blit_encoder_new(command);CHECK(encoder);
    api->blit_copy_texture_to_buffer(encoder,texture,0,0,(qm_origin){0},(qm_size){8,8,1},readback,0,32,8*8*4);
    CHECK(api->blit_end(encoder));api->release(encoder);
    /* Encoded work keeps these allocations live after the C wrappers go away. */
    uint64_t held=api->device_current_allocated_size(device);
    api->release(constants);api->release(render);api->release(compute);
    CHECK(api->device_current_allocated_size(device)>=held);
    CHECK(api->command_buffer_commit(command));CHECK(api->command_buffer_wait(command)==QM_STATUS_COMPLETED);
    const uint32_t *words=api->buffer_contents(output);CHECK(words);
    for(unsigned i=0;i<128;i++) CHECK(words[i]==(i<65?i+1:0xcafebabe));
    const unsigned char *pixels=api->buffer_contents(readback);CHECK(pixels);
    for(unsigned i=0;i<8*8*4;i+=4) CHECK(pixels[i]==255&&pixels[i+1]==0&&pixels[i+2]==255&&pixels[i+3]==255);
    api->release(command);api->release(output);api->release(readback);api->release(texture);
    api->release(vertex);api->release(fragment);api->release(kernel);api->release(render_library);api->release(compute_library);api->release(queue);
    snapshot(device,"AFTER"); api->release(device);
    puts("PASS: recorded/warmed render and compute states retain exact authored GPU output");
    return 0;
}

/* Same authored workload against the old ABI 1 bridge or the ABI 2 fork. Release builds only.
 * Timings report host-observed lavapipe costs, not a hardware GPU frame rate. */
#define _POSIX_C_SOURCE 200809L
#include "../prototype/metal-vulkan/quadra_metal.h"
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
static const qm_api *api;
#define CHECK(c) do { if (!(c)) { fprintf(stderr,"FAIL %d %s: %s\n",__LINE__,#c,api?api->last_error():dlerror());exit(1); } } while(0)
static double now(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t); return t.tv_sec+t.tv_nsec/1e9; }
static int cmp(const void *a,const void *b) { double x=*(const double *)a,y=*(const double *)b; return (x>y)-(x<y); }
static void report(const char *name,double *values,unsigned n) {
    double sorted[32]; CHECK(n<=32); memcpy(sorted,values,n*sizeof(double)); qsort(sorted,n,sizeof(double),cmp);
    printf("%s median_ms=%.6f min_ms=%.6f max_ms=%.6f samples=%u\n",name,(sorted[(n-1)/2]+sorted[n/2])*500,sorted[0]*1000,sorted[n-1]*1000,n);
}
static void *load_library(void *device,const char *path) {
    FILE *f=fopen(path,"rb"); CHECK(f); CHECK(!fseek(f,0,SEEK_END)); long n=ftell(f); CHECK(n>0); rewind(f);
    void *bytes=malloc(n); CHECK(bytes&&fread(bytes,1,n,f)==(size_t)n); fclose(f);
    void *library=api->library_new(device,bytes,n); free(bytes); CHECK(library); return library;
}
static void draws(void *device,void *queue,const char *path) {
    void *library=load_library(device,path);
    void *vertex=api->function_new(library,"bench_vertex"),*fragment=api->function_new(library,"bench_fragment"); CHECK(vertex&&fragment);
    qm_render_pipeline_desc desc={0}; desc.vertex_function=vertex; desc.fragment_function=fragment;
    desc.color[0].pixel_format=70; desc.color[0].write_mask=15; desc.sample_count=1; desc.rasterization_enabled=1;
    void *pipeline=api->render_pipeline_new(device,&desc); CHECK(pipeline);
    float one=1.0f; void *constants=api->buffer_new(device,4,0,&one); CHECK(constants);
    qm_texture_desc td={.texture_type=2,.pixel_format=70,.width=16,.height=16,.depth=1,.mipmap_level_count=1,.sample_count=1,.array_length=1,.usage=4,.resource_options=2<<4};
    void *texture=api->texture_new(device,&td),*readback=api->buffer_new(device,1024,0,NULL); CHECK(texture&&readback);
    double encoding[20],total[20];
    for (unsigned frame=0;frame<25;frame++) {
        double start=now(); void *command=api->command_buffer_new(queue); CHECK(command);
        qm_render_pass_desc pass={0}; pass.color[0].texture=texture; pass.color[0].load_action=2; pass.color[0].store_action=1; pass.color[0].clear[3]=1;
        pass.render_target_array_length=1; pass.default_raster_sample_count=1;
        void *encoder=api->render_encoder_new(command,&pass); CHECK(encoder); api->render_set_pipeline(encoder,pipeline);
        const double viewport[6]={0,0,16,16,0,1}; api->render_set_viewport(encoder,viewport);
        for (unsigned i=0;i<500;i++) { api->render_set_buffer(encoder,0,constants,0,0); api->render_draw(encoder,3,0,3,1,0); }
        CHECK(api->render_end(encoder)); api->release(encoder); double encoded=now()-start;
        encoder=api->blit_encoder_new(command); CHECK(encoder);
        api->blit_copy_texture_to_buffer(encoder,texture,0,0,(qm_origin){0},(qm_size){16,16,1},readback,0,64,1024);
        CHECK(api->blit_end(encoder)); api->release(encoder); CHECK(api->command_buffer_commit(command)); CHECK(api->command_buffer_wait(command)==QM_STATUS_COMPLETED);
        double elapsed=now()-start; const unsigned char *pixels=api->buffer_contents(readback);
        for (unsigned i=0;i<1024;i+=4) CHECK(pixels[i]==255&&pixels[i+1]==0&&pixels[i+2]==255&&pixels[i+3]==255);
        api->release(command); if (frame>=5) { encoding[frame-5]=encoded;total[frame-5]=elapsed; }
    }
    report("draw_500_encode",encoding,20);report("draw_500_submit_readback",total,20);
    api->release(readback);api->release(texture);api->release(constants);api->release(pipeline);api->release(fragment);api->release(vertex);api->release(library);
}
static void blocks(void *device,void *queue,uint64_t format,unsigned block) {
    const unsigned side=1024, row=(side/4)*block, logical=row*(side/4);
    /* The baseline ABI overstates the host slice as row*height; reserve that span in both runs. */
    unsigned char *source=malloc(row*side); CHECK(source);memset(source,0x37,row*side);
    void *readback=api->buffer_new(device,logical,0,NULL); CHECK(readback);double times[12];
    for(unsigned i=0;i<14;i++) {
        double start=now();qm_texture_desc desc={.texture_type=2,.pixel_format=format,.width=side,.height=side,.depth=1,.mipmap_level_count=1,.sample_count=1,.array_length=1,.usage=1};
        void *texture=api->texture_new(device,&desc); CHECK(texture);
        CHECK(api->texture_replace_region(texture,(qm_origin){0},(qm_size){side,side,1},0,0,source,row,0));
        void *command=api->command_buffer_new(queue),*encoder=api->blit_encoder_new(command); CHECK(command&&encoder);
        api->blit_copy_texture_to_buffer(encoder,texture,0,0,(qm_origin){0},(qm_size){side,side,1},readback,0,row,logical);
        CHECK(api->blit_end(encoder));api->release(encoder);CHECK(api->command_buffer_commit(command));CHECK(api->command_buffer_wait(command)==QM_STATUS_COMPLETED);
        CHECK(!memcmp(source,api->buffer_contents(readback),logical));api->release(command);api->release(texture);
        if (i>=2) times[i-2]=now()-start;
    }
    report(format==130?"bc1_1024_upload_readback":"bc5_1024_upload_readback",times,12);api->release(readback);free(source);
}
int main(int argc,char **argv) {
    CHECK(argc==3);void *dso=dlopen(argv[1],RTLD_NOW|RTLD_LOCAL);CHECK(dso);qm_api_entry entry=(qm_api_entry)dlsym(dso,QM_API_SYMBOL);CHECK(entry);
    api=entry(2);if(!api)api=entry(1);CHECK(api);void *device=api->device_create(NULL);CHECK(device);void *queue=api->queue_new(device);CHECK(queue);
    draws(device,queue,argv[2]);blocks(device,queue,130,8);blocks(device,queue,142,16);api->release(queue);api->release(device);return 0;
}

/* Optional GPU regression of the real C ABI, render clear, MSAA resolve and
 * texture-to-buffer readback. No compositor, account or Roblox client needed.
 * clang -O2 -Wall -Wextra tests/metal_host_test.c -ldl -o /tmp/metal-host-test
 * /tmp/metal-host-test build/metal/libquadra_metal_host.so
 */
#include "../prototype/metal-vulkan/quadra_metal.h"
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const qm_api *api;
#define CHECK(condition) do { if (!(condition)) { \
    fprintf(stderr, "FAIL line %d: %s: %s\n", __LINE__, #condition, api ? api->last_error() : dlerror()); \
    exit(1); \
} } while (0)

static void render_and_read(void *device, void *queue, unsigned samples) {
    enum { width = 16, height = 8, pitch = width * 4, bytes = pitch * height };
    qm_texture_desc desc = {
        .texture_type = 2, .pixel_format = 70, /* 2D RGBA8Unorm */
        .width = width, .height = height, .depth = 1,
        .mipmap_level_count = 1, .sample_count = 1, .array_length = 1,
        .usage = 4, .resource_options = 2 << 4, /* render target, private */
    };
    void *texture = api->texture_new(device, &desc);
    CHECK(texture);
    void *multisample = NULL;
    if (samples > 1) {
        desc.texture_type = 4; /* 2D multisample */
        desc.sample_count = samples;
        multisample = api->texture_new(device, &desc);
        CHECK(multisample);
    }
    void *readback = api->buffer_new(device, bytes, 0, NULL);
    CHECK(readback && api->buffer_length(readback) == bytes);
    memset(api->buffer_contents(readback), 0xcd, bytes);
    void *command = api->command_buffer_new(queue);
    CHECK(command);
    qm_render_pass_desc pass = {0};
    pass.color[0].texture = multisample ? multisample : texture;
    pass.color[0].resolve_texture = multisample ? texture : NULL;
    pass.color[0].load_action = 2; /* clear */
    pass.color[0].store_action = multisample ? 2 : 1; /* resolve / store */
    pass.color[0].clear[0] = 1.0;
    pass.color[0].clear[2] = 1.0;
    pass.color[0].clear[3] = 1.0;
    pass.render_target_array_length = 1;
    pass.default_raster_sample_count = samples;
    void *render = api->render_encoder_new(command, &pass);
    CHECK(render && api->render_end(render));
    api->release(render);
    void *blit = api->blit_encoder_new(command);
    CHECK(blit);
    api->blit_copy_texture_to_buffer(blit, texture, 0, 0, (qm_origin){0, 0, 0},
                                    (qm_size){width, height, 1}, readback, 0, pitch, bytes);
    CHECK(api->blit_end(blit));
    api->release(blit);
    CHECK(api->command_buffer_commit(command));
    CHECK(api->command_buffer_wait(command) == QM_STATUS_COMPLETED);
    const unsigned char *pixels = api->buffer_contents(readback);
    CHECK(pixels);
    for (unsigned i = 0; i < bytes; i += 4)
        CHECK(pixels[i] == 255 && pixels[i + 1] == 0 && pixels[i + 2] == 255 && pixels[i + 3] == 255);
    api->release(command);
    api->release(readback);
    api->release(multisample);
    api->release(texture);
    printf("PASS: %ux Metal render clear, resolve and exact GPU readback through C ABI\n", samples);
}

int main(int argc, char **argv) {
    CHECK(argc == 2);
    void *library = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    CHECK(library);
    qm_api_entry entry = (qm_api_entry)dlsym(library, QM_API_SYMBOL);
    CHECK(entry && !entry(QM_API_VERSION + 1));
    api = entry(QM_API_VERSION);
    CHECK(api && api->version == QM_API_VERSION && api->size == sizeof(qm_api));
    int (*check_air)(void) = (int (*)(void))dlsym(library, "quadra_metal_host_check_air");
    CHECK(check_air && check_air());
    void *device = api->device_create(NULL);
    CHECK(device);
    qm_device_info info = {0};
    api->device_info(device, &info);
    printf("Device: %s\n", info.name);
    const char *original_budget = getenv("QUADRA_VRAM_BYTES");
    char *saved_budget = original_budget ? strdup(original_budget) : NULL;
    setenv("QUADRA_VRAM_BYTES", "invalid", 1);
    api->device_info(device, &info);
    CHECK(info.recommended_max_working_set_size >= (64u << 20));
    CHECK(info.recommended_max_working_set_size <= (512u << 20));
    setenv("QUADRA_VRAM_BYTES", "134217728", 1);
    api->device_info(device, &info);
    CHECK(info.recommended_max_working_set_size <= (128u << 20));
    if (saved_budget) { setenv("QUADRA_VRAM_BYTES", saved_budget, 1); free(saved_budget); }
    else unsetenv("QUADRA_VRAM_BYTES");
    puts("PASS: Metal C ABI bounds malformed and explicit graphics budgets on the selected Vulkan device");
    void *queue = api->queue_new(device);
    CHECK(queue);
    render_and_read(device, queue, 1);
    if (api->device_supports_texture_sample_count(device, 4))
        render_and_read(device, queue, 4);
    api->release(queue);
    api->release(device);
    /* The runtime owns worker threads; keep its DSO loaded through exit. */
    return 0;
}

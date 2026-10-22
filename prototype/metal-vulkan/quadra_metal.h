/* Quadra's Metal on Vulkan: the ABI between the guest Metal.framework
 * (metal/framework, Mach-O inside Darling) and the host library
 * (metal/host, an ELF built on metal2vulkan-runtime).
 *
 * The guest opens libquadra_metal_host.so through Darling's _elfcalls and
 * asks it for this table once. Both sides are x86_64 System V code in one
 * process, so plain C structs and pointers cross unchanged. Every handle is
 * the host's: the guest keeps it inside its Objective-C object and gives it
 * back with qm_api.release when that object goes away. A call that fails
 * returns 0 or a null handle; qm_api.last_error then describes it (one
 * message per calling thread, valid until that thread's next failing call).
 *
 * The host never calls guest code: Metal's completion and scheduled blocks
 * run on guest threads, which wait for a command buffer with
 * command_buffer_wait. Host threads (the runtime's own, the presenter) only
 * run host code. Numeric Metal values (pixel formats, enums, option bits)
 * keep Metal's raw values. */
#ifndef QUADRA_METAL_H
#define QUADRA_METAL_H

#include <stdint.h>

#define QM_API_VERSION 2

typedef struct { uint64_t x, y, z; } qm_origin;
typedef struct { uint64_t width, height, depth; } qm_size;

typedef struct {
    uint64_t texture_type, pixel_format, width, height, depth;
    uint64_t mipmap_level_count, sample_count, array_length;
    uint64_t usage, resource_options;
    uint8_t framebuffer_only, allow_gpu_optimized_contents, pad[6];
} qm_texture_desc;

typedef struct {
    void *texture;
    uint64_t level, slice, depth_plane;
    void *resolve_texture;
    uint64_t resolve_level, resolve_slice, resolve_depth_plane;
    uint32_t load_action, store_action;
    /* Color: red, green, blue, alpha. Depth: clear[0]. Stencil: clear[0]. */
    double clear[4];
} qm_attachment;

typedef struct {
    qm_attachment color[8];
    qm_attachment depth, stencil;
    void *visibility_result_buffer;
    uint64_t render_target_width, render_target_height;
    uint64_t render_target_array_length, default_raster_sample_count;
} qm_render_pass_desc;

#define QM_VERTEX_SLOTS 31

typedef struct { uint32_t present, format, offset, buffer_index; } qm_vertex_attribute;
typedef struct { uint32_t present, stride, step_function, step_rate; } qm_vertex_layout;

typedef struct {
    uint64_t pixel_format;
    uint32_t blending_enabled, write_mask;
    uint32_t source_rgb, destination_rgb, rgb_operation;
    uint32_t source_alpha, destination_alpha, alpha_operation;
} qm_color_attachment_state;

typedef struct {
    void *vertex_function, *fragment_function;
    uint32_t has_vertex_descriptor, pad;
    qm_vertex_attribute attributes[QM_VERTEX_SLOTS];
    qm_vertex_layout layouts[QM_VERTEX_SLOTS];
    qm_color_attachment_state color[8];
    uint64_t depth_format, stencil_format;
    uint32_t sample_count, alpha_to_coverage, alpha_to_one, rasterization_enabled;
    uint32_t input_primitive_topology, pad2;
    const char *label;
} qm_render_pipeline_desc;

typedef struct {
    uint32_t min_filter, mag_filter, mip_filter;
    uint32_t s_address_mode, t_address_mode, r_address_mode;
    uint32_t border_color, normalized_coordinates;
    float lod_min_clamp, lod_max_clamp;
    uint32_t lod_average, max_anisotropy, compare_function, support_argument_buffers;
} qm_sampler_desc;

typedef struct {
    uint32_t compare_function, failure_operation, depth_failure_operation, pass_operation;
    uint32_t read_mask, write_mask;
} qm_stencil_desc;

typedef struct {
    uint32_t depth_compare_function, depth_write_enabled;
    qm_stencil_desc front, back;
} qm_depth_stencil_desc;

typedef struct {
    char name[256];
    uint64_t registry_id, max_buffer_length, recommended_max_working_set_size;
    uint64_t max_threadgroup_memory_length;
    qm_size max_threads_per_threadgroup;
    uint32_t has_unified_memory, is_low_power, is_headless, argument_buffers_tier;
    uint32_t read_write_texture_tier, depth24_stencil8_supported, vendor_id, device_id;
} qm_device_info;

/* Where a CAMetalLayer's frames go. */
enum { QM_SURFACE_X11 = 1, QM_SURFACE_WAYLAND = 2 };

typedef struct {
    uint32_t kind, pad;
    /* X11: the game window. The host makes a click-through child window of
     * it on its own connection to the display named here (NULL: $DISPLAY). */
    uint64_t x11_parent;
    const char *x11_display;
    /* Wayland: the view's own subsurface and its display connection. */
    void *wl_display, *wl_surface;
} qm_surface_target;

typedef struct {
    /* The view's rectangle in the parent's pixels (X11 child window). */
    int32_t x, y;
    uint32_t width, height;
    /* The layer's drawable size: the swapchain's extent. */
    uint32_t drawable_width, drawable_height;
    uint64_t pixel_format;
    uint32_t display_sync, maximum_drawable_count;
    uint32_t framebuffer_only, visible;
} qm_surface_config;

enum {
    QM_STATUS_NOT_ENQUEUED = 0, QM_STATUS_ENQUEUED, QM_STATUS_COMMITTED,
    QM_STATUS_SCHEDULED, QM_STATUS_COMPLETED, QM_STATUS_ERROR
};

enum { QM_STAGE_VERTEX = 0, QM_STAGE_FRAGMENT = 1, QM_STAGE_COMPUTE = 2 };

typedef struct qm_api {
    uint32_t version, size;

    const char *(*last_error)(void);
    void (*release)(void *object);

    /* Device. options: reserved, pass 0. */
    void *(*device_create)(const void *options);
    void (*device_info)(void *device, qm_device_info *out);
    int (*device_supports_family)(void *device, int64_t family);
    int (*device_supports_texture_sample_count)(void *device, uint64_t count);
    uint64_t (*device_current_allocated_size)(void *device);

    /* Resources. */
    void *(*buffer_new)(void *device, uint64_t length, uint64_t options, const void *bytes);
    void *(*buffer_contents)(void *buffer);
    uint64_t (*buffer_length)(void *buffer);
    int (*buffer_did_modify_range)(void *buffer, uint64_t start, uint64_t end);
    void *(*texture_new)(void *device, const qm_texture_desc *descriptor);
    void *(*texture_view)(void *texture, uint64_t pixel_format, uint64_t texture_type,
                          uint64_t level_start, uint64_t level_count,
                          uint64_t slice_start, uint64_t slice_count);
    void (*texture_describe)(void *texture, qm_texture_desc *out);
    int (*texture_replace_region)(void *texture, qm_origin origin, qm_size size,
                                  uint64_t level, uint64_t slice, const void *bytes,
                                  uint64_t bytes_per_row, uint64_t bytes_per_image);
    int (*texture_get_bytes)(void *texture, void *bytes, uint64_t length,
                             uint64_t bytes_per_row, uint64_t bytes_per_image,
                             qm_origin origin, qm_size size, uint64_t level, uint64_t slice);
    void *(*sampler_new)(void *device, const qm_sampler_desc *descriptor);
    void *(*depth_stencil_new)(void *device, const qm_depth_stencil_desc *descriptor);

    /* Shaders. names: NUL-separated into buffer; returns the bytes needed. */
    void *(*library_new)(void *device, const void *data, uint64_t length);
    uint64_t (*library_function_names)(void *library, char *buffer, uint64_t capacity);
    void *(*function_new)(void *library, const char *name);
    int (*function_type)(void *function); /* 1 vertex, 2 fragment, 3 kernel, 0 unknown */
    void *(*render_pipeline_new)(void *device, const qm_render_pipeline_desc *descriptor);
    void *(*compute_pipeline_new)(void *device, void *function, const char *label);
    void (*compute_pipeline_info)(void *pipeline, uint32_t *max_threads, uint32_t *execution_width);

    /* Queues and command buffers. */
    void *(*queue_new)(void *device);
    void *(*command_buffer_new)(void *queue);
    int (*command_buffer_commit)(void *command_buffer);
    int (*command_buffer_wait)(void *command_buffer); /* returns the final QM_STATUS_* */
    int (*command_buffer_status)(void *command_buffer);
    void (*command_buffer_times)(void *command_buffer, double *gpu_start, double *gpu_end);
    /* Present the drawable once this command buffer runs. Before commit. */
    int (*command_buffer_present)(void *command_buffer, void *drawable);

    /* Render encoder. */
    void *(*render_encoder_new)(void *command_buffer, const qm_render_pass_desc *descriptor);
    int (*render_end)(void *encoder);
    void (*render_set_pipeline)(void *encoder, void *pipeline);
    void (*render_set_buffer)(void *encoder, int stage, void *buffer, uint64_t offset, uint32_t index);
    void (*render_set_buffer_offset)(void *encoder, int stage, uint64_t offset, uint32_t index);
    void (*render_set_bytes)(void *encoder, int stage, const void *bytes, uint64_t length, uint32_t index);
    void (*render_set_texture)(void *encoder, int stage, void *texture, uint32_t index);
    void (*render_set_sampler)(void *encoder, int stage, void *sampler, uint32_t index);
    void (*render_set_viewport)(void *encoder, const double viewport[6]);
    void (*render_set_scissor)(void *encoder, uint64_t x, uint64_t y, uint64_t width, uint64_t height);
    void (*render_set_cull_mode)(void *encoder, uint32_t mode);
    void (*render_set_winding)(void *encoder, uint32_t winding);
    void (*render_set_depth_bias)(void *encoder, float bias, float slope, float clamp);
    void (*render_set_depth_clip_mode)(void *encoder, uint32_t mode);
    void (*render_set_fill_mode)(void *encoder, uint32_t mode);
    void (*render_set_depth_stencil)(void *encoder, void *state);
    void (*render_set_stencil_reference)(void *encoder, uint32_t front, uint32_t back);
    void (*render_set_blend_color)(void *encoder, float red, float green, float blue, float alpha);
    void (*render_set_visibility_mode)(void *encoder, uint32_t mode, uint64_t offset);
    void (*render_draw)(void *encoder, uint32_t primitive, uint64_t start, uint64_t count,
                        uint64_t instances, uint64_t base_instance);
    void (*render_draw_indexed)(void *encoder, uint32_t primitive, uint64_t count, uint32_t index_type,
                                void *index_buffer, uint64_t index_offset, uint64_t instances,
                                int64_t base_vertex, uint64_t base_instance);

    /* Blit encoder. */
    void *(*blit_encoder_new)(void *command_buffer);
    int (*blit_end)(void *encoder);
    void (*blit_copy_buffer)(void *encoder, void *source, uint64_t source_offset,
                             void *destination, uint64_t destination_offset, uint64_t size);
    void (*blit_copy_buffer_to_texture)(void *encoder, void *source, uint64_t source_offset,
                                        uint64_t bytes_per_row, uint64_t bytes_per_image, qm_size size,
                                        void *destination, uint64_t slice, uint64_t level, qm_origin origin);
    void (*blit_copy_texture_to_buffer)(void *encoder, void *source, uint64_t slice, uint64_t level,
                                        qm_origin origin, qm_size size, void *destination,
                                        uint64_t destination_offset, uint64_t bytes_per_row,
                                        uint64_t bytes_per_image);
    void (*blit_copy_texture)(void *encoder, void *source, uint64_t source_slice, uint64_t source_level,
                              qm_origin source_origin, qm_size size, void *destination,
                              uint64_t destination_slice, uint64_t destination_level,
                              qm_origin destination_origin);
    void (*blit_copy_texture_slices)(void *encoder, void *source, uint64_t source_slice,
                                     uint64_t source_level, void *destination, uint64_t destination_slice,
                                     uint64_t destination_level, uint64_t slice_count, uint64_t level_count);
    void (*blit_generate_mipmaps)(void *encoder, void *texture);
    void (*blit_synchronize)(void *encoder, void *buffer_or_texture);

    /* Compute encoder. */
    void *(*compute_encoder_new)(void *command_buffer);
    int (*compute_end)(void *encoder);
    void (*compute_set_pipeline)(void *encoder, void *pipeline);
    void (*compute_set_buffer)(void *encoder, void *buffer, uint64_t offset, uint32_t index);
    void (*compute_set_buffer_offset)(void *encoder, uint64_t offset, uint32_t index);
    void (*compute_set_bytes)(void *encoder, const void *bytes, uint64_t length, uint32_t index);
    void (*compute_set_texture)(void *encoder, void *texture, uint32_t index);
    void (*compute_set_sampler)(void *encoder, void *sampler, uint32_t index);
    void (*compute_dispatch)(void *encoder, qm_size groups, qm_size threads_per_group);

    /* Presentation. next_drawable blocks until an image is free and gives
     * a new texture handle in *texture (the guest releases it). */
    void *(*surface_new)(void *device, const qm_surface_target *target);
    int (*surface_configure)(void *surface, const qm_surface_config *config);
    void *(*surface_next_drawable)(void *surface, void **texture);
    int (*drawable_present)(void *drawable); /* without a command buffer */

    /* Logging into the game's launch log (stderr), once per distinct text. */
    void (*log_once)(const char *text);

    /* ABI 2. Span validation happens before any host slice or guest pointer access. */
    int (*texture_copy_byte_length)(void *texture, qm_origin origin, qm_size size,
        uint64_t level, uint64_t slice, uint64_t row, uint64_t image, uint64_t *out);
    void (*compute_dispatch_threads)(void *encoder, qm_size threads, qm_size per_group);
    void (*compute_set_threadgroup_memory)(void *encoder, uint64_t length, uint32_t index);
    void (*compute_barrier)(void *encoder, uint32_t scope);
    int (*command_buffer_wait_scheduled)(void *command_buffer);
    void *(*queue_new_with_limit)(void *device, uint64_t count);
    void *(*fence_new)(void *device);
    void (*encoder_fence)(void *encoder, void *fence, int update, uint32_t stages);
    void (*encoder_use_resource)(void *encoder, void *resource, uint32_t usage, uint32_t stages);
    void (*render_barrier)(void *encoder, uint32_t scope, uint32_t after, uint32_t before);
    void (*render_set_buffers)(void *encoder, int stage, void *const *buffers, const uint64_t *offsets, uint32_t first, uint32_t count);
    void (*render_set_textures)(void *encoder, int stage, void *const *textures, uint32_t first, uint32_t count);
    void (*render_set_samplers)(void *encoder, int stage, void *const *samplers, uint32_t first, uint32_t count);
} qm_api;

typedef const qm_api *(*qm_api_entry)(uint32_t version);
#define QM_API_SYMBOL "quadra_metal_host_api"

/* Optional Linux host-tool exports; callbacks stay in the launcher's helper process. */
typedef void (*qm_preload_progress)(uint32_t completed, uint32_t total, uint32_t failed, void *context);
typedef int (*qm_preload_entry)(qm_preload_progress progress, void *context, uint32_t maximum);
typedef int (*qm_preload_device_entry)(void *device, qm_preload_progress progress, void *context, uint32_t maximum);
typedef uint64_t (*qm_diagnostics_entry)(void *device, char *buffer, uint64_t capacity);
#define QM_PRELOAD_SYMBOL "quadra_metal_host_preload"
#define QM_PRELOAD_DEVICE_SYMBOL "quadra_metal_host_preload_device"
#define QM_DIAGNOSTICS_SYMBOL "quadra_metal_host_diagnostics"

#endif

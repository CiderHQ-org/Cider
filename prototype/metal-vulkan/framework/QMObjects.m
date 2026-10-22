/* MTLDevice and everything it makes: resources, shaders, pipelines, queues,
 * command buffers and encoders, over the host library's handles. */
#include "qm.h"

typedef void *dispatch_data_t;
extern dispatch_data_t dispatch_data_create_map(dispatch_data_t data, const void **buffer, unsigned long *size);
extern void dispatch_release(void *object);

void qm_texture_desc_from(id descriptor, qm_texture_desc *out);
const qm_sampler_desc *qm_sampler_desc_of(id descriptor);
void qm_depth_stencil_desc_from(id descriptor, qm_depth_stencil_desc *out);
void qm_render_pipeline_desc_from(id descriptor, qm_render_pipeline_desc *out);
void qm_render_pass_desc_from(id descriptor, qm_render_pass_desc *out);

static void log_once(const char *text) {
    if (qm)
        qm->log_once(text);
}

/* --- Simple objects -------------------------------------------------------- */

@interface QMSamplerState : QMObject
@end
@implementation QMSamplerState
@end

@interface QMDepthStencilState : QMObject
@end
@implementation QMDepthStencilState
@end

@interface QMRenderPipelineState : QMObject
@end
@implementation QMRenderPipelineState
- (NSUInteger)maxTotalThreadsPerThreadgroup { return 1024; }
- (BOOL)threadgroupSizeMatchesTileSize { return NO; }
- (NSUInteger)imageblockSampleLength { return 0; }
- (BOOL)supportIndirectCommandBuffers { return NO; }
@end

/* The kernels of Resources/builtins.shaders (Metal source, which Linux
 * cannot compile): uploads of tightly strided bytes into a texture, which
 * this framework runs as blits. */
enum { BUILTIN_NONE, BUILTIN_3D_RGBA8, BUILTIN_2D_R8, BUILTIN_3D_RG8 };

static int builtin_kind(const char *name) {
    if (!strcmp(name, "blitTexture3D_RGBA8")) return BUILTIN_3D_RGBA8;
    if (!strcmp(name, "blitTexture2D_R8")) return BUILTIN_2D_R8;
    if (!strcmp(name, "blitTexture3D_RG8")) return BUILTIN_3D_RG8;
    return BUILTIN_NONE;
}

@interface QMComputePipelineState : QMObject {
@public
    int builtin;
    uint32_t max_threads, execution_width;
}
@end
@implementation QMComputePipelineState
- (NSUInteger)maxTotalThreadsPerThreadgroup { return max_threads ? max_threads : 1024; }
- (NSUInteger)threadExecutionWidth { return execution_width ? execution_width : 32; }
- (NSUInteger)staticThreadgroupMemoryLength { return 0; }
- (BOOL)supportIndirectCommandBuffers { return NO; }
@end

@interface QMFunction : QMObject {
@public
    id name;
    int builtin;
}
@end
@implementation QMFunction
- (void)dealloc { [name release]; [super dealloc]; }
- (NSString *)name { return name; }
- (NSUInteger)functionType {
    if (builtin)
        return 3;
    int type = handle ? qm->function_type(handle) : 0;
    return type ? type : 1;
}
- (id)vertexAttributes { return nil; }
- (id)stageInputAttributes { return nil; }
- (NSUInteger)options { return 0; }
- (NSUInteger)patchType { return 0; }
- (NSInteger)patchControlPointCount { return -1; }
@end

@interface QMLibrary : QMObject {
@public
    BOOL builtins;
}
@end
@implementation QMLibrary
- (NSArray *)functionNames {
    if (builtins) {
        id names[3] = {[NSString stringWithUTF8String:"blitTexture3D_RGBA8"], [NSString stringWithUTF8String:"blitTexture2D_R8"],
                       [NSString stringWithUTF8String:"blitTexture3D_RG8"]};
        return [NSArray arrayWithObjects:names count:3];
    }
    uint64_t size = qm->library_function_names(handle, 0, 0);
    char *buffer = malloc(size + 1);
    qm->library_function_names(handle, buffer, size);
    id names[256];
    NSUInteger count = 0;
    for (uint64_t at = 0; at < size && count < 256; at += strlen(buffer + at) + 1)
        names[count++] = [NSString stringWithUTF8String:buffer + at];
    free(buffer);
    return [NSArray arrayWithObjects:names count:count];
}
- (id)newFunctionWithName:(NSString *)functionName {
    if (!functionName)
        return nil;
    const char *text = [functionName UTF8String];
    QMFunction *function = [QMFunction new];
    function->name = [functionName copy];
    if (builtins) {
        function->builtin = builtin_kind(text);
        if (!function->builtin) {
            [function release];
            return nil;
        }
        return function;
    }
    function->handle = qm->function_new(handle, text);
    if (!function->handle) {
        qm_error("newFunctionWithName");
        [function release];
        return nil;
    }
    return function;
}
- (id)newFunctionWithName:(NSString *)functionName constantValues:(id)values error:(NSError **)error {
    id function = [self newFunctionWithName:functionName];
    if (!function && error)
        *error = qm_error("newFunctionWithName:constantValues:");
    return function;
}
- (NSUInteger)type { return 0; }
- (NSString *)installName { return nil; }
@end

/* --- Buffers and textures --------------------------------------------------- */

@implementation QMBuffer
- (void *)contents { return contents; }
- (NSUInteger)length { return length; }
- (NSUInteger)allocatedSize { return length; }
- (void)didModifyRange:(NSRange)range {
    if (((options >> 4) & 0xf) == 1) /* Managed */
        qm->buffer_did_modify_range(handle, range.location, range.location + range.length);
}
- (NSUInteger)storageMode { return (options >> 4) & 0xf; }
- (NSUInteger)cpuCacheMode { return options & 0xf; }
- (NSUInteger)hazardTrackingMode { return (options >> 8) & 3; }
- (NSUInteger)resourceOptions { return options; }
- (uint64_t)gpuAddress { return 0; }
- (NSUInteger)setPurgeableState:(NSUInteger)state { return 2; /* NonVolatile */ }
- (BOOL)isAliasable { return NO; }
- (void)makeAliasable {}
- (id)heap { return nil; }
- (id)remoteStorageBuffer { return nil; }
@end

@implementation QMTexture
+ (id)newWithHandle:(void *)value owner:(id)owner {
    QMTexture *texture = [QMTexture new];
    texture->handle = value;
    texture->parent = [owner retain];
    qm->texture_describe(value, &texture->info);
    return texture;
}
- (void)dealloc { [parent release]; [super dealloc]; }
- (NSUInteger)width { return info.width; }
- (NSUInteger)height { return info.height; }
- (NSUInteger)depth { return info.depth; }
- (NSUInteger)mipmapLevelCount { return info.mipmap_level_count; }
- (NSUInteger)sampleCount { return info.sample_count; }
- (NSUInteger)arrayLength { return info.array_length; }
- (NSUInteger)pixelFormat { return info.pixel_format; }
- (NSUInteger)textureType { return info.texture_type; }
- (NSUInteger)usage { return info.usage; }
- (NSUInteger)storageMode { return (info.resource_options >> 4) & 0xf; }
- (NSUInteger)cpuCacheMode { return info.resource_options & 0xf; }
- (NSUInteger)hazardTrackingMode { return (info.resource_options >> 8) & 3; }
- (NSUInteger)resourceOptions { return info.resource_options; }
- (BOOL)isFramebufferOnly { return info.framebuffer_only; }
- (BOOL)framebufferOnly { return info.framebuffer_only; }
- (BOOL)allowGPUOptimizedContents { return YES; }
- (BOOL)isShareable { return NO; }
- (BOOL)isAliasable { return NO; }
- (id)parentTexture { return [parent isKindOfClass:[QMTexture class]] ? parent : nil; }
- (id)buffer { return nil; }
- (id)iosurface { return nil; }
- (NSUInteger)allocatedSize { return info.width * info.height * info.depth * info.array_length * 4; }
- (NSUInteger)setPurgeableState:(NSUInteger)state { return 2; }
- (void)replaceRegion:(MTLRegion)region mipmapLevel:(NSUInteger)level slice:(NSUInteger)slice
            withBytes:(const void *)bytes bytesPerRow:(NSUInteger)row bytesPerImage:(NSUInteger)image {
    qm_origin origin = {region.origin.x, region.origin.y, region.origin.z};
    qm_size size = {region.size.width, region.size.height, region.size.depth};
    if (!qm->texture_replace_region(handle, origin, size, level, slice, bytes, row, image))
        qm_error("replaceRegion");
}
- (void)replaceRegion:(MTLRegion)region mipmapLevel:(NSUInteger)level withBytes:(const void *)bytes bytesPerRow:(NSUInteger)row {
    [self replaceRegion:region mipmapLevel:level slice:0 withBytes:bytes bytesPerRow:row bytesPerImage:0];
}
- (void)getBytes:(void *)bytes bytesPerRow:(NSUInteger)row bytesPerImage:(NSUInteger)image
      fromRegion:(MTLRegion)region mipmapLevel:(NSUInteger)level slice:(NSUInteger)slice {
    qm_origin origin = {region.origin.x, region.origin.y, region.origin.z};
    qm_size size = {region.size.width, region.size.height, region.size.depth};
    uint64_t length = 0;
    if (!qm->texture_copy_byte_length(handle, origin, size, level, slice, row, image, &length)) {
        qm_error("getBytes copy span");
        return;
    }
    if (!qm->texture_get_bytes(handle, bytes, length, row, image, origin, size, level, slice))
        qm_error("getBytes");
}
- (void)getBytes:(void *)bytes bytesPerRow:(NSUInteger)row fromRegion:(MTLRegion)region mipmapLevel:(NSUInteger)level {
    [self getBytes:bytes bytesPerRow:row bytesPerImage:0 fromRegion:region mipmapLevel:level slice:0];
}
- (id)newTextureViewWithPixelFormat:(NSUInteger)format {
    void *view = qm->texture_view(handle, format, 0, 0, 0, 0, 0);
    if (!view) {
        qm_error("newTextureViewWithPixelFormat");
        return nil;
    }
    return [QMTexture newWithHandle:view owner:self];
}
- (id)newTextureViewWithPixelFormat:(NSUInteger)format textureType:(NSUInteger)type levels:(NSRange)levels slices:(NSRange)slices {
    void *view = qm->texture_view(handle, format, type, levels.location, levels.length, slices.location, slices.length);
    if (!view) {
        qm_error("newTextureViewWithPixelFormat:textureType:levels:slices:");
        return nil;
    }
    return [QMTexture newWithHandle:view owner:self];
}
@end

/* --- The device ------------------------------------------------------------- */

@interface QMCommandQueue : QMObject {
@public
    qm_mutex_t lock;
    qm_cond_t ready;
    id *pending;
    unsigned head, count, capacity;
    BOOL running;
}
- (void)track:(id)commandBuffer;
@end

@implementation QMDevice {
    qm_device_info info;
    BOOL described;
    id name;
}
- (const qm_device_info *)info {
    if (!described) {
        memset(&info, 0, sizeof info);
        qm->device_info(handle, &info);
        described = YES;
        qm_log("[Quadra Metal] device %s (vendor %04x device %04x), unified memory %d", info.name, info.vendor_id,
               info.device_id, info.has_unified_memory);
    }
    return &info;
}
- (id)device { return self; }
- (NSString *)name {
    if (!name)
        name = [[NSString stringWithUTF8String:[self info]->name] retain];
    return name;
}
- (uint64_t)registryID { return [self info]->registry_id; }
- (NSUInteger)maxBufferLength { return [self info]->max_buffer_length; }
- (uint64_t)recommendedMaxWorkingSetSize { return [self info]->recommended_max_working_set_size; }
- (NSUInteger)currentAllocatedSize { return qm->device_current_allocated_size(handle); }
- (NSUInteger)maxThreadgroupMemoryLength { return [self info]->max_threadgroup_memory_length; }
- (MTLSize)maxThreadsPerThreadgroup {
    MTLSize size = {[self info]->max_threads_per_threadgroup.width, [self info]->max_threads_per_threadgroup.height,
                    [self info]->max_threads_per_threadgroup.depth};
    return size;
}
- (BOOL)hasUnifiedMemory { return [self info]->has_unified_memory; }
- (BOOL)isLowPower { return [self info]->is_low_power; }
- (BOOL)isHeadless { return NO; }
- (BOOL)isRemovable { return NO; }
- (NSUInteger)location { return 0; }
- (NSUInteger)locationNumber { return 0; }
- (uint64_t)maxTransferRate { return 0; }
- (uint32_t)peerCount { return 1; }
- (uint32_t)peerIndex { return 0; }
- (uint64_t)peerGroupID { return 0; }
- (NSUInteger)argumentBuffersSupport { return [self info]->argument_buffers_tier; }
- (NSUInteger)readWriteTextureSupport { return [self info]->read_write_texture_tier; }
- (BOOL)isDepth24Stencil8PixelFormatSupported { return [self info]->depth24_stencil8_supported; }
- (BOOL)supports32BitFloatFiltering { return YES; }
- (BOOL)supports32BitMSAA { return YES; }
- (BOOL)supportsBCTextureCompression { return YES; }
- (BOOL)supportsQueryTextureLOD { return YES; }
- (BOOL)supportsRaytracing { return NO; }
- (BOOL)supportsFunctionPointers { return NO; }
- (BOOL)supportsDynamicLibraries { return NO; }
- (BOOL)supportsShaderBarycentricCoordinates { return NO; }
- (BOOL)supportsPullModelInterpolation { return NO; }
- (BOOL)areRasterOrderGroupsSupported { return NO; }
- (BOOL)areProgrammableSamplePositionsSupported { return NO; }
- (BOOL)areBarycentricCoordsSupported { return NO; }
- (BOOL)supportsPrimitiveMotionBlur { return NO; }
- (NSUInteger)sparseTileSizeInBytes { return 65536; }
- (NSUInteger)minimumLinearTextureAlignmentForPixelFormat:(NSUInteger)format { return 256; }
- (NSUInteger)minimumTextureBufferAlignmentForPixelFormat:(NSUInteger)format { return 256; }

/* Roblox picks its Metal feature level from these. A discrete GPU on Vulkan
 * runs Metal's Mac2/Common3 feature set; Apple-family (tile GPU) features
 * are not offered. */
- (BOOL)supportsFamily:(NSInteger)family {
    BOOL answer = qm->device_supports_family(handle, family);
    char text[96];
    snprintf(text, sizeof text, "[Quadra Metal] supportsFamily %ld -> %d", (long)family, answer);
    log_once(text);
    return answer;
}
- (BOOL)supportsFeatureSet:(NSUInteger)set {
    BOOL answer = set >= 10000 && set <= 10005; /* macOS_GPUFamily1_v1 ... GPUFamily2_v1 */
    char text[96];
    snprintf(text, sizeof text, "[Quadra Metal] supportsFeatureSet %lu -> %d", (unsigned long)set, answer);
    log_once(text);
    return answer;
}
- (BOOL)supportsTextureSampleCount:(NSUInteger)count {
    return count == 1 || qm->device_supports_texture_sample_count(handle, count);
}
- (void)getDefaultSamplePositions:(void *)positions count:(NSUInteger)count {
    memset(positions, 0, count * 8);
}

- (id)newBufferWithLength:(NSUInteger)length options:(NSUInteger)options {
    void *buffer = qm->buffer_new(handle, length, options, 0);
    if (!buffer) {
        qm_error("newBufferWithLength");
        return nil;
    }
    QMBuffer *object = [QMBuffer new];
    object->handle = buffer;
    object->length = length;
    object->options = options;
    object->contents = qm->buffer_contents(buffer);
    return object;
}
- (id)newBufferWithBytes:(const void *)bytes length:(NSUInteger)length options:(NSUInteger)options {
    void *buffer = qm->buffer_new(handle, length, options, bytes);
    if (!buffer) {
        qm_error("newBufferWithBytes");
        return nil;
    }
    QMBuffer *object = [QMBuffer new];
    object->handle = buffer;
    object->length = length;
    object->options = options;
    object->contents = qm->buffer_contents(buffer);
    return object;
}
- (id)newTextureWithDescriptor:(id)descriptor {
    qm_texture_desc value;
    qm_texture_desc_from(descriptor, &value);
    void *texture = qm->texture_new(handle, &value);
    if (!texture) {
        qm_error("newTextureWithDescriptor");
        return nil;
    }
    return [QMTexture newWithHandle:texture owner:nil];
}
- (id)newSamplerStateWithDescriptor:(id)descriptor {
    void *sampler = qm->sampler_new(handle, qm_sampler_desc_of(descriptor));
    if (!sampler) {
        qm_error("newSamplerStateWithDescriptor");
        return nil;
    }
    QMSamplerState *object = [QMSamplerState new];
    object->handle = sampler;
    return object;
}
- (id)newDepthStencilStateWithDescriptor:(id)descriptor {
    qm_depth_stencil_desc value;
    qm_depth_stencil_desc_from(descriptor, &value);
    void *state = qm->depth_stencil_new(handle, &value);
    if (!state) {
        qm_error("newDepthStencilStateWithDescriptor");
        return nil;
    }
    QMDepthStencilState *object = [QMDepthStencilState new];
    object->handle = state;
    return object;
}
- (id)newLibraryWithBytes:(const void *)bytes length:(unsigned long)length error:(NSError **)error {
    void *library = qm->library_new(handle, bytes, length);
    if (!library) {
        NSError *failure = qm_error("newLibraryWithData");
        if (error)
            *error = failure;
        return nil;
    }
    QMLibrary *object = [QMLibrary new];
    object->handle = library;
    return object;
}
- (id)newLibraryWithData:(dispatch_data_t)data error:(NSError **)error {
    const void *bytes = 0;
    unsigned long length = 0;
    dispatch_data_t map = dispatch_data_create_map(data, &bytes, &length);
    id library = [self newLibraryWithBytes:bytes length:length error:error];
    if (map)
        dispatch_release(map);
    return library;
}
- (id)newLibraryWithSource:(NSString *)source options:(id)options error:(NSError **)error {
    const char *text = source ? [source UTF8String] : "";
    if (strstr(text, "blitTexture3D_RGBA8") && strstr(text, "blitTexture2D_R8")) {
        QMLibrary *library = [QMLibrary new];
        library->builtins = YES;
        qm_log("[Quadra Metal] builtins.shaders: its upload kernels run as blits");
        return library;
    }
    if (error) {
        NSDictionary *details = [NSDictionary dictionaryWithObject:[NSString stringWithUTF8String:
            "Metal source cannot be compiled on Linux"] forKey:NSLocalizedDescriptionKey];
        *error = [NSError errorWithDomain:[NSString stringWithUTF8String:"MTLLibraryErrorDomain"] code:3 userInfo:details];
    }
    log_once("[Quadra Metal] newLibraryWithSource: Metal source cannot be compiled on Linux");
    return nil;
}
- (id)newDefaultLibrary { return nil; }
- (id)newRenderPipelineStateWithDescriptor:(id)descriptor error:(NSError **)error {
    qm_render_pipeline_desc value;
    qm_render_pipeline_desc_from(descriptor, &value);
    void *pipeline = qm->render_pipeline_new(handle, &value);
    if (!pipeline) {
        NSError *failure = qm_error("newRenderPipelineStateWithDescriptor");
        if (error)
            *error = failure;
        return nil;
    }
    QMRenderPipelineState *object = [QMRenderPipelineState new];
    object->handle = pipeline;
    return object;
}
- (id)newRenderPipelineStateWithDescriptor:(id)descriptor options:(NSUInteger)options reflection:(id *)reflection error:(NSError **)error {
    if (reflection)
        *reflection = nil;
    return [self newRenderPipelineStateWithDescriptor:descriptor error:error];
}
- (id)newComputePipelineStateWithFunction:(id)function error:(NSError **)error {
    QMFunction *kernel = function;
    QMComputePipelineState *object = [QMComputePipelineState new];
    if (kernel && kernel->builtin) {
        object->builtin = kernel->builtin;
        return object;
    }
    object->handle = qm->compute_pipeline_new(handle, qm_handle(function), 0);
    if (!object->handle) {
        NSError *failure = qm_error("newComputePipelineStateWithFunction");
        if (error)
            *error = failure;
        [object release];
        return nil;
    }
    qm->compute_pipeline_info(object->handle, &object->max_threads, &object->execution_width);
    return object;
}
- (id)newComputePipelineStateWithFunction:(id)function options:(NSUInteger)options reflection:(id *)reflection error:(NSError **)error {
    if (reflection)
        *reflection = nil;
    return [self newComputePipelineStateWithFunction:function error:error];
}
- (id)newCommandQueue { return [self newCommandQueueWithMaxCommandBufferCount:64]; }
- (id)newCommandQueueWithMaxCommandBufferCount:(NSUInteger)count {
    void *queue = qm->queue_new_with_limit(handle, count);
    if (!queue) {
        qm_error("newCommandQueue");
        return nil;
    }
    QMCommandQueue *object = [QMCommandQueue new];
    object->handle = queue;
    qm_mutex_t queue_lock = QM_MUTEX_INIT;
    qm_cond_t queue_ready = QM_COND_INIT;
    object->lock = queue_lock;
    object->ready = queue_ready;
    return object;
}
- (id)newFence {
    QMObject *fence = [QMObject new];
    fence->handle = qm->fence_new(handle);
    if (!fence->handle) { [fence release]; return nil; }
    return fence;
}
- (MTLSizeAndAlign)heapTextureSizeAndAlignWithDescriptor:(id)descriptor {
    qm_texture_desc value;
    qm_texture_desc_from(descriptor, &value);
    MTLSizeAndAlign result = {value.width * value.height * value.depth * value.array_length * 16, 65536};
    return result;
}
- (MTLSizeAndAlign)heapBufferSizeAndAlignWithLength:(NSUInteger)length options:(NSUInteger)options {
    MTLSizeAndAlign result = {(length + 255) & ~255UL, 256};
    return result;
}
@end

/* --- Command buffers --------------------------------------------------------- */

@interface QMCommandBuffer : QMObject {
@public
    QMCommandQueue *queue;
    qm_mutex_t lock;
    QMCommandBufferHandler *completed;
    unsigned completed_count;
    QMCommandBufferHandler *scheduled;
    unsigned scheduled_count;
    id *drawables;
    unsigned drawable_count;
    int status; /* QM_STATUS_* as this side last saw it */
    BOOL retains, tracked, scheduled_done, completed_done;
    qm_cond_t done;
    qm_thread_t worker;
}
@end

static void *queue_worker(void *argument);

@implementation QMCommandQueue
- (void)dealloc {
    pthread_cond_destroy(&ready);
    pthread_mutex_destroy(&lock);
    free(pending);
    [super dealloc];
}
- (id)commandBufferRetaining:(BOOL)retains {
    void *buffer = qm->command_buffer_new(handle);
    if (!buffer) {
        qm_error("commandBuffer");
        return nil;
    }
    QMCommandBuffer *object = [QMCommandBuffer new];
    object->handle = buffer;
    object->queue = [self retain];
    qm_mutex_t buffer_lock = QM_MUTEX_INIT;
    object->lock = buffer_lock;
    object->retains = retains;
    qm_cond_t buffer_done = QM_COND_INIT;
    object->done = buffer_done;
    return [object autorelease];
}
- (id)commandBuffer { return [self commandBufferRetaining:YES]; }
- (id)commandBufferWithUnretainedReferences { return [self commandBufferRetaining:NO]; }
- (id)commandBufferWithDescriptor:(id)descriptor { return [self commandBufferRetaining:YES]; }
- (void)insertDebugCaptureBoundary {}
/* Command buffers with handlers or drawables wait, in commit order, on this
 * queue's own guest thread, which then runs their blocks. */
- (void)track:(id)commandBuffer {
    BOOL fallback = NO;
    pthread_mutex_lock(&lock);
    if (count == capacity) {
        unsigned grown = capacity ? capacity * 2 : 16;
        id *items = malloc(grown * sizeof(id));
        for (unsigned index = 0; index < count; index++)
            items[index] = pending[(head + index) % capacity];
        free(pending);
        pending = items;
        head = 0;
        capacity = grown;
    }
    pending[(head + count++) % capacity] = [commandBuffer retain];
    if (!running) {
        running = YES;
        [self retain]; /* the worker's */
        qm_thread_t thread;
        if (!pthread_create(&thread, 0, queue_worker, self))
            pthread_detach(thread);
        else {
            qm_log("[Quadra Metal] command queue thread creation failed; draining on the committing thread");
            fallback = YES;
        }
    }
    pthread_cond_broadcast(&ready);
    pthread_mutex_unlock(&lock);
    if (fallback) queue_worker(self);
}
@end

static void run_handlers(QMCommandBufferHandler *handlers, unsigned count, id argument) {
    for (unsigned index = 0; index < count; index++) {
        id pool = objc_autoreleasePoolPush();
        handlers[index](argument);
        objc_autoreleasePoolPop(pool);
        _Block_release(handlers[index]);
    }
    free(handlers);
}

static void *queue_worker(void *argument) {
    QMCommandQueue *queue = argument;
    for (;;) {
        pthread_mutex_lock(&queue->lock);
        while (!queue->count) {
            const struct qm_timespec idle = {1, 0};
            int result = pthread_cond_timedwait_relative_np(&queue->ready, &queue->lock, &idle);
            if (result && !queue->count) {
                queue->running = NO;
                pthread_mutex_unlock(&queue->lock);
                [queue release];
                return 0;
            }
        }
        QMCommandBuffer *buffer = queue->pending[queue->head];
        queue->head = (queue->head + 1) % queue->capacity;
        queue->count--;
        pthread_mutex_unlock(&queue->lock);

        qm->command_buffer_wait_scheduled(buffer->handle);
        pthread_mutex_lock(&buffer->lock);
        buffer->worker = pthread_self();
        if (buffer->status < QM_STATUS_SCHEDULED) buffer->status = QM_STATUS_SCHEDULED;
        QMCommandBufferHandler *scheduled = buffer->scheduled;
        unsigned scheduled_count = buffer->scheduled_count;
        buffer->scheduled = 0;
        buffer->scheduled_count = 0;
        pthread_mutex_unlock(&buffer->lock);
        run_handlers(scheduled, scheduled_count, buffer);
        pthread_mutex_lock(&buffer->lock);
        buffer->scheduled_done = YES;
        pthread_cond_broadcast(&buffer->done);
        pthread_mutex_unlock(&buffer->lock);

        int status = qm->command_buffer_wait(buffer->handle);
        double now = qm_now();
        pthread_mutex_lock(&buffer->lock);
        buffer->status = status;
        QMCommandBufferHandler *completed = buffer->completed;
        unsigned completed_count = buffer->completed_count;
        id *drawables = buffer->drawables;
        unsigned drawable_count = buffer->drawable_count;
        buffer->completed = 0;
        buffer->completed_count = 0;
        buffer->drawables = 0;
        buffer->drawable_count = 0;
        pthread_mutex_unlock(&buffer->lock);
        for (unsigned index = 0; index < drawable_count; index++) {
            [drawables[index] didPresentAt:now];
            [drawables[index] release];
        }
        free(drawables);
        run_handlers(completed, completed_count, buffer);
        pthread_mutex_lock(&buffer->lock);
        buffer->completed_done = YES;
        pthread_cond_broadcast(&buffer->done);
        pthread_mutex_unlock(&buffer->lock);
        [buffer release];
    }
    return 0;
}

@implementation QMCommandBuffer
- (void)dealloc {
    for (unsigned index = 0; index < completed_count; index++)
        _Block_release(completed[index]);
    for (unsigned index = 0; index < scheduled_count; index++)
        _Block_release(scheduled[index]);
    for (unsigned index = 0; index < drawable_count; index++)
        [drawables[index] release];
    free(completed);
    free(scheduled);
    free(drawables);
    pthread_cond_destroy(&done);
    pthread_mutex_destroy(&lock);
    [queue release];
    [super dealloc];
}
- (id)commandQueue { return queue; }
- (BOOL)retainedReferences { return retains; }
- (NSUInteger)errorOptions { return 0; }
- (id)logs { return nil; }
- (void)pushDebugGroup:(NSString *)name {}
- (void)popDebugGroup {}
static void append_block(QMCommandBufferHandler **list, unsigned *count, QMCommandBufferHandler block) {
    *list = realloc(*list, (*count + 1) * sizeof **list);
    (*list)[(*count)++] = _Block_copy(block);
}
- (void)addCompletedHandler:(QMCommandBufferHandler)block {
    if (!block)
        return;
    pthread_mutex_lock(&lock);
    if (status >= QM_STATUS_COMPLETED) {
        pthread_mutex_unlock(&lock);
        block(self);
        return;
    }
    append_block(&completed, &completed_count, block);
    BOOL start = status >= QM_STATUS_COMMITTED && !tracked;
    if (start) tracked = YES;
    pthread_mutex_unlock(&lock);
    if (start) [queue track:self];
}
- (void)addScheduledHandler:(QMCommandBufferHandler)block {
    if (!block)
        return;
    pthread_mutex_lock(&lock);
    if (status >= QM_STATUS_SCHEDULED) {
        pthread_mutex_unlock(&lock);
        block(self);
        return;
    }
    append_block(&scheduled, &scheduled_count, block);
    BOOL start = status >= QM_STATUS_COMMITTED && !tracked;
    if (start) tracked = YES;
    pthread_mutex_unlock(&lock);
    if (start) [queue track:self];
}
- (void)presentDrawable:(id)drawable {
    if (!drawable || ![drawable isKindOfClass:[QMDrawable class]])
        return;
    QMDrawable *value = drawable;
    pthread_mutex_lock(&value->lock);
    BOOL first = !value->presented;
    value->presented = YES;
    pthread_mutex_unlock(&value->lock);
    if (!first || !value->handle)
        return;
    qm->command_buffer_present(handle, value->handle);
    pthread_mutex_lock(&lock);
    drawables = realloc(drawables, (drawable_count + 1) * sizeof(id));
    drawables[drawable_count++] = [drawable retain];
    pthread_mutex_unlock(&lock);
}
- (void)presentDrawable:(id)drawable atTime:(CFTimeInterval)time { [self presentDrawable:drawable]; }
- (void)presentDrawable:(id)drawable afterMinimumDuration:(CFTimeInterval)duration { [self presentDrawable:drawable]; }
- (void)enqueue {}
- (void)commit {
    pthread_mutex_lock(&lock);
    if (status >= QM_STATUS_COMMITTED) {
        pthread_mutex_unlock(&lock);
        return;
    }
    status = QM_STATUS_COMMITTED;
    BOOL track = completed_count || scheduled_count || drawable_count;
    tracked = track;
    if (!qm->command_buffer_commit(handle)) {
        status = QM_STATUS_ERROR;
        qm_error("commit");
    }
    pthread_mutex_unlock(&lock);
    if (track)
        [queue track:self];
}
- (void)waitUntilScheduled {
    pthread_mutex_lock(&lock);
    BOOL committed = status >= QM_STATUS_COMMITTED;
    pthread_mutex_unlock(&lock);
    if (!committed) return;
    qm->command_buffer_wait_scheduled(handle);
    pthread_mutex_lock(&lock);
    while (tracked && !scheduled_done && !(worker && pthread_equal(worker, pthread_self())))
        pthread_cond_wait(&done, &lock);
    pthread_mutex_unlock(&lock);
}
- (void)waitUntilCompleted {
    pthread_mutex_lock(&lock);
    BOOL committed = status >= QM_STATUS_COMMITTED;
    pthread_mutex_unlock(&lock);
    if (!committed) return;
    int result = qm->command_buffer_wait(handle);
    pthread_mutex_lock(&lock);
    while (tracked && !completed_done && !(worker && pthread_equal(worker, pthread_self())))
        pthread_cond_wait(&done, &lock);
    if (status < result) status = result;
    pthread_mutex_unlock(&lock);
}
- (NSUInteger)status {
    pthread_mutex_lock(&lock);
    int seen = status;
    pthread_mutex_unlock(&lock);
    if (seen >= QM_STATUS_COMMITTED && seen < QM_STATUS_COMPLETED) {
        int now = qm->command_buffer_status(handle);
        return now > seen ? now : seen;
    }
    return seen;
}
- (NSError *)error {
    if ([self status] != QM_STATUS_ERROR)
        return nil;
    NSDictionary *info = [NSDictionary dictionaryWithObject:[NSString stringWithUTF8String:"The Vulkan command buffer failed"]
                                                     forKey:NSLocalizedDescriptionKey];
    return [NSError errorWithDomain:[NSString stringWithUTF8String:"MTLCommandBufferErrorDomain"] code:1 userInfo:info];
}
- (CFTimeInterval)GPUStartTime {
    double start = 0, end = 0;
    qm->command_buffer_times(handle, &start, &end);
    return start;
}
- (CFTimeInterval)GPUEndTime {
    double start = 0, end = 0;
    qm->command_buffer_times(handle, &start, &end);
    return end;
}
- (CFTimeInterval)kernelStartTime { return [self GPUStartTime]; }
- (CFTimeInterval)kernelEndTime { return [self GPUEndTime]; }
@end

/* --- Encoders ----------------------------------------------------------------- */

@interface QMEncoder : QMObject {
@public
    QMCommandBuffer *buffer;
}
@end
@implementation QMEncoder
- (void)dealloc { [buffer release]; [super dealloc]; }
- (void)pushDebugGroup:(NSString *)name {}
- (void)popDebugGroup {}
- (void)insertDebugSignpost:(NSString *)name {}
- (void)updateFence:(id)fence { qm->encoder_fence(handle, qm_handle(fence), 1, 3); }
- (void)waitForFence:(id)fence { qm->encoder_fence(handle, qm_handle(fence), 0, 3); }
- (void)updateFence:(id)fence afterStages:(NSUInteger)stages { qm->encoder_fence(handle, qm_handle(fence), 1, (uint32_t)stages); }
- (void)waitForFence:(id)fence beforeStages:(NSUInteger)stages { qm->encoder_fence(handle, qm_handle(fence), 0, (uint32_t)stages); }
- (id)device { return qm_device; }
@end

@interface QMRenderCommandEncoder : QMEncoder
@end

@implementation QMRenderCommandEncoder
- (void)endEncoding {
    if (handle)
        qm->render_end(handle);
}
- (void)setRenderPipelineState:(id)state { qm->render_set_pipeline(handle, qm_handle(state)); }
- (void)setVertexBuffer:(id)value offset:(NSUInteger)offset atIndex:(NSUInteger)index {
    qm->render_set_buffer(handle, QM_STAGE_VERTEX, qm_handle(value), offset, (uint32_t)index);
}
- (void)setFragmentBuffer:(id)value offset:(NSUInteger)offset atIndex:(NSUInteger)index {
    qm->render_set_buffer(handle, QM_STAGE_FRAGMENT, qm_handle(value), offset, (uint32_t)index);
}
- (void)setVertexBuffers:(const id *)values offsets:(const NSUInteger *)offsets withRange:(NSRange)range {
    void *handles[31];
    if (range.length > 31 || range.location > 31 - range.length) { qm_log("[Quadra Metal] invalid buffer range"); return; }
    for (NSUInteger i = 0; i < range.length; i++) handles[i] = qm_handle(values[i]);
    qm->render_set_buffers(handle, QM_STAGE_VERTEX, handles, (const uint64_t *)offsets, (uint32_t)range.location, (uint32_t)range.length);
}
- (void)setFragmentBuffers:(const id *)values offsets:(const NSUInteger *)offsets withRange:(NSRange)range {
    void *handles[31];
    if (range.length > 31 || range.location > 31 - range.length) { qm_log("[Quadra Metal] invalid buffer range"); return; }
    for (NSUInteger i = 0; i < range.length; i++) handles[i] = qm_handle(values[i]);
    qm->render_set_buffers(handle, QM_STAGE_FRAGMENT, handles, (const uint64_t *)offsets, (uint32_t)range.location, (uint32_t)range.length);
}
- (void)setVertexBufferOffset:(NSUInteger)offset atIndex:(NSUInteger)index {
    qm->render_set_buffer_offset(handle, QM_STAGE_VERTEX, offset, (uint32_t)index);
}
- (void)setFragmentBufferOffset:(NSUInteger)offset atIndex:(NSUInteger)index {
    qm->render_set_buffer_offset(handle, QM_STAGE_FRAGMENT, offset, (uint32_t)index);
}
- (void)setVertexBytes:(const void *)bytes length:(NSUInteger)length atIndex:(NSUInteger)index {
    qm->render_set_bytes(handle, QM_STAGE_VERTEX, bytes, length, (uint32_t)index);
}
- (void)setFragmentBytes:(const void *)bytes length:(NSUInteger)length atIndex:(NSUInteger)index {
    qm->render_set_bytes(handle, QM_STAGE_FRAGMENT, bytes, length, (uint32_t)index);
}
- (void)setVertexTexture:(id)texture atIndex:(NSUInteger)index {
    qm->render_set_texture(handle, QM_STAGE_VERTEX, qm_handle(texture), (uint32_t)index);
}
- (void)setFragmentTexture:(id)texture atIndex:(NSUInteger)index {
    qm->render_set_texture(handle, QM_STAGE_FRAGMENT, qm_handle(texture), (uint32_t)index);
}
- (void)setVertexTextures:(const id *)textures withRange:(NSRange)range {
    void *handles[128];
    if (range.length > 128 || range.location > 128 - range.length) { qm_log("[Quadra Metal] invalid textures range"); return; }
    for (NSUInteger i = 0; i < range.length; i++) handles[i] = qm_handle(textures[i]);
    qm->render_set_textures(handle, QM_STAGE_VERTEX, handles, (uint32_t)range.location, (uint32_t)range.length);
}
- (void)setFragmentTextures:(const id *)textures withRange:(NSRange)range {
    void *handles[128];
    if (range.length > 128 || range.location > 128 - range.length) { qm_log("[Quadra Metal] invalid textures range"); return; }
    for (NSUInteger i = 0; i < range.length; i++) handles[i] = qm_handle(textures[i]);
    qm->render_set_textures(handle, QM_STAGE_FRAGMENT, handles, (uint32_t)range.location, (uint32_t)range.length);
}
- (void)setVertexSamplerState:(id)sampler atIndex:(NSUInteger)index {
    qm->render_set_sampler(handle, QM_STAGE_VERTEX, qm_handle(sampler), (uint32_t)index);
}
- (void)setFragmentSamplerState:(id)sampler atIndex:(NSUInteger)index {
    qm->render_set_sampler(handle, QM_STAGE_FRAGMENT, qm_handle(sampler), (uint32_t)index);
}
- (void)setVertexSamplerStates:(const id *)samplers withRange:(NSRange)range {
    void *handles[16];
    if (range.length > 16 || range.location > 16 - range.length) { qm_log("[Quadra Metal] invalid sampler range"); return; }
    for (NSUInteger i = 0; i < range.length; i++) handles[i] = qm_handle(samplers[i]);
    qm->render_set_samplers(handle, QM_STAGE_VERTEX, handles, (uint32_t)range.location, (uint32_t)range.length);
}
- (void)setFragmentSamplerStates:(const id *)samplers withRange:(NSRange)range {
    void *handles[16];
    if (range.length > 16 || range.location > 16 - range.length) { qm_log("[Quadra Metal] invalid sampler range"); return; }
    for (NSUInteger i = 0; i < range.length; i++) handles[i] = qm_handle(samplers[i]);
    qm->render_set_samplers(handle, QM_STAGE_FRAGMENT, handles, (uint32_t)range.location, (uint32_t)range.length);
}
- (void)setViewport:(MTLViewport)viewport {
    double values[6] = {viewport.originX, viewport.originY, viewport.width, viewport.height, viewport.znear, viewport.zfar};
    qm->render_set_viewport(handle, values);
}
- (void)setViewports:(const MTLViewport *)viewports count:(NSUInteger)count {
    if (count)
        [self setViewport:viewports[0]];
}
- (void)setScissorRect:(MTLScissorRect)rect { qm->render_set_scissor(handle, rect.x, rect.y, rect.width, rect.height); }
- (void)setScissorRects:(const MTLScissorRect *)rects count:(NSUInteger)count {
    if (count)
        [self setScissorRect:rects[0]];
}
- (void)setCullMode:(NSUInteger)mode { qm->render_set_cull_mode(handle, (uint32_t)mode); }
- (void)setFrontFacingWinding:(NSUInteger)winding { qm->render_set_winding(handle, (uint32_t)winding); }
- (void)setDepthBias:(float)bias slopeScale:(float)slope clamp:(float)clamp { qm->render_set_depth_bias(handle, bias, slope, clamp); }
- (void)setDepthClipMode:(NSUInteger)mode { qm->render_set_depth_clip_mode(handle, (uint32_t)mode); }
- (void)setTriangleFillMode:(NSUInteger)mode { qm->render_set_fill_mode(handle, (uint32_t)mode); }
- (void)setDepthStencilState:(id)state { qm->render_set_depth_stencil(handle, qm_handle(state)); }
- (void)setStencilReferenceValue:(uint32_t)value { qm->render_set_stencil_reference(handle, value, value); }
- (void)setStencilFrontReferenceValue:(uint32_t)front backReferenceValue:(uint32_t)back {
    qm->render_set_stencil_reference(handle, front, back);
}
- (void)setBlendColorRed:(float)red green:(float)green blue:(float)blue alpha:(float)alpha {
    qm->render_set_blend_color(handle, red, green, blue, alpha);
}
- (void)setVisibilityResultMode:(NSUInteger)mode offset:(NSUInteger)offset {
    qm->render_set_visibility_mode(handle, (uint32_t)mode, offset);
}
- (void)drawPrimitives:(NSUInteger)type vertexStart:(NSUInteger)start vertexCount:(NSUInteger)count
         instanceCount:(NSUInteger)instances baseInstance:(NSUInteger)base {
    qm->render_draw(handle, (uint32_t)type, start, count, instances, base);
}
- (void)drawPrimitives:(NSUInteger)type vertexStart:(NSUInteger)start vertexCount:(NSUInteger)count instanceCount:(NSUInteger)instances {
    qm->render_draw(handle, (uint32_t)type, start, count, instances, 0);
}
- (void)drawPrimitives:(NSUInteger)type vertexStart:(NSUInteger)start vertexCount:(NSUInteger)count {
    qm->render_draw(handle, (uint32_t)type, start, count, 1, 0);
}
- (void)drawIndexedPrimitives:(NSUInteger)type indexCount:(NSUInteger)count indexType:(NSUInteger)indexType
                  indexBuffer:(id)indices indexBufferOffset:(NSUInteger)offset instanceCount:(NSUInteger)instances
                   baseVertex:(NSInteger)baseVertex baseInstance:(NSUInteger)baseInstance {
    qm->render_draw_indexed(handle, (uint32_t)type, count, (uint32_t)indexType, qm_handle(indices), offset, instances,
                            baseVertex, baseInstance);
}
- (void)drawIndexedPrimitives:(NSUInteger)type indexCount:(NSUInteger)count indexType:(NSUInteger)indexType
                  indexBuffer:(id)indices indexBufferOffset:(NSUInteger)offset instanceCount:(NSUInteger)instances {
    qm->render_draw_indexed(handle, (uint32_t)type, count, (uint32_t)indexType, qm_handle(indices), offset, instances, 0, 0);
}
- (void)drawIndexedPrimitives:(NSUInteger)type indexCount:(NSUInteger)count indexType:(NSUInteger)indexType
                  indexBuffer:(id)indices indexBufferOffset:(NSUInteger)offset {
    qm->render_draw_indexed(handle, (uint32_t)type, count, (uint32_t)indexType, qm_handle(indices), offset, 1, 0, 0);
}
- (void)useResource:(id)resource usage:(NSUInteger)usage { qm->encoder_use_resource(handle, qm_handle(resource), (uint32_t)usage, 3); }
- (void)useResource:(id)resource usage:(NSUInteger)usage stages:(NSUInteger)stages { qm->encoder_use_resource(handle, qm_handle(resource), (uint32_t)usage, (uint32_t)stages); }
- (void)useResources:(const id *)resources count:(NSUInteger)count usage:(NSUInteger)usage {
    for (NSUInteger i = 0; i < count; i++) [self useResource:resources[i] usage:usage];
}
- (void)useHeap:(id)heap {}
- (void)useHeaps:(const id *)heaps count:(NSUInteger)count {}
- (void)textureBarrier {}
- (void)memoryBarrierWithScope:(NSUInteger)scope afterStages:(NSUInteger)after beforeStages:(NSUInteger)before { qm->render_barrier(handle, (uint32_t)scope, (uint32_t)after, (uint32_t)before); }
@end

@interface QMBlitCommandEncoder : QMEncoder
@end

@implementation QMBlitCommandEncoder
- (void)endEncoding {
    if (handle)
        qm->blit_end(handle);
}
- (void)copyFromBuffer:(id)source sourceOffset:(NSUInteger)sourceOffset toBuffer:(id)destination
     destinationOffset:(NSUInteger)destinationOffset size:(NSUInteger)size {
    qm->blit_copy_buffer(handle, qm_handle(source), sourceOffset, qm_handle(destination), destinationOffset, size);
}
- (void)copyFromBuffer:(id)source sourceOffset:(NSUInteger)offset sourceBytesPerRow:(NSUInteger)row
     sourceBytesPerImage:(NSUInteger)image sourceSize:(MTLSize)size toTexture:(id)destination
        destinationSlice:(NSUInteger)slice destinationLevel:(NSUInteger)level destinationOrigin:(MTLOrigin)origin {
    qm_size extent = {size.width, size.height, size.depth};
    qm_origin at = {origin.x, origin.y, origin.z};
    qm->blit_copy_buffer_to_texture(handle, qm_handle(source), offset, row, image, extent, qm_handle(destination), slice, level, at);
}
- (void)copyFromBuffer:(id)source sourceOffset:(NSUInteger)offset sourceBytesPerRow:(NSUInteger)row
     sourceBytesPerImage:(NSUInteger)image sourceSize:(MTLSize)size toTexture:(id)destination
        destinationSlice:(NSUInteger)slice destinationLevel:(NSUInteger)level destinationOrigin:(MTLOrigin)origin
                 options:(NSUInteger)options {
    [self copyFromBuffer:source sourceOffset:offset sourceBytesPerRow:row sourceBytesPerImage:image sourceSize:size
               toTexture:destination destinationSlice:slice destinationLevel:level destinationOrigin:origin];
}
- (void)copyFromTexture:(id)source sourceSlice:(NSUInteger)slice sourceLevel:(NSUInteger)level sourceOrigin:(MTLOrigin)origin
             sourceSize:(MTLSize)size toBuffer:(id)destination destinationOffset:(NSUInteger)offset
 destinationBytesPerRow:(NSUInteger)row destinationBytesPerImage:(NSUInteger)image {
    qm_size extent = {size.width, size.height, size.depth};
    qm_origin at = {origin.x, origin.y, origin.z};
    qm->blit_copy_texture_to_buffer(handle, qm_handle(source), slice, level, at, extent, qm_handle(destination), offset, row, image);
}
- (void)copyFromTexture:(id)source sourceSlice:(NSUInteger)slice sourceLevel:(NSUInteger)level sourceOrigin:(MTLOrigin)origin
             sourceSize:(MTLSize)size toBuffer:(id)destination destinationOffset:(NSUInteger)offset
 destinationBytesPerRow:(NSUInteger)row destinationBytesPerImage:(NSUInteger)image options:(NSUInteger)options {
    [self copyFromTexture:source sourceSlice:slice sourceLevel:level sourceOrigin:origin sourceSize:size toBuffer:destination
        destinationOffset:offset destinationBytesPerRow:row destinationBytesPerImage:image];
}
- (void)copyFromTexture:(id)source sourceSlice:(NSUInteger)sourceSlice sourceLevel:(NSUInteger)sourceLevel
           sourceOrigin:(MTLOrigin)sourceOrigin sourceSize:(MTLSize)size toTexture:(id)destination
       destinationSlice:(NSUInteger)destinationSlice destinationLevel:(NSUInteger)destinationLevel
      destinationOrigin:(MTLOrigin)destinationOrigin {
    qm_size extent = {size.width, size.height, size.depth};
    qm_origin from = {sourceOrigin.x, sourceOrigin.y, sourceOrigin.z};
    qm_origin to = {destinationOrigin.x, destinationOrigin.y, destinationOrigin.z};
    qm->blit_copy_texture(handle, qm_handle(source), sourceSlice, sourceLevel, from, extent, qm_handle(destination),
                          destinationSlice, destinationLevel, to);
}
- (void)copyFromTexture:(id)source sourceSlice:(NSUInteger)sourceSlice sourceLevel:(NSUInteger)sourceLevel
              toTexture:(id)destination destinationSlice:(NSUInteger)destinationSlice destinationLevel:(NSUInteger)destinationLevel
             sliceCount:(NSUInteger)slices levelCount:(NSUInteger)levels {
    qm->blit_copy_texture_slices(handle, qm_handle(source), sourceSlice, sourceLevel, qm_handle(destination),
                                 destinationSlice, destinationLevel, slices, levels);
}
- (void)copyFromTexture:(id)source toTexture:(id)destination {
    QMTexture *texture = source;
    if (![texture isKindOfClass:[QMTexture class]])
        return;
    NSUInteger slices = texture->info.texture_type == 5 ? 6 * texture->info.array_length : texture->info.array_length;
    [self copyFromTexture:source sourceSlice:0 sourceLevel:0 toTexture:destination destinationSlice:0 destinationLevel:0
               sliceCount:slices levelCount:texture->info.mipmap_level_count];
}
- (void)generateMipmapsForTexture:(id)texture { qm->blit_generate_mipmaps(handle, qm_handle(texture)); }
- (void)synchronizeResource:(id)resource { qm->blit_synchronize(handle, qm_handle(resource)); }
- (void)synchronizeTexture:(id)texture slice:(NSUInteger)slice level:(NSUInteger)level {
    qm->blit_synchronize(handle, qm_handle(texture));
}
- (void)optimizeContentsForGPUAccess:(id)texture {}
- (void)optimizeContentsForCPUAccess:(id)texture {}
@end

/* --- Compute, with the builtin upload kernels as blits ------------------------- */

#define COMPUTE_SLOTS 31
#define COMPUTE_TEXTURE_SLOTS 128

@interface QMComputeCommandEncoder : QMEncoder {
@public
    QMComputePipelineState *pipeline;
    id buffers[COMPUTE_SLOTS];
    NSUInteger offsets[COMPUTE_SLOTS];
    void *bytes[COMPUTE_SLOTS];
    NSUInteger byte_lengths[COMPUTE_SLOTS], byte_capacities[COMPUTE_SLOTS];
    BOOL inline_bytes[COMPUTE_SLOTS];
    id textures[COMPUTE_TEXTURE_SLOTS];
    NSUInteger threadgroup_lengths[31];
    uint32_t threadgroup_set;
    id samplers[16];
    BOOL ended;
}
@end

@implementation QMComputeCommandEncoder
- (void)dealloc {
    [pipeline release];
    for (unsigned index = 0; index < COMPUTE_SLOTS; index++) {
        [buffers[index] release];
        free(bytes[index]);
    }
    for (unsigned index = 0; index < COMPUTE_TEXTURE_SLOTS; index++)
        [textures[index] release];
    for (unsigned index = 0; index < 16; index++)
        [samplers[index] release];
    [super dealloc];
}
/* The host encoder, made at the first dispatch after a builtin upload or at
 * the first one at all, with every binding set again. */
- (void *)encoder {
    if (handle || ended)
        return handle;
    handle = qm->compute_encoder_new(buffer->handle);
    if (!handle) {
        qm_error("computeCommandEncoder");
        return 0;
    }
    if (pipeline && pipeline->handle)
        qm->compute_set_pipeline(handle, pipeline->handle);
    for (unsigned index = 0; index < COMPUTE_SLOTS; index++) {
        if (inline_bytes[index])
            qm->compute_set_bytes(handle, bytes[index], byte_lengths[index], index);
        else if (buffers[index])
            qm->compute_set_buffer(handle, qm_handle(buffers[index]), offsets[index], index);
    }
    for (unsigned index = 0; index < COMPUTE_TEXTURE_SLOTS; index++)
        if (textures[index]) qm->compute_set_texture(handle, qm_handle(textures[index]), index);
    for (unsigned index = 0; index < 31; index++)
        if (threadgroup_set & (1u << index))
            qm->compute_set_threadgroup_memory(handle, threadgroup_lengths[index], index);
    for (unsigned index = 0; index < 16; index++)
        if (samplers[index])
            qm->compute_set_sampler(handle, qm_handle(samplers[index]), index);
    return handle;
}
- (void)endEncoding {
    if (handle)
        qm->compute_end(handle);
    ended = YES;
}
- (void)setComputePipelineState:(id)state {
    [state retain];
    [pipeline release];
    pipeline = state;
    if (handle && pipeline->handle)
        qm->compute_set_pipeline(handle, pipeline->handle);
}
- (void)setBuffer:(id)value offset:(NSUInteger)offset atIndex:(NSUInteger)index {
    if (index >= COMPUTE_SLOTS)
        return;
    [value retain];
    [buffers[index] release];
    buffers[index] = value;
    offsets[index] = offset;
    inline_bytes[index] = NO;
    byte_lengths[index] = 0;
    if (handle)
        qm->compute_set_buffer(handle, qm_handle(value), offset, (uint32_t)index);
}
- (void)setBuffers:(const id *)values offsets:(const NSUInteger *)values_offsets withRange:(NSRange)range {
    for (NSUInteger index = 0; index < range.length; index++)
        [self setBuffer:values[index] offset:values_offsets[index] atIndex:range.location + index];
}
- (void)setBufferOffset:(NSUInteger)offset atIndex:(NSUInteger)index {
    if (index >= COMPUTE_SLOTS)
        return;
    offsets[index] = offset;
    if (handle)
        qm->compute_set_buffer_offset(handle, offset, (uint32_t)index);
}
- (void)setBytes:(const void *)value length:(NSUInteger)length atIndex:(NSUInteger)index {
    if (index >= COMPUTE_SLOTS)
        return;
    if (length > 4096 || (length && !value)) {
        qm_log("[Quadra Metal] invalid inline byte span");
        return;
    }
    if (byte_capacities[index] < (length ? length : 1)) {
        NSUInteger capacity = 16;
        while (capacity < length) capacity *= 2;
        void *grown = realloc(bytes[index], capacity);
        if (!grown) { qm_log("[Quadra Metal] inline byte allocation failed"); return; }
        bytes[index] = grown;
        byte_capacities[index] = capacity;
    }
    if (length) memcpy(bytes[index], value, length);
    byte_lengths[index] = length;
    inline_bytes[index] = YES;
    [buffers[index] release];
    buffers[index] = nil;
    if (handle)
        qm->compute_set_bytes(handle, value, length, (uint32_t)index);
}
- (void)setTexture:(id)texture atIndex:(NSUInteger)index {
    if (index >= COMPUTE_TEXTURE_SLOTS)
        return;
    [texture retain];
    [textures[index] release];
    textures[index] = texture;
    if (handle)
        qm->compute_set_texture(handle, qm_handle(texture), (uint32_t)index);
}
- (void)setTextures:(const id *)values withRange:(NSRange)range {
    for (NSUInteger index = 0; index < range.length; index++)
        [self setTexture:values[index] atIndex:range.location + index];
}
- (void)setSamplerState:(id)sampler atIndex:(NSUInteger)index {
    if (index >= 16)
        return;
    [sampler retain];
    [samplers[index] release];
    samplers[index] = sampler;
    if (handle)
        qm->compute_set_sampler(handle, qm_handle(sampler), (uint32_t)index);
}
- (void)setSamplerStates:(const id *)values withRange:(NSRange)range {
    for (NSUInteger index = 0; index < range.length; index++)
        [self setSamplerState:values[index] atIndex:range.location + index];
}
- (void)setThreadgroupMemoryLength:(NSUInteger)length atIndex:(NSUInteger)index {
    if (index >= 31) { qm_log("[Quadra Metal] invalid threadgroup memory index"); return; }
    threadgroup_lengths[index] = length;
    threadgroup_set |= 1u << index;
    if (handle) qm->compute_set_threadgroup_memory(handle, length, (uint32_t)index);
}
- (void)useResource:(id)resource usage:(NSUInteger)usage { qm->encoder_use_resource([self encoder], qm_handle(resource), (uint32_t)usage, 3); }
- (void)useResources:(const id *)resources count:(NSUInteger)count usage:(NSUInteger)usage {
    for (NSUInteger i = 0; i < count; i++) [self useResource:resources[i] usage:usage];
}
- (void)updateFence:(id)fence { qm->encoder_fence([self encoder], qm_handle(fence), 1, 3); }
- (void)waitForFence:(id)fence { qm->encoder_fence([self encoder], qm_handle(fence), 0, 3); }
- (void)useHeap:(id)heap {}
- (void)memoryBarrierWithScope:(NSUInteger)scope {
    void *encoder = [self encoder];
    if (encoder) qm->compute_barrier(encoder, (uint32_t)scope);
}
- (void)memoryBarrierWithResources:(const id *)resources count:(NSUInteger)count {
    [self memoryBarrierWithScope:3]; /* A global buffer/texture barrier covers these resources. */
}

/* blitTexture*: params at buffer 0 (uint3 offset, uint3 size, uint2 stride,
 * in elements), bytes at buffer 1, the texture at 0. */
- (void)runBuiltin:(int)kind {
    const uint32_t *params = 0;
    if (inline_bytes[0] && byte_lengths[0] >= 40)
        params = bytes[0];
    else if (buffers[0] && ((QMBuffer *)buffers[0])->contents)
        params = (const uint32_t *)((char *)((QMBuffer *)buffers[0])->contents + offsets[0]);
    QMTexture *texture = textures[0];
    if (!params || !buffers[1] || ![texture isKindOfClass:[QMTexture class]]) {
        log_once("[Quadra Metal] builtin upload without its parameters, input or texture");
        return;
    }
    NSUInteger element = kind == BUILTIN_3D_RGBA8 ? 4 : kind == BUILTIN_3D_RG8 ? 2 : 1;
    NSUInteger expected = kind == BUILTIN_3D_RGBA8 ? 70 : kind == BUILTIN_3D_RG8 ? 30 : 10;
    if (texture->info.pixel_format != expected) {
        char text[160];
        snprintf(text, sizeof text, "[Quadra Metal] builtin upload %d into pixel format %llu: copied as raw bytes", kind,
                 (unsigned long long)texture->info.pixel_format);
        log_once(text);
    }
    qm_origin origin = {params[0], params[1], kind == BUILTIN_2D_R8 ? 0 : params[2]};
    qm_size size = {params[4], params[5], kind == BUILTIN_2D_R8 ? 1 : params[6]};
    uint64_t row = (uint64_t)params[8] * element, image = (uint64_t)params[9] * element;
    if (kind == BUILTIN_2D_R8)
        image = row * size.height;
    if (handle) {
        qm->compute_end(handle);
        qm->release(handle);
        handle = 0;
    }
    void *blit = qm->blit_encoder_new(buffer->handle);
    if (!blit) {
        qm_error("blitCommandEncoder for a builtin upload");
        return;
    }
    qm->blit_copy_buffer_to_texture(blit, qm_handle(buffers[1]), offsets[1], row, image, size, texture->handle, 0, 0, origin);
    qm->blit_end(blit);
    qm->release(blit);
}
- (void)dispatchThreadgroups:(MTLSize)groups threadsPerThreadgroup:(MTLSize)threads {
    if (pipeline && pipeline->builtin) {
        [self runBuiltin:pipeline->builtin];
        return;
    }
    void *encoder = [self encoder];
    if (!encoder)
        return;
    qm_size a = {groups.width, groups.height, groups.depth}, b = {threads.width, threads.height, threads.depth};
    qm->compute_dispatch(encoder, a, b);
}
- (void)dispatchThreads:(MTLSize)threads threadsPerThreadgroup:(MTLSize)group {
    if (pipeline && pipeline->builtin) { [self runBuiltin:pipeline->builtin]; return; }
    void *encoder = [self encoder];
    if (!encoder) return;
    qm_size a = {threads.width, threads.height, threads.depth}, b = {group.width, group.height, group.depth};
    qm->compute_dispatch_threads(encoder, a, b);
}
@end

@interface QMCommandBuffer (Encoders)
@end

@implementation QMCommandBuffer (Encoders)
- (id)renderCommandEncoderWithDescriptor:(id)descriptor {
    qm_render_pass_desc value;
    qm_render_pass_desc_from(descriptor, &value);
    QMRenderCommandEncoder *encoder = [QMRenderCommandEncoder new];
    encoder->buffer = [self retain];
    encoder->handle = qm->render_encoder_new(handle, &value);
    if (!encoder->handle)
        qm_error("renderCommandEncoderWithDescriptor");
    return [encoder autorelease];
}
- (id)blitCommandEncoder {
    QMBlitCommandEncoder *encoder = [QMBlitCommandEncoder new];
    encoder->buffer = [self retain];
    encoder->handle = qm->blit_encoder_new(handle);
    if (!encoder->handle)
        qm_error("blitCommandEncoder");
    return [encoder autorelease];
}
- (id)blitCommandEncoderWithDescriptor:(id)descriptor { return [self blitCommandEncoder]; }
- (id)computeCommandEncoder {
    QMComputeCommandEncoder *encoder = [QMComputeCommandEncoder new];
    encoder->buffer = [self retain];
    return [encoder autorelease];
}
- (id)computeCommandEncoderWithDispatchType:(NSUInteger)type { return [self computeCommandEncoder]; }
@end

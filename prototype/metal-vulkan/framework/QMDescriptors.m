/* Metal's descriptor classes, under their own names: RobloxPlayer binds to
 * them. Plain value objects with Metal's defaults (macOS). */
#include "qm.h"

#define VALUE_PROPERTY(type, getter, setter, field) \
    - (type)getter { return field; } \
    - (void)setter:(type)qm_new_value { field = qm_new_value; }
#define OBJECT_PROPERTY(getter, setter, field) \
    - (id)getter { return field; } \
    - (void)setter:(id)qm_new_value { id old = field; field = [qm_new_value retain]; [old release]; }

/* --- Textures and samplers ------------------------------------------------ */

@interface MTLTextureDescriptor : NSObject {
@public
    NSUInteger textureType, pixelFormat, width, height, depth, mipmapLevelCount, sampleCount, arrayLength;
    NSUInteger resourceOptions, usage;
    BOOL allowGPUOptimizedContents;
    unsigned swizzle;
}
@end

@implementation MTLTextureDescriptor
- (id)init {
    if ((self = [super init])) {
        textureType = 2; /* 2D */
        pixelFormat = 70; /* RGBA8Unorm */
        width = height = depth = mipmapLevelCount = sampleCount = arrayLength = 1;
        resourceOptions = 1 << 4; /* Managed: macOS's default for textures */
        usage = 1;                /* ShaderRead */
        allowGPUOptimizedContents = YES;
        swizzle = 0x05040302;     /* identity RGBA */
    }
    return self;
}
static NSUInteger levels_for(NSUInteger width, NSUInteger height) {
    NSUInteger size = width > height ? width : height, levels = 1;
    while (size > 1) {
        size >>= 1;
        levels++;
    }
    return levels;
}
+ (id)texture2DDescriptorWithPixelFormat:(NSUInteger)format width:(NSUInteger)w height:(NSUInteger)h mipmapped:(BOOL)mipmapped {
    MTLTextureDescriptor *descriptor = [[self new] autorelease];
    descriptor->pixelFormat = format;
    descriptor->width = w;
    descriptor->height = h;
    descriptor->mipmapLevelCount = mipmapped ? levels_for(w, h) : 1;
    return descriptor;
}
+ (id)textureCubeDescriptorWithPixelFormat:(NSUInteger)format size:(NSUInteger)size mipmapped:(BOOL)mipmapped {
    MTLTextureDescriptor *descriptor = [self texture2DDescriptorWithPixelFormat:format width:size height:size mipmapped:mipmapped];
    descriptor->textureType = 5;
    return descriptor;
}
+ (id)textureBufferDescriptorWithPixelFormat:(NSUInteger)format width:(NSUInteger)w resourceOptions:(NSUInteger)options usage:(NSUInteger)u {
    MTLTextureDescriptor *descriptor = [self texture2DDescriptorWithPixelFormat:format width:w height:1 mipmapped:NO];
    descriptor->textureType = 9;
    descriptor->resourceOptions = options;
    descriptor->usage = u;
    return descriptor;
}
- (id)copyWithZone:(NSZone *)zone {
    MTLTextureDescriptor *copy = [[MTLTextureDescriptor alloc] init];
    copy->textureType = textureType;
    copy->pixelFormat = pixelFormat;
    copy->width = width;
    copy->height = height;
    copy->depth = depth;
    copy->mipmapLevelCount = mipmapLevelCount;
    copy->sampleCount = sampleCount;
    copy->arrayLength = arrayLength;
    copy->resourceOptions = resourceOptions;
    copy->usage = usage;
    copy->allowGPUOptimizedContents = allowGPUOptimizedContents;
    copy->swizzle = swizzle;
    return copy;
}
VALUE_PROPERTY(NSUInteger, textureType, setTextureType, textureType)
VALUE_PROPERTY(NSUInteger, pixelFormat, setPixelFormat, pixelFormat)
VALUE_PROPERTY(NSUInteger, width, setWidth, width)
VALUE_PROPERTY(NSUInteger, height, setHeight, height)
VALUE_PROPERTY(NSUInteger, depth, setDepth, depth)
VALUE_PROPERTY(NSUInteger, mipmapLevelCount, setMipmapLevelCount, mipmapLevelCount)
VALUE_PROPERTY(NSUInteger, sampleCount, setSampleCount, sampleCount)
VALUE_PROPERTY(NSUInteger, arrayLength, setArrayLength, arrayLength)
VALUE_PROPERTY(NSUInteger, resourceOptions, setResourceOptions, resourceOptions)
VALUE_PROPERTY(NSUInteger, usage, setUsage, usage)
VALUE_PROPERTY(BOOL, allowGPUOptimizedContents, setAllowGPUOptimizedContents, allowGPUOptimizedContents)
VALUE_PROPERTY(unsigned, swizzle, setSwizzle, swizzle)
- (NSUInteger)cpuCacheMode { return resourceOptions & 0xf; }
- (void)setCpuCacheMode:(NSUInteger)value { resourceOptions = (resourceOptions & ~0xfUL) | (value & 0xf); }
- (NSUInteger)storageMode { return (resourceOptions >> 4) & 0xf; }
- (void)setStorageMode:(NSUInteger)value { resourceOptions = (resourceOptions & ~0xf0UL) | ((value & 0xf) << 4); }
- (NSUInteger)hazardTrackingMode { return (resourceOptions >> 8) & 0x3; }
- (void)setHazardTrackingMode:(NSUInteger)value { resourceOptions = (resourceOptions & ~0x300UL) | ((value & 3) << 8); }
@end

void qm_texture_desc_from(id object, qm_texture_desc *out) {
    MTLTextureDescriptor *descriptor = object;
    memset(out, 0, sizeof *out);
    out->texture_type = descriptor->textureType;
    out->pixel_format = descriptor->pixelFormat;
    out->width = descriptor->width;
    out->height = descriptor->height;
    out->depth = descriptor->depth;
    out->mipmap_level_count = descriptor->mipmapLevelCount;
    out->sample_count = descriptor->sampleCount;
    out->array_length = descriptor->arrayLength;
    out->usage = descriptor->usage;
    out->resource_options = descriptor->resourceOptions;
    out->allow_gpu_optimized_contents = descriptor->allowGPUOptimizedContents;
}

@interface MTLSamplerDescriptor : NSObject {
@public
    qm_sampler_desc value;
    id label;
}
@end

@implementation MTLSamplerDescriptor
- (id)init {
    if ((self = [super init])) {
        value.normalized_coordinates = 1;
        value.lod_max_clamp = 3.40282347e+38f;
        value.max_anisotropy = 1;
    }
    return self;
}
- (void)dealloc { [label release]; [super dealloc]; }
- (id)copyWithZone:(NSZone *)zone {
    MTLSamplerDescriptor *copy = [[MTLSamplerDescriptor alloc] init];
    copy->value = value;
    copy->label = [label retain];
    return copy;
}
VALUE_PROPERTY(NSUInteger, minFilter, setMinFilter, value.min_filter)
VALUE_PROPERTY(NSUInteger, magFilter, setMagFilter, value.mag_filter)
VALUE_PROPERTY(NSUInteger, mipFilter, setMipFilter, value.mip_filter)
VALUE_PROPERTY(NSUInteger, maxAnisotropy, setMaxAnisotropy, value.max_anisotropy)
VALUE_PROPERTY(NSUInteger, sAddressMode, setSAddressMode, value.s_address_mode)
VALUE_PROPERTY(NSUInteger, tAddressMode, setTAddressMode, value.t_address_mode)
VALUE_PROPERTY(NSUInteger, rAddressMode, setRAddressMode, value.r_address_mode)
VALUE_PROPERTY(NSUInteger, borderColor, setBorderColor, value.border_color)
VALUE_PROPERTY(BOOL, normalizedCoordinates, setNormalizedCoordinates, value.normalized_coordinates)
VALUE_PROPERTY(float, lodMinClamp, setLodMinClamp, value.lod_min_clamp)
VALUE_PROPERTY(float, lodMaxClamp, setLodMaxClamp, value.lod_max_clamp)
VALUE_PROPERTY(BOOL, lodAverage, setLodAverage, value.lod_average)
VALUE_PROPERTY(NSUInteger, compareFunction, setCompareFunction, value.compare_function)
VALUE_PROPERTY(BOOL, supportArgumentBuffers, setSupportArgumentBuffers, value.support_argument_buffers)
OBJECT_PROPERTY(label, setLabel, label)
@end

const qm_sampler_desc *qm_sampler_desc_of(id object) {
    return &((MTLSamplerDescriptor *)object)->value;
}

/* --- Depth and stencil ---------------------------------------------------- */

@interface MTLStencilDescriptor : NSObject {
@public
    qm_stencil_desc value;
}
@end

@implementation MTLStencilDescriptor
- (id)init {
    if ((self = [super init])) {
        value.compare_function = 7; /* Always */
        value.read_mask = value.write_mask = 0xffffffffu;
    }
    return self;
}
- (id)copyWithZone:(NSZone *)zone {
    MTLStencilDescriptor *copy = [[MTLStencilDescriptor alloc] init];
    copy->value = value;
    return copy;
}
VALUE_PROPERTY(NSUInteger, stencilCompareFunction, setStencilCompareFunction, value.compare_function)
VALUE_PROPERTY(NSUInteger, stencilFailureOperation, setStencilFailureOperation, value.failure_operation)
VALUE_PROPERTY(NSUInteger, depthFailureOperation, setDepthFailureOperation, value.depth_failure_operation)
VALUE_PROPERTY(NSUInteger, depthStencilPassOperation, setDepthStencilPassOperation, value.pass_operation)
VALUE_PROPERTY(unsigned, readMask, setReadMask, value.read_mask)
VALUE_PROPERTY(unsigned, writeMask, setWriteMask, value.write_mask)
@end

@interface MTLDepthStencilDescriptor : NSObject {
@public
    NSUInteger depthCompareFunction;
    BOOL depthWriteEnabled;
    MTLStencilDescriptor *front, *back;
    id label;
}
@end

@implementation MTLDepthStencilDescriptor
- (id)init {
    if ((self = [super init]))
        depthCompareFunction = 7; /* Always */
    return self;
}
- (void)dealloc {
    [front release];
    [back release];
    [label release];
    [super dealloc];
}
- (id)copyWithZone:(NSZone *)zone {
    MTLDepthStencilDescriptor *copy = [[MTLDepthStencilDescriptor alloc] init];
    copy->depthCompareFunction = depthCompareFunction;
    copy->depthWriteEnabled = depthWriteEnabled;
    copy->front = [front copy];
    copy->back = [back copy];
    copy->label = [label retain];
    return copy;
}
VALUE_PROPERTY(NSUInteger, depthCompareFunction, setDepthCompareFunction, depthCompareFunction)
VALUE_PROPERTY(BOOL, isDepthWriteEnabled, setDepthWriteEnabled, depthWriteEnabled)
- (BOOL)depthWriteEnabled { return depthWriteEnabled; }
OBJECT_PROPERTY(frontFaceStencil, setFrontFaceStencil, front)
OBJECT_PROPERTY(backFaceStencil, setBackFaceStencil, back)
OBJECT_PROPERTY(label, setLabel, label)
@end

void qm_depth_stencil_desc_from(id object, qm_depth_stencil_desc *out) {
    MTLDepthStencilDescriptor *descriptor = object;
    qm_stencil_desc disabled = {7, 0, 0, 0, 0xffffffffu, 0xffffffffu};
    out->depth_compare_function = (uint32_t)descriptor->depthCompareFunction;
    out->depth_write_enabled = descriptor->depthWriteEnabled;
    out->front = descriptor->front ? descriptor->front->value : disabled;
    out->back = descriptor->back ? descriptor->back->value : disabled;
}

/* --- Vertex descriptors ---------------------------------------------------- */

@interface MTLVertexAttributeDescriptor : NSObject {
@public
    qm_vertex_attribute value;
}
@end

@implementation MTLVertexAttributeDescriptor
- (id)copyWithZone:(NSZone *)zone {
    MTLVertexAttributeDescriptor *copy = [[MTLVertexAttributeDescriptor alloc] init];
    copy->value = value;
    return copy;
}
- (NSUInteger)format { return value.format; }
- (void)setFormat:(NSUInteger)format { value.format = (uint32_t)format; value.present = 1; }
- (NSUInteger)offset { return value.offset; }
- (void)setOffset:(NSUInteger)offset { value.offset = (uint32_t)offset; value.present = 1; }
- (NSUInteger)bufferIndex { return value.buffer_index; }
- (void)setBufferIndex:(NSUInteger)index { value.buffer_index = (uint32_t)index; value.present = 1; }
@end

@interface MTLVertexBufferLayoutDescriptor : NSObject {
@public
    qm_vertex_layout value;
}
@end

@implementation MTLVertexBufferLayoutDescriptor
- (id)init {
    if ((self = [super init])) {
        value.step_function = 1; /* PerVertex */
        value.step_rate = 1;
    }
    return self;
}
- (id)copyWithZone:(NSZone *)zone {
    MTLVertexBufferLayoutDescriptor *copy = [[MTLVertexBufferLayoutDescriptor alloc] init];
    copy->value = value;
    return copy;
}
- (NSUInteger)stride { return value.stride; }
- (void)setStride:(NSUInteger)stride { value.stride = (uint32_t)stride; value.present = 1; }
- (NSUInteger)stepFunction { return value.step_function; }
- (void)setStepFunction:(NSUInteger)function { value.step_function = (uint32_t)function; value.present = 1; }
- (NSUInteger)stepRate { return value.step_rate; }
- (void)setStepRate:(NSUInteger)rate { value.step_rate = (uint32_t)rate; value.present = 1; }
@end

/* An array of descriptors made on first use, as Metal's are. */
@interface QMDescriptorArray : NSObject {
@public
    Class kind;
    NSUInteger count;
    id items[QM_VERTEX_SLOTS];
}
@end

@implementation QMDescriptorArray
- (id)initWithClass:(Class)cls count:(NSUInteger)n {
    if ((self = [super init])) {
        kind = cls;
        count = n;
    }
    return self;
}
- (void)dealloc {
    for (NSUInteger index = 0; index < count; index++)
        [items[index] release];
    [super dealloc];
}
- (id)copyArray {
    QMDescriptorArray *copy = [[[self class] alloc] initWithClass:kind count:count];
    for (NSUInteger index = 0; index < count; index++)
        copy->items[index] = [items[index] copy];
    return copy;
}
- (id)objectAtIndexedSubscript:(NSUInteger)index {
    if (index >= count)
        return nil;
    if (!items[index])
        items[index] = [[kind alloc] init];
    return items[index];
}
- (void)setObject:(id)object atIndexedSubscript:(NSUInteger)index {
    if (index >= count)
        return;
    id old = items[index];
    items[index] = object ? [object copy] : nil;
    [old release];
}
- (id)existing:(NSUInteger)index { return index < count ? items[index] : nil; }
@end

@interface MTLVertexAttributeDescriptorArray : QMDescriptorArray
@end
@implementation MTLVertexAttributeDescriptorArray
@end
@interface MTLVertexBufferLayoutDescriptorArray : QMDescriptorArray
@end
@implementation MTLVertexBufferLayoutDescriptorArray
@end

@interface MTLVertexDescriptor : NSObject {
@public
    QMDescriptorArray *attributes, *layouts;
}
@end

@implementation MTLVertexDescriptor
+ (id)vertexDescriptor { return [[self new] autorelease]; }
- (id)init {
    if ((self = [super init])) {
        attributes = [[MTLVertexAttributeDescriptorArray alloc] initWithClass:[MTLVertexAttributeDescriptor class] count:QM_VERTEX_SLOTS];
        layouts = [[MTLVertexBufferLayoutDescriptorArray alloc] initWithClass:[MTLVertexBufferLayoutDescriptor class] count:QM_VERTEX_SLOTS];
    }
    return self;
}
- (void)dealloc {
    [attributes release];
    [layouts release];
    [super dealloc];
}
- (id)copyWithZone:(NSZone *)zone {
    MTLVertexDescriptor *copy = [[MTLVertexDescriptor alloc] init];
    [copy->attributes release];
    [copy->layouts release];
    copy->attributes = [attributes copyArray];
    copy->layouts = [layouts copyArray];
    return copy;
}
- (id)attributes { return attributes; }
- (id)layouts { return layouts; }
- (void)reset {
    [attributes release];
    [layouts release];
    attributes = [[MTLVertexAttributeDescriptorArray alloc] initWithClass:[MTLVertexAttributeDescriptor class] count:QM_VERTEX_SLOTS];
    layouts = [[MTLVertexBufferLayoutDescriptorArray alloc] initWithClass:[MTLVertexBufferLayoutDescriptor class] count:QM_VERTEX_SLOTS];
}
@end

/* --- Render pipelines ------------------------------------------------------ */

@interface MTLRenderPipelineColorAttachmentDescriptor : NSObject {
@public
    qm_color_attachment_state value;
}
@end

@implementation MTLRenderPipelineColorAttachmentDescriptor
- (id)init {
    if ((self = [super init])) {
        value.source_rgb = value.source_alpha = 1; /* One */
        value.write_mask = 0xf;
    }
    return self;
}
- (id)copyWithZone:(NSZone *)zone {
    MTLRenderPipelineColorAttachmentDescriptor *copy = [[MTLRenderPipelineColorAttachmentDescriptor alloc] init];
    copy->value = value;
    return copy;
}
VALUE_PROPERTY(NSUInteger, pixelFormat, setPixelFormat, value.pixel_format)
VALUE_PROPERTY(BOOL, isBlendingEnabled, setBlendingEnabled, value.blending_enabled)
- (BOOL)blendingEnabled { return value.blending_enabled; }
VALUE_PROPERTY(NSUInteger, sourceRGBBlendFactor, setSourceRGBBlendFactor, value.source_rgb)
VALUE_PROPERTY(NSUInteger, destinationRGBBlendFactor, setDestinationRGBBlendFactor, value.destination_rgb)
VALUE_PROPERTY(NSUInteger, rgbBlendOperation, setRgbBlendOperation, value.rgb_operation)
VALUE_PROPERTY(NSUInteger, sourceAlphaBlendFactor, setSourceAlphaBlendFactor, value.source_alpha)
VALUE_PROPERTY(NSUInteger, destinationAlphaBlendFactor, setDestinationAlphaBlendFactor, value.destination_alpha)
VALUE_PROPERTY(NSUInteger, alphaBlendOperation, setAlphaBlendOperation, value.alpha_operation)
VALUE_PROPERTY(NSUInteger, writeMask, setWriteMask, value.write_mask)
@end

@interface MTLRenderPipelineColorAttachmentDescriptorArray : QMDescriptorArray
@end
@implementation MTLRenderPipelineColorAttachmentDescriptorArray
@end

@interface MTLRenderPipelineDescriptor : NSObject {
@public
    id label, vertexFunction, fragmentFunction, vertexDescriptor;
    QMDescriptorArray *colorAttachments;
    NSUInteger depthFormat, stencilFormat, sampleCount, inputPrimitiveTopology;
    BOOL alphaToCoverage, alphaToOne, rasterizationEnabled, supportIndirectCommandBuffers;
}
@end

@implementation MTLRenderPipelineDescriptor
- (id)init {
    if ((self = [super init])) {
        colorAttachments = [[MTLRenderPipelineColorAttachmentDescriptorArray alloc]
            initWithClass:[MTLRenderPipelineColorAttachmentDescriptor class] count:8];
        sampleCount = 1;
        rasterizationEnabled = YES;
    }
    return self;
}
- (void)dealloc {
    [label release];
    [vertexFunction release];
    [fragmentFunction release];
    [vertexDescriptor release];
    [colorAttachments release];
    [super dealloc];
}
- (id)copyWithZone:(NSZone *)zone {
    MTLRenderPipelineDescriptor *copy = [[MTLRenderPipelineDescriptor alloc] init];
    [copy->colorAttachments release];
    copy->colorAttachments = [colorAttachments copyArray];
    copy->label = [label retain];
    copy->vertexFunction = [vertexFunction retain];
    copy->fragmentFunction = [fragmentFunction retain];
    copy->vertexDescriptor = [vertexDescriptor copy];
    copy->depthFormat = depthFormat;
    copy->stencilFormat = stencilFormat;
    copy->sampleCount = sampleCount;
    copy->inputPrimitiveTopology = inputPrimitiveTopology;
    copy->alphaToCoverage = alphaToCoverage;
    copy->alphaToOne = alphaToOne;
    copy->rasterizationEnabled = rasterizationEnabled;
    return copy;
}
- (void)reset {
    [vertexFunction release];
    [fragmentFunction release];
    [vertexDescriptor release];
    vertexFunction = fragmentFunction = vertexDescriptor = nil;
    [colorAttachments release];
    colorAttachments = [[MTLRenderPipelineColorAttachmentDescriptorArray alloc]
        initWithClass:[MTLRenderPipelineColorAttachmentDescriptor class] count:8];
    depthFormat = stencilFormat = inputPrimitiveTopology = 0;
    sampleCount = 1;
    alphaToCoverage = alphaToOne = NO;
    rasterizationEnabled = YES;
}
OBJECT_PROPERTY(label, setLabel, label)
OBJECT_PROPERTY(vertexFunction, setVertexFunction, vertexFunction)
OBJECT_PROPERTY(fragmentFunction, setFragmentFunction, fragmentFunction)
- (id)vertexDescriptor { return vertexDescriptor; }
- (void)setVertexDescriptor:(id)value { id old = vertexDescriptor; vertexDescriptor = [value copy]; [old release]; }
- (id)colorAttachments { return colorAttachments; }
VALUE_PROPERTY(NSUInteger, depthAttachmentPixelFormat, setDepthAttachmentPixelFormat, depthFormat)
VALUE_PROPERTY(NSUInteger, stencilAttachmentPixelFormat, setStencilAttachmentPixelFormat, stencilFormat)
VALUE_PROPERTY(NSUInteger, sampleCount, setSampleCount, sampleCount)
VALUE_PROPERTY(NSUInteger, rasterSampleCount, setRasterSampleCount, sampleCount)
VALUE_PROPERTY(NSUInteger, inputPrimitiveTopology, setInputPrimitiveTopology, inputPrimitiveTopology)
VALUE_PROPERTY(BOOL, isAlphaToCoverageEnabled, setAlphaToCoverageEnabled, alphaToCoverage)
VALUE_PROPERTY(BOOL, isAlphaToOneEnabled, setAlphaToOneEnabled, alphaToOne)
VALUE_PROPERTY(BOOL, isRasterizationEnabled, setRasterizationEnabled, rasterizationEnabled)
VALUE_PROPERTY(BOOL, supportIndirectCommandBuffers, setSupportIndirectCommandBuffers, supportIndirectCommandBuffers)
- (BOOL)alphaToCoverageEnabled { return alphaToCoverage; }
- (BOOL)rasterizationEnabled { return rasterizationEnabled; }
@end

void qm_render_pipeline_desc_from(id object, qm_render_pipeline_desc *out) {
    MTLRenderPipelineDescriptor *descriptor = object;
    memset(out, 0, sizeof *out);
    out->vertex_function = qm_handle(descriptor->vertexFunction);
    out->fragment_function = qm_handle(descriptor->fragmentFunction);
    MTLVertexDescriptor *vertex = descriptor->vertexDescriptor;
    if (vertex) {
        out->has_vertex_descriptor = 1;
        for (unsigned index = 0; index < QM_VERTEX_SLOTS; index++) {
            MTLVertexAttributeDescriptor *attribute = [vertex->attributes existing:index];
            MTLVertexBufferLayoutDescriptor *layout = [vertex->layouts existing:index];
            if (attribute)
                out->attributes[index] = attribute->value;
            if (layout)
                out->layouts[index] = layout->value;
        }
    }
    for (unsigned index = 0; index < 8; index++) {
        MTLRenderPipelineColorAttachmentDescriptor *color = [descriptor->colorAttachments existing:index];
        if (color)
            out->color[index] = color->value;
    }
    out->depth_format = descriptor->depthFormat;
    out->stencil_format = descriptor->stencilFormat;
    out->sample_count = (uint32_t)descriptor->sampleCount;
    out->alpha_to_coverage = descriptor->alphaToCoverage;
    out->alpha_to_one = descriptor->alphaToOne;
    out->rasterization_enabled = descriptor->rasterizationEnabled;
    out->input_primitive_topology = (uint32_t)descriptor->inputPrimitiveTopology;
    out->label = descriptor->label ? [descriptor->label UTF8String] : 0;
}

/* --- Render passes ------------------------------------------------------- */

@interface MTLRenderPassAttachmentDescriptor : NSObject {
@public
    id texture, resolveTexture;
    qm_attachment value;
}
@end

@implementation MTLRenderPassAttachmentDescriptor
- (void)dealloc {
    [texture release];
    [resolveTexture release];
    [super dealloc];
}
- (id)copyWithZone:(NSZone *)zone {
    MTLRenderPassAttachmentDescriptor *copy = [[[self class] alloc] init];
    copy->value = value;
    copy->texture = [texture retain];
    copy->resolveTexture = [resolveTexture retain];
    return copy;
}
OBJECT_PROPERTY(texture, setTexture, texture)
OBJECT_PROPERTY(resolveTexture, setResolveTexture, resolveTexture)
VALUE_PROPERTY(NSUInteger, level, setLevel, value.level)
VALUE_PROPERTY(NSUInteger, slice, setSlice, value.slice)
VALUE_PROPERTY(NSUInteger, depthPlane, setDepthPlane, value.depth_plane)
VALUE_PROPERTY(NSUInteger, resolveLevel, setResolveLevel, value.resolve_level)
VALUE_PROPERTY(NSUInteger, resolveSlice, setResolveSlice, value.resolve_slice)
VALUE_PROPERTY(NSUInteger, resolveDepthPlane, setResolveDepthPlane, value.resolve_depth_plane)
VALUE_PROPERTY(NSUInteger, loadAction, setLoadAction, value.load_action)
VALUE_PROPERTY(NSUInteger, storeAction, setStoreAction, value.store_action)
- (NSUInteger)storeActionOptions { return 0; }
- (void)setStoreActionOptions:(NSUInteger)options {}
@end

@interface MTLRenderPassColorAttachmentDescriptor : MTLRenderPassAttachmentDescriptor
@end

@implementation MTLRenderPassColorAttachmentDescriptor
- (id)init {
    if ((self = [super init])) {
        value.store_action = 1; /* Store */
        value.clear[3] = 1.0;
    }
    return self;
}
- (MTLClearColor)clearColor {
    MTLClearColor color = {value.clear[0], value.clear[1], value.clear[2], value.clear[3]};
    return color;
}
- (void)setClearColor:(MTLClearColor)color {
    value.clear[0] = color.red;
    value.clear[1] = color.green;
    value.clear[2] = color.blue;
    value.clear[3] = color.alpha;
}
@end

@interface MTLRenderPassDepthAttachmentDescriptor : MTLRenderPassAttachmentDescriptor
@end

@implementation MTLRenderPassDepthAttachmentDescriptor
- (id)init {
    if ((self = [super init])) {
        value.load_action = 2; /* Clear */
        value.clear[0] = 1.0;
    }
    return self;
}
- (double)clearDepth { return value.clear[0]; }
- (void)setClearDepth:(double)depth { value.clear[0] = depth; }
- (NSUInteger)depthResolveFilter { return 0; }
- (void)setDepthResolveFilter:(NSUInteger)filter {}
@end

@interface MTLRenderPassStencilAttachmentDescriptor : MTLRenderPassAttachmentDescriptor
@end

@implementation MTLRenderPassStencilAttachmentDescriptor
- (id)init {
    if ((self = [super init]))
        value.load_action = 2; /* Clear */
    return self;
}
- (unsigned)clearStencil { return (unsigned)value.clear[0]; }
- (void)setClearStencil:(unsigned)stencil { value.clear[0] = stencil; }
- (NSUInteger)stencilResolveFilter { return 0; }
- (void)setStencilResolveFilter:(NSUInteger)filter {}
@end

@interface MTLRenderPassColorAttachmentDescriptorArray : QMDescriptorArray
@end
@implementation MTLRenderPassColorAttachmentDescriptorArray
@end

@interface MTLRenderPassDescriptor : NSObject {
@public
    QMDescriptorArray *colors;
    MTLRenderPassDepthAttachmentDescriptor *depth;
    MTLRenderPassStencilAttachmentDescriptor *stencil;
    id visibility;
    NSUInteger width, height, arrayLength, defaultSamples;
}
@end

@implementation MTLRenderPassDescriptor
+ (id)renderPassDescriptor { return [[self new] autorelease]; }
- (id)init {
    if ((self = [super init])) {
        colors = [[MTLRenderPassColorAttachmentDescriptorArray alloc]
            initWithClass:[MTLRenderPassColorAttachmentDescriptor class] count:8];
        depth = [[MTLRenderPassDepthAttachmentDescriptor alloc] init];
        stencil = [[MTLRenderPassStencilAttachmentDescriptor alloc] init];
    }
    return self;
}
- (void)dealloc {
    [colors release];
    [depth release];
    [stencil release];
    [visibility release];
    [super dealloc];
}
- (id)copyWithZone:(NSZone *)zone {
    MTLRenderPassDescriptor *copy = [[MTLRenderPassDescriptor alloc] init];
    [copy->colors release];
    [copy->depth release];
    [copy->stencil release];
    copy->colors = [colors copyArray];
    copy->depth = [depth copy];
    copy->stencil = [stencil copy];
    copy->visibility = [visibility retain];
    copy->width = width;
    copy->height = height;
    copy->arrayLength = arrayLength;
    copy->defaultSamples = defaultSamples;
    return copy;
}
- (id)colorAttachments { return colors; }
- (id)depthAttachment { return depth; }
- (void)setDepthAttachment:(id)value { id old = depth; depth = [value copy]; [old release]; }
- (id)stencilAttachment { return stencil; }
- (void)setStencilAttachment:(id)value { id old = stencil; stencil = [value copy]; [old release]; }
OBJECT_PROPERTY(visibilityResultBuffer, setVisibilityResultBuffer, visibility)
VALUE_PROPERTY(NSUInteger, renderTargetWidth, setRenderTargetWidth, width)
VALUE_PROPERTY(NSUInteger, renderTargetHeight, setRenderTargetHeight, height)
VALUE_PROPERTY(NSUInteger, renderTargetArrayLength, setRenderTargetArrayLength, arrayLength)
VALUE_PROPERTY(NSUInteger, defaultRasterSampleCount, setDefaultRasterSampleCount, defaultSamples)
@end

static void attachment_from(MTLRenderPassAttachmentDescriptor *attachment, qm_attachment *out) {
    if (!attachment)
        return;
    *out = attachment->value;
    out->texture = qm_handle(attachment->texture);
    out->resolve_texture = qm_handle(attachment->resolveTexture);
}

void qm_render_pass_desc_from(id object, qm_render_pass_desc *out) {
    MTLRenderPassDescriptor *descriptor = object;
    memset(out, 0, sizeof *out);
    for (unsigned index = 0; index < 8; index++)
        attachment_from([descriptor->colors existing:index], &out->color[index]);
    attachment_from(descriptor->depth, &out->depth);
    attachment_from(descriptor->stencil, &out->stencil);
    out->visibility_result_buffer = qm_handle(descriptor->visibility);
    out->render_target_width = descriptor->width;
    out->render_target_height = descriptor->height;
    out->render_target_array_length = descriptor->arrayLength;
    out->default_raster_sample_count = descriptor->defaultSamples;
}

/* The drawable texture of the first color attachment, for presentation. */
id qm_render_pass_color_texture(id object, unsigned index) {
    MTLRenderPassDescriptor *descriptor = object;
    MTLRenderPassAttachmentDescriptor *attachment = [descriptor->colors existing:index];
    return attachment ? attachment->texture : nil;
}

/* --- Compilation and capture ----------------------------------------------- */

@interface MTLCompileOptions : NSObject {
    id macros;
    BOOL fastMath;
    NSUInteger languageVersion;
}
@end

@implementation MTLCompileOptions
- (id)init {
    if ((self = [super init]))
        fastMath = YES;
    return self;
}
- (void)dealloc { [macros release]; [super dealloc]; }
- (id)copyWithZone:(NSZone *)zone { return [self retain]; }
OBJECT_PROPERTY(preprocessorMacros, setPreprocessorMacros, macros)
VALUE_PROPERTY(BOOL, fastMathEnabled, setFastMathEnabled, fastMath)
VALUE_PROPERTY(NSUInteger, languageVersion, setLanguageVersion, languageVersion)
@end

@interface QMCaptureScope : NSObject {
    id label;
}
@end

@implementation QMCaptureScope
- (void)dealloc { [label release]; [super dealloc]; }
- (void)beginScope {}
- (void)endScope {}
- (id)device { return qm_device; }
OBJECT_PROPERTY(label, setLabel, label)
@end

@interface MTLCaptureDescriptor : NSObject {
    id object, url;
    NSUInteger destination;
}
@end

@implementation MTLCaptureDescriptor
- (void)dealloc { [object release]; [url release]; [super dealloc]; }
OBJECT_PROPERTY(captureObject, setCaptureObject, object)
OBJECT_PROPERTY(outputURL, setOutputURL, url)
VALUE_PROPERTY(NSUInteger, destination, setDestination, destination)
@end

@interface MTLCaptureManager : NSObject {
    id scope;
}
@end

@implementation MTLCaptureManager
+ (id)sharedCaptureManager {
    static MTLCaptureManager *shared;
    if (!shared)
        shared = [[MTLCaptureManager alloc] init];
    return shared;
}
- (id)newCaptureScopeWithDevice:(id)device { return [[QMCaptureScope alloc] init]; }
- (id)newCaptureScopeWithCommandQueue:(id)queue { return [[QMCaptureScope alloc] init]; }
OBJECT_PROPERTY(defaultCaptureScope, setDefaultCaptureScope, scope)
- (BOOL)supportsDestination:(NSUInteger)destination { return NO; }
- (BOOL)startCaptureWithDescriptor:(id)descriptor error:(NSError **)error {
    if (error)
        *error = nil;
    return NO;
}
- (void)startCaptureWithDevice:(id)device {}
- (void)startCaptureWithCommandQueue:(id)queue {}
- (void)startCaptureWithScope:(id)scope {}
- (void)stopCapture {}
- (BOOL)isCapturing { return NO; }
@end

//! The host half of Quadra's Metal on Vulkan: metal2vulkan-runtime behind the C table that
//! `../quadra_metal.h` describes. The guest Metal.framework (`../framework`) holds the handles
//! this file gives out; see the header for the rules both sides keep.
#![allow(clippy::missing_safety_doc, clippy::too_many_arguments)]

pub mod air;
mod present;
mod util;

use metal2vulkan::metal::{
    BlendFactor, BlendOperation, ColorWriteMask, CompareFunction, CullMode, DepthClipMode,
    IndexType, PixelFormat, PrimitiveTopologyClass, PrimitiveType, SamplerAddressMode,
    SamplerBorderColor, SamplerMinMagFilter, SamplerMipFilter, StencilOperation, TextureType,
    TextureUsage, TriangleFillMode, VertexFormat, VertexStepFunction, Winding,
};
use metal2vulkan::pipeline::{
    ColorAttachmentDescriptor, RenderPipelineDescriptor, StageSource, VertexAttributeDescriptor,
    VertexBufferLayoutDescriptor, VertexDescriptor,
};
use metal2vulkan_runtime::{
    BlitCommandEncoder, BlitOption, Buffer, ClearColor, CommandBuffer, CommandBufferStatus,
    CommandQueue, ComputeCommandEncoder, ComputePipelineState, DepthStencilState, Device,
    DeviceKind, DeviceOptions, Function, Library, LoadAction, Origin, PipelineOptions,
    RenderCommandEncoder, RenderPassDescriptor, RenderPipelineState, ResourceOptions,
    ResourceRef, SamplerState, ScissorRect, Size, StoreAction, Texture, TextureDescriptor,
    Viewport, VisibilityResultMode,
};
use std::ffi::{c_char, c_int, c_void, CStr};
use std::sync::{Arc, Mutex};
use util::{fail, guard, log_once, set_error};

pub use present::{Drawable, Surface};

// ---------------------------------------------------------------------------------------------
// The C types of quadra_metal.h.

#[repr(C)]
#[derive(Clone, Copy)]
pub struct QmOrigin {
    x: u64,
    y: u64,
    z: u64,
}

#[repr(C)]
#[derive(Clone, Copy)]
pub struct QmSize {
    width: u64,
    height: u64,
    depth: u64,
}

#[repr(C)]
pub struct QmTextureDesc {
    texture_type: u64,
    pixel_format: u64,
    width: u64,
    height: u64,
    depth: u64,
    mipmap_level_count: u64,
    sample_count: u64,
    array_length: u64,
    usage: u64,
    resource_options: u64,
    framebuffer_only: u8,
    allow_gpu_optimized_contents: u8,
    pad: [u8; 6],
}

#[repr(C)]
pub struct QmAttachment {
    texture: *mut c_void,
    level: u64,
    slice: u64,
    depth_plane: u64,
    resolve_texture: *mut c_void,
    resolve_level: u64,
    resolve_slice: u64,
    resolve_depth_plane: u64,
    load_action: u32,
    store_action: u32,
    clear: [f64; 4],
}

#[repr(C)]
pub struct QmRenderPassDesc {
    color: [QmAttachment; 8],
    depth: QmAttachment,
    stencil: QmAttachment,
    visibility_result_buffer: *mut c_void,
    render_target_width: u64,
    render_target_height: u64,
    render_target_array_length: u64,
    default_raster_sample_count: u64,
}

const VERTEX_SLOTS: usize = 31;

#[repr(C)]
#[derive(Clone, Copy)]
pub struct QmVertexAttribute {
    present: u32,
    format: u32,
    offset: u32,
    buffer_index: u32,
}

#[repr(C)]
#[derive(Clone, Copy)]
pub struct QmVertexLayout {
    present: u32,
    stride: u32,
    step_function: u32,
    step_rate: u32,
}

#[repr(C)]
#[derive(Clone, Copy)]
pub struct QmColorAttachmentState {
    pixel_format: u64,
    blending_enabled: u32,
    write_mask: u32,
    source_rgb: u32,
    destination_rgb: u32,
    rgb_operation: u32,
    source_alpha: u32,
    destination_alpha: u32,
    alpha_operation: u32,
}

#[repr(C)]
pub struct QmRenderPipelineDesc {
    vertex_function: *mut c_void,
    fragment_function: *mut c_void,
    has_vertex_descriptor: u32,
    pad: u32,
    attributes: [QmVertexAttribute; VERTEX_SLOTS],
    layouts: [QmVertexLayout; VERTEX_SLOTS],
    color: [QmColorAttachmentState; 8],
    depth_format: u64,
    stencil_format: u64,
    sample_count: u32,
    alpha_to_coverage: u32,
    alpha_to_one: u32,
    rasterization_enabled: u32,
    input_primitive_topology: u32,
    pad2: u32,
    label: *const c_char,
}

#[repr(C)]
pub struct QmSamplerDesc {
    min_filter: u32,
    mag_filter: u32,
    mip_filter: u32,
    s_address_mode: u32,
    t_address_mode: u32,
    r_address_mode: u32,
    border_color: u32,
    normalized_coordinates: u32,
    lod_min_clamp: f32,
    lod_max_clamp: f32,
    lod_average: u32,
    max_anisotropy: u32,
    compare_function: u32,
    support_argument_buffers: u32,
}

#[repr(C)]
pub struct QmStencilDesc {
    compare_function: u32,
    failure_operation: u32,
    depth_failure_operation: u32,
    pass_operation: u32,
    read_mask: u32,
    write_mask: u32,
}

#[repr(C)]
pub struct QmDepthStencilDesc {
    depth_compare_function: u32,
    depth_write_enabled: u32,
    front: QmStencilDesc,
    back: QmStencilDesc,
}

#[repr(C)]
pub struct QmDeviceInfo {
    name: [u8; 256],
    registry_id: u64,
    max_buffer_length: u64,
    recommended_max_working_set_size: u64,
    max_threadgroup_memory_length: u64,
    max_threads_per_threadgroup: QmSize,
    has_unified_memory: u32,
    is_low_power: u32,
    is_headless: u32,
    argument_buffers_tier: u32,
    read_write_texture_tier: u32,
    depth24_stencil8_supported: u32,
    vendor_id: u32,
    device_id: u32,
}

// ---------------------------------------------------------------------------------------------
// Handles.

/// What a handle points at. Encoders are `None` once ended.
pub enum Obj {
    Device(Device),
    Buffer(Buffer),
    Texture(Texture),
    Sampler(SamplerState),
    DepthStencil(DepthStencilState),
    Library(Library),
    Function(Function),
    RenderPipeline(RenderPipelineState),
    ComputePipeline(ComputePipelineState),
    Queue(CommandQueue),
    CommandBuffer(CommandBufferObject),
    RenderEncoder(Option<RenderCommandEncoder>),
    BlitEncoder(Option<BlitCommandEncoder>),
    ComputeEncoder(Option<ComputeCommandEncoder>),
    Surface(Arc<Surface>),
    Drawable(Arc<Drawable>),
}

pub struct CommandBufferObject {
    buffer: CommandBuffer,
    presents: Mutex<Vec<Arc<Drawable>>>,
}

fn handle(object: Obj) -> *mut c_void {
    Box::into_raw(Box::new(object)) as *mut c_void
}

unsafe fn object<'a>(handle: *mut c_void) -> Option<&'a Obj> {
    (handle as *const Obj).as_ref()
}

// Metal encoders are confined to their encoding thread. Shared resources,
// queues and command buffers must only be borrowed immutably: they can be
// referenced by multiple encoders, including twice in a single copy call.
unsafe fn object_mut<'a>(handle: *mut c_void) -> Option<&'a mut Obj> {
    (handle as *mut Obj).as_mut()
}

macro_rules! get {
    ($handle:expr, $variant:ident) => {
        match unsafe { object($handle) } {
            Some(Obj::$variant(value)) => Some(value),
            _ => None,
        }
    };
}

macro_rules! get_or {
    ($handle:expr, $variant:ident, $default:expr) => {
        match get!($handle, $variant) {
            Some(value) => value,
            None => {
                set_error(concat!("not a ", stringify!($variant), " handle"));
                return $default;
            }
        }
    };
}

fn optional_texture<'a>(handle: *mut c_void) -> Option<&'a Texture> {
    if handle.is_null() {
        None
    } else {
        get!(handle, Texture).map(|texture| &*texture)
    }
}

fn optional_buffer<'a>(handle: *mut c_void) -> Option<&'a Buffer> {
    if handle.is_null() {
        None
    } else {
        get!(handle, Buffer).map(|buffer| &*buffer)
    }
}

fn origin(value: QmOrigin) -> Origin {
    Origin::new(value.x, value.y, value.z)
}

fn size(value: QmSize) -> Size {
    Size::new(value.width, value.height, value.depth)
}

fn pixel_format(raw: u64) -> Result<PixelFormat, String> {
    u32::try_from(raw)
        .ok()
        .and_then(|raw| PixelFormat::try_from(raw).ok())
        .ok_or_else(|| format!("unknown pixel format {raw}"))
}

fn enum_value<T: TryFrom<u32>>(raw: u32, what: &str) -> Result<T, String> {
    T::try_from(raw).map_err(|_| format!("unknown {what} {raw}"))
}

// ---------------------------------------------------------------------------------------------
// The table.

extern "C" fn last_error() -> *const c_char {
    util::last_error()
}

extern "C" fn release(handle: *mut c_void) {
    if handle.is_null() {
        return;
    }
    let _ = std::panic::catch_unwind(|| unsafe { drop(Box::from_raw(handle as *mut Obj)) });
}

extern "C" fn device_create(_options: *const c_void) -> *mut c_void {
    guard(std::ptr::null_mut(), || {
        let mut options = DeviceOptions::default();
        // Two timestamps less per command buffer; Roblox reads GPU times only for its stats.
        options.gpu_times_from_host = true;
        if let Some(directory) = std::env::var_os("MACOBLOX_METAL_SHADER_CACHE") {
            options.shader_cache.directory = Some(directory.into());
        }
        present::add_surface_extensions(&mut options);
        options.messages = Some(util::message_sink());
        match Device::system_default_with(&options) {
            Ok(device) => {
                log_once(&format!("[Quadra Metal] Vulkan device: {}", device.name()));
                handle(Obj::Device(device))
            }
            Err(error) => fail(format!("no Vulkan device for Metal: {error}")),
        }
    })
}

extern "C" fn device_info(device: *mut c_void, out: *mut QmDeviceInfo) {
    let device = get_or!(device, Device, ());
    let Some(out) = (unsafe { out.as_mut() }) else { return };
    let properties = device.properties();
    let name = properties.name.as_bytes();
    let count = name.len().min(out.name.len() - 1);
    out.name[..count].copy_from_slice(&name[..count]);
    out.name[count] = 0;
    out.registry_id = device.registry_id();
    out.max_buffer_length = properties.max_buffer_length;
    out.recommended_max_working_set_size = std::env::var("MACOBLOX_VRAM_BYTES")
        .ok()
        .and_then(|value| value.parse().ok())
        .unwrap_or(4 << 30);
    out.max_threadgroup_memory_length = properties.max_threadgroup_memory_length;
    out.max_threads_per_threadgroup = QmSize {
        width: properties.max_threads_per_threadgroup.width,
        height: properties.max_threads_per_threadgroup.height,
        depth: properties.max_threads_per_threadgroup.depth,
    };
    out.has_unified_memory = properties.has_unified_memory as u32;
    out.is_low_power = matches!(properties.kind, DeviceKind::Integrated) as u32;
    out.is_headless = 0;
    out.argument_buffers_tier = properties.argument_buffers_support as u32;
    out.read_write_texture_tier = properties.read_write_texture_support as u32;
    out.depth24_stencil8_supported = device
        .pixel_format_capabilities(PixelFormat::Depth24UnormStencil8)
        .iter()
        .next()
        .is_some() as u32;
    out.vendor_id = properties.vendor_id;
    out.device_id = properties.device_id;
}

extern "C" fn device_supports_family(device: *mut c_void, family: i64) -> c_int {
    let device = get_or!(device, Device, 0);
    guard(0, || device.supports_family(family) as c_int)
}

extern "C" fn device_supports_texture_sample_count(device: *mut c_void, count: u64) -> c_int {
    let device = get_or!(device, Device, 0);
    let limits = &device.properties().description.limits;
    let supported = limits.framebuffer_color_sample_counts.as_raw() & limits.framebuffer_depth_sample_counts.as_raw();
    (count.is_power_of_two() && count <= 64 && supported & count as u32 != 0) as c_int
}

extern "C" fn device_current_allocated_size(device: *mut c_void) -> u64 {
    let _device = get_or!(device, Device, 0);
    util::allocated_bytes()
}

extern "C" fn buffer_new(device: *mut c_void, length: u64, options: u64, bytes: *const c_void) -> *mut c_void {
    let device = get_or!(device, Device, std::ptr::null_mut());
    guard(std::ptr::null_mut(), || {
        let options = match ResourceOptions::from_raw(options) {
            Ok(options) => options,
            Err(error) => return fail(format!("buffer options {options:#x}: {error}")),
        };
        let result = if bytes.is_null() {
            device.new_buffer(length.max(1), options)
        } else {
            let bytes = unsafe { std::slice::from_raw_parts(bytes as *const u8, length as usize) };
            device.new_buffer_with_bytes(bytes, options)
        };
        match result {
            Ok(buffer) => {
                util::count_allocation(buffer.length() as i64);
                handle(Obj::Buffer(buffer))
            }
            Err(error) => fail(format!("newBufferWithLength {length}: {error}")),
        }
    })
}

extern "C" fn buffer_contents(buffer: *mut c_void) -> *mut c_void {
    let buffer = get_or!(buffer, Buffer, std::ptr::null_mut());
    buffer.contents().map_or(std::ptr::null_mut(), |pointer| pointer.as_ptr() as *mut c_void)
}

extern "C" fn buffer_length(buffer: *mut c_void) -> u64 {
    get_or!(buffer, Buffer, 0).length()
}

extern "C" fn buffer_did_modify_range(buffer: *mut c_void, start: u64, end: u64) -> c_int {
    let buffer = get_or!(buffer, Buffer, 0);
    guard(0, || match buffer.did_modify_range(start..end) {
        Ok(()) => 1,
        Err(error) => {
            set_error(format!("didModifyRange: {error}"));
            0
        }
    })
}

fn texture_descriptor(desc: &QmTextureDesc) -> Result<TextureDescriptor, String> {
    let mut descriptor = TextureDescriptor::default();
    descriptor.texture_type = enum_value::<TextureType>(desc.texture_type as u32, "texture type")?;
    descriptor.pixel_format = pixel_format(desc.pixel_format)?;
    descriptor.width = desc.width.max(1);
    descriptor.height = desc.height.max(1);
    descriptor.depth = desc.depth.max(1);
    descriptor.mipmap_level_count = desc.mipmap_level_count.max(1);
    descriptor.sample_count = desc.sample_count.max(1);
    descriptor.array_length = desc.array_length.max(1);
    descriptor.usage = TextureUsage::try_from(desc.usage as u32)
        .map_err(|_| format!("texture usage {:#x}", desc.usage))?;
    descriptor.resource_options = ResourceOptions::from_raw(desc.resource_options)
        .map_err(|error| format!("texture options {:#x}: {error}", desc.resource_options))?;
    descriptor.framebuffer_only = desc.framebuffer_only != 0;
    descriptor.allow_gpu_optimized_contents = desc.allow_gpu_optimized_contents != 0;
    Ok(descriptor)
}

fn texture_bytes(descriptor: &TextureDescriptor) -> i64 {
    let texel = match descriptor.pixel_format as u32 {
        10..=13 => 1,
        20..=60 => 2,
        70..=99 => 4,
        100..=139 => 8,
        _ => 4,
    } as u64;
    (descriptor.width * descriptor.height * descriptor.depth * descriptor.array_length
        * descriptor.sample_count * texel * if descriptor.mipmap_level_count > 1 { 4 } else { 3 }
        / 3) as i64
}

extern "C" fn texture_new(device: *mut c_void, desc: *const QmTextureDesc) -> *mut c_void {
    let device = get_or!(device, Device, std::ptr::null_mut());
    let Some(desc) = (unsafe { desc.as_ref() }) else { return fail("no texture descriptor") };
    guard(std::ptr::null_mut(), || {
        let descriptor = match texture_descriptor(desc) {
            Ok(descriptor) => descriptor,
            Err(error) => return fail(error),
        };
        match device.new_texture(&descriptor) {
            Ok(texture) => {
                util::count_allocation(texture_bytes(&descriptor));
                handle(Obj::Texture(texture))
            }
            Err(error) => fail(format!(
                "newTextureWithDescriptor {:?} {}x{}x{} levels {} samples {}: {error}",
                descriptor.pixel_format, descriptor.width, descriptor.height, descriptor.depth,
                descriptor.mipmap_level_count, descriptor.sample_count
            )),
        }
    })
}

extern "C" fn texture_view(
    texture: *mut c_void,
    format: u64,
    texture_type: u64,
    level_start: u64,
    level_count: u64,
    slice_start: u64,
    slice_count: u64,
) -> *mut c_void {
    let texture = get_or!(texture, Texture, std::ptr::null_mut());
    guard(std::ptr::null_mut(), || {
        let format = match pixel_format(format) {
            Ok(format) => format,
            Err(error) => return fail(error),
        };
        let result = if level_count == 0 {
            texture.new_texture_view(format)
        } else {
            match enum_value::<TextureType>(texture_type as u32, "texture type") {
                Ok(kind) => texture.new_texture_view_with_levels_slices(
                    format,
                    kind,
                    level_start..level_start + level_count,
                    slice_start..slice_start + slice_count,
                ),
                Err(error) => return fail(error),
            }
        };
        match result {
            Ok(view) => handle(Obj::Texture(view)),
            Err(error) => fail(format!("newTextureView: {error}")),
        }
    })
}

extern "C" fn texture_describe(texture: *mut c_void, out: *mut QmTextureDesc) {
    let texture = get_or!(texture, Texture, ());
    let Some(out) = (unsafe { out.as_mut() }) else { return };
    out.texture_type = texture.texture_type() as u64;
    out.pixel_format = texture.pixel_format() as u64;
    out.width = texture.width();
    out.height = texture.height();
    out.depth = texture.depth();
    out.mipmap_level_count = texture.mipmap_level_count();
    out.sample_count = texture.sample_count();
    out.array_length = texture.array_length();
    out.usage = u32::from(texture.usage()) as u64;
    out.resource_options = texture.resource_options().raw();
    out.framebuffer_only = texture.framebuffer_only() as u8;
}

extern "C" fn texture_replace_region(
    texture: *mut c_void,
    region_origin: QmOrigin,
    region_size: QmSize,
    level: u64,
    slice: u64,
    bytes: *const c_void,
    bytes_per_row: u64,
    bytes_per_image: u64,
) -> c_int {
    let texture = get_or!(texture, Texture, 0);
    guard(0, || {
        let rows = region_size.height.max(1);
        let images = region_size.depth.max(1);
        let length = if images > 1 || bytes_per_image != 0 {
            bytes_per_image.max(bytes_per_row * rows) * images
        } else {
            bytes_per_row * rows
        };
        let length = if length == 0 { util::packed_length(texture, region_size) } else { length };
        let data = unsafe { std::slice::from_raw_parts(bytes as *const u8, length as usize) };
        let region = metal2vulkan_runtime::Region::new_3d(region_origin.x, region_origin.y, region_origin.z, region_size.width, region_size.height, region_size.depth);
        match texture.replace_region(region, level, slice, data, bytes_per_row, bytes_per_image) {
            Ok(()) => 1,
            Err(error) => {
                set_error(format!("replaceRegion: {error}"));
                0
            }
        }
    })
}

extern "C" fn texture_get_bytes(
    texture: *mut c_void,
    bytes: *mut c_void,
    length: u64,
    bytes_per_row: u64,
    bytes_per_image: u64,
    region_origin: QmOrigin,
    region_size: QmSize,
    level: u64,
    slice: u64,
) -> c_int {
    let texture = get_or!(texture, Texture, 0);
    guard(0, || {
        let data = unsafe { std::slice::from_raw_parts_mut(bytes as *mut u8, length as usize) };
        let region = metal2vulkan_runtime::Region::new_3d(region_origin.x, region_origin.y, region_origin.z, region_size.width, region_size.height, region_size.depth);
        match texture.get_bytes(data, bytes_per_row, bytes_per_image, region, level, slice) {
            Ok(()) => 1,
            Err(error) => {
                set_error(format!("getBytes: {error}"));
                0
            }
        }
    })
}

extern "C" fn sampler_new(device: *mut c_void, desc: *const QmSamplerDesc) -> *mut c_void {
    let device = get_or!(device, Device, std::ptr::null_mut());
    let Some(desc) = (unsafe { desc.as_ref() }) else { return fail("no sampler descriptor") };
    guard(std::ptr::null_mut(), || {
        let build = || -> Result<metal2vulkan::bind::SamplerDescriptor, String> {
            let mut descriptor = metal2vulkan::bind::SamplerDescriptor::default();
            descriptor.min_filter = enum_value::<SamplerMinMagFilter>(desc.min_filter, "min filter")?;
            descriptor.mag_filter = enum_value::<SamplerMinMagFilter>(desc.mag_filter, "mag filter")?;
            descriptor.mip_filter = enum_value::<SamplerMipFilter>(desc.mip_filter, "mip filter")?;
            descriptor.s_address_mode = enum_value::<SamplerAddressMode>(desc.s_address_mode, "address mode")?;
            descriptor.t_address_mode = enum_value::<SamplerAddressMode>(desc.t_address_mode, "address mode")?;
            descriptor.r_address_mode = enum_value::<SamplerAddressMode>(desc.r_address_mode, "address mode")?;
            descriptor.border_color = enum_value::<SamplerBorderColor>(desc.border_color, "border color")?;
            descriptor.normalized_coordinates = desc.normalized_coordinates != 0;
            descriptor.lod_min_clamp = desc.lod_min_clamp;
            descriptor.lod_max_clamp = desc.lod_max_clamp;
            descriptor.lod_average = desc.lod_average != 0;
            descriptor.max_anisotropy = desc.max_anisotropy.max(1);
            descriptor.compare_function = enum_value::<CompareFunction>(desc.compare_function, "compare function")?;
            Ok(descriptor)
        };
        let descriptor = match build() {
            Ok(descriptor) => descriptor,
            Err(error) => return fail(error),
        };
        match device.new_sampler_state(&descriptor) {
            Ok(sampler) => handle(Obj::Sampler(sampler)),
            Err(error) => fail(format!("newSamplerStateWithDescriptor: {error}")),
        }
    })
}

fn stencil(desc: &QmStencilDesc) -> Result<metal2vulkan::metal::state::StencilDescriptor, String> {
    let mut stencil = metal2vulkan::metal::state::StencilDescriptor::default();
    stencil.stencil_compare_function = enum_value::<CompareFunction>(desc.compare_function, "stencil compare")?;
    stencil.stencil_failure_operation = enum_value::<StencilOperation>(desc.failure_operation, "stencil operation")?;
    stencil.depth_failure_operation = enum_value::<StencilOperation>(desc.depth_failure_operation, "stencil operation")?;
    stencil.depth_stencil_pass_operation = enum_value::<StencilOperation>(desc.pass_operation, "stencil operation")?;
    stencil.read_mask = desc.read_mask;
    stencil.write_mask = desc.write_mask;
    Ok(stencil)
}

extern "C" fn depth_stencil_new(device: *mut c_void, desc: *const QmDepthStencilDesc) -> *mut c_void {
    let device = get_or!(device, Device, std::ptr::null_mut());
    let Some(desc) = (unsafe { desc.as_ref() }) else { return fail("no depth-stencil descriptor") };
    guard(std::ptr::null_mut(), || {
        let build = || -> Result<metal2vulkan::metal::state::DepthStencilDescriptor, String> {
            let mut descriptor = metal2vulkan::metal::state::DepthStencilDescriptor::default();
            descriptor.depth_compare_function =
                enum_value::<CompareFunction>(desc.depth_compare_function, "depth compare")?;
            descriptor.depth_write_enabled = desc.depth_write_enabled != 0;
            descriptor.front_face_stencil = stencil(&desc.front)?;
            descriptor.back_face_stencil = stencil(&desc.back)?;
            Ok(descriptor)
        };
        let descriptor = match build() {
            Ok(descriptor) => descriptor,
            Err(error) => return fail(error),
        };
        match device.new_depth_stencil_state(&descriptor) {
            Ok(state) => handle(Obj::DepthStencil(state)),
            Err(error) => fail(format!("newDepthStencilStateWithDescriptor: {error}")),
        }
    })
}

/// Roblox ships metallibs of format 2.2, whose public metadata starts right after the function
/// list; metal2vulkan reads the formats 2.7 and later, which put an extended-header tag list
/// there. An empty one (`ENDT`) is inserted and the three later sections move by its 4 bytes;
/// their contents, the bitcode and its hash, stay as they are.
pub fn normalize_metallib(bytes: &[u8]) -> std::borrow::Cow<'_, [u8]> {
    let u64_at = |at: usize| bytes.get(at..at + 8).map(|b| u64::from_le_bytes(b.try_into().unwrap()));
    if bytes.len() < 0x58 || &bytes[..4] != b"MTLB" {
        return bytes.into();
    }
    let (Some(list_offset), Some(list_size), Some(public)) = (u64_at(24), u64_at(32), u64_at(40)) else {
        return bytes.into();
    };
    let list_end = list_offset + 4 + list_size;
    if list_end != public || list_end as usize > bytes.len() {
        return bytes.into();
    }
    let at = list_end as usize;
    let mut out = Vec::with_capacity(bytes.len() + 4);
    out.extend_from_slice(&bytes[..at]);
    out.extend_from_slice(b"ENDT");
    out.extend_from_slice(&bytes[at..]);
    let mut shift = |field: usize| {
        let value = u64::from_le_bytes(out[field..field + 8].try_into().unwrap());
        out[field..field + 8].copy_from_slice(&(value + 4).to_le_bytes());
    };
    shift(16); // file size
    shift(40); // public metadata
    shift(56); // private metadata
    shift(72); // bitcode
    out.into()
}

extern "C" fn library_new(device: *mut c_void, data: *const c_void, length: u64) -> *mut c_void {
    let device = get_or!(device, Device, std::ptr::null_mut());
    guard(std::ptr::null_mut(), || {
        let bytes = unsafe { std::slice::from_raw_parts(data as *const u8, length as usize) };
        let prepared = match air::prepare(bytes) {
            Ok(prepared) => prepared,
            Err(error) => {
                log_once(&format!("[Quadra Metal] shader upgrade: {error}"));
                return fail(format!("newLibraryWithData ({length} bytes): {error}"));
            }
        };
        let bytes = normalize_metallib(&prepared);
        match device.new_library_with_data(&bytes) {
            Ok(library) => handle(Obj::Library(library)),
            Err(error) => fail(format!("newLibraryWithData ({length} bytes): {error}")),
        }
    })
}

extern "C" fn library_function_names(library: *mut c_void, buffer: *mut c_char, capacity: u64) -> u64 {
    let library = get_or!(library, Library, 0);
    guard(0, || {
        let mut joined = Vec::new();
        for name in library.function_names() {
            joined.extend_from_slice(name.as_bytes());
            joined.push(0);
        }
        if !buffer.is_null() && capacity >= joined.len() as u64 {
            unsafe { std::ptr::copy_nonoverlapping(joined.as_ptr(), buffer as *mut u8, joined.len()) };
        }
        joined.len() as u64
    })
}

extern "C" fn function_new(library: *mut c_void, name: *const c_char) -> *mut c_void {
    let library = get_or!(library, Library, std::ptr::null_mut());
    guard(std::ptr::null_mut(), || {
        let name = unsafe { CStr::from_ptr(name) }.to_string_lossy();
        match library.new_function_with_name(&name) {
            Ok(function) => handle(Obj::Function(function)),
            Err(error) => fail(format!("newFunctionWithName {name}: {error}")),
        }
    })
}

extern "C" fn function_type(function: *mut c_void) -> c_int {
    let function = get_or!(function, Function, 0);
    guard(0, || function.function_type().map_or(0, |kind| kind as c_int))
}

fn render_pipeline_descriptor(desc: &QmRenderPipelineDesc) -> Result<RenderPipelineDescriptor, String> {
    let vertex = get!(desc.vertex_function, Function).ok_or("no vertex function")?;
    let mut descriptor = RenderPipelineDescriptor::new(StageSource::Function(vertex.function_descriptor()));
    if !desc.fragment_function.is_null() {
        let fragment = get!(desc.fragment_function, Function).ok_or("bad fragment function")?;
        descriptor.fragment = Some(StageSource::Function(fragment.function_descriptor()));
    }
    if desc.has_vertex_descriptor != 0 {
        let mut vertex_descriptor = VertexDescriptor::default();
        for (index, attribute) in desc.attributes.iter().enumerate() {
            // MTLVertexFormatInvalid (0) is an attribute the descriptor leaves out.
            if attribute.present == 0 || attribute.format == 0 {
                continue;
            }
            let value = VertexAttributeDescriptor::new(
                enum_value::<VertexFormat>(attribute.format, "vertex format")?,
                attribute.offset,
                attribute.buffer_index,
            );
            vertex_descriptor.attributes.insert(index as u32, value);
        }
        for (index, layout) in desc.layouts.iter().enumerate() {
            if layout.present == 0 {
                continue;
            }
            let used = vertex_descriptor.attributes.values().any(|attribute| attribute.buffer_index == index as u32);
            if !used && layout.stride == 0 {
                continue;
            }
            let mut value = VertexBufferLayoutDescriptor::new(Some(layout.stride));
            value.step_function = enum_value::<VertexStepFunction>(layout.step_function, "step function")?;
            value.step_rate = layout.step_rate;
            vertex_descriptor.layouts.insert(index as u32, value);
        }
        descriptor.vertex_descriptor = Some(vertex_descriptor);
    }
    for (index, color) in desc.color.iter().enumerate() {
        if color.pixel_format == 0 {
            continue;
        }
        let mut attachment = ColorAttachmentDescriptor::new(pixel_format(color.pixel_format)?);
        attachment.blending_enabled = color.blending_enabled != 0;
        attachment.source_rgb_blend_factor = enum_value::<BlendFactor>(color.source_rgb, "blend factor")?;
        attachment.destination_rgb_blend_factor = enum_value::<BlendFactor>(color.destination_rgb, "blend factor")?;
        attachment.rgb_blend_operation = enum_value::<BlendOperation>(color.rgb_operation, "blend operation")?;
        attachment.source_alpha_blend_factor = enum_value::<BlendFactor>(color.source_alpha, "blend factor")?;
        attachment.destination_alpha_blend_factor = enum_value::<BlendFactor>(color.destination_alpha, "blend factor")?;
        attachment.alpha_blend_operation = enum_value::<BlendOperation>(color.alpha_operation, "blend operation")?;
        attachment.write_mask = ColorWriteMask::try_from(color.write_mask).map_err(|_| "write mask")?;
        descriptor.color_attachments[index] = Some(attachment);
    }
    if desc.depth_format != 0 {
        descriptor.depth_format = Some(pixel_format(desc.depth_format)?);
    }
    if desc.stencil_format != 0 {
        descriptor.stencil_format = Some(pixel_format(desc.stencil_format)?);
    }
    descriptor.raster_sample_count = desc.sample_count.max(1);
    descriptor.alpha_to_coverage = desc.alpha_to_coverage != 0;
    descriptor.alpha_to_one = desc.alpha_to_one != 0;
    descriptor.rasterization_enabled = desc.rasterization_enabled != 0;
    descriptor.input_primitive_topology =
        enum_value::<PrimitiveTopologyClass>(desc.input_primitive_topology, "primitive topology")?;
    Ok(descriptor)
}

extern "C" fn render_pipeline_new(device: *mut c_void, desc: *const QmRenderPipelineDesc) -> *mut c_void {
    let device = get_or!(device, Device, std::ptr::null_mut());
    let Some(desc) = (unsafe { desc.as_ref() }) else { return fail("no pipeline descriptor") };
    guard(std::ptr::null_mut(), || {
        let descriptor = match render_pipeline_descriptor(desc) {
            Ok(descriptor) => descriptor,
            Err(error) => return fail(error),
        };
        let mut options = PipelineOptions::default();
        if !desc.label.is_null() {
            options.label = Some(unsafe { CStr::from_ptr(desc.label) }.to_string_lossy().into_owned());
        }
        let started = std::time::Instant::now();
        let result = device.new_render_pipeline_state(&descriptor, &options);
        util::note_pipeline_time(started.elapsed());
        match result {
            Ok(state) => handle(Obj::RenderPipeline(state)),
            Err(error) => fail(format!(
                "newRenderPipelineState {}: {error}",
                options.label.as_deref().unwrap_or("(no label)")
            )),
        }
    })
}

extern "C" fn compute_pipeline_new(device: *mut c_void, function: *mut c_void, label: *const c_char) -> *mut c_void {
    let device = get_or!(device, Device, std::ptr::null_mut());
    let function = get_or!(function, Function, std::ptr::null_mut());
    guard(std::ptr::null_mut(), || {
        let mut options = PipelineOptions::default();
        if !label.is_null() {
            options.label = Some(unsafe { CStr::from_ptr(label) }.to_string_lossy().into_owned());
        }
        match device.new_compute_pipeline_state_with_function(function, &options) {
            Ok(state) => handle(Obj::ComputePipeline(state)),
            Err(error) => fail(format!("newComputePipelineState {}: {error}", function.name())),
        }
    })
}

extern "C" fn compute_pipeline_info(pipeline: *mut c_void, max_threads: *mut u32, execution_width: *mut u32) {
    let pipeline = get_or!(pipeline, ComputePipeline, ());
    unsafe {
        if let Some(out) = max_threads.as_mut() {
            *out = pipeline.max_total_threads_per_threadgroup();
        }
        if let Some(out) = execution_width.as_mut() {
            *out = pipeline.thread_execution_width();
        }
    }
}

extern "C" fn queue_new(device: *mut c_void) -> *mut c_void {
    let device = get_or!(device, Device, std::ptr::null_mut());
    guard(std::ptr::null_mut(), || match device.new_command_queue() {
        Ok(queue) => handle(Obj::Queue(queue)),
        Err(error) => fail(format!("newCommandQueue: {error}")),
    })
}

extern "C" fn command_buffer_new(queue: *mut c_void) -> *mut c_void {
    let queue = get_or!(queue, Queue, std::ptr::null_mut());
    guard(std::ptr::null_mut(), || match queue.command_buffer() {
        Ok(buffer) => handle(Obj::CommandBuffer(CommandBufferObject { buffer, presents: Mutex::new(Vec::new()) })),
        Err(error) => fail(format!("commandBuffer: {error}")),
    })
}

extern "C" fn command_buffer_present(command_buffer: *mut c_void, drawable: *mut c_void) -> c_int {
    let command_buffer = get_or!(command_buffer, CommandBuffer, 0);
    let drawable = get_or!(drawable, Drawable, 0);
    command_buffer.presents.lock().unwrap().push(drawable.clone());
    1
}

extern "C" fn command_buffer_commit(command_buffer: *mut c_void) -> c_int {
    let command_buffer = get_or!(command_buffer, CommandBuffer, 0);
    guard(0, || {
        let presents = std::mem::take(&mut *command_buffer.presents.lock().unwrap());
        for drawable in presents {
            if let Err(error) = drawable.encode_present(&command_buffer.buffer) {
                log_once(&format!("[Quadra Metal] presentDrawable: {error}"));
            }
        }
        match command_buffer.buffer.commit() {
            Ok(()) => 1,
            Err(error) => {
                log_once(&format!("[Quadra Metal] commit: {error}"));
                set_error(format!("commit: {error}"));
                0
            }
        }
    })
}

fn status(status: CommandBufferStatus) -> c_int {
    match status {
        CommandBufferStatus::NotEnqueued => 0,
        CommandBufferStatus::Enqueued => 1,
        CommandBufferStatus::Committed => 2,
        CommandBufferStatus::Scheduled => 3,
        CommandBufferStatus::Completed => 4,
        CommandBufferStatus::Error => 5,
        _ => 5,
    }
}

extern "C" fn command_buffer_wait(command_buffer: *mut c_void) -> c_int {
    let command_buffer = get_or!(command_buffer, CommandBuffer, 5);
    guard(5, || {
        if let Err(error) = command_buffer.buffer.wait_until_completed() {
            log_once(&format!("[Quadra Metal] waitUntilCompleted: {error}"));
        }
        let result = command_buffer.buffer.status();
        if matches!(result, CommandBufferStatus::Error) {
            let description = command_buffer.buffer.error_description().unwrap_or_default();
            log_once(&format!("[Quadra Metal] command buffer failed: {description}"));
        }
        status(result)
    })
}

extern "C" fn command_buffer_status(command_buffer: *mut c_void) -> c_int {
    let command_buffer = get_or!(command_buffer, CommandBuffer, 5);
    status(command_buffer.buffer.status())
}

extern "C" fn command_buffer_times(command_buffer: *mut c_void, start: *mut f64, end: *mut f64) {
    let command_buffer = get_or!(command_buffer, CommandBuffer, ());
    unsafe {
        if let Some(out) = start.as_mut() {
            *out = command_buffer.buffer.gpu_start_time().unwrap_or(0.0);
        }
        if let Some(out) = end.as_mut() {
            *out = command_buffer.buffer.gpu_end_time().unwrap_or(0.0);
        }
    }
}

fn load_action(raw: u32) -> LoadAction {
    match raw {
        1 => LoadAction::Load,
        2 => LoadAction::Clear,
        _ => LoadAction::DontCare,
    }
}

fn store_action(raw: u32) -> StoreAction {
    match raw {
        1 => StoreAction::Store,
        2 => StoreAction::MultisampleResolve,
        3 => StoreAction::StoreAndMultisampleResolve,
        4 => StoreAction::Unknown,
        5 => StoreAction::CustomSampleDepthStore,
        _ => StoreAction::DontCare,
    }
}

extern "C" fn render_encoder_new(command_buffer: *mut c_void, desc: *const QmRenderPassDesc) -> *mut c_void {
    let command_buffer = get_or!(command_buffer, CommandBuffer, std::ptr::null_mut());
    let Some(desc) = (unsafe { desc.as_ref() }) else { return fail("no render pass descriptor") };
    guard(std::ptr::null_mut(), || {
        let mut pass = RenderPassDescriptor::new();
        for (index, color) in desc.color.iter().enumerate() {
            let Some(texture) = optional_texture(color.texture) else { continue };
            let attachment = &mut pass.color_attachments[index];
            attachment.texture = Some(texture.clone());
            attachment.level = color.level;
            attachment.slice = color.slice;
            attachment.depth_plane = color.depth_plane;
            attachment.resolve_texture = optional_texture(color.resolve_texture).cloned();
            attachment.resolve_level = color.resolve_level;
            attachment.resolve_slice = color.resolve_slice;
            attachment.resolve_depth_plane = color.resolve_depth_plane;
            attachment.load_action = load_action(color.load_action);
            attachment.store_action = store_action(color.store_action);
            attachment.clear_color = ClearColor::new(color.clear[0], color.clear[1], color.clear[2], color.clear[3]);
        }
        if let Some(texture) = optional_texture(desc.depth.texture) {
            let depth = &mut pass.depth_attachment;
            depth.texture = Some(texture.clone());
            depth.level = desc.depth.level;
            depth.slice = desc.depth.slice;
            depth.depth_plane = desc.depth.depth_plane;
            depth.resolve_texture = optional_texture(desc.depth.resolve_texture).cloned();
            depth.resolve_level = desc.depth.resolve_level;
            depth.resolve_slice = desc.depth.resolve_slice;
            depth.load_action = load_action(desc.depth.load_action);
            depth.store_action = store_action(desc.depth.store_action);
            depth.clear_depth = desc.depth.clear[0];
        }
        if let Some(texture) = optional_texture(desc.stencil.texture) {
            let stencil = &mut pass.stencil_attachment;
            stencil.texture = Some(texture.clone());
            stencil.level = desc.stencil.level;
            stencil.slice = desc.stencil.slice;
            stencil.depth_plane = desc.stencil.depth_plane;
            stencil.resolve_texture = optional_texture(desc.stencil.resolve_texture).cloned();
            stencil.resolve_level = desc.stencil.resolve_level;
            stencil.resolve_slice = desc.stencil.resolve_slice;
            stencil.load_action = load_action(desc.stencil.load_action);
            stencil.store_action = store_action(desc.stencil.store_action);
            stencil.clear_stencil = desc.stencil.clear[0] as u32;
        }
        pass.visibility_result_buffer = optional_buffer(desc.visibility_result_buffer).cloned();
        pass.render_target_width = desc.render_target_width;
        pass.render_target_height = desc.render_target_height;
        pass.render_target_array_length = desc.render_target_array_length;
        pass.default_raster_sample_count = desc.default_raster_sample_count;
        match command_buffer.buffer.render_command_encoder(&pass) {
            Ok(encoder) => handle(Obj::RenderEncoder(Some(encoder))),
            Err(error) => fail(format!("renderCommandEncoderWithDescriptor: {error}")),
        }
    })
}

macro_rules! encoder {
    ($handle:expr, $variant:ident) => {
        match unsafe { object_mut($handle) } {
            Some(Obj::$variant(Some(encoder))) => encoder,
            _ => {
                log_once(concat!("[Quadra Metal] call on an ended or missing ", stringify!($variant)));
                return;
            }
        }
    };
}

/// Encoder calls answer nothing in Metal; a refusal is logged once per distinct text.
fn report<T>(call: &str, result: Result<T, metal2vulkan_runtime::Error>) {
    if let Err(error) = result {
        log_once(&format!("[Quadra Metal] {call}: {error}"));
    }
}

extern "C" fn render_end(encoder: *mut c_void) -> c_int {
    let Some(Obj::RenderEncoder(slot)) = (unsafe { object_mut(encoder) }) else { return 0 };
    let Some(value) = slot.take() else { return 0 };
    guard(0, || match value.end_encoding() {
        Ok(()) => 1,
        Err(error) => {
            log_once(&format!("[Quadra Metal] render endEncoding: {error}"));
            0
        }
    })
}

extern "C" fn render_set_pipeline(encoder: *mut c_void, pipeline: *mut c_void) {
    let encoder = encoder!(encoder, RenderEncoder);
    let Some(pipeline) = get!(pipeline, RenderPipeline) else { return };
    report("setRenderPipelineState", encoder.set_render_pipeline_state(pipeline));
}

extern "C" fn render_set_buffer(encoder: *mut c_void, stage: c_int, buffer: *mut c_void, offset: u64, index: u32) {
    let encoder = encoder!(encoder, RenderEncoder);
    let buffer = optional_buffer(buffer);
    if stage == 0 {
        report("setVertexBuffer", encoder.set_vertex_buffer(buffer, offset, index));
    } else {
        report("setFragmentBuffer", encoder.set_fragment_buffer(buffer, offset, index));
    }
}

extern "C" fn render_set_buffer_offset(encoder: *mut c_void, stage: c_int, offset: u64, index: u32) {
    let encoder = encoder!(encoder, RenderEncoder);
    if stage == 0 {
        report("setVertexBufferOffset", encoder.set_vertex_buffer_offset(offset, index));
    } else {
        report("setFragmentBufferOffset", encoder.set_fragment_buffer_offset(offset, index));
    }
}

extern "C" fn render_set_bytes(encoder: *mut c_void, stage: c_int, bytes: *const c_void, length: u64, index: u32) {
    let encoder = encoder!(encoder, RenderEncoder);
    let bytes = unsafe { std::slice::from_raw_parts(bytes as *const u8, length as usize) };
    if stage == 0 {
        report("setVertexBytes", encoder.set_vertex_bytes(bytes, index));
    } else {
        report("setFragmentBytes", encoder.set_fragment_bytes(bytes, index));
    }
}

extern "C" fn render_set_texture(encoder: *mut c_void, stage: c_int, texture: *mut c_void, index: u32) {
    let encoder = encoder!(encoder, RenderEncoder);
    let texture = optional_texture(texture);
    if stage == 0 {
        report("setVertexTexture", encoder.set_vertex_texture(texture, index));
    } else {
        report("setFragmentTexture", encoder.set_fragment_texture(texture, index));
    }
}

extern "C" fn render_set_sampler(encoder: *mut c_void, stage: c_int, sampler: *mut c_void, index: u32) {
    let encoder = encoder!(encoder, RenderEncoder);
    let sampler = if sampler.is_null() { None } else { get!(sampler, Sampler).map(|value| &*value) };
    if stage == 0 {
        report("setVertexSamplerState", encoder.set_vertex_sampler_state(sampler, index));
    } else {
        report("setFragmentSamplerState", encoder.set_fragment_sampler_state(sampler, index));
    }
}

extern "C" fn render_set_viewport(encoder: *mut c_void, viewport: *const f64) {
    let encoder = encoder!(encoder, RenderEncoder);
    let values = unsafe { std::slice::from_raw_parts(viewport, 6) };
    let mut value = Viewport::default();
    value.origin_x = values[0];
    value.origin_y = values[1];
    value.width = values[2];
    value.height = values[3];
    value.znear = values[4];
    value.zfar = values[5];
    report("setViewport", encoder.set_viewport(value));
}

extern "C" fn render_set_scissor(encoder: *mut c_void, x: u64, y: u64, width: u64, height: u64) {
    let encoder = encoder!(encoder, RenderEncoder);
    let mut rect = ScissorRect::default();
    rect.x = x;
    rect.y = y;
    rect.width = width;
    rect.height = height;
    report("setScissorRect", encoder.set_scissor_rect(rect));
}

extern "C" fn render_set_cull_mode(encoder: *mut c_void, mode: u32) {
    let encoder = encoder!(encoder, RenderEncoder);
    if let Ok(mode) = CullMode::try_from(mode) {
        encoder.set_cull_mode(mode);
    }
}

extern "C" fn render_set_winding(encoder: *mut c_void, winding: u32) {
    let encoder = encoder!(encoder, RenderEncoder);
    if let Ok(winding) = Winding::try_from(winding) {
        encoder.set_front_facing_winding(winding);
    }
}

extern "C" fn render_set_depth_bias(encoder: *mut c_void, bias: f32, slope: f32, clamp: f32) {
    let encoder = encoder!(encoder, RenderEncoder);
    report("setDepthBias", encoder.set_depth_bias(bias, slope, clamp));
}

extern "C" fn render_set_depth_clip_mode(encoder: *mut c_void, mode: u32) {
    let encoder = encoder!(encoder, RenderEncoder);
    if let Ok(mode) = DepthClipMode::try_from(mode) {
        report("setDepthClipMode", encoder.set_depth_clip_mode(mode));
    }
}

extern "C" fn render_set_fill_mode(encoder: *mut c_void, mode: u32) {
    let encoder = encoder!(encoder, RenderEncoder);
    if let Ok(mode) = TriangleFillMode::try_from(mode) {
        report("setTriangleFillMode", encoder.set_triangle_fill_mode(mode));
    }
}

extern "C" fn render_set_depth_stencil(encoder: *mut c_void, state: *mut c_void) {
    let encoder = encoder!(encoder, RenderEncoder);
    let state = if state.is_null() { None } else { get!(state, DepthStencil).map(|value| &*value) };
    report("setDepthStencilState", encoder.set_depth_stencil_state(state));
}

extern "C" fn render_set_stencil_reference(encoder: *mut c_void, front: u32, back: u32) {
    let encoder = encoder!(encoder, RenderEncoder);
    encoder.set_stencil_reference_values(front, back);
}

extern "C" fn render_set_blend_color(encoder: *mut c_void, red: f32, green: f32, blue: f32, alpha: f32) {
    let encoder = encoder!(encoder, RenderEncoder);
    encoder.set_blend_color(red, green, blue, alpha);
}

extern "C" fn render_set_visibility_mode(encoder: *mut c_void, mode: u32, offset: u64) {
    let encoder = encoder!(encoder, RenderEncoder);
    let mode = match mode {
        1 => VisibilityResultMode::Boolean,
        2 => VisibilityResultMode::Counting,
        _ => VisibilityResultMode::Disabled,
    };
    report("setVisibilityResultMode", encoder.set_visibility_result_mode(mode, offset));
}

fn primitive(raw: u32) -> Option<PrimitiveType> {
    PrimitiveType::try_from(raw).ok()
}

extern "C" fn render_draw(encoder: *mut c_void, kind: u32, start: u64, count: u64, instances: u64, base_instance: u64) {
    let encoder = encoder!(encoder, RenderEncoder);
    let Some(kind) = primitive(kind) else { return };
    report(
        "drawPrimitives",
        encoder.draw_primitives(kind, start as u32, count as u32, instances as u32, base_instance as u32),
    );
}

extern "C" fn render_draw_indexed(
    encoder: *mut c_void,
    kind: u32,
    count: u64,
    index_type: u32,
    index_buffer: *mut c_void,
    index_offset: u64,
    instances: u64,
    base_vertex: i64,
    base_instance: u64,
) {
    let encoder = encoder!(encoder, RenderEncoder);
    let Some(kind) = primitive(kind) else { return };
    let Some(index_buffer) = get!(index_buffer, Buffer) else { return };
    let Ok(index_type) = IndexType::try_from(index_type) else { return };
    report(
        "drawIndexedPrimitives",
        encoder.draw_indexed_primitives(
            kind,
            count as u32,
            index_type,
            index_buffer,
            index_offset,
            instances as u32,
            base_vertex as i32,
            base_instance as u32,
        ),
    );
}

extern "C" fn blit_encoder_new(command_buffer: *mut c_void) -> *mut c_void {
    let command_buffer = get_or!(command_buffer, CommandBuffer, std::ptr::null_mut());
    guard(std::ptr::null_mut(), || match command_buffer.buffer.blit_command_encoder() {
        Ok(encoder) => handle(Obj::BlitEncoder(Some(encoder))),
        Err(error) => fail(format!("blitCommandEncoder: {error}")),
    })
}

extern "C" fn blit_end(encoder: *mut c_void) -> c_int {
    let Some(Obj::BlitEncoder(slot)) = (unsafe { object_mut(encoder) }) else { return 0 };
    let Some(value) = slot.take() else { return 0 };
    guard(0, || match value.end_encoding() {
        Ok(()) => 1,
        Err(error) => {
            log_once(&format!("[Quadra Metal] blit endEncoding: {error}"));
            0
        }
    })
}

extern "C" fn blit_copy_buffer(
    encoder: *mut c_void,
    source: *mut c_void,
    source_offset: u64,
    destination: *mut c_void,
    destination_offset: u64,
    length: u64,
) {
    let encoder = encoder!(encoder, BlitEncoder);
    let (Some(source), Some(destination)) = (get!(source, Buffer), get!(destination, Buffer)) else { return };
    report(
        "copyFromBuffer:toBuffer:",
        encoder.copy_from_buffer_to_buffer(source, source_offset, destination, destination_offset, length),
    );
}

extern "C" fn blit_copy_buffer_to_texture(
    encoder: *mut c_void,
    source: *mut c_void,
    source_offset: u64,
    bytes_per_row: u64,
    bytes_per_image: u64,
    region_size: QmSize,
    destination: *mut c_void,
    slice: u64,
    level: u64,
    destination_origin: QmOrigin,
) {
    let encoder = encoder!(encoder, BlitEncoder);
    let (Some(source), Some(destination)) = (get!(source, Buffer), get!(destination, Texture)) else { return };
    report(
        "copyFromBuffer:toTexture:",
        encoder.copy_from_buffer_to_texture(
            source,
            source_offset,
            bytes_per_row,
            bytes_per_image,
            size(region_size),
            destination,
            slice,
            level,
            origin(destination_origin),
            BlitOption::None,
        ),
    );
}

extern "C" fn blit_copy_texture_to_buffer(
    encoder: *mut c_void,
    source: *mut c_void,
    slice: u64,
    level: u64,
    source_origin: QmOrigin,
    region_size: QmSize,
    destination: *mut c_void,
    destination_offset: u64,
    bytes_per_row: u64,
    bytes_per_image: u64,
) {
    let encoder = encoder!(encoder, BlitEncoder);
    let (Some(source), Some(destination)) = (get!(source, Texture), get!(destination, Buffer)) else { return };
    report(
        "copyFromTexture:toBuffer:",
        encoder.copy_from_texture_to_buffer(
            source,
            slice,
            level,
            origin(source_origin),
            size(region_size),
            destination,
            destination_offset,
            bytes_per_row,
            bytes_per_image,
            BlitOption::None,
        ),
    );
}

extern "C" fn blit_copy_texture(
    encoder: *mut c_void,
    source: *mut c_void,
    source_slice: u64,
    source_level: u64,
    source_origin: QmOrigin,
    region_size: QmSize,
    destination: *mut c_void,
    destination_slice: u64,
    destination_level: u64,
    destination_origin: QmOrigin,
) {
    let encoder = encoder!(encoder, BlitEncoder);
    let (Some(source), Some(destination)) = (get!(source, Texture), get!(destination, Texture)) else { return };
    report(
        "copyFromTexture:toTexture:",
        encoder.copy_from_texture_to_texture(
            source,
            source_slice,
            source_level,
            origin(source_origin),
            size(region_size),
            destination,
            destination_slice,
            destination_level,
            origin(destination_origin),
        ),
    );
}

extern "C" fn blit_copy_texture_slices(
    encoder: *mut c_void,
    source: *mut c_void,
    source_slice: u64,
    source_level: u64,
    destination: *mut c_void,
    destination_slice: u64,
    destination_level: u64,
    slice_count: u64,
    level_count: u64,
) {
    let encoder = encoder!(encoder, BlitEncoder);
    let (Some(source), Some(destination)) = (get!(source, Texture), get!(destination, Texture)) else { return };
    report(
        "copyFromTexture:sliceCount:levelCount:",
        encoder.copy_texture_slices(
            source,
            source_slice,
            source_level,
            destination,
            destination_slice,
            destination_level,
            slice_count,
            level_count,
        ),
    );
}

extern "C" fn blit_generate_mipmaps(encoder: *mut c_void, texture: *mut c_void) {
    let encoder = encoder!(encoder, BlitEncoder);
    let Some(texture) = get!(texture, Texture) else { return };
    report("generateMipmapsForTexture", encoder.generate_mipmaps(texture));
}

extern "C" fn blit_synchronize(encoder: *mut c_void, resource: *mut c_void) {
    let encoder = encoder!(encoder, BlitEncoder);
    let resource: ResourceRef<'_> = match unsafe { object(resource) } {
        Some(Obj::Buffer(buffer)) => buffer.as_resource(),
        Some(Obj::Texture(texture)) => texture.as_resource(),
        _ => return,
    };
    report("synchronizeResource", encoder.synchronize_resource(resource));
}

extern "C" fn compute_encoder_new(command_buffer: *mut c_void) -> *mut c_void {
    let command_buffer = get_or!(command_buffer, CommandBuffer, std::ptr::null_mut());
    guard(std::ptr::null_mut(), || match command_buffer.buffer.compute_command_encoder() {
        Ok(encoder) => handle(Obj::ComputeEncoder(Some(encoder))),
        Err(error) => fail(format!("computeCommandEncoder: {error}")),
    })
}

extern "C" fn compute_end(encoder: *mut c_void) -> c_int {
    let Some(Obj::ComputeEncoder(slot)) = (unsafe { object_mut(encoder) }) else { return 0 };
    let Some(value) = slot.take() else { return 0 };
    guard(0, || match value.end_encoding() {
        Ok(()) => 1,
        Err(error) => {
            log_once(&format!("[Quadra Metal] compute endEncoding: {error}"));
            0
        }
    })
}

extern "C" fn compute_set_pipeline(encoder: *mut c_void, pipeline: *mut c_void) {
    let encoder = encoder!(encoder, ComputeEncoder);
    let Some(pipeline) = get!(pipeline, ComputePipeline) else { return };
    report("setComputePipelineState", encoder.set_compute_pipeline_state(pipeline));
}

extern "C" fn compute_set_buffer(encoder: *mut c_void, buffer: *mut c_void, offset: u64, index: u32) {
    let encoder = encoder!(encoder, ComputeEncoder);
    report("setBuffer", encoder.set_buffer(optional_buffer(buffer), offset, index));
}

extern "C" fn compute_set_buffer_offset(encoder: *mut c_void, offset: u64, index: u32) {
    let encoder = encoder!(encoder, ComputeEncoder);
    report("setBufferOffset", encoder.set_buffer_offset(offset, index));
}

extern "C" fn compute_set_bytes(encoder: *mut c_void, bytes: *const c_void, length: u64, index: u32) {
    let encoder = encoder!(encoder, ComputeEncoder);
    let bytes = unsafe { std::slice::from_raw_parts(bytes as *const u8, length as usize) };
    report("setBytes", encoder.set_bytes(bytes, index));
}

extern "C" fn compute_set_texture(encoder: *mut c_void, texture: *mut c_void, index: u32) {
    let encoder = encoder!(encoder, ComputeEncoder);
    report("setTexture", encoder.set_texture(optional_texture(texture), index));
}

extern "C" fn compute_set_sampler(encoder: *mut c_void, sampler: *mut c_void, index: u32) {
    let encoder = encoder!(encoder, ComputeEncoder);
    let sampler = if sampler.is_null() { None } else { get!(sampler, Sampler).map(|value| &*value) };
    report("setSamplerState", encoder.set_sampler_state(sampler, index));
}

extern "C" fn compute_dispatch(encoder: *mut c_void, groups: QmSize, threads: QmSize) {
    let encoder = encoder!(encoder, ComputeEncoder);
    report("dispatchThreadgroups", encoder.dispatch_threadgroups(size(groups), size(threads)));
}

extern "C" fn surface_new(device: *mut c_void, target: *const present::QmSurfaceTarget) -> *mut c_void {
    let device = get_or!(device, Device, std::ptr::null_mut());
    let Some(target) = (unsafe { target.as_ref() }) else { return fail("no surface target") };
    guard(std::ptr::null_mut(), || match Surface::new(device, target) {
        Ok(surface) => handle(Obj::Surface(surface)),
        Err(error) => {
            log_once(&format!("[Quadra Metal] presentation surface: {error}"));
            fail(error)
        }
    })
}

extern "C" fn surface_configure(surface: *mut c_void, config: *const present::QmSurfaceConfig) -> c_int {
    let surface = get_or!(surface, Surface, 0);
    let Some(config) = (unsafe { config.as_ref() }) else { return 0 };
    guard(0, || match surface.configure(config) {
        Ok(()) => 1,
        Err(error) => {
            log_once(&format!("[Quadra Metal] surface configure: {error}"));
            set_error(error);
            0
        }
    })
}

extern "C" fn surface_next_drawable(surface: *mut c_void, texture: *mut *mut c_void) -> *mut c_void {
    let surface = get_or!(surface, Surface, std::ptr::null_mut());
    guard(std::ptr::null_mut(), || match surface.next_drawable() {
        Ok(drawable) => {
            if let Some(out) = unsafe { texture.as_mut() } {
                *out = handle(Obj::Texture(drawable.texture().clone()));
            }
            handle(Obj::Drawable(drawable))
        }
        Err(error) => {
            log_once(&format!("[Quadra Metal] nextDrawable: {error}"));
            fail(error)
        }
    })
}

extern "C" fn drawable_present(drawable: *mut c_void) -> c_int {
    let drawable = get_or!(drawable, Drawable, 0);
    guard(0, || match drawable.present_now() {
        Ok(()) => 1,
        Err(error) => {
            log_once(&format!("[Quadra Metal] present: {error}"));
            0
        }
    })
}

extern "C" fn log_text_once(text: *const c_char) {
    if !text.is_null() {
        log_once(&unsafe { CStr::from_ptr(text) }.to_string_lossy());
    }
}

// ---------------------------------------------------------------------------------------------

#[repr(C)]
pub struct QmApi {
    version: u32,
    size: u32,
    last_error: extern "C" fn() -> *const c_char,
    release: extern "C" fn(*mut c_void),
    device_create: extern "C" fn(*const c_void) -> *mut c_void,
    device_info: extern "C" fn(*mut c_void, *mut QmDeviceInfo),
    device_supports_family: extern "C" fn(*mut c_void, i64) -> c_int,
    device_supports_texture_sample_count: extern "C" fn(*mut c_void, u64) -> c_int,
    device_current_allocated_size: extern "C" fn(*mut c_void) -> u64,
    buffer_new: extern "C" fn(*mut c_void, u64, u64, *const c_void) -> *mut c_void,
    buffer_contents: extern "C" fn(*mut c_void) -> *mut c_void,
    buffer_length: extern "C" fn(*mut c_void) -> u64,
    buffer_did_modify_range: extern "C" fn(*mut c_void, u64, u64) -> c_int,
    texture_new: extern "C" fn(*mut c_void, *const QmTextureDesc) -> *mut c_void,
    texture_view: extern "C" fn(*mut c_void, u64, u64, u64, u64, u64, u64) -> *mut c_void,
    texture_describe: extern "C" fn(*mut c_void, *mut QmTextureDesc),
    texture_replace_region: extern "C" fn(*mut c_void, QmOrigin, QmSize, u64, u64, *const c_void, u64, u64) -> c_int,
    texture_get_bytes: extern "C" fn(*mut c_void, *mut c_void, u64, u64, u64, QmOrigin, QmSize, u64, u64) -> c_int,
    sampler_new: extern "C" fn(*mut c_void, *const QmSamplerDesc) -> *mut c_void,
    depth_stencil_new: extern "C" fn(*mut c_void, *const QmDepthStencilDesc) -> *mut c_void,
    library_new: extern "C" fn(*mut c_void, *const c_void, u64) -> *mut c_void,
    library_function_names: extern "C" fn(*mut c_void, *mut c_char, u64) -> u64,
    function_new: extern "C" fn(*mut c_void, *const c_char) -> *mut c_void,
    function_type: extern "C" fn(*mut c_void) -> c_int,
    render_pipeline_new: extern "C" fn(*mut c_void, *const QmRenderPipelineDesc) -> *mut c_void,
    compute_pipeline_new: extern "C" fn(*mut c_void, *mut c_void, *const c_char) -> *mut c_void,
    compute_pipeline_info: extern "C" fn(*mut c_void, *mut u32, *mut u32),
    queue_new: extern "C" fn(*mut c_void) -> *mut c_void,
    command_buffer_new: extern "C" fn(*mut c_void) -> *mut c_void,
    command_buffer_commit: extern "C" fn(*mut c_void) -> c_int,
    command_buffer_wait: extern "C" fn(*mut c_void) -> c_int,
    command_buffer_status: extern "C" fn(*mut c_void) -> c_int,
    command_buffer_times: extern "C" fn(*mut c_void, *mut f64, *mut f64),
    command_buffer_present: extern "C" fn(*mut c_void, *mut c_void) -> c_int,
    render_encoder_new: extern "C" fn(*mut c_void, *const QmRenderPassDesc) -> *mut c_void,
    render_end: extern "C" fn(*mut c_void) -> c_int,
    render_set_pipeline: extern "C" fn(*mut c_void, *mut c_void),
    render_set_buffer: extern "C" fn(*mut c_void, c_int, *mut c_void, u64, u32),
    render_set_buffer_offset: extern "C" fn(*mut c_void, c_int, u64, u32),
    render_set_bytes: extern "C" fn(*mut c_void, c_int, *const c_void, u64, u32),
    render_set_texture: extern "C" fn(*mut c_void, c_int, *mut c_void, u32),
    render_set_sampler: extern "C" fn(*mut c_void, c_int, *mut c_void, u32),
    render_set_viewport: extern "C" fn(*mut c_void, *const f64),
    render_set_scissor: extern "C" fn(*mut c_void, u64, u64, u64, u64),
    render_set_cull_mode: extern "C" fn(*mut c_void, u32),
    render_set_winding: extern "C" fn(*mut c_void, u32),
    render_set_depth_bias: extern "C" fn(*mut c_void, f32, f32, f32),
    render_set_depth_clip_mode: extern "C" fn(*mut c_void, u32),
    render_set_fill_mode: extern "C" fn(*mut c_void, u32),
    render_set_depth_stencil: extern "C" fn(*mut c_void, *mut c_void),
    render_set_stencil_reference: extern "C" fn(*mut c_void, u32, u32),
    render_set_blend_color: extern "C" fn(*mut c_void, f32, f32, f32, f32),
    render_set_visibility_mode: extern "C" fn(*mut c_void, u32, u64),
    render_draw: extern "C" fn(*mut c_void, u32, u64, u64, u64, u64),
    render_draw_indexed: extern "C" fn(*mut c_void, u32, u64, u32, *mut c_void, u64, u64, i64, u64),
    blit_encoder_new: extern "C" fn(*mut c_void) -> *mut c_void,
    blit_end: extern "C" fn(*mut c_void) -> c_int,
    blit_copy_buffer: extern "C" fn(*mut c_void, *mut c_void, u64, *mut c_void, u64, u64),
    blit_copy_buffer_to_texture: extern "C" fn(*mut c_void, *mut c_void, u64, u64, u64, QmSize, *mut c_void, u64, u64, QmOrigin),
    blit_copy_texture_to_buffer: extern "C" fn(*mut c_void, *mut c_void, u64, u64, QmOrigin, QmSize, *mut c_void, u64, u64, u64),
    blit_copy_texture: extern "C" fn(*mut c_void, *mut c_void, u64, u64, QmOrigin, QmSize, *mut c_void, u64, u64, QmOrigin),
    blit_copy_texture_slices: extern "C" fn(*mut c_void, *mut c_void, u64, u64, *mut c_void, u64, u64, u64, u64),
    blit_generate_mipmaps: extern "C" fn(*mut c_void, *mut c_void),
    blit_synchronize: extern "C" fn(*mut c_void, *mut c_void),
    compute_encoder_new: extern "C" fn(*mut c_void) -> *mut c_void,
    compute_end: extern "C" fn(*mut c_void) -> c_int,
    compute_set_pipeline: extern "C" fn(*mut c_void, *mut c_void),
    compute_set_buffer: extern "C" fn(*mut c_void, *mut c_void, u64, u32),
    compute_set_buffer_offset: extern "C" fn(*mut c_void, u64, u32),
    compute_set_bytes: extern "C" fn(*mut c_void, *const c_void, u64, u32),
    compute_set_texture: extern "C" fn(*mut c_void, *mut c_void, u32),
    compute_set_sampler: extern "C" fn(*mut c_void, *mut c_void, u32),
    compute_dispatch: extern "C" fn(*mut c_void, QmSize, QmSize),
    surface_new: extern "C" fn(*mut c_void, *const present::QmSurfaceTarget) -> *mut c_void,
    surface_configure: extern "C" fn(*mut c_void, *const present::QmSurfaceConfig) -> c_int,
    surface_next_drawable: extern "C" fn(*mut c_void, *mut *mut c_void) -> *mut c_void,
    drawable_present: extern "C" fn(*mut c_void) -> c_int,
    log_once: extern "C" fn(*const c_char),
}

static API: QmApi = QmApi {
    version: 1,
    size: std::mem::size_of::<QmApi>() as u32,
    last_error,
    release,
    device_create,
    device_info,
    device_supports_family,
    device_supports_texture_sample_count,
    device_current_allocated_size,
    buffer_new,
    buffer_contents,
    buffer_length,
    buffer_did_modify_range,
    texture_new,
    texture_view,
    texture_describe,
    texture_replace_region,
    texture_get_bytes,
    sampler_new,
    depth_stencil_new,
    library_new,
    library_function_names,
    function_new,
    function_type,
    render_pipeline_new,
    compute_pipeline_new,
    compute_pipeline_info,
    queue_new,
    command_buffer_new,
    command_buffer_commit,
    command_buffer_wait,
    command_buffer_status,
    command_buffer_times,
    command_buffer_present,
    render_encoder_new,
    render_end,
    render_set_pipeline,
    render_set_buffer,
    render_set_buffer_offset,
    render_set_bytes,
    render_set_texture,
    render_set_sampler,
    render_set_viewport,
    render_set_scissor,
    render_set_cull_mode,
    render_set_winding,
    render_set_depth_bias,
    render_set_depth_clip_mode,
    render_set_fill_mode,
    render_set_depth_stencil,
    render_set_stencil_reference,
    render_set_blend_color,
    render_set_visibility_mode,
    render_draw,
    render_draw_indexed,
    blit_encoder_new,
    blit_end,
    blit_copy_buffer,
    blit_copy_buffer_to_texture,
    blit_copy_texture_to_buffer,
    blit_copy_texture,
    blit_copy_texture_slices,
    blit_generate_mipmaps,
    blit_synchronize,
    compute_encoder_new,
    compute_end,
    compute_set_pipeline,
    compute_set_buffer,
    compute_set_buffer_offset,
    compute_set_bytes,
    compute_set_texture,
    compute_set_sampler,
    compute_dispatch,
    surface_new,
    surface_configure,
    surface_next_drawable,
    drawable_present,
    log_once: log_text_once,
};

/// Check the dynamically loaded LLVM shader upgrader before starting the game.
#[no_mangle]
pub extern "C" fn quadra_metal_host_check_air() -> c_int {
    guard(0, || match air::check_llvm() {
        Ok(()) => 1,
        Err(error) => {
            set_error(error);
            0
        }
    })
}

/// The table of quadra_metal.h, or null for another version.
#[no_mangle]
pub extern "C" fn quadra_metal_host_api(version: u32) -> *const QmApi {
    if version == API.version {
        &API
    } else {
        std::ptr::null()
    }
}

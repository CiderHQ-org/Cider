//! CAMetalLayer's frames on screen: a Vulkan swapchain on the layer's own window.
//!
//! - X11: a child window of the game window, made on this library's own Xlib connection,
//!   input-transparent (its input shape is empty), so the game window keeps every event.
//! - Wayland: the subsurface the shim's Wayland host made for the view
//!   (`macoblox_wayland_metal_surface`); the guest passes its `wl_display` and `wl_surface`.
//!
//! A drawable is a swapchain image the runtime wraps (`Device::new_texture_with_vk_image`,
//! homed in `PRESENT_SRC_KHR`). `nextDrawable` acquires with a fence and waits for it, as
//! Metal's blocks. `presentDrawable:` makes the command buffer signal the image's binary
//! semaphore after its work; once that command buffer is scheduled, the surface's presenter
//! thread queues the present on the device's presenting queue, waiting on the semaphore.
//! Swapchains replaced at a resize are destroyed only when no drawable of theirs is left and
//! the last command buffer that used each of their images has completed.
use crate::util::log_once;
use ash::vk;
use metal2vulkan::metal::{PixelFormat, TextureType, TextureUsage};
use metal2vulkan_runtime::{
    CommandBuffer, CommandQueue, Device, DeviceOptions, ResourceOptions, Texture, TextureDescriptor,
    VkImageLayouts,
};
use std::ffi::{c_char, c_int, c_uint, c_ulong, c_void, CStr, CString};
use std::sync::mpsc::{channel, Sender};
use std::sync::{Arc, Mutex, Weak};

#[repr(C)]
pub struct QmSurfaceTarget {
    kind: u32,
    pad: u32,
    x11_parent: u64,
    x11_display: *const c_char,
    wl_display: *mut c_void,
    wl_surface: *mut c_void,
}

#[repr(C)]
#[derive(Clone, Copy, Default, PartialEq, Eq, Debug)]
pub struct QmSurfaceConfig {
    x: i32,
    y: i32,
    width: u32,
    height: u32,
    drawable_width: u32,
    drawable_height: u32,
    pixel_format: u64,
    display_sync: u32,
    maximum_drawable_count: u32,
    framebuffer_only: u32,
    visible: u32,
}

/// Instance and device extensions presentation needs, of those the loader has.
pub fn add_surface_extensions(options: &mut DeviceOptions) {
    let available: Vec<CString> = match unsafe { ash::Entry::load() } {
        Ok(entry) => unsafe { entry.enumerate_instance_extension_properties(None) }
            .unwrap_or_default()
            .iter()
            .filter_map(|property| property.extension_name_as_c_str().ok().map(CStr::to_owned))
            .collect(),
        Err(_) => Vec::new(),
    };
    for name in [ash::khr::surface::NAME, ash::khr::xlib_surface::NAME, ash::khr::wayland_surface::NAME] {
        if available.iter().any(|have| have.as_c_str() == name) {
            options.instance_extensions.push(name.to_owned());
        }
    }
    options.device_extensions.push(ash::khr::swapchain::NAME.to_owned());
}

// ---------------------------------------------------------------------------------------------
// Xlib, opened at run time: the game's process already has the host's libX11 loaded.

type XDisplay = c_void;

struct Xlib {
    open_display: unsafe extern "C" fn(*const c_char) -> *mut XDisplay,
    create_window: unsafe extern "C" fn(
        *mut XDisplay, c_ulong, c_int, c_int, c_uint, c_uint, c_uint, c_int, c_uint, *mut c_void,
        c_ulong, *mut XSetWindowAttributes,
    ) -> c_ulong,
    map_raised: unsafe extern "C" fn(*mut XDisplay, c_ulong) -> c_int,
    unmap_window: unsafe extern "C" fn(*mut XDisplay, c_ulong) -> c_int,
    move_resize: unsafe extern "C" fn(*mut XDisplay, c_ulong, c_int, c_int, c_uint, c_uint) -> c_int,
    destroy_window: unsafe extern "C" fn(*mut XDisplay, c_ulong) -> c_int,
    flush: unsafe extern "C" fn(*mut XDisplay) -> c_int,
    sync: unsafe extern "C" fn(*mut XDisplay, c_int) -> c_int,
    set_error_handler: unsafe extern "C" fn(Option<unsafe extern "C" fn(*mut XDisplay, *mut c_void) -> c_int>) -> *mut c_void,
    shape_combine_rectangles: Option<
        unsafe extern "C" fn(*mut XDisplay, c_ulong, c_int, c_int, c_int, *mut c_void, c_int, c_int, c_int),
    >,
}

/// XSetWindowAttributes (LP64), of which only the background pixmap and event mask are set.
#[repr(C)]
#[derive(Default)]
struct XSetWindowAttributes {
    background_pixmap: c_ulong,
    background_pixel: c_ulong,
    border_pixmap: c_ulong,
    border_pixel: c_ulong,
    bit_gravity: c_int,
    win_gravity: c_int,
    backing_store: c_int,
    backing_planes: c_ulong,
    backing_pixel: c_ulong,
    save_under: c_int,
    event_mask: std::ffi::c_long,
    do_not_propagate_mask: std::ffi::c_long,
    override_redirect: c_int,
    colormap: c_ulong,
    cursor: c_ulong,
}

unsafe fn symbol<T>(library: *mut c_void, name: &CStr) -> Option<T> {
    let pointer = libc::dlsym(library, name.as_ptr());
    if pointer.is_null() {
        None
    } else {
        Some(std::mem::transmute_copy(&pointer))
    }
}

/// X errors on this library's connection (a destroyed parent while the game closes) are not
/// fatal; Xlib's default handler would end the process.
unsafe extern "C" fn x_error(_display: *mut XDisplay, _event: *mut c_void) -> c_int {
    0
}

fn xlib() -> Result<&'static Xlib, String> {
    static XLIB: std::sync::OnceLock<Result<Xlib, String>> = std::sync::OnceLock::new();
    XLIB.get_or_init(|| unsafe {
        let x11 = libc::dlopen(c"libX11.so.6".as_ptr(), libc::RTLD_NOW);
        if x11.is_null() {
            return Err("libX11.so.6 is missing".into());
        }
        let shape = libc::dlopen(c"libXext.so.6".as_ptr(), libc::RTLD_NOW);
        let missing = |name: &str| format!("libX11 has no {name}");
        Ok(Xlib {
            open_display: symbol(x11, c"XOpenDisplay").ok_or_else(|| missing("XOpenDisplay"))?,
            create_window: symbol(x11, c"XCreateWindow").ok_or_else(|| missing("XCreateWindow"))?,
            map_raised: symbol(x11, c"XMapRaised").ok_or_else(|| missing("XMapRaised"))?,
            unmap_window: symbol(x11, c"XUnmapWindow").ok_or_else(|| missing("XUnmapWindow"))?,
            move_resize: symbol(x11, c"XMoveResizeWindow").ok_or_else(|| missing("XMoveResizeWindow"))?,
            destroy_window: symbol(x11, c"XDestroyWindow").ok_or_else(|| missing("XDestroyWindow"))?,
            flush: symbol(x11, c"XFlush").ok_or_else(|| missing("XFlush"))?,
            sync: symbol(x11, c"XSync").ok_or_else(|| missing("XSync"))?,
            set_error_handler: symbol(x11, c"XSetErrorHandler").ok_or_else(|| missing("XSetErrorHandler"))?,
            shape_combine_rectangles: if shape.is_null() { None } else { symbol(shape, c"XShapeCombineRectangles") },
        })
    })
    .as_ref()
    .map_err(Clone::clone)
}

struct X11Child {
    display: *mut XDisplay,
    window: c_ulong,
    mapped: bool,
    geometry: (i32, i32, u32, u32),
}

impl X11Child {
    fn new(display_name: *const c_char, parent: c_ulong) -> Result<X11Child, String> {
        let x = xlib()?;
        unsafe {
            let display = (x.open_display)(display_name);
            if display.is_null() {
                return Err("cannot open the X display".into());
            }
            (x.set_error_handler)(Some(x_error));
            let mut attributes = XSetWindowAttributes::default(); // background None, no events
            const CW_BACK_PIXMAP: c_ulong = 1 << 0;
            const CW_EVENT_MASK: c_ulong = 1 << 11;
            let window = (x.create_window)(
                display, parent, 0, 0, 16, 16, 0, 0 /* CopyFromParent */, 1 /* InputOutput */,
                std::ptr::null_mut(), CW_BACK_PIXMAP | CW_EVENT_MASK, &mut attributes,
            );
            if window == 0 {
                return Err("XCreateWindow failed".into());
            }
            if let Some(combine) = x.shape_combine_rectangles {
                // ShapeInput, ShapeSet, no rectangles: clicks fall through to the game window.
                combine(display, window, 2, 0, 0, std::ptr::null_mut(), 0, 0, 0);
            }
            (x.sync)(display, 0);
            Ok(X11Child { display, window, mapped: false, geometry: (0, 0, 16, 16) })
        }
    }

    fn place(&mut self, config: &QmSurfaceConfig) {
        let Ok(x) = xlib() else { return };
        let geometry = (config.x, config.y, config.width.max(1), config.height.max(1));
        unsafe {
            if geometry != self.geometry {
                (x.move_resize)(self.display, self.window, geometry.0, geometry.1, geometry.2, geometry.3);
                self.geometry = geometry;
            }
            let visible = config.visible != 0;
            if visible && !self.mapped {
                (x.map_raised)(self.display, self.window);
            } else if !visible && self.mapped {
                (x.unmap_window)(self.display, self.window);
            }
            self.mapped = visible;
            (x.sync)(self.display, 0);
        }
    }
}

impl Drop for X11Child {
    fn drop(&mut self) {
        if let Ok(x) = xlib() {
            unsafe {
                (x.destroy_window)(self.display, self.window);
                (x.flush)(self.display);
            }
        }
    }
}

// ---------------------------------------------------------------------------------------------

fn vk_format(format: u64) -> Option<vk::Format> {
    Some(match format {
        70 => vk::Format::R8G8B8A8_UNORM,
        71 => vk::Format::R8G8B8A8_SRGB,
        80 => vk::Format::B8G8R8A8_UNORM,
        81 => vk::Format::B8G8R8A8_SRGB,
        90 => vk::Format::A2B10G10R10_UNORM_PACK32, // RGB10A2Unorm
        94 => vk::Format::A2R10G10B10_UNORM_PACK32, // BGR10A2Unorm
        115 => vk::Format::R16G16B16A16_SFLOAT,
        _ => return None,
    })
}

pub struct Chain {
    handle: vk::SwapchainKHR,
    textures: Vec<Texture>,
    semaphores: Vec<vk::Semaphore>,
    /// The last command buffer that presented each image: waited for before the chain goes.
    last_use: Mutex<Vec<Option<CommandBuffer>>>,
}

struct Inner {
    surface: vk::SurfaceKHR,
    x11: Option<X11Child>,
    config: QmSurfaceConfig,
    chain: Option<Arc<Chain>>,
    retired: Vec<Arc<Chain>>,
    dirty: bool,
    fence: vk::Fence,
    failures: u32,
}

pub struct Surface {
    device: Device,
    present_queue: CommandQueue,
    surface_fn: ash::khr::surface::Instance,
    swapchain_fn: ash::khr::swapchain::Device,
    inner: Mutex<Inner>,
    presenter: Mutex<Option<Sender<Arc<Drawable>>>>,
    presented: std::sync::atomic::AtomicU64,
}

// The raw Vulkan and X handles are used only under `inner`'s lock or by the presenter thread.
unsafe impl Send for Surface {}
unsafe impl Sync for Surface {}

pub struct Drawable {
    surface: Weak<Surface>,
    chain: Arc<Chain>,
    index: u32,
    texture: Texture,
    queued: std::sync::atomic::AtomicBool,
}

impl Surface {
    pub fn new(device: &Device, target: &QmSurfaceTarget) -> Result<Arc<Surface>, String> {
        let handles = unsafe { device.raw() };
        let entry = handles.entry;
        let instance = handles.instance;
        let surface_fn = ash::khr::surface::Instance::new(entry, instance);
        let (surface, x11) = match target.kind {
            1 => {
                let child = X11Child::new(target.x11_display, target.x11_parent as c_ulong)?;
                let xlib_fn = ash::khr::xlib_surface::Instance::new(entry, instance);
                let info = vk::XlibSurfaceCreateInfoKHR::default()
                    .dpy(child.display as *mut vk::Display)
                    .window(child.window);
                let surface = unsafe { xlib_fn.create_xlib_surface(&info, None) }
                    .map_err(|error| format!("vkCreateXlibSurfaceKHR: {error}"))?;
                (surface, Some(child))
            }
            2 => {
                if target.wl_display.is_null() || target.wl_surface.is_null() {
                    return Err("no Wayland surface for the Metal layer".into());
                }
                let wayland_fn = ash::khr::wayland_surface::Instance::new(entry, instance);
                let info = vk::WaylandSurfaceCreateInfoKHR::default()
                    .display(target.wl_display)
                    .surface(target.wl_surface);
                let surface = unsafe { wayland_fn.create_wayland_surface(&info, None) }
                    .map_err(|error| format!("vkCreateWaylandSurfaceKHR: {error}"))?;
                (surface, None)
            }
            other => return Err(format!("unknown surface kind {other}")),
        };
        let present_queue = device
            .new_command_queue_for_presenting()
            .map_err(|error| format!("presenting queue: {error}"))?;
        let family = unsafe { present_queue.with_vk_queue(|_, family| family) };
        let supported = unsafe {
            surface_fn.get_physical_device_surface_support(handles.physical_device, family, surface)
        }
        .unwrap_or(false);
        if !supported {
            unsafe { surface_fn.destroy_surface(surface, None) };
            return Err(format!("queue family {family} cannot present to this window"));
        }
        let swapchain_fn = ash::khr::swapchain::Device::new(instance, handles.device);
        let fence = unsafe { handles.device.create_fence(&vk::FenceCreateInfo::default(), None) }
            .map_err(|error| format!("vkCreateFence: {error}"))?;
        let surface = Arc::new(Surface {
            device: device.clone(),
            present_queue,
            surface_fn,
            swapchain_fn,
            inner: Mutex::new(Inner {
                surface,
                x11,
                config: QmSurfaceConfig::default(),
                chain: None,
                retired: Vec::new(),
                dirty: true,
                fence,
                failures: 0,
            }),
            presenter: Mutex::new(None),
            presented: std::sync::atomic::AtomicU64::new(0),
        });
        let (sender, receiver) = channel::<Arc<Drawable>>();
        let weak = Arc::downgrade(&surface);
        std::thread::Builder::new()
            .name("quadra-metal-present".into())
            .spawn(move || {
                for drawable in receiver {
                    let Some(surface) = weak.upgrade() else { break };
                    surface.queue_present(&drawable, true);
                }
            })
            .map_err(|error| format!("presenter thread: {error}"))?;
        *surface.presenter.lock().unwrap() = Some(sender);
        log_once(&format!(
            "[Quadra Metal] presenting through {}",
            if target.kind == 1 { "an X11 child window" } else { "a Wayland subsurface" }
        ));
        Ok(surface)
    }

    pub fn configure(&self, config: &QmSurfaceConfig) -> Result<(), String> {
        let mut inner = self.inner.lock().unwrap();
        if let Some(child) = inner.x11.as_mut() {
            child.place(config);
        }
        let chain_changed = inner.config.drawable_width != config.drawable_width
            || inner.config.drawable_height != config.drawable_height
            || inner.config.pixel_format != config.pixel_format
            || inner.config.display_sync != config.display_sync
            || inner.config.maximum_drawable_count != config.maximum_drawable_count
            || inner.config.framebuffer_only != config.framebuffer_only;
        inner.dirty |= chain_changed;
        inner.config = *config;
        Ok(())
    }

    fn present_mode(&self, surface: vk::SurfaceKHR, display_sync: bool) -> vk::PresentModeKHR {
        let handles = unsafe { self.device.raw() };
        let modes = unsafe {
            self.surface_fn.get_physical_device_surface_present_modes(handles.physical_device, surface)
        }
        .unwrap_or_default();
        let wanted = match std::env::var("MACOBLOX_METAL_PRESENT_MODE").as_deref() {
            Ok("fifo") => vec![vk::PresentModeKHR::FIFO],
            Ok("mailbox") => vec![vk::PresentModeKHR::MAILBOX, vk::PresentModeKHR::IMMEDIATE],
            Ok("immediate") => vec![vk::PresentModeKHR::IMMEDIATE, vk::PresentModeKHR::MAILBOX],
            _ if display_sync => vec![vk::PresentModeKHR::FIFO],
            _ => vec![vk::PresentModeKHR::MAILBOX, vk::PresentModeKHR::IMMEDIATE],
        };
        wanted.into_iter().find(|mode| modes.contains(mode)).unwrap_or(vk::PresentModeKHR::FIFO)
    }

    /// Makes the swapchain for the current configuration, retiring the old one.
    fn rebuild(&self, inner: &mut Inner) -> Result<(), String> {
        let config = inner.config;
        let format = vk_format(config.pixel_format)
            .ok_or_else(|| format!("CAMetalLayer pixel format {} has no swapchain format", config.pixel_format))?;
        let handles = unsafe { self.device.raw() };
        let caps = unsafe {
            self.surface_fn.get_physical_device_surface_capabilities(handles.physical_device, inner.surface)
        }
        .map_err(|error| format!("surface capabilities: {error}"))?;
        let formats = unsafe {
            self.surface_fn.get_physical_device_surface_formats(handles.physical_device, inner.surface)
        }
        .map_err(|error| format!("surface formats: {error}"))?;
        let Some(surface_format) = formats.iter().find(|entry| entry.format == format) else {
            return Err(format!("the window cannot show Vulkan format {} (it offers {:?})", format.as_raw(),
                formats.iter().map(|entry| entry.format.as_raw()).collect::<Vec<_>>()));
        };
        let mut extent = vk::Extent2D { width: config.drawable_width.max(1), height: config.drawable_height.max(1) };
        if caps.current_extent.width != u32::MAX {
            // X11: the window decides. The child window follows the drawable size, so a
            // mismatch is a resize the window has not reached yet.
            extent = caps.current_extent;
        }
        extent.width = extent.width.clamp(caps.min_image_extent.width.max(1), caps.max_image_extent.width.max(1));
        extent.height = extent.height.clamp(caps.min_image_extent.height.max(1), caps.max_image_extent.height.max(1));
        let wanted_images = config.maximum_drawable_count.clamp(2, 3);
        let mut images = wanted_images.max(caps.min_image_count);
        if caps.max_image_count != 0 {
            images = images.min(caps.max_image_count);
        }
        let mut usage = vk::ImageUsageFlags::COLOR_ATTACHMENT | vk::ImageUsageFlags::TRANSFER_SRC | vk::ImageUsageFlags::TRANSFER_DST;
        let mut texture_usage = TextureUsage::RENDER_TARGET;
        if config.framebuffer_only == 0 {
            usage |= vk::ImageUsageFlags::SAMPLED;
            texture_usage |= TextureUsage::SHADER_READ;
        }
        usage &= caps.supported_usage_flags;
        let mode = self.present_mode(inner.surface, config.display_sync != 0);
        let old = inner.chain.take();
        let info = vk::SwapchainCreateInfoKHR::default()
            .surface(inner.surface)
            .min_image_count(images)
            .image_format(format)
            .image_color_space(surface_format.color_space)
            .image_extent(extent)
            .image_array_layers(1)
            .image_usage(usage)
            .image_sharing_mode(vk::SharingMode::EXCLUSIVE)
            .pre_transform(caps.current_transform)
            .composite_alpha(if caps.supported_composite_alpha.contains(vk::CompositeAlphaFlagsKHR::OPAQUE) {
                vk::CompositeAlphaFlagsKHR::OPAQUE
            } else {
                vk::CompositeAlphaFlagsKHR::INHERIT
            })
            .present_mode(mode)
            .clipped(true)
            .old_swapchain(old.as_ref().map_or(vk::SwapchainKHR::null(), |chain| chain.handle));
        let handle = self.device.with_loader_word(|| unsafe { self.swapchain_fn.create_swapchain(&info, None) })
            .map_err(|error| format!("vkCreateSwapchainKHR {}x{} format {}: {error}", extent.width, extent.height, format.as_raw()))?;
        if let Some(old) = old {
            inner.retired.push(old);
        }
        let vk_images = unsafe { self.swapchain_fn.get_swapchain_images(handle) }
            .map_err(|error| format!("vkGetSwapchainImagesKHR: {error}"))?;
        let pixel_format = PixelFormat::try_from(config.pixel_format as u32).map_err(|_| "pixel format")?;
        let mut textures = Vec::with_capacity(vk_images.len());
        let mut semaphores = Vec::with_capacity(vk_images.len());
        for image in &vk_images {
            let mut descriptor = TextureDescriptor::texture_2d(pixel_format, extent.width as u64, extent.height as u64, false);
            descriptor.texture_type = TextureType::Type2D;
            descriptor.usage = texture_usage;
            descriptor.resource_options = ResourceOptions::private();
            descriptor.framebuffer_only = config.framebuffer_only != 0;
            descriptor.is_drawable = true;
            let image_info = vk::ImageCreateInfo::default()
                .image_type(vk::ImageType::TYPE_2D)
                .format(format)
                .extent(vk::Extent3D { width: extent.width, height: extent.height, depth: 1 })
                .mip_levels(1)
                .array_layers(1)
                .samples(vk::SampleCountFlags::TYPE_1)
                .tiling(vk::ImageTiling::OPTIMAL)
                .usage(usage)
                .sharing_mode(vk::SharingMode::EXCLUSIVE)
                .initial_layout(vk::ImageLayout::UNDEFINED);
            let layouts = VkImageLayouts::new(
                metal2vulkan::vk::ImageLayout::UNDEFINED,
                metal2vulkan::vk::ImageLayout::PRESENT_SRC_KHR,
            );
            let texture = unsafe { self.device.new_texture_with_vk_image(&descriptor, *image, &image_info, layouts) }
                .map_err(|error| format!("wrapping a swapchain image: {error}"))?;
            textures.push(texture);
            let semaphore = unsafe { handles.device.create_semaphore(&vk::SemaphoreCreateInfo::default(), None) }
                .map_err(|error| format!("vkCreateSemaphore: {error}"))?;
            semaphores.push(semaphore);
        }
        log_once(&format!(
            "[Quadra Metal] swapchain {}x{} format {}, {} images, present mode {}",
            extent.width, extent.height, format.as_raw(), vk_images.len(), mode.as_raw()
        ));
        inner.chain = Some(Arc::new(Chain {
            handle,
            last_use: Mutex::new(vec![None; vk_images.len()]),
            textures,
            semaphores,
        }));
        inner.dirty = false;
        Ok(())
    }

    /// Destroys retired chains no drawable holds once their GPU work is done.
    fn reap(&self, inner: &mut Inner) {
        let handles = unsafe { self.device.raw() };
        let mut kept = Vec::new();
        for chain in inner.retired.drain(..) {
            if Arc::strong_count(&chain) > 1 {
                kept.push(chain);
                continue;
            }
            for buffer in chain.last_use.lock().unwrap().iter().flatten() {
                let _ = buffer.wait_until_completed();
            }
            unsafe {
                self.present_queue.with_vk_queue(|queue, _| handles.device.queue_wait_idle(queue).ok());
            }
            let Ok(chain) = Arc::try_unwrap(chain) else { continue };
            let Chain { handle, textures, semaphores, .. } = chain;
            drop(textures);
            unsafe {
                for semaphore in semaphores {
                    handles.device.destroy_semaphore(semaphore, None);
                }
                self.device.with_loader_word(|| self.swapchain_fn.destroy_swapchain(handle, None));
            }
        }
        inner.retired = kept;
    }

    pub fn next_drawable(self: &Arc<Self>) -> Result<Arc<Drawable>, String> {
        let handles = unsafe { self.device.raw() };
        let mut inner = self.inner.lock().unwrap();
        self.reap(&mut inner);
        for _attempt in 0..3 {
            if inner.dirty || inner.chain.is_none() {
                if let Err(error) = self.rebuild(&mut inner) {
                    inner.failures += 1;
                    return Err(error);
                }
            }
            let chain = inner.chain.clone().unwrap();
            let fence = inner.fence;
            let result = unsafe {
                self.swapchain_fn.acquire_next_image(chain.handle, 1_000_000_000, vk::Semaphore::null(), fence)
            };
            match result {
                Ok((index, suboptimal)) => {
                    unsafe {
                        handles.device.wait_for_fences(&[fence], true, 2_000_000_000)
                            .map_err(|error| format!("waiting for the acquire fence: {error}"))?;
                        handles.device.reset_fences(&[fence]).map_err(|error| format!("vkResetFences: {error}"))?;
                    }
                    if suboptimal {
                        inner.dirty = true;
                    }
                    return Ok(Arc::new(Drawable {
                        surface: Arc::downgrade(self),
                        texture: chain.textures[index as usize].clone(),
                        chain,
                        index,
                        queued: false.into(),
                    }));
                }
                Err(vk::Result::ERROR_OUT_OF_DATE_KHR) => inner.dirty = true,
                Err(vk::Result::TIMEOUT) | Err(vk::Result::NOT_READY) => {
                    return Err("no drawable became free within a second".into())
                }
                Err(error) => return Err(format!("vkAcquireNextImageKHR: {error}")),
            }
        }
        Err("the window kept changing while acquiring a drawable".into())
    }

    fn queue_present(&self, drawable: &Drawable, wait: bool) {
        let mut inner = self.inner.lock().unwrap();
        let chain = &drawable.chain;
        let semaphores = [chain.semaphores[drawable.index as usize]];
        let swapchains = [chain.handle];
        let indices = [drawable.index];
        let mut info = vk::PresentInfoKHR::default().swapchains(&swapchains).image_indices(&indices);
        if wait {
            info = info.wait_semaphores(&semaphores);
        }
        let result = unsafe {
            self.present_queue.with_vk_queue(|queue, _| self.swapchain_fn.queue_present(queue, &info))
        };
        match result {
            Ok(false) => {
                let count = self.presented.fetch_add(1, std::sync::atomic::Ordering::Relaxed) + 1;
                if matches!(count, 1 | 60 | 600) {
                    log_once(&format!("[Quadra Metal] presented {count} Vulkan frames"));
                }
            }
            Ok(true) | Err(vk::Result::ERROR_OUT_OF_DATE_KHR) => {
                if inner.chain.as_ref().is_some_and(|current| Arc::ptr_eq(current, chain)) {
                    inner.dirty = true;
                }
            }
            Err(error) => log_once(&format!("[Quadra Metal] vkQueuePresentKHR: {error}")),
        }
    }
}

impl Drop for Surface {
    fn drop(&mut self) {
        let handles = unsafe { self.device.raw() };
        let inner = self.inner.get_mut().unwrap();
        if let Some(chain) = inner.chain.take() {
            inner.retired.push(chain);
        }
        for chain in inner.retired.drain(..) {
            for buffer in chain.last_use.lock().unwrap().iter().flatten() {
                let _ = buffer.wait_until_completed();
            }
            unsafe {
                self.present_queue.with_vk_queue(|queue, _| handles.device.queue_wait_idle(queue).ok());
                for semaphore in &chain.semaphores {
                    handles.device.destroy_semaphore(*semaphore, None);
                }
                self.device.with_loader_word(|| self.swapchain_fn.destroy_swapchain(chain.handle, None));
            }
        }
        unsafe {
            handles.device.destroy_fence(inner.fence, None);
            self.surface_fn.destroy_surface(inner.surface, None);
        }
    }
}

impl Drawable {
    pub fn texture(&self) -> &Texture {
        &self.texture
    }

    /// `presentDrawable:` of a command buffer, at its commit.
    pub fn encode_present(self: &Arc<Self>, buffer: &CommandBuffer) -> Result<(), String> {
        if self.queued.swap(true, std::sync::atomic::Ordering::AcqRel) {
            return Ok(()); // Metal presents a drawable once.
        }
        let Some(surface) = self.surface.upgrade() else { return Ok(()) };
        let semaphore = self.chain.semaphores[self.index as usize];
        unsafe { buffer.encode_signal_vk_semaphore(semaphore) }.map_err(|error| format!("signal: {error}"))?;
        self.chain.last_use.lock().unwrap()[self.index as usize] = Some(buffer.clone());
        let sender = surface.presenter.lock().unwrap().clone();
        let drawable = self.clone();
        buffer
            .add_scheduled_handler(Box::new(move |_| {
                if let Some(sender) = sender {
                    let _ = sender.send(drawable);
                }
            }))
            .map_err(|error| format!("scheduled handler: {error}"))
    }

    /// `-[CAMetalDrawable present]` outside a command buffer: after the device's queued work.
    pub fn present_now(self: &Arc<Self>) -> Result<(), String> {
        if self.queued.swap(true, std::sync::atomic::Ordering::AcqRel) {
            return Ok(());
        }
        let Some(surface) = self.surface.upgrade() else { return Ok(()) };
        let buffer = surface.present_queue.command_buffer().map_err(|error| format!("{error}"))?;
        self.queued.store(false, std::sync::atomic::Ordering::Release);
        self.encode_present(&buffer)?;
        buffer.commit().map_err(|error| format!("commit: {error}"))
    }
}

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
    CommandBuffer, CommandQueue, Device, DeviceOptions, ResourceOptions, Texture,
    TextureDescriptor, VkImageLayouts,
};
use std::ffi::{c_char, c_int, c_uint, c_ulong, c_void, CStr, CString};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{sync_channel, SyncSender};
use std::sync::{Arc, Mutex, Weak};
use std::time::Duration;

/// Mailbox stays synchronized to vblank while replacing obsolete pending frames. FIFO's
/// compositor backpressure must not be mistaken for a shader or GPU bottleneck.
fn select_present_mode(
    available: &[vk::PresentModeKHR],
    display_sync: bool,
    requested: Option<&str>,
) -> vk::PresentModeKHR {
    let wanted: &[vk::PresentModeKHR] = match requested {
        Some("fifo") => &[vk::PresentModeKHR::FIFO],
        Some("mailbox") => &[vk::PresentModeKHR::MAILBOX, vk::PresentModeKHR::FIFO],
        Some("immediate") => &[
            vk::PresentModeKHR::IMMEDIATE,
            vk::PresentModeKHR::MAILBOX,
            vk::PresentModeKHR::FIFO,
        ],
        _ if display_sync => &[vk::PresentModeKHR::MAILBOX, vk::PresentModeKHR::FIFO],
        _ => &[
            vk::PresentModeKHR::IMMEDIATE,
            vk::PresentModeKHR::MAILBOX,
            vk::PresentModeKHR::FIFO,
        ],
    };
    wanted
        .iter()
        .copied()
        .find(|mode| available.contains(mode))
        .unwrap_or(vk::PresentModeKHR::FIFO)
}

fn image_count(requested: u32, minimum: u32, maximum: u32, mode: vk::PresentModeKHR) -> u32 {
    let mut count = requested.clamp(2, 3).max(minimum);
    // Mailbox's nonblocking guarantee, when the application owns no other images, needs
    // minImageCount + 1, rather than a hardcoded assumption of three images on every driver.
    if mode == vk::PresentModeKHR::MAILBOX {
        count = count.max(minimum.saturating_add(1));
    }
    if maximum != 0 {
        count = count.min(maximum);
    }
    count
}

fn composite_alpha(supported: vk::CompositeAlphaFlagsKHR) -> Option<vk::CompositeAlphaFlagsKHR> {
    [
        vk::CompositeAlphaFlagsKHR::OPAQUE,
        vk::CompositeAlphaFlagsKHR::INHERIT,
        vk::CompositeAlphaFlagsKHR::PRE_MULTIPLIED,
        vk::CompositeAlphaFlagsKHR::POST_MULTIPLIED,
    ]
    .into_iter()
    .find(|mode| supported.contains(*mode))
}

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
    for name in [
        ash::khr::surface::NAME,
        ash::khr::xlib_surface::NAME,
        ash::khr::wayland_surface::NAME,
    ] {
        if available.iter().any(|have| have.as_c_str() == name) {
            options.instance_extensions.push(name.to_owned());
        }
    }
    options
        .device_extensions
        .push(ash::khr::swapchain::NAME.to_owned());
}

// ---------------------------------------------------------------------------------------------
// Xlib, opened at run time: the game's process already has the host's libX11 loaded.

type XDisplay = c_void;

struct Xlib {
    open_display: unsafe extern "C" fn(*const c_char) -> *mut XDisplay,
    close_display: unsafe extern "C" fn(*mut XDisplay) -> c_int,
    create_window: unsafe extern "C" fn(
        *mut XDisplay,
        c_ulong,
        c_int,
        c_int,
        c_uint,
        c_uint,
        c_uint,
        c_int,
        c_uint,
        *mut c_void,
        c_ulong,
        *mut XSetWindowAttributes,
    ) -> c_ulong,
    map_raised: unsafe extern "C" fn(*mut XDisplay, c_ulong) -> c_int,
    unmap_window: unsafe extern "C" fn(*mut XDisplay, c_ulong) -> c_int,
    move_resize:
        unsafe extern "C" fn(*mut XDisplay, c_ulong, c_int, c_int, c_uint, c_uint) -> c_int,
    destroy_window: unsafe extern "C" fn(*mut XDisplay, c_ulong) -> c_int,
    flush: unsafe extern "C" fn(*mut XDisplay) -> c_int,
    sync: unsafe extern "C" fn(*mut XDisplay, c_int) -> c_int,
    set_error_handler: unsafe extern "C" fn(
        Option<unsafe extern "C" fn(*mut XDisplay, *mut c_void) -> c_int>,
    ) -> *mut c_void,
    shape_combine_rectangles: Option<
        unsafe extern "C" fn(
            *mut XDisplay,
            c_ulong,
            c_int,
            c_int,
            c_int,
            *mut c_void,
            c_int,
            c_int,
            c_int,
        ),
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
            close_display: symbol(x11, c"XCloseDisplay").ok_or_else(|| missing("XCloseDisplay"))?,
            create_window: symbol(x11, c"XCreateWindow").ok_or_else(|| missing("XCreateWindow"))?,
            map_raised: symbol(x11, c"XMapRaised").ok_or_else(|| missing("XMapRaised"))?,
            unmap_window: symbol(x11, c"XUnmapWindow").ok_or_else(|| missing("XUnmapWindow"))?,
            move_resize: symbol(x11, c"XMoveResizeWindow")
                .ok_or_else(|| missing("XMoveResizeWindow"))?,
            destroy_window: symbol(x11, c"XDestroyWindow")
                .ok_or_else(|| missing("XDestroyWindow"))?,
            flush: symbol(x11, c"XFlush").ok_or_else(|| missing("XFlush"))?,
            sync: symbol(x11, c"XSync").ok_or_else(|| missing("XSync"))?,
            set_error_handler: symbol(x11, c"XSetErrorHandler")
                .ok_or_else(|| missing("XSetErrorHandler"))?,
            shape_combine_rectangles: if shape.is_null() {
                None
            } else {
                symbol(shape, c"XShapeCombineRectangles")
            },
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
                display,
                parent,
                0,
                0,
                16,
                16,
                0,
                0, /* CopyFromParent */
                1, /* InputOutput */
                std::ptr::null_mut(),
                CW_BACK_PIXMAP | CW_EVENT_MASK,
                &mut attributes,
            );
            if window == 0 {
                (x.close_display)(display);
                return Err("XCreateWindow failed".into());
            }
            if let Some(combine) = x.shape_combine_rectangles {
                // ShapeInput, ShapeSet, no rectangles: clicks fall through to the game window.
                combine(display, window, 2, 0, 0, std::ptr::null_mut(), 0, 0, 0);
            }
            (x.sync)(display, 0);
            Ok(X11Child {
                display,
                window,
                mapped: false,
                geometry: (0, 0, 16, 16),
            })
        }
    }

    fn place(&mut self, config: &QmSurfaceConfig) {
        let Ok(x) = xlib() else { return };
        let geometry = (
            config.x,
            config.y,
            config.width.max(1),
            config.height.max(1),
        );
        unsafe {
            if geometry != self.geometry {
                (x.move_resize)(
                    self.display,
                    self.window,
                    geometry.0,
                    geometry.1,
                    geometry.2,
                    geometry.3,
                );
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
                (x.close_display)(self.display);
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

/// Shared by every image owner, so the surface and X connection outlive all swapchains.
struct SurfaceLife {
    _device: Device,
    functions: ash::khr::surface::Instance,
    handle: vk::SurfaceKHR,
    x11: Mutex<Option<X11Child>>,
}
unsafe impl Send for SurfaceLife {}
unsafe impl Sync for SurfaceLife {}
impl Drop for SurfaceLife {
    fn drop(&mut self) {
        unsafe { self.functions.destroy_surface(self.handle, None) };
    }
}

/// Owns raw WSI objects. Wrapped textures retain this owner through views and GPU uses, while
/// the owner holds none of those textures. Also cleans up a partially constructed chain.
struct ChainOwner {
    device: Device,
    queue: CommandQueue,
    functions: ash::khr::swapchain::Device,
    _surface: Arc<SurfaceLife>,
    handle: vk::SwapchainKHR,
    semaphores: Vec<vk::Semaphore>,
    last_use: Mutex<Vec<Option<CommandBuffer>>>,
}
impl Drop for ChainOwner {
    fn drop(&mut self) {
        for buffer in self.last_use.get_mut().unwrap().iter().flatten() {
            let _ = buffer.wait_until_completed();
        }
        let handles = unsafe { self.device.raw() };
        unsafe {
            self.queue
                .with_vk_queue(|queue, _| handles.device.queue_wait_idle(queue).ok());
            for &semaphore in &self.semaphores {
                handles.device.destroy_semaphore(semaphore, None);
            }
            self.device
                .with_loader_word(|| self.functions.destroy_swapchain(self.handle, None));
        }
    }
}

pub struct Chain {
    textures: Vec<Texture>,
    owner: Arc<ChainOwner>,
    abandoned: AtomicBool,
    statistics: Option<Arc<crate::diagnostics::PresentationStatistics>>,
    made: std::time::Instant,
    /// The drawables of this chain the game holds: acquired and not yet released.
    held: std::sync::atomic::AtomicU32,
    /// The drawables of this chain queued for presentation whose present call has not returned.
    unpresented: std::sync::atomic::AtomicU32,
}

struct Acquire {
    device: Device,
    fence: vk::Fence,
    /// A successful acquire whose fence has not completed yet keeps its chain alive.
    pending: Option<Arc<Chain>>,
}
impl Drop for Acquire {
    fn drop(&mut self) {
        let handles = unsafe { self.device.raw() };
        unsafe {
            if self.pending.is_some() {
                let _ = handles
                    .device
                    .wait_for_fences(&[self.fence], true, u64::MAX);
            }
            handles.device.destroy_fence(self.fence, None);
        }
    }
}

struct Inner {
    config: QmSurfaceConfig,
    chain: Option<Arc<Chain>>,
    retired: Vec<Arc<Chain>>,
    dirty: bool,
    failures: u32,
}

pub struct Surface {
    device: Device,
    present_queue: CommandQueue,
    surface_fn: ash::khr::surface::Instance,
    swapchain_fn: ash::khr::swapchain::Device,
    inner: Mutex<Inner>,
    life: Arc<SurfaceLife>,
    acquire: Mutex<Acquire>,
    presenter: Mutex<Option<SyncSender<QueuedDrawable>>>,
    statistics: Option<Arc<crate::diagnostics::PresentationStatistics>>,
    presented: std::sync::atomic::AtomicU64,
    /// When a present call last returned, as nanoseconds after `born`.
    last_present: std::sync::atomic::AtomicU64,
    born: std::time::Instant,
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

struct QueuedDrawable {
    drawable: Arc<Drawable>,
    ready: Option<std::time::Instant>,
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
        let life = Arc::new(SurfaceLife {
            _device: device.clone(),
            functions: surface_fn.clone(),
            handle: surface,
            x11: Mutex::new(x11),
        });
        let present_queue = device
            .new_command_queue_for_presenting()
            .map_err(|error| format!("presenting queue: {error}"))?;
        let family = unsafe { present_queue.with_vk_queue(|_, family| family) };
        let supported = unsafe {
            surface_fn.get_physical_device_surface_support(handles.physical_device, family, surface)
        }
        .unwrap_or(false);
        if !supported {
            return Err(format!(
                "queue family {family} cannot present to this window"
            ));
        }
        let swapchain_fn = ash::khr::swapchain::Device::new(instance, handles.device);
        let fence = unsafe {
            handles
                .device
                .create_fence(&vk::FenceCreateInfo::default(), None)
        }
        .map_err(|error| format!("vkCreateFence: {error}"))?;
        let surface = Arc::new(Surface {
            device: device.clone(),
            present_queue,
            surface_fn,
            swapchain_fn,
            inner: Mutex::new(Inner {
                config: QmSurfaceConfig::default(),
                chain: None,
                retired: Vec::new(),
                dirty: true,
                failures: 0,
            }),
            life,
            acquire: Mutex::new(Acquire {
                device: device.clone(),
                fence,
                pending: None,
            }),
            presenter: Mutex::new(None),
            statistics: crate::diagnostics::presentation(device),
            presented: std::sync::atomic::AtomicU64::new(0),
            last_present: std::sync::atomic::AtomicU64::new(0),
            born: std::time::Instant::now(),
        });
        // A blocked compositor must not accumulate an unbounded queue through resizes.
        let (sender, receiver) = sync_channel::<QueuedDrawable>(16);
        let weak = Arc::downgrade(&surface);
        std::thread::Builder::new()
            .name("quadra-metal-present".into())
            .spawn(move || {
                for queued in receiver {
                    let Some(surface) = weak.upgrade() else { break };
                    if let Some(ready) = queued.ready {
                        crate::diagnostics::duration(
                            &surface.device,
                            crate::diagnostics::Phase::PresentQueue,
                            ready.elapsed(),
                        );
                    }
                    surface.queue_present(&queued.drawable, true);
                }
            })
            .map_err(|error| format!("presenter thread: {error}"))?;
        *surface.presenter.lock().unwrap() = Some(sender);
        log_once(&format!(
            "[Quadra Metal] presenting through {}",
            if target.kind == 1 {
                "an X11 child window"
            } else {
                "a Wayland subsurface"
            }
        ));
        Ok(surface)
    }

    pub fn configure(&self, config: &QmSurfaceConfig) -> Result<(), String> {
        let mut inner = self.inner.lock().unwrap();
        if let Some(child) = self.life.x11.lock().unwrap().as_mut() {
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
            self.surface_fn
                .get_physical_device_surface_present_modes(handles.physical_device, surface)
        }
        .unwrap_or_default();
        let requested = std::env::var("MACOBLOX_METAL_PRESENT_MODE").ok();
        select_present_mode(&modes, display_sync, requested.as_deref())
    }

    /// Makes the swapchain for the current configuration, retiring the old one.
    fn rebuild(&self, inner: &mut Inner) -> Result<(), String> {
        let config = inner.config;
        let format = vk_format(config.pixel_format).ok_or_else(|| {
            format!(
                "CAMetalLayer pixel format {} has no swapchain format",
                config.pixel_format
            )
        })?;
        let handles = unsafe { self.device.raw() };
        let caps = unsafe {
            self.surface_fn
                .get_physical_device_surface_capabilities(handles.physical_device, self.life.handle)
        }
        .map_err(|error| format!("surface capabilities: {error}"))?;
        let formats = unsafe {
            self.surface_fn
                .get_physical_device_surface_formats(handles.physical_device, self.life.handle)
        }
        .map_err(|error| format!("surface formats: {error}"))?;
        let Some(surface_format) = formats
            .iter()
            .find(|entry| entry.format == format || entry.format == vk::Format::UNDEFINED)
        else {
            return Err(format!(
                "the window cannot show Vulkan format {} (it offers {:?})",
                format.as_raw(),
                formats
                    .iter()
                    .map(|entry| entry.format.as_raw())
                    .collect::<Vec<_>>()
            ));
        };
        let mut extent = vk::Extent2D {
            width: config.drawable_width.max(1),
            height: config.drawable_height.max(1),
        };
        if caps.current_extent.width != u32::MAX {
            // X11: the window decides. The child window follows the drawable size, so a
            // mismatch is a resize the window has not reached yet.
            extent = caps.current_extent;
        }
        extent.width = extent.width.clamp(
            caps.min_image_extent.width.max(1),
            caps.max_image_extent.width.max(1),
        );
        extent.height = extent.height.clamp(
            caps.min_image_extent.height.max(1),
            caps.max_image_extent.height.max(1),
        );
        let mode = self.present_mode(self.life.handle, config.display_sync != 0);
        let images = image_count(
            config.maximum_drawable_count,
            caps.min_image_count,
            caps.max_image_count,
            mode,
        );
        let alpha = composite_alpha(caps.supported_composite_alpha)
            .ok_or("the surface offers no supported composite alpha mode")?;
        let mut usage = vk::ImageUsageFlags::COLOR_ATTACHMENT
            | vk::ImageUsageFlags::TRANSFER_SRC
            | vk::ImageUsageFlags::TRANSFER_DST;
        let mut texture_usage = TextureUsage::RENDER_TARGET;
        if config.framebuffer_only == 0 {
            usage |= vk::ImageUsageFlags::SAMPLED;
            texture_usage |= TextureUsage::SHADER_READ;
        }
        usage &= caps.supported_usage_flags;
        if !usage.contains(vk::ImageUsageFlags::COLOR_ATTACHMENT) {
            return Err("the surface does not support rendering into its swapchain images".into());
        }
        let old_handle = inner
            .chain
            .as_ref()
            .map_or(vk::SwapchainKHR::null(), |chain| chain.owner.handle);
        // A create with oldSwapchain retires it even on failure. Keep its ownership in all cases.
        if let Some(old) = inner.chain.take() {
            inner.retired.push(old);
        }
        let info = vk::SwapchainCreateInfoKHR::default()
            .surface(self.life.handle)
            .min_image_count(images)
            .image_format(format)
            .image_color_space(surface_format.color_space)
            .image_extent(extent)
            .image_array_layers(1)
            .image_usage(usage)
            .image_sharing_mode(vk::SharingMode::EXCLUSIVE)
            .pre_transform(caps.current_transform)
            .composite_alpha(alpha)
            .present_mode(mode)
            .clipped(true)
            .old_swapchain(old_handle);
        let handle = self
            .device
            .with_loader_word(|| unsafe { self.swapchain_fn.create_swapchain(&info, None) })
            .map_err(|error| {
                format!(
                    "vkCreateSwapchainKHR {}x{} format {}: {error}",
                    extent.width,
                    extent.height,
                    format.as_raw()
                )
            })?;
        let mut owner = ChainOwner {
            device: self.device.clone(),
            queue: self.present_queue.clone(),
            functions: self.swapchain_fn.clone(),
            _surface: self.life.clone(),
            handle,
            semaphores: Vec::new(),
            last_use: Mutex::new(Vec::new()),
        };
        let vk_images = unsafe { self.swapchain_fn.get_swapchain_images(handle) }
            .map_err(|error| format!("vkGetSwapchainImagesKHR: {error}"))?;
        let pixel_format =
            PixelFormat::try_from(config.pixel_format as u32).map_err(|_| "pixel format")?;
        owner.last_use = Mutex::new(vec![None; vk_images.len()]);
        for _ in &vk_images {
            let semaphore = unsafe {
                handles
                    .device
                    .create_semaphore(&vk::SemaphoreCreateInfo::default(), None)
            }
            .map_err(|error| format!("vkCreateSemaphore: {error}"))?;
            owner.semaphores.push(semaphore);
        }
        let owner = Arc::new(owner);
        let mut textures = Vec::with_capacity(vk_images.len());
        for image in &vk_images {
            let mut descriptor = TextureDescriptor::texture_2d(
                pixel_format,
                extent.width as u64,
                extent.height as u64,
                false,
            );
            descriptor.texture_type = TextureType::Type2D;
            descriptor.usage = texture_usage;
            descriptor.resource_options = ResourceOptions::private();
            descriptor.framebuffer_only = config.framebuffer_only != 0;
            descriptor.is_drawable = true;
            let image_info = vk::ImageCreateInfo::default()
                .image_type(vk::ImageType::TYPE_2D)
                .format(format)
                .extent(vk::Extent3D {
                    width: extent.width,
                    height: extent.height,
                    depth: 1,
                })
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
            let texture = unsafe {
                self.device.new_texture_with_vk_image_keep_alive(
                    &descriptor,
                    *image,
                    &image_info,
                    layouts,
                    Box::new(owner.clone()),
                )
            }
            .map_err(|error| format!("wrapping a swapchain image: {error}"))?;
            textures.push(texture);
        }
        log_once(&format!(
            "[Quadra Metal] swapchain {}x{} format {}, {} images, present mode {}",
            extent.width,
            extent.height,
            format.as_raw(),
            vk_images.len(),
            mode.as_raw()
        ));
        if let Some(statistics) = &self.statistics {
            statistics.rebuilt(mode, vk_images.len() as u64);
        }
        inner.chain = Some(Arc::new(Chain {
            textures,
            owner,
            abandoned: AtomicBool::new(false),
            statistics: self.statistics.clone(),
            made: std::time::Instant::now(),
            held: 0.into(),
            unpresented: 0.into(),
        }));
        inner.dirty = false;
        Ok(())
    }

    /// Remove unheld retired chains without holding the surface state during teardown waits.
    fn reap(&self) {
        let retired = {
            let mut inner = self.inner.lock().unwrap();
            std::mem::take(&mut inner.retired)
        };
        let mut kept = Vec::new();
        for chain in retired {
            if Arc::strong_count(&chain) > 1 {
                kept.push(chain);
            }
            // Otherwise the textures release their owner. Views and GPU work retain it too.
        }
        self.inner.lock().unwrap().retired.extend(kept);
    }

    pub fn next_drawable(self: &Arc<Self>) -> Result<Arc<Drawable>, String> {
        let _timing = crate::diagnostics::timer(&self.device, crate::diagnostics::Phase::Acquire);
        let handles = unsafe { self.device.raw() };
        if let Some(statistics) = &self.statistics {
            statistics.acquire_calls.fetch_add(1, Ordering::Relaxed);
        }
        // Only acquisitions share this fence. Present/configure never need this lock.
        let mut acquire = self.acquire.lock().unwrap();
        if acquire.pending.is_some() {
            unsafe {
                handles
                    .device
                    .wait_for_fences(&[acquire.fence], true, 2_000_000_000)
                    .map_err(|error| format!("waiting for a prior acquire fence: {error}"))?;
                handles
                    .device
                    .reset_fences(&[acquire.fence])
                    .map_err(|error| format!("vkResetFences: {error}"))?;
            }
            acquire.pending = None;
        }
        self.reap();
        for _attempt in 0..3 {
            let chain = {
                let mut inner = self.inner.lock().unwrap();
                if inner
                    .chain
                    .as_ref()
                    .is_some_and(|chain| chain.abandoned.load(Ordering::Acquire))
                {
                    inner.dirty = true;
                }
                if inner.dirty || inner.chain.is_none() {
                    if let Err(error) = self.rebuild(&mut inner) {
                        inner.failures += 1;
                        return Err(error);
                    }
                }
                inner.chain.clone().unwrap()
            };
            // With none of this chain's images held by the game or queued for the presenter,
            // nothing of ours can free one: the wait is on the compositor alone, so it is short
            // and the game gets control back (to pump its window events, among other things).
            let timeout = acquire_timeout(
                chain.held.load(Ordering::Acquire),
                chain.unpresented.load(Ordering::Acquire),
            );
            // No surface state lock while the driver waits for an image or its acquire fence.
            let result = unsafe {
                self.swapchain_fn.acquire_next_image(
                    chain.owner.handle,
                    timeout,
                    vk::Semaphore::null(),
                    acquire.fence,
                )
            };
            match result {
                Ok((index, suboptimal)) => {
                    acquire.pending = Some(chain.clone());
                    let waited = unsafe {
                        handles
                            .device
                            .wait_for_fences(&[acquire.fence], true, 2_000_000_000)
                    };
                    if let Err(error) = waited {
                        chain.abandoned.store(true, Ordering::Release);
                        return Err(format!("waiting for the acquire fence: {error}"));
                    }
                    unsafe { handles.device.reset_fences(&[acquire.fence]) }
                        .map_err(|error| format!("vkResetFences: {error}"))?;
                    acquire.pending = None;
                    if let Some(statistics) = &self.statistics {
                        statistics.acquired.fetch_add(1, Ordering::Relaxed);
                    }
                    if suboptimal {
                        self.inner.lock().unwrap().dirty = true;
                    }
                    chain.held.fetch_add(1, Ordering::AcqRel);
                    return Ok(Arc::new(Drawable {
                        surface: Arc::downgrade(self),
                        texture: chain.textures[index as usize].clone(),
                        chain,
                        index,
                        queued: false.into(),
                    }));
                }
                Err(vk::Result::ERROR_OUT_OF_DATE_KHR) => self.inner.lock().unwrap().dirty = true,
                Err(vk::Result::TIMEOUT) | Err(vk::Result::NOT_READY) => {
                    if let Some(statistics) = &self.statistics {
                        statistics.acquire_timeouts.fetch_add(1, Ordering::Relaxed);
                    }
                    self.explain_timeout(&chain, timeout);
                    return Err(format!(
                        "no drawable became free within {} ms",
                        timeout / 1_000_000
                    ));
                }
                Err(error) => return Err(format!("vkAcquireNextImageKHR: {error}")),
            }
        }
        Err("the window kept changing while acquiring a drawable".into())
    }

    /// Say once per distinct state why no image was free after a second: the images, how many the
    /// game holds, how many are queued for the presenter, and how long since the swapchain was
    /// made and since a present call last returned. A wedged presentation engine and a game that
    /// holds every image look alike from `vkAcquireNextImageKHR`, and differ here.
    fn explain_timeout(&self, chain: &Chain, timeout: u64) {
        let last = self.last_present.load(Ordering::Relaxed);
        let ago = if last == 0 {
            None
        } else {
            Some(
                self.born
                    .elapsed()
                    .saturating_sub(Duration::from_nanos(last))
                    .as_millis() as u64,
            )
        };
        log_once(&timeout_line(
            chain.textures.len(),
            chain.held.load(Ordering::Acquire),
            chain.unpresented.load(Ordering::Acquire),
            chain.made.elapsed().as_millis() as u64 / 250 * 250,
            ago.map(|ms| ms / 250 * 250),
            self.presented.load(Ordering::Relaxed),
            timeout / 1_000_000,
        ));
    }

    fn queue_present(&self, drawable: &Drawable, wait: bool) {
        let _timing = crate::diagnostics::timer(&self.device, crate::diagnostics::Phase::Present);
        let chain = &drawable.chain;
        let semaphores = [chain.owner.semaphores[drawable.index as usize]];
        let swapchains = [chain.owner.handle];
        let indices = [drawable.index];
        let mut info = vk::PresentInfoKHR::default()
            .swapchains(&swapchains)
            .image_indices(&indices);
        if wait {
            info = info.wait_semaphores(&semaphores);
        }
        let result = unsafe {
            self.present_queue
                .with_vk_queue(|queue, _| self.swapchain_fn.queue_present(queue, &info))
        };
        chain.unpresented.fetch_sub(1, Ordering::AcqRel);
        self.last_present.store(
            (self.born.elapsed().as_nanos() as u64).max(1),
            Ordering::Relaxed,
        );
        match result {
            Ok(false) => {
                if let Some(statistics) = &self.statistics {
                    statistics.presented.fetch_add(1, Ordering::Relaxed);
                }
                let count = self
                    .presented
                    .fetch_add(1, std::sync::atomic::Ordering::Relaxed)
                    + 1;
                if matches!(count, 1 | 60 | 600) {
                    log_once(&format!("[Quadra Metal] presented {count} Vulkan frames"));
                }
            }
            Ok(true) | Err(vk::Result::ERROR_OUT_OF_DATE_KHR) => {
                if let Some(statistics) = &self.statistics {
                    statistics.out_of_date.fetch_add(1, Ordering::Relaxed);
                }
                let mut inner = self.inner.lock().unwrap();
                if inner
                    .chain
                    .as_ref()
                    .is_some_and(|current| Arc::ptr_eq(current, chain))
                {
                    inner.dirty = true;
                }
            }
            Err(error) => {
                // A failed present can leave the acquisition and its signalled semaphore
                // unconsumed. Do not repeatedly acquire from that exhausted image pool.
                chain.abandoned.store(true, Ordering::Release);
                if let Some(statistics) = &self.statistics {
                    statistics.present_errors.fetch_add(1, Ordering::Relaxed);
                }
                log_once(&format!("[Quadra Metal] vkQueuePresentKHR: {error}"));
            }
        }
    }
}

impl Drop for Drawable {
    fn drop(&mut self) {
        self.chain.held.fetch_sub(1, Ordering::AcqRel);
        // Without maintenance1 an unused acquisition cannot be returned individually. Retire
        // its chain at the next acquisition; existing drawables can still finish on it.
        if !self.queued.load(Ordering::Acquire) {
            self.chain.abandoned.store(true, Ordering::Release);
            if let Some(statistics) = &self.chain.statistics {
                statistics.cancelled.fetch_add(1, Ordering::Relaxed);
            }
        }
    }
}

impl Drawable {
    pub fn texture(&self) -> &Texture {
        &self.texture
    }

    /// `presentDrawable:` of a command buffer, at its commit.
    pub fn encode_present(self: &Arc<Self>, buffer: &CommandBuffer) -> Result<(), String> {
        if self.queued.swap(true, Ordering::AcqRel) {
            return Ok(());
        }
        let result = (|| {
            let surface = self
                .surface
                .upgrade()
                .ok_or("the drawable's surface was released")?;
            let semaphore = self.chain.owner.semaphores[self.index as usize];
            unsafe { buffer.encode_signal_vk_semaphore(semaphore) }
                .map_err(|error| format!("signal: {error}"))?;
            let sender = surface
                .presenter
                .lock()
                .unwrap()
                .clone()
                .ok_or("the presenter is stopped")?;
            let drawable = self.clone();
            self.chain.unpresented.fetch_add(1, Ordering::AcqRel);
            buffer
                .add_scheduled_handler(Box::new(move |command| {
                    drawable.chain.owner.last_use.lock().unwrap()[drawable.index as usize] =
                        Some(command.clone());
                    let queued = QueuedDrawable {
                        drawable: drawable.clone(),
                        ready: crate::diagnostics::enabled().then(std::time::Instant::now),
                    };
                    if command.status() == metal2vulkan_runtime::CommandBufferStatus::Error
                        || sender.try_send(queued).is_err()
                    {
                        if let Some(statistics) = &drawable.chain.statistics {
                            statistics.queue_rejections.fetch_add(1, Ordering::Relaxed);
                        }
                        drawable.queued.store(false, Ordering::Release);
                        drawable.chain.abandoned.store(true, Ordering::Release);
                        drawable.chain.unpresented.fetch_sub(1, Ordering::AcqRel);
                    }
                }))
                .map_err(|error| format!("scheduled handler: {error}"))
        })();
        if result.is_err() {
            self.queued.store(false, Ordering::Release);
            self.chain.unpresented.fetch_sub(1, Ordering::AcqRel);
        }
        result
    }

    /// `-[CAMetalDrawable present]` outside a command buffer: after the device's queued work.
    pub fn present_now(self: &Arc<Self>) -> Result<(), String> {
        if self.queued.swap(true, std::sync::atomic::Ordering::AcqRel) {
            return Ok(());
        }
        let Some(surface) = self.surface.upgrade() else {
            return Ok(());
        };
        let buffer = surface
            .present_queue
            .command_buffer()
            .map_err(|error| format!("{error}"))?;
        self.queued
            .store(false, std::sync::atomic::Ordering::Release);
        self.encode_present(&buffer)?;
        buffer.commit().map_err(|error| format!("commit: {error}"))
    }
}

/// The longest `nextDrawable` waits for an image while the game holds none and none is queued for
/// the presenter (nanoseconds), and while it may be waiting on its own earlier frames: Metal's
/// second.
const IDLE_ACQUIRE_NANOS: u64 = 100_000_000;
const BUSY_ACQUIRE_NANOS: u64 = 1_000_000_000;

/// How long to wait for an image: briefly when nothing of ours can free one.
fn acquire_timeout(held: u32, unpresented: u32) -> u64 {
    if held == 0 && unpresented == 0 {
        IDLE_ACQUIRE_NANOS
    } else {
        BUSY_ACQUIRE_NANOS
    }
}

/// The line `Surface::explain_timeout` logs: times rounded to a quarter second, so that a state
/// that repeats logs once.
fn timeout_line(
    images: usize,
    held: u32,
    unpresented: u32,
    chain_age_ms: u64,
    since_present_ms: Option<u64>,
    presented: u64,
    waited_ms: u64,
) -> String {
    let since = since_present_ms.map_or("never".to_owned(), |ms| format!("{ms} ms ago"));
    format!(
        "[Quadra Metal] nextDrawable timed out after {waited_ms} ms: {images} images, {held} held by the game, {unpresented} queued for the presenter, swapchain {chain_age_ms} ms old, last present returned {since}, {presented} presented so far"
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_timeout_line_states_who_holds_the_images() {
        let line = timeout_line(3, 2, 1, 1250, Some(1000), 703, 1000);
        assert!(line.contains(
            "timed out after 1000 ms: 3 images, 2 held by the game, 1 queued for the presenter"
        ));
        assert!(line.contains("swapchain 1250 ms old"));
        assert!(line.contains("last present returned 1000 ms ago"));
        assert!(timeout_line(3, 0, 0, 0, None, 0, 100).contains("returned never"));
    }

    #[test]
    fn only_a_wait_on_the_compositor_alone_is_short() {
        assert_eq!(acquire_timeout(0, 0), IDLE_ACQUIRE_NANOS);
        for (held, queued) in [(1, 0), (0, 1), (3, 2)] {
            assert_eq!(acquire_timeout(held, queued), BUSY_ACQUIRE_NANOS);
        }
        assert!(IDLE_ACQUIRE_NANOS < BUSY_ACQUIRE_NANOS);
    }

    #[test]
    fn display_sync_keeps_vblank_without_requiring_a_fifo_backlog() {
        let modes = [
            vk::PresentModeKHR::IMMEDIATE,
            vk::PresentModeKHR::FIFO,
            vk::PresentModeKHR::MAILBOX,
        ];
        assert!(select_present_mode(&modes, true, None) == vk::PresentModeKHR::MAILBOX);
        assert!(select_present_mode(&modes, false, None) == vk::PresentModeKHR::IMMEDIATE);
        assert!(select_present_mode(&modes, true, Some("fifo")) == vk::PresentModeKHR::FIFO);
        assert!(
            select_present_mode(&modes, true, Some("immediate")) == vk::PresentModeKHR::IMMEDIATE
        );
        // A driver without mailbox must retain a tear-free fallback when sync is enabled.
        let limited = [vk::PresentModeKHR::IMMEDIATE, vk::PresentModeKHR::FIFO];
        assert!(select_present_mode(&limited, true, None) == vk::PresentModeKHR::FIFO);
        assert!(select_present_mode(&limited, false, Some("mailbox")) == vk::PresentModeKHR::FIFO);
    }

    #[test]
    fn mailbox_provisions_the_drivers_minimum_plus_one_when_possible() {
        for minimum in 1..8 {
            for maximum in [0, minimum, minimum + 1, minimum + 4] {
                for requested in [0, 2, 3, 10] {
                    let actual =
                        image_count(requested, minimum, maximum, vk::PresentModeKHR::MAILBOX);
                    assert!(actual >= minimum);
                    assert!(maximum == 0 || actual <= maximum);
                    if maximum == 0 || maximum > minimum {
                        assert!(actual > minimum);
                    }
                }
            }
        }
        assert_eq!(image_count(2, 3, 0, vk::PresentModeKHR::MAILBOX), 4);
        assert_eq!(image_count(2, 3, 0, vk::PresentModeKHR::FIFO), 3);
    }

    #[test]
    fn composite_alpha_never_requests_an_unadvertised_mode() {
        for bits in 1..16 {
            let supported = vk::CompositeAlphaFlagsKHR::from_raw(bits);
            let selected = composite_alpha(supported).unwrap();
            assert!(supported.contains(selected));
            assert_eq!(selected.as_raw().count_ones(), 1);
        }
        assert!(composite_alpha(vk::CompositeAlphaFlagsKHR::empty()).is_none());
    }
}

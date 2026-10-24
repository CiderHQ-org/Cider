//! The device's identity in the launch log: which GPU and driver the game runs on, and whether
//! the runtime has measured that exact combination. A bug report from an unqualified GPU needs
//! these facts to be useful.
use crate::util::log_once;
use ash::vk;
use metal2vulkan_runtime::{Device, DeviceKind, Error};
use serde::Serialize;

/// The id of the runtime's informational message about an unmeasured driver.
const UNMEASURED_DRIVER: &str = "metal2vulkan-unmeasured-driver";

/// Whether a runtime message that is neither a degrade notice, a warning nor an error still
/// belongs in the launch log: the one that says which paths an unmeasured driver takes.
pub fn forwarded_info(id_name: &str) -> bool {
    id_name == UNMEASURED_DRIVER
}

/// One memory heap of the device.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub struct Heap {
    pub size: u64,
    pub device_local: bool,
}

/// What the identity line states.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Identity {
    pub name: String,
    pub vendor_id: u32,
    pub device_id: u32,
    pub kind: &'static str,
    pub driver_name: String,
    pub driver_info: String,
    pub driver_id: String,
    pub driver_version: u32,
    pub api_version: String,
    pub measured: bool,
    pub defects: Vec<String>,
    pub heaps: Vec<Heap>,
    /// The optional device extensions the device took.
    pub extensions: Vec<&'static str>,
}

/// The optional device extensions whose use the log states.
const REPORTED: [&str; 4] = [
    "VK_EXT_memory_priority",
    "VK_EXT_pageable_device_local_memory",
    "VK_KHR_swapchain_maintenance1",
    "VK_EXT_swapchain_maintenance1",
];

fn kind_name(kind: DeviceKind) -> &'static str {
    match kind {
        DeviceKind::Discrete => "discrete",
        DeviceKind::Integrated => "integrated",
        DeviceKind::Virtual => "virtual",
        DeviceKind::Cpu => "cpu",
        _ => "other",
    }
}

fn mib(bytes: u64) -> u64 {
    bytes >> 20
}

/// The identity as one JSON object, for a hardware report.
pub fn json(identity: &Identity) -> String {
    serde_json::to_string(identity).unwrap_or_else(|_| "{}".to_owned())
}

/// The single line a bug report quotes. Stable field names, no paths or account data.
pub fn describe(identity: &Identity) -> String {
    let heaps = identity
        .heaps
        .iter()
        .map(|heap| {
            format!(
                "{}MiB{}",
                mib(heap.size),
                if heap.device_local { "(local)" } else { "" }
            )
        })
        .collect::<Vec<_>>()
        .join(",");
    let defects = if identity.defects.is_empty() {
        "none".to_owned()
    } else {
        identity.defects.join(",")
    };
    format!(
        "[Quadra Metal] gpu: {} | vendor {:#06x} device {:#06x} {} | driver {} {} (id {}, version {:#x}) | Vulkan {} | measured {} | driver workarounds {} | heaps {} | extensions {}",
        identity.name,
        identity.vendor_id,
        identity.device_id,
        identity.kind,
        identity.driver_name,
        identity.driver_info,
        identity.driver_id,
        identity.driver_version,
        identity.api_version,
        if identity.measured { "yes" } else { "no" },
        defects,
        heaps,
        if identity.extensions.is_empty() {
            "none".to_owned()
        } else {
            identity.extensions.join(",")
        },
    )
}

fn text(chars: &[std::ffi::c_char]) -> String {
    // SAFETY: Vulkan returns NUL-terminated names in fixed arrays; the slice is that array.
    let bytes: Vec<u8> = chars
        .iter()
        .take_while(|&&c| c != 0)
        .map(|&c| c as u8)
        .collect();
    String::from_utf8_lossy(&bytes).into_owned()
}

/// Read the identity of `device`.
pub fn of(device: &Device) -> Identity {
    let properties = device.properties();
    // SAFETY: the handles stay valid for the borrow of `device`; only properties are queried.
    let raw = unsafe { device.raw() };
    let mut driver = vk::PhysicalDeviceDriverProperties::default();
    let mut query = vk::PhysicalDeviceProperties2::default().push_next(&mut driver);
    // SAFETY: `physical_device` belongs to `instance`; the driver properties are core in 1.2.
    unsafe {
        raw.instance
            .get_physical_device_properties2(raw.physical_device, &mut query)
    };
    let device_api = query.properties.api_version;
    // SAFETY: as above.
    let memory = unsafe {
        raw.instance
            .get_physical_device_memory_properties(raw.physical_device)
    };
    let heaps = memory.memory_heaps[..memory.memory_heap_count as usize]
        .iter()
        .map(|heap| Heap {
            size: heap.size,
            device_local: heap.flags.contains(vk::MemoryHeapFlags::DEVICE_LOCAL),
        })
        .collect();
    let description = &properties.description;
    Identity {
        name: properties.name.clone(),
        vendor_id: properties.vendor_id,
        device_id: properties.device_id,
        kind: kind_name(properties.kind),
        driver_name: text(&driver.driver_name),
        driver_info: text(&driver.driver_info),
        driver_id: description
            .driver_id
            .map_or_else(|| "unknown".to_owned(), |id| format!("{id:?}")),
        driver_version: description.driver_version,
        api_version: format!(
            "{}.{}.{} (runtime uses {}.{})",
            vk::api_version_major(device_api),
            vk::api_version_minor(device_api),
            vk::api_version_patch(device_api),
            properties.api_version.major,
            properties.api_version.minor,
        ),
        measured: description.measured_identity(),
        defects: properties
            .driver_defects
            .iter()
            .map(|defect| format!("{defect:?}"))
            .collect(),
        heaps,
        extensions: REPORTED
            .iter()
            .copied()
            .filter(|name| {
                let name = std::ffi::CString::new(*name).unwrap_or_default();
                device.extension_enabled(&name)
            })
            .collect(),
    }
}

/// What to tell someone whose game found no usable Vulkan device: the cause the runtime reports,
/// in the words of the fix. The loader lists no surface extension when no driver is installed, so
/// that refusal is the missing driver, not a bridge problem.
pub fn explain_no_device(error: &Error) -> String {
    const DRIVERS: &str = "Install the Vulkan driver for your GPU: NVIDIA's proprietary driver (nvidia-utils), \
        or Mesa's for AMD (vulkan-radeon, mesa-vulkan-drivers) or Intel (vulkan-intel, mesa-vulkan-drivers).";
    match error {
        Error::NoDevice => format!("the Vulkan loader found no graphics device. {DRIVERS}"),
        Error::InstanceExtensionRequired(missing) if missing.instance_extension == "VK_KHR_surface" => {
            format!("the Vulkan loader found no graphics driver. {DRIVERS}")
        }
        Error::LoaderNotFound(_) => format!(
            "the Vulkan loader (libvulkan.so.1) is not installed ({error}). Install vulkan-icd-loader, libvulkan1 or vulkan-loader."
        ),
        other => other.to_string(),
    }
}

/// Log the identity line once, and the runtime's own account of an unmeasured identity.
pub fn log(device: &Device) {
    let identity = of(device);
    log_once(&describe(&identity));
    if !identity.measured {
        log_once(
            "[Quadra Metal] this GPU and driver release are not among the combinations the runtime has measured; it takes exact paths and assumes the driver's known defects. Include the gpu line above when reporting a problem.",
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample() -> Identity {
        Identity {
            name: "Test GPU".into(),
            vendor_id: 0x10de,
            device_id: 0x2489,
            kind: "discrete",
            driver_name: "NVIDIA".into(),
            driver_info: "615.78.08".into(),
            driver_id: "NVIDIA_PROPRIETARY".into(),
            driver_version: 0x9a1e_0000,
            api_version: "1.4.351".into(),
            measured: false,
            defects: vec!["MultisampledStencilColourCopies".into()],
            heaps: vec![
                Heap {
                    size: 8 << 30,
                    device_local: true,
                },
                Heap {
                    size: 24 << 30,
                    device_local: false,
                },
            ],
            extensions: vec!["VK_EXT_memory_priority"],
        }
    }

    #[test]
    fn the_line_names_the_driver_release_and_measurement() {
        let line = describe(&sample());
        for expected in [
            "gpu: Test GPU",
            "vendor 0x10de device 0x2489 discrete",
            "driver NVIDIA 615.78.08",
            "id NVIDIA_PROPRIETARY",
            "Vulkan 1.4.351",
            "measured no",
            "MultisampledStencilColourCopies",
            "8192MiB(local),24576MiB",
            "extensions VK_EXT_memory_priority",
        ] {
            assert!(line.contains(expected), "{expected:?} missing from {line}");
        }
        assert!(!line.contains('\n'));
    }

    #[test]
    fn a_clean_measured_device_says_so() {
        let mut identity = sample();
        identity.measured = true;
        identity.defects.clear();
        let line = describe(&identity);
        assert!(line.contains("measured yes"));
        assert!(line.contains("driver workarounds none"));
        identity.extensions.clear();
        assert!(describe(&identity).ends_with("extensions none"));
    }

    #[test]
    fn the_json_carries_the_fields_a_report_needs() {
        let parsed: serde_json::Value = serde_json::from_str(&json(&sample())).unwrap();
        assert_eq!(parsed["name"], "Test GPU");
        assert_eq!(parsed["device_id"], 0x2489);
        assert_eq!(parsed["driver_info"], "615.78.08");
        assert_eq!(parsed["measured"], false);
        assert_eq!(parsed["defects"][0], "MultisampledStencilColourCopies");
        assert_eq!(parsed["heaps"][0]["size"], 8u64 << 30);
        assert_eq!(parsed["extensions"][0], "VK_EXT_memory_priority");
    }

    #[test]
    fn only_the_unmeasured_driver_message_is_forwarded() {
        assert!(forwarded_info("metal2vulkan-unmeasured-driver"));
        assert!(!forwarded_info("metal2vulkan-pipeline-log"));
        assert!(!forwarded_info(""));
    }

    #[test]
    fn a_missing_device_is_explained_with_its_remedy() {
        let text = explain_no_device(&Error::NoDevice);
        assert!(text.contains("no graphics device"), "{text}");
        assert!(
            text.contains("nvidia-utils") && text.contains("vulkan-radeon"),
            "{text}"
        );
        assert_eq!(
            explain_no_device(&Error::DeviceLost),
            Error::DeviceLost.to_string()
        );
    }

    #[test]
    fn names_stop_at_the_terminator() {
        let mut raw = [0 as std::ffi::c_char; 8];
        for (slot, byte) in raw.iter_mut().zip(b"abc") {
            *slot = *byte as std::ffi::c_char;
        }
        raw[4] = b'z' as std::ffi::c_char;
        assert_eq!(text(&raw), "abc");
    }
}

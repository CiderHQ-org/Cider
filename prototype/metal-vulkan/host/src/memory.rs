//! Graphics budgets for the device actually selected by Vulkan. An APU's
//! framebuffer reservation is not memory independent of the host: Roblox,
//! its uploads, the compositor and the driver all compete for the same RAM.
use ash::vk;
use metal2vulkan_runtime::Device;

const MIB: u64 = 1 << 20;
const MINIMUM: u64 = 64 * MIB;
const FALLBACK: u64 = 512 * MIB;

fn launcher_budget(value: Option<&str>) -> u64 {
    value
        .filter(|value| !value.is_empty() && value.bytes().all(|byte| byte.is_ascii_digit()))
        .and_then(|value| value.parse::<u64>().ok())
        .filter(|value| *value >= MINIMUM)
        .unwrap_or(FALLBACK)
}

fn heap_budget(
    memory: &vk::PhysicalDeviceMemoryProperties,
    budget: Option<&vk::PhysicalDeviceMemoryBudgetPropertiesEXT<'_>>,
) -> u64 {
    memory
        .memory_heaps_as_slice()
        .iter()
        .enumerate()
        .filter(|(_, heap)| heap.flags.contains(vk::MemoryHeapFlags::DEVICE_LOCAL))
        .map(|(index, heap)| {
            let (total, used) = match budget {
                Some(budget)
                    if budget.heap_budget[index] > 0 && budget.heap_budget[index] <= heap.size =>
                {
                    (budget.heap_budget[index], budget.heap_usage[index])
                }
                _ => (heap.size, 0),
            };
            let reserve = (256 * MIB).min(total / 4);
            // Leave room for swapchain images, staging and driver allocations
            // that are outside Roblox's own texture/geometry budget.
            (total / 4 * 3).min(total.saturating_sub(used).saturating_sub(reserve))
        })
        .max()
        .unwrap_or(FALLBACK)
        .max(MINIMUM)
}

fn shared_budget(meminfo: &str) -> Option<u64> {
    let read = |key| {
        meminfo.lines().find_map(|line| {
            let mut fields = line.split_whitespace();
            if fields.next()? != key {
                return None;
            }
            let value = fields.next()?.parse::<u64>().ok()?;
            if fields.next()? != "kB" || fields.next().is_some() {
                return None;
            }
            value.checked_mul(1024)
        })
    };
    let total = read("MemTotal:")?;
    let available = read("MemAvailable:")?;
    if total == 0 || available > total {
        return None;
    }
    // Leave the bulk of system RAM for the game and desktop. In particular,
    // a 6 GiB Renoir system must not promise a separate 1.5 GiB graphics pool.
    Some((total / 8).min(available / 4).max(MINIMUM))
}

fn working_set(hint: Option<&str>, heap: u64, unified: bool, meminfo: &str) -> u64 {
    let mut bytes = launcher_budget(hint).min(heap);
    if unified {
        bytes = bytes.min(shared_budget(meminfo).unwrap_or(FALLBACK));
    }
    bytes
}

pub fn recommended_working_set(device: &Device) -> u64 {
    // Read this physical device, not the largest GPU visible to the launcher.
    // The memory-budget extension is optional and needs no enabled feature
    // for its physical-device query.
    let heap = unsafe {
        let raw = device.raw();
        let supports_budget = raw
            .instance
            .enumerate_device_extension_properties(raw.physical_device)
            .unwrap_or_default()
            .iter()
            .any(|extension| {
                extension.extension_name_as_c_str().ok() == Some(ash::ext::memory_budget::NAME)
            });
        let mut budget = vk::PhysicalDeviceMemoryBudgetPropertiesEXT::default();
        let mut properties = vk::PhysicalDeviceMemoryProperties2::default();
        if supports_budget {
            properties = properties.push_next(&mut budget);
        }
        raw.instance
            .get_physical_device_memory_properties2(raw.physical_device, &mut properties);
        heap_budget(
            &properties.memory_properties,
            supports_budget.then_some(&budget),
        )
    };
    let hint = std::env::var("MACOBLOX_VRAM_BYTES").ok();
    let unified = device.properties().has_unified_memory;
    let meminfo = if unified {
        std::fs::read_to_string("/proc/meminfo").unwrap_or_default()
    } else {
        String::new()
    };
    let bytes = working_set(hint.as_deref(), heap, unified, &meminfo);
    crate::util::log_once(&format!(
        "[Quadra Metal] graphics memory budget: {} MiB (unified memory {})",
        bytes / MIB,
        unified
    ));
    bytes
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn renoir_budget_reserves_ram_for_the_game_and_desktop() {
        let meminfo = "MemTotal: 6291456 kB\nMemAvailable: 2097152 kB\n";
        assert_eq!(
            working_set(Some("1490595840"), 1536 * MIB, true, meminfo),
            512 * MIB
        );
        let pressure = "MemTotal: 6291456 kB\nMemAvailable: 524288 kB\n";
        assert_eq!(
            working_set(Some("1490595840"), 1536 * MIB, true, pressure),
            128 * MIB
        );
        assert_eq!(
            working_set(Some("134217728"), 1536 * MIB, true, meminfo),
            128 * MIB
        );
    }

    #[test]
    fn discrete_gpu_uses_its_own_heap_and_launch_limit() {
        let mut memory = vk::PhysicalDeviceMemoryProperties::default();
        memory.memory_heap_count = 2;
        memory.memory_heaps[0] = vk::MemoryHeap {
            size: 8 << 30,
            flags: vk::MemoryHeapFlags::DEVICE_LOCAL,
        };
        memory.memory_heaps[1].size = 32 << 30; // host heap is not VRAM
        let mut budget = vk::PhysicalDeviceMemoryBudgetPropertiesEXT::default();
        budget.heap_budget[0] = 3 << 30;
        budget.heap_usage[0] = 1 << 30;
        let heap = heap_budget(&memory, Some(&budget));
        assert_eq!(heap, 1792 * MIB);
        assert_eq!(working_set(Some("4294967296"), heap, false, ""), heap);
        assert_eq!(working_set(Some("1073741824"), heap, false, ""), 1 << 30);
        assert_eq!(heap_budget(&memory, None), 6 << 30);
    }

    #[test]
    fn unknown_and_malformed_reports_cannot_claim_four_gibibytes() {
        for hint in [
            None,
            Some(""),
            Some("-1"),
            Some("+4294967296"),
            Some("0"),
            Some("NaN"),
            Some("18446744073709551616"),
        ] {
            assert_eq!(working_set(hint, 8 << 30, false, ""), FALLBACK);
        }
        for info in [
            "",
            "MemTotal: 6291456 kB\n",
            "MemTotal: -1 kB\nMemAvailable: 4 kB\n",
            "MemTotal: 4 kB\nMemAvailable: 8 kB\n",
            "MemTotal: 18446744073709551615 kB\nMemAvailable: 4 kB\n",
        ] {
            assert_eq!(
                working_set(Some("4294967296"), 8 << 30, true, info),
                FALLBACK
            );
        }
        let mut memory = vk::PhysicalDeviceMemoryProperties::default();
        memory.memory_heap_count = 1;
        memory.memory_heaps[0] = vk::MemoryHeap {
            size: 2 << 30,
            flags: vk::MemoryHeapFlags::DEVICE_LOCAL,
        };
        let mut budget = vk::PhysicalDeviceMemoryBudgetPropertiesEXT::default();
        budget.heap_budget[0] = 1 << 30;
        budget.heap_usage[0] = 2 << 30;
        assert_eq!(heap_budget(&memory, Some(&budget)), MINIMUM);
    }
}

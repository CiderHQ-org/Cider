//! Operational compilation limits based on CPU and host/cgroup memory.
use std::num::NonZeroUsize;
use std::path::Path;
use std::sync::Once;

const COMPILE_BYTES: u64 = 512 << 20;

pub fn turns(threads: usize, available: Option<u64>) -> usize {
    let cpu = if threads >= 16 {
        12
    } else {
        (threads / 2).clamp(1, 12)
    };
    available.map_or(cpu, |bytes| {
        let reserve = (512 << 20).max(bytes / 4);
        let memory = bytes.saturating_sub(reserve) / COMPILE_BYTES;
        cpu.min(memory.max(1) as usize)
    })
}

fn cgroup_available(root: &Path, group: &Path) -> Option<u64> {
    let mut group = group.to_path_buf();
    let mut available = None;
    loop {
        let directory = root.join(&group);
        for limit in ["memory.max", "memory.high"] {
            let maximum = std::fs::read_to_string(directory.join(limit))
                .ok()
                .and_then(|v| v.trim().parse::<u64>().ok());
            let current = std::fs::read_to_string(directory.join("memory.current"))
                .ok()
                .and_then(|v| v.trim().parse::<u64>().ok());
            if let (Some(maximum), Some(current)) = (maximum, current) {
                let free = maximum.saturating_sub(current);
                available = Some(available.map_or(free, |old: u64| old.min(free)));
            }
        }
        if !group.pop() {
            break;
        }
    }
    available
}

pub fn available_memory() -> Option<u64> {
    let host = std::fs::read_to_string("/proc/meminfo")
        .ok()
        .and_then(|text| {
            text.lines().find_map(|line| {
                let value = line
                    .strip_prefix("MemAvailable:")?
                    .split_whitespace()
                    .next()?
                    .parse::<u64>()
                    .ok()?;
                value.checked_mul(1024)
            })
        });
    let group = std::fs::read_to_string("/proc/self/cgroup")
        .ok()
        .and_then(|text| {
            text.lines()
                .find_map(|line| line.strip_prefix("0::/").map(std::path::PathBuf::from))
        });
    let group = group.and_then(|group| cgroup_available(Path::new("/sys/fs/cgroup"), &group));
    match (host, group) {
        (Some(a), Some(b)) => Some(a.min(b)),
        (a, b) => a.or(b),
    }
}

pub fn configure() {
    static ONCE: Once = Once::new();
    ONCE.call_once(|| {
        let threads = std::thread::available_parallelism().map_or(1, NonZeroUsize::get);
        let available = available_memory();
        let count = turns(threads, available);
        if metal2vulkan_runtime::set_pipeline_compile_budget(NonZeroUsize::new(count).unwrap()) {
            crate::util::log_once(&format!("[Quadra Metal] pipeline compilation cap: {count}, available host/cgroup memory: {} MiB", available.unwrap_or(0) >> 20));
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn compile_turns_follow_both_cpu_and_memory_pressure() {
        assert_eq!(turns(1, Some(64 << 30)), 1);
        assert_eq!(turns(32, Some(0)), 1);
        assert_eq!(turns(32, Some(2 << 30)), 3);
        assert_eq!(turns(32, Some(16 << 30)), 12);
        assert_eq!(turns(4, None), 2);
    }

    #[test]
    fn cgroup_parent_limits_are_not_ignored() {
        let root = std::env::temp_dir().join(format!("quadra-cgroup-test-{}", std::process::id()));
        std::fs::create_dir_all(root.join("child")).unwrap();
        for (name, value) in [
            ("memory.max", "1000"),
            ("memory.current", "900"),
            ("child/memory.max", "max"),
            ("child/memory.current", "10"),
        ] {
            std::fs::write(root.join(name), value).unwrap();
        }
        assert_eq!(cgroup_available(&root, Path::new("child")), Some(100));
        std::fs::remove_dir_all(root).unwrap();
    }
}

//! The user's Quadra M2VK settings, as the launcher passes them in the environment.
//!
//! Every value has a safe default for an unset, empty or unrecognized variable: a typo in a
//! setting never changes how a game runs.
use metal2vulkan::device::{BlockDecodePolicy, DevicePolicy};

/// How closely the translation follows Metal where the device differs from it
/// (`MACOBLOX_METAL_ACCURACY`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Accuracy {
    /// The runtime's defaults: the device's own maths, sampling and block decoders.
    Fast,
    /// The defaults, but BC1 to BC5 textures keep Metal's decode in a twin where the device's
    /// decoder is not measured to match it.
    Textures,
    /// Every exact form the runtime has (`DevicePolicy::exact_answers`): slower to translate and
    /// to run.
    Exact,
}

/// The settings (`MACOBLOX_METAL_*`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Tuning {
    pub accuracy: Accuracy,
    /// Memory priorities and pageable device-local memory (`MACOBLOX_METAL_MEMORY_PRIORITY`).
    pub memory_priority: bool,
    /// Pipeline compilations at once, where the user fixed it (`MACOBLOX_METAL_COMPILE_THREADS`).
    pub compile_threads: Option<usize>,
    /// The most learned pipeline states kept warm (`MACOBLOX_METAL_WARM_STATES`).
    pub warm_states: usize,
}

/// Where the warm-state ceiling starts, and the most a setting may raise it to.
pub const DEFAULT_WARM_STATES: usize = 256;
pub const MAX_WARM_STATES: usize = 1024;
/// The most compilations a setting may allow at once.
pub const MAX_COMPILE_THREADS: usize = 32;

impl Default for Tuning {
    fn default() -> Tuning {
        Tuning {
            accuracy: Accuracy::Fast,
            memory_priority: true,
            compile_threads: None,
            warm_states: DEFAULT_WARM_STATES,
        }
    }
}

impl Tuning {
    /// The settings of this process's environment.
    pub fn from_env() -> Tuning {
        Tuning::parse(|name| std::env::var(name).ok())
    }

    pub fn parse(get: impl Fn(&str) -> Option<String>) -> Tuning {
        let text = |name: &str| get(name).map(|value| value.trim().to_ascii_lowercase());
        let number = |name: &str| text(name).and_then(|value| value.parse::<usize>().ok());
        let default = Tuning::default();
        Tuning {
            accuracy: match text("MACOBLOX_METAL_ACCURACY").as_deref() {
                Some("textures") => Accuracy::Textures,
                Some("exact") => Accuracy::Exact,
                _ => default.accuracy,
            },
            memory_priority: match text("MACOBLOX_METAL_MEMORY_PRIORITY").as_deref() {
                Some("0" | "off" | "false" | "no") => false,
                _ => default.memory_priority,
            },
            compile_threads: number("MACOBLOX_METAL_COMPILE_THREADS")
                .filter(|&count| count > 0)
                .map(|count| count.min(MAX_COMPILE_THREADS)),
            warm_states: number("MACOBLOX_METAL_WARM_STATES")
                .map_or(default.warm_states, |count| count.min(MAX_WARM_STATES)),
        }
    }

    /// The translation policy the accuracy asks for.
    pub fn policy(&self) -> DevicePolicy {
        match self.accuracy {
            Accuracy::Fast => DevicePolicy::default(),
            Accuracy::Textures => {
                let mut policy = DevicePolicy::default();
                policy.block_decode = BlockDecodePolicy::Exact;
                policy
            }
            Accuracy::Exact => DevicePolicy::default().exact_answers(),
        }
    }

    /// One line stating what is not the default, for the launch log.
    pub fn describe(&self) -> String {
        let mut changed = Vec::new();
        if self.accuracy != Accuracy::Fast {
            changed.push(format!("accuracy {:?}", self.accuracy).to_ascii_lowercase());
        }
        if !self.memory_priority {
            changed.push("memory priority off".to_owned());
        }
        if let Some(count) = self.compile_threads {
            changed.push(format!("{count} compile threads"));
        }
        if self.warm_states != DEFAULT_WARM_STATES {
            changed.push(format!("up to {} warm states", self.warm_states));
        }
        if changed.is_empty() {
            "[Quadra Metal] settings: defaults".to_owned()
        } else {
            format!("[Quadra Metal] settings: {}", changed.join(", "))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn tuning(pairs: &[(&str, &str)]) -> Tuning {
        let map: HashMap<String, String> = pairs
            .iter()
            .map(|(name, value)| (name.to_string(), value.to_string()))
            .collect();
        Tuning::parse(|name| map.get(name).cloned())
    }

    #[test]
    fn an_empty_environment_is_the_defaults() {
        assert_eq!(tuning(&[]), Tuning::default());
        assert_eq!(tuning(&[]).describe(), "[Quadra Metal] settings: defaults");
        assert_eq!(tuning(&[]).policy(), DevicePolicy::default());
    }

    #[test]
    fn each_setting_is_read_and_a_typo_changes_nothing() {
        let set = tuning(&[
            ("MACOBLOX_METAL_ACCURACY", " Exact "),
            ("MACOBLOX_METAL_MEMORY_PRIORITY", "0"),
            ("MACOBLOX_METAL_COMPILE_THREADS", "4"),
            ("MACOBLOX_METAL_WARM_STATES", "512"),
        ]);
        assert_eq!(set.accuracy, Accuracy::Exact);
        assert!(!set.memory_priority);
        assert_eq!(set.compile_threads, Some(4));
        assert_eq!(set.warm_states, 512);
        assert_eq!(
            set.describe(),
            "[Quadra Metal] settings: accuracy exact, memory priority off, 4 compile threads, up to 512 warm states"
        );
        let typos = tuning(&[
            ("MACOBLOX_METAL_ACCURACY", "excat"),
            ("MACOBLOX_METAL_MEMORY_PRIORITY", "maybe"),
            ("MACOBLOX_METAL_COMPILE_THREADS", "many"),
            ("MACOBLOX_METAL_WARM_STATES", "-1"),
        ]);
        assert_eq!(typos, Tuning::default());
    }

    #[test]
    fn counts_are_bounded() {
        assert_eq!(
            tuning(&[("MACOBLOX_METAL_COMPILE_THREADS", "0")]).compile_threads,
            None,
            "0 is automatic"
        );
        assert_eq!(
            tuning(&[("MACOBLOX_METAL_COMPILE_THREADS", "999")]).compile_threads,
            Some(MAX_COMPILE_THREADS)
        );
        assert_eq!(
            tuning(&[("MACOBLOX_METAL_WARM_STATES", "100000")]).warm_states,
            MAX_WARM_STATES
        );
        assert_eq!(
            tuning(&[("MACOBLOX_METAL_WARM_STATES", "0")]).warm_states,
            0
        );
    }

    #[test]
    fn accuracy_selects_the_policy() {
        let textures = tuning(&[("MACOBLOX_METAL_ACCURACY", "textures")]).policy();
        assert_eq!(textures.block_decode, BlockDecodePolicy::Exact);
        let mut expected = DevicePolicy::default();
        expected.block_decode = BlockDecodePolicy::Exact;
        assert_eq!(
            textures, expected,
            "only the block decode differs from the defaults"
        );
        assert_eq!(
            tuning(&[("MACOBLOX_METAL_ACCURACY", "exact")]).policy(),
            DevicePolicy::default().exact_answers()
        );
    }
}

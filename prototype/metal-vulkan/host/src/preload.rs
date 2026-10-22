//! Learn pipeline descriptions during play and replay their creations before a later launch.
//! These are local cache records, never a shader pack or a promise to predict every draw variant.
use crate::{cache, Obj, QmRenderPipelineDesc};
use metal2vulkan::library::FunctionConstantValues;
use metal2vulkan_runtime::{
    ComputePipelineState, Device, Function, PipelineOptions, RenderPipelineState,
};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashSet};
use std::ffi::c_void;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, OnceLock};

const CAPACITY: u64 = 512 << 20;
const MAX_RECORDS: usize = 4096;
const MAX_RECIPE: u64 = 64 << 10;
const MAX_RESIDENT: usize = 256;
const UNKNOWN_MEMORY_RESIDENT: usize = 64;
// Driver allocations are not exposed by the runtime allocator. This estimate bounds the
// count rather than promising an exact byte cap; also recheck actual pressure between calls.
const ESTIMATED_STATE_BYTES: u64 = 8 << 20;
const MEMORY_RESERVE: u64 = 768 << 20;
const RESIDENT_SOURCE_BYTES: u64 = 128 << 20;
pub static RECORDED: AtomicU64 = AtomicU64::new(0);
pub static WARMED: AtomicU64 = AtomicU64::new(0);
pub static FAILED: AtomicU64 = AtomicU64::new(0);

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Source {
    library: String,
    name: String,
    constants: FunctionConstantValues,
}

#[derive(Serialize, Deserialize)]
#[serde(tag = "kind", deny_unknown_fields)]
enum Recipe {
    Render {
        vertex: Source,
        fragment: Option<Source>,
        state: Box<QmRenderPipelineDesc>,
    },
    Compute {
        function: Source,
    },
}

enum ReadyPipeline {
    Render(RenderPipelineState),
    Compute(ComputePipelineState),
}
impl ReadyPipeline {
    fn release(self) {
        match self {
            Self::Render(state) => drop(state),
            Self::Compute(state) => drop(state),
        }
    }
}

/// Strong holds until the live game creates the matching state, so its runtime can reuse the
/// variant's Vulkan objects. Owned by the C device handle, never by the runtime device itself.
#[derive(Default)]
pub struct WarmStates {
    states: BTreeMap<[u8; 32], ReadyPipeline>,
    limit: usize,
}
impl WarmStates {
    pub fn len(&self) -> usize {
        self.states.len()
    }
    pub fn limit(&self) -> usize {
        self.limit
    }
    pub fn forget_render(&mut self, desc: &QmRenderPipelineDesc) {
        if let Ok(recipe) = render_recipe(desc) {
            self.forget(&recipe);
        }
    }
    pub fn forget_compute(&mut self, function: &Function) {
        self.forget(&Recipe::Compute {
            function: source_description(function),
        });
    }
    fn forget(&mut self, recipe: &Recipe) {
        if let Ok(bytes) = serde_json::to_vec(recipe) {
            if let Some(state) = self.states.remove(&cache::hash(&bytes)) {
                state.release();
            }
        }
    }
}

fn source_description(function: &Function) -> Source {
    let descriptor = function.function_descriptor();
    Source {
        library: cache::hex(descriptor.function.library().content_hash()),
        name: function.name().to_owned(),
        constants: descriptor.constants,
    }
}

fn render_recipe(desc: &QmRenderPipelineDesc) -> Result<Recipe, String> {
    let vertex = source_description(function(desc.vertex_function)?);
    let fragment = if desc.fragment_function.is_null() {
        None
    } else {
        Some(source_description(function(desc.fragment_function)?))
    };
    let mut state = Box::new(desc.clone());
    state.vertex_function = std::ptr::null_mut();
    state.fragment_function = std::ptr::null_mut();
    state.label = std::ptr::null();
    state.pad = 0;
    state.pad2 = 0;
    Ok(Recipe::Render {
        vertex,
        fragment,
        state,
    })
}

struct Recorder {
    root: PathBuf,
    scope: String,
    state: Mutex<State>,
}

struct State {
    seen: HashSet<String>,
    bytes: u64,
    records: usize,
}

pub fn scope() -> String {
    cache::hex(&cache::hash(
        std::env::var("MACOBLOX_METAL_PRELOAD_KEY")
            .unwrap_or_else(|_| "unscoped".into())
            .as_bytes(),
    ))
}

pub fn root() -> Option<PathBuf> {
    if std::env::var("MACOBLOX_METAL_PRELOAD").as_deref() == Ok("0") {
        return None;
    }
    std::env::var_os("MACOBLOX_METAL_SHADER_CACHE")
        .map(|root| PathBuf::from(root).join("quadra-preload-v1"))
}

fn recorder() -> Option<&'static Recorder> {
    static RECORDER: OnceLock<Option<Recorder>> = OnceLock::new();
    RECORDER
        .get_or_init(|| {
            let root = root()?;
            let bytes = cache::trim(&root, CAPACITY * 9 / 10, 8192).unwrap_or(CAPACITY);
            Some(Recorder {
                root,
                scope: scope(),
                state: Mutex::new(State {
                    seen: HashSet::new(),
                    bytes,
                    records: 0,
                }),
            })
        })
        .as_ref()
}

pub fn initialize() {
    let _ = recorder();
}

fn function<'a>(handle: *mut c_void) -> Result<&'a Function, String> {
    match unsafe { crate::object(handle) } {
        Some(Obj::Function(function)) => Ok(function),
        _ => Err("invalid preload function handle".into()),
    }
}

impl Recorder {
    fn store(
        &self,
        name: String,
        kind: u32,
        key: &[u8; 32],
        bytes: &[u8],
        limit: u64,
    ) -> Result<bool, String> {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if state.seen.contains(&name) {
            return Ok(false);
        }
        if state.seen.len() >= 8192 {
            return Err("shader preload recording reached its entry bound".into());
        }
        if kind == cache::RECIPE && state.records >= MAX_RECORDS {
            return Err("shader preload recording reached its pipeline bound".into());
        }
        let path = self.root.join(&name);
        // Existing immutable entries are checked by the preloader. A damaged entry is removed
        // there and regenerated when the live game next supplies its real source/descriptor.
        if let Ok(metadata) = path.metadata() {
            if metadata.is_file() {
                if let Ok(file) = std::fs::File::open(&path) {
                    let _ = file.set_times(
                        std::fs::FileTimes::new().set_modified(std::time::SystemTime::now()),
                    );
                }
                state.seen.insert(name);
                state.records += usize::from(kind == cache::RECIPE);
                return Ok(true);
            }
        }
        if state.bytes.saturating_add(bytes.len() as u64 + 84) > CAPACITY {
            return Err("shader preload recording reached its 512 MiB cache bound".into());
        }
        cache::write(&path, kind, key, bytes, limit)
            .map_err(|error| format!("shader preload cache write: {error}"))?;
        state.bytes += bytes.len() as u64 + 84;
        state.seen.insert(name);
        state.records += usize::from(kind == cache::RECIPE);
        Ok(true)
    }

    fn source(&self, function: &Function) -> Result<Source, String> {
        let descriptor = function.function_descriptor();
        let library = descriptor.function.library();
        let key = *library.content_hash();
        let text = cache::hex(&key);
        self.store(
            format!("library-{text}.qmc"),
            cache::LIBRARY,
            &key,
            library.bytes(),
            cache::MAX_LIBRARY,
        )?;
        Ok(source_description(function))
    }

    fn recipe(&self, recipe: Recipe) -> Result<(), String> {
        let bytes = serde_json::to_vec(&recipe).map_err(|error| error.to_string())?;
        let key = cache::hash(&bytes);
        if self.store(
            format!("pipeline-{}-{}.qmc", self.scope, cache::hex(&key)),
            cache::RECIPE,
            &key,
            &bytes,
            MAX_RECIPE,
        )? {
            RECORDED.fetch_add(1, Ordering::Relaxed);
        }
        Ok(())
    }
}

pub fn record_render(desc: &QmRenderPipelineDesc) {
    let Some(recorder) = recorder() else {
        return;
    };
    let result = (|| {
        recorder.source(function(desc.vertex_function)?)?;
        if !desc.fragment_function.is_null() {
            recorder.source(function(desc.fragment_function)?)?;
        }
        recorder.recipe(render_recipe(desc)?)
    })();
    if let Err(error) = result {
        crate::util::log_once(&format!("[Quadra Metal] {error}"));
    }
}

pub fn record_compute(function: &Function) {
    let Some(recorder) = recorder() else {
        return;
    };
    if let Err(error) = recorder
        .source(function)
        .and_then(|function| recorder.recipe(Recipe::Compute { function }))
    {
        crate::util::log_once(&format!("[Quadra Metal] {error}"));
    }
}

fn load_source(device: &Device, root: &Path, source: &Source) -> Result<Function, String> {
    let key = cache::unhex(&source.library).ok_or("invalid preload library key")?;
    let path = root.join(format!("library-{}.qmc", cache::hex(&key)));
    let bytes = cache::read(&path, cache::LIBRARY, &key, cache::MAX_LIBRARY)
        .map_err(|error| error.to_string())?
        .ok_or("missing preload library")?;
    if cache::hash(&bytes) != key {
        return Err("preload library content does not match its identity".into());
    }
    let library = device
        .new_library_with_data(&bytes)
        .map_err(|error| error.to_string())?;
    library
        .new_function_with_name_constant_values(&source.name, &source.constants)
        .map_err(|error| error.to_string())
}

fn replay(device: &Device, root: &Path, recipe: Recipe) -> Result<ReadyPipeline, String> {
    let options = PipelineOptions::default();
    match recipe {
        Recipe::Compute { function } => {
            let function = load_source(device, root, &function)?;
            device
                .new_compute_pipeline_state_with_function(&function, &options)
                .map(ReadyPipeline::Compute)
                .map_err(|error| error.to_string())
        }
        Recipe::Render {
            vertex,
            fragment,
            mut state,
        } => {
            let vertex = Box::new(Obj::Function(load_source(device, root, &vertex)?));
            let fragment = fragment
                .map(|source| {
                    load_source(device, root, &source)
                        .map(|function| Box::new(Obj::Function(function)))
                })
                .transpose()?;
            // These temporary handles only borrow owned function boxes during descriptor
            // conversion. No guest pointer or label is read from a persistent record.
            state.vertex_function = (&*vertex as *const Obj).cast_mut().cast();
            state.fragment_function = fragment.as_ref().map_or(std::ptr::null_mut(), |function| {
                (&**function as *const Obj).cast_mut().cast()
            });
            let descriptor = crate::render_pipeline_descriptor(&state)?;
            device
                .new_render_pipeline_state(&descriptor, &options)
                .map(ReadyPipeline::Render)
                .map_err(|error| error.to_string())
        }
    }
}

pub type Progress = extern "C" fn(u32, u32, u32, *mut c_void);

pub fn run(
    device: &Device,
    progress: Option<Progress>,
    context: *mut c_void,
    maximum: u32,
) -> Result<u32, String> {
    run_inner(device, progress, context, maximum, false).map(|(count, _)| count)
}

pub fn warm_live(device: &Device) -> WarmStates {
    if std::env::var("MACOBLOX_METAL_PRELOAD_IN_PROCESS").as_deref() != Ok("1") {
        return WarmStates::default();
    }
    let maximum = resident_limit(crate::limits::available_memory());
    match run_inner(device, None, std::ptr::null_mut(), maximum as u32, true) {
        Ok((count, states)) => {
            crate::util::log_once(&format!(
                "[Quadra Metal] retained {count} preloaded pipeline states for the game device (memory-based limit {maximum})"
            ));
            states
        }
        Err(error) => {
            crate::util::log_once(&format!(
                "[Quadra Metal] in-process shader preloading unavailable: {error}"
            ));
            WarmStates::default()
        }
    }
}

fn resident_limit(available: Option<u64>) -> usize {
    available.map_or(UNKNOWN_MEMORY_RESIDENT, |bytes| {
        let budget = (bytes / 4).min(bytes.saturating_sub(MEMORY_RESERVE));
        (budget / ESTIMATED_STATE_BYTES).min(MAX_RESIDENT as u64) as usize
    })
}

fn run_inner(
    device: &Device,
    progress: Option<Progress>,
    context: *mut c_void,
    maximum: u32,
    retain: bool,
) -> Result<(u32, WarmStates), String> {
    let mut states = WarmStates {
        states: BTreeMap::new(),
        limit: if retain {
            (maximum as usize).min(MAX_RESIDENT)
        } else {
            0
        },
    };
    let Some(root) = root() else {
        return Ok((0, states));
    };
    cache::trim(&root, CAPACITY * 9 / 10, 8192).map_err(|error| error.to_string())?;
    let prefix = format!("pipeline-{}-", scope());
    let rows = match std::fs::read_dir(&root) {
        Ok(rows) => rows,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok((0, states)),
        Err(error) => return Err(error.to_string()),
    };
    let mut records = Vec::new();
    for row in rows.flatten() {
        let name = row.file_name();
        let Some(name) = name.to_str() else {
            continue;
        };
        let Some(key) = name
            .strip_prefix(&prefix)
            .and_then(|s| s.strip_suffix(".qmc"))
            .and_then(cache::unhex)
        else {
            continue;
        };
        if records.len() >= 8192 {
            break;
        }
        let modified = row
            .metadata()
            .ok()
            .and_then(|data| data.modified().ok())
            .unwrap_or(std::time::UNIX_EPOCH);
        records.push((modified, row.path(), key));
    }
    records.sort_unstable_by_key(|row| std::cmp::Reverse(row.0));
    records.truncate((maximum as usize).min(MAX_RECORDS));
    let total = records.len() as u32;
    let mut failed = 0;
    let mut completed = 0;
    let started = std::time::Instant::now();
    let mut source_bytes = 0u64;
    if let Some(callback) = progress {
        callback(0, total, 0, context);
    }
    for (index, (_, path, key)) in records.into_iter().enumerate() {
        if retain
            && (started.elapsed().as_secs() >= 5
                || crate::limits::available_memory().is_some_and(|bytes| bytes < MEMORY_RESERVE))
        {
            break;
        }
        let result = (|| {
            let bytes = cache::read(&path, cache::RECIPE, &key, MAX_RECIPE)
                .map_err(|error| error.to_string())?
                .ok_or("invalid preload recipe")?;
            if cache::hash(&bytes) != key {
                return Err("preload recipe content does not match its identity".into());
            }
            let recipe = serde_json::from_slice(&bytes)
                .map_err(|error| format!("invalid preload recipe: {error}"))?;
            if retain {
                let sources = match &recipe {
                    Recipe::Compute { function } => vec![function],
                    Recipe::Render {
                        vertex, fragment, ..
                    } => std::iter::once(vertex).chain(fragment.iter()).collect(),
                };
                let weight = sources
                    .iter()
                    .map(|source| {
                        std::fs::metadata(root.join(format!("library-{}.qmc", source.library)))
                            .map_or(0, |data| data.len())
                    })
                    .sum::<u64>();
                if source_bytes.saturating_add(weight) > RESIDENT_SOURCE_BYTES {
                    return Ok(None);
                }
                source_bytes = source_bytes.saturating_add(weight);
            }
            replay(device, &root, recipe).map(Some)
        })();
        match result {
            Ok(Some(state)) => {
                WARMED.fetch_add(1, Ordering::Relaxed);
                completed += 1;
                if retain {
                    states.states.insert(key, state);
                } else {
                    state.release();
                }
            }
            Ok(None) => break,
            Err(_) => {
                // A failed speculative creation cannot fail the game. Forget its description;
                // the live game can record it again on a later successful creation.
                failed += 1;
                FAILED.fetch_add(1, Ordering::Relaxed);
                let _ = std::fs::remove_file(path);
            }
        }
        if let Some(callback) = progress {
            callback(index as u32 + 1, total, failed, context);
        }
    }
    Ok((completed, states))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn residency_preserves_headroom_on_small_and_memory_limited_hosts() {
        assert_eq!(resident_limit(Some(0)), 0);
        assert_eq!(resident_limit(Some(768 << 20)), 0);
        assert_eq!(resident_limit(Some(1 << 30)), 32);
        assert_eq!(resident_limit(Some(2 << 30)), 64);
        assert_eq!(resident_limit(Some(3 << 30)), 96);
        assert_eq!(resident_limit(Some(8 << 30)), 256);
        assert_eq!(resident_limit(Some(u64::MAX)), 256);
        assert_eq!(resident_limit(None), 64);
    }
}

//! Errors, logging and counters shared by the table's functions.
use metal2vulkan_runtime::{DebugMessage, MessageSeverity, MessageSink};
use std::cell::RefCell;
use std::collections::HashSet;
use std::ffi::{c_char, CString};
use std::io::Write;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::Duration;

thread_local! {
    static LAST_ERROR: RefCell<CString> = RefCell::new(CString::default());
}

pub fn set_error(message: impl Into<String>) {
    let text = message.into().replace('\0', " ");
    LAST_ERROR.with(|slot| *slot.borrow_mut() = CString::new(text).unwrap_or_default());
}

pub fn last_error() -> *const c_char {
    LAST_ERROR.with(|slot| slot.borrow().as_ptr())
}

pub fn fail<T>(message: impl Into<String>) -> *mut T {
    set_error(message);
    std::ptr::null_mut()
}

/// Runs `body`, turning a panic into `default` and an error message: no unwind may cross into
/// the guest.
pub fn guard<T>(default: T, body: impl FnOnce() -> T) -> T {
    match std::panic::catch_unwind(std::panic::AssertUnwindSafe(body)) {
        Ok(value) => value,
        Err(payload) => {
            let text = payload
                .downcast_ref::<String>()
                .cloned()
                .or_else(|| payload.downcast_ref::<&str>().map(|text| text.to_string()))
                .unwrap_or_else(|| "unknown panic".into());
            log_once(&format!("[Quadra Metal] internal error: {text}"));
            set_error(text);
            default
        }
    }
}

static LOGGED: Mutex<Option<HashSet<String>>> = Mutex::new(None);
const MAX_DISTINCT_LINES: usize = 400;

/// One line in the launch log per distinct text. The game's stderr is the log file.
pub fn log_once(text: &str) {
    let line: String = text.chars().take(1500).collect();
    let mut logged = LOGGED.lock().unwrap_or_else(|poison| poison.into_inner());
    let set = logged.get_or_insert_with(HashSet::new);
    if set.len() >= MAX_DISTINCT_LINES || !set.insert(line.clone()) {
        return;
    }
    drop(logged);
    let mut stderr = std::io::stderr().lock();
    let _ = writeln!(stderr, "{line}");
}

/// The runtime's validation messages and degrade notices, into the launch log once each.
pub fn message_sink() -> MessageSink {
    MessageSink::new(|message: &DebugMessage| {
        if let Some(notice) = &message.degradation {
            log_once(&format!(
                "[Quadra Metal] notice {}: {}",
                notice.degradation.code(),
                notice.reason
            ));
        } else if matches!(
            message.severity,
            MessageSeverity::Error | MessageSeverity::Warning
        ) || crate::identity::forwarded_info(&message.id_name)
        {
            log_once(&format!(
                "[Quadra Metal] {}: {}",
                message.id_name, message.text
            ));
        }
    })
}

static PIPELINES: AtomicU64 = AtomicU64::new(0);
static PIPELINE_NANOS: AtomicU64 = AtomicU64::new(0);

/// Logs the pipeline count and total making time every 100 pipelines.
pub fn note_pipeline_time(elapsed: Duration) {
    let count = PIPELINES.fetch_add(1, Ordering::Relaxed) + 1;
    let total = PIPELINE_NANOS.fetch_add(elapsed.as_nanos() as u64, Ordering::Relaxed)
        + elapsed.as_nanos() as u64;
    if count.is_multiple_of(100) || elapsed > Duration::from_secs(2) {
        let mut stderr = std::io::stderr().lock();
        let _ = writeln!(
            stderr,
            "[Quadra Metal] render pipelines: {count}, {:.1} s making in all (last {:.0} ms)",
            total as f64 / 1e9,
            elapsed.as_secs_f64() * 1000.0
        );
    }
}

/// A C caller's readable bytes. Validate representable spans before forming a Rust reference;
/// the caller still owns the allocation and guarantees its readability for this call.
pub unsafe fn input_bytes<'a>(
    pointer: *const std::ffi::c_void,
    length: u64,
) -> Result<&'a [u8], String> {
    if length > isize::MAX as u64 {
        return Err("host byte span exceeds the maximum slice length".into());
    }
    if length == 0 {
        return Ok(&[]);
    }
    if pointer.is_null() {
        return Err("null source for a nonempty host byte span".into());
    }
    Ok(unsafe { std::slice::from_raw_parts(pointer.cast::<u8>(), length as usize) })
}

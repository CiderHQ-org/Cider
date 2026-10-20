//! Roblox's shaders in the AIR metal2vulkan 0.2 reads.
//!
//! RobloxPlayer's `shaders_metal_osx.pack` holds metallibs of format 2.2 made by Apple's Metal
//! 2.2-era compiler: LLVM bitcode of module version 1 (typed pointers, no string table), and AIR
//! call forms older than those metal2vulkan decodes. Each library is rewritten once, on the host:
//!
//! 1. The host's LLVM (libLLVM, which Mesa depends on, through its stable C API) reads the old
//!    bitcode and prints the module as IR text.
//! 2. The text gets the current AIR forms:
//!    - texture samples, gathers, reads and writes take their texture's access qualifier as a
//!      last `i32` (from the entry's argument metadata), samples their `min_lod_clamp` (0), and
//!      samples, gathers and reads return `{ texel, i8 status }` (the texel is extracted);
//!    - memory atomics take their trailing `volatile` flag (false);
//!    - a fragment output's `air.render_target` names its dual-source index (0) after its
//!      attachment.
//!    - one-element array wrappers used for runtime-sized StructuredBuffers lose their old
//!      `air.buffer_size` hint, which modern AIR otherwise treats as a fixed object boundary.
//! 3. LLVM parses the text and writes current bitcode, which replaces the function's in the
//!    library (`MDSZ`, `HASH` and the bitcode section follow).
//!
//! Results are kept on disk by the SHA-256 of the original library. Only libraries of a format
//! older than 2.7 (the formats metal2vulkan documents) are touched.
use sha2::{Digest, Sha256};
use std::borrow::Cow;
use std::ffi::{c_char, c_int, c_void, CStr};
use std::path::PathBuf;
use std::sync::OnceLock;

type Ref = *mut c_void;

struct Llvm {
    context_create: unsafe extern "C" fn() -> Ref,
    context_dispose: unsafe extern "C" fn(Ref),
    buffer_copy: unsafe extern "C" fn(*const c_char, usize, *const c_char) -> Ref,
    buffer_start: unsafe extern "C" fn(Ref) -> *const c_char,
    buffer_size: unsafe extern "C" fn(Ref) -> usize,
    buffer_dispose: unsafe extern "C" fn(Ref),
    parse_bitcode: unsafe extern "C" fn(Ref, Ref, *mut Ref) -> c_int,
    parse_ir: unsafe extern "C" fn(Ref, Ref, *mut Ref, *mut *mut c_char) -> c_int,
    print_module: unsafe extern "C" fn(Ref) -> *mut c_char,
    write_bitcode: unsafe extern "C" fn(Ref) -> Ref,
    module_dispose: unsafe extern "C" fn(Ref),
    message_dispose: unsafe extern "C" fn(*mut c_char),
}

unsafe impl Send for Llvm {}
unsafe impl Sync for Llvm {}

/// The newest libLLVM of the usual places (15 or newer: opaque pointers).
fn llvm_candidates() -> Vec<PathBuf> {
    if let Some(path) = std::env::var_os("MACOBLOX_METAL_LIBLLVM") {
        return vec![path.into()];
    }
    let mut found: Vec<(u32, PathBuf)> = Vec::new();
    let mut directories: Vec<PathBuf> = ["/usr/lib", "/usr/lib64", "/usr/lib/x86_64-linux-gnu", "/usr/local/lib", "/app/lib"]
        .iter()
        .map(PathBuf::from)
        .collect();
    for root in ["/usr/lib", "/usr/lib64"] {
        if let Ok(entries) = std::fs::read_dir(root) {
            for entry in entries.flatten() {
                let name = entry.file_name().to_string_lossy().into_owned();
                if name.starts_with("llvm-") || name.starts_with("llvm") && name.len() <= 8 {
                    directories.push(entry.path().join("lib"));
                    directories.push(entry.path().join("lib64"));
                }
            }
        }
    }
    for directory in directories {
        let Ok(entries) = std::fs::read_dir(&directory) else { continue };
        for entry in entries.flatten() {
            let name = entry.file_name().to_string_lossy().into_owned();
            // libLLVM.so.23.1, libLLVM-19.so, libLLVM.so.18.1 (Debian: libLLVM.so.1 in llvm-N/lib).
            let Some(rest) = name.strip_prefix("libLLVM") else { continue };
            if !rest.contains(".so") {
                continue;
            }
            let version: u32 = rest
                .trim_start_matches(['-', '.'])
                .trim_start_matches("so.")
                .split(|c: char| !c.is_ascii_digit())
                .next()
                .and_then(|digits| digits.parse().ok())
                .or_else(|| {
                    directory.parent()?.file_name()?.to_str()?.strip_prefix("llvm-")?.parse().ok()
                })
                .unwrap_or(0);
            found.push((version, entry.path()));
        }
    }
    found.sort_by(|a, b| b.0.cmp(&a.0));
    found.into_iter().filter(|(version, _)| *version == 0 || *version >= 15).map(|(_, path)| path).collect()
}

fn llvm() -> Result<&'static Llvm, String> {
    static LLVM: OnceLock<Result<Llvm, String>> = OnceLock::new();
    LLVM.get_or_init(|| unsafe {
        let candidates = llvm_candidates();
        let library = candidates
            .iter()
            .find_map(|path| {
                let name = std::ffi::CString::new(path.as_os_str().as_encoded_bytes()).ok()?;
                let handle = libc::dlopen(name.as_ptr(), libc::RTLD_NOW | libc::RTLD_LOCAL);
                (!handle.is_null()).then_some((handle, path.clone()))
            })
            .ok_or_else(|| {
                "Roblox's shaders need the host's LLVM library (libLLVM 15 or newer, installed with Mesa)".to_string()
            })?;
        let (handle, path) = library;
        let symbol = |name: &CStr| -> Result<*mut c_void, String> {
            let pointer = libc::dlsym(handle, name.as_ptr());
            if pointer.is_null() {
                Err(format!("{} has no {}", path.display(), name.to_string_lossy()))
            } else {
                Ok(pointer)
            }
        };
        macro_rules! load {
            ($name:literal) => {
                std::mem::transmute(symbol($name)?)
            };
        }
        crate::util::log_once(&format!("[Quadra Metal] AIR upgrades through {}", path.display()));
        Ok(Llvm {
            context_create: load!(c"LLVMContextCreate"),
            context_dispose: load!(c"LLVMContextDispose"),
            buffer_copy: load!(c"LLVMCreateMemoryBufferWithMemoryRangeCopy"),
            buffer_start: load!(c"LLVMGetBufferStart"),
            buffer_size: load!(c"LLVMGetBufferSize"),
            buffer_dispose: load!(c"LLVMDisposeMemoryBuffer"),
            parse_bitcode: load!(c"LLVMParseBitcodeInContext2"),
            parse_ir: load!(c"LLVMParseIRInContext"),
            print_module: load!(c"LLVMPrintModuleToString"),
            write_bitcode: load!(c"LLVMWriteBitcodeToMemoryBuffer"),
            module_dispose: load!(c"LLVMDisposeModule"),
            message_dispose: load!(c"LLVMDisposeMessage"),
        })
    })
    .as_ref()
    .map_err(Clone::clone)
}

pub fn check_llvm() -> Result<(), String> {
    llvm().map(|_| ())
}

/// Old bitcode in, current bitcode of the rewritten module out.
fn upgrade_bitcode(bitcode: &[u8]) -> Result<Vec<u8>, String> {
    let llvm = llvm()?;
    unsafe {
        let context = (llvm.context_create)();
        let result = (|| {
            let input = (llvm.buffer_copy)(bitcode.as_ptr() as *const c_char, bitcode.len(), c"air".as_ptr());
            let mut module: Ref = std::ptr::null_mut();
            let failed = (llvm.parse_bitcode)(context, input, &mut module);
            (llvm.buffer_dispose)(input);
            if failed != 0 || module.is_null() {
                return Err("LLVM could not read the shader's bitcode".to_string());
            }
            let printed = (llvm.print_module)(module);
            let text = CStr::from_ptr(printed).to_string_lossy().into_owned();
            (llvm.message_dispose)(printed);
            (llvm.module_dispose)(module);
            let text = rewrite(&text)?;
            let source = (llvm.buffer_copy)(text.as_ptr() as *const c_char, text.len(), c"air.ll".as_ptr());
            let mut rewritten: Ref = std::ptr::null_mut();
            let mut message: *mut c_char = std::ptr::null_mut();
            // Takes the buffer.
            if (llvm.parse_ir)(context, source, &mut rewritten, &mut message) != 0 || rewritten.is_null() {
                let detail = if message.is_null() {
                    String::new()
                } else {
                    let detail = CStr::from_ptr(message).to_string_lossy().into_owned();
                    (llvm.message_dispose)(message);
                    detail
                };
                return Err(format!("the upgraded shader does not parse: {}", detail.chars().take(400).collect::<String>()));
            }
            let output = (llvm.write_bitcode)(rewritten);
            let bytes = std::slice::from_raw_parts((llvm.buffer_start)(output) as *const u8, (llvm.buffer_size)(output)).to_vec();
            (llvm.buffer_dispose)(output);
            (llvm.module_dispose)(rewritten);
            Ok(bytes)
        })();
        (llvm.context_dispose)(context);
        result
    }
}

// ---------------------------------------------------------------------------------------------
// The IR text rewrite.

#[derive(Clone, Copy, PartialEq)]
enum Kind {
    Sample,
    SampleGrad,
    Gather,
    Read,
    Write,
    Atomic,
}

impl Kind {
    fn of(name: &str) -> Option<Kind> {
        let starts = |prefixes: &[&str]| prefixes.iter().any(|prefix| name.starts_with(prefix));
        if starts(&["air.sample_texture_", "air.sample_depth_"]) {
            let family = name.split('.').nth(1).unwrap_or_default();
            return Some(if family.ends_with("_grad") { Kind::SampleGrad } else { Kind::Sample });
        }
        if starts(&["air.gather_texture_", "air.gather_depth_"]) {
            return Some(Kind::Gather);
        }
        if starts(&["air.read_texture_", "air.read_depth_"]) {
            return Some(Kind::Read);
        }
        if starts(&["air.write_texture_"]) {
            return Some(Kind::Write);
        }
        if starts(&["air.atomic.global.", "air.atomic.local."]) {
            return Some(Kind::Atomic);
        }
        None
    }

    fn returns_status(self) -> bool {
        matches!(self, Kind::Sample | Kind::SampleGrad | Kind::Gather | Kind::Read)
    }
}

/// Top-level comma split of an argument list.
fn split_arguments(text: &str) -> Vec<String> {
    let (mut out, mut depth, mut start) = (Vec::new(), 0i32, 0);
    for (index, character) in text.char_indices() {
        match character {
            '<' | '(' | '{' | '[' => depth += 1,
            '>' | ')' | '}' | ']' => depth -= 1,
            ',' if depth == 0 => {
                out.push(text[start..index].trim().to_string());
                start = index + 1;
            }
            _ => {}
        }
    }
    let tail = text[start..].trim();
    if !tail.is_empty() {
        out.push(tail.to_string());
    }
    out
}

/// The index of the `)` closing the `(` at `open`.
fn closing(text: &str, open: usize) -> Option<usize> {
    let mut depth = 0;
    for (index, character) in text[open..].char_indices() {
        match character {
            '(' => depth += 1,
            ')' => {
                depth -= 1;
                if depth == 0 {
                    return Some(open + index);
                }
            }
            _ => {}
        }
    }
    None
}

struct Entry {
    name: String,
    parameters: usize,
    /// Argument index -> access (0 sample, 1 read, 2 write, 3 read_write).
    access: std::collections::HashMap<usize, u32>,
}

fn entry_of(lines: &[&str]) -> Entry {
    let mut access = std::collections::HashMap::new();
    let mut name = String::new();
    for line in lines {
        if let Some(texture) = line.find("!\"air.texture\"") {
            let head = &line[..texture];
            let index = head
                .rsplit("i32 ")
                .next()
                .and_then(|value| value.trim_end_matches([',', ' ']).parse::<usize>().ok());
            let value = [("!\"air.read_write\"", 3), ("!\"air.sample\"", 0), ("!\"air.write\"", 2), ("!\"air.read\"", 1)]
                .iter()
                .find(|(token, _)| line.contains(token))
                .map(|(_, value)| *value);
            if let (Some(index), Some(value)) = (index, value) {
                access.insert(index, value);
            }
        }
        for stage in ["!air.vertex = !{", "!air.fragment = !{", "!air.kernel = !{"] {
            if line.starts_with(stage) {
                // The stage's node: `!N = !{ptr @main0, ...}`.
                let node = line[stage.len()..].split(['}', ',']).next().unwrap_or_default().trim().to_string();
                let prefix = format!("{node} = !{{");
                if let Some(definition) = lines.iter().find(|candidate| candidate.starts_with(&prefix)) {
                    if let Some(at) = definition.find('@') {
                        name = definition[at + 1..]
                            .split([',', ' ', '}'])
                            .next()
                            .unwrap_or_default()
                            .to_string();
                    }
                }
            }
        }
    }
    let mut parameters = 0;
    let marker = format!("@{name}(");
    if let Some(definition) = lines.iter().find(|line| line.starts_with("define ") && line.contains(&marker)) {
        let open = definition.find(&marker).unwrap() + marker.len() - 1;
        if let Some(close) = closing(definition, open) {
            parameters = split_arguments(&definition[open + 1..close]).len();
        }
    }
    Entry { name, parameters, access }
}

fn rewritten_arguments(kind: Kind, arguments: &[String], access: Option<u32>, declaration: bool) -> Vec<String> {
    let mut out = arguments.to_vec();
    let zero = if declaration { "float".to_string() } else { "float 0.000000e+00".to_string() };
    match kind {
        Kind::Atomic => out.push(if declaration { "i1".into() } else { "i1 false".into() }),
        _ => {
            if kind == Kind::Sample {
                out.push(zero.clone());
            }
            if kind == Kind::SampleGrad {
                // min_lod_clamp follows dpdy, before the offset flag (the last i1).
                let flag = out.iter().rposition(|argument| argument.split_whitespace().next() == Some("i1"));
                match flag {
                    Some(at) => out.insert(at, zero),
                    None => out.push(zero),
                }
            }
            let fallback = match kind {
                Kind::Read => 1,
                Kind::Write => 2,
                _ => 0,
            };
            let value = access.unwrap_or(fallback);
            out.push(if declaration { "i32".into() } else { format!("i32 {value}") });
        }
    }
    out
}

/// The operand's value name: the last token of `type attributes %value`.
fn value_of(argument: &str) -> &str {
    argument.rsplit(' ').next().unwrap_or_default()
}

const FAST_MATH: [&str; 8] = ["fast", "nnan", "ninf", "nsz", "arcp", "contract", "afn", "reassoc"];

pub fn rewrite(text: &str) -> Result<String, String> {
    let lines: Vec<&str> = text.lines().collect();
    let entry = entry_of(&lines);
    // Old HLSL-to-Metal compilers spell StructuredBuffer<T> as a struct containing
    // T[1], with buffer_size equal to one element. It is a runtime-sized buffer,
    // not a reference limited to that element. Modern AIR uses no buffer_size
    // for it; keeping the old hint clips Vulkan descriptors to one record.
    let runtime_arrays: Vec<&str> = lines
        .iter()
        .filter_map(|line| {
            let (name, body) = line.split_once(" = type ")?;
            if !body.starts_with("{ [1 x ") || !body.ends_with("] }") {
                return None;
            }
            name.strip_prefix("%struct.")
        })
        .collect();
    let mut out = String::with_capacity(text.len() + text.len() / 8);
    let mut current: Option<String> = None;
    let mut temporaries = 0usize;
    for raw in &lines {
        let mut line = raw.to_string();
        if line.contains("!\"air.buffer\"") && runtime_arrays.iter().any(|name| {
            line.contains(&format!("!\"air.arg_type_name\", !\"{name}\""))
        }) {
            if let Some(at) = line.find(", !\"air.buffer_size\", i32 ") {
                let end = at + ", !\"air.buffer_size\", i32 ".len();
                let digits = line[end..].chars().take_while(|c| c.is_ascii_digit()).count();
                if digits > 0 {
                    line.replace_range(at..end + digits, "");
                }
            }
        }
        // A fragment output names its attachment and (AIR 2.3 and later) its dual-source index.
        if let Some(at) = line.find("!\"air.render_target\", i32 ") {
            let digits_at = at + "!\"air.render_target\", i32 ".len();
            let digits = line[digits_at..].chars().take_while(|c| c.is_ascii_digit()).count();
            let after = digits_at + digits;
            if digits > 0 && !line[after..].starts_with(", i32 ") {
                line.insert_str(after, ", i32 0");
            }
        }
        if line.starts_with("define ") {
            current = line.find('@').map(|at| line[at + 1..].split('(').next().unwrap_or_default().to_string());
        } else if line == "}" {
            current = None;
        }
        // `declare RET @air.NAME(TYPES) ATTRIBUTES`
        if line.starts_with("declare ") {
            if let Some(at) = line.find(" @air.") {
                let open = line[at..].find('(').map(|offset| at + offset);
                let name = open.map(|open| line[at + 2..open].to_string()).unwrap_or_default();
                if let (Some(kind), Some(open)) = (Kind::of(&name), open) {
                    let close = closing(&line, open).ok_or("an unbalanced declaration")?;
                    let ret = line["declare ".len()..at].to_string();
                    let arguments = rewritten_arguments(kind, &split_arguments(&line[open + 1..close]), None, true);
                    let ret = if kind.returns_status() { format!("{{ {ret}, i8 }}") } else { ret };
                    out.push_str(&format!("declare {ret} @{name}({}){}\n", arguments.join(", "), &line[close + 1..]));
                    continue;
                }
            }
        }
        // `[%x = ][tail ]call [flags] RET @air.NAME(ARGS) REST`
        if let Some(call) = line.find("call ") {
            if let Some(at) = line[call..].find(" @air.").map(|offset| call + offset) {
                let open = line[at..].find('(').map(|offset| at + offset);
                let name = open.map(|open| line[at + 2..open].to_string()).unwrap_or_default();
                if let (Some(kind), Some(open)) = (Kind::of(&name), open) {
                    let close = closing(&line, open).ok_or("an unbalanced call")?;
                    let arguments = split_arguments(&line[open + 1..close]);
                    let access = if current.as_deref() == Some(entry.name.as_str()) {
                        arguments.first().and_then(|texture| {
                            let value = value_of(texture).strip_prefix('%')?.parse::<usize>().ok()?;
                            (value < entry.parameters).then(|| entry.access.get(&value).copied()).flatten()
                        })
                    } else {
                        None
                    };
                    let arguments = rewritten_arguments(kind, &arguments, access, false);
                    // Split `[flags] RET` after `call `.
                    let mut words: Vec<&str> = line[call + "call ".len()..at].split(' ').collect();
                    let mut flags = Vec::new();
                    while words.first().is_some_and(|word| FAST_MATH.contains(word)) {
                        flags.push(words.remove(0));
                    }
                    let ret = words.join(" ");
                    let head = &line[..call + "call ".len()];
                    let flags = if flags.is_empty() { String::new() } else { format!("{} ", flags.join(" ")) };
                    let rest = &line[close + 1..];
                    if kind.returns_status() && ret != "void" {
                        let Some(assign) = head.find(" = ") else {
                            // An unused result: the struct is dropped as the texel was.
                            out.push_str(&format!("{head}{flags}{{ {ret}, i8 }} @{name}({}){rest}\n", arguments.join(", ")));
                            continue;
                        };
                        let indent = &head[..head.len() - head.trim_start().len()];
                        let result = head[..assign].trim();
                        temporaries += 1;
                        let temporary = format!("%qm.status.{temporaries}");
                        let structure = format!("{{ {ret}, i8 }}");
                        out.push_str(&format!(
                            "{indent}{temporary} = {}{flags}{structure} @{name}({}){rest}\n",
                            &head[assign + 3..],
                            arguments.join(", ")
                        ));
                        out.push_str(&format!("{indent}{result} = extractvalue {structure} {temporary}, 0\n"));
                    } else {
                        out.push_str(&format!("{head}{flags}{ret} @{name}({}){rest}\n", arguments.join(", ")));
                    }
                    continue;
                }
            }
        }
        out.push_str(&line);
        out.push('\n');
    }
    Ok(out)
}

// ---------------------------------------------------------------------------------------------
// The container.

fn u64_at(bytes: &[u8], at: usize) -> Option<u64> {
    bytes.get(at..at + 8).map(|b| u64::from_le_bytes(b.try_into().unwrap()))
}

struct FunctionTags {
    mdsz: usize,
    hash: Option<usize>,
    offt: usize,
}

/// Whether the library is of a format older than metal2vulkan reads.
fn old_format(bytes: &[u8]) -> bool {
    bytes.len() >= 0x58 && &bytes[..4] == b"MTLB" && {
        let major = u16::from_le_bytes([bytes[6], bytes[7]]);
        let minor = u16::from_le_bytes([bytes[8], bytes[9]]);
        (major, minor) < (2, 7)
    }
}

fn function_tags(bytes: &[u8]) -> Result<Vec<FunctionTags>, String> {
    let bad = || "a malformed metallib function table".to_string();
    let list = u64_at(bytes, 24).ok_or_else(bad)? as usize;
    let count = u32::from_le_bytes(bytes.get(list..list + 4).ok_or_else(bad)?.try_into().unwrap()) as usize;
    let mut at = list + 4;
    let mut out = Vec::with_capacity(count.min(1024));
    for _ in 0..count {
        let size = u32::from_le_bytes(bytes.get(at..at + 4).ok_or_else(bad)?.try_into().unwrap()) as usize;
        let end = at + size;
        let mut position = at + 4;
        let (mut mdsz, mut hash, mut offt) = (None, None, None);
        while position + 4 <= end {
            let tag = &bytes[position..position + 4];
            position += 4;
            if tag == b"ENDT" {
                break;
            }
            let length = u16::from_le_bytes(bytes.get(position..position + 2).ok_or_else(bad)?.try_into().unwrap()) as usize;
            position += 2;
            match tag {
                b"MDSZ" => mdsz = Some(position),
                b"HASH" if length == 32 => hash = Some(position),
                b"OFFT" => offt = Some(position),
                _ => {}
            }
            position += length;
        }
        out.push(FunctionTags { mdsz: mdsz.ok_or_else(bad)?, hash, offt: offt.ok_or_else(bad)? });
        at = end;
    }
    Ok(out)
}

fn upgrade_library(bytes: &[u8]) -> Result<Vec<u8>, String> {
    let functions = function_tags(bytes)?;
    let bad = || "a malformed metallib".to_string();
    let bitcode_offset = u64_at(bytes, 72).ok_or_else(bad)? as usize;
    let bitcode_size = u64_at(bytes, 80).ok_or_else(bad)? as usize;
    let mut section = Vec::new();
    let mut placed = Vec::new();
    for function in &functions {
        let size = u64_at(bytes, function.mdsz).ok_or_else(bad)? as usize;
        let relative = u64_at(bytes, function.offt + 16).ok_or_else(bad)? as usize;
        let start = bitcode_offset + relative;
        let old = bytes.get(start..start + size).ok_or_else(bad)?;
        let new = upgrade_bitcode(old)?;
        placed.push((section.len(), new.len(), Sha256::digest(&new)));
        section.extend_from_slice(&new);
    }
    let mut out = Vec::with_capacity(bitcode_offset + section.len());
    out.extend_from_slice(&bytes[..bitcode_offset]);
    out.extend_from_slice(&section);
    out.extend_from_slice(bytes.get(bitcode_offset + bitcode_size..).unwrap_or_default());
    for (function, (relative, size, hash)) in functions.iter().zip(&placed) {
        out[function.mdsz..function.mdsz + 8].copy_from_slice(&(*size as u64).to_le_bytes());
        out[function.offt + 16..function.offt + 24].copy_from_slice(&(*relative as u64).to_le_bytes());
        if let Some(at) = function.hash {
            out[at..at + 32].copy_from_slice(hash);
        }
    }
    let total = out.len() as u64;
    out[80..88].copy_from_slice(&(section.len() as u64).to_le_bytes());
    out[16..24].copy_from_slice(&total.to_le_bytes());
    Ok(out)
}

fn cache_directory() -> Option<PathBuf> {
    let root = std::env::var_os("MACOBLOX_METAL_SHADER_CACHE")?;
    let directory = PathBuf::from(root).join("air-upgrade-v2");
    std::fs::create_dir_all(&directory).ok()?;
    Some(directory)
}

/// The library as metal2vulkan reads it: old formats upgraded (cached), others unchanged.
pub fn prepare(bytes: &[u8]) -> Result<Cow<'_, [u8]>, String> {
    if !old_format(bytes) {
        return Ok(bytes.into());
    }
    let key = format!("{:x}", Sha256::digest(bytes));
    let cached = cache_directory().map(|directory| directory.join(format!("{key}.metallib")));
    if let Some(path) = &cached {
        if let Ok(data) = std::fs::read(path) {
            return Ok(data.into());
        }
    }
    let upgraded = upgrade_library(bytes)?;
    if let Some(path) = cached {
        // Roblox loads libraries on several threads; each writer needs its
        // own inode so a rename cannot expose another writer's partial data.
        static WRITER: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let writer = WRITER.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let temporary = path.with_extension(format!("tmp{}-{writer}", std::process::id()));
        if std::fs::write(&temporary, &upgraded).is_ok() {
            let _ = std::fs::rename(&temporary, &path);
        }
        let _ = std::fs::remove_file(&temporary);
    }
    Ok(upgraded.into())
}

#[cfg(test)]
mod tests;

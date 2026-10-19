//! pack_census <shaders_metal_osx.pack> [--compute]: loads every metallib of a Roblox shader pack
//! as the game does (newLibraryWithData, newFunctionWithName) and, with --compute, makes each
//! kernel's pipeline state. Prints one line per failure and a summary.
use metal2vulkan_runtime::{Device, PipelineOptions};
use std::collections::BTreeMap;

fn main() {
    let path = std::env::args().nth(1).expect("pack path");
    let compute = std::env::args().any(|argument| argument == "--compute");
    let pack = std::fs::read(&path).expect("read pack");
    let device = Device::system_default().expect("device");
    let (mut libraries, mut functions, mut kernels) = (0, 0, 0);
    let mut failures: BTreeMap<String, usize> = BTreeMap::new();
    let mut at = 0;
    while let Some(found) = pack[at..].windows(4).position(|window| window == b"MTLB") {
        let start = at + found;
        let size = pack.get(start + 16..start + 24).map(|b| u64::from_le_bytes(b.try_into().unwrap())).unwrap_or(0) as usize;
        if size < 0x58 || start + size > pack.len() {
            at = start + 4;
            continue;
        }
        at = start + size;
        let prepared = match quadra_metal_host::air::prepare(&pack[start..start + size]) {
            Ok(prepared) => prepared,
            Err(error) => {
                *failures.entry(format!("upgrade: {error}")).or_default() += 1;
                continue;
            }
        };
        let bytes = quadra_metal_host::normalize_metallib(&prepared);
        let library = match device.new_library_with_data(&bytes) {
            Ok(library) => library,
            Err(error) => {
                *failures.entry(format!("library: {error}")).or_default() += 1;
                continue;
            }
        };
        libraries += 1;
        for name in library.function_names() {
            let function = match library.new_function_with_name(&name) {
                Ok(function) => function,
                Err(error) => {
                    *failures.entry(format!("function: {error}")).or_default() += 1;
                    continue;
                }
            };
            functions += 1;
            if compute && matches!(function.function_type(), Ok(metal2vulkan::metal::FunctionType::Kernel)) {
                match device.new_compute_pipeline_state_with_function(&function, &PipelineOptions::default()) {
                    Ok(_) => kernels += 1,
                    Err(error) => *failures.entry(format!("kernel {name}: {error}")).or_default() += 1,
                }
            }
        }
    }
    for (failure, count) in &failures {
        println!("{count:5} x {}", failure.chars().take(400).collect::<String>());
    }
    println!("libraries {libraries}, functions {functions}, kernels made {kernels}");
    if !failures.is_empty() {
        std::process::exit(1);
    }
}

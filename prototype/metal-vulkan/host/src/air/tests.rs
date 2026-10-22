//! Self-authored legacy AIR, so regression coverage needs no Roblox shader assets.
use super::*;
use metal2vulkan_runtime::{Device, PipelineOptions, ResourceOptions, Size};

const SCATTER: &str = r#"
target datalayout = "e-p:64:64-i64:64-v128:128-n8:16:32"
target triple = "air64-apple-macosx10.11.0"
%struct.Records = type { [1 x <4 x i32>] }
define void @scatter(ptr addrspace(1) %out, ptr addrspace(1) %input, <3 x i32> %tid) {
  %id = extractelement <3 x i32> %tid, i32 0
  %wide = zext i32 %id to i64
  %src = getelementptr %struct.Records, ptr addrspace(1) %input, i64 0, i32 0, i64 %wide
  %data = load <4 x i32>, ptr addrspace(1) %src, align 16
  %index = extractelement <4 x i32> %data, i32 0
  %index64 = zext i32 %index to i64
  %dst = getelementptr %struct.Records, ptr addrspace(1) %out, i64 0, i32 0, i64 %index64
  store <4 x i32> %data, ptr addrspace(1) %dst, align 16
  ret void
}
!air.version = !{!0}
!air.language_version = !{!1}
!air.kernel = !{!2}
!0 = !{i32 1, i32 8, i32 0}
!1 = !{!"Metal", i32 1, i32 1, i32 0}
!2 = !{ptr @scatter, !3, !4}
!3 = !{}
!4 = !{!5, !6, !7}
!5 = !{i32 0, !"air.buffer", !"air.buffer_size", i32 16, !"air.location_index", i32 0, i32 1, !"air.read_write", !"air.arg_type_size", i32 16, !"air.arg_type_align_size", i32 16, !"air.arg_type_name", !"Records", !"air.arg_name", !"out"}
!6 = !{i32 1, !"air.buffer", !"air.buffer_size", i32 16, !"air.location_index", i32 1, i32 1, !"air.read", !"air.arg_type_size", i32 16, !"air.arg_type_align_size", i32 16, !"air.arg_type_name", !"Records", !"air.arg_name", !"input"}
!7 = !{i32 2, !"air.thread_position_in_grid", !"air.arg_type_name", !"uint3", !"air.arg_name", !"tid"}
"#;

#[test]
fn runtime_array_bounds_and_fixed_constants() {
    let text = format!("{SCATTER}\n%struct.Constants = type {{ [4 x <4 x float>] }}\n!8 = !{{i32 3, !\"air.buffer\", !\"air.buffer_size\", i32 64, !\"air.arg_type_name\", !\"Constants\"}}\n");
    let rewritten = rewrite(&text).unwrap();
    assert_eq!(rewritten.matches("!\"air.buffer_size\"").count(), 1);
    assert!(rewritten.contains("!\"air.buffer_size\", i32 64"));
    // Element layout metadata still describes one record; only the fixed buffer bound goes.
    assert_eq!(
        rewritten.matches("!\"air.arg_type_size\", i32 16").count(),
        2
    );
    assert_eq!(rewrite(&rewritten).unwrap(), rewritten);
}

/// Assemble our IR through the same dynamically loaded LLVM C API as the upgrader.
fn bitcode(text: &str) -> Vec<u8> {
    let llvm = llvm().unwrap();
    unsafe {
        let context = (llvm.context_create)();
        let source = (llvm.buffer_copy)(text.as_ptr().cast(), text.len(), c"fixture.ll".as_ptr());
        let mut module = std::ptr::null_mut();
        let mut message = std::ptr::null_mut();
        let result = (llvm.parse_ir)(context, source, &mut module, &mut message);
        assert_eq!(result, 0, "fixture IR must parse");
        let output = (llvm.write_bitcode)(module);
        let bytes = std::slice::from_raw_parts(
            (llvm.buffer_start)(output).cast(),
            (llvm.buffer_size)(output),
        )
        .to_vec();
        (llvm.buffer_dispose)(output);
        (llvm.module_dispose)(module);
        (llvm.context_dispose)(context);
        bytes
    }
}

/// The documented legacy MTLB container, with one compute entry and empty metadata sections.
fn library(bitcode: &[u8]) -> Vec<u8> {
    fn tag(out: &mut Vec<u8>, name: &[u8; 4], data: &[u8]) {
        out.extend(name);
        out.extend((data.len() as u16).to_le_bytes());
        out.extend(data);
    }
    let mut tags = Vec::new();
    tag(&mut tags, b"NAME", b"scatter\0");
    tag(&mut tags, b"TYPE", &[2]);
    tag(&mut tags, b"HASH", &Sha256::digest(bitcode));
    tag(&mut tags, b"OFFT", &[0; 24]);
    tag(&mut tags, b"VERS", &[1, 0, 8, 0, 1, 0, 1, 0]);
    tag(&mut tags, b"MDSZ", &(bitcode.len() as u64).to_le_bytes());
    tags.extend(b"ENDT");
    let entry_size = (4 + tags.len()) as u64;
    let public = 88 + 4 + entry_size;
    let private = public + 8;
    let code = private + 8;
    let mut out = b"MTLB\x01\x80\x02\0\x02\0\0\0\0\0\0\0".to_vec();
    for value in [
        code + bitcode.len() as u64,
        88,
        entry_size,
        public,
        8,
        private,
        8,
        code,
        bitcode.len() as u64,
    ] {
        out.extend(value.to_le_bytes());
    }
    out.extend(1u32.to_le_bytes());
    out.extend((entry_size as u32).to_le_bytes());
    out.extend(tags);
    for _ in 0..2 {
        out.extend(8u32.to_le_bytes());
        out.extend(b"ENDT");
    }
    out.extend(bitcode);
    out
}

#[test]
fn concurrent_cache_requests_upgrade_once_and_corrupt_entries_rebuild() {
    use std::sync::atomic::Ordering;
    let directory = std::env::temp_dir().join(format!("quadra-air-cache-{}", std::process::id()));
    let cache = UpgradeCache::new(directory.clone()).unwrap();
    let original = library(&bitcode(SCATTER));
    let before = UPGRADES.load(Ordering::Relaxed);
    let results = std::thread::scope(|scope| {
        let workers: Vec<_> = (0..8)
            .map(|_| {
                scope.spawn(|| {
                    prepare_cached(&original, Some(&cache))
                        .unwrap()
                        .into_owned()
                })
            })
            .collect();
        workers
            .into_iter()
            .map(|thread| thread.join().unwrap())
            .collect::<Vec<_>>()
    });
    assert!(results.iter().all(|bytes| bytes == &results[0]));
    assert_eq!(UPGRADES.load(Ordering::Relaxed) - before, 1);
    let path = directory.join(format!(
        "{}.qmc",
        crate::cache::hex(&crate::cache::hash(&original))
    ));
    let mut damaged = std::fs::read(&path).unwrap();
    let last = damaged.len() - 1;
    damaged[last] ^= 1;
    std::fs::write(&path, damaged).unwrap();
    assert_eq!(
        prepare_cached(&original, Some(&cache)).unwrap().as_ref(),
        results[0]
    );
    assert_eq!(UPGRADES.load(Ordering::Relaxed) - before, 2);
    std::fs::remove_dir_all(directory).unwrap();
}

#[test]
#[ignore = "requires Vulkan and libLLVM; run in the Metal host CI job"]
fn legacy_scatter_upload_reaches_every_record() {
    let original = library(&bitcode(SCATTER));
    // Exercise old-container detection, LLVM reassembly and new-container normalization.
    assert!(old_format(&original));
    let upgraded = upgrade_library(&original).unwrap();
    let device = Device::system_default().unwrap();
    let lib = device
        .new_library_with_data(&crate::normalize_metallib(&upgraded))
        .unwrap();
    let function = lib.new_function_with_name("scatter").unwrap();
    let pipeline = device
        .new_compute_pipeline_state_with_function(&function, &PipelineOptions::default())
        .unwrap();
    let queue = device.new_command_queue().unwrap();
    const COUNT: usize = 64;
    let mut input = Vec::new();
    let mut expected = vec![0u8; COUNT * 16];
    for i in 0..COUNT {
        let target = (i * 17) % COUNT;
        let record = [target as u32, 1000 + i as u32, !(i as u32), 0x12345678];
        for (j, value) in record.iter().enumerate() {
            let bytes = value.to_le_bytes();
            input.extend(bytes);
            expected[target * 16 + j * 4..target * 16 + j * 4 + 4].copy_from_slice(&bytes);
        }
    }
    let source = device
        .new_buffer_with_bytes(&input, ResourceOptions::shared())
        .unwrap();
    let output = device
        .new_buffer_with_bytes(&vec![0; expected.len()], ResourceOptions::shared())
        .unwrap();
    let command = queue.command_buffer().unwrap();
    let mut compute = command.compute_command_encoder().unwrap();
    compute.set_compute_pipeline_state(&pipeline).unwrap();
    compute.set_buffer(Some(&output), 0, 0).unwrap();
    compute.set_buffer(Some(&source), 0, 1).unwrap();
    compute
        .dispatch_threadgroups(Size::new(1, 1, 1), Size::new(COUNT as u64, 1, 1))
        .unwrap();
    compute.end_encoding().unwrap();
    command.commit().unwrap();
    command.wait_until_completed().unwrap();
    let actual =
        unsafe { std::slice::from_raw_parts(output.contents().unwrap().as_ptr(), expected.len()) };
    assert_eq!(
        actual, expected,
        "every instance record must survive the scatter upload"
    );
}

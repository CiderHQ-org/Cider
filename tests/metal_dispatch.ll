; Authored regression kernel. A 65-thread dispatch must leave words 65..127 untouched.
target triple = "air64_v28-apple-macosx26.0.0"
define void @dispatch_probe(ptr addrspace(1) %out, ptr addrspace(3) %scratch, i32 %tid) {
entry:
  %at = getelementptr i32, ptr addrspace(1) %out, i32 %tid
  %value = add i32 %tid, 1
  %lane = urem i32 %tid, 64
  %slot = getelementptr i32, ptr addrspace(3) %scratch, i32 %lane
  store volatile i32 %value, ptr addrspace(3) %slot, align 4
  %loaded = load volatile i32, ptr addrspace(3) %slot, align 4
  store i32 %loaded, ptr addrspace(1) %at, align 4
  ret void
}
!air.kernel = !{!0}
!0 = !{ptr @dispatch_probe, !1, !2}
!1 = !{}
!2 = !{!3, !5, !4}
!3 = !{i32 0, !"air.buffer", !"air.location_index", i32 0, i32 1, !"air.read_write", !"air.address_space", i32 1, !"air.arg_type_size", i32 4, !"air.arg_type_align_size", i32 4, !"air.arg_type_name", !"uint", !"air.arg_name", !"out"}
!4 = !{i32 2, !"air.thread_position_in_grid", !"air.arg_type_name", !"uint", !"air.arg_name", !"tid"}
!5 = !{i32 1, !"air.buffer", !"air.location_index", i32 0, i32 1, !"air.read_write", !"air.address_space", i32 3, !"air.arg_type_size", i32 4, !"air.arg_type_align_size", i32 4, !"air.arg_type_name", !"uint", !"air.arg_name", !"scratch"}

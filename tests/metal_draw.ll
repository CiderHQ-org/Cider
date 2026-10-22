; Authored draw workload: one constant buffer and a procedural full-screen triangle.
target triple = "air64_v28-apple-macosx26.0.0"
define <4 x float> @bench_vertex(ptr addrspace(2) %scale, i32 %vid) {
  %s = load float, ptr addrspace(2) %scale, align 4
  %x = icmp eq i32 %vid, 1
  %y = icmp eq i32 %vid, 2
  %xf = select i1 %x, float 3.0, float -1.0
  %yf = select i1 %y, float 3.0, float -1.0
  %xs = fmul float %xf, %s
  %ys = fmul float %yf, %s
  %v0 = insertelement <4 x float> <float 0.0, float 0.0, float 0.0, float 1.0>, float %xs, i32 0
  %v1 = insertelement <4 x float> %v0, float %ys, i32 1
  ret <4 x float> %v1
}
define <4 x float> @bench_fragment() {
  ret <4 x float> <float 1.0, float 0.0, float 1.0, float 1.0>
}
!air.vertex = !{!0}
!air.fragment = !{!5}
!0 = !{ptr @bench_vertex, !1, !2}
!1 = !{!3}
!2 = !{!4, !8}
!3 = !{!"air.position", !"air.arg_type_name", !"float4", !"air.arg_name", !"position"}
!4 = !{i32 0, !"air.buffer", !"air.location_index", i32 0, i32 1, !"air.read", !"air.address_space", i32 2, !"air.arg_type_size", i32 4, !"air.arg_type_align_size", i32 4, !"air.arg_type_name", !"float", !"air.arg_name", !"scale"}
!5 = !{ptr @bench_fragment, !6, !7}
!6 = !{!9}
!7 = !{}
!8 = !{i32 1, !"air.vertex_id", !"air.arg_type_name", !"uint", !"air.arg_name", !"vid"}
!9 = !{!"air.render_target", i32 0, i32 0, !"air.arg_type_name", !"float4", !"air.arg_name", !"color"}

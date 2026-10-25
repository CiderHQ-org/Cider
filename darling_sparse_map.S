/* ABI-preserving implementation of darling_sparse_map.c.
 * Keep the original libkqueue functions' rbp frame, stack allocation,
 * callee-save set and epilog offsets so their unwind metadata stays valid.
 * Copyright/license: see darling_sparse_map.c (Mark Heily, ISC).
 */
#ifdef __APPLE__
#define SYMBOL(name) _##name
#define LOCAL(name) L##name
#else
#define SYMBOL(name) name
#define LOCAL(name) .L##name
#endif
.text
.p2align 4
.globl SYMBOL(quadra_sparse_map_insert_asm)
SYMBOL(quadra_sparse_map_insert_asm):
    pushq %rbp
    movq %rsp, %rbp
    subq $64, %rsp
    testl %esi, %esi
    js LOCAL(insert_fail)
    cmpq $2147483647, (%rdi)
    ja LOCAL(insert_fail)
    movl %esi, %ecx
    cmpq (%rdi), %rcx
    ja LOCAL(insert_fail)
    movq 8(%rdi), %r8
    xorl %eax, %eax
    lock cmpxchgq %rdx, (%r8,%rcx,8)
    jne LOCAL(insert_fail)
    incq %rcx
    cmpq 16(%rdi), %rcx
    jbe LOCAL(insert_success)
    movq %rcx, 16(%rdi)
LOCAL(insert_success):
    xorl %eax, %eax
    jmp LOCAL(insert_epilog)
LOCAL(insert_fail):
    movl $-1, %eax
    jmp LOCAL(insert_epilog)
    .org SYMBOL(quadra_sparse_map_insert_asm)+0x13f, 0x90
LOCAL(insert_epilog):
    addq $64, %rsp
    popq %rbp
    retq

.p2align 4
.globl SYMBOL(quadra_sparse_map_foreach_asm)
SYMBOL(quadra_sparse_map_foreach_asm):
    pushq %rbp
    movq %rsp, %rbp
    subq $32, %rsp
    movq %rdi, -8(%rbp)
    movq %rsi, -16(%rbp)
    movq %rdx, -24(%rbp)
    movq $0, -32(%rbp)
LOCAL(foreach_loop):
    movq -8(%rbp), %rcx
    movq (%rcx), %rax
    cmpq $2147483647, %rax
    ja LOCAL(foreach_epilog)
    incq %rax
    cmpq 16(%rcx), %rax
    cmovaq 16(%rcx), %rax
    movq -32(%rbp), %rdi
    cmpq %rax, %rdi
    jae LOCAL(foreach_epilog)
    movq 8(%rcx), %rdx
    movq (%rdx,%rdi,8), %rsi
    testq %rsi, %rsi
    je LOCAL(foreach_next)
    movq -24(%rbp), %rdx
    callq *-16(%rbp)
LOCAL(foreach_next):
    incq -32(%rbp)
    jmp LOCAL(foreach_loop)
    .org SYMBOL(quadra_sparse_map_foreach_asm)+0x74, 0x90
LOCAL(foreach_epilog):
    addq $32, %rsp
    popq %rbp
    retq
#ifndef __APPLE__
.section .note.GNU-stack,"",@progbits
#endif

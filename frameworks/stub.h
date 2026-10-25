// Darling's sysroot has no SDK headers, so the stubs declare the little they
// need themselves. NSObject comes from libobjc, string literals are
// CoreFoundation constant strings.
typedef struct objc_class *Class;
typedef signed char BOOL;
typedef id (*IMP)(id, SEL, ...);
extern BOOL class_addMethod(Class, SEL, IMP, const char *);
extern Class object_getClass(id);

__attribute__((objc_root_class))
@interface NSObject {
    Class isa;
}
@end

@interface NSString : NSObject
@end

// A stub class only has to exist, but a message it does not implement would
// raise "unrecognized selector" and end the game. STUB_RESOLVERS, placed in
// every stub @implementation, answers any other message with nil / 0 / NO
// (and 0.0 for floating point results), as a class that is missing
// altogether would, where messages go to nil.
__attribute__((naked, used)) static void quadra_stub_nothing(void) {
    __asm__("xorl %eax, %eax\n\t"
            "xorl %edx, %edx\n\t"
            "xorps %xmm0, %xmm0\n\t"
            "xorps %xmm1, %xmm1\n\t"
            "ret");
}

#define STUB_RESOLVERS                                                          \
    +(BOOL)resolveClassMethod:(SEL)selector {                                   \
        class_addMethod(object_getClass((id)self), selector,                    \
                        (IMP)quadra_stub_nothing, "@@:");                     \
        return 1;                                                               \
    }                                                                           \
    +(BOOL)resolveInstanceMethod:(SEL)selector {                                \
        class_addMethod((Class)self, selector, (IMP)quadra_stub_nothing, "@@:"); \
        return 1;                                                               \
    }

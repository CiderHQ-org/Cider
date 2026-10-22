/* Quadra's Metal.framework: shared declarations.
 *
 * Built without SDK headers (Darling's runtime sysroot has none), like the
 * shim: the Foundation and AppKit methods used here are declared below, and
 * Metal's own types keep Metal's layouts and raw values. Objects follow
 * Cocoa's conventions: new/alloc/copy return +1, everything else is
 * autoreleased. Every Metal object holds one handle of the host library
 * (../quadra_metal.h) and releases it in -dealloc. */
#ifndef QUADRA_METAL_FRAMEWORK_H
#define QUADRA_METAL_FRAMEWORK_H

#include "../quadra_metal.h"

typedef signed char BOOL;
#define YES ((BOOL)1)
#define NO ((BOOL)0)
#define nil ((id)0)
typedef unsigned long NSUInteger;
typedef long NSInteger;
typedef struct _NSZone NSZone;
typedef struct { NSUInteger location, length; } NSRange;
typedef double CGFloat;
typedef struct { CGFloat x, y; } CGPoint;
typedef struct { CGFloat width, height; } CGSize;
typedef struct { CGPoint origin; CGSize size; } CGRect;
typedef double CFTimeInterval;

typedef struct { NSUInteger x, y, z; } MTLOrigin;
typedef struct { NSUInteger width, height, depth; } MTLSize;
typedef struct { MTLOrigin origin; MTLSize size; } MTLRegion;
typedef struct { double originX, originY, width, height, znear, zfar; } MTLViewport;
typedef struct { NSUInteger x, y, width, height; } MTLScissorRect;
typedef struct { double red, green, blue, alpha; } MTLClearColor;
typedef struct { NSUInteger size, align; } MTLSizeAndAlign;

typedef void (^QMCommandBufferHandler)(id);
typedef void (^QMDrawableHandler)(id);

@class NSString, NSArray, NSError, NSDictionary, NSMethodSignature, NSInvocation;

__attribute__((objc_root_class))
@interface NSObject {
    Class isa;
}
+ (id)alloc;
+ (id)allocWithZone:(NSZone *)zone;
+ (id)new;
+ (Class)class;
+ (BOOL)instancesRespondToSelector:(SEL)selector;
- (id)init;
- (id)retain;
- (oneway void)release;
- (id)autorelease;
- (void)dealloc;
- (Class)class;
- (id)copy;
- (BOOL)isKindOfClass:(Class)cls;
- (BOOL)respondsToSelector:(SEL)selector;
- (BOOL)conformsToProtocol:(id)protocol;
- (NSMethodSignature *)methodSignatureForSelector:(SEL)selector;
- (void)forwardInvocation:(NSInvocation *)invocation;
- (NSString *)description;
@end

@interface NSString : NSObject
+ (id)stringWithUTF8String:(const char *)text;
- (id)initWithBytes:(const void *)bytes length:(NSUInteger)length encoding:(NSUInteger)encoding;
- (const char *)UTF8String;
- (NSUInteger)length;
- (id)copyWithZone:(NSZone *)zone;
@end

@interface NSArray : NSObject
+ (id)arrayWithObjects:(const id *)objects count:(NSUInteger)count;
- (NSUInteger)count;
- (id)objectAtIndex:(NSUInteger)index;
@end

@interface NSDictionary : NSObject
+ (id)dictionaryWithObject:(id)object forKey:(id)key;
@end

@interface NSError : NSObject
+ (id)errorWithDomain:(NSString *)domain code:(NSInteger)code userInfo:(NSDictionary *)info;
@end

@interface NSMethodSignature : NSObject
+ (NSMethodSignature *)signatureWithObjCTypes:(const char *)types;
- (NSUInteger)methodReturnLength;
- (const char *)methodReturnType;
@end

@interface NSInvocation : NSObject
- (SEL)selector;
- (void)setReturnValue:(void *)value;
- (NSMethodSignature *)methodSignature;
@end

@interface NSThread : NSObject
+ (BOOL)isMainThread;
@end

/* AppKit and QuartzCore, reached through messages only (no link: QuartzCore
 * links Metal). */
@protocol QMViewMethods
- (CGRect)bounds;
- (CGRect)convertRect:(CGRect)rect toView:(id)view;
- (id)window;
- (id)layer;
- (BOOL)isHiddenOrHasHiddenAncestor;
@end
@protocol QMWindowMethods
- (id)platformWindow;
- (CGRect)frame;
- (NSUInteger)styleMask;
- (id)contentView;
@end
@protocol QMLayerMethods
- (CGRect)bounds;
- (CGFloat)contentsScale;
- (id)delegate;
- (id)superlayer;
@end

extern NSString *const NSLocalizedDescriptionKey;
extern void *_Block_copy(const void *block);
extern void _Block_release(const void *block);
extern id objc_getClass(const char *name);
extern SEL sel_registerName(const char *name);
extern const char *sel_getName(SEL selector);
extern const char *class_getName(Class cls);
extern Class object_getClass(id object);
extern BOOL class_addMethod(Class cls, SEL name, void (*imp)(void), const char *types);
extern void (*class_replaceMethod(Class cls, SEL name, void (*imp)(void), const char *types))(void);
extern Class objc_allocateClassPair(Class superclass, const char *name, unsigned long extra);
extern void objc_registerClassPair(Class cls);
extern id class_createInstance(Class cls, unsigned long extra);
extern void *object_getIndexedIvars(id object);
extern id objc_msgSend(id self, SEL selector, ...);
extern id objc_autoreleasePoolPush(void);
extern void objc_autoreleasePoolPop(id pool);

extern char *getenv(const char *name);
extern int snprintf(char *buffer, unsigned long size, const char *format, ...);
extern void *malloc(unsigned long size);
extern void *calloc(unsigned long count, unsigned long size);
extern void *realloc(void *pointer, unsigned long size);
extern void free(void *pointer);
extern void *memcpy(void *destination, const void *source, unsigned long size);
extern void *memset(void *destination, int value, unsigned long size);
extern int memcmp(const void *a, const void *b, unsigned long size);
extern unsigned long strlen(const char *text);
extern int strcmp(const char *a, const char *b);
extern char *strstr(const char *haystack, const char *needle);
extern long write(int fd, const void *buffer, unsigned long count);
extern void *dlsym(void *handle, const char *name);
extern unsigned long long mach_absolute_time(void);
#define QM_RTLD_DEFAULT ((void *)-2)

/* pthread, with Darwin's x86_64 sizes. */
typedef struct { long sig; char opaque[56]; } qm_mutex_t;
typedef struct { long sig; char opaque[40]; } qm_cond_t;
typedef void *qm_thread_t;
#define QM_MUTEX_INIT {0x32AAABA7, {0}}
#define QM_COND_INIT {0x3CB0B1BB, {0}}
extern int pthread_mutex_lock(qm_mutex_t *mutex);
extern int pthread_mutex_unlock(qm_mutex_t *mutex);
extern int pthread_cond_wait(qm_cond_t *cond, qm_mutex_t *mutex);
struct qm_timespec { long tv_sec, tv_nsec; };
extern int pthread_cond_timedwait_relative_np(qm_cond_t *cond, qm_mutex_t *mutex, const struct qm_timespec *relative);
extern qm_thread_t pthread_self(void);
extern int pthread_equal(qm_thread_t left, qm_thread_t right);
extern int pthread_mutex_destroy(qm_mutex_t *mutex);
extern int pthread_cond_destroy(qm_cond_t *cond);
extern int pthread_cond_broadcast(qm_cond_t *cond);
extern int pthread_create(qm_thread_t *thread, const void *attributes, void *(*start)(void *), void *argument);
extern int pthread_detach(qm_thread_t thread);

/* Shared state (QMHost.m). */
extern const qm_api *qm;
int qm_load_host(void);
void qm_log(const char *format, ...) __attribute__((format(printf, 1, 2)));
NSError *qm_error(const char *what);
double qm_now(void);
void qm_install_layer(void);

/* The host handle of a Metal object of this framework (0 for nil or a
 * foreign object). */
void *qm_handle(id object);

@interface QMObject : NSObject {
@public
    void *handle;
    id label;
}
- (NSString *)label;
- (void)setLabel:(NSString *)value;
- (id)device;
@end

/* Classes other files create. */
@interface QMDevice : QMObject
@end
extern QMDevice *qm_device;

@interface QMTexture : QMObject {
@public
    qm_texture_desc info;
    id parent;     /* a view's texture, or a drawable's */
}
+ (id)newWithHandle:(void *)handle owner:(id)owner; /* +1 */
@end

@interface QMBuffer : QMObject {
@public
    void *contents;
    NSUInteger length;
    NSUInteger options;
}
@end

@interface QMDrawable : QMObject {
@public
    id layer;
    QMTexture *texture;
    double presented_time;
    QMDrawableHandler *presented_handlers;
    unsigned presented_count;
    qm_mutex_t lock;
    BOOL presented;
}
- (void)didPresentAt:(double)time;
@end

#endif

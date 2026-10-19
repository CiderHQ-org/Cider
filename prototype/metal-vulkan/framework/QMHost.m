/* The host library, the base class and MTLCreateSystemDefaultDevice. */
#include "qm.h"
#include <stdarg.h>

extern int vsnprintf(char *buffer, unsigned long size, const char *format, va_list arguments);

const qm_api *qm;
QMDevice *qm_device;

void qm_log(const char *format, ...) {
    char line[1024];
    va_list arguments;
    va_start(arguments, format);
    int length = vsnprintf(line, sizeof line - 1, format, arguments);
    va_end(arguments);
    if (length < 0)
        return;
    if (length > (int)sizeof line - 2)
        length = sizeof line - 2;
    line[length++] = '\n';
    write(2, line, length);
}

double qm_now(void) {
    /* Darling's mach timebase is nanoseconds. */
    return (double)mach_absolute_time() / 1e9;
}

NSError *qm_error(const char *what) {
    char text[1200];
    const char *detail = qm ? qm->last_error() : "the Vulkan host library is not loaded";
    snprintf(text, sizeof text, "%s: %s", what, detail && *detail ? detail : "unknown error");
    qm_log("[Quadra Metal] %s", text);
    NSString *message = [NSString stringWithUTF8String:text];
    NSDictionary *info = [NSDictionary dictionaryWithObject:message forKey:NSLocalizedDescriptionKey];
    return [NSError errorWithDomain:[NSString stringWithUTF8String:"MTLLibraryErrorDomain"] code:3 userInfo:info];
}

/* The first symbols of Darling's mldr function table (see mangohud_bridge.c). */
struct qm_elf_calls {
    void *(*open)(const char *, int);
    int (*close)(void *);
    void *(*symbol)(void *, const char *);
};

int qm_load_host(void) {
    static int state; /* 0 untried, 1 loaded, -1 failed */
    static qm_mutex_t lock = QM_MUTEX_INIT;
    pthread_mutex_lock(&lock);
    if (!state) {
        state = -1;
        const char *path = getenv("MACOBLOX_METAL_HOST_LIBRARY");
        struct qm_elf_calls **table = dlsym(QM_RTLD_DEFAULT, "_elfcalls");
        if (!path || !*path) {
            qm_log("[Quadra Metal] MACOBLOX_METAL_HOST_LIBRARY is not set; Metal stays off");
        } else if (!table || !*table) {
            qm_log("[Quadra Metal] Darling's ELF loader is unavailable; Metal stays off");
        } else {
            void *library = (*table)->open(path, 2 /* RTLD_NOW */);
            qm_api_entry entry = library ? (qm_api_entry)(*table)->symbol(library, QM_API_SYMBOL) : 0;
            const qm_api *api = entry ? entry(QM_API_VERSION) : 0;
            if (!library)
                qm_log("[Quadra Metal] could not load %s", path);
            else if (!api || api->size < sizeof(qm_api))
                qm_log("[Quadra Metal] %s is from another version of Quadra", path);
            else {
                qm = api;
                state = 1;
            }
        }
    }
    pthread_mutex_unlock(&lock);
    return state == 1;
}

void *qm_handle(id object) {
    if (!object || ![object isKindOfClass:[QMObject class]])
        return 0;
    return ((QMObject *)object)->handle;
}

@implementation QMObject
- (void)dealloc {
    if (handle && qm)
        qm->release(handle);
    [label release];
    [super dealloc];
}
- (NSString *)label { return label; }
- (void)setLabel:(NSString *)value {
    id old = label;
    label = [value copy];
    [old release];
}
- (id)device { return qm_device; }

/* A selector this framework lacks: logged once, answered with zeros. Real
 * Metal would raise; Roblox keeps going with a nil/zero answer, and the log
 * shows what to add. */
- (NSMethodSignature *)methodSignatureForSelector:(SEL)selector {
    NSMethodSignature *signature = [super methodSignatureForSelector:selector];
    if (signature)
        return signature;
    char text[300];
    snprintf(text, sizeof text, "[Quadra Metal] missing -[%s %s]", class_getName(object_getClass(self)),
             sel_getName(selector));
    if (qm)
        qm->log_once(text);
    else
        qm_log("%s", text);
    return [NSMethodSignature signatureWithObjCTypes:"@@:"];
}
- (void)forwardInvocation:(NSInvocation *)invocation {
    unsigned long long zero[8] = {0};
    if ([[invocation methodSignature] methodReturnLength] <= sizeof zero)
        [invocation setReturnValue:zero];
}
@end

id MTLCreateSystemDefaultDevice(void) {
    static qm_mutex_t lock = QM_MUTEX_INIT;
    pthread_mutex_lock(&lock);
    if (!qm_device && qm_load_host()) {
        void *device = qm->device_create(0);
        if (device) {
            qm_device = [QMDevice new];
            qm_device->handle = device;
            qm_install_layer();
        } else {
            qm_log("[Quadra Metal] %s", qm->last_error());
        }
    }
    pthread_mutex_unlock(&lock);
    return [qm_device retain];
}

NSArray *MTLCopyAllDevices(void) {
    id device = MTLCreateSystemDefaultDevice();
    NSArray *devices = device ? [NSArray arrayWithObjects:&device count:1] : [NSArray arrayWithObjects:0 count:0];
    [device release];
    return [devices retain];
}

NSArray *MTLCopyAllDevicesWithObserver(id *observer, id handler) {
    if (observer)
        *observer = nil;
    return MTLCopyAllDevices();
}

void MTLRemoveDeviceObserver(id observer) {}

NSString *MTLDeviceWasAddedNotification, *MTLDeviceRemovalRequestedNotification, *MTLDeviceWasRemovedNotification;

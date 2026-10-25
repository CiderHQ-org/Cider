/* Darling compatibility for Crashpad xattrs, without discarding their data.
 * Linux requires the user. namespace. Darling's path-based setxattr also
 * fails for valid virtual paths, so resolve through open() and fd operations.
 * Keep other attributes and nonzero position/options on the native path.
 * Covers getxattr, setxattr and removexattr (what RobloxPlayer imports:
 * Crashpad's ReadXattr, WriteXattr and RemoveXattr) and fremovexattr.
 */
extern int dprintf(int, const char *, ...);
extern char *getenv(const char *);
extern int open(const char *, int, ...);
extern int close(int);
extern int *__error(void);
extern void *dlsym(void *, const char *);
extern unsigned long strlen(const char *);
extern int strncmp(const char *, const char *, unsigned long);
extern void *memcpy(void *, const void *, unsigned long);
extern long getxattr(const char *, const char *, void *, unsigned long, unsigned int, int);
extern int setxattr(const char *, const char *, const void *, unsigned long, unsigned int, int);
extern long fgetxattr(int, const char *, void *, unsigned long, unsigned int, int);
extern int fsetxattr(int, const char *, const void *, unsigned long, unsigned int, int);
extern int removexattr(const char *, const char *, int);
extern int fremovexattr(int, const char *, int);
#define RTLD_NEXT ((void *)-1)
#define DARWIN_O_RDONLY 0
#define DARWIN_O_CLOEXEC 0x1000000
#define DARWIN_ENOATTR 93
#define DARWIN_ENODATA 96 /* Linux ENODATA as Darling reports it */
#define INTERPOSE(replacement, original) \
 __attribute__((used,section("__DATA,__interpose"))) \
 static const void *interpose_##original[] = {(const void *)&replacement, (const void *)&original};

static int translated_name(const char *name, char out[256]) {
    if (!name || (strncmp(name, "org.chromium.crashpad.", 22) &&
                  strncmp(name, "com.googlecode.crashpad.", 24))) return 0;
    unsigned long n = strlen(name);
    if (n + 6 > 256) return 0;
    memcpy(out, "user.", 5);
    memcpy(out + 5, name, n + 1);
    return 1;
}
long quadra_getxattr(const char *path, const char *name, void *value,
                      unsigned long size, unsigned int position, int options) {
    char linux_name[256];
    if (!position && !options && translated_name(name, linux_name)) {
        int fd = open(path, DARWIN_O_RDONLY | DARWIN_O_CLOEXEC);
        if (fd < 0) {
            int saved = *__error();
            if (getenv("QUADRA_TRACE_XATTR") && *getenv("QUADRA_TRACE_XATTR"))
                dprintf(2, "[xattr] open failed: %s errno=%d\n", path, saved);
            *__error() = saved;
            return -1;
        }
        long result = fgetxattr(fd, linux_name, value, size, 0, 0);
        int err = *__error();
        close(fd);
        if (getenv("QUADRA_TRACE_XATTR") && *getenv("QUADRA_TRACE_XATTR")) dprintf(2, "[xattr] %s %s result=%ld errno=%d\n", path, name, (long)result, err);
        /* Linux ENODATA becomes Darwin ENODATA; Cocoa expects ENOATTR. */
        *__error() = (result < 0 && err == DARWIN_ENODATA) ? DARWIN_ENOATTR : err;
        return result;
    }
    long (*real_fn)(const char*, const char*, void*, unsigned long, unsigned int, int) =
        dlsym(RTLD_NEXT, "getxattr");
    if (!real_fn) { *__error() = 78; return -1; }
    return real_fn(path, name, value, size, position, options);
}
INTERPOSE(quadra_getxattr, getxattr);

int quadra_setxattr(const char *path, const char *name, const void *value,
                     unsigned long size, unsigned int position, int options) {
    char linux_name[256];
    if (!position && !options && translated_name(name, linux_name)) {
        int fd = open(path, DARWIN_O_RDONLY | DARWIN_O_CLOEXEC);
        if (fd < 0) {
            int saved = *__error();
            if (getenv("QUADRA_TRACE_XATTR") && *getenv("QUADRA_TRACE_XATTR"))
                dprintf(2, "[xattr] open failed: %s errno=%d\n", path, saved);
            *__error() = saved;
            return -1;
        }
        int result = fsetxattr(fd, linux_name, value, size, 0, 0);
        int err = *__error();
        close(fd);
        if (getenv("QUADRA_TRACE_XATTR") && *getenv("QUADRA_TRACE_XATTR")) dprintf(2, "[xattr] %s %s result=%ld errno=%d\n", path, name, (long)result, err);
        *__error() = err;
        return result;
    }
    int (*real_fn)(const char*, const char*, const void*, unsigned long, unsigned int, int) =
        dlsym(RTLD_NEXT, "setxattr");
    if (!real_fn) { *__error() = 78; return -1; }
    return real_fn(path, name, value, size, position, options);
}
INTERPOSE(quadra_setxattr, setxattr);

/* Crashpad's RemoveXattr treats ENOATTR as "no such attribute"; anything
 * else is logged as a database error. */
int quadra_fremovexattr(int fd, const char *name, int options) {
    char linux_name[256];
    if (options || !translated_name(name, linux_name))
        return fremovexattr(fd, name, options);
    int result = fremovexattr(fd, linux_name, 0);
    int err = *__error();
    if (getenv("QUADRA_TRACE_XATTR") && *getenv("QUADRA_TRACE_XATTR"))
        dprintf(2, "[xattr] fd %d remove %s result=%d errno=%d\n", fd, name, result, err);
    *__error() = (result < 0 && err == DARWIN_ENODATA) ? DARWIN_ENOATTR : err;
    return result;
}
INTERPOSE(quadra_fremovexattr, fremovexattr);

int quadra_removexattr(const char *path, const char *name, int options) {
    char linux_name[256];
    if (options || !translated_name(name, linux_name))
        return removexattr(path, name, options);
    int fd = open(path, DARWIN_O_RDONLY | DARWIN_O_CLOEXEC);
    if (fd < 0) {
        int saved = *__error();
        if (getenv("QUADRA_TRACE_XATTR") && *getenv("QUADRA_TRACE_XATTR"))
            dprintf(2, "[xattr] open failed: %s errno=%d\n", path, saved);
        *__error() = saved;
        return -1;
    }
    int result = fremovexattr(fd, linux_name, 0);
    int err = *__error();
    close(fd);
    if (getenv("QUADRA_TRACE_XATTR") && *getenv("QUADRA_TRACE_XATTR"))
        dprintf(2, "[xattr] %s remove %s result=%d errno=%d\n", path, name, result, err);
    *__error() = (result < 0 && err == DARWIN_ENODATA) ? DARWIN_ENOATTR : err;
    return result;
}
INTERPOSE(quadra_removexattr, removexattr);

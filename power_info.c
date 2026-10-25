/* Experimental native Wayland has no macOS powerd service. Avoid synchronous
 * Mach calls to it during startup. An empty inventory is also the IOKit API's
 * documented failure result. X11 retains Darling's power-source path. */
extern int quadra_wayland_enabled(void);
extern const void *CFArrayCreate(const void *, const void **, long, const void *);
__attribute__((weak_import)) extern const void *IOPSCopyPowerSourcesInfo(void);
__attribute__((weak_import)) extern const void *IOPSCopyPowerSourcesByType(int);
#define INTERPOSE(fn, original) \
    __attribute__((used)) static const struct {const void *replacement,*replacee;} \
    interpose_##original __attribute__((section("__DATA,__interpose"))) = \
        {(const void *)&fn,(const void *)&original}
static const void *wayland_power_info(void) {
    return quadra_wayland_enabled() ? CFArrayCreate(0,0,0,0)
                                     : IOPSCopyPowerSourcesInfo();
}
static const void *wayland_power_by_type(int type) {
    return quadra_wayland_enabled() ? CFArrayCreate(0,0,0,0)
                                     : IOPSCopyPowerSourcesByType(type);
}
INTERPOSE(wayland_power_info, IOPSCopyPowerSourcesInfo);
INTERPOSE(wayland_power_by_type, IOPSCopyPowerSourcesByType);

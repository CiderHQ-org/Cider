#ifndef QUADRA_UI_SCALE_H
#define QUADRA_UI_SCALE_H

/* The client's own getSurfaceSettings return contract on x86_64. Keeping
 * this separate from Cocoa backing factors leaves drawable and input pixels
 * unchanged. Unknown method encodings must never use this return ABI. */
typedef struct {
    void *surface;
    float scale;
    int width_mm, height_mm, unused;
    _Bool enabled;
    void *other_surface;
    _Bool other_enabled;
    unsigned int first_flags, second_flags;
} QuadraSurfaceSettings;

#if defined(__x86_64__)
_Static_assert(sizeof(QuadraSurfaceSettings) == 56, "Settings return size");
_Static_assert(__alignof__(QuadraSurfaceSettings) == 8, "Settings return alignment");
_Static_assert(__builtin_offsetof(QuadraSurfaceSettings, scale) == 8, "Settings scale offset");
_Static_assert(__builtin_offsetof(QuadraSurfaceSettings, width_mm) == 12, "Settings width offset");
_Static_assert(__builtin_offsetof(QuadraSurfaceSettings, height_mm) == 16, "Settings height offset");
_Static_assert(__builtin_offsetof(QuadraSurfaceSettings, enabled) == 24, "Settings first bool offset");
_Static_assert(__builtin_offsetof(QuadraSurfaceSettings, other_surface) == 32, "Settings second pointer offset");
_Static_assert(__builtin_offsetof(QuadraSurfaceSettings, other_enabled) == 40, "Settings second bool offset");
_Static_assert(__builtin_offsetof(QuadraSurfaceSettings, first_flags) == 44, "Settings first flags offset");
_Static_assert(__builtin_offsetof(QuadraSurfaceSettings, second_flags) == 48, "Settings second flags offset");
#endif

static inline int quadra_surface_settings_abi_matches(const char *encoding) {
#if defined(__x86_64__)
    const char *expected = "{Settings=^vfiiiB^vBII}16@0:8";
    if (!encoding) return 0;
    while (*expected && *encoding == *expected) { ++encoding; ++expected; }
    return *expected == 0 && *encoding == 0;
#else
    (void)encoding;
    return 0;
#endif
}

/* -1: invalid input, preserved; 0: default scale, preserved; 1: transformed.
 * Work in double so a finite float product can be checked before narrowing.
 * No pointer, size, flag, padding or original invalid-scale byte is changed. */
static inline int quadra_surface_settings_scale(QuadraSurfaceSettings *settings,
                                                  double requested) {
    if (!__builtin_isfinite(requested) || requested < 1.0 || requested > 4.0)
        return -1;
    if (requested == 1.0) return 0;
    float before = settings->scale;
    if (!__builtin_isfinite(before) || before <= 0.0f) return -1;
    double after = (double)before * requested;
    if (!__builtin_isfinite(after) || after > __FLT_MAX__) return -1;
    settings->scale = (float)after;
    return 1;
}
#endif

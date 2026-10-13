#ifndef MACOBLOX_MATH_COMPAT_H
#define MACOBLOX_MATH_COMPAT_H

extern double pow(double, double);
extern double __exp10(double);
extern float __exp10f(float);
extern float sinf(float), cosf(float);
extern double sin(double), cos(double);
struct MacOBloxFloat2 { float sine, cosine; };
struct MacOBloxDouble2 { double sine, cosine; };
extern struct MacOBloxFloat2 __sincosf_stret(float);
extern struct MacOBloxDouble2 __sincos_stret(double);
extern struct MacOBloxFloat2 __sincospif_stret(float);
extern struct MacOBloxDouble2 __sincospi_stret(double);

/* Older Darling builds let Clang turn pow(10, x) inside __exp10 into a
 * tail-call to __exp10 itself. Roblox's audio setup then spins forever.
 * A volatile function pointer keeps this call indirect even with newer
 * Darwin-target Clang and LTO, preventing the same rewrite in our shim.
 * Keep the existing float wrapper's double calculation and final rounding. */
static double (*volatile macoblox_exp10_power)(double, double) = pow;

static double macoblox_exp10(double value) {
    return macoblox_exp10_power(10.0, value);
}

static float macoblox_exp10f(float value) {
    return (float)macoblox_exp10_power(10.0, (double)value);
}

/* The older 4312 runtime also compiles sinf/cosf pairs into calls to the
 * sincos wrapper being defined. Both volatile calls are necessary: Clang
 * otherwise combines the pair back into the same recursive symbol. */
static float (*volatile macoblox_sine_float)(float) = sinf;
static float (*volatile macoblox_cosine_float)(float) = cosf;
static double (*volatile macoblox_sine)(double) = sin;
static double (*volatile macoblox_cosine)(double) = cos;
static struct MacOBloxFloat2 macoblox_sincosf(float value) {
    struct MacOBloxFloat2 result = {macoblox_sine_float(value), macoblox_cosine_float(value)};
    return result;
}
static struct MacOBloxDouble2 macoblox_sincos(double value) {
    struct MacOBloxDouble2 result = {macoblox_sine(value), macoblox_cosine(value)};
    return result;
}
static struct MacOBloxFloat2 macoblox_sincospif(float value) {
    return macoblox_sincosf((float)((double)value * 3.14159265358979323846264338327950288));
}
static struct MacOBloxDouble2 macoblox_sincospi(double value) {
    return macoblox_sincos(value * 3.14159265358979323846264338327950288);
}

#endif

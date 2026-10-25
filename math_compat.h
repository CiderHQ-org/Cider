#ifndef QUADRA_MATH_COMPAT_H
#define QUADRA_MATH_COMPAT_H

extern double pow(double, double);
extern double __exp10(double);
extern float __exp10f(float);
extern float sinf(float), cosf(float);
extern double sin(double), cos(double);
struct QuadraFloat2 { float sine, cosine; };
struct QuadraDouble2 { double sine, cosine; };
extern struct QuadraFloat2 __sincosf_stret(float);
extern struct QuadraDouble2 __sincos_stret(double);
extern struct QuadraFloat2 __sincospif_stret(float);
extern struct QuadraDouble2 __sincospi_stret(double);

/* Older Darling builds let Clang turn pow(10, x) inside __exp10 into a
 * tail-call to __exp10 itself. Roblox's audio setup then spins forever.
 * A volatile function pointer keeps this call indirect even with newer
 * Darwin-target Clang and LTO, preventing the same rewrite in our shim.
 * Keep the existing float wrapper's double calculation and final rounding. */
static double (*volatile quadra_exp10_power)(double, double) = pow;

static double quadra_exp10(double value) {
    return quadra_exp10_power(10.0, value);
}

static float quadra_exp10f(float value) {
    return (float)quadra_exp10_power(10.0, (double)value);
}

/* The older 4312 runtime also compiles sinf/cosf pairs into calls to the
 * sincos wrapper being defined. Both volatile calls are necessary: Clang
 * otherwise combines the pair back into the same recursive symbol. */
static float (*volatile quadra_sine_float)(float) = sinf;
static float (*volatile quadra_cosine_float)(float) = cosf;
static double (*volatile quadra_sine)(double) = sin;
static double (*volatile quadra_cosine)(double) = cos;
static struct QuadraFloat2 quadra_sincosf(float value) {
    struct QuadraFloat2 result = {quadra_sine_float(value), quadra_cosine_float(value)};
    return result;
}
static struct QuadraDouble2 quadra_sincos(double value) {
    struct QuadraDouble2 result = {quadra_sine(value), quadra_cosine(value)};
    return result;
}
static struct QuadraFloat2 quadra_sincospif(float value) {
    return quadra_sincosf((float)((double)value * 3.14159265358979323846264338327950288));
}
static struct QuadraDouble2 quadra_sincospi(double value) {
    return quadra_sincos(value * 3.14159265358979323846264338327950288);
}

#endif

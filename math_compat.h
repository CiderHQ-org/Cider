#ifndef MACOBLOX_MATH_COMPAT_H
#define MACOBLOX_MATH_COMPAT_H

extern double pow(double, double);
extern double __exp10(double);
extern float __exp10f(float);

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

#endif

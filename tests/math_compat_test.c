#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <unistd.h>

#ifdef __APPLE__
/* In Darling this tests actual dynamic imports, including dyld interposing. */
extern double __exp10(double);
extern float __exp10f(float);
#define EXP10 __exp10
#define EXP10F __exp10f
#define SINCOSF __sincosf_stret
#define SINCOS __sincos_stret
#define SINCOSPIF __sincospif_stret
#define SINCOSPI __sincospi_stret
#define FloatPair struct __float2
#define DoublePair struct __double2
#define PAIR_SINE __sinval
#define PAIR_COSINE __cosval
#else
#include "../math_compat.h"
#define EXP10 quadra_exp10
#define EXP10F quadra_exp10f
#define SINCOSF quadra_sincosf
#define SINCOS quadra_sincos
#define SINCOSPIF quadra_sincospif
#define SINCOSPI quadra_sincospi
#define FloatPair struct QuadraFloat2
#define DoublePair struct QuadraDouble2
#define PAIR_SINE sine
#define PAIR_COSINE cosine
#endif

int main(void) {
    alarm(10);
    const double inputs[] = {-3.0, -1.0, -0.0, 1.0, 2.0, 3.0};
    const double expected[] = {0.001, 0.1, 1.0, 10.0, 100.0, 1000.0};
    for (unsigned i = 0; i < sizeof(inputs) / sizeof(inputs[0]); i++) {
        volatile double value = inputs[i];
        volatile float small = (float)inputs[i];
        double result = EXP10(value);
        float rounded = EXP10F(small);
        assert(fabs(result - expected[i]) <= expected[i] * 1e-14);
        assert(fabs((double)rounded - expected[i]) <= expected[i] * 1e-6);
    }
    volatile double huge = 309.0, tiny = -400.0, infinity = INFINITY, nan_value = NAN;
    volatile float huge_float = 50.0f, tiny_float = -50.0f, infinity_float = INFINITY, nan_float = NAN;
    assert(isinf(EXP10(huge)) && isinf(EXP10(infinity)));
    assert(EXP10(tiny) == 0.0 && EXP10(-infinity) == 0.0);
    assert(isnan(EXP10(nan_value)));
    assert(isinf(EXP10F(huge_float)) && isinf(EXP10F(infinity_float)));
    assert(EXP10F(tiny_float) == 0.0f && EXP10F(-infinity_float) == 0.0f);
    assert(isnan(EXP10F(nan_float)));
    for (unsigned i = 0; i < sizeof(inputs) / sizeof(inputs[0]); i++) {
        volatile double angle = inputs[i];
        volatile float small_angle = (float)angle;
        FloatPair fp = SINCOSF(small_angle);
        DoublePair dp = SINCOS(angle);
        assert(fabsf(fp.PAIR_SINE - sinf(small_angle)) < 1e-6f);
        assert(fabsf(fp.PAIR_COSINE - cosf(small_angle)) < 1e-6f);
        assert(fabs(dp.PAIR_SINE - sin(angle)) < 1e-14);
        assert(fabs(dp.PAIR_COSINE - cos(angle)) < 1e-14);
    }
    volatile float quarter = 0.25f;
    volatile double half = 0.5;
    FloatPair fp = SINCOSPIF(quarter);
    DoublePair dp = SINCOSPI(half);
    assert(fabsf(fp.PAIR_SINE - sqrtf(0.5f)) < 1e-6f);
    assert(fabsf(fp.PAIR_COSINE - sqrtf(0.5f)) < 1e-6f);
    assert(fabs(dp.PAIR_SINE - 1.0) < 1e-14 && fabs(dp.PAIR_COSINE) < 1e-14);
    fp = SINCOSF(nan_float); dp = SINCOS(infinity);
    assert(isnan(fp.PAIR_SINE) && isnan(fp.PAIR_COSINE));
    assert(isnan(dp.PAIR_SINE) && isnan(dp.PAIR_COSINE));
    puts("PASS: exp10/exp10f finite values, float rounding, overflow, underflow, infinity and NaN");
    puts("PASS: float/double sincos ABI, pi wrappers, finite angles and non-finite inputs");
    fflush(stdout);
    return 0;
}

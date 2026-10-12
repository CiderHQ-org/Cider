#include <assert.h>
#include <math.h>
#include <stdio.h>

#ifdef __APPLE__
/* In Darling this tests actual dynamic imports, including dyld interposing. */
extern double __exp10(double);
extern float __exp10f(float);
#define EXP10 __exp10
#define EXP10F __exp10f
#else
#include "../math_compat.h"
#define EXP10 macoblox_exp10
#define EXP10F macoblox_exp10f
#endif

int main(void) {
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
    puts("PASS: exp10/exp10f finite values, float rounding, overflow, underflow, infinity and NaN");
    return 0;
}

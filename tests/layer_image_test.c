#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../layer_image.c"

static unsigned long width = 2, height = 2, stride = 12;
static unsigned int info = 2 | 0x2000;
static unsigned long bits = 32;
static unsigned char image_bytes[24], copied_pixels[24];
static int provider_present = 1, data_present = 1, copy_calls, releases, draws;
static long data_length = 24;
static unsigned int uploaded_format;
static int uploaded_width, uploaded_height, unpack[4] = {8, 9, 10, 11};
static unsigned int unpack_buffer = 7;
static void *context_pixels;
unsigned long CGImageGetWidth(void *image) { assert(image); return width; }
unsigned long CGImageGetHeight(void *image) { assert(image); return height; }
unsigned long CGImageGetBitsPerComponent(void *image) { assert(image); return 8; }
unsigned long CGImageGetBitsPerPixel(void *image) { assert(image); return bits; }
unsigned long CGImageGetBytesPerRow(void *image) { assert(image); return stride; }
unsigned int CGImageGetBitmapInfo(void *image) { assert(image); return info; }
void *CGImageGetDataProvider(void *image) { assert(image); return provider_present ? (void *)2 : 0; }
void *CGDataProviderCopyData(void *provider) { assert(provider); ++copy_calls; return data_present ? (void *)3 : 0; }
const unsigned char *CFDataGetBytePtr(void *data) { assert(data); return image_bytes; }
long CFDataGetLength(void *data) { assert(data); return data_length; }
void CFRelease(const void *data) { assert(data); ++releases; }
void *CGColorSpaceCreateDeviceRGB(void) { return (void *)4; }
void CGColorSpaceRelease(void *space) { assert(space == (void *)4); }
void *CGBitmapContextCreate(void *pixels, unsigned long w, unsigned long h,
                           unsigned long bpc, unsigned long row,
                           void *space, unsigned int bitmap_info) {
    assert(w == width && h == height && bpc == 8 && row == w * 4);
    assert(space == (void *)4 && bitmap_info == (2 | 0x2000));
    context_pixels = pixels;
    return (void *)5;
}
void CGContextDrawImage(void *context, LayerImageRect bounds, void *image) {
    assert(context == (void *)5 && image && bounds.size.width == width);
    ++draws;
    memset(context_pixels, 0x44, width * height * 4);
}
void CGContextRelease(void *context) { assert(context == (void *)5); }
static int unpack_index(unsigned int name) {
    switch(name) { case 0x0CF5: return 0; case 0x0CF2: return 1;
                   case 0x0CF3: return 2; case 0x0CF4: return 3; }
    assert(0); return -1;
}
void glGetIntegerv(unsigned int name, int *value) {
    *value = name == 0x88EF ? (int)unpack_buffer : unpack[unpack_index(name)];
}
void glBindBuffer(unsigned int name, unsigned int buffer) {
    assert(name == 0x88EC); unpack_buffer = buffer;
}
void glPixelStorei(unsigned int name, int value) { unpack[unpack_index(name)] = value; }
void glTexImage2D(unsigned int target, int level, int internal, int w, int h, int border,
                  unsigned int format, unsigned int type, const void *pixels) {
    assert(target == 0x0DE1 && level == 0 && internal == 0x8058 && border == 0);
    assert(type == 0x1401 && !unpack_buffer && unpack[0] == 1 && !unpack[2] && !unpack[3]);
    assert(unpack[1] >= w);
    uploaded_width = w; uploaded_height = h; uploaded_format = format;
    assert(w * h * 4 <= (int)sizeof copied_pixels);
    for(int y = 0; y < h; ++y)
        memcpy(copied_pixels + y * w * 4, (const char *)pixels + y * unpack[1] * 4, w * 4);
}
static void check_restored(void) {
    assert(unpack_buffer == 7 && unpack[0] == 8 && unpack[1] == 9 &&
           unpack[2] == 10 && unpack[3] == 11);
}
int main(void) {
    quadra_CATexImage2DCGImage(0);
    assert(uploaded_width == 1 && uploaded_height == 1 && !copy_calls);
    assert(!memcmp(copied_pixels, "\0\0\0\0", 4));
    check_restored();
    for(int i = 0; i < 24; ++i) image_bytes[i] = (unsigned char)i;
    quadra_CATexImage2DCGImage((void *)1);
    assert(copy_calls == 1 && releases == 1 && !draws && uploaded_format == 0x80E1);
    assert(!memcmp(copied_pixels, image_bytes, 8));
    assert(!memcmp(copied_pixels + 8, image_bytes + 12, 8));
    check_restored();
    data_length = 19;
    quadra_CATexImage2DCGImage((void *)1);
    assert(releases == 2 && !draws && uploaded_width == 1);
    check_restored();
    provider_present = 0;
    quadra_CATexImage2DCGImage((void *)1);
    assert(copy_calls == 2 && draws == 1 && uploaded_width == 2);
    check_restored();
    provider_present = 1; bits = 8;
    quadra_CATexImage2DCGImage((void *)1);
    assert(copy_calls == 2 && draws == 2);
    check_restored();
    width = ~0UL;
    quadra_CATexImage2DCGImage((void *)1);
    assert(uploaded_width == 1 && draws == 2);
    check_restored();
    puts("layer image upload tests passed");
}

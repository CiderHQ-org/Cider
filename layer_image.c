/* Darling's CARenderer uploads every layer's contents, including empty
 * container layers. Its uploader dereferences a NULL data provider and leaks
 * copied image data. Keep empty layers transparent and upload complete rows. */
typedef struct { double x, y; } LayerImagePoint;
typedef struct { double width, height; } LayerImageSize;
typedef struct { LayerImagePoint origin; LayerImageSize size; } LayerImageRect;

extern unsigned long CGImageGetWidth(void *);
extern unsigned long CGImageGetHeight(void *);
extern unsigned long CGImageGetBitsPerComponent(void *);
extern unsigned long CGImageGetBitsPerPixel(void *);
extern unsigned long CGImageGetBytesPerRow(void *);
extern unsigned int CGImageGetBitmapInfo(void *);
extern void *CGImageGetDataProvider(void *);
extern void *CGDataProviderCopyData(void *);
extern const unsigned char *CFDataGetBytePtr(void *);
extern long CFDataGetLength(void *);
extern void CFRelease(const void *);
extern void *CGColorSpaceCreateDeviceRGB(void);
extern void CGColorSpaceRelease(void *);
extern void *CGBitmapContextCreate(void *, unsigned long, unsigned long,
                                 unsigned long, unsigned long, void *, unsigned int);
extern void CGContextDrawImage(void *, LayerImageRect, void *);
extern void CGContextRelease(void *);
extern void *calloc(unsigned long, unsigned long);
extern void free(void *);
extern void glGetIntegerv(unsigned int, int *);
extern void glBindBuffer(unsigned int, unsigned int);
extern void glPixelStorei(unsigned int, int);
extern void glTexImage2D(unsigned int, int, int, int, int, int,
                         unsigned int, unsigned int, const void *);

static void upload_layer_pixels(unsigned long width, unsigned long height,
                                unsigned long stride, unsigned int format,
                                const void *pixels) {
    static const unsigned int unpack_names[] = {
        0x0CF5, /* GL_UNPACK_ALIGNMENT */
        0x0CF2, /* GL_UNPACK_ROW_LENGTH */
        0x0CF3, /* GL_UNPACK_SKIP_ROWS */
        0x0CF4, /* GL_UNPACK_SKIP_PIXELS */
    };
    int saved[4], buffer = 0;
    glGetIntegerv(0x88EF /* GL_PIXEL_UNPACK_BUFFER_BINDING */, &buffer);
    for (int i = 0; i < 4; ++i)
        glGetIntegerv(unpack_names[i], &saved[i]);
    if (buffer)
        glBindBuffer(0x88EC /* GL_PIXEL_UNPACK_BUFFER */, 0);
    glPixelStorei(unpack_names[0], 1);
    glPixelStorei(unpack_names[1], (int)(stride / 4));
    glPixelStorei(unpack_names[2], 0);
    glPixelStorei(unpack_names[3], 0);
    glTexImage2D(0x0DE1 /* GL_TEXTURE_2D */, 0, 0x8058 /* GL_RGBA8 */,
                 (int)width, (int)height, 0, format, 0x1401 /* GL_UNSIGNED_BYTE */, pixels);
    for (int i = 0; i < 4; ++i)
        glPixelStorei(unpack_names[i], saved[i]);
    if (buffer)
        glBindBuffer(0x88EC, (unsigned int)buffer);
}

static void upload_empty_layer(void) {
    static const unsigned int transparent;
    upload_layer_pixels(1, 1, 4, 0x1908 /* GL_RGBA */, &transparent);
}

void quadra_CATexImage2DCGImage(void *image) {
    if (!image) {
        upload_empty_layer();
        return;
    }
    unsigned long width = CGImageGetWidth(image), height = CGImageGetHeight(image);
    if (!width || !height || width > 0x7FFFFFFFUL || height > 0x7FFFFFFFUL ||
        width > (~0UL / 4) / height) {
        upload_empty_layer();
        return;
    }

    unsigned int info = CGImageGetBitmapInfo(image);
    unsigned int alpha = info & 0x1F, byte_order = info & 0x7000;
    unsigned long stride = CGImageGetBytesPerRow(image);
    unsigned int direct_format = 0;
    if (CGImageGetBitsPerComponent(image) == 8 && CGImageGetBitsPerPixel(image) == 32 &&
        stride >= width * 4 && !(stride % 4) && stride / 4 <= 0x7FFFFFFFUL &&
        stride <= ~0UL / height) {
        if (alpha == 2 /* PremultipliedFirst */ && byte_order == 0x2000 /* 32Little */)
            direct_format = 0x80E1; /* GL_BGRA */
        else if (alpha == 1 /* PremultipliedLast */ && byte_order == 0x4000 /* 32Big */)
            direct_format = 0x1908; /* GL_RGBA */
    }
    void *provider = direct_format ? CGImageGetDataProvider(image) : 0;
    void *data = provider ? CGDataProviderCopyData(provider) : 0;
    if (data) {
        const unsigned char *bytes = CFDataGetBytePtr(data);
        long length = CFDataGetLength(data);
        unsigned long required = stride * (height - 1) + width * 4;
        if (bytes && length >= 0 && (unsigned long)length >= required) {
            upload_layer_pixels(width, height, stride, direct_format, bytes);
            CFRelease(data);
            return;
        }
        CFRelease(data);
        upload_empty_layer();
        return;
    }

    /* Decoded images without a provider, grayscale images and other channel
     * layouts are valid CGImages. Draw them into a known premultiplied layout. */
    unsigned char *pixels = (unsigned char *)calloc(height, width * 4);
    void *color_space = pixels ? CGColorSpaceCreateDeviceRGB() : 0;
    void *bitmap = color_space
        ? CGBitmapContextCreate(pixels, width, height, 8, width * 4,
                                color_space, 2U | 0x2000U) : 0;
    if (color_space)
        CGColorSpaceRelease(color_space);
    if (bitmap) {
        LayerImageRect bounds = {{0, 0}, {(double)width, (double)height}};
        CGContextDrawImage(bitmap, bounds, image);
        upload_layer_pixels(width, height, width * 4, 0x80E1, pixels);
        CGContextRelease(bitmap);
    } else {
        upload_empty_layer();
    }
    free(pixels);
}

#ifdef __APPLE__
extern void CATexImage2DCGImage(void *);
__attribute__((used)) static struct { const void *replacement; const void *replacee; }
    layer_image_interpose __attribute__((section("__DATA,__interpose"))) = {
        (const void *)&quadra_CATexImage2DCGImage, (const void *)&CATexImage2DCGImage
    };
#endif

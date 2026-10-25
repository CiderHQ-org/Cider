/* Optional Darling integration regression on an X11 GPU display:
 * clang -target x86_64-apple-darwin -fuse-ld=lld -isysroot /usr/libexec/darling \
 *   -mmacosx-version-min=11.0 tests/darling_gl_test.m -framework AppKit \
 *   -framework Foundation -framework OpenGL -o /tmp/quadra-darling-gl-test
 * DPREFIX=/tmp/quadra-test-prefix EGL_PLATFORM=x11 darling shell /bin/bash -c \
 *   'export DYLD_FORCE_FLAT_NAMESPACE=1 DYLD_INSERT_LIBRARIES=/Volumes/SystemRoot/PATH/TO/build/libQuadraShims.dylib; exec /Volumes/SystemRoot/tmp/quadra-darling-gl-test'
 * For Zink, also export renderer_environment("vulkan") variables in the guest.
 * Tests context creation and shaders, not gameplay or presentation.
 * Darling's sysroot has no AppKit/OpenGL headers, as for the shim itself. */
extern int printf(const char *, ...);
extern int fflush(void *);
extern void *dlopen(const char *, int);
extern void *dlsym(void *, const char *);
extern char *strstr(const char *, const char *);
__attribute__((objc_root_class)) @interface NSObject
+ (id)alloc;
- (id)init;
@end
@interface NSAutoreleasePool : NSObject @end
@interface NSApplication : NSObject
+ (id)sharedApplication;
@end
@interface NSOpenGLPixelFormat : NSObject
- (id)initWithAttributes:(const unsigned int *)attributes;
@end
@interface NSOpenGLContext : NSObject
- (id)initWithFormat:(id)format shareContext:(id)other;
- (void)makeCurrentContext;
@end
extern unsigned int glCreateShader(unsigned int);
extern void glCompileShader(unsigned int);
extern void glGetShaderiv(unsigned int,unsigned int,int *);
extern void glGetShaderSource(unsigned int,int,int *,char *);
extern void glGetShaderInfoLog(unsigned int,int,int *,char *);
extern const unsigned char *glGetString(unsigned int);
int main(void) {
    [[NSAutoreleasePool alloc] init];
    [NSApplication sharedApplication];
    unsigned int attrs[]={99,0x3200,8,24,0};
    id format=[[NSOpenGLPixelFormat alloc] initWithAttributes:attrs];
    id context=[[NSOpenGLContext alloc] initWithFormat:format shareContext:0];
    [context makeCurrentContext];
    printf("Renderer: %s; GL: %s\n",glGetString(0x1F01),glGetString(0x1F02));
    /* Roblox resolves this function dynamically, which must reach the shim. */
    void *library=dlopen("/System/Library/Frameworks/OpenGL.framework/OpenGL",2);
    void (*source_fn)(unsigned int,int,const char *const *,const int *)=dlsym(library,"glShaderSource");
    if (!source_fn || !context) return 1;
    const char *input="#version 150\nin vec4 POSITION; uniform vec4 CB12[256]; void main(){gl_Position=CB12[((uint(POSITION.w) >> 8u) & 255u) * 1 + 0];}";
    unsigned int shader=glCreateShader(0x8B31);
    source_fn(shader,1,&input,0);
    glCompileShader(shader);
    int ok=0;glGetShaderiv(shader,0x8B81,&ok);
    char received[1024]={0},error[1024]={0};
    glGetShaderSource(shader,sizeof(received),0,received);
    glGetShaderInfoLog(shader,sizeof(error),0,error);
    int fixed=strstr(received,"CB12[((uint(POSITION.w) >> 8u) & 255u)]")!=0;
    printf("Shader status=%d injected fix=%d %s\n",ok,fixed,error);
    /* Fast shim exit bypasses stdio flushing. */
    fflush(0);
    return !(ok && fixed && context);
}

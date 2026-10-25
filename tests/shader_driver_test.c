/* Optional real-driver regression, against an X11 EGL display:
 * clang -O2 tests/shader_driver_test.c shader_compat.c -lEGL -lGL -o /tmp/shader-driver-test
 * EGL_PLATFORM=x11 /tmp/shader-driver-test [optional shader files...]
 */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <EGL/egl.h>
#define GL_GLEXT_PROTOTYPES
#include <GL/gl.h>
#include <GL/glext.h>
extern char *quadra_fix_shader_indices(char *, unsigned long *);

static int compile(const char *source) {
    GLuint shader = glCreateShader(strstr(source, "gl_Position") ? GL_VERTEX_SHADER : GL_FRAGMENT_SHADER);
    glShaderSource(shader, 1, &source, 0);
    glCompileShader(shader);
    GLint ok;
    glGetShaderiv(shader, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[8192];
        glGetShaderInfoLog(shader, sizeof(log), 0, log);
        fprintf(stderr, "%s\n", log);
    }
    glDeleteShader(shader);
    return ok;
}
int main(int argc, char **argv) {
    EGLDisplay display = eglGetDisplay(EGL_DEFAULT_DISPLAY);
    assert(eglInitialize(display, 0, 0));
    assert(eglBindAPI(EGL_OPENGL_API));
    EGLint attrs[] = {EGL_SURFACE_TYPE, EGL_PBUFFER_BIT, EGL_RENDERABLE_TYPE, EGL_OPENGL_BIT, EGL_NONE};
    EGLConfig config;
    EGLint count;
    assert(eglChooseConfig(display, attrs, &config, 1, &count) && count);
    EGLint size[] = {EGL_WIDTH, 16, EGL_HEIGHT, 16, EGL_NONE};
    EGLSurface surface = eglCreatePbufferSurface(display, config, size);
    EGLint context_attrs[] = {EGL_CONTEXT_MAJOR_VERSION, 4, EGL_CONTEXT_MINOR_VERSION, 1,
                             EGL_CONTEXT_OPENGL_PROFILE_MASK, EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT, EGL_NONE};
    EGLContext context = eglCreateContext(display, config, EGL_NO_CONTEXT, context_attrs);
    assert(surface && context && eglMakeCurrent(display, surface, surface, context));
    const char *version = (const char *)glGetString(GL_VERSION);
        /* Reduce the actual CB12 index arithmetic, rather than testing an
     * unrelated assignment whose destination happens to be signed. */
    const char *input = "#version 150\nin vec4 POSITION; uniform vec4 CB12[256]; void main(){gl_Position=CB12[((uint(POSITION.w) >> 8u) & 255u) * 1 + 0];}";
    char *source = strdup(input);
    unsigned long length = strlen(source);
    source = quadra_fix_shader_indices(source, &length);
    assert(compile(source));
    free(source);
    assert(compile("#version 150\nin vec4 POSITION; void main(){uint i=((uint(POSITION.w) >> 8u) & 255u); gl_Position=vec4(float(i));}"));
    source = strdup("#version 150\nuniform vec4 CB3[64]; in vec4 NORMAL; void main(){uint _500=uint(NORMAL.w); gl_Position=CB3[(_500 & 63u) * 1 + 0];}");
    length = strlen(source);
    source = quadra_fix_shader_indices(source, &length);
    assert(compile(source));
    free(source);
    for (int index = 1; index < argc; index++) {
        FILE *file = fopen(argv[index], "rb");
        assert(file && !fseek(file, 0, SEEK_END));
        long size = ftell(file);
        assert(size > 0 && !fseek(file, 0, SEEK_SET));
        source = malloc(size + 1);
        assert(source && fread(source, 1, size, file) == (unsigned long)size);
        fclose(file);
        source[size] = 0;
        length = size;
        source = quadra_fix_shader_indices(source, &length);
        if (!compile(source)) {
            fprintf(stderr, "FAIL: corrected shader %s\n", argv[index]);
            return 1;
        }
        free(source);
    }
    if (argc > 1) printf("PASS: %d supplied shaders\n", argc - 1);
    printf("PASS: GLSL 1.50 compatibility on %s\n", version);
    eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
    eglDestroyContext(display, context);
    eglDestroySurface(display, surface);
    eglTerminate(display);
}

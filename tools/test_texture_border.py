"""Render production GLES border helpers into an isolated ANGLE pbuffer.

No game data or visible window is used. Requires the local macOS ANGLE build
dependencies and access to Metal, like the native renderer smoke tests.
"""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / "port/linux/src"
ANGLE = ROOT / "build/macos/angle/dist"

HARNESS = r'''
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>
#include <assert.h>
#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define HALO_ANDROID 1
#define HALO_GLES 1
#define SAMPLE_BIAS ", texture_lod_bias[%d]"
typedef unsigned DWORD;
enum { D3DTSS_MINFILTER, D3DTSS_MAGFILTER, D3DTSS_ADDRESSU, D3DTSS_ADDRESSV, D3DTSS_MAXMIPLEVEL };
enum { D3DTEXF_POINT = 1, D3DTEXF_LINEAR, D3DTEXF_ANISOTROPIC };
enum { D3DTADDRESS_WRAP = 1, D3DTADDRESS_CLAMP = 3, D3DTADDRESS_BORDER = 4 };
enum { _xgpu_sampler_none, _xgpu_sampler_2d, _xgpu_sampler_3d, _xgpu_sampler_cube };
static struct { int border_clamp; } xgpu_capabilities;
static DWORD D3D__TextureState[4][5];
struct xgpu_texture_description { unsigned long levels; int hires; };
struct nv2a_pixel_shader_key {
    unsigned char sampler_type[4], border_axes[4], border_filter[4];
};
struct xgpu_text { char *buffer; unsigned long length, capacity; };
static void xgpu_text_append(struct xgpu_text *text, const char *format, ...) {
    va_list args; va_start(args, format); va_list copy; va_copy(copy, args);
    int size = vsnprintf(NULL, 0, format, copy); va_end(copy); assert(size >= 0);
    text->buffer = realloc(text->buffer, text->length + size + 1); assert(text->buffer);
    vsnprintf(text->buffer + text->length, size + 1, format, args); va_end(args);
    text->length += size;
}
/* KEY_CODE */
/* SHADER_CODE */

static void check_scope(void) {
    struct nv2a_pixel_shader_key key = {0};
    struct xgpu_texture_description description = {1, 0};
    D3D__TextureState[0][D3DTSS_MINFILTER] = D3DTEXF_LINEAR;
    D3D__TextureState[0][D3DTSS_MAGFILTER] = D3DTEXF_POINT;
    D3D__TextureState[0][D3DTSS_ADDRESSU] = D3DTADDRESS_BORDER;
    D3D__TextureState[0][D3DTSS_ADDRESSV] = D3DTADDRESS_WRAP;
    texture_border_key(&key, 0, GL_TEXTURE_2D, &description);
    assert(key.border_axes[0] == 1 && key.border_filter[0] == 1);
    D3D__TextureState[0][D3DTSS_ADDRESSU] = D3DTADDRESS_WRAP;
    D3D__TextureState[0][D3DTSS_ADDRESSV] = D3DTADDRESS_BORDER;
    texture_border_key(&key, 0, GL_TEXTURE_2D, &description);
    assert(key.border_axes[0] == 2);
    for (unsigned mode = 0; mode < 5; mode++) {
        memset(&key, 0, sizeof(key));
        xgpu_capabilities.border_clamp = mode == 0;
        description.levels = mode == 1 ? 3 : 1;
        D3D__TextureState[0][D3DTSS_MINFILTER] = mode == 2 ? D3DTEXF_ANISOTROPIC : D3DTEXF_LINEAR;
        GLenum target = mode == 3 ? GL_TEXTURE_3D : mode == 4 ? GL_TEXTURE_CUBE_MAP : GL_TEXTURE_2D;
        texture_border_key(&key, 0, target, &description);
        assert(!key.border_axes[0] && !key.border_filter[0]);
    }
    xgpu_capabilities.border_clamp = 0;
    D3D__TextureState[0][D3DTSS_MAXMIPLEVEL] = 2;
    texture_border_key(&key, 0, GL_TEXTURE_2D, &description);
    assert(key.border_filter[0] == 3);
    D3D__TextureState[0][D3DTSS_MAXMIPLEVEL] = 0;
}

static GLuint shader(GLenum kind, const char *source) {
    GLuint result = glCreateShader(kind); glShaderSource(result, 1, &source, NULL); glCompileShader(result);
    GLint ok; glGetShaderiv(result, GL_COMPILE_STATUS, &ok);
    if (!ok) { char log[8192]; glGetShaderInfoLog(result, sizeof(log), NULL, log); fprintf(stderr, "%s\n%s", log, source); exit(1); }
    return result;
}
static GLuint program(unsigned axes, unsigned filtering) {
    struct nv2a_pixel_shader_key key = {0}; key.sampler_type[0] = _xgpu_sampler_2d;
    key.border_axes[0] = axes; key.border_filter[0] = filtering;
    struct xgpu_text text = {0};
    xgpu_text_append(&text, "#version 300 es\nprecision highp float;\nprecision highp sampler2D;\n"
        "uniform sampler2D tex0;\nuniform vec4 texture_border_color[4], texture_scale[4];\n"
        "uniform vec4 texture_lod_bias;\nuniform vec2 test_uv, test_delta;\n"
        "layout(location=0) out vec4 color;\n");
    border_sample_function(&text, &key, 0);
    xgpu_text_append(&text, "void main() { vec4 coordinates = vec4(test_uv + (gl_FragCoord.xy - vec2(2.5)) * test_delta, 0.0, 1.0); color = ");
    sample(&text, &key, 0, "coordinates");
    xgpu_text_append(&text, "; }\n");
    GLuint vertex = shader(GL_VERTEX_SHADER, "#version 300 es\nvoid main() { vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2); gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0); }");
    GLuint fragment = shader(GL_FRAGMENT_SHADER, text.buffer);
    GLuint result = glCreateProgram(); glAttachShader(result, vertex); glAttachShader(result, fragment); glLinkProgram(result);
    GLint ok; glGetProgramiv(result, GL_LINK_STATUS, &ok); assert(ok);
    glDeleteShader(vertex); glDeleteShader(fragment); free(text.buffer); return result;
}

static unsigned char pixels[4][4][4];
static const float border[4] = {0.1f, 0.2f, 0.9f, 0.25f};
static float texel(int x, int y, unsigned axes, int channel) {
    if (((axes & 1) && (x < 0 || x >= 4)) || ((axes & 2) && (y < 0 || y >= 4))) return border[channel];
    x = (x % 4 + 4) % 4; y = (y % 4 + 4) % 4;
    return pixels[y][x][channel] / 255.f;
}
/* Independent reference: explicitly sample/wrap the neighboring texels and
   substitute border texels before interpolation, rather than edge coverage. */
static float reference(float u, float v, unsigned axes, int linear, int channel) {
    if (!linear) return texel((int)floorf(u * 4), (int)floorf(v * 4), axes, channel);
    float x = u * 4 - .5f, y = v * 4 - .5f;
    int ix = (int)floorf(x), iy = (int)floorf(y); float fx = x - ix, fy = y - iy;
    return texel(ix, iy, axes, channel) * (1-fx) * (1-fy) + texel(ix+1, iy, axes, channel) * fx * (1-fy)
        + texel(ix, iy+1, axes, channel) * (1-fx) * fy + texel(ix+1, iy+1, axes, channel) * fx * fy;
}

int main(void) {
    check_scope();
    PFNEGLGETPLATFORMDISPLAYEXTPROC get_display = (void *)eglGetProcAddress("eglGetPlatformDisplayEXT"); assert(get_display);
    const EGLint display_attributes[] = {0x3203, 0x3489, EGL_NONE};
    EGLDisplay display = get_display(0x3202, NULL, display_attributes);
    assert(eglInitialize(display, NULL, NULL)); assert(eglBindAPI(EGL_OPENGL_ES_API));
    const EGLint config_attributes[] = {EGL_SURFACE_TYPE, EGL_PBUFFER_BIT, EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT,
        EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8, EGL_NONE};
    EGLConfig config; EGLint count; assert(eglChooseConfig(display, config_attributes, &config, 1, &count) && count);
    const EGLint context_attributes[] = {EGL_CONTEXT_CLIENT_VERSION, 3, EGL_NONE};
    EGLContext context = eglCreateContext(display, config, EGL_NO_CONTEXT, context_attributes); assert(context != EGL_NO_CONTEXT);
    const EGLint surface_attributes[] = {EGL_WIDTH, 4, EGL_HEIGHT, 4, EGL_NONE};
    EGLSurface surface = eglCreatePbufferSurface(display, config, surface_attributes); assert(surface != EGL_NO_SURFACE);
    assert(eglMakeCurrent(display, surface, surface, context)); glViewport(0, 0, 4, 4);
    for (int y=0; y<4; y++) for (int x=0; x<4; x++) for (int c=0; c<4; c++) pixels[y][x][c] = 40 + x*31 + y*17 + c*13;
    GLuint texture; glGenTextures(1, &texture); glBindTexture(GL_TEXTURE_2D, texture);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 4, 4, 0, GL_RGBA, GL_UNSIGNED_BYTE, pixels);
    const float coordinates[] = {-2.f, -.25f, -.0625f, 0.f, .0625f, .125f, .5f, .875f, .9375f, 1.f, 1.0625f, 1.25f, 3.f};
    /* Magnification/minification transitions, including bias: the native
       sampler must choose the same texel footprint as border coverage. */
    const float footprints[][2] = {{0,0}, {.24f,0}, {.25f,0}, {.26f,0}, {.6f,0},
        {.125f,1}, {.125f,1.125f}, {.5f,-1}, {.5f,-1.125f}};
    unsigned checks = 0;
    for (unsigned axes=1; axes<=3; axes++) for (unsigned filtering=0; filtering<=3; filtering++) {
        GLuint p = program(axes, filtering); glUseProgram(p);
        glUniform1i(glGetUniformLocation(p, "tex0"), 0);
        glUniform4fv(glGetUniformLocation(p, "texture_border_color"), 1, border);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, axes & 1 ? GL_CLAMP_TO_EDGE : GL_REPEAT);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, axes & 2 ? GL_CLAMP_TO_EDGE : GL_REPEAT);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, filtering & 1 ? GL_LINEAR : GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, filtering & 2 ? GL_LINEAR : GL_NEAREST);
        for (unsigned scale_case=0; scale_case<2; scale_case++) for (unsigned footprint=0; footprint<sizeof(footprints)/sizeof(footprints[0]); footprint++) {
            float scale = scale_case ? .25f : 1.f;
            float delta = footprints[footprint][0], bias = footprints[footprint][1];
            unsigned minifying = delta*delta*16.f*exp2f(2*bias) > 1.f;
            glUniform4f(glGetUniformLocation(p, "texture_scale"), scale, scale, 1, 1);
            glUniform4f(glGetUniformLocation(p, "texture_lod_bias"), bias, 0, 0, 0);
            glUniform2f(glGetUniformLocation(p, "test_delta"), delta / scale, 0);
            int linear = filtering & (minifying ? 1 : 2);
            for (unsigned iu=0; iu<sizeof(coordinates)/sizeof(float); iu++) for (unsigned iv=0; iv<sizeof(coordinates)/sizeof(float); iv++) {
                float u = coordinates[iu], v = coordinates[iv]; unsigned char result[4];
                glUniform2f(glGetUniformLocation(p, "test_uv"), u / scale, v / scale);
                glDrawArrays(GL_TRIANGLES, 0, 3); glReadPixels(2, 2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, result);
                for (int c=0; c<4; c++) {
                    float expected = reference(u, v, axes, linear, c)*255;
                    if (fabsf(result[c]-expected) > 2.1f) {
                        fprintf(stderr, "border mismatch: axes=%u filters=%u min=%u delta=%g bias=%g scale=%g uv=(%g,%g) channel=%d got=%u want=%g\n", axes, filtering, minifying, delta, bias, scale, u, v, c, result[c], expected); return 1;
                    }
                }
                checks++;
            }
        }
        glDeleteProgram(p);
    }
    assert(glGetError() == GL_NO_ERROR);
    printf("%u border pixel checks passed; native/mip/anisotropic/3D/cube scope preserved\n", checks);
    eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
    eglDestroySurface(display, surface); eglDestroyContext(display, context); eglTerminate(display); return 0;
}
'''


@unittest.skipUnless(sys.platform == "darwin", "ANGLE Metal regression requires macOS")
class TextureBorderTests(unittest.TestCase):
    def test_generated_shader_pixels_and_fallback_scope(self):
        shader_source = (PORT / "nv2a_psh.c").read_text()
        helpers = shader_source[shader_source.index("static void border_sample_function("):
                                shader_source.index("static void texture_stage(")]
        device_source = (PORT / "d3d8_gl.c").read_text()
        key_code = device_source[device_source.index("static void texture_border_key("):
                                 device_source.index("static void bind_textures(")]
        with tempfile.TemporaryDirectory(prefix="halo-texture-border-") as temporary:
            directory = Path(temporary)
            source = directory / "border.c"
            source.write_text(HARNESS.replace("/* KEY_CODE */", key_code).replace("/* SHADER_CODE */", helpers))
            egl = ANGLE / "EGL.xcframework/macos-arm64"
            gles = ANGLE / "GLESv2.xcframework/macos-arm64"
            subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2", str(source),
                            f"-I{ROOT / 'build/macos/toolchain/gl'}", f"-F{egl}", f"-F{gles}",
                            "-framework", "libEGL", "-framework", "libGLESv2", f"-Wl,-rpath,{egl}",
                            f"-Wl,-rpath,{gles}", "-o", str(directory / "border")], check=True)
            result = subprocess.run([str(directory / "border")], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("36504 border pixel checks passed", result.stdout)
            print(result.stdout.strip())


if __name__ == "__main__":
    unittest.main()

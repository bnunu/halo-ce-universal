"""Execute generated guest GL wrappers against mock host imports.

These checks cover pointers deliberately widened to integers by the generator;
the LLVM guest rebase pass can no longer recognize those arguments as pointers.
No GL context, graphics driver, app, or game data is required.
"""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = (
    "glTexImage2D", "glTexImage3D", "glTexSubImage2D",
    "glCompressedTexImage3D", "glShaderSource", "glVertexAttribPointer",
    "glDrawElements", "glBufferData",
)

# Standard GLES declarations for the exercised imports. Keeping the fixture
# self-contained lets CI run without downloading an SDK or ANGLE distribution.
HEADER = r'''
#include <stddef.h>
typedef unsigned int GLenum, GLuint;
typedef int GLint, GLsizei;
typedef unsigned char GLboolean;
typedef char GLchar;
typedef ptrdiff_t GLsizeiptr;
#include "fixture_macros.h"
GL_APICALL void GL_APIENTRY glTexImage2D(GLenum target, GLint level,
    GLint internalformat, GLsizei width, GLsizei height, GLint border,
    GLenum format, GLenum type, const void *pixels);
GL_APICALL void GL_APIENTRY glTexImage3D(GLenum target, GLint level,
    GLint internalformat, GLsizei width, GLsizei height, GLsizei depth,
    GLint border, GLenum format, GLenum type, const void *pixels);
GL_APICALL void GL_APIENTRY glTexSubImage2D(GLenum target, GLint level,
    GLint xoffset, GLint yoffset, GLsizei width, GLsizei height,
    GLenum format, GLenum type, const void *pixels);
GL_APICALL void GL_APIENTRY glCompressedTexImage3D(GLenum target, GLint level,
    GLenum internalformat, GLsizei width, GLsizei height, GLsizei depth,
    GLint border, GLsizei imageSize, const void *data);
GL_APICALL void GL_APIENTRY glShaderSource(GLuint shader, GLsizei count,
    const GLchar *const *strings, const GLint *lengths);
GL_APICALL void GL_APIENTRY glVertexAttribPointer(GLuint index, GLint size,
    GLenum type, GLboolean normalized, GLsizei stride, const void *pointer);
GL_APICALL void GL_APIENTRY glDrawElements(GLenum mode, GLsizei count,
    GLenum type, const void *indices);
GL_APICALL void GL_APIENTRY glBufferData(GLenum target, GLsizeiptr size,
    const void *data, GLenum usage);
'''

HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include "generated.c"

static unsigned calls;
static unsigned long long expected_pixels;
static const GLint lengths[16] = {1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16};
static int expected_count;
static const void *typed_pointer;

void hostgl_glTexImage2D(GLenum a0, GLint a1, GLint a2, GLsizei a3,
    GLsizei a4, GLint a5, GLenum a6, GLenum a7, unsigned long long a8) {
    assert(a0==1 && a1==-2 && a2==3 && a3==4 && a4==5 && a5==6 && a6==7 && a7==8);
    assert(a8==expected_pixels); calls++;
}
void hostgl_glTexImage3D(GLenum a0, GLint a1, GLint a2, GLsizei a3,
    GLsizei a4, GLsizei a5, GLint a6, GLenum a7, long long a8,
    unsigned long long a9) {
    assert(a0==1 && a1==-2 && a2==3 && a3==4 && a4==5 && a5==6 && a6==7 && a7==8);
    assert(a8==0xfedcba98u && a9==expected_pixels); calls++;
}
void hostgl_glTexSubImage2D(GLenum a0, GLint a1, GLint a2, GLint a3,
    GLsizei a4, GLsizei a5, GLenum a6, GLenum a7, unsigned long long a8) {
    assert(a0==1 && a1==-2 && a2==3 && a3==4 && a4==5 && a5==6 && a6==7 && a7==8);
    assert(a8==expected_pixels); calls++;
}
void hostgl_glCompressedTexImage3D(GLenum a0, GLint a1, GLenum a2, GLsizei a3,
    GLsizei a4, GLsizei a5, GLint a6, GLsizei a7, unsigned long long a8) {
    assert(a0==1 && a1==-2 && a2==3 && a3==4 && a4==5 && a5==6 && a6==7 && a7==8);
    assert(a8==expected_pixels); calls++;
}
static unsigned long long widened(unsigned int address) {
#ifdef HALO_MACOS
    return address ? (0x10000000000ull | address) : 0;
#else
    return address;
#endif
}
void hostgl_glShaderSource(GLuint shader, GLsizei count,
    const unsigned long long *strings, const GLint *sizes) {
    assert(shader==42 && count==expected_count && sizes==lengths);
    for (int i=0; i<count; i++)
        assert(strings[i]==widened(i==3 ? 0 : 0x80000000u+i*32));
    calls++;
}
void hostgl_glVertexAttribPointer(GLuint index, GLint size, GLenum type,
    GLboolean normalized, GLsizei stride, const void *pointer) {
    assert(index==1 && size==2 && type==3 && normalized==1 && stride==16);
    assert(pointer==typed_pointer); calls++;
}
void hostgl_glDrawElements(GLenum mode, GLsizei count, GLenum type,
    const void *indices) {
    assert(mode==1 && count==2 && type==3 && indices==typed_pointer); calls++;
}
void hostgl_glBufferData(GLenum target, long long size, const void *data, GLenum usage) {
    assert(target==1 && size==-16 && data==typed_pointer && usage==2); calls++;
}
int main(void) {
    const unsigned int addresses[]={0, 0x030d4550, 0x80000000u, 0xffffffffu};
    for (unsigned i=0; i<sizeof(addresses)/sizeof(addresses[0]); i++) {
        const void *pixels=(const void *)(uintptr_t)addresses[i];
        expected_pixels=widened(addresses[i]);
        guest_glTexImage2D(1,-2,3,4,5,6,7,8,pixels);
        guest_glTexImage3D(1,-2,3,4,5,6,7,8,0xfedcba98u,pixels);
        guest_glTexSubImage2D(1,-2,3,4,5,6,7,8,pixels);
        guest_glCompressedTexImage3D(1,-2,3,4,5,6,7,8,pixels);
    }
    const GLchar *strings[20];
    for (unsigned i=0; i<20; i++)
        strings[i]=(const GLchar *)(uintptr_t)(i==3 ? 0 : 0x80000000u+i*32);
    expected_count=16; guest_glShaderSource(42,20,strings,lengths);
    expected_count=5; guest_glShaderSource(42,5,strings,lengths);
    expected_count=0; guest_glShaderSource(42,0,NULL,lengths);
    typed_pointer=(const void *)(uintptr_t)32;
    guest_glVertexAttribPointer(1,2,3,1,16,typed_pointer);
    guest_glDrawElements(1,2,3,typed_pointer);
    guest_glBufferData(1,-16,typed_pointer,2);
    assert(calls==22);
    assert(guest_gl_get_proc_address("glTexImage2D")==(guest_gl_function)guest_glTexImage2D);
    assert(guest_gl_get_proc_address("missing")==NULL);
    return 0;
}
'''


class GeneratedGLPointerTests(unittest.TestCase):
    def compile_and_run(self, macos):
        compiler = shutil.which("clang") or shutil.which("cc")
        if compiler is None:
            self.skipTest("a C compiler is required")
        production = (ROOT / "port/linux/src/gl.h").read_text()
        for name in FUNCTIONS:
            self.assertIn(f"X({name})", production)
        with tempfile.TemporaryDirectory(prefix="halo-gl-stubs-") as directory:
            temp = Path(directory)
            (temp / "GLES3").mkdir()
            (temp / "GLES2").mkdir()
            (temp / "GLES3/gl32.h").write_text(HEADER)
            (temp / "GLES2/gl2ext.h").write_text("")
            (temp / "fixture_macros.h").write_text("#define GL_APICALL\n#define GL_APIENTRY\n")
            (temp / "gl.h").write_text(
                "/* ANDROID_GL_FUNCTIONS_BEGIN */\n" +
                "\n".join(f"X({name})" for name in FUNCTIONS) +
                "\n/* ANDROID_GL_FUNCTIONS_END */\n")
            subprocess.run([
                sys.executable, str(ROOT / "tools/android_gl_stubs.py"),
                str(temp / "gl.h"), str(temp / "GLES3/gl32.h"),
                str(temp / "GLES2/gl2ext.h"), str(temp / "generated.c"),
                str(temp / "imports.list"),
            ], check=True, capture_output=True, text=True)
            self.assertEqual((temp / "imports.list").read_text().splitlines(),
                             ["hostgl_" + name for name in FUNCTIONS])
            (temp / "test.c").write_text(HARNESS)
            command = [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                       "-Wno-pointer-to-int-cast", "-DHALO_ANDROID=1", "-I", str(temp)]
            if macos:
                command.append("-DHALO_MACOS=1")
            result = subprocess.run(command + [str(temp / "test.c"), "-o", str(temp / "test")],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(temp / "test")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_macos_integer_pointers_acquire_guest_bias_once(self):
        self.compile_and_run(macos=True)

    def test_android_integer_pointers_remain_unbiased(self):
        self.compile_and_run(macos=False)


if __name__ == "__main__":
    unittest.main()

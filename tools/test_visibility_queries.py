#!/usr/bin/env python3
"""Exercise the actual GLES visibility adapter with a deterministic fake GPU."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#define HALO_ANDROID 1
#define HALO_MACOS 1
#define WINAPI
#define TRUE 1
#define FALSE 0
#define S_OK 0
#define D3DERR_TESTINCOMPLETE 1
#define VISIBILITY_TEST_SLOTS 4096
#define VISIBILITY_QUERY 1
#define VISIBILITY_ALL_SAMPLES 1000000
#define GL_QUERY_RESULT_AVAILABLE 2
#define GL_QUERY_RESULT 3
#define GL_ATOMIC_COUNTER_BUFFER 4
typedef unsigned GLuint, DWORD, UINT;
typedef int BOOL, HRESULT;
typedef uint64_t ULONGLONG;
static struct { int atomic_counters; } xgpu_capabilities;
static struct {
    int gl_ready, visibility_test_active;
    GLuint queries[VISIBILITY_TEST_SLOTS + 1];
    BOOL query_pending[VISIBILITY_TEST_SLOTS];
    GLuint query_results[VISIBILITY_TEST_SLOTS];
    float query_area[VISIBILITY_TEST_SLOTS];
    GLuint visibility_counters, counter_next, counter_active;
    GLuint counter_of_slot[VISIBILITY_TEST_SLOTS];
} device;
static float target_scale[2] = {1,1};
static GLuint active_query, next_samples;
static struct { GLuint samples, available; } gpu[VISIBILITY_TEST_SLOTS + 2];
static void glBeginQuery(unsigned target, GLuint query) {
    (void)target; assert(!active_query); assert(query); active_query = query;
}
static void glEndQuery(unsigned target) {
    (void)target; assert(active_query);
    gpu[active_query].samples = next_samples;
    gpu[active_query].available = 0;
    active_query = 0;
}
static void glGetQueryObjectuiv(GLuint query, unsigned key, GLuint *value) {
    assert(query);
    if (key == GL_QUERY_RESULT) assert(gpu[query].available);
    *value = key == GL_QUERY_RESULT_AVAILABLE ? gpu[query].available : gpu[query].samples;
}
static void glBindBuffer(unsigned target, GLuint buffer) { (void)target; (void)buffer; }
static void host_gl_buffer_write(unsigned t, unsigned o, unsigned n, const void *p) {
    (void)t; (void)o; (void)n; (void)p; assert(0);
}
static GLuint host_gl_read_buffer_word(GLuint b, unsigned o) { (void)b; (void)o; assert(0); return 0; }
/* ADAPTER */
static void submit(unsigned slot, unsigned samples) {
    next_samples = samples;
    D3DDevice_BeginVisibilityTest();
    assert(D3DDevice_EndVisibilityTest(slot) == S_OK);
}
static unsigned result(unsigned slot) {
    UINT samples = 123;
    assert(D3DDevice_GetVisibilityTestResult(slot, &samples, NULL) == S_OK);
    return samples;
}
static void complete_gpu(void) {
    for (unsigned i = 1; i < VISIBILITY_TEST_SLOTS + 2; i++) gpu[i].available = 1;
}
int main(void) {
    device.gl_ready = 1;
    for (unsigned i = 0; i <= VISIBILITY_TEST_SLOTS; i++) device.queries[i] = i + 1;
    /* Adjacent effects must not share a result, including the valid slot zero. */
    submit(0, 1); submit(1, 0); submit(VISIBILITY_TEST_SLOTS - 1, 1);
    complete_gpu();
    assert(result(0) == VISIBILITY_ALL_SAMPLES);
    assert(result(1) == 0);
    assert(result(VISIBILITY_TEST_SLOTS - 1) == VISIBILITY_ALL_SAMPLES);
    /* Pending GPU work retains the last completed result without blocking. */
    submit(0, 0); submit(1, 1);
    assert(result(0) == VISIBILITY_ALL_SAMPLES);
    assert(result(1) == 0);
    complete_gpu();
    assert(result(0) == 0);
    assert(result(1) == VISIBILITY_ALL_SAMPLES);
    puts("Independent visibility slots and asynchronous results passed");
}
"""


class VisibilityQueries(unittest.TestCase):
    def test_gles_result_slots(self):
        source = (ROOT / "port/linux/src/d3d8_gl.c").read_text()
        adapter = source.split("/* ---------- visibility (occlusion) tests */", 1)[1]
        adapter = adapter.split("/* ---------- render and texture stage state */", 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            probe = directory / "visibility.c"
            probe.write_text(HARNESS.replace("/* ADAPTER */", adapter))
            executable = directory / "visibility"
            compiled = subprocess.run(["clang", "-O2", "-Wall", str(probe), "-o", str(executable)],
                                      capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            tested = subprocess.run([str(executable)], capture_output=True, text=True, timeout=5)
            self.assertEqual(tested.returncode, 0, tested.stderr)


if __name__ == "__main__":
    unittest.main()

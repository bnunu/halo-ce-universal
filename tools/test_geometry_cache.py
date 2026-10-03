"""Exercise the renderer's real cache with map-address reuse and a fake GPU."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <assert.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define HALO_ANDROID 1
#define HALO_GLES 1
#define HALO_MACOS 1
/* CONFIG */
#define TRUE 1
#define FALSE 0
#define GL_COPY_WRITE_BUFFER 1
#define GL_DYNAMIC_DRAW 2
typedef int BOOL;
typedef unsigned GLuint;
typedef intptr_t GLintptr, GLsizeiptr;
typedef uint16_t WORD;
#define SEGMENT_BYTES 0x400000UL
static unsigned char memory[2 * SEGMENT_BYTES] __attribute__((aligned(4096)));
#define PLATFORM_CONTIGUOUS_BASE ((unsigned long)memory)
#define PLATFORM_CONTIGUOUS_SIZE sizeof(memory)
static struct { unsigned long frame; } device;
static struct { unsigned long mirrored_bytes; } stats;
static unsigned next_buffer, bound, allocations, fail_allocation;
static unsigned char *gpu[3];
static unsigned long uploaded;
/* Deliberately unchanged: reused map memory must not trust this generation. */
static unsigned long memory_watch_generation(unsigned long a, unsigned long n) {
    (void)a; (void)n; return 1;
}
static void memory_watch_protect(unsigned long a, unsigned long n) { (void)a; (void)n; }
static void glGenBuffers(unsigned n, GLuint *buffers) {
    while (n--) { assert(next_buffer < 2); *buffers++ = ++next_buffer; }
}
static void glBindBuffer(unsigned target, GLuint buffer) {
    assert(target == GL_COPY_WRITE_BUFFER && buffer && buffer <= next_buffer); bound = buffer;
}
static void glBufferData(unsigned target, GLsizeiptr size, const void *data, unsigned usage) {
    assert(target == GL_COPY_WRITE_BUFFER && usage == GL_DYNAMIC_DRAW && !data);
    assert(size == SEGMENT_BYTES && !gpu[bound]);
    gpu[bound] = calloc(1, size); assert(gpu[bound]);
}
static void glBufferSubData(unsigned target, GLintptr offset, GLsizeiptr size, const void *data) {
    assert(target == GL_COPY_WRITE_BUFFER && offset >= 0 && size >= 0 && offset + size <= SEGMENT_BYTES);
    memcpy(gpu[bound] + offset, data, size); uploaded += size;
}
static void host_gl_buffer_write(unsigned target, unsigned offset, unsigned size, const void *data) {
    glBufferSubData(target, offset, size, data);
}
static void *snapshot_allocate(size_t size) {
    allocations++;
    if (fail_allocation) { fail_allocation = 0; return NULL; }
    return malloc(size);
}
#define malloc snapshot_allocate
/* CACHE */
#undef malloc

static unsigned long current(unsigned long offset, unsigned long size) {
    GLuint buffer;
    unsigned long gpu_offset, generation;
    assert(mirror_range(PLATFORM_CONTIGUOUS_BASE + offset, size, &buffer, &gpu_offset, &generation));
    assert(!memcmp(gpu[buffer] + gpu_offset, memory + offset, size));
    return generation;
}
int main(void) {
    GLuint buffer;
    unsigned long offset, generation, low, high;
#if defined(HALO_IOS) || !HALO_MACOS_GEOMETRY_CACHE
    assert(!mirror_range(PLATFORM_CONTIGUOUS_BASE, 128, &buffer, &offset, &generation));
    assert(!uploaded && !allocations && !next_buffer);
    puts("Stable Apple defaults retain streamed geometry");
    return 0;
#else
    WORD *indices = (void *)memory;
    indices[0] = 4; indices[1] = 20; indices[2] = 8;
    generation = current(0, 128);
    assert(uploaded == 4096 && allocations == 1);
    index_extent(indices, 3, generation, TRUE, &low, &high);
    assert(low == 4 && high == 20);
    /* Every byte must be compared, including tails of each machine word. */
    for (unsigned i = 0; i < 4096; i++) {
        memory[i] ^= 0x80;
        assert(!mirror_page_equal(memory, mirror.contents[0]));
        memory[i] ^= 0x80;
    }
    assert(mirror_page_equal(memory, mirror.contents[0]));
    for (unsigned i = 0; i < 1000; i++) assert(current(0, 128) == generation);
    assert(uploaded == 4096);
    /* A map can reuse an address, and dynamic data can change in the same
       frame. Its GPU copy and cached index extent must both become current. */
    indices[0] = 100; indices[1] = 300; indices[2] = 200;
    unsigned long changed = current(0, 128);
    assert(changed > generation && uploaded == 8192);
    index_extent(indices, 3, changed, TRUE, &low, &high);
    assert(low == 100 && high == 300);
    /* Cover both sides of a native 16 KB page boundary and an unwatched
       neighboring Xbox page; only the changed page should upload. */
    current(3 * 4096, 8192);
    unsigned long before = uploaded;
    memory[4 * 4096 + 77] = 91;
    current(3 * 4096, 8192);
    assert(uploaded == before + 4096);
    before = uploaded;
    memory[6 * 4096 + 55] = 88;
    current(3 * 4096, 8192);
    assert(uploaded == before);
    current(6 * 4096, 128);
    /* Large ranges use multiple refresh chunks without missing their tail. */
    memory[0x300000 - 1] = 64;
    current(0x100000, 0x200000);
    memory[0x300000 - 1] = 65;
    current(0x100000, 0x200000);
    assert(!mirror_range(PLATFORM_CONTIGUOUS_BASE - 1, 1, &buffer, &offset, NULL));
    assert(!mirror_range(PLATFORM_CONTIGUOUS_BASE + 8, ULONG_MAX, &buffer, &offset, NULL));
    assert(!mirror_range(PLATFORM_CONTIGUOUS_BASE + SEGMENT_BYTES - 1, 2, &buffer, &offset, NULL));
    assert(!mirror_range(PLATFORM_CONTIGUOUS_BASE + PLATFORM_CONTIGUOUS_SIZE, 1, &buffer, &offset, NULL));
    /* Rewritten pages stream temporarily, then can become static again. */
    unsigned long dynamic = 80 * 4096;
    current(dynamic, 128);
    for (unsigned i = 1; i < MIRROR_VOLATILE_REWRITES; i++) {
        device.frame++; memory[dynamic] = i; current(dynamic, 128);
    }
    device.frame++; memory[dynamic] = 55;
    assert(!mirror_range(PLATFORM_CONTIGUOUS_BASE + dynamic, 128, &buffer, &offset, NULL));
    device.frame += MIRROR_VOLATILE_FRAMES;
    current(dynamic, 128);
    /* Allocation failure falls back before publishing an incomplete cache. */
    fail_allocation = 1;
    assert(!mirror_range(PLATFORM_CONTIGUOUS_BASE + SEGMENT_BYTES, 128, &buffer, &offset, NULL));
    assert(next_buffer == 1);
    current(SEGMENT_BYTES, 128);
    unsigned bounded_allocations = allocations;
    for (unsigned i = 0; i < 200; i++) {
        device.frame += 10; memory[33] = i; current(0, 128);
    }
    assert(allocations == bounded_allocations && next_buffer == 2);
    puts("Unchanged uploads, map reuse, index extents, page boundaries, dynamic fallback and bounded storage passed");
    return 0;
#endif
}
'''


class GeometryCache(unittest.TestCase):
    def run_probe(self, enabled=True):
        source = (ROOT / 'port/linux/src/d3d8_gl.c').read_text()
        cache = source.split('#define MIRROR_SEGMENT_SIZE ', 1)[1]
        cache = '#define MIRROR_SEGMENT_SIZE ' + cache.split('/* ---------- vertex data */', 1)[0]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            probe = directory / 'geometry.c'
            configuration = (ROOT / 'port/macos/renderer_config.h').read_text()
            probe.write_text(HARNESS.replace('/* CONFIG */', configuration).replace('/* CACHE */', cache))
            executable = directory / 'geometry'
            compiled = subprocess.run(['clang', '-O2', '-Wall',
                                       *(['-DHALO_MACOS_GEOMETRY_CACHE=1'] if enabled else []),
                                       probe, '-o', executable], capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([executable], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_map_reuse_and_uploads(self):
        self.run_probe()

    def test_mac_streaming_default(self):
        self.run_probe(enabled=False)


if __name__ == '__main__':
    unittest.main()

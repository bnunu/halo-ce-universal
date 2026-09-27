/* Opt-in frame and driver diagnostics. No per-draw work when disabled. */
#include "host.h"
#include <GLES3/gl3.h>
#include <SDL3/SDL.h>
#include <mach/mach.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static FILE *output;
static int initialized;
static uint64_t frame, previous, draws, upload_bytes, query_calls;
static double draw_ms, shader_ms;
static GLuint array_buffer;
static size_t buffer_sizes[65536];
static struct { int enabled, size, stride; GLenum type; GLuint buffer; uintptr_t offset; } attributes[16];

static int enabled(void) {
    if (!initialized) {
        initialized = 1;
        const char *path = getenv("HALO_PERF_LOG");
        if (path && *path) {
            output = fopen(path, "w");
            if (output) {
                fprintf(output, "frame,frame_ms,swap_ms,draw_ms,shader_ms,draws,upload_bytes,footprint_mb,query_calls\n");
                setvbuf(output, NULL, _IOLBF, 0);
            }
        }
    }
    return output != NULL;
}

void host_perf_frame(double swap_ms) {
    if (!enabled()) return;
    uint64_t now = SDL_GetTicksNS();
    static double footprint;
    if (!(frame % 30)) {
        task_vm_info_data_t info;
        mach_msg_type_number_t count = TASK_VM_INFO_COUNT;
        if (task_info(mach_task_self(), TASK_VM_INFO, (task_info_t)&info, &count) == KERN_SUCCESS)
            footprint = info.phys_footprint / 1048576.0;
    }
    if (previous)
        fprintf(output, "%llu,%.3f,%.3f,%.3f,%.3f,%llu,%llu,%.2f,%llu\n",
                (unsigned long long)frame, (now-previous)/1e6, swap_ms, draw_ms, shader_ms,
                (unsigned long long)draws, (unsigned long long)upload_bytes, footprint,
                (unsigned long long)query_calls);
    previous = now; frame++; draws = upload_bytes = query_calls = 0; draw_ms = shader_ms = 0;
}

void host_perf_upload(uint32_t size) { if (output) upload_bytes += size; }

static void bind_buffer(GLenum target, GLuint buffer) {
    if (target == GL_ARRAY_BUFFER) array_buffer = buffer;
    glBindBuffer(target, buffer);
}
static void buffer_data(GLenum target, GLsizeiptr size, const void *data, GLenum usage) {
    if (target == GL_ARRAY_BUFFER && array_buffer < 65536) buffer_sizes[array_buffer] = size;
    if (data) upload_bytes += size;
    glBufferData(target, size, data, usage);
}
static void buffer_subdata(GLenum target, GLintptr offset, GLsizeiptr size, const void *data) {
    upload_bytes += size; glBufferSubData(target, offset, size, data);
}
static void enable_attribute(GLuint index) {
    if (index < 16) attributes[index].enabled = 1;
    glEnableVertexAttribArray(index);
}
static void disable_attribute(GLuint index) {
    if (index < 16) attributes[index].enabled = 0;
    glDisableVertexAttribArray(index);
}
static void attribute(GLuint i, GLint size, GLenum type, GLboolean normalized, GLsizei stride, const void *offset) {
    if (i < 16) {
        attributes[i].size = size; attributes[i].type = type; attributes[i].stride = stride;
        attributes[i].offset = (uintptr_t)offset; attributes[i].buffer = array_buffer;
    }
    glVertexAttribPointer(i, size, type, normalized, stride, offset);
}
static void draw_end(uint64_t start, GLsizei count) {
    double ms = (SDL_GetTicksNS()-start)/1e6;
    draw_ms += ms; draws++;
    static unsigned reports;
    if (ms > 100 && reports++ < 40) {
        host_logf(1, "Slow draw: %.1f ms, %d vertices/indices, frame %llu", ms, count, (unsigned long long)frame);
        for (unsigned i=0; i<16; i++) if (attributes[i].enabled)
            host_logf(1, "  attribute %u: %dx%x stride=%d offset=%llu buffer=%u bytes=%zu", i,
                      attributes[i].size, attributes[i].type, attributes[i].stride,
                      (unsigned long long)attributes[i].offset, attributes[i].buffer,
                      attributes[i].buffer < 65536 ? buffer_sizes[attributes[i].buffer] : 0);
    }
}
static void draw_arrays(GLenum mode, GLint first, GLsizei count) {
    uint64_t start = SDL_GetTicksNS(); glDrawArrays(mode, first, count); draw_end(start, count);
}
static void draw_elements(GLenum mode, GLsizei count, GLenum type, const void *offset) {
    uint64_t start = SDL_GetTicksNS(); glDrawElements(mode, count, type, offset); draw_end(start, count);
}
static void compile_shader(GLuint shader) {
    uint64_t start = SDL_GetTicksNS(); glCompileShader(shader); shader_ms += (SDL_GetTicksNS()-start)/1e6;
}
static void link_program(GLuint program) {
    uint64_t start = SDL_GetTicksNS(); glLinkProgram(program); shader_ms += (SDL_GetTicksNS()-start)/1e6;
}
static void query_result(GLuint query, GLenum pname, GLuint *value) {
    query_calls++;
    glGetQueryObjectuiv(query, pname, value);
}
void *host_perf_resolve(const char *name) {
    if (!enabled()) return NULL;
#define WRAP(gl, fn) if (!strcmp(name, #gl)) return (void *)fn
    WRAP(glBindBuffer, bind_buffer); WRAP(glBufferData, buffer_data); WRAP(glBufferSubData, buffer_subdata);
    WRAP(glEnableVertexAttribArray, enable_attribute); WRAP(glDisableVertexAttribArray, disable_attribute);
    WRAP(glVertexAttribPointer, attribute); WRAP(glDrawArrays, draw_arrays); WRAP(glDrawElements, draw_elements);
    WRAP(glCompileShader, compile_shader); WRAP(glLinkProgram, link_program);
    WRAP(glGetQueryObjectuiv, query_result);
#undef WRAP
    return NULL;
}

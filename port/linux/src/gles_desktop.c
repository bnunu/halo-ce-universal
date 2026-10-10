/*
GLES_DESKTOP.C

The desktop builds' OpenGL ES renderer (configure.py --gles, gl.h's
HALO_GLES), for graphics that have no OpenGL 4.5. The renderer's ES path is
Android's (d3d8_gl.c, nv2a_vsh.c, nv2a_psh.c, xbox_textures.c), which asks
the Android host for a few things (xgpu.h, host_gl_*); here they are done
directly, as port/android/host/host_gl.c does them. On Windows the ES context
comes from ANGLE, which draws with Direct3D 11, when its libGLESv2.dll is
next to the game; otherwise from the graphics driver's own OpenGL ES
support.
*/

#include "xgpu.h"

#if defined(HALO_GLES) && !defined(HALO_ANDROID)

#include <SDL3/SDL.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ---------- constants */

/* the frames whose stream buffers are fenced (d3d8_gl.c STREAM_BUFFER_RING) */
#define FRAME_FENCE_SLOTS 8

#ifdef _WIN32
/* EGL_ANGLE_platform_angle and EGL_ANGLE_platform_angle_d3d */
#define ANGLE_PLATFORM 0x3202
#define ANGLE_PLATFORM_TYPE 0x3203
#define ANGLE_PLATFORM_MAXIMUM_VERSION_MAJOR 0x3204
#define ANGLE_PLATFORM_MAXIMUM_VERSION_MINOR 0x3205
#define ANGLE_PLATFORM_TYPE_DIRECT3D_11 0x3208
#define EGL_ATTRIBUTES_END 0x3038
#endif

/* ---------- globals */

/* the entry points these helpers use beyond the renderer's own (gl.h) */
static __typeof__(&glGetStringi) gles_glGetStringi;
static __typeof__(&glMapBufferRange) gles_glMapBufferRange;
static __typeof__(&glUnmapBuffer) gles_glUnmapBuffer;
static __typeof__(&glFenceSync) gles_glFenceSync;
static __typeof__(&glClientWaitSync) gles_glClientWaitSync;
static __typeof__(&glDeleteSync) gles_glDeleteSync;
static BOOL gles_loaded;

static GLsync frame_fences[FRAME_FENCE_SLOTS];

#ifdef _WIN32
/* the Direct3D feature level ANGLE is held to (HALO_ANGLE_FEATURE_LEVEL) */
static int angle_feature_level_major, angle_feature_level_minor;
#endif

/* ---------- private code */

#ifdef _WIN32
/* what ANGLE's display is made with (SDL frees it) */
static SDL_EGLAttrib *SDLCALL angle_display_attributes(void *userdata)
{
	SDL_EGLAttrib *attributes = SDL_malloc(7 * sizeof(*attributes));

	(void)userdata;
	if (attributes)
	{
		attributes[0] = ANGLE_PLATFORM_TYPE;
		attributes[1] = ANGLE_PLATFORM_TYPE_DIRECT3D_11;
		attributes[2] = ANGLE_PLATFORM_MAXIMUM_VERSION_MAJOR;
		attributes[3] = angle_feature_level_major;
		attributes[4] = ANGLE_PLATFORM_MAXIMUM_VERSION_MINOR;
		attributes[5] = angle_feature_level_minor;
		attributes[6] = EGL_ATTRIBUTES_END;
	}
	return attributes;
}
#endif

static void gles_load(void)
{
	if (gles_loaded)
		return;
	gles_loaded = TRUE;
	gles_glGetStringi = (__typeof__(gles_glGetStringi))SDL_GL_GetProcAddress("glGetStringi");
	gles_glMapBufferRange = (__typeof__(gles_glMapBufferRange))SDL_GL_GetProcAddress("glMapBufferRange");
	gles_glUnmapBuffer = (__typeof__(gles_glUnmapBuffer))SDL_GL_GetProcAddress("glUnmapBuffer");
	gles_glFenceSync = (__typeof__(gles_glFenceSync))SDL_GL_GetProcAddress("glFenceSync");
	gles_glClientWaitSync = (__typeof__(gles_glClientWaitSync))SDL_GL_GetProcAddress("glClientWaitSync");
	gles_glDeleteSync = (__typeof__(gles_glDeleteSync))SDL_GL_GetProcAddress("glDeleteSync");
}

/* ---------- public code */

/* Before the window is made: ANGLE's OpenGL ES where ANGLE's libGLESv2.dll
is next to the game (sdl_platform.c, platform_video_initialize), else the
driver's. SDL3 gets to it through the libEGL.dll the build makes
(port/windows/angle/libEGL.c).

HALO_ANGLE_FEATURE_LEVEL=10.1 in the environment holds ANGLE to that
Direct3D feature level: how older graphics (10.1 is the least ANGLE gives
OpenGL ES 3.0 on) are tried on newer ones. */
void gles_desktop_choose_driver(void)
{
#ifdef _WIN32
	const char *base = SDL_GetBasePath();
	char path[1024];

	snprintf(path, sizeof(path), "%slibGLESv2.dll", base ? base : "");
	if (SDL_GetPathInfo(path, NULL))
	{
		const char *level = getenv("HALO_ANGLE_FEATURE_LEVEL");

		SDL_SetHint(SDL_HINT_OPENGL_ES_DRIVER, "1");
		platform_log("OpenGL ES: ANGLE's (%s)", path);
		if (level && sscanf(level, "%d.%d", &angle_feature_level_major, &angle_feature_level_minor) == 2)
		{
			SDL_GL_SetAttribute(SDL_GL_EGL_PLATFORM, ANGLE_PLATFORM);
			SDL_EGL_SetAttributeCallbacks(angle_display_attributes, NULL, NULL, NULL);
			platform_log("OpenGL ES: ANGLE held to Direct3D feature level %d.%d", angle_feature_level_major,
				angle_feature_level_minor);
		}
		return;
	}
#endif
	platform_log("OpenGL ES: the graphics driver's");
}

/* debug.gl_debug: what the context says about each error, where it has
GL_KHR_debug (ANGLE has); the renderer's own check (d3d8_gl.c,
gl_check_errors) only tells the error's number */
static void GLAPIENTRY gles_debug_callback(GLenum source, GLenum type, GLuint id, GLenum severity, GLsizei length,
	const GLchar *message, const void *user)
{
	static unsigned long reports;

	(void)source; (void)id; (void)length; (void)user;
	if (severity != GL_DEBUG_SEVERITY_NOTIFICATION && reports++ < 200)
		platform_log("GL %s: %s", type == GL_DEBUG_TYPE_ERROR ? "error" : "debug", message);
}

void gles_desktop_debug_output(void)
{
	void (GLAPIENTRY *debug_message_callback)(GLDEBUGPROC callback, const void *user);

	if (!host_gl_has_extension("GL_KHR_debug"))
		return;
	debug_message_callback = (__typeof__(debug_message_callback))SDL_GL_GetProcAddress("glDebugMessageCallbackKHR");
	if (!debug_message_callback)
		return;
	glEnable(GL_DEBUG_OUTPUT);
	glEnable(GL_DEBUG_OUTPUT_SYNCHRONOUS);
	debug_message_callback(gles_debug_callback, NULL);
}

int host_gl_has_extension(const char *name)
{
	GLint count = 0, index;

	gles_load();
	if (!gles_glGetStringi)
		return 0;
	glGetIntegerv(GL_NUM_EXTENSIONS, &count);
	for (index = 0; index < count; index++)
	{
		const char *extension = (const char *)gles_glGetStringi(GL_EXTENSIONS, (GLuint)index);

		if (extension && !strcmp(extension, name))
			return 1;
	}
	return 0;
}

/* size bytes of a buffer object (the snapshots of the visibility tests'
counters, d3d8_gl.c), as the Android host copies them
(port/android/host/host_gl.c): ES has no glGetBufferSubData. Binds
GL_COPY_READ_BUFFER, which the renderer uses only for its copies, and
leaves it unbound. */
void host_gl_read_buffer(unsigned int buffer, unsigned int offset, unsigned int size, void *data)
{
	const void *mapping;

	memset(data, 0, size);
	gles_load();
	if (!gles_glMapBufferRange || !gles_glUnmapBuffer)
		return;
	glBindBuffer(GL_COPY_READ_BUFFER, buffer);
	mapping = gles_glMapBufferRange(GL_COPY_READ_BUFFER, offset, size, GL_MAP_READ_BIT);
	if (mapping)
	{
		memcpy(data, mapping, size);
		gles_glUnmapBuffer(GL_COPY_READ_BUFFER);
	}
	glBindBuffer(GL_COPY_READ_BUFFER, 0);
}

/* a fence at the end of a frame's work, and the wait for it before its
stream buffers are written again (d3d8_gl.c, STREAM_BUFFER_RING) */
void host_gl_fence_frame(unsigned int slot)
{
	gles_load();
	if (slot >= FRAME_FENCE_SLOTS || !gles_glFenceSync || !gles_glDeleteSync)
		return;
	if (frame_fences[slot])
		gles_glDeleteSync(frame_fences[slot]);
	frame_fences[slot] = gles_glFenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE, 0);
}

void host_gl_wait_frame(unsigned int slot)
{
	gles_load();
	if (slot >= FRAME_FENCE_SLOTS || !frame_fences[slot] || !gles_glClientWaitSync || !gles_glDeleteSync)
		return;
	/* at most a second: a lost context must not hang the game */
	gles_glClientWaitSync(frame_fences[slot], GL_SYNC_FLUSH_COMMANDS_BIT, 1000000000ull);
	gles_glDeleteSync(frame_fences[slot]);
	frame_fences[slot] = NULL;
}

/* Writes data into the buffer bound to target. The Android host maps the
range for this (port/android/host/host_gl.c). ANGLE on Direct3D 11 takes a
mapped range very badly: the main menu, about a hundred such writes a frame
into the 16 MB stream buffer, ran at 10 frames a second on a GeForce RTX
5080, and at 1,240 with glBufferSubData. */
void host_gl_buffer_write(unsigned int target, unsigned int offset, unsigned int size, const void *data)
{
	glBufferSubData(target, offset, size, data);
}

#endif

/*
GL_FUNCTIONS.C

Run-time resolution of the OpenGL entry points listed in gl.h.
*/

#include "platform.h"
#define GL_FUNCTIONS_DEFINE
#include "gl.h"

#include <SDL3/SDL.h>

#define GL_DEFINE_FUNCTION(name) __typeof__(&name) halo_##name;
GL_FUNCTIONS(GL_DEFINE_FUNCTION)

#if defined(HALO_GLES) && !defined(HALO_ANDROID)
#include <stdio.h>
#include <string.h>

/* The desktop builds' OpenGL ES context (gles_desktop.c) can be an ES 3.0
one. The renderer's list is ES 3.2's. Two of its entry points an ES 3.0
context has only as an extension's, under the extension's name (ANGLE
refuses the plain name there: "Command requires OpenGL ES 3.2"), or not at
all, and the renderer then does without them (d3d8_gl.c,
xgpu_capabilities). */

/* gles_desktop.c */
int host_gl_has_extension(const char *name);

/* the entry point `name` of the extension GL_OES_`extension` or
GL_EXT_`extension`, whichever the context has, or NULL */
static void *gl_extension_function(const char *name, const char *extension)
{
	static const char *const vendors[] = { "OES", "EXT" };
	int index;

	for (index = 0; index < (int)(sizeof(vendors) / sizeof(vendors[0])); index++)
	{
		char text[96];

		snprintf(text, sizeof(text), "GL_%s_%s", vendors[index], extension);
		if (host_gl_has_extension(text))
		{
			snprintf(text, sizeof(text), "%s%s", name, vendors[index]);
			return (void *)SDL_GL_GetProcAddress(text);
		}
	}
	return NULL;
}

/* (glMemoryBarrier is ES 3.1's: the renderer calls it only with the atomic
counters, which are 3.1's too) */
static int gl_function_optional(const char *name)
{
	return !strcmp(name, "glCopyImageSubData") || !strcmp(name, "glDrawElementsBaseVertex") ||
		!strcmp(name, "glMemoryBarrier");
}

int gl_functions_load(void)
{
	int success = TRUE;
	GLint major = 0, minor = 0;

#define GL_LOAD_FUNCTION(name) \
	halo_##name = (__typeof__(halo_##name))SDL_GL_GetProcAddress(#name); \
	if (!halo_##name && !gl_function_optional(#name)) \
	{ \
		platform_log("OpenGL function %s is unavailable", #name); \
		success = FALSE; \
	}
	GL_FUNCTIONS(GL_LOAD_FUNCTION)
#undef GL_LOAD_FUNCTION
	if (!success)
		return FALSE;
	halo_glGetIntegerv(GL_MAJOR_VERSION, &major);
	halo_glGetIntegerv(GL_MINOR_VERSION, &minor);
	if (major == 3 && minor < 2)
	{
		halo_glCopyImageSubData = (__typeof__(halo_glCopyImageSubData))gl_extension_function(
			"glCopyImageSubData", "copy_image");
		halo_glDrawElementsBaseVertex = (__typeof__(halo_glDrawElementsBaseVertex))gl_extension_function(
			"glDrawElementsBaseVertex", "draw_elements_base_vertex");
	}
	return TRUE;
}
#else
int gl_functions_load(void)
{
	int success = TRUE;

#define GL_LOAD_FUNCTION(name) \
	halo_##name = (__typeof__(halo_##name))SDL_GL_GetProcAddress(#name); \
	if (!halo_##name) \
	{ \
		platform_log("OpenGL function %s is unavailable", #name); \
		success = FALSE; \
	}
	GL_FUNCTIONS(GL_LOAD_FUNCTION)
#undef GL_LOAD_FUNCTION
	return success;
}
#endif

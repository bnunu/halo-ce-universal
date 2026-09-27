/*
HOST_SDL.C

SDL3 on behalf of the guest (guest/runtime/guest_sdl.c). SDL objects are
64-bit pointers, which the guest cannot hold; it gets small handles into the
table here instead.

SDL video runs on the main thread. Audio mixing runs on a worker with a
guest stack, and output returns to SDL's callback thread to avoid taking
SDL's stream lock recursively from a different thread.
*/

#include "host.h"

#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <SDL3/SDL.h>
#include <pthread.h>
#include <string.h>

#define HANDLE_COUNT 256

enum handle_type {
    _handle_free,
    _handle_window,
    _handle_context,
    _handle_gamepad,
    _handle_audio,
};

struct handle {
    int type;
    void *object;
};

static struct handle handles[HANDLE_COUNT];
static pthread_mutex_t handle_lock = PTHREAD_MUTEX_INITIALIZER;

static uint32_t handle_new(int type, void *object) {
    uint32_t index;

    if (!object)
        return 0;
    pthread_mutex_lock(&handle_lock);
    /* an object that already has a handle keeps it */
    for (index = 1; index < HANDLE_COUNT; index++) {
        if (handles[index].type == type && handles[index].object == object) {
            pthread_mutex_unlock(&handle_lock);
            return index;
        }
    }
    for (index = 1; index < HANDLE_COUNT; index++) {
        if (handles[index].type == _handle_free) {
            handles[index].type = type;
            handles[index].object = object;
            pthread_mutex_unlock(&handle_lock);
            return index;
        }
    }
    pthread_mutex_unlock(&handle_lock);
    host_logf(HOST_LOG_ERROR, "out of SDL handles");
    return 0;
}

static void *handle_get(uint32_t handle, int type) {
    void *object = NULL;

    if (handle == 0 || handle >= HANDLE_COUNT)
        return NULL;
    pthread_mutex_lock(&handle_lock);
    if (handles[handle].type == type)
        object = handles[handle].object;
    pthread_mutex_unlock(&handle_lock);
    return object;
}

static EGLDisplay metal_display;
static EGLContext metal_context;
static EGLSurface metal_surface;
static int requested_minor;
static SDL_Window *metal_window;
static SDL_MetalView metal_view;

/* ---------- general */

int host_sdl_init(uint32_t flags) { return SDL_Init((SDL_InitFlags)flags); }

int host_sdl_set_hint(const char *name, const char *value) { return SDL_SetHint(name, value); }

void host_sdl_get_error(char *buffer, uint32_t size) { SDL_strlcpy(buffer, SDL_GetError(), size); }

int64_t host_sdl_ticks(void) { return (int64_t)SDL_GetTicks(); }

int64_t host_sdl_thread_id(void) { return (int64_t)SDL_GetCurrentThreadID(); }

/* ---------- video */

uint32_t host_sdl_create_window(const char *title, int width, int height, int64_t flags) {
    (void)flags;
    const char *windowed = SDL_getenv("HALO_WINDOWED");
    SDL_WindowFlags mode = SDL_WINDOW_METAL | SDL_WINDOW_RESIZABLE | SDL_WINDOW_HIGH_PIXEL_DENSITY;
    if (!windowed || !SDL_atoi(windowed)) mode |= SDL_WINDOW_FULLSCREEN;
    metal_window = SDL_CreateWindow(title, width > 0 ? width : 1280, height > 0 ? height : 960,
                                    mode);
    if (metal_window) {
        SDL_SyncWindow(metal_window);
        int w, h;
        SDL_GetWindowSizeInPixels(metal_window, &w, &h);
        host_logf(HOST_LOG_INFO, "Metal drawable %dx%d (%s)", w, h,
                  (mode & SDL_WINDOW_FULLSCREEN) ? "borderless fullscreen" : "windowed");
    }
    return handle_new(_handle_window, metal_window);
}

void host_sdl_window_size_in_pixels(uint32_t window, int *width, int *height) {
    SDL_Window *object = handle_get(window, _handle_window);

    *width = 0;
    *height = 0;
    if (object)
        SDL_GetWindowSizeInPixels(object, width, height);
}

int host_sdl_set_relative_mouse(uint32_t window, int enabled) {
    SDL_Window *object = handle_get(window, _handle_window);

    return object ? SDL_SetWindowRelativeMouseMode(object, enabled != 0) : 0;
}

int host_sdl_gl_set_attribute(int attribute, int value) {
    if (attribute == SDL_GL_CONTEXT_MINOR_VERSION)
        requested_minor = value;
    return 1;
}
uint32_t host_sdl_gl_create_context(uint32_t window) {
    SDL_Window *object = handle_get(window, _handle_window);
    if (!object || requested_minor > 0) {
        SDL_SetError("ANGLE Metal uses ES 3.0");
        return 0;
    }
    PFNEGLGETPLATFORMDISPLAYEXTPROC getDisplay =
        (void *)eglGetProcAddress("eglGetPlatformDisplayEXT");
    const EGLint displayAttributes[] = {0x3203, 0x3489, EGL_NONE};
    metal_display = getDisplay ? getDisplay(0x3202, (void *)0, displayAttributes) : EGL_NO_DISPLAY;
    EGLint major, minor, count;
    if (metal_display == EGL_NO_DISPLAY || !eglInitialize(metal_display, &major, &minor)) {
        SDL_SetError("Cannot initialize ANGLE Metal: %x", eglGetError());
        return 0;
    }
    const EGLint configAttributes[] = {EGL_SURFACE_TYPE,
                                       EGL_WINDOW_BIT,
                                       EGL_RENDERABLE_TYPE,
                                       EGL_OPENGL_ES3_BIT,
                                       EGL_RED_SIZE,
                                       8,
                                       EGL_GREEN_SIZE,
                                       8,
                                       EGL_BLUE_SIZE,
                                       8,
                                       EGL_ALPHA_SIZE,
                                       8,
                                       EGL_DEPTH_SIZE,
                                       24,
                                       EGL_STENCIL_SIZE,
                                       8,
                                       EGL_NONE};
    EGLConfig config;
    if (!eglChooseConfig(metal_display, configAttributes, &config, 1, &count) || !count)
        return 0;
    eglBindAPI(EGL_OPENGL_ES_API);
    const EGLint contextAttributes[] = {EGL_CONTEXT_CLIENT_VERSION, 3, EGL_NONE};
    metal_context = eglCreateContext(metal_display, config, EGL_NO_CONTEXT, contextAttributes);
    metal_view = SDL_Metal_CreateView(object);
    metal_surface = eglCreateWindowSurface(
        metal_display, config, (EGLNativeWindowType)SDL_Metal_GetLayer(metal_view), NULL);
    if (metal_context == EGL_NO_CONTEXT || metal_surface == EGL_NO_SURFACE) {
        SDL_SetError("Cannot create Metal surface: %x", eglGetError());
        return 0;
    }
    eglMakeCurrent(metal_display, metal_surface, metal_surface, metal_context);
#if defined(HALO_IOS) && !defined(HALO_IOS_MAC_CHECK)
    // Attach controls after SDL has installed the Metal view, otherwise
    // the drawable can cover the controller's UIKit overlay.
    extern void host_ios_controls_initialize(SDL_Window *);
    host_ios_controls_initialize(object);
#endif
    return handle_new(_handle_context, metal_context);
}
int host_sdl_gl_make_current(uint32_t window, uint32_t context) {
    (void)window;
    return eglMakeCurrent(metal_display, metal_surface, metal_surface,
                          handle_get(context, _handle_context));
}
int host_sdl_gl_set_swap_interval(int interval) { return eglSwapInterval(metal_display, interval); }
int host_sdl_gl_swap_window(uint32_t window) {
    (void)window;
    uint64_t start = SDL_GetTicksNS();
    int result = eglSwapBuffers(metal_display, metal_surface);
    host_perf_frame((SDL_GetTicksNS() - start) / 1e6);
    return result;
}

int host_sdl_poll_event(void *event) {
    SDL_Event host_event;

    if (!SDL_PollEvent(&host_event))
        return 0;
    /* the layouts agree except for the pointers of text, drop and user
    events, which the guest does not read */
    memcpy(event, &host_event, sizeof(host_event));
    return 1;
}

/* ---------- gamepads */

int host_sdl_get_gamepads(uint32_t *ids, int capacity) {
    int count = 0, index;
    SDL_JoystickID *list = SDL_GetGamepads(&count);

    if (!list)
        return 0;
    if (count > capacity)
        count = capacity;
    for (index = 0; index < count; index++)
        ids[index] = list[index];
    SDL_free(list);
    return count;
}

uint32_t host_sdl_open_gamepad(uint32_t id) {
    SDL_Gamepad *gamepad = SDL_OpenGamepad((SDL_JoystickID)id);

    if (gamepad)
        host_logf(HOST_LOG_INFO, "gamepad %u: %s (type %d, %04x:%04x)", (unsigned)id,
                  SDL_GetGamepadName(gamepad), (int)SDL_GetGamepadType(gamepad),
                  SDL_GetGamepadVendor(gamepad), SDL_GetGamepadProduct(gamepad));
    return handle_new(_handle_gamepad, gamepad);
}

uint32_t host_sdl_gamepad_from_id(uint32_t id) {
    return handle_new(_handle_gamepad, SDL_GetGamepadFromID((SDL_JoystickID)id));
}

int host_sdl_gamepad_axis(uint32_t gamepad, int axis) {
    SDL_Gamepad *object = handle_get(gamepad, _handle_gamepad);

    return object ? SDL_GetGamepadAxis(object, (SDL_GamepadAxis)axis) : 0;
}

int host_sdl_gamepad_button(uint32_t gamepad, int button) {
    SDL_Gamepad *object = handle_get(gamepad, _handle_gamepad);

    return object ? SDL_GetGamepadButton(object, (SDL_GamepadButton)button) : 0;
}

int host_sdl_gamepad_type(uint32_t gamepad) {
    SDL_Gamepad *object = handle_get(gamepad, _handle_gamepad);

    return object ? SDL_GetGamepadType(object) : SDL_GAMEPAD_TYPE_UNKNOWN;
}

int host_sdl_rumble_gamepad(uint32_t gamepad, uint32_t low, uint32_t high, uint32_t milliseconds) {
    SDL_Gamepad *object = handle_get(gamepad, _handle_gamepad);

    return object ? SDL_RumbleGamepad(object, (Uint16)low, (Uint16)high, milliseconds) : 0;
}

/* ---------- audio */

/* SDL calls audio_callback on its own audio thread, which cannot run guest
code; it passes each request to the stream's thread (audio_thread), which
can, and waits for it to be done */
struct audio_binding {
    uint32_t handle;
    uint32_t callback;
    uint32_t userdata;
    pthread_mutex_t lock;
    pthread_cond_t requested;
    pthread_cond_t done;
    int pending;
    int additional;
    int total;
    unsigned char *staging;
    size_t staging_length;
    size_t staging_capacity;
};
static struct audio_binding *audio_bindings[HANDLE_COUNT];

static void *audio_thread(void *context) {
    struct audio_binding *binding = context;

    pthread_mutex_lock(&binding->lock);
    for (;;) {
        int additional, total;

        while (!binding->pending)
            pthread_cond_wait(&binding->requested, &binding->lock);
        additional = binding->additional;
        total = binding->total;
        pthread_mutex_unlock(&binding->lock);
        host_call_guest(binding->callback, binding->userdata, binding->handle, (uint32_t)additional,
                        (uint32_t)total);
        pthread_mutex_lock(&binding->lock);
        binding->pending = 0;
        pthread_cond_signal(&binding->done);
    }
    return NULL;
}

static void SDLCALL audio_callback(void *userdata, SDL_AudioStream *stream, int additional,
                                   int total) {
    struct audio_binding *binding = userdata;

    (void)stream;
    pthread_mutex_lock(&binding->lock);
    binding->additional = additional;
    binding->total = total;
    binding->pending = 1;
    pthread_cond_signal(&binding->requested);
    while (binding->pending)
        pthread_cond_wait(&binding->done, &binding->lock);
    /* SDL invokes its callback with the stream locked. The guest mixer runs
     * on a different thread, so its output is staged and submitted here on
     * the callback thread. Calling SDL_PutAudioStreamData from that worker
     * would deadlock on SDL's stream lock while this callback waited. */
    if (binding->staging_length) {
        if (!SDL_PutAudioStreamData(stream, binding->staging, (int)binding->staging_length))
            host_logf(HOST_LOG_ERROR, "Audio submission failed: %s", SDL_GetError());
        binding->staging_length = 0;
    }
    pthread_mutex_unlock(&binding->lock);
}

uint32_t host_sdl_open_audio_stream(uint32_t device, const void *spec, uint32_t callback,
                                    uint32_t userdata) {
    struct audio_binding *binding = SDL_calloc(1, sizeof(*binding));
    SDL_AudioStream *stream;
    if (!binding)
        return 0;

    binding->callback = callback;
    binding->userdata = userdata;
    pthread_mutex_init(&binding->lock, NULL);
    pthread_cond_init(&binding->requested, NULL);
    pthread_cond_init(&binding->done, NULL);
    stream = SDL_OpenAudioDeviceStream((SDL_AudioDeviceID)device, spec,
                                       callback ? audio_callback : NULL, binding);
    if (!stream) {
        SDL_free(binding);
        return 0;
    }
    /* the device starts paused, so no callback can run before this */
    binding->handle = handle_new(_handle_audio, stream);
    audio_bindings[binding->handle] = binding;
    if (callback && host_native_thread_create(audio_thread, binding, 256 * 1024) != 0)
        host_fatal("cannot start the audio thread");
    return binding->handle;
}

int host_sdl_put_audio_stream_data(uint32_t stream, const void *data, int length) {
    if (stream >= HANDLE_COUNT || length < 0)
        return 0;
    struct audio_binding *binding = audio_bindings[stream];
    if (!binding)
        return 0;
    pthread_mutex_lock(&binding->lock);
    size_t needed = binding->staging_length + (size_t)length;
    if (needed > binding->staging_capacity) {
        size_t capacity = (needed + 16383) & ~(size_t)16383;
        void *buffer = SDL_realloc(binding->staging, capacity);
        if (!buffer) {
            pthread_mutex_unlock(&binding->lock);
            return 0;
        }
        binding->staging = buffer;
        binding->staging_capacity = capacity;
    }
    memcpy(binding->staging + binding->staging_length, data, (size_t)length);
    binding->staging_length = needed;
    pthread_mutex_unlock(&binding->lock);
    return 1;
}

int host_sdl_resume_audio_stream_device(uint32_t stream) {
    SDL_AudioStream *object = handle_get(stream, _handle_audio);

    return object ? SDL_ResumeAudioStreamDevice(object) : 0;
}

/* A real SDL callback must be able to consume output from the guest worker. */
#include "host.h"
#include <SDL3/SDL.h>
#include <assert.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>

extern uint32_t host_sdl_open_audio_stream(uint32_t, const void *, uint32_t, uint32_t);
extern int host_sdl_put_audio_stream_data(uint32_t, const void *, int);
extern int host_sdl_resume_audio_stream_device(uint32_t);
static unsigned mixed_callbacks;
void host_perf_frame(double swap_ms) { (void)swap_ms; }

void host_logf(int priority, const char *format, ...) {
    (void)priority;
    va_list arguments;
    va_start(arguments, format);
    vfprintf(stderr, format, arguments);
    va_end(arguments);
}
void host_fatal(const char *format, ...) {
    fprintf(stderr, "%s\n", format);
    exit(1);
}
int host_native_thread_create(void *(*function)(void *), void *argument, size_t size) {
    (void)size;
    pthread_t thread;
    int error = pthread_create(&thread, NULL, function, argument);
    if (!error)
        pthread_detach(thread);
    return error;
}
uint32_t host_call_guest(uint32_t callback, uint32_t userdata, uint32_t stream, uint32_t additional,
                         uint32_t total) {
    (void)callback;
    (void)userdata;
    (void)total;
    float samples[512];
    for (unsigned i = 0; i < 512; i++)
        samples[i] = (i & 1) ? 0.125f : -0.125f;
    while (additional) {
        unsigned bytes = additional < sizeof(samples) ? additional : sizeof(samples);
        assert(host_sdl_put_audio_stream_data(stream, samples, (int)bytes));
        additional -= bytes;
    }
    __atomic_add_fetch(&mixed_callbacks, 1, __ATOMIC_RELEASE);
    return 0;
}
int main(void) {
    SDL_SetHint(SDL_HINT_AUDIO_DRIVER, "dummy");
    assert(SDL_Init(SDL_INIT_AUDIO));
    SDL_AudioSpec spec = {.format = SDL_AUDIO_F32, .channels = 2, .freq = 48000};
    uint32_t stream = host_sdl_open_audio_stream(SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK, &spec, 1, 0);
    assert(stream);
    assert(host_sdl_resume_audio_stream_device(stream));
    for (int i = 0; i < 200 && __atomic_load_n(&mixed_callbacks, __ATOMIC_ACQUIRE) < 4; i++)
        SDL_Delay(10);
    assert(__atomic_load_n(&mixed_callbacks, __ATOMIC_ACQUIRE) >= 4);
    puts("SDL audio callback/guest worker handoff passed without deadlock");
    return 0;
}

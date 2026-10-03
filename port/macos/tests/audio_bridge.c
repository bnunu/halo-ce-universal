/* A real SDL callback must be able to consume output from the guest worker. */
#include "host.h"
#include <SDL3/SDL.h>
#include <assert.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

extern uint32_t host_sdl_open_audio_stream(uint32_t, const void *, uint32_t, uint32_t);
extern int host_sdl_put_audio_stream_data(uint32_t, const void *, int);
extern int host_sdl_resume_audio_stream_device(uint32_t);
extern int host_sdl_init(uint32_t);
extern int host_sdl_poll_event(void *);
static unsigned mixed_callbacks;
void host_perf_frame(double swap_ms) { (void)swap_ms; }
void host_menu_window_changed(void) {}

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
    assert(host_sdl_init(SDL_INIT_AUDIO | SDL_INIT_EVENTS));
    /* Cocoa delivers opened URLs using native drop events. The URL must
       reach the instance's save folder without leaking a 64-bit pointer
       into the guest's 32-bit event layout. */
    char directory[] = "/tmp/halo-invite-event.XXXXXX";
    assert(mkdtemp(directory));
    assert(setenv("HALO_SAVE_ROOT", directory, 1) == 0);
    const char *invite = "halo://join/0123456789abcdef0123456789abcdeffedcba9876543210fedcba9876543210";
    SDL_Event drop = {.type = SDL_EVENT_DROP_FILE};
    drop.drop.data = invite;
    assert(SDL_PushEvent(&drop));
    SDL_Event guest_event;
    int consumed = 0;
    for (int i = 0; i < 20 && host_sdl_poll_event(&guest_event); i++) {
        if (!guest_event.type) {
            SDL_Event empty = {0};
            assert(memcmp(&guest_event, &empty, sizeof(empty)) == 0);
            consumed = 1;
            break;
        }
    }
    assert(consumed);
    char path[4096], text[128];
    snprintf(path, sizeof(path), "%s/join_link.txt", directory);
    FILE *file = fopen(path, "r");
    assert(file && fgets(text, sizeof(text), file));
    fclose(file);
    assert(strcmp(text, invite) == 0);
    assert(unlink(path) == 0 && rmdir(directory) == 0);
    puts("SDL opened-invite event delivered without a native pointer in the guest");
    /* Command-W must not turn a movement key into a quit, while the
       window's close button and Command-Q still deliver a quit event. */
    SDL_FlushEvents(SDL_EVENT_FIRST, SDL_EVENT_LAST);
    SDL_Event command = {.type = SDL_EVENT_KEY_DOWN};
    command.key.scancode = SDL_SCANCODE_LGUI;
    command.key.mod = SDL_KMOD_GUI;
    command.key.down = true;
    assert(SDL_PushEvent(&command));
    SDL_Event close = {.type = SDL_EVENT_WINDOW_CLOSE_REQUESTED};
    assert(SDL_PushEvent(&close));
    command.type = SDL_EVENT_KEY_UP;
    command.key.mod = SDL_KMOD_NONE;
    command.key.down = false;
    assert(SDL_PushEvent(&command));
    assert(SDL_PushEvent(&close));
    SDL_Event quit = {.type = SDL_EVENT_QUIT};
    assert(SDL_PushEvent(&quit));
    int suppressed = 0, quits = 0;
    while (host_sdl_poll_event(&guest_event)) {
        suppressed += guest_event.type == 0;
        quits += guest_event.type == SDL_EVENT_QUIT;
    }
    assert(suppressed == 1 && quits == 2);
    puts("Command-W ignored; window close and Command-Q still quit");
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

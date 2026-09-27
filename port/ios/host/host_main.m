/* SDL owns UIApplication and invokes this entry on the UIKit main thread. */
#include "host.h"
#include <SDL3/SDL.h>
#include <SDL3/SDL_main.h>
#import <Foundation/Foundation.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
static char data_root[4096], save_root[4096];
void host_logf(int priority, const char *format, ...) {
    (void)priority;
    va_list a; va_start(a, format); vfprintf(stderr, format, a); va_end(a);
    fputc('\n', stderr);
}
void host_log(int priority, const char *text) { host_logf(priority, "%s", text); }
void host_fatal(const char *format, ...) {
    char message[2048];
    va_list a; va_start(a, format); vsnprintf(message, sizeof(message), format, a); va_end(a);
    host_logf(HOST_LOG_ERROR, "%s", message);
    SDL_ShowSimpleMessageBox(SDL_MESSAGEBOX_ERROR, "Halo could not start", message, NULL);
    exit(1);
}
void host_abort(const char *reason) { host_fatal("Game stopped: %s", reason); }
void host_exit(int code) { host_logf(HOST_LOG_INFO, "Game exited (%d)", code); exit(code); }
int host_errno(void) { return host_linux_errno(errno); }
void host_android_path(int which, char *buffer, uint32_t size) {
    snprintf(buffer, size, "%s", which ? save_root : data_root);
}
extern char **environ;
static uint32_t make_boot(void) {
    size_t size = 0x20000;
    char *memory = host_low_map(size, PROT_READ | PROT_WRITE);
    if (!memory) host_fatal("Cannot allocate game startup memory.");
    struct halo_guest_boot *boot = (void *)memory;
    uint32_t *args = (void *)(memory + sizeof(*boot)), *env = args + 2;
    char *strings = (void *)(env + 256);
    unsigned count = 0;
    strcpy(strings, "halo"); args[0] = (uint32_t)(uintptr_t)strings; args[1] = 0; strings += 5;
    for (char **p = environ; *p && count < 255; p++) {
        size_t n = strlen(*p) + 1;
        if (strings + n > memory + size) break;
        memcpy(strings, *p, n); env[count++] = (uint32_t)(uintptr_t)strings; strings += n;
    }
    env[count] = 0;
    *boot = (struct halo_guest_boot){1, (uint32_t)(uintptr_t)args,
        (uint32_t)(uintptr_t)env, HALO_MACOS_PAGE};
    return (uint32_t)(uintptr_t)boot;
}
extern void macos_enter_guest_stack(void *, uint32_t) __attribute__((noreturn));
int main(int argc, char **argv) {
    (void)argc; (void)argv;
    @autoreleasepool {
        NSFileManager *files = NSFileManager.defaultManager;
        NSString *documents = NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES).firstObject;
        NSString *data = [documents stringByAppendingPathComponent:@"GameData"];
        [files createDirectoryAtPath:data withIntermediateDirectories:YES attributes:nil error:NULL];
        if (![files fileExistsAtPath:[data stringByAppendingPathComponent:@"maps/ui.map"]])
            data = [NSBundle.mainBundle.resourcePath stringByAppendingPathComponent:@"GameData"];
        NSString *saves = [NSSearchPathForDirectoriesInDomains(NSApplicationSupportDirectory, NSUserDomainMask, YES).firstObject stringByAppendingPathComponent:@"Halo"];
        [files createDirectoryAtPath:saves withIntermediateDirectories:YES attributes:nil error:NULL];
        snprintf(data_root, sizeof(data_root), "%s", data.fileSystemRepresentation);
        snprintf(save_root, sizeof(save_root), "%s", saves.fileSystemRepresentation);
        freopen([[saves stringByAppendingPathComponent:@"halo.log"] fileSystemRepresentation], "w", stderr);
        setbuf(stderr, NULL);
        if (![files fileExistsAtPath:[data stringByAppendingPathComponent:@"maps/ui.map"]])
            host_fatal("Copy your Xbox Halo maps folder into Halo's GameData folder using Files or Finder, then reopen the app.");
    }
    host_install_signal_handlers();
    setenv("HALO_DATA_ROOT", data_root, 1); setenv("HALO_SAVE_ROOT", save_root, 1);
    SDL_SetHint(SDL_HINT_ORIENTATIONS, "LandscapeLeft LandscapeRight");
    SDL_SetHint(SDL_HINT_IOS_HIDE_HOME_INDICATOR, "2");
    if (!SDL_InitSubSystem(SDL_INIT_VIDEO | SDL_INIT_GAMEPAD))
        host_fatal("Cannot initialize display: %s", SDL_GetError());
    const SDL_DisplayMode *display = SDL_GetDesktopDisplayMode(SDL_GetPrimaryDisplay());
    if (display && display->h > 0 && display->w > 0) {
        int long_side = display->w > display->h ? display->w : display->h;
        int short_side = display->w < display->h ? display->w : display->h;
        char width[32]; snprintf(width, sizeof(width), "%d", (480 * long_side / short_side) & ~1);
        setenv("HALO_DISPLAY_WIDTH", width, 0);
    }
    if (host_load_image(NULL, 0)) host_fatal("Cannot initialize game memory. Check the app's Extended Virtual Addressing signing capability.");
    uint32_t boot = make_boot();
    size_t stack_size = 16 * 1024 * 1024;
    char *stack = host_low_map(stack_size + HALO_MACOS_PAGE, PROT_READ | PROT_WRITE);
    if (!stack) host_fatal("Cannot allocate game stack.");
    mprotect(stack, HALO_MACOS_PAGE, PROT_NONE);
    host_logf(HOST_LOG_INFO, "Halo iOS starting; data %s; saves %s", data_root, save_root);
    macos_enter_guest_stack(stack + stack_size + HALO_MACOS_PAGE, boot);
}

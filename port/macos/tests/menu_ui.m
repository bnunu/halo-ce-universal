/* The real menu/settings and SDL bridge, in a separate bundle with test saves. */
#import <Cocoa/Cocoa.h>
#define SDL_MAIN_HANDLED
#include <SDL3/SDL.h>
#include <SDL3/SDL_main.h>
#include "host_menu.h"
#include <assert.h>
#include <arpa/inet.h>
#include <fcntl.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>
extern uint32_t host_sdl_create_window(const char *, int, int, int64_t);

@protocol MenuActions
- (void)showSettings:(id)sender;
- (void)closeSettings:(id)sender;
- (void)selectFolder:(id)sender;
- (void)selectImage:(id)sender;
- (void)openConfig:(id)sender;
- (void)importImage:(NSURL *)image completion:(void (^)(BOOL))completion;
@end

static void check_main_loop(const char *image) {
    NSMenuItem *settings = NSApp.mainMenu.itemArray[0].submenu.itemArray[1];
    id<MenuActions> target = settings.target;
    int sender = socket(AF_INET, SOCK_DGRAM, 0), receiver = socket(AF_INET, SOCK_DGRAM, 0);
    assert(sender >= 0 && receiver >= 0);
    struct sockaddr_in address = {.sin_family = AF_INET, .sin_addr.s_addr = htonl(INADDR_LOOPBACK)};
    assert(bind(receiver, (void *)&address, sizeof(address)) == 0);
    socklen_t size = sizeof(address);
    assert(getsockname(receiver, (void *)&address, &size) == 0);
    assert(fcntl(receiver, F_SETFL, O_NONBLOCK) == 0);
    __block BOOL imported = NO;
    unsigned step = 0, ticks = 0, received = 0;
    BOOL quit = NO;
    Uint64 started = SDL_GetTicks();
    while (!quit && SDL_GetTicks() - started < 10000) {
        Uint64 elapsed = SDL_GetTicks() - started;
        NSWindow *window = [(id)target valueForKey:@"settingsWindow"];
        if (step == 0) {
            [NSApp sendAction:settings.action to:settings.target from:settings];
            assert(!NSApp.modalWindow);
            step++;
        } else if (step == 1 && elapsed > 400) {
            assert(window.visible);
            [target selectFolder:nil];
            assert(window.attachedSheet && !NSApp.modalWindow);
            step++;
        } else if (step == 2 && elapsed > 900) {
            [window endSheet:window.attachedSheet returnCode:NSModalResponseCancel];
            step++;
        } else if (step == 3 && elapsed > 1400) {
            assert(!window.attachedSheet);
            [target selectImage:nil];
            assert(window.attachedSheet && !NSApp.modalWindow);
            step++;
        } else if (step == 4 && elapsed > 1900) {
            [window endSheet:window.attachedSheet returnCode:NSModalResponseCancel];
            step++;
        } else if (step == 5 && elapsed > 2400) {
            assert(!window.attachedSheet);
            [target importImage:[NSURL fileURLWithPath:@(image)] completion:^(BOOL success) {
                assert(success);
                imported = YES;
            }];
            assert(!imported && !NSApp.modalWindow);
            step++;
        } else if (step == 6 && imported && elapsed > 2900) {
            [target openConfig:nil];
            assert(window.attachedSheet && !NSApp.modalWindow);
            step++;
        } else if (step == 7 && elapsed > 3400) {
            [target closeSettings:nil];
            assert(!window.visible);
            step++;
        } else if (step == 8 && elapsed > 3900) {
            [target showSettings:nil];
            [target selectFolder:nil];
            assert(window.attachedSheet);
            [NSApp terminate:nil];
            assert(!window.visible && !NSApp.modalWindow);
            step++;
        }
        assert(sendto(sender, &ticks, sizeof(ticks), 0, (void *)&address, sizeof(address)) == sizeof(ticks));
        struct pollfd ready = {.fd = receiver, .events = POLLIN};
        assert(poll(&ready, 1, 100) == 1);
        unsigned packet;
        if (recv(receiver, &packet, sizeof(packet), 0) == sizeof(packet)) received++;
        SDL_Event event;
        while (SDL_PollEvent(&event)) quit |= event.type == SDL_EVENT_QUIT;
        /* Match the game: SDL pumps Cocoa, without a nested AppKit loop. */
        SDL_Delay(10);
        ticks++;
    }
    close(sender);
    close(receiver);
    fprintf(stderr, "Menu loop: quit=%d imported=%d step=%u ticks=%u packets=%u\n", quit, imported, step, ticks, received);
    assert(quit && imported && step == 9 && ticks >= 20 && received == ticks);
    printf("Settings, folder/image sheets, import and quit kept the main loop running (%u packets)\n", received);
}

int main(int argc, const char **argv) {
    @autoreleasepool {
        assert(argc == 3 || argc == 4);
        printf("Menu UI test PID %d\n", getpid());
        fflush(stdout);
        host_menu_initialize_application();
        SDL_SetMainReady();
        SDL_SetHint(SDL_HINT_VIDEO_MAC_FULLSCREEN_SPACES, "0");
        SDL_SetHint(SDL_HINT_VIDEO_MAC_FULLSCREEN_MENU_VISIBILITY, "1");
        SDL_SetHint(SDL_HINT_WINDOW_ALLOW_TOPMOST, "0");
        assert(SDL_Init(SDL_INIT_VIDEO));
        char data[4096];
        if (!host_menu_prepare(argv[1], argv[2], data, sizeof(data))) {
            SDL_Quit();
            return 0;
        }
        assert(host_sdl_create_window("Halo Menu Test", 640, 480, 0));
        host_menu_begin_game();
        if (argc == 4) {
            check_main_loop(argv[3]);
            host_menu_finish_game(0);
            SDL_Quit();
            return 0;
        }
        [NSTimer scheduledTimerWithTimeInterval:0.05 repeats:YES block:^(NSTimer *timer) {
            SDL_Event event;
            while (SDL_PollEvent(&event)) {
                if (event.type == SDL_EVENT_QUIT) {
                    [timer invalidate];
                    [NSApp stop:nil];
                }
            }
        }];
        /* Open the actual settings panel without a moving/captured game canvas. */
        [NSTimer scheduledTimerWithTimeInterval:0.1 repeats:NO block:^(NSTimer *timer) {
            (void)timer;
            NSMenuItem *settings = NSApp.mainMenu.itemArray[0].submenu.itemArray[1];
            [NSApp sendAction:settings.action to:settings.target from:settings];
        }];
        [NSApp run];
        host_menu_finish_game(0);
        SDL_Quit();
    }
    return 0;
}

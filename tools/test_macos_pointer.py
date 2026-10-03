"""Compile the real Mac mouse bridges, SDL event paths and controller mapping.

Only OS calls, the event queue and unrelated renderer/network services are
stubbed. No window, app, game data, PB menu or settings binding is required.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SDL = Path(os.environ.get("HALO_MACOS_SDL_PREFIX", "/opt/homebrew/opt/sdl3"))


def function(source, signature):
    """Keep production function bodies intact, ignoring braces inside literals."""
    start = source.index(signature)
    opening = source.index("{", start)
    tokens = re.finditer(
        r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[{}]',
        source[opening:], re.S,
    )
    depth = 0
    for token in tokens:
        if token.group() == "{":
            depth += 1
        elif token.group() == "}":
            depth -= 1
            if not depth:
                return source[start:opening + token.end()]
    raise ValueError(f"Unclosed production function: {signature}")


PREFIX = r'''
#define HALO_ANDROID 1
#define HALO_MACOS 1
#include <SDL3/SDL.h>
#include <assert.h>
#include <math.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef int BOOL;
typedef unsigned char BYTE;
typedef char CHAR;
typedef short SHORT;
#define TRUE 1
#define FALSE 0
#include "port/linux/src/sdl_platform.h"
#include "port/linux/include/halo_ui_pointer.h"
#include "port/macos/native_events.h"
typedef struct {
    unsigned short wButtons;
    BYTE bAnalogButtons[8];
    SHORT sThumbLX, sThumbLY, sThumbRX, sThumbRY;
} XINPUT_GAMEPAD;
enum {
    XINPUT_GAMEPAD_A, XINPUT_GAMEPAD_B, XINPUT_GAMEPAD_X, XINPUT_GAMEPAD_Y,
    XINPUT_GAMEPAD_BLACK, XINPUT_GAMEPAD_WHITE,
    XINPUT_GAMEPAD_LEFT_TRIGGER, XINPUT_GAMEPAD_RIGHT_TRIGGER,
    XINPUT_GAMEPAD_DPAD_UP=1, XINPUT_GAMEPAD_DPAD_DOWN=2,
    XINPUT_GAMEPAD_DPAD_LEFT=4, XINPUT_GAMEPAD_DPAD_RIGHT=8,
    XINPUT_GAMEPAD_START=16, XINPUT_GAMEPAD_BACK=32,
    XINPUT_GAMEPAD_LEFT_THUMB=64, XINPUT_GAMEPAD_RIGHT_THUMB=128
};
static SDL_Window *platform_window;
static SDL_ThreadID platform_event_thread=1;
static SDL_Window *metal_window=(SDL_Window *)(uintptr_t)0x3333;
static int metal_window_hidden;
enum {_handle_window=1};
static SDL_Event events[128];
static unsigned event_count, event_read, warps, raises, capture_calls;
static int window_width=800, window_height=600, pixel_width=1600, pixel_height=1200;
static bool captured=true, capture_succeeds=true;
static float warp_x, warp_y;
static Uint64 ticks=100, wheel_press_until_ms;
static void *handle_get(uint32_t handle, int kind) {
    assert(kind==_handle_window);
    return handle==3 ? metal_window : NULL;
}
static bool native_window_size(SDL_Window *window, int *width, int *height) {
    assert(window==metal_window); *width=window_width; *height=window_height; return true;
}
static bool native_pixel_size(SDL_Window *window, int *width, int *height) {
    assert(window==metal_window); *width=pixel_width; *height=pixel_height; return true;
}
static void native_warp(SDL_Window *window, float x, float y) {
    assert(window==metal_window); warp_x=x; warp_y=y; warps++;
}
static bool native_relative(SDL_Window *window, bool enabled) {
    assert(window==metal_window); capture_calls++;
    if (!capture_succeeds && enabled) return false;
    captured=enabled; return true;
}
bool SDL_RaiseWindow(SDL_Window *window) {assert(window==metal_window); raises++; return true;}
bool SDL_PushEvent(SDL_Event *event) {
    assert(event_count<sizeof(events)/sizeof(events[0]));
    events[event_count++]=*event; return true;
}
bool SDL_PollEvent(SDL_Event *event) {
    if (event_read==event_count) return false;
    *event=events[event_read++]; return true;
}
Uint64 SDL_GetTicks(void) {return ticks;}
SDL_ThreadID SDL_GetCurrentThreadID(void) {return 1;}
SDL_Gamepad *SDL_OpenGamepad(SDL_JoystickID id) {(void)id; return NULL;}
static double config_real(const char *name) {(void)name; return 0.0;}
static void platform_log(const char *format, ...) {(void)format;}
static void platform_show_pending_message(void) {}
static void platform_invite_clipboard(BOOL look) {(void)look;}
/* The host calls native SDL; guest SDL below uses the real handle bridge. */
#define SDL_GetWindowSize native_window_size
#define SDL_GetWindowSizeInPixels native_pixel_size
#define SDL_WarpMouseInWindow native_warp
#define SDL_SetWindowRelativeMouseMode native_relative
/* HOST FUNCTIONS */
#undef SDL_GetWindowSize
#undef SDL_GetWindowSizeInPixels
#undef SDL_WarpMouseInWindow
#undef SDL_SetWindowRelativeMouseMode
/* GUEST FUNCTIONS */
/* PLATFORM GLOBALS */
/* PLATFORM FUNCTIONS */
struct render_target_entry {struct {int width,height,gl_width,gl_height;} target;};
static struct render_target_entry back_buffer={{640,480,640,480}};
static struct {int gl_ready,back_buffer;} device={1,0};
static struct render_target_entry *render_target_get(void *target) {(void)target; return &back_buffer;}
static long halo_screen_width(void) {return back_buffer.target.width;}
/* RENDERER POINTER */
/* CONTROLLER MAPPING */
'''

CHECKS = r'''
static void reset_fixture(void) {
    memset(&input_state,0,sizeof(input_state));
    memset(keys_pressed,0,sizeof(keys_pressed));
    memset(&ui_pointer,0,sizeof(ui_pointer));
    memset(keystroke_queue,0,sizeof(keystroke_queue));
    keystroke_head=keystroke_count=0;
    ui_pointer_wheel=scoreboard_wheel=0;
    scoreboard_open_until_ms=0; scoreboard_notches=scoreboard_pages=0;
    event_count=event_read=warps=raises=capture_calls=0;
    captured=capture_succeeds=true; input_state.focused=TRUE;
    platform_window=(SDL_Window *)(uintptr_t)3;
    window_width=800; window_height=600; pixel_width=1600; pixel_height=1200;
    back_buffer=(struct render_target_entry){{640,480,640,480}};
}
static void key(SDL_Scancode scancode, bool down) {
    SDL_Event e={.type=down ? SDL_EVENT_KEY_DOWN:SDL_EVENT_KEY_UP};
    e.key.scancode=scancode; e.key.key=SDLK_W; e.key.down=down;
    SDL_PushEvent(&e);
}
static void mouse(unsigned button, bool down, float x, float y) {
    SDL_Event e={.type=down ? SDL_EVENT_MOUSE_BUTTON_DOWN:SDL_EVENT_MOUSE_BUTTON_UP};
    e.button.button=(Uint8)button; e.button.down=down; e.button.x=x; e.button.y=y;
    SDL_PushEvent(&e);
}
static void motion(float x, float y, float dx, float dy) {
    SDL_Event e={.type=SDL_EVENT_MOUSE_MOTION};
    e.motion.x=x; e.motion.y=y; e.motion.xrel=dx; e.motion.yrel=dy;
    SDL_PushEvent(&e);
}
static void wheel(float amount) {
    SDL_Event e={.type=SDL_EVENT_MOUSE_WHEEL}; e.wheel.y=amount; SDL_PushEvent(&e);
}
static void focus(bool gained) {
    SDL_Event e={.type=gained ? SDL_EVENT_WINDOW_FOCUS_GAINED:SDL_EVENT_WINDOW_FOCUS_LOST};
    SDL_PushEvent(&e);
}
static XINPUT_GAMEPAD read_pad(void) {
    struct platform_input_state input; XINPUT_GAMEPAD pad={0};
    platform_input_read(&input,TRUE); keyboard_gamepad(&input,&pad); return pad;
}
static void assert_no_gameplay_input(void) {
    struct platform_input_state input; struct platform_keystroke stroke;
    platform_input_read(&input,TRUE);
    for (unsigned i=0;i<SDL_SCANCODE_COUNT;i++) assert(!input.keys[i]);
    for (unsigned i=0;i<PLATFORM_MOUSE_BUTTON_COUNT;i++) assert(!input.mouse_buttons[i]);
    assert(input.mouse_dx==0 && input.mouse_dy==0 && input.mouse_wheel==0);
    assert(!platform_next_keystroke(&stroke));
    XINPUT_GAMEPAD pad={0}; keyboard_gamepad(&input,&pad);
    assert(!pad.sThumbLX && !pad.sThumbLY);
    assert(!pad.bAnalogButtons[XINPUT_GAMEPAD_RIGHT_TRIGGER]);
    assert(!pad.bAnalogButtons[XINPUT_GAMEPAD_LEFT_TRIGGER]);
}
static void menus_and_retina(void) {
    reset_fixture(); struct halo_ui_pointer pointer;
    assert(halo_ui_pointer_update(1,&pointer));
    assert(!captured && warps==1 && warp_x==400 && warp_y==300);
    assert(pointer.x==320 && pointer.y==240);
    motion(200,150,80,50); mouse(SDL_BUTTON_LEFT,true,200,150);
    mouse(SDL_BUTTON_RIGHT,true,200,150); wheel(0.25f); wheel(0.75f);
    platform_pump_events();
    XINPUT_GAMEPAD pad=read_pad();
    assert(!pad.bAnalogButtons[XINPUT_GAMEPAD_RIGHT_TRIGGER]);
    assert(!pad.bAnalogButtons[XINPUT_GAMEPAD_LEFT_TRIGGER]);
    assert(input_state.mouse_dx==0 && input_state.mouse_dy==0 && input_state.mouse_wheel==0);
    assert(halo_ui_pointer_update(1,&pointer));
    assert(pointer.x==160 && pointer.y==120 && pointer.moved);
    assert(pointer.click_x==160 && pointer.click_y==120);
    assert(pointer.left_clicks==1 && pointer.right_clicks==1 && pointer.wheel_steps==1);
    assert(halo_ui_pointer_update(1,&pointer));
    assert(!pointer.left_clicks && !pointer.right_clicks && !pointer.wheel_steps && !pointer.moved);
    /* Widescreen uses logical window coordinates, then removes UI centering. */
    window_width=1000; window_height=500; pixel_width=2000; pixel_height=1000;
    back_buffer=(struct render_target_entry){{960,480,960,480}};
    motion(500,250,0,0); mouse(SDL_BUTTON_LEFT,true,500,250);
    platform_pump_events(); assert(halo_ui_pointer_update(1,&pointer));
    assert(pointer.x==320 && pointer.y==240 && pointer.click_x==320 && pointer.click_y==240);
    /* A point in a pillarbox remains outside the 640-wide menu. */
    window_width=1200; window_height=800; pixel_width=2400; pixel_height=1600;
    back_buffer=(struct render_target_entry){{640,480,640,480}};
    motion(0,400,0,0); platform_pump_events(); assert(halo_ui_pointer_update(1,&pointer));
    assert(pointer.x<0 && pointer.y==240);
    assert(!halo_ui_pointer_update(0,&pointer) && captured);
    pad=read_pad(); assert(!pad.bAnalogButtons[XINPUT_GAMEPAD_RIGHT_TRIGGER]);
}
static void native_release_and_focus(void) {
    reset_fixture();
    key(SDL_SCANCODE_W,true); mouse(SDL_BUTTON_LEFT,true,400,300);
    motion(400,300,20,-12); wheel(1); platform_pump_events();
    assert(input_state.keys[SDL_SCANCODE_W] && keys_pressed[SDL_SCANCODE_W]);
    assert(input_state.mouse_buttons[SDL_BUTTON_LEFT] && keystroke_count);
    /* The production Cocoa helper must send the actual private SDL event. */
    host_sdl_release_mouse(); assert(!captured);
    assert(events[event_count-1].type==SDL_EVENT_USER);
    assert(events[event_count-1].user.code==HALO_MACOS_MOUSE_RELEASE);
    platform_pump_events(); assert(input_state.mouse_released);
    assert_no_gameplay_input();
    host_sdl_show_game(); assert(raises==1 && !captured);
    focus(true); platform_pump_events(); assert(input_state.focused && !captured);
    /* Focus loss also discards a short key press queued between snapshots. */
    key(SDL_SCANCODE_W,true); key(SDL_SCANCODE_W,false); focus(false);
    platform_pump_events(); assert(!input_state.focused && input_state.mouse_released);
    assert_no_gameplay_input();
    /* A native panel cannot leave a queued menu action for the next frame. */
    struct halo_ui_pointer pointer; assert(halo_ui_pointer_update(1,&pointer));
    mouse(SDL_BUTTON_LEFT,true,400,300); wheel(1.5f); platform_pump_events();
    host_sdl_release_mouse(); platform_pump_events(); assert(halo_ui_pointer_update(1,&pointer));
    assert(!pointer.left_clicks && !pointer.right_clicks && !pointer.wheel_steps && ui_pointer_wheel==0);
}
static void recapture_without_firing(void) {
    reset_fixture(); host_sdl_release_mouse(); platform_pump_events();
    /* Failed OS capture leaves input released, and consumes its click. */
    capture_succeeds=false;
    motion(450,320,50,20); wheel(1); mouse(SDL_BUTTON_LEFT,true,450,320);
    platform_pump_events(); assert(input_state.mouse_released && !captured);
    assert_no_gameplay_input();
    mouse(SDL_BUTTON_LEFT,false,450,320); platform_pump_events();
    capture_succeeds=true;
    motion(500,350,90,30); wheel(2); mouse(SDL_BUTTON_LEFT,true,500,350);
    platform_pump_events(); assert(!input_state.mouse_released && captured);
    assert_no_gameplay_input();
    /* Only a later, fresh gameplay press is allowed to fire. */
    mouse(SDL_BUTTON_LEFT,false,500,350); platform_pump_events();
    assert(!read_pad().bAnalogButtons[XINPUT_GAMEPAD_RIGHT_TRIGGER]);
    mouse(SDL_BUTTON_LEFT,true,500,350); platform_pump_events();
    assert(read_pad().bAnalogButtons[XINPUT_GAMEPAD_RIGHT_TRIGGER]==255);
}
int main(int argc,char **argv) {
    assert(argc==2);
    if (!strcmp(argv[1],"menus")) menus_and_retina();
    else if (!strcmp(argv[1],"release")) native_release_and_focus();
    else if (!strcmp(argv[1],"recapture")) recapture_without_firing();
    else assert(0);
    puts("Production Mac mouse path passed");
}
'''


def fixture_source():
    platform = (ROOT / "port/linux/src/sdl_platform.c").read_text()
    host = (ROOT / "port/macos/host/host_sdl.c").read_text()
    guest = (ROOT / "port/android/guest/runtime/guest_sdl.c").read_text()
    renderer = (ROOT / "port/linux/src/d3d8_gl.c").read_text()
    controller = (ROOT / "port/linux/src/xinput_sdl.c").read_text()
    host_functions = "\n".join(function(host, name) for name in (
        "void host_sdl_window_size_in_pixels(", "void host_sdl_window_size(",
        "void host_sdl_warp_mouse(", "int host_sdl_set_relative_mouse(",
        "void host_sdl_release_mouse(", "void host_sdl_show_game(",
    ))
    guest_functions = "\n".join(function(guest, name) for name in (
        "bool SDL_GetWindowSizeInPixels(", "bool SDL_GetWindowSize(",
        "void SDL_WarpMouseInWindow(", "bool SDL_SetWindowRelativeMouseMode(",
    ))
    globals_start = platform.index("static struct platform_input_state input_state;")
    globals_end = platform.index("\n#ifndef HALO_ANDROID\n/* updater.c", globals_start)
    platform_functions = "\n".join(function(platform, name) for name in (
        "void platform_mouse_capture(", "static void platform_native_input_clear(",
        "static void platform_native_mouse_release(", "static BYTE virtual_key_from_scancode(",
        "static CHAR ascii_from_key(", "static void queue_keystroke(",
        "BOOL platform_next_keystroke(", "void platform_pump_events(",
        "void platform_ui_pointer_set_active(", "BOOL platform_ui_pointer_read(",
        "void platform_video_window_size(", "void platform_video_drawable_size(",
        "void platform_input_read(",
    ))
    pointer_start = renderer.index("/* ---------- the menus' pointer */")
    pointer_end = renderer.index("/* takes up the display's shape", pointer_start)
    mapping = "\n".join(function(controller, name) for name in (
        "static BYTE analog(", "static void keyboard_gamepad(",
    ))
    return (PREFIX.replace("/* HOST FUNCTIONS */", host_functions)
            .replace("/* GUEST FUNCTIONS */", guest_functions)
            .replace("/* PLATFORM GLOBALS */", platform[globals_start:globals_end])
            .replace("/* PLATFORM FUNCTIONS */", platform_functions)
            .replace("/* RENDERER POINTER */", renderer[pointer_start:pointer_end])
            .replace("/* CONTROLLER MAPPING */", mapping) + CHECKS)


class MacPointer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (SDL / "include/SDL3/SDL.h").is_file():
            raise unittest.SkipTest("SDL3 development headers are required for the Mac bridge fixture")
        compiler = shutil.which("clang")
        if not compiler:
            raise unittest.SkipTest("clang is required for the native pointer fixture")
        temporary = tempfile.TemporaryDirectory(prefix="halo-macos-pointer-")
        cls.addClassCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        source = directory / "pointer.c"
        source.write_text(fixture_source())
        cls.executable = directory / "pointer"
        subprocess.run([
            compiler, "-std=gnu11", "-Wall", "-Wextra", "-Werror",
            "-Wno-pointer-to-int-cast", "-fsanitize=address,undefined",
            "-fno-omit-frame-pointer", "-I", str(ROOT), "-I", str(SDL / "include"),
            str(source), "-pthread", "-lm", "-o", str(cls.executable),
        ], check=True, capture_output=True, text=True)

    def check_path(self, name):
        result = subprocess.run([self.executable, name], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_retina_menu_pointer_and_no_gameplay_clicks(self):
        self.check_path("menus")

    def test_native_panel_release_clears_held_and_queued_input(self):
        self.check_path("release")

    def test_recapture_consumes_click_and_stale_motion(self):
        self.check_path("recapture")


if __name__ == "__main__":
    unittest.main()

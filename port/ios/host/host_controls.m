/* UIKit controls drive SDL's virtual gamepad and the existing Xbox input path. */
#import <UIKit/UIKit.h>
#import <GameController/GameController.h>
#include <SDL3/SDL.h>
#include "host.h"
static SDL_Joystick *touch_pad;
@interface HaloStick : UIView
@property int axis;
@property(strong) UIView *thumb;
@end
@implementation HaloStick
- (instancetype)initWithFrame:(CGRect)frame {
    if ((self = [super initWithFrame:frame])) {
        self.backgroundColor = [UIColor colorWithWhite:0 alpha:0.18];
        self.layer.borderColor = [UIColor colorWithWhite:1 alpha:0.45].CGColor;
        self.layer.borderWidth = 1; self.layer.cornerRadius = frame.size.width / 2;
        self.thumb = [[UIView alloc] initWithFrame:CGRectMake(0, 0, 46, 46)];
        self.thumb.backgroundColor = [UIColor colorWithWhite:1 alpha:0.25];
        self.thumb.layer.cornerRadius = 23; self.thumb.userInteractionEnabled = NO;
        [self addSubview:self.thumb];
        self.thumb.center = CGPointMake(frame.size.width / 2, frame.size.height / 2);
        self.isAccessibilityElement = YES;
    }
    return self;
}
- (void)updateTouch:(UITouch *)touch {
    CGPoint p = [touch locationInView:self];
    CGFloat radius = self.bounds.size.width / 2, travel = radius - 23;
    CGFloat x = (p.x - radius) / travel, y = (p.y - radius) / travel;
    CGFloat length = hypot(x, y);
    if (length > 1) { x /= length; y /= length; }
    self.thumb.center = CGPointMake(radius + x * travel, radius + y * travel);
    SDL_SetJoystickVirtualAxis(touch_pad, self.axis, (Sint16)(x * 32767));
    SDL_SetJoystickVirtualAxis(touch_pad, self.axis + 1, (Sint16)(y * 32767));
}
- (void)touchesBegan:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event { (void)event; [self updateTouch:touches.anyObject]; }
- (void)touchesMoved:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event { (void)event; [self updateTouch:touches.anyObject]; }
- (void)reset {
    self.thumb.center = CGPointMake(self.bounds.size.width / 2, self.bounds.size.height / 2);
    SDL_SetJoystickVirtualAxis(touch_pad, self.axis, 0);
    SDL_SetJoystickVirtualAxis(touch_pad, self.axis + 1, 0);
}
- (void)touchesEnded:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event { (void)touches; (void)event; [self reset]; }
- (void)touchesCancelled:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event { [self touchesEnded:touches withEvent:event]; }
@end
@interface HaloControls : UIView
@property(strong) HaloStick *moveStick;
@property(strong) HaloStick *lookStick;
@property(strong) NSMutableArray<UIButton *> *buttons;
@end
@implementation HaloControls
- (UIButton *)button:(NSString *)title input:(int)input {
    UIButton *button = [UIButton buttonWithType:UIButtonTypeCustom];
    [button setTitle:title forState:UIControlStateNormal];
    button.titleLabel.font = [UIFont boldSystemFontOfSize:14];
    button.backgroundColor = [UIColor colorWithWhite:0 alpha:0.3];
    button.layer.borderColor = [UIColor colorWithWhite:1 alpha:0.5].CGColor;
    button.layer.borderWidth = 1; button.layer.cornerRadius = 22; button.tag = input;
    [button addTarget:self action:@selector(down:) forControlEvents:UIControlEventTouchDown | UIControlEventTouchDragEnter];
    [button addTarget:self action:@selector(up:) forControlEvents:UIControlEventTouchUpInside | UIControlEventTouchUpOutside | UIControlEventTouchCancel | UIControlEventTouchDragExit];
    [self addSubview:button]; [self.buttons addObject:button];
    return button;
}
- (instancetype)initWithFrame:(CGRect)frame {
    if ((self = [super initWithFrame:frame])) {
        self.multipleTouchEnabled = YES; self.buttons = [NSMutableArray new];
        self.moveStick = [[HaloStick alloc] initWithFrame:CGRectMake(0, 0, 126, 126)];
        self.moveStick.axis = SDL_GAMEPAD_AXIS_LEFTX; self.moveStick.accessibilityLabel = @"Move";
        self.lookStick = [[HaloStick alloc] initWithFrame:CGRectMake(0, 0, 126, 126)];
        self.lookStick.axis = SDL_GAMEPAD_AXIS_RIGHTX; self.lookStick.accessibilityLabel = @"Look";
        [self addSubview:self.moveStick]; [self addSubview:self.lookStick];
        [self button:@"A" input:SDL_GAMEPAD_BUTTON_SOUTH].accessibilityLabel = @"A: Jump or confirm";
        [self button:@"B" input:SDL_GAMEPAD_BUTTON_EAST].accessibilityLabel = @"B: Melee or back";
        [self button:@"X" input:SDL_GAMEPAD_BUTTON_WEST].accessibilityLabel = @"X: Reload or interact";
        [self button:@"Y" input:SDL_GAMEPAD_BUTTON_NORTH].accessibilityLabel = @"Y: Switch weapon";
        [self button:@"Fire" input:100 + SDL_GAMEPAD_AXIS_RIGHT_TRIGGER];
        [self button:@"Grenade" input:100 + SDL_GAMEPAD_AXIS_LEFT_TRIGGER];
        [self button:@"Pause" input:SDL_GAMEPAD_BUTTON_START];
        [self button:@"Light" input:SDL_GAMEPAD_BUTTON_LEFT_SHOULDER];
        [self button:@"Type" input:SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER].accessibilityLabel = @"Switch grenade type";
        [self button:@"Crouch" input:SDL_GAMEPAD_BUTTON_LEFT_STICK];
        [self button:@"Zoom" input:SDL_GAMEPAD_BUTTON_RIGHT_STICK];
        [self button:@"Back" input:SDL_GAMEPAD_BUTTON_BACK];
    }
    return self;
}
- (void)layoutSubviews {
    [super layoutSubviews];
    CGRect safe = UIEdgeInsetsInsetRect(self.bounds, self.safeAreaInsets);
    CGFloat left = CGRectGetMinX(safe) + 18, right = CGRectGetMaxX(safe) - 40;
    CGFloat bottom = CGRectGetMaxY(safe) - 14, top = CGRectGetMinY(safe) + 12;
    self.moveStick.frame = CGRectMake(left, bottom - 126, 126, 126);
    self.lookStick.frame = CGRectMake(right - 254, bottom - 126, 126, 126);
    CGPoint points[] = {{right-50,bottom-44},{right,bottom-94},{right-100,bottom-94},{right-50,bottom-144},
        {right-45,top+32},{left+45,top+32},{CGRectGetMidX(safe),top+12},
        {left+158,top+12},{right-158,top+12},{left+158,bottom-20},{right-254,bottom-160},
        {CGRectGetMidX(safe)-85,top+12}};
    for (NSUInteger i = 0; i < self.buttons.count; i++) {
        UIButton *button = self.buttons[i]; CGFloat width = i < 4 ? 44 : 70;
        button.frame = CGRectMake(points[i].x-width/2, points[i].y-22, width, 44);
    }
}
- (void)down:(UIButton *)button {
    button.alpha = 0.65;
    if (button.tag >= 100) SDL_SetJoystickVirtualAxis(touch_pad, (int)button.tag - 100, 32767);
    else SDL_SetJoystickVirtualButton(touch_pad, (int)button.tag, true);
}
- (void)up:(UIButton *)button {
    button.alpha = 1;
    if (button.tag >= 100) SDL_SetJoystickVirtualAxis(touch_pad, (int)button.tag - 100, -32768);
    else SDL_SetJoystickVirtualButton(touch_pad, (int)button.tag, false);
}
- (BOOL)pointInside:(CGPoint)point withEvent:(UIEvent *)event {
    for (UIView *view in self.subviews)
        if (!view.hidden && [view pointInside:[view convertPoint:point fromView:self] withEvent:event]) return YES;
    return NO;
}
- (void)reset {
    [self.moveStick reset]; [self.lookStick reset];
    for (UIButton *button in self.buttons) [self up:button];
}
@end
static HaloControls *controls;
static void refresh_controls(void) {
    BOOL physical = NO;
    for (GCController *controller in GCController.controllers)
        if (controller.extendedGamepad) physical = YES;
    const char *setting = SDL_getenv("HALO_TOUCH_CONTROLS");
    if (setting) physical = !SDL_atoi(setting);
    controls.hidden = physical; [controls reset];
    host_logf(HOST_LOG_INFO, "Touch controls %s; %lu system controllers",
        physical ? "hidden" : "visible", (unsigned long)GCController.controllers.count);
}
void host_ios_controls_initialize(SDL_Window *window) {
    if (controls) return;
    SDL_VirtualJoystickDesc descriptor;
    SDL_INIT_INTERFACE(&descriptor);
    descriptor.type = SDL_JOYSTICK_TYPE_GAMEPAD;
    descriptor.naxes = SDL_GAMEPAD_AXIS_COUNT; descriptor.nbuttons = SDL_GAMEPAD_BUTTON_COUNT;
    descriptor.axis_mask = (1u << SDL_GAMEPAD_AXIS_COUNT) - 1;
    descriptor.button_mask = (1u << SDL_GAMEPAD_BUTTON_COUNT) - 1;
    descriptor.name = "Halo Touch Controls";
    SDL_JoystickID id = SDL_AttachVirtualJoystick(&descriptor);
    touch_pad = SDL_OpenJoystick(id);
    if (!touch_pad) { host_logf(HOST_LOG_WARN, "Touch controls: %s", SDL_GetError()); return; }
    UIWindow *native = (__bridge UIWindow *)SDL_GetPointerProperty(SDL_GetWindowProperties(window), SDL_PROP_WINDOW_UIKIT_WINDOW_POINTER, NULL);
    UIView *view = native.rootViewController.view;
    controls = [[HaloControls alloc] initWithFrame:view.bounds];
    controls.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
    [view addSubview:controls];
    for (NSNotificationName name in @[GCControllerDidConnectNotification, GCControllerDidDisconnectNotification])
        [NSNotificationCenter.defaultCenter addObserverForName:name object:nil queue:NSOperationQueue.mainQueue
            usingBlock:^(NSNotification *notification) { (void)notification; refresh_controls(); }];
    [NSNotificationCenter.defaultCenter addObserverForName:UIApplicationWillResignActiveNotification object:nil queue:NSOperationQueue.mainQueue
        usingBlock:^(NSNotification *notification) { (void)notification; [controls reset]; }];
    refresh_controls();
    host_logf(HOST_LOG_INFO, "Touch controls ready (%u)", id);
}

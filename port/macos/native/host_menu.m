#import <Cocoa/Cocoa.h>
#import <Sparkle/Sparkle.h>
#import "HaloPreferences.h"
#include <SDL3/SDL.h>
#include "host_menu.h"
#include <stdlib.h>
#include <string.h>

@interface HaloMenu : NSObject <NSApplicationDelegate, NSMenuDelegate, NSMenuItemValidation,
                               SPUUpdaterDelegate, SPUStandardUserDriverDelegate>
@property(nonatomic, strong) HaloPreferences *preferences;
@property(nonatomic, strong) NSStatusItem *status;
@property(nonatomic, strong) NSWindow *settingsWindow;
@property(nonatomic, strong) NSTextField *dataLabel;
@property(nonatomic, strong) NSTextField *sourceLabel;
@property(nonatomic, strong) NSButton *fullscreenButton;
@property(nonatomic, strong) NSButton *automaticUpdatesButton;
@property(nonatomic, strong) SPUStandardUpdaterController *updater;
@property(nonatomic, strong) id previousDelegate;
@property(nonatomic) BOOL gameRunning;
@property(nonatomic) BOOL waitingForUpdate;
@property(nonatomic) BOOL importing;
@property(nonatomic) BOOL settingsVisible;
@property(nonatomic) BOOL quitting;
@property(nonatomic, copy) void (^pendingInstall)(void);
@property(nonatomic, copy) NSString *availableVersion;
@property(nonatomic, copy) NSString *launchDataPath;
- (void)refreshSettings;
- (void)refreshFullscreen;
- (BOOL)chooseFolder;
- (BOOL)chooseImage;
- (void)showSettings:(id)sender;
- (void)closeSettings:(id)sender;
- (void)importImage:(NSURL *)image completion:(void (^)(BOOL))completion;
@end

static HaloMenu *menu;

static void showError(NSError *error) {
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = @"Halo could not use that setting";
    alert.informativeText = error.localizedDescription ?: @"Please try again.";
    if (menu.gameRunning) {
        [menu showSettings:nil];
        [alert beginSheetModalForWindow:menu.settingsWindow completionHandler:nil];
    } else {
        [alert runModal];
    }
}

static NSMenuItem *item(NSMenu *parent, NSString *title, SEL action, NSString *key) {
    NSMenuItem *result = [[NSMenuItem alloc] initWithTitle:title action:action keyEquivalent:key ?: @""];
    result.target = menu;
    [parent addItem:result];
    return result;
}

static NSTextField *label(NSView *view, NSString *text, NSRect frame, BOOL secondary) {
    NSTextField *result = [NSTextField labelWithString:text];
    result.frame = frame;
    result.lineBreakMode = NSLineBreakByTruncatingMiddle;
    if (secondary) result.textColor = NSColor.secondaryLabelColor;
    [view addSubview:result];
    return result;
}

static NSButton *button(NSView *view, NSString *title, SEL action, NSRect frame) {
    NSButton *result = [NSButton buttonWithTitle:title target:menu action:action];
    result.frame = frame;
    [view addSubview:result];
    return result;
}

struct import_progress {
    __unsafe_unretained NSTextField *label;
    __unsafe_unretained NSProgressIndicator *bar;
};

static void importProgress(void *context, const char *file, unsigned long long done, unsigned long long total) {
    struct import_progress *progress = context;
    NSTextField *progressLabel = progress->label;
    NSProgressIndicator *bar = progress->bar;
    NSString *name = [NSString stringWithUTF8String:file] ?: @"Maps";
    dispatch_async(dispatch_get_main_queue(), ^{
        progressLabel.stringValue = [NSString stringWithFormat:@"%@ — %llu of %llu MB", name, done >> 20, total >> 20];
        bar.doubleValue = total ? (100.0 * done / total) : 0;
    });
}

@implementation HaloMenu
- (BOOL)respondsToSelector:(SEL)selector {
    return [super respondsToSelector:selector] || [self.previousDelegate respondsToSelector:selector];
}
- (id)forwardingTargetForSelector:(SEL)selector {
    return [self.previousDelegate respondsToSelector:selector] ? self.previousDelegate : [super forwardingTargetForSelector:selector];
}
- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)sender {
    (void)sender;
    if (self.importing) return NSTerminateCancel;
    if (self.gameRunning) {
        self.quitting = YES;
        if (NSApp.modalWindow) [NSApp stopModal];
        [self closeSettings:nil];
        host_sdl_request_quit();
        return NSTerminateCancel;
    }
    return NSTerminateNow;
}
- (void)buildMenus {
    self.status = [NSStatusBar.systemStatusBar statusItemWithLength:NSSquareStatusItemLength];
    NSURL *icon = [NSBundle.mainBundle URLForResource:@"Helmet" withExtension:@"pdf"];
    NSImage *image = [[NSImage alloc] initWithContentsOfURL:icon];
    image.size = NSMakeSize(18, 18);
    image.template = YES;
    self.status.button.image = image ?: [NSImage imageWithSystemSymbolName:@"gamecontroller" accessibilityDescription:@"Halo"];
    self.status.button.toolTip = @"Halo CE Universal";
    self.status.button.accessibilityLabel = @"Halo CE Universal";
    NSMenu *statusMenu = [[NSMenu alloc] initWithTitle:@"Halo"];
    statusMenu.delegate = self;
    NSMenuItem *title = [[NSMenuItem alloc] initWithTitle:@"Halo CE Universal" action:nil keyEquivalent:@""];
    title.enabled = NO;
    [statusMenu addItem:title];
    [statusMenu addItem:NSMenuItem.separatorItem];
    item(statusMenu, @"Show Game", @selector(showGame:), @"");
    item(statusMenu, @"Enter Full Screen", @selector(toggleFullscreen:), @"");
    item(statusMenu, @"Settings…", @selector(showSettings:), @",");
    [statusMenu addItem:NSMenuItem.separatorItem];
    item(statusMenu, @"Choose Disc Image…", @selector(selectImage:), @"");
    item(statusMenu, @"Choose Maps Folder…", @selector(selectFolder:), @"");
    item(statusMenu, @"Open Saves Folder", @selector(openSaves:), @"");
    item(statusMenu, @"Edit Controls and Advanced Settings…", @selector(openConfig:), @"");
    [statusMenu addItem:NSMenuItem.separatorItem];
    item(statusMenu, @"Check for Updates…", @selector(checkUpdates:), @"");
    NSMenuItem *statusQuit = item(statusMenu, @"Quit Halo", @selector(terminate:), @"q");
    statusQuit.target = NSApp;
    self.status.menu = statusMenu;

    NSMenu *main = [[NSMenu alloc] initWithTitle:@"Main"];
    NSMenuItem *app = [[NSMenuItem alloc] initWithTitle:@"Halo" action:nil keyEquivalent:@""];
    NSMenu *appMenu = [[NSMenu alloc] initWithTitle:@"Halo"];
    item(appMenu, @"About Halo CE Universal", @selector(about:), @"");
    item(appMenu, @"Settings…", @selector(showSettings:), @",");
    item(appMenu, @"Check for Updates…", @selector(checkUpdates:), @"");
    [appMenu addItem:NSMenuItem.separatorItem];
    NSMenuItem *appQuit = item(appMenu, @"Quit Halo", @selector(terminate:), @"q");
    appQuit.target = NSApp;
    app.submenu = appMenu;
    [main addItem:app];
    NSMenuItem *view = [[NSMenuItem alloc] initWithTitle:@"View" action:nil keyEquivalent:@""];
    NSMenu *viewMenu = [[NSMenu alloc] initWithTitle:@"View"];
    viewMenu.delegate = self;
    NSMenuItem *fullscreen = item(viewMenu, @"Enter Full Screen", @selector(toggleFullscreen:), @"f");
    fullscreen.keyEquivalentModifierMask = NSEventModifierFlagControl | NSEventModifierFlagCommand;
    item(viewMenu, @"Show Game", @selector(showGame:), @"");
    view.submenu = viewMenu;
    [main addItem:view];
    NSApp.mainMenu = main;
}
- (void)menuWillOpen:(NSMenu *)sender { (void)sender; host_sdl_release_mouse(); }
- (void)menuNeedsUpdate:(NSMenu *)sender {
    for (NSMenuItem *entry in sender.itemArray) {
        if (entry.action == @selector(toggleFullscreen:))
            entry.title = host_sdl_is_fullscreen() ? @"Exit Full Screen" : @"Enter Full Screen";
        if (entry.action == @selector(checkUpdates:))
            entry.title = !self.updater ? @"Download Mac Builds…" : self.pendingInstall ? @"Update Ready — Quit to Install" : self.availableVersion
                ? [NSString stringWithFormat:@"Update to Halo %@…", self.availableVersion] : @"Check for Updates…";
    }
}
- (BOOL)validateMenuItem:(NSMenuItem *)entry {
    if (self.importing) return NO;
    if (entry.action == @selector(showGame:)) return self.gameRunning;
    if (entry.action == @selector(toggleFullscreen:)) return self.gameRunning;
    if (entry.action == @selector(checkUpdates:))
        return self.updater ? self.updater.updater.canCheckForUpdates && !self.pendingInstall
            : HaloMacDownloadsURL(NSBundle.mainBundle.infoDictionary) != nil;
    return YES;
}
- (void)refreshFullscreen {
    self.fullscreenButton.state = (self.gameRunning ? host_sdl_is_fullscreen() : !self.preferences.windowed)
        ? NSControlStateValueOn : NSControlStateValueOff;
}
- (void)toggleFullscreen:(id)sender {
    (void)sender;
    BOOL fullscreen = self.gameRunning ? !host_sdl_is_fullscreen() : self.preferences.windowed;
    NSError *error = nil;
    if (self.gameRunning && !host_sdl_set_fullscreen(fullscreen)) {
        showError([NSError errorWithDomain:@"Halo" code:1 userInfo:@{NSLocalizedDescriptionKey:@"The display could not change modes."}]);
        [self refreshFullscreen];
        return;
    }
    if (![self.preferences setWindowed:!fullscreen error:&error]) showError(error);
    [self refreshFullscreen];
    if (self.settingsVisible) {
        host_sdl_release_mouse();
        [self.settingsWindow makeKeyAndOrderFront:self];
    }
}
- (void)showGame:(id)sender { (void)sender; host_sdl_show_game(); }
- (void)about:(id)sender { (void)sender; host_sdl_release_mouse(); [NSApp orderFrontStandardAboutPanel:self]; }
- (void)quit:(id)sender {
    (void)sender;
    if (self.importing) return;
    self.quitting = YES;
    [self closeSettings:nil];
    if (self.gameRunning) host_sdl_request_quit();
    else [NSApp terminate:self];
}
- (void)buildSettings {
    self.settingsWindow = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 520, 350)
        styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
    self.settingsWindow.title = @"Halo Settings";
    self.settingsWindow.releasedWhenClosed = NO;
    self.settingsWindow.preventsApplicationTerminationWhenModal = NO;
    self.settingsWindow.level = NSFloatingWindowLevel;
    self.settingsWindow.collectionBehavior = NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary;
    NSView *content = self.settingsWindow.contentView;
    label(content, @"Display", NSMakeRect(24, 305, 472, 22), NO).font = [NSFont boldSystemFontOfSize:13];
    self.fullscreenButton = [NSButton checkboxWithTitle:@"Full Screen" target:self action:@selector(toggleFullscreen:)];
    self.fullscreenButton.frame = NSMakeRect(24, 275, 472, 24);
    [content addSubview:self.fullscreenButton];
    label(content, @"Game Data", NSMakeRect(24, 235, 472, 22), NO).font = [NSFont boldSystemFontOfSize:13];
    self.dataLabel = label(content, @"No maps selected", NSMakeRect(24, 206, 472, 20), YES);
    self.sourceLabel = label(content, @"", NSMakeRect(24, 182, 472, 20), YES);
    button(content, @"Choose Disc Image…", @selector(selectImage:), NSMakeRect(20, 143, 183, 32));
    button(content, @"Choose Maps Folder…", @selector(selectFolder:), NSMakeRect(211, 143, 193, 32));
    label(content, @"Changes to game data take effect when Halo next opens.", NSMakeRect(24, 116, 472, 19), YES).font = [NSFont systemFontOfSize:11];
    self.automaticUpdatesButton = [NSButton checkboxWithTitle:@"Automatically check for updates"
                                                                  target:self action:@selector(automaticUpdates:)];
    self.automaticUpdatesButton.frame = NSMakeRect(24, 78, 472, 24);
    self.automaticUpdatesButton.enabled = self.updater != nil;
    [content addSubview:self.automaticUpdatesButton];
    if (!self.updater) label(content, @"Use Download Mac Builds in the Halo menu for newer builds.", NSMakeRect(24, 58, 472, 17), YES).font = [NSFont systemFontOfSize:11];
    button(content, @"Advanced Settings…", @selector(openConfig:), NSMakeRect(20, 14, 185, 32));
    NSButton *done = button(content, @"Done", @selector(closeSettings:), NSMakeRect(401, 14, 95, 32));
    done.keyEquivalent = @"\r";
}
- (void)refreshSettings {
    self.dataLabel.stringValue = self.preferences.dataPath ?: self.launchDataPath ?: @"No maps selected";
    self.dataLabel.toolTip = self.dataLabel.stringValue;
    self.sourceLabel.stringValue = self.preferences.isoPath ? [@"Disc image: " stringByAppendingString:self.preferences.isoPath] : @"Using an extracted maps folder";
    self.sourceLabel.toolTip = self.preferences.isoPath;
    self.automaticUpdatesButton.state = self.updater.updater.automaticallyChecksForUpdates ? NSControlStateValueOn : NSControlStateValueOff;
    [self refreshFullscreen];
}
- (void)showSettings:(id)sender {
    (void)sender;
    host_sdl_release_mouse();
    if (!self.settingsWindow) [self buildSettings];
    [self refreshSettings];
    [self.settingsWindow center];
    [NSApp activateIgnoringOtherApps:YES];
    [self.settingsWindow makeKeyAndOrderFront:self];
    /* Return to SDL immediately: the guest must keep servicing its network
       connections while native settings are open. */
    self.settingsVisible = YES;
}
- (void)closeSettings:(id)sender {
    (void)sender;
    if (self.settingsWindow.attachedSheet)
        [self.settingsWindow endSheet:self.settingsWindow.attachedSheet returnCode:NSModalResponseCancel];
    self.settingsVisible = NO;
    [self.settingsWindow orderOut:self];
    if (self.gameRunning && !self.quitting) host_sdl_show_game();
}
- (void)automaticUpdates:(NSButton *)sender {
    self.updater.updater.automaticallyChecksForUpdates = sender.state == NSControlStateValueOn;
}
- (void)openSaves:(id)sender {
    (void)sender;
    [NSWorkspace.sharedWorkspace openURL:self.preferences.supportDirectory];
}
- (void)openConfig:(id)sender {
    (void)sender;
    NSURL *config = [self.preferences.supportDirectory URLByAppendingPathComponent:@"config.toml"];
    if ([NSFileManager.defaultManager fileExistsAtPath:config.path]) {
        NSURL *editor = [NSWorkspace.sharedWorkspace URLForApplicationWithBundleIdentifier:@"com.apple.TextEdit"];
        if (editor) [NSWorkspace.sharedWorkspace openURLs:@[config] withApplicationAtURL:editor
            configuration:NSWorkspaceOpenConfiguration.configuration completionHandler:nil];
        else [NSWorkspace.sharedWorkspace openURL:config];
    } else {
        NSAlert *alert = [[NSAlert alloc] init];
        alert.messageText = @"Advanced settings appear after the first game launch";
        alert.informativeText = @"Start Halo once to create its controls and advanced settings file.";
        if (self.gameRunning) {
            [self showSettings:nil];
            [alert beginSheetModalForWindow:self.settingsWindow completionHandler:nil];
        } else {
            [alert runModal];
        }
    }
}
- (BOOL)chooseFolder {
    host_sdl_release_mouse();
    NSOpenPanel *panel = NSOpenPanel.openPanel;
    panel.title = @"Choose Your Xbox Halo Maps";
    panel.message = @"Choose an extracted game folder or its maps folder.";
    panel.canChooseDirectories = YES;
    panel.canChooseFiles = NO;
    panel.allowsMultipleSelection = NO;
    NSModalResponse result = [panel runModal];
    if (result != NSModalResponseOK) return NO;
    NSError *error = nil;
    if (![self.preferences selectDataRoot:panel.URL iso:nil error:&error]) { showError(error); return NO; }
    [self refreshSettings];
    return YES;
}
- (BOOL)chooseImage {
    host_sdl_release_mouse();
    NSOpenPanel *panel = NSOpenPanel.openPanel;
    panel.title = @"Choose Your Xbox Halo Disc Image";
    panel.message = @"The app imports only the maps from your local disc image.";
    panel.canChooseDirectories = NO;
    panel.canChooseFiles = YES;
    panel.allowsMultipleSelection = NO;
    NSModalResponse result = [panel runModal];
    if (result != NSModalResponseOK) return NO;
    __block BOOL finished = NO, succeeded = NO;
    [self importImage:panel.URL completion:^(BOOL success) { succeeded = success; finished = YES; }];
    /* The first-launch chooser runs before the engine starts. Runtime imports
       use the asynchronous completion directly and never enter this loop. */
    while (!finished)
        [NSRunLoop.currentRunLoop runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
    return succeeded;
}
- (void)importImage:(NSURL *)image completion:(void (^)(BOOL))completion {
    NSWindow *window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 470, 130)
        styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
    window.title = @"Importing Halo Maps";
    window.level = NSFloatingWindowLevel;
    NSTextField *progressLabel = label(window.contentView, @"Reading disc image…", NSMakeRect(24, 78, 422, 22), NO);
    NSProgressIndicator *bar = [[NSProgressIndicator alloc] initWithFrame:NSMakeRect(24, 48, 422, 18)];
    bar.indeterminate = NO;
    bar.minValue = 0;
    bar.maxValue = 100;
    [window.contentView addSubview:bar];
    label(window.contentView, @"Your existing maps and saves stay in place.", NSMakeRect(24, 16, 422, 19), YES);
    [window center];
    [window makeKeyAndOrderFront:self];
    self.importing = YES;
    __block struct import_progress progress = {progressLabel, bar};
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        NSError *error = nil;
        NSURL *imported = HaloImportDiscImage(image, self.preferences.supportDirectory, importProgress, &progress, &error);
        dispatch_async(dispatch_get_main_queue(), ^{
            self.importing = NO;
            [window orderOut:self];
            NSError *selectionError = error;
            BOOL succeeded = imported && [self.preferences selectDataRoot:imported iso:image error:&selectionError];
            if (!succeeded) {
                if (imported) [NSFileManager.defaultManager removeItemAtURL:imported error:nil];
                showError(selectionError);
            } else {
                [self refreshSettings];
            }
            completion(succeeded);
        });
    });
}
- (void)changedDataNotice {
    if (!self.gameRunning) return;
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = @"Game data updated";
    alert.informativeText = @"Halo will use your selection the next time it opens. Your current game can continue.";
    [self showSettings:nil];
    [alert beginSheetModalForWindow:self.settingsWindow completionHandler:nil];
}
- (void)selectFolder:(id)sender {
    (void)sender;
    if (self.importing || self.settingsWindow.attachedSheet) return;
    if (!self.gameRunning) { [self chooseFolder]; return; }
    [self showSettings:nil];
    NSOpenPanel *panel = NSOpenPanel.openPanel;
    panel.title = @"Choose Your Xbox Halo Maps";
    panel.message = @"Choose an extracted game folder or its maps folder.";
    panel.canChooseDirectories = YES;
    panel.canChooseFiles = NO;
    panel.allowsMultipleSelection = NO;
    [panel beginSheetModalForWindow:self.settingsWindow completionHandler:^(NSModalResponse response) {
        if (self.quitting || response != NSModalResponseOK) return;
        NSError *error = nil;
        if (![self.preferences selectDataRoot:panel.URL iso:nil error:&error]) showError(error);
        else { [self refreshSettings]; [self changedDataNotice]; }
    }];
}
- (void)selectImage:(id)sender {
    (void)sender;
    if (self.importing || self.settingsWindow.attachedSheet) return;
    if (!self.gameRunning) { [self chooseImage]; return; }
    [self showSettings:nil];
    NSOpenPanel *panel = NSOpenPanel.openPanel;
    panel.title = @"Choose Your Xbox Halo Disc Image";
    panel.message = @"The app imports only the maps from your local disc image.";
    panel.canChooseDirectories = NO;
    panel.canChooseFiles = YES;
    panel.allowsMultipleSelection = NO;
    [panel beginSheetModalForWindow:self.settingsWindow completionHandler:^(NSModalResponse response) {
        if (self.quitting || response != NSModalResponseOK) return;
        [self importImage:panel.URL completion:^(BOOL success) { if (success) [self changedDataNotice]; }];
    }];
}
- (void)checkUpdates:(id)sender {
    (void)sender;
    host_sdl_release_mouse();
    if (self.updater) [self.updater checkForUpdates:self];
    else {
        NSURL *downloads = HaloMacDownloadsURL(NSBundle.mainBundle.infoDictionary);
        if (downloads) [NSWorkspace.sharedWorkspace openURL:downloads];
    }
}
- (BOOL)supportsGentleScheduledUpdateReminders { return YES; }
- (BOOL)standardUserDriverShouldHandleShowingScheduledUpdate:(SUAppcastItem *)update andInImmediateFocus:(BOOL)focus {
    (void)update; (void)focus;
    return !self.gameRunning;
}
- (void)standardUserDriverWillHandleShowingUpdate:(BOOL)handle forUpdate:(SUAppcastItem *)update state:(SPUUserUpdateState *)state {
    (void)handle; (void)state;
    self.availableVersion = update.displayVersionString;
    self.status.button.toolTip = [NSString stringWithFormat:@"Halo %@ is available", self.availableVersion];
}
- (BOOL)updater:(SPUUpdater *)updater shouldPostponeRelaunchForUpdate:(SUAppcastItem *)update untilInvokingBlock:(void (^)(void))install {
    (void)updater; (void)update;
    if (!self.gameRunning) return NO;
    self.pendingInstall = install;
    self.status.button.toolTip = @"Halo update ready — quit the game to install";
    return YES;
}
- (BOOL)updater:(SPUUpdater *)updater willInstallUpdateOnQuit:(SUAppcastItem *)update immediateInstallationBlock:(void (^)(void))install {
    (void)updater; (void)update;
    self.pendingInstall = install;
    return YES;
}
- (void)updater:(SPUUpdater *)updater didAbortWithError:(NSError *)error {
    (void)updater; (void)error;
    self.pendingInstall = nil;
    self.waitingForUpdate = NO;
}
@end

void host_menu_initialize_application(void) {
    @autoreleasepool {
        /* SDL's NSApplication subclass intercepts terminate: without consulting
           delegates. Use Cocoa's normal lifecycle so settings can close and
           Sparkle can terminate after the guest saves and exits. SDL supports
           an existing NSApplication and still pumps its native input/events. */
        [NSApplication sharedApplication];
        [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
    }
}

int host_menu_prepare(const char *support, const char *fallback, char *data, size_t capacity) {
    @autoreleasepool {
        menu = [[HaloMenu alloc] init];
        menu.preferences = [[HaloPreferences alloc] initWithSupportDirectory:[NSURL fileURLWithPath:@(support) isDirectory:YES]];
        menu.previousDelegate = NSApp.delegate;
        NSApp.delegate = menu;
        if (HaloUpdateConfigurationIsValid(NSBundle.mainBundle.infoDictionary))
            menu.updater = [[SPUStandardUpdaterController alloc] initWithStartingUpdater:YES updaterDelegate:menu userDriverDelegate:menu];
        [menu buildMenus];
        [NSApp finishLaunching];
        NSString *selected = menu.preferences.dataPath;
        const char *override = getenv("HALO_DATA_ROOT");
        if (override && *override) selected = @(override);
        NSURL *valid = selected ? HaloValidateGameData([NSURL fileURLWithPath:selected], nil) : nil;
        if (!selected && fallback && *fallback) valid = HaloValidateGameData([NSURL fileURLWithPath:@(fallback)], nil);
        if (valid && !selected) {
            NSError *error = nil;
            if (![menu.preferences selectDataRoot:valid iso:nil error:&error]) { showError(error); return 0; }
        }
        while (!valid) {
            NSAlert *alert = [[NSAlert alloc] init];
            alert.messageText = @"Choose your Halo game data";
            alert.informativeText = @"Use your own original Xbox Halo disc image or extracted maps folder. The app does not include game data.";
            [alert addButtonWithTitle:@"Choose Disc Image…"];
            [alert addButtonWithTitle:@"Choose Maps Folder…"];
            [alert addButtonWithTitle:@"Quit"];
            NSModalResponse answer = [alert runModal];
            if (answer == NSAlertThirdButtonReturn) return 0;
            BOOL chosen = answer == NSAlertFirstButtonReturn ? [menu chooseImage] : [menu chooseFolder];
            if (chosen) valid = [NSURL fileURLWithPath:menu.preferences.dataPath];
        }
        /* Development overrides apply to this launch; chooser actions save the
           next launch's selection without changing the current game's files. */
        menu.launchDataPath = valid.path;
        if (!getenv("HALO_WINDOWED")) SDL_setenv_unsafe("HALO_WINDOWED", menu.preferences.windowed ? "1" : "0", 1);
        return [valid.path getCString:data maxLength:capacity encoding:NSUTF8StringEncoding] ? 1 : 0;
    }
}
void host_menu_begin_game(void) { menu.gameRunning = YES; [menu refreshFullscreen]; }
void host_menu_window_changed(void) { [menu refreshFullscreen]; }
void host_menu_finish_game(int exit_code) {
    @autoreleasepool {
        menu.quitting = YES;
        [menu closeSettings:nil];
        menu.gameRunning = NO;
        if (!exit_code && menu.pendingInstall) {
            menu.waitingForUpdate = YES;
            menu.pendingInstall();
            menu.pendingInstall = nil;
            /* Sparkle gets a normal Cocoa termination after the guest has saved
               and exited. SDL's delegate must not cancel that termination. */
            while (menu.waitingForUpdate)
                [NSRunLoop.currentRunLoop runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
        }
        if (menu.status) [NSStatusBar.systemStatusBar removeStatusItem:menu.status];
    }
}

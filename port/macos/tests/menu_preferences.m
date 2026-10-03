#import <Foundation/Foundation.h>
#import "HaloPreferences.h"
#include <assert.h>

static unsigned progressCalls;
static void progress(void *context, const char *name, unsigned long long done, unsigned long long total) {
    (void)context;
    assert(name && done <= total);
    progressCalls++;
}

int main(int argc, const char **argv) {
    @autoreleasepool {
        assert(argc >= 2);
        NSURL *test = [NSURL fileURLWithPath:@(argv[1]) isDirectory:YES];
        NSURL *valid = [test URLByAppendingPathComponent:@"valid"];
        NSURL *support = [test URLByAppendingPathComponent:@"support"];
        NSError *error = nil;
        assert([HaloValidateGameData(valid, &error).path isEqualToString:valid.path]);
        assert([HaloValidateGameData([valid URLByAppendingPathComponent:@"maps"], &error).path isEqualToString:valid.path]);
        NSURL *custom = [test URLByAppendingPathComponent:@"mixed-custom"];
        assert([HaloValidateGameData(custom, &error).path isEqualToString:custom.path]);
        assert([HaloValidateGameData([custom URLByAppendingPathComponent:@"maps"], &error).path isEqualToString:custom.path]);
        for (NSString *name in @[@"pc", @"mixed", @"missing", @"truncated", @"ce-ui", @"ce-a10",
                                @"pc-retail", @"mixed-retail", @"invalid-retail", @"missing-ui-with-ce"]) {
            error = nil;
            assert(!HaloValidateGameData([test URLByAppendingPathComponent:name], &error));
            assert(error.localizedDescription.length);
        }
        if (argc == 3) assert(HaloValidateGameData([NSURL fileURLWithPath:@(argv[2])], &error));
        HaloPreferences *preferences = [[HaloPreferences alloc] initWithSupportDirectory:support];
        assert([preferences selectDataRoot:valid iso:nil error:&error]);
        NSURL *settings = [support URLByAppendingPathComponent:@"macos-settings.json"];
        NSMutableDictionary *saved = [[NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfURL:settings]
            options:0 error:nil] mutableCopy];
        saved[@"future_setting"] = @"preserve me";
        assert([[NSJSONSerialization dataWithJSONObject:saved options:0 error:nil] writeToURL:settings atomically:YES]);
        NSURL *controls = [support URLByAppendingPathComponent:@"config.toml"];
        assert([@"[bindings]\nx = \"E\"\n" writeToURL:controls atomically:YES encoding:NSUTF8StringEncoding error:&error]);
        preferences = [[HaloPreferences alloc] initWithSupportDirectory:support];
        assert([preferences setWindowed:YES error:&error]);
        NSData *before = [NSData dataWithContentsOfURL:settings];
        assert(![preferences selectDataRoot:[test URLByAppendingPathComponent:@"pc"] iso:nil error:&error]);
        assert([[NSData dataWithContentsOfURL:settings] isEqualToData:before]);
        assert([preferences.dataPath isEqualToString:valid.path]);
        NSURL *image = [test URLByAppendingPathComponent:@"disc.iso"];
        NSURL *imported = HaloImportDiscImage(image, support, progress, NULL, &error);
        assert(imported && progressCalls == 2);
        assert([preferences.dataPath isEqualToString:valid.path]);
        assert([[NSData dataWithContentsOfURL:[imported URLByAppendingPathComponent:@"maps/ui.map"]]
            isEqualToData:[NSData dataWithContentsOfURL:[valid URLByAppendingPathComponent:@"maps/ui.map"]]]);
        assert([preferences selectDataRoot:imported iso:image error:&error]);
        before = [NSData dataWithContentsOfURL:settings];
        NSURL *imports = [support URLByAppendingPathComponent:@"Game Data"];
        NSUInteger count = [NSFileManager.defaultManager contentsOfDirectoryAtURL:imports
            includingPropertiesForKeys:nil options:0 error:nil].count;
        for (NSString *name in @[@"broken.iso", @"pc.iso"]) {
            assert(!HaloImportDiscImage([test URLByAppendingPathComponent:name], support, NULL, NULL, &error));
            assert([NSFileManager.defaultManager contentsOfDirectoryAtURL:imports
                includingPropertiesForKeys:nil options:0 error:nil].count == count);
            assert([[NSData dataWithContentsOfURL:settings] isEqualToData:before]);
        }
        preferences = [[HaloPreferences alloc] initWithSupportDirectory:support];
        assert(preferences.windowed && [preferences.isoPath isEqualToString:image.path]);
        assert([preferences.dataPath isEqualToString:imported.path]);
        saved = [NSJSONSerialization JSONObjectWithData:before options:0 error:nil];
        assert([saved[@"future_setting"] isEqualToString:@"preserve me"]);
        assert([[NSString stringWithContentsOfURL:controls encoding:NSUTF8StringEncoding error:nil]
            isEqualToString:@"[bindings]\nx = \"E\"\n"]);
        NSURL *blocked = [test URLByAppendingPathComponent:@"not-a-directory"];
        assert([@"file" writeToURL:blocked atomically:YES encoding:NSUTF8StringEncoding error:&error]);
        HaloPreferences *unwritable = [[HaloPreferences alloc] initWithSupportDirectory:blocked];
        assert(![unwritable selectDataRoot:valid iso:nil error:&error]);
        assert(!unwritable.dataPath);
        NSString *key = [[NSMutableData dataWithLength:32] base64EncodedStringWithOptions:0];
        assert(HaloUpdateConfigurationIsValid(@{@"SUFeedURL":@"https://example.com/appcast.xml", @"SUPublicEDKey":key}));
        for (NSString *url in @[@"http://example.com/feed.xml", @"https://user:pass@example.com/feed.xml", @"file:///feed.xml",
                               @"https://example.com/feed.xml?token=private", @"https://example.com/feed.xml#fragment"])
            assert(!HaloUpdateConfigurationIsValid(@{@"SUFeedURL":url, @"SUPublicEDKey":key}));
        assert(!HaloUpdateConfigurationIsValid(@{}));
        assert(!HaloUpdateConfigurationIsValid(@{@"SUFeedURL":@"https://example.com/feed.xml", @"SUPublicEDKey":@"invalid"}));
        NSString *downloads = @"https://github.com/owner/halo-ce-universal/actions/workflows/macos-dmg.yml";
        assert([HaloMacDownloadsURL(@{@"HaloMacDownloadsURL":downloads}).absoluteString isEqualToString:downloads]);
        for (id value in @[@"http://github.com/owner/repo/actions/workflows/macos-dmg.yml",
                           @"https://user:pass@github.com/owner/repo/actions/workflows/macos-dmg.yml",
                           @"https://github.com:443/owner/repo/actions/workflows/macos-dmg.yml",
                           @"https://github.com/owner/repo/actions/workflows/macos-dmg.yml?token=private",
                           @"https://github.com/owner/repo/actions/workflows/macos-dmg.yml#fragment",
                           @"https://github.com/../repo/actions/workflows/macos-dmg.yml",
                           @"https://github.com/owner/repo/actions/workflows/other.yml",
                           @"https://example.com/owner/repo/actions/workflows/macos-dmg.yml", @1])
            assert(!HaloMacDownloadsURL(@{@"HaloMacDownloadsURL":value}));
        assert(!HaloMacDownloadsURL(@{}));
        puts("Map validation, XISO import, failed-import rollback, persistent preferences and update configuration passed");
    }
    return 0;
}

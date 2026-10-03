"""Exercise the production map registry with synthetic, redistributable headers.

Compile the real registry, format reader and BMP reader. Only the engine's
filesystem, graphics allocation and setting boundaries are faked. The CE
recognition, cache-slot selection and last-used selection code are extracted
from their production units so these tests also cover their integration.
These fixtures establish discovery behavior, not that a map's tags will run.
"""
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / "port/linux/game"
STOCK = ["beavercreek", "sidewinder", "damnation", "ratrace", "prisoner",
         "hangemhigh", "chillout", "carousel", "boardingaction", "bloodgulch",
         "wizard", "putput", "longest"]
CAPACITY = 0x08000000


def function(source, name):
    """Take a complete function definition, excluding its forward declaration."""
    match = re.search(r"(?m)^(?:static )?[\w *]+\b" + re.escape(name)
                      + r"\([^;{}]*\)\s*\{", source)
    if not match:
        raise AssertionError(f"missing production definition: {name}")
    depth = 1
    end = match.end()
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[match.start():end]


BOUNDARIES = r'''
#ifndef TEST_ENGINE_BOUNDARIES
#define TEST_ENGINE_BOUNDARIES
#include <assert.h>
#include <dirent.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <wchar.h>
#include <unistd.h>
typedef int boolean;
typedef uint8_t byte;
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define MIN(a,b) ((a)<(b)?(a):(b))
#define FLAG(b) (1u<<(b))
#define NUMBEROF(a) (sizeof(a)/sizeof((a)[0]))
#define MAXIMUM_FILENAME_LENGTH 255
#define csmemcpy memcpy
#define csmemset memset
#define csprintf sprintf
#define csstrcpy strcpy
#define csstrlen strlen
#define csstrcasecmp strcasecmp
#define csstrncmp strncmp
#define _stricmp strcasecmp
#define _error_silent 0
#define error(...) ((void)0)
enum { _scenario_type_solo, _scenario_type_multiplayer, _scenario_type_main_menu };
enum { _name_filename_bit, _name_extension_bit };
struct file_reference { char path[1024]; };
struct bitmap_data { uint32_t *base_address; int hardware_format; };
static char map_directory[1024];
static int ce_enabled, bitmap_allocations, bitmap_deletions;
static char *entries[512];
static int entry_count, entry_index;
static char const *cache_files_map_directory(void) { return map_directory; }
static char const *tag_name_strip_path(char const *path) {
    char const *name = path;
    for (; *path; path++) if (*path == '\\' || *path == '/') name = path + 1;
    return name;
}
/* The native Xbox filesystem resolves components case-insensitively.
   Model that boundary here, including mixed-case extensions on Linux. */
static FILE *fixture_fopen(char const *path, char const *mode) {
    FILE *stream = fopen(path, mode);
    DIR *directory;
    struct dirent *entry;
    char resolved[2048];
    if (stream) return stream;
    directory = opendir(map_directory);
    if (!directory) return NULL;
    while ((entry = readdir(directory))) {
        if (!strcasecmp(entry->d_name, tag_name_strip_path(path))) {
            snprintf(resolved, sizeof(resolved), "%s%s", map_directory, entry->d_name);
            stream = fopen(resolved, mode);
            break;
        }
    }
    closedir(directory);
    return stream;
}
#define fopen fixture_fopen
static struct file_reference *file_reference_create_from_path(
    struct file_reference *file, char const *path, boolean directory) {
    (void)directory; assert(strlen(path) < sizeof(file->path));
    strcpy(file->path, path); return file;
}
static boolean file_exists(struct file_reference const *file) {
    FILE *stream = fopen(file->path, "rb");
    if (!stream) return FALSE;
    fclose(stream); return TRUE;
}
static int reverse_entries(void const *a, void const *b) {
    return -strcmp(*(char *const *)a, *(char *const *)b);
}
static void find_files_start(int flags, struct file_reference const *file) {
    DIR *directory = opendir(file->path);
    struct dirent *entry;
    (void)flags;
    for (int i = 0; i < entry_count; i++) free(entries[i]);
    entry_count = entry_index = 0;
    if (!directory) return;
    while ((entry = readdir(directory))) {
        if (entry->d_name[0] == '.') continue;
        assert(entry_count < 512);
        entries[entry_count++] = strdup(entry->d_name);
    }
    closedir(directory);
    /* Deliberately put .yelo before .map, opposite loader preference. */
    qsort(entries, entry_count, sizeof(entries[0]), reverse_entries);
}
static boolean find_files_next(struct file_reference *file, void *unused) {
    (void)unused;
    if (entry_index == entry_count) return FALSE;
    strcpy(file->path, entries[entry_index++]); return TRUE;
}
static void file_reference_get_name(struct file_reference const *file, unsigned flags, char *out) {
    char const *dot = strrchr(file->path, '.');
    if (flags == FLAG(_name_extension_bit)) strcpy(out, dot ? dot + 1 : "");
    else {
        size_t size = dot ? (size_t)(dot - file->path) : strlen(file->path);
        memcpy(out, file->path, size); out[size] = 0;
    }
}
static void *halo_custom_edition_tag_cache(void) { return ce_enabled ? &ce_enabled : NULL; }
static struct bitmap_data *bitmap_2d_new(int width, int height, int flags, int format) {
    struct bitmap_data *bitmap = calloc(1, sizeof(*bitmap));
    (void)flags; assert(format == 11 && bitmap);
    bitmap->base_address = calloc((size_t)width * height, sizeof(uint32_t));
    assert(bitmap->base_address); bitmap_allocations++; return bitmap;
}
static void bitmap_rebuild(struct bitmap_data *bitmap) { bitmap->hardware_format = 1; }
static void bitmap_delete(struct bitmap_data *bitmap) {
    if (bitmap) { free(bitmap->base_address); free(bitmap); bitmap_deletions++; }
}
static char *tag_get_name(long index) {
    return index == 1 ? "ui\\shell\\bitmaps\\mp_map_grafix" : "other";
}
char const *cache_files_build_region(char const *build);
#endif
'''

HARNESS = r'''
#include "boundaries.h"
#include "cache_file_formats.h"
#include "halo_port_capacity.h"
/* PRODUCTION HELPERS */
#include "custom_edition_maps.c"
static char *stock[] = {
    "beavercreek", "sidewinder", "damnation", "ratrace", "prisoner",
    "hangemhigh", "chillout", "carousel", "boardingaction", "bloodgulch",
    "wizard", "putput", "longest"
};
static int selected(char const *map_name, char **levels, short level_count) {
    struct { struct { short selected_index; } data3C; } storage = {{0}}, *widget = &storage;
    /* PRODUCTION SELECTION */
    return widget->data3C.selected_index;
}
static void wide(wchar_t const *value) {
    if (value) for (; *value; value++) printf("%02x", (unsigned)*value);
}
static void dump(char **levels, short count) {
    printf("count\t%d\n", count);
    for (short i = 0; i < count; i++) {
        short index = custom_edition_maps_level_display_index(i);
        printf("level\t%s\t%d\t", levels[i], index);
        wide(custom_edition_maps_name(index)); printf("\t");
        wide(custom_edition_maps_description(index)); printf("\n");
    }
}
int main(int argc, char **argv) {
    short count, frame, other_frame;
    char **levels;
    struct bitmap_data *picture;
    assert(argc >= 3 && strlen(argv[1]) + 2 < sizeof(map_directory));
    snprintf(map_directory, sizeof(map_directory), "%s/", argv[1]);
    ce_enabled = atoi(argv[2]);
    /* Browser lookup happens before the selector has supplied stock names. */
    printf("stock_lookup\t%d\n", custom_edition_maps_display_index("bloodgulch"));
    levels = custom_edition_maps_level_list(stock, NUMBEROF(stock), &count);
    dump(levels, count);
    if (argc >= 4) {
        short index = custom_edition_maps_display_index(argv[3]);
        printf("lookup\t%d\nselection\t%d\n", index, selected(argv[3], levels, count));
        frame = index; other_frame = index;
        assert(!custom_edition_maps_picture(2, &other_frame) && other_frame == index);
        picture = custom_edition_maps_picture(1, &frame);
        printf("picture\t%d\t%d\t%08x\n", !!picture, frame,
               picture ? picture->base_address[0] : 0);
        frame = index;
        assert(picture == custom_edition_maps_picture(1, &frame));
        printf("allocations\t%d\n", bitmap_allocations);
    }
    if (argc >= 5) { assert(!unlink(argv[4])); }
    levels = custom_edition_maps_level_list(stock, NUMBEROF(stock), &count);
    printf("refresh_count\t%d\ndeletions\t%d\n", count, bitmap_deletions);
    custom_edition_maps_forget();
    for (int i = 0; i < entry_count; i++) free(entries[i]);
    return 0;
}
'''

CAPACITY_HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "halo_port_capacity.h"
typedef int boolean;
typedef uint8_t byte;
#define FALSE 0
#define TRUE 1
#define NONE (-1)
#define CACHE_FILE_HEADER_SIGNATURE 'head'
#define CACHE_FILE_FOOTER_SIGNATURE 'foot'
#define csprintf sprintf
#define match_assert(file,line,condition) ((void)0)
#define match_vassert(file,line,condition,message) abort()
enum { _scenario_type_solo, _scenario_type_multiplayer, _scenario_type_main_menu };
/* PRODUCTION CONSTANTS */
/* PRODUCTION HEADER */
static char temporary[1024];
static struct { short open_map_file_index; } cache_file_globals = { 2 };
struct cached_map_file { int last_modification_date; };
static struct cached_map_file files[6];
static struct cached_map_file *cached_map_file_get(short index) { return &files[index]; }
static int CompareFileTime(int const *a, int const *b) { return (*a > *b) - (*a < *b); }
static boolean custom_edition_cache_refuse(void const *h, char const *b, char const *s, boolean f) {
    (void)h; (void)b; (void)s; (void)f; return FALSE;
}
/* PRODUCTION FUNCTIONS */
int main(void) {
    struct cache_file_header header;
    memset(&header, 0, sizeof(header));
    assert(sizeof(header) == 2048);
    header.header_signature = CACHE_FILE_HEADER_SIGNATURE;
    header.footer_signature = CACHE_FILE_FOOTER_SIGNATURE;
    header.version = 5;
    header.scenario_type = _scenario_type_multiplayer;
    header.file_length = HALO_PORT_MULTIPLAYER_CACHE_SIZE;
    assert(cache_file_header_verify(&header, "fixture", FALSE));
    assert(cached_map_files_find_free_map(header.file_length, header.scenario_type) >= 3);
    header.file_length++;
    assert(!cache_file_header_verify(&header, "fixture", FALSE));
    assert(cached_map_files_find_free_map(header.file_length, header.scenario_type) == NONE);
    header.scenario_type = _scenario_type_solo;
    assert(cache_file_header_verify(&header, "fixture", FALSE));
    assert(cached_map_files_find_free_map(SOLO_CACHE_FILE_MAXIMUM_SIZE, _scenario_type_solo) == NONE);
    cache_file_globals.open_map_file_index = 0;
    assert(cached_map_files_find_free_map(MAIN_MENU_CACHE_FILE_MAXIMUM_SIZE, _scenario_type_main_menu) == NONE);
    assert(cached_map_files_find_free_map(MAIN_MENU_CACHE_FILE_MAXIMUM_SIZE - 1, _scenario_type_main_menu) == 2);
    memset(header.name, 'x', sizeof(header.name));
    assert(!cache_file_header_verify(&header, "fixture", FALSE));
    puts("128 MiB is inclusive for multiplayer only; unterminated names are rejected");
    return 0;
}
'''


class CommunityMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="halo-community-test-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.build = Path(cls.temporary.name)
        cls.compiler = shutil.which("clang") or shutil.which("cc")
        if not cls.compiler:
            raise unittest.SkipTest("a C compiler is required")
        (cls.build / "boundaries.h").write_text(BOUNDARIES)
        for header in ("cseries.h", "errors.h", "tag_files/files.h", "tag_files/tag_files.h",
                       "bitmaps/bitmaps.h", "bitmaps/bitmap_group.h", "cache/cache_files.h"):
            path = cls.build / header
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('#include "boundaries.h"\n')
        ce = (GAME / "custom_edition_cache.c").read_text()
        cache = (ROOT / "source/cache/cache_files.c").read_text()
        helpers = '#define MAP_PATH_SIZE 256\n#define MAP_FILE_EXTENSION ".map"\n'
        helpers += '#define OPENSAUCE_MAP_FILE_EXTENSION ".yelo"\n'
        helpers += 'struct custom_edition_file { FILE *stream; struct cache_file_source source; };\n'
        for name in ("custom_edition_file_read", "custom_edition_file_open", "custom_edition_file_close",
                     "file_path_exists", "custom_edition_map_path", "custom_edition_cache_identify",
                     "custom_edition_cache_multiplayer"):
            helpers += function(ce, name) + "\n"
        table_start = cache.index("static struct\n{\n\tchar const *build;")
        helpers += cache[table_start:cache.index("};", table_start) + 2] + "\n"
        helpers += 'struct { struct { char build[32]; } header; } cache_file_globals;\n'
        helpers += function(cache, "cache_files_build_region")
        ui = (ROOT / "source/interface/ui_widget_event_handler_functions.c").read_text()
        selection_start = ui.index("while (widget->data3C.selected_index < level_count &&")
        selection_end = ui.index("\n\t\t}", selection_start) + len("\n\t\t}")
        source = HARNESS.replace("/* PRODUCTION HELPERS */", helpers).replace(
            "/* PRODUCTION SELECTION */", ui[selection_start:selection_end])
        cls.registry = cls.compile("registry", source,
                                   GAME / "cache_file_formats.c", GAME / "bmp_files.c")
        windows = (ROOT / "source/cache/cache_files_windows.c").read_text()
        constants = "enum { NUMBER_OF_CACHED_MAP_FILES = 6,\n"
        for name in ("SOLO_CACHE_FILE_MAXIMUM_SIZE", "MAIN_MENU_CACHE_FILE_MAXIMUM_SIZE",
                     "MULTIPLAYER_CACHE_FILE_MAXIMUM_SIZE"):
            constants += re.search(r"\b" + name + r"\s*=\s*[^,]+,", windows)[0] + "\n"
        constants += "};"
        header_start = cache.index("struct cache_file_header\n{")
        header = cache[header_start:cache.index("};", header_start) + 2]
        # The game uses the Xbox ILP32 ABI; the host harness also runs on LP64.
        header = header.replace("unsigned long", "uint32_t").replace("long", "int32_t")
        functions = function(windows, "cached_map_file_get_size") + "\n"
        functions += function(windows, "cached_map_files_find_free_map") + "\n"
        functions += function(cache, "cache_file_header_verify")
        source = CAPACITY_HARNESS.replace("/* PRODUCTION CONSTANTS */", constants).replace(
            "/* PRODUCTION HEADER */", header).replace("/* PRODUCTION FUNCTIONS */", functions)
        cls.capacity = cls.compile("capacity", source)

    @classmethod
    def compile(cls, name, source, *extra):
        path = cls.build / f"{name}.c"
        output = cls.build / name
        path.write_text(source)
        command = [cls.compiler, "-std=gnu99", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                   "-Wno-sign-compare", "-Wno-unused-variable", "-Wno-unused-parameter",
                   "-Wno-multichar", "-fsanitize=undefined", "-fsanitize-undefined-trap-on-error",
                   f"-I{cls.build}", f"-I{GAME}", "-iquote", str(ROOT / "port/linux/include"),
                   str(path), *map(str, extra), "-o", str(output)]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        return output

    def setUp(self):
        self.data = tempfile.TemporaryDirectory(prefix="halo-community-maps-")
        self.maps = Path(self.data.name)
        self.addCleanup(self.data.cleanup)

    def map(self, name, version=5, scenario=1, build="01.10.12.2276", extension="map",
            declared=0x1000, physical=0x1000, tag_offset=0x800, tag_size=0x40,
            header_name=None, opensauce=False):
        data = bytearray(0x800)
        struct.pack_into("<6I", data, 0, 0x68656164, version, declared, 0, tag_offset, tag_size)
        for offset, value in ((0x20, name if header_name is None else header_name), (0x40, build)):
            value = value.encode("ascii")[:32]
            data[offset:offset + len(value)] = value
        struct.pack_into("<H", data, 0x60, scenario)
        struct.pack_into("<I", data, 0x7FC, 0x666F6F74)
        if opensauce:
            struct.pack_into("<IH", data, 0x70, 0x79656C6F, 1)
            data[0x78:0x7A] = bytes((2, 2))
        path = self.maps / f"{name}.{extension}"
        with path.open("wb") as stream:
            stream.write(data[:physical])
            stream.truncate(physical)
        return path

    def scan(self, enabled=False, lookup=None, remove=None):
        command = [str(self.registry), str(self.maps), str(int(enabled))]
        if lookup is not None:
            command.append(lookup)
        if remove is not None:
            command.append(str(remove))
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = {"levels": []}
        for line in result.stdout.splitlines():
            fields = line.split("\t")
            if fields[0] == "level":
                report["levels"].append({"path": fields[1], "index": int(fields[2]),
                    "name": bytes.fromhex(fields[3]).decode("ascii"),
                    "description": bytes.fromhex(fields[4]).decode("ascii")})
            else:
                report[fields[0]] = fields[1:]
        self.assertEqual([row["path"] for row in report["levels"][:13]], STOCK)
        self.assertEqual([row["index"] for row in report["levels"][:13]], list(range(13)))
        self.assertEqual(report["stock_lookup"], ["-1"])
        report["custom"] = report["levels"][13:]
        return report

    def test_ce_off_keeps_xbox_maps_with_bare_names_and_stock_order(self):
        self.map("zulu_map")
        self.map("Alpha", extension="MaP", header_name="alpha")
        self.map("bloodgulch")
        self.map("custom", version=609)
        self.map("sauce", version=609, extension="yelo", opensauce=True)
        report = self.scan(lookup="levels\\test\\zulu_map\\zulu_map")
        self.assertEqual([r["path"] for r in report["custom"]], ["Alpha", "zulu_map"])
        self.assertEqual(report["custom"][1]["name"], "Zulu Map")
        self.assertEqual(report["custom"][1]["description"], "Xbox community\r\nmap")
        self.assertEqual(report["lookup"], [str(0x4001)])
        self.assertEqual(report["selection"], ["14"])

    def test_enabled_ce_and_yelo_retain_names_and_default_description(self):
        self.map("xbox")
        self.map("custom", version=609)
        self.map("sauce", version=609, extension="yelo", opensauce=True)
        report = self.scan(True, lookup="sauce")
        self.assertEqual([r["path"] for r in report["custom"]], [
            "levels\\test\\custom\\custom", "levels\\test\\sauce\\sauce", "xbox"])
        self.assertEqual(report["custom"][0]["description"], "Halo Custom\r\nEdition map")
        self.assertEqual(report["selection"], ["14"])

    def test_map_over_yelo_preference_matches_loader_with_ce_on_or_off(self):
        self.map("both", extension="yelo", version=609, opensauce=True)
        self.map("both")
        self.map("ce_wins", extension="yelo", version=609)
        self.map("ce_wins", version=609)
        self.map("blocked", extension="yelo", version=609)
        self.map("blocked", build="unsupported")
        self.assertEqual([r["path"] for r in self.scan()["custom"]], ["both"])
        self.assertEqual([r["path"] for r in self.scan(True)["custom"]], [
            "both", "levels\\test\\ce_wins\\ce_wins"])

    def test_names_are_bounded_for_both_canonical_forms(self):
        self.map("x" * 31)
        self.map("y" * 32)
        self.map("c" * 25, version=609)
        self.map("d" * 26, version=609)
        self.map("bad.name")
        self.map("bad+name")
        report = self.scan(True)
        self.assertEqual(len(report["custom"]), 2)
        self.assertEqual([len(r["path"]) for r in report["custom"]], [63, 31])

    def test_invalid_headers_are_rejected_without_affecting_valid_maps(self):
        cases = {
            "campaign": {"scenario": 0}, "ui": {"scenario": 2},
            "unknown_type": {"scenario": 3}, "wrong_build": {"build": "unreleased"},
            "wrong_version": {"version": 7}, "wrong_name": {"header_name": "different"},
            "unterminated_name": {"header_name": "n" * 32},
            "unterminated_build": {"build": "b" * 32},
            "header_only": {"physical": 0x800}, "short_file": {"physical": 64},
            "long_physical": {"physical": CAPACITY + 1},
            "long_declared": {"declared": CAPACITY + 1},
            "short_declared": {"declared": 0x800}, "tag_in_header": {"tag_offset": 0x7FC},
            "tag_past_end": {"tag_offset": 0x1001}, "small_tag": {"tag_size": 0x23},
            "tag_overflows": {"tag_size": 0x900},
            "large_tag_arena": {"declared": CAPACITY, "tag_size": 0x01600001},
        }
        for name, options in cases.items():
            self.map(name, **options)
        for name, offset in (("bad_head", 0), ("bad_foot", 0x7FC)):
            with self.map(name).open("r+b") as stream:
                stream.seek(offset); stream.write(b"bad!")
        self.map("valid")
        self.assertEqual([r["path"] for r in self.scan(True)["custom"]], ["valid"])

    def test_compressed_physical_size_can_differ_and_supported_builds_are_accepted(self):
        for index, build in enumerate(("01.01.14.2342", "01.10.12.2276", "01.08.15.1749")):
            path = self.map(f"region{index}", build=build, declared=CAPACITY,
                            physical=0x1000, tag_offset=CAPACITY - 0x01600000,
                            tag_size=0x01600000)
            with path.open("r+b") as stream:
                stream.seek(0x0C); stream.write(struct.pack("<I", 1980))
        self.map("physical_boundary", physical=CAPACITY, declared=CAPACITY)
        self.assertEqual(len(self.scan()["custom"]), 4)

    def test_case_insensitive_duplicates_have_one_display_index(self):
        self.map("Echo")
        self.map("eCHO", version=609, extension="yelo")
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                report = self.scan(enabled, lookup="levels\\test\\ECHO\\ECHO")
                self.assertEqual(len(report["custom"]), 1)
                self.assertEqual(report["custom"][0]["path"].lower(), "echo")
                self.assertEqual(report["lookup"], [str(0x4000)])
                self.assertEqual(report["selection"], ["13"])

    def test_count_is_bounded_and_case_insensitively_sorted(self):
        for index in range(140):
            self.map(f"arena_{index:03}")
        report = self.scan()
        paths = [r["path"] for r in report["custom"]]
        self.assertEqual(len(paths), 128)
        self.assertEqual(paths, sorted(set(paths), key=str.lower))
        self.assertEqual(report["custom"][-1]["index"], 0x407F)

    def test_description_and_preview_survive_then_release_on_refresh(self):
        path = self.map("sidecar")
        (self.maps / "sidecar.txt").write_bytes(b"\xef\xbb\xbfFirst\tline\r\nSecond \xc3\xa9\n\n")
        bmp = bytearray(58)
        bmp[:2] = b"BM"
        struct.pack_into("<I", bmp, 2, len(bmp))
        struct.pack_into("<I", bmp, 10, 54)
        struct.pack_into("<IiiHHI", bmp, 14, 40, 1, 1, 1, 24, 0)
        bmp[54:57] = bytes((0x33, 0x22, 0x11))
        (self.maps / "sidecar.bmp").write_bytes(bmp)
        report = self.scan(lookup="sidecar", remove=path)
        self.assertEqual(report["custom"][0]["description"], "First line\r\nSecond ?")
        self.assertEqual(report["picture"], ["1", "13", "ff112233"])
        self.assertEqual(report["allocations"], ["1"])
        self.assertEqual(report["deletions"], ["1"])
        self.assertEqual(report["refresh_count"], ["13"])

    def test_missing_or_bad_picture_uses_unknown_frame(self):
        self.map("missing")
        self.map("bad_picture")
        (self.maps / "bad_picture.bmp").write_bytes(b"not a BMP")
        for name in ("missing", "bad_picture"):
            with self.subTest(name=name):
                report = self.scan(lookup=name)
                self.assertEqual(report["picture"], ["0", "13", "00000000"])
                self.assertEqual(report["allocations"], ["0"])

    def test_multiplayer_cache_boundary_matches_header_and_slot(self):
        result = subprocess.run([str(self.capacity)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()

/*
CUSTOM_MULTIPLAYER_MAPS.C

Multiplayer maps beyond the original thirteen, for the native ports
(port/linux, port/android, port/windows).

The Xbox game lists its multiplayer maps from a fixed table
(event_handler_functions.multiplayer_levels in
ui_widget_event_handler_functions.c) and shows each one's name, picture and
description from ui.map by its position in that table. The ports list, after
those, every other multiplayer cache file in the map directory: a file whose
header is a cache file's of this version (of any build, as
cache_file_header_verify takes in the native builds), whose scenario type is
multiplayer, and whose internal name is its file name. It is offered as
"levels\test\<name>\<name>", like the originals; only the last part of that
path picks the file (scenario_tags_load), and the scenario comes from the
cache file's own tag header.

The Custom Edition maps (custom_edition_maps.c, with the game.custom_edition
setting) follow these in the list.

The name and description shown for such a map come from an optional block in
the unused part of the cache file header:

	0x100 'cmap' (the bytes 'c' 'm' 'a' 'p')
	0x104 long version, 1
	0x108 wchar_t display_name[32] (UTF-16, zero terminated)
	0x148 wchar_t description[128] (UTF-16, zero terminated, lines end in \r\n)

Without it, the file name stands in for the name. The picture is ui.map's
"unknown level" frame.

Text boxes take these strings through negative string list indices
(CUSTOM_MULTIPLAYER_MAP_STRING_BASE and below), which widget text rendering
(ui_widget.c) passes here instead of to the string list tag.
*/

#include "cseries/cseries.h"
#include "cache/cache_files.h"

#include <xtl.h>

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ---------- constants */

#ifndef FILE_SHARE_READ
/* winbase.h's; not among the port's Xbox SDK declarations (port/include/xdk) */
#define FILE_SHARE_READ 0x00000001
#endif

enum
{
	MAXIMUM_CUSTOM_MULTIPLAYER_MAPS = 32,
	MAXIMUM_ORIGINAL_MULTIPLAYER_MAPS = 16,
	CUSTOM_MAP_NAME_LENGTH = 32,
	CUSTOM_MAP_DESCRIPTION_LENGTH = 128,

	CACHE_FILE_HEADER_SIZE = 0x800,
	CACHE_FILE_HEADER_SIGNATURE = 'head',
	CACHE_FILE_FOOTER_SIGNATURE = 'foot',
	CACHE_FILE_VERSION = 5,
	SCENARIO_TYPE_MULTIPLAYER = 1,

	CUSTOM_MAP_INFO_OFFSET = 0x100,
	CUSTOM_MAP_INFO_VERSION = 1,

	CUSTOM_MULTIPLAYER_MAP_STRING_BASE = -1000,
};

/* ---------- structures */

struct custom_multiplayer_map
{
	/* the scenario path the game loads it by; 256 characters, because
	saved_game_file_remember_last_used_multiplayer_map writes that many */
	char scenario_name[256];
	char file_name[32];
	wchar_t display_name[CUSTOM_MAP_NAME_LENGTH];
	wchar_t description[CUSTOM_MAP_DESCRIPTION_LENGTH];
};

/* ---------- globals */

/* the file names of the multiplayer maps the game lists itself (see
event_handler_functions.multiplayer_levels) */
static char const *const original_multiplayer_maps[] =
{
	"beavercreek", "sidewinder", "damnation", "ratrace", "prisoner", "hangemhigh", "chillout",
	"carousel", "boardingaction", "bloodgulch", "wizard", "putput", "longest",
};

static struct
{
	boolean scanned;
	short count;
	struct custom_multiplayer_map maps[MAXIMUM_CUSTOM_MULTIPLAYER_MAPS];
	/* the originals followed by the custom maps (the level list widget's
	generated list) */
	char *level_list[MAXIMUM_ORIGINAL_MULTIPLAYER_MAPS + MAXIMUM_CUSTOM_MULTIPLAYER_MAPS];
} custom_map_globals;

/* ---------- private code */

static char const *path_last_component(
	char const *path)
{
	char const *slash = strrchr(path, '\\');

	return slash ? slash + 1 : path;
}

static unsigned long read_long(
	byte const *data)
{
	return (unsigned long)data[0] | ((unsigned long)data[1] << 8) |
		((unsigned long)data[2] << 16) | ((unsigned long)data[3] << 24);
}

static void copy_utf16(
	wchar_t *destination,
	byte const *source,
	long maximum_count)
{
	long index;

	for (index = 0; index < maximum_count - 1; index++)
	{
		wchar_t character = (wchar_t)(source[2 * index] | (source[2 * index + 1] << 8));

		if (!character)
			break;
		destination[index] = character;
	}
	destination[index] = 0;
}

static void ascii_to_utf16(
	wchar_t *destination,
	char const *source,
	long maximum_count)
{
	long index;

	for (index = 0; index < maximum_count - 1 && source[index]; index++)
		destination[index] = (wchar_t)(unsigned char)source[index];
	destination[index] = 0;
}

static boolean is_original_multiplayer_map(
	char const *file_name)
{
	long index;

	for (index = 0; index < (long)NUMBEROF(original_multiplayer_maps); index++)
	{
		if (!_stricmp(file_name, original_multiplayer_maps[index]))
			return TRUE;
	}

	return FALSE;
}

static boolean read_cache_file_header(
	char const *path,
	byte *header)
{
	boolean result = FALSE;
	HANDLE file = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);

	if (file != INVALID_HANDLE_VALUE)
	{
		unsigned long bytes_read = 0;

		result = ReadFile(file, header, CACHE_FILE_HEADER_SIZE, &bytes_read, NULL) &&
			bytes_read == CACHE_FILE_HEADER_SIZE;
		CloseHandle(file);
	}

	return result;
}

static boolean custom_map_from_file(
	char const *directory,
	char const *file_name,
	struct custom_multiplayer_map *map)
{
	byte header[CACHE_FILE_HEADER_SIZE];
	char base_name[32];
	char header_name[33];
	char path[512];
	char const *extension = strrchr(file_name, '.');
	long base_length = extension ? (long)(extension - file_name) : (long)strlen(file_name);

	if (base_length <= 0 || base_length >= (long)sizeof(base_name))
		return FALSE;
	memcpy(base_name, file_name, base_length);
	base_name[base_length] = 0;
	if (is_original_multiplayer_map(base_name))
		return FALSE;

	_snprintf(path, sizeof(path), "%s%s", directory, file_name);
	path[sizeof(path) - 1] = 0;
	if (!read_cache_file_header(path, header))
		return FALSE;
	if (read_long(header + 0x00) != CACHE_FILE_HEADER_SIGNATURE ||
		read_long(header + 0x7FC) != CACHE_FILE_FOOTER_SIGNATURE ||
		read_long(header + 0x04) != CACHE_FILE_VERSION ||
		(header[0x60] | (header[0x61] << 8)) != SCENARIO_TYPE_MULTIPLAYER)
	{
		return FALSE;
	}
	memcpy(header_name, header + 0x20, 32);
	header_name[32] = 0;
	if (_stricmp(header_name, base_name))
		return FALSE;

	memset(map, 0, sizeof(*map));
	_snprintf(map->file_name, sizeof(map->file_name), "%s", header_name);
	map->file_name[sizeof(map->file_name) - 1] = 0;
	_snprintf(map->scenario_name, sizeof(map->scenario_name), "levels\\test\\%s\\%s",
		map->file_name, map->file_name);
	map->scenario_name[sizeof(map->scenario_name) - 1] = 0;

	if (read_long(header + CUSTOM_MAP_INFO_OFFSET) == 'pamc' &&
		read_long(header + CUSTOM_MAP_INFO_OFFSET + 4) == CUSTOM_MAP_INFO_VERSION)
	{
		copy_utf16(map->display_name, header + CUSTOM_MAP_INFO_OFFSET + 8, CUSTOM_MAP_NAME_LENGTH);
		copy_utf16(map->description, header + CUSTOM_MAP_INFO_OFFSET + 8 + 2 * CUSTOM_MAP_NAME_LENGTH,
			CUSTOM_MAP_DESCRIPTION_LENGTH);
	}
	if (!map->display_name[0])
	{
		ascii_to_utf16(map->display_name, map->file_name, CUSTOM_MAP_NAME_LENGTH);
		if (map->display_name[0] < 0x80)
			map->display_name[0] = (wchar_t)toupper(map->display_name[0]);
	}
	if (!map->description[0])
		ascii_to_utf16(map->description, "Custom map", CUSTOM_MAP_DESCRIPTION_LENGTH);

	return TRUE;
}

static int custom_map_compare(
	void const *a,
	void const *b)
{
	return _stricmp(((struct custom_multiplayer_map const *)a)->file_name,
		((struct custom_multiplayer_map const *)b)->file_name);
}

static void custom_multiplayer_maps_scan(
	void)
{
	char const *directory = cache_files_map_directory();
	char pattern[512];
	WIN32_FIND_DATAA data;
	HANDLE find;

	custom_map_globals.count = 0;
	custom_map_globals.scanned = TRUE;
	_snprintf(pattern, sizeof(pattern), "%s*.map", directory);
	pattern[sizeof(pattern) - 1] = 0;
	find = FindFirstFileA(pattern, &data);
	if (find == INVALID_HANDLE_VALUE)
		return;
	do
	{
		if (custom_map_globals.count < MAXIMUM_CUSTOM_MULTIPLAYER_MAPS &&
			!(data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) &&
			custom_map_from_file(directory, data.cFileName,
				&custom_map_globals.maps[custom_map_globals.count]))
		{
			custom_map_globals.count++;
		}
	}
	while (FindNextFileA(find, &data));
	CloseHandle(find);

	qsort(custom_map_globals.maps, custom_map_globals.count, sizeof(custom_map_globals.maps[0]),
		custom_map_compare);
}

/* ---------- public code */

char **custom_multiplayer_level_list(
	char **original_levels,
	short original_count,
	short *level_count,
	boolean rescan)
{
	short index;

	if (original_count > MAXIMUM_ORIGINAL_MULTIPLAYER_MAPS)
		original_count = MAXIMUM_ORIGINAL_MULTIPLAYER_MAPS;
	if (rescan || !custom_map_globals.scanned)
		custom_multiplayer_maps_scan();
	for (index = 0; index < original_count; index++)
		custom_map_globals.level_list[index] = original_levels[index];
	for (index = 0; index < custom_map_globals.count; index++)
		custom_map_globals.level_list[original_count + index] = custom_map_globals.maps[index].scenario_name;
	*level_count = (short)(original_count + custom_map_globals.count);

	return custom_map_globals.level_list;
}

short custom_multiplayer_map_count(
	void)
{
	if (!custom_map_globals.scanned)
		custom_multiplayer_maps_scan();

	return custom_map_globals.count;
}

short custom_multiplayer_map_find(
	char const *map_name)
{
	short index;

	if (!map_name || !*map_name)
		return NONE;
	if (!custom_map_globals.scanned)
		custom_multiplayer_maps_scan();
	for (index = 0; index < custom_map_globals.count; index++)
	{
		if (!_stricmp(path_last_component(map_name), custom_map_globals.maps[index].file_name))
			return index;
	}

	return NONE;
}

short custom_multiplayer_map_name_string(
	short custom_index)
{
	return (short)(CUSTOM_MULTIPLAYER_MAP_STRING_BASE - 2 * custom_index);
}

short custom_multiplayer_map_description_string(
	short custom_index)
{
	return (short)(CUSTOM_MULTIPLAYER_MAP_STRING_BASE - 2 * custom_index - 1);
}

wchar_t *custom_multiplayer_map_string(
	short string_list_index)
{
	long code;
	long custom_index;

	if (string_list_index > CUSTOM_MULTIPLAYER_MAP_STRING_BASE)
		return NULL;
	code = CUSTOM_MULTIPLAYER_MAP_STRING_BASE - string_list_index;
	custom_index = code / 2;
	if (custom_index >= custom_map_globals.count)
		return L" ";

	return (code & 1) ?
		custom_map_globals.maps[custom_index].description :
		custom_map_globals.maps[custom_index].display_name;
}

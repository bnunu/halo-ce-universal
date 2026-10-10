/*
WIN32_MEMORY_WATCH.C

Write tracking for guest memory that the renderer caches: the Windows version
of port/linux/src/memory_watch.c (see there for the design). The pages behind
a cached texture are made read-only; a vectored exception handler catches
the first write, records a new generation for the page and makes it
writable again.

With the debug.sample_seconds setting, this file also reports where the
game's main thread is that often, which finds hangs without a debugger
(llvm-symbolizer turns the addresses into functions).
*/

#include <windows.h>
#include <stdio.h>
#include <string.h>

#include "port_config.h"

/* the Xbox memory window (port/linux/src/platform.h: the desktop builds') */
#define PLATFORM_CONTIGUOUS_BASE 0x80000000UL
#define PLATFORM_CONTIGUOUS_SIZE 0x20000000UL

#define WATCH_PAGE_SIZE 0x1000UL
#define WATCH_PAGE_COUNT (PLATFORM_CONTIGUOUS_SIZE / WATCH_PAGE_SIZE)

void platform_log(const char *format, ...);

static volatile unsigned char page_protected[WATCH_PAGE_COUNT];
static volatile LONG page_generation[WATCH_PAGE_COUNT];
static volatile LONG current_generation = 1;
static BOOL watch_active = FALSE;

static BOOL in_window(unsigned long address)
{
	return address >= PLATFORM_CONTIGUOUS_BASE && address - PLATFORM_CONTIGUOUS_BASE < PLATFORM_CONTIGUOUS_SIZE;
}

static unsigned long page_index(unsigned long address)
{
	return (address - PLATFORM_CONTIGUOUS_BASE) / WATCH_PAGE_SIZE;
}

static void mark_written(unsigned long page)
{
	DWORD previous;

	page_generation[page] = InterlockedIncrement(&current_generation);
	page_protected[page] = 0;
	VirtualProtect((void *)(PLATFORM_CONTIGUOUS_BASE + page * WATCH_PAGE_SIZE), WATCH_PAGE_SIZE,
		PAGE_READWRITE, &previous);
}

static LONG CALLBACK watch_handler(EXCEPTION_POINTERS *exception)
{
	EXCEPTION_RECORD *record = exception->ExceptionRecord;

	if (record->ExceptionCode == EXCEPTION_ACCESS_VIOLATION && record->NumberParameters >= 2 &&
		record->ExceptionInformation[0] == 1 /* a write */)
	{
		unsigned long address = (unsigned long)record->ExceptionInformation[1];

		if (in_window(address) && page_protected[page_index(address)])
		{
			mark_written(page_index(address));
			return EXCEPTION_CONTINUE_EXECUTION;
		}
	}
	return EXCEPTION_CONTINUE_SEARCH;
}

void memory_watch_initialize(void)
{
	if (watch_active)
		return;
	if (AddVectoredExceptionHandler(1, watch_handler))
		watch_active = TRUE;
}

void memory_watch_protect(unsigned long address, unsigned long size)
{
	unsigned long first, last, page;

	if (!watch_active || !size || !in_window(address))
		return;
	first = page_index(address);
	last = page_index(address + size - 1);
	if (last >= WATCH_PAGE_COUNT)
		last = WATCH_PAGE_COUNT - 1;
	for (page = first; page <= last; page++)
	{
		if (!page_protected[page])
		{
			DWORD previous;

			page_protected[page] = 1;
			VirtualProtect((void *)(PLATFORM_CONTIGUOUS_BASE + page * WATCH_PAGE_SIZE), WATCH_PAGE_SIZE,
				PAGE_READONLY, &previous);
		}
	}
}

unsigned long memory_watch_serial(void)
{
	return (unsigned long)current_generation;
}

unsigned long memory_watch_generation(unsigned long address, unsigned long size)
{
	unsigned long first, last, page, newest = 0;

	if (!size || !in_window(address))
		return 0;
	first = page_index(address);
	last = page_index(address + size - 1);
	if (last >= WATCH_PAGE_COUNT)
		last = WATCH_PAGE_COUNT - 1;
	for (page = first; page <= last; page++)
	{
		if ((unsigned long)page_generation[page] > newest)
			newest = (unsigned long)page_generation[page];
	}
	return newest;
}

void memory_watch_prepare_write(void *address, unsigned long size)
{
	unsigned long start = (unsigned long)address;
	unsigned long first, last, page;

	if (!watch_active || !size)
		return;
	if (start + size <= PLATFORM_CONTIGUOUS_BASE || start >= PLATFORM_CONTIGUOUS_BASE + PLATFORM_CONTIGUOUS_SIZE)
		return;
	if (start < PLATFORM_CONTIGUOUS_BASE)
		start = PLATFORM_CONTIGUOUS_BASE;
	first = page_index(start);
	last = page_index((unsigned long)address + size - 1);
	if (last >= WATCH_PAGE_COUNT)
		last = WATCH_PAGE_COUNT - 1;
	for (page = first; page <= last; page++)
	{
		if (page_protected[page])
			mark_written(page);
	}
}

void memory_watch_forget(void *address, unsigned long size)
{
	unsigned long start = (unsigned long)address;
	unsigned long first, last, page;

	if (!size || !in_window(start))
		return;
	first = page_index(start);
	last = page_index(start + size - 1);
	if (last >= WATCH_PAGE_COUNT)
		last = WATCH_PAGE_COUNT - 1;
	for (page = first; page <= last; page++)
	{
		page_protected[page] = 0;
		page_generation[page] = InterlockedIncrement(&current_generation);
	}
}

/* page protection sees each write at once: nothing to do per frame */
void memory_watch_begin_frame(void)
{
}

/* ---------- stack reports (debug.sample_seconds) */

int crash_reporter_process(void);

static HANDLE reported_thread;
static DWORD report_interval_milliseconds;

/* the EBP frame chain from `ebp` (the game keeps frame pointers) */
static void frame_chain_log(const char *prefix, DWORD ebp)
{
	const DWORD *frame = (const DWORD *)ebp;
	int depth;

	for (depth = 0; depth < 32 && frame && !IsBadReadPtr(frame, 2 * sizeof(DWORD)); depth++)
	{
		platform_log("%s: called from %08lx", prefix, frame[1]);
		if ((const DWORD *)frame[0] <= frame)
			break;
		frame = (const DWORD *)frame[0];
	}
}

static DWORD WINAPI stack_report_thread(LPVOID parameter)
{
	(void)parameter;
	for (;;)
	{
		CONTEXT context;

		Sleep(report_interval_milliseconds);
		if (SuspendThread(reported_thread) == (DWORD)-1)
			continue;
		memset(&context, 0, sizeof(context));
		context.ContextFlags = CONTEXT_CONTROL | CONTEXT_INTEGER;
		if (GetThreadContext(reported_thread, &context))
		{
			/* the image may load anywhere (ASLR): llvm-symbolizer wants the
			addresses moved to the linked base */
			platform_log("stack report: main thread at eip %08lx ebp %08lx (image at %p)",
				context.Eip, context.Ebp, (void *)GetModuleHandleA(NULL));
			frame_chain_log("stack report", context.Ebp);
			fflush(stderr);
		}
		ResumeThread(reported_thread);
	}
	return 0;
}

__attribute__((constructor))
static void stack_reports_install(void)
{
	double seconds;

	/* (not the crash reporter's copy of the game: win32_crash.c) */
	if (crash_reporter_process())
		return;
	seconds = config_real("debug.sample_seconds");
	/* at most a day apart; constructors run on the main thread */
	if (seconds > 86400.0)
		seconds = 86400.0;
	if (seconds >= 0.001 &&
		DuplicateHandle(GetCurrentProcess(), GetCurrentThread(), GetCurrentProcess(), &reported_thread,
			THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT, FALSE, 0))
	{
		report_interval_milliseconds = (DWORD)(seconds * 1000.0);
		CloseHandle(CreateThread(NULL, 0, stack_report_thread, NULL, 0, NULL));
	}
}

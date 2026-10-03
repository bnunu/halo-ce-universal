"""Compile the shipped Mac clocks against a controlled monotonic OS clock.

No game data or full build is needed. Only clock_gettime and the Windows scalar
types are supplied by the fixture; the origin and exported clock functions are
extracted unchanged from xbox_kernel.c. A native pthread test races first use
of both clock APIs and checks that every caller observes one shared origin.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

PREFIX = r'''
#include <assert.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define WINAPI
#define TRUE 1
typedef uint32_t DWORD;
typedef int BOOL;
typedef int64_t LONGLONG;
typedef struct { int64_t QuadPart; } LARGE_INTEGER;

static _Atomic uint64_t next_nanoseconds;
static uint64_t step_nanoseconds;
static _Thread_local uint64_t sampled_nanoseconds;

static int fixture_clock_gettime(clockid_t clock, struct timespec *now)
{
    assert(clock == CLOCK_MONOTONIC);
    sampled_nanoseconds = atomic_fetch_add_explicit(
        &next_nanoseconds, step_nanoseconds, memory_order_relaxed);
    now->tv_sec = (time_t)(sampled_nanoseconds / UINT64_C(1000000000));
    now->tv_nsec = (long)(sampled_nanoseconds % UINT64_C(1000000000));
    if (step_nanoseconds) sched_yield();
    return 0;
}
#define clock_gettime fixture_clock_gettime
'''

HARNESS = r'''
#undef clock_gettime

static void frequency_is_microseconds(void)
{
    LARGE_INTEGER frequency = {0};
    assert(QueryPerformanceFrequency(&frequency));
    assert(frequency.QuadPart == INT64_C(1000000));
}

#ifdef HALO_MACOS
static void long_uptime(uint64_t uptime, int performance_first)
{
    LARGE_INTEGER counter = {0};
    uint32_t previous_tick;
    int64_t previous_counter;
    atomic_store(&next_nanoseconds, uptime);
    if (performance_first) {
        assert(QueryPerformanceCounter(&counter));
        assert(counter.QuadPart == INT64_C(10000000));
    } else {
        assert(GetTickCount() == 10000);
    }
    assert(GetTickCount() == 10000);
    assert(QueryPerformanceCounter(&counter));
    assert(counter.QuadPart == INT64_C(10000000));
    previous_tick = GetTickCount();
    previous_counter = counter.QuadPart;
    /* A 120 Hz sequence must retain sub-millisecond counter precision even
       after OS uptime has crossed signed and unsigned 32-bit milliseconds. */
    for (uint64_t frame = 1; frame <= 7200; ++frame) {
        uint64_t elapsed = frame * UINT64_C(8333333);
        atomic_store(&next_nanoseconds, uptime + elapsed);
        uint32_t tick = GetTickCount();
        assert(QueryPerformanceCounter(&counter));
        assert(tick == 10000 + elapsed / UINT64_C(1000000));
        assert(counter.QuadPart == INT64_C(10000000) + (int64_t)(elapsed / 1000));
        assert((int32_t)tick > 0);
        assert(tick > previous_tick && tick - previous_tick <= 9);
        assert(counter.QuadPart > previous_counter && counter.QuadPart - previous_counter <= 8334);
        previous_tick = tick;
        previous_counter = counter.QuadPart;
    }
    puts("Mac clocks preserve elapsed time and precision across long OS uptime");
}

enum { THREAD_COUNT = 24, READS_PER_THREAD = 128 };
static pthread_mutex_t gate_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t ready_condition = PTHREAD_COND_INITIALIZER;
static pthread_cond_t start_condition = PTHREAD_COND_INITIALIZER;
static int threads_ready, start_threads;
static uint64_t origins[THREAD_COUNT];

static uint64_t observed_origin(int performance, uint64_t *elapsed)
{
    if (performance) {
        LARGE_INTEGER counter;
        assert(QueryPerformanceCounter(&counter));
        *elapsed = (uint64_t)counter.QuadPart * UINT64_C(1000);
    } else {
        *elapsed = (uint64_t)GetTickCount() * UINT64_C(1000000);
    }
    return sampled_nanoseconds - *elapsed;
}

static void *first_use_thread(void *context)
{
    uintptr_t index = (uintptr_t)context;
    uint64_t previous = 0;
    assert(!pthread_mutex_lock(&gate_lock));
    ++threads_ready;
    assert(!pthread_cond_signal(&ready_condition));
    while (!start_threads) assert(!pthread_cond_wait(&start_condition, &gate_lock));
    assert(!pthread_mutex_unlock(&gate_lock));
    for (unsigned read = 0; read < READS_PER_THREAD; ++read) {
        uint64_t elapsed;
        /* Half the threads first enter GetTickCount, half QPC. Each switches
           between APIs so separate origins cannot accidentally pass. */
        uint64_t origin = observed_origin((int)((index + read) & 1), &elapsed);
        if (!read) origins[index] = origin;
        assert(origin == origins[index]);
        assert(elapsed >= previous);
        previous = elapsed;
    }
    return NULL;
}

static void concurrent_first_use(uint64_t uptime)
{
    pthread_t threads[THREAD_COUNT];
    /* Millisecond-aligned samples make the origin exactly recoverable from
       either API. Samples differ across threads to expose per-thread clocks. */
    atomic_store(&next_nanoseconds, uptime);
    step_nanoseconds = UINT64_C(1000000);
    for (uintptr_t index = 0; index < THREAD_COUNT; ++index)
        assert(!pthread_create(&threads[index], NULL, first_use_thread, (void *)index));
    assert(!pthread_mutex_lock(&gate_lock));
    while (threads_ready != THREAD_COUNT)
        assert(!pthread_cond_wait(&ready_condition, &gate_lock));
    start_threads = 1;
    assert(!pthread_cond_broadcast(&start_condition));
    assert(!pthread_mutex_unlock(&gate_lock));
    for (unsigned index = 0; index < THREAD_COUNT; ++index) {
        assert(!pthread_join(threads[index], NULL));
        assert(origins[index] == origins[0]);
    }
    assert(origins[0] >= uptime - UINT64_C(10000000000));
    assert(origins[0] < uptime - UINT64_C(10000000000) + THREAD_COUNT * step_nanoseconds);
    puts("Concurrent clock calls share one process origin");
}
#endif

int main(int argc, char **argv)
{
    assert(argc == 3);
    uint64_t uptime = strtoull(argv[2], NULL, 10);
    frequency_is_microseconds();
#ifdef HALO_MACOS
    if (!strcmp(argv[1], "threads")) concurrent_first_use(uptime);
    else long_uptime(uptime, !strcmp(argv[1], "counter-first"));
#else
    LARGE_INTEGER counter;
    atomic_store(&next_nanoseconds, uptime);
    assert(GetTickCount() == (uint32_t)(uptime / UINT64_C(1000000)));
    assert(QueryPerformanceCounter(&counter));
    assert(counter.QuadPart == (int64_t)(uptime / 1000));
    puts("Other ports retain the existing OS-uptime clocks");
#endif
    return 0;
}
'''


class MacClockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="halo-mac-clock-")
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        source = (ROOT / "port/linux/src/xbox_kernel.c").read_text()
        start = source.index("/* ---------- time */")
        end = source.index("/* seconds between 1601-01-01", start)
        fixture = directory / "clock.c"
        fixture.write_text(PREFIX + source[start:end] + HARNESS)
        cls.executables = {}
        for platform, flags in (("macos", ["-DHALO_MACOS=1"]), ("other", [])):
            executable = directory / platform
            built = subprocess.run(["clang", "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror",
                                    "-pthread", *flags, str(fixture), "-o", str(executable)],
                                   capture_output=True, text=True, timeout=30)
            if built.returncode:
                raise AssertionError(built.stderr)
            cls.executables[platform] = executable

    def run_clock(self, mode, uptime, platform="macos"):
        result = subprocess.run([str(self.executables[platform]), mode, str(uptime)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_long_uptime_both_api_entry_orders(self):
        uptimes = (45 * 86400 * 10**9 + 123456789, (2**32 - 5) * 10**6, 400 * 86400 * 10**9)
        for uptime in uptimes:
            for mode in ("ticks-first", "counter-first"):
                with self.subTest(uptime=uptime, mode=mode):
                    self.run_clock(mode, uptime)

    def test_concurrent_first_use_shares_origin_between_apis(self):
        # A fresh process gives the actual function-local static a fresh start.
        for iteration in range(4):
            with self.subTest(iteration=iteration):
                self.run_clock("threads", 400 * 86400 * 10**9)

    def test_other_ports_keep_existing_clock_origin(self):
        for uptime in (45 * 86400 * 10**9 + 123456789, (2**32 + 5) * 10**6):
            with self.subTest(uptime=uptime):
                self.run_clock("ticks-first", uptime, platform="other")


if __name__ == "__main__":
    unittest.main()

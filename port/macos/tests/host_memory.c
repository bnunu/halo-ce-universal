/* Exercise the real Darwin allocator and syscall boundary without game data. */
#include "host.h"
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

void host_logf(int priority, const char *format, ...) {
    (void)priority;
    va_list arguments;
    va_start(arguments, format);
    vfprintf(stderr, format, arguments);
    va_end(arguments);
}
void host_exit(int code) { exit(code); }
extern long long host_syscall(long long, long long, long long, long long, long long, long long,
                              long long);
static uint32_t *futex_word;
static void *wake_thread(void *unused) {
    (void)unused;
    usleep(20000);
    __atomic_store_n(futex_word, 1, __ATOMIC_SEQ_CST);
    host_syscall(98, (uint32_t)(uintptr_t)futex_word, 1, 1, 0, 0, 0);
    return NULL;
}

int main(void) {
    assert(host_memory_initialize(HALO_GUEST_IMAGE_BASE, 0x40000) == 0);
    host_install_signal_handlers();
    unsigned char *first = host_low_map(4096, PROT_READ | PROT_WRITE);
    assert(first);
    memset(first, 0x82, HALO_MACOS_PAGE);
    host_low_unmap(first, 4096);
    unsigned char *reused = host_low_map(4096, PROT_READ | PROT_WRITE);
    assert(reused == first);
    for (unsigned i = 0; i < HALO_MACOS_PAGE; i++)
        assert(reused[i] == 0);

    const uint32_t a = HALO_GUEST_WINDOW_BASE + 0x3a5000;
    const uint32_t b = a + 4096;
    assert(host_guest_mmap(a, 4096, PROT_READ | PROT_WRITE, 0x32, -1, 0) == a);
    memset(guest_pointer(a), 0x63, 4096);
    assert(host_guest_mmap(b, 4096, PROT_READ | PROT_WRITE, 0x32, -1, 0) == b);
    memset(guest_pointer(b), 0x45, 4096);
    assert(host_guest_mmap(b, 4096, PROT_NONE, 0x32, -1, 0) == b);
    for (unsigned i = 0; i < 4096; i++)
        assert(((unsigned char *)guest_pointer(a))[i] == 0x63);
    assert(host_guest_mmap(b, 4096, PROT_READ | PROT_WRITE, 0x32, -1, 0) == b);
    for (unsigned i = 0; i < 4096; i++)
        assert(((unsigned char *)guest_pointer(b))[i] == 0);

    uint32_t before = host_memory_watch_generation(a, 4096);
    host_memory_watch_protect(a, 4096);
    *(volatile uint32_t *)guest_pointer(a) = 0x12345678;
    assert(host_memory_watch_generation(a, 4096) > before);
    assert(*(uint32_t *)guest_pointer(a) == 0x12345678);
    assert(host_guest_mmap(0x1000, 4096, PROT_READ, 0x32, -1, 0) == -22);

    futex_word = (uint32_t *)reused;
    pthread_t thread;
    assert(pthread_create(&thread, NULL, wake_thread, NULL) == 0);
    long long wait_result = host_syscall(98, (uint32_t)(uintptr_t)futex_word, 0, 0, 0, 0, 0);
    assert(wait_result == 0 || wait_result == -11);
    pthread_join(thread, NULL);
    assert(*futex_word == 1);
    assert(host_syscall(113, 1, (uint32_t)(uintptr_t)(reused + 16), 0, 0, 0, 0) == 0);
    assert(*(int32_t *)(reused + 16) >= 0);
    puts("Darwin allocator, 4 KB neighbors, write watch, futex, and clock passed");
    return 0;
}

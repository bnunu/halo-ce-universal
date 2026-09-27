/* Probe the address-space assumptions of the Android ILP32 runtime.
 * This is a diagnostic executable, not the game. Never replace mappings:
 * mmap hints let the OS reject an unavailable address without overwriting it.
 */
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/mman.h>
#include <unistd.h>

static int probe_address(uintptr_t address, size_t size) {
    void *mapping =
        mmap((void *)address, size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
    int available = mapping == (void *)address;
    int error = mapping == MAP_FAILED ? errno : 0;

    printf("{\"requested\":%llu,\"mapped\":%llu,\"available\":%s,\"errno\":%d}",
           (unsigned long long)address,
           mapping == MAP_FAILED ? 0ULL : (unsigned long long)(uintptr_t)mapping,
           available ? "true" : "false", error);
    if (mapping != MAP_FAILED)
        munmap(mapping, size);
    return available;
}

int main(void) {
    long page_size = sysconf(_SC_PAGESIZE);
    int window, image;

    if (page_size <= 0)
        return 1;
    printf("{\"page_size\":%ld,\"pointer_size\":%zu,\"mappings\":[", page_size, sizeof(void *));
    window = probe_address(0x80000000u, 0x08000000u);
    printf(",");
    image = probe_address(0x88000000u, (size_t)page_size);
    printf("]}\n");
    return window && image ? 0 : 2;
}

/* Instructions are part of the signed Mach-O __TEXT segment. Only the
 * guest's separate data copy and host-import table are changed at startup. */
#include "host.h"
#include "image.h"
#include <string.h>
#include <sys/mman.h>

struct host_guest_image host_image;
void *guest_code_pointer(uint32_t address) {
    if (address < HALO_IOS_IMAGE_BASE || address >= HALO_IOS_IMAGE_BASE + HALO_IOS_IMAGE_SIZE)
        host_fatal("Invalid game function %08x", address);
    return (void *)(halo_ios_image + address - HALO_IOS_IMAGE_BASE);
}
static int extent(uint32_t address, uint64_t size) {
    return address >= HALO_IOS_IMAGE_BASE &&
        (uint64_t)address + size <= HALO_IOS_IMAGE_BASE + HALO_IOS_IMAGE_SIZE;
}
int host_load_image(const void *unused, size_t unused_size) {
    (void)unused; (void)unused_size;
    if (host_memory_initialize(HALO_IOS_IMAGE_BASE, HALO_IOS_IMAGE_SIZE))
        return -1;
    memcpy(guest_pointer(HALO_IOS_IMAGE_BASE), halo_ios_image, HALO_IOS_IMAGE_SIZE);
    const struct halo_guest_header *h = guest_pointer(HALO_IOS_IMAGE_BASE);
    if (h->magic != HALO_GUEST_MAGIC || h->abi_version != HALO_GUEST_ABI_VERSION ||
        !extent(h->image_end, 0) || !extent(h->import_count, 4))
        return -1;
    host_image = (struct host_guest_image){h, HALO_IOS_IMAGE_BASE,
        HALO_IOS_IMAGE_BASE + HALO_IOS_IMAGE_SIZE};
    uint32_t count = *(const uint32_t *)guest_pointer(h->import_count);
    if (count > 4096 || !extent(h->import_table, (uint64_t)count * 8) ||
        !extent(h->import_names, 1))
        return -1;
    uint64_t *table = guest_pointer(h->import_table);
    const char *name = guest_pointer(h->import_names);
    const char *end = guest_pointer(host_image.end);
    for (uint32_t i = 0; i < count; i++) {
        if (name >= end || !memchr(name, 0, (size_t)(end - name))) return -1;
        void *fn = host_resolve_import(name);
        if (!fn && !strncmp(name, "hostgl_", 7)) fn = host_gl_resolve(name + 7);
        if (!fn) {
            host_logf(HOST_LOG_ERROR, "Missing import: %s", name);
            return -1;
        }
        table[i] = (uintptr_t)fn;
        name += strlen(name) + 1;
    }
    uint64_t *delta = guest_pointer(0xff0000);
    if (mprotect(delta, HALO_MACOS_PAGE, PROT_READ | PROT_WRITE)) return -1;
    *delta = (uintptr_t)halo_ios_image - HALO_IOS_IMAGE_BASE;
    if (mprotect(delta, HALO_MACOS_PAGE, PROT_READ)) return -1;
    host_logf(HOST_LOG_INFO, "Signed iOS image %p, data %p, %u imports",
        halo_ios_image, h, count);
    return 0;
}

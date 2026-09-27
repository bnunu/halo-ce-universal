/* Executes guest instructions from a signed __TEXT section, with RW-only data. */
#include "image.h"
#include <mach/mach.h>
#include <mach/mach_vm.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#define BIAS UINT64_C(0x400000000)
static void *run(void *unused) {
    (void)unused;
    uint32_t (*entry)(uint32_t) = (void *)(halo_ios_image + HALO_IOS_IMAGE_ENTRY - HALO_IOS_IMAGE_BASE);
    uint32_t result = entry(42);
    printf("Signed image probe: result=%u expected=93; code=%p data=%p\n", result,
           (void *)entry, (void *)(BIAS + HALO_IOS_IMAGE_BASE));
    return (void *)(uintptr_t)(result != 93);
}
int main(void) {
    mach_vm_address_t address = BIAS;
    if (mach_vm_allocate(mach_task_self(), &address, UINT64_C(0x100000000), VM_FLAGS_FIXED)) {
        fprintf(stderr, "Cannot reserve iOS guest arena at 16 GB\n");
        return 1;
    }
    mprotect((void *)BIAS, UINT64_C(0x100000000), PROT_NONE);
    mprotect((void *)(BIAS + HALO_IOS_IMAGE_BASE), HALO_IOS_IMAGE_SIZE, PROT_READ | PROT_WRITE);
    memcpy((void *)(BIAS + HALO_IOS_IMAGE_BASE), halo_ios_image, HALO_IOS_IMAGE_SIZE);
    mprotect((void *)(BIAS + 0xff0000), 16384, PROT_READ | PROT_WRITE);
    *(uint64_t *)(BIAS + 0xff0000) = (uintptr_t)halo_ios_image - HALO_IOS_IMAGE_BASE;
    mprotect((void *)(BIAS + 0xff0000), 16384, PROT_READ);
    mprotect((void *)(BIAS + 0x80000000), 16384, PROT_READ | PROT_WRITE);
    void *stack = (void *)(BIAS + 0x90000000);
    mprotect(stack, 0x400000, PROT_READ | PROT_WRITE);
    pthread_attr_t attributes;
    pthread_attr_init(&attributes);
    pthread_attr_setstack(&attributes, stack, 0x400000);
    pthread_t thread;
    if (pthread_create(&thread, &attributes, run, NULL)) return 2;
    void *result;
    pthread_join(thread, &result);
    return (int)(uintptr_t)result;
}

#include <libkern/OSCacheControl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#define BASE UINT64_C(0x10000000000)
typedef struct {
    unsigned char ident[16];
    uint16_t type, machine;
    uint32_t version;
    uint64_t entry, phoff, shoff;
    uint32_t flags;
    uint16_t ehsize, phentsize, phnum, shentsize, shnum, shstrndx;
} Elf;
typedef struct {
    uint32_t type, flags;
    uint64_t offset, vaddr, paddr, filesz, memsz, align;
} Ph;
static uint32_t (*guest)(uint32_t);
static void *map_at(uint64_t a, size_t n) {
    void *p = mmap((void *)a, n, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
    if (p != (void *)a) {
        perror("mapping");
        fprintf(stderr, "wanted %llx, got %p\n", a, p);
        exit(1);
    }
    return p;
}
static void *run(void *unused) {
    volatile int stack = 0;
    uint32_t r = guest(42);
    printf("guest result=%u expected=93; stack=%p; Xbox word=%u\n", r, &stack,
           *(uint32_t *)(BASE + 0x80000000));
    return (void *)(uintptr_t)(r != 93);
}
int main(int argc, char **argv) {
    if (argc != 2)
        return 2;
    FILE *f = fopen(argv[1], "rb");
    if (!f) {
        perror("fopen");
        return 2;
    }
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    rewind(f);
    unsigned char *file = malloc(n);
    if (fread(file, 1, n, f) != (size_t)n)
        return 2;
    fclose(f);
    Elf *e = (Elf *)file;
    if (memcmp(e->ident, "\177ELF", 4) || e->phentsize != sizeof(Ph))
        return 2;
    void *image = map_at(BASE + 0x88000000, 0x40000);
    map_at(BASE + 0x80000000, 0x4000);
    for (unsigned i = 0; i < e->phnum; i++) {
        Ph *p = (Ph *)(file + e->phoff + i * sizeof(Ph));
        if (p->type != 1 || p->vaddr < 0x88000000)
            continue;
        if (p->vaddr + p->memsz > 0x88040000 || p->offset + p->filesz > (uint64_t)n)
            return 2;
        memcpy((void *)(BASE + p->vaddr), file + p->offset, p->filesz);
    }
    sys_icache_invalidate(image, 0x4000);
    if (mprotect(image, 0x4000, PROT_READ | PROT_EXEC)) {
        perror("RX");
        return 2;
    }
    guest = (void *)(BASE + e->entry);
    void *stack = map_at(BASE + 0x90000000, 0x400000);
    pthread_attr_t a;
    pthread_attr_init(&a);
    pthread_attr_setstack(&a, stack, 0x400000);
    pthread_t t;
    int err = pthread_create(&t, &a, run, 0);
    if (err) {
        fprintf(stderr, "thread %d\n", err);
        return 2;
    }
    void *result = 0;
    pthread_join(t, &result);
    return (int)(uintptr_t)result;
}

/* Minimal freestanding memory routines for the signed-image ABI probe. */
void *memcpy(void *destination, const void *source, unsigned long size) {
    unsigned char *d = destination;
    const unsigned char *s = source;
    while (size--) *d++ = *s++;
    return destination;
}
void *memmove(void *destination, const void *source, unsigned long size) {
    unsigned char *d = destination;
    const unsigned char *s = source;
    if (d < s) return memcpy(d, s, size);
    while (size) { --size; d[size] = s[size]; }
    return destination;
}
int memcmp(const void *left, const void *right, unsigned long size) {
    const unsigned char *a = left, *b = right;
    while (size--) { if (*a != *b) return *a - *b; a++; b++; }
    return 0;
}

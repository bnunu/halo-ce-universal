/* Native execution probe for 32-bit guest layouts above 4 GB. */
typedef unsigned int u32;
_Static_assert(sizeof(void *) == 4, "guest pointer layout");
_Static_assert(sizeof(long) == 4, "guest long layout");
extern void *memcpy(void *, const void *, unsigned long);
extern void *memmove(void *, const void *, unsigned long);
extern int memcmp(const void *, const void *, unsigned long);
static volatile u32 global = 7;
struct pair { u32 a, b; };
__attribute__((noinline)) static u32 sum_pair(const struct pair *p) {
    unsigned long long word;
    __builtin_memcpy(&word, p, sizeof(word));
    return (u32)word + (u32)(word >> 32);
}
__attribute__((noinline)) static u32 inc(u32 *p) { return ++*p; }
__attribute__((noinline)) static u32 variadic(int first, ...) {
    __builtin_va_list args, copy;
    __builtin_va_start(args, first);
    __builtin_va_copy(copy, args);
    int a = __builtin_va_arg(copy, int);
    double b = __builtin_va_arg(copy, double);
    long long c = __builtin_va_arg(copy, long long);
    u32 *p = __builtin_va_arg(copy, u32 *);
    __builtin_va_end(copy);
    __builtin_va_end(args);
    return (u32)(first + a + b + c + *p);
}
u32 guest_test(u32 value) {
    /* A stack address arrives in a full X register, despite ILP32's pointer
       type. Adjacent loads must not add the arena bias a second time. */
    struct pair pair = {value, value + 1};
    u32 (*volatile read_pair)(const struct pair *) = sum_pair;
    if (read_pair(&pair) != value * 2 + 1)
        return 105;
    volatile u32 stack = value;
    u32 (*volatile fp)(u32 *) = inc;
    u32 *volatile xbox = (u32 *)0x80000000;
    *xbox = stack;
    global += fp(xbox);
    if (variadic(1, 2, 3.0, 4LL, (u32 *)xbox) != 53)
        return 100;
    char a[64], b[64];
    for (u32 i = 0; i < 64; i++)
        a[i] = (char)i;
    memcpy(b, a, value);
    if (memcmp(a, b, value))
        return 101;
    memmove(b + 3, b, 30);
    for (u32 i = 0; i < 30; i++)
        if (b[i + 3] != (char)i)
            return 102;
    volatile u32 atomic = 2;
    if (__atomic_fetch_add(&atomic, 3, __ATOMIC_SEQ_CST) != 2 || atomic != 5)
        return 103;
    u32 expected = 5;
    if (!__atomic_compare_exchange_n(&atomic, &expected, 9, 0, __ATOMIC_SEQ_CST,
                                     __ATOMIC_SEQ_CST) ||
        atomic != 9)
        return 104;
    return global + *xbox;
}

/* No guest engine is needed for the real native menu/SDL main-loop test. */
#include "host.h"
#include <stdio.h>
#include <stdlib.h>

void host_perf_frame(double swap_ms) { (void)swap_ms; }
void host_logf(int priority, const char *format, ...) {
    (void)priority;
    va_list arguments;
    va_start(arguments, format);
    vfprintf(stderr, format, arguments);
    fputc('\n', stderr);
    va_end(arguments);
}
void host_fatal(const char *format, ...) {
    (void)format;
    abort();
}
int host_native_thread_create(void *(*function)(void *), void *argument, size_t size) {
    (void)function; (void)argument; (void)size;
    abort();
}
uint32_t host_call_guest(uint32_t function, uint32_t a, uint32_t b, uint32_t c, uint32_t d) {
    (void)function; (void)a; (void)b; (void)c; (void)d;
    abort();
}

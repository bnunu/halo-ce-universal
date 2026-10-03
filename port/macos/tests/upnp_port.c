/* The native UPnP cleanup must leave an active game's port alone. */
#include <assert.h>
#include <netinet/in.h>
#include <stdio.h>
#include <unistd.h>
#include "port/macos/host/posix_upnp.c"

int main(void) {
    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    assert(fd >= 0);
    struct sockaddr_in address = {.sin_len = sizeof(address), .sin_family = AF_INET};
    assert(bind(fd, (const struct sockaddr *)&address, sizeof(address)) == 0);
    socklen_t length = sizeof(address);
    assert(getsockname(fd, (struct sockaddr *)&address, &length) == 0);
    assert(address.sin_port);
    assert(!port_unused(address.sin_port));
    assert(close(fd) == 0);
    assert(port_unused(address.sin_port));
    puts("Darwin UPnP probe distinguishes occupied and unused UDP ports");
    return 0;
}

/* Exercise the real Mac transport against a local RPC peer or desktop Discord. */
#include "posix.h"
#include <assert.h>
#include <fcntl.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

static void wait_readable(int fd) {
    struct pollfd ready = {.fd = fd, .events = POLLIN};
    assert(poll(&ready, 1, 5000) == 1);
}

static void read_bytes(int fd, unsigned char *bytes, int size) {
    while (size > 0) {
        wait_readable(fd);
        int count = posix_discord_read(fd, bytes, size);
        assert(count > 0);
        bytes += count;
        size -= count;
    }
}

static void send_frame(int fd, int opcode, const char *json) {
    unsigned char bytes[1024] = {0};
    size_t length = strlen(json);
    assert(length + 8 <= sizeof(bytes));
    bytes[0] = (unsigned char)opcode;
    bytes[4] = (unsigned char)length;
    bytes[5] = (unsigned char)(length >> 8);
    memcpy(bytes + 8, json, length);
    int size = (int)length + 8, offset = 0;
    while (offset < size) {
        int count = posix_discord_write(fd, bytes + offset, size - offset);
        assert(count >= 0);
        if (!count) {
            struct pollfd ready = {.fd = fd, .events = POLLOUT};
            assert(poll(&ready, 1, 5000) == 1);
        }
        offset += count;
    }
}

static void receive_frame(int fd, char *json, int maximum) {
    unsigned char header[8];
    read_bytes(fd, header, sizeof(header));
    assert(header[0] == 1 && !header[1] && !header[2] && !header[3]);
    uint32_t size = (uint32_t)header[4] | (uint32_t)header[5] << 8 |
                    (uint32_t)header[6] << 16 | (uint32_t)header[7] << 24;
    assert(size < (uint32_t)maximum);
    read_bytes(fd, (unsigned char *)json, (int)size);
    json[size] = 0;
}

static void live_discord(void) {
    int fd = posix_discord_connect();
    assert(fd >= 0);
    send_frame(fd, 0, "{\"v\":1,\"client_id\":\"1553978809840050229\"}");
    char json[16384];
    receive_frame(fd, json, sizeof(json));
    assert(strstr(json, "\"READY\""));
    send_frame(fd, 1, "{\"cmd\":\"SUBSCRIBE\",\"evt\":\"ACTIVITY_JOIN\","
                      "\"nonce\":\"macos-invite-probe\"}");
    receive_frame(fd, json, sizeof(json));
    assert(!strstr(json, "\"ERROR\"") && strstr(json, "\"ACTIVITY_JOIN\"") &&
           strstr(json, "\"macos-invite-probe\""));
    posix_discord_close(fd);
    puts("Desktop Discord handshake and ACTIVITY_JOIN subscription accepted");
}

int main(int argc, char **argv) {
    if (argc == 2 && !strcmp(argv[1], "--live")) {
        live_discord();
        return 0;
    }
    assert(argc == 1);
    char directory[] = "/tmp/halo-discord-test.XXXXXX";
    assert(mkdtemp(directory));
    /* An oversized candidate must be skipped before trying the real TMPDIR. */
    char oversized[256];
    memset(oversized, 'x', sizeof(oversized) - 1);
    oversized[sizeof(oversized) - 1] = 0;
    assert(setenv("XDG_RUNTIME_DIR", oversized, 1) == 0);
    assert(setenv("TMPDIR", directory, 1) == 0);
    struct sockaddr_un address = {.sun_family = AF_UNIX, .sun_len = sizeof(address)};
    snprintf(address.sun_path, sizeof(address.sun_path), "%s/discord-ipc-4", directory);
    int server = socket(AF_UNIX, SOCK_STREAM, 0);
    assert(server >= 0 && bind(server, (void *)&address, sizeof(address)) == 0);
    assert(listen(server, 1) == 0);
    int client = posix_discord_connect();
    assert(client >= 0);
    assert(fcntl(client, F_GETFL) & O_NONBLOCK);
    assert(fcntl(client, F_GETFD) & FD_CLOEXEC);
    int peer = accept(server, NULL, NULL);
    assert(peer >= 0);
    char bytes[128];
    assert(posix_discord_read(client, bytes, sizeof(bytes)) == 0);
    const char request[] = "RPC handshake";
    assert(posix_discord_write(client, request, sizeof(request)) == sizeof(request));
    wait_readable(peer);
    assert(recv(peer, bytes, sizeof(bytes), 0) == sizeof(request));
    assert(!memcmp(bytes, request, sizeof(request)));
    const char first[] = "partial ", second[] = "invite event";
    assert(send(peer, first, sizeof(first), 0) == sizeof(first));
    read_bytes(client, (unsigned char *)bytes, sizeof(first));
    assert(!memcmp(bytes, first, sizeof(first)));
    assert(posix_discord_read(client, bytes, sizeof(bytes)) == 0);
    assert(send(peer, second, sizeof(second), 0) == sizeof(second));
    read_bytes(client, (unsigned char *)bytes, sizeof(second));
    assert(!memcmp(bytes, second, sizeof(second)));
    assert(close(peer) == 0);
    wait_readable(client);
    assert(posix_discord_read(client, bytes, sizeof(bytes)) == -1);
    /* A stopped Discord client must not terminate Halo with SIGPIPE. */
    assert(posix_discord_write(client, request, sizeof(request)) == -1);
    posix_discord_close(client);
    assert(close(server) == 0 && unlink(address.sun_path) == 0 && rmdir(directory) == 0);
    puts("Mac Discord socket discovery, nonblocking IO and disconnect handling passed");
    return 0;
}

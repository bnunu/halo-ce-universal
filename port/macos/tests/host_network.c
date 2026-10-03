/* Exercise the Darwin Winsock adapter with the game's IPv4 address layout. */
#include "posix.h"
#include <arpa/inet.h>
#include <assert.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>

struct guest_address {
    uint16_t family;
    uint16_t port;
    uint32_t address;
    uint8_t padding[8];
};
_Static_assert(sizeof(struct guest_address) == 16, "Xbox IPv4 address size");

static int bound_socket(struct guest_address *address) {
    int fd = posix_socket(AF_INET, SOCK_DGRAM, 0);
    assert(fd >= 0);
    *address = (struct guest_address){.family = AF_INET, .address = htonl(INADDR_LOOPBACK)};
    assert(posix_socket_bind(fd, address, sizeof(*address)) == 0);
    int length = sizeof(*address);
    assert(posix_socket_getsockname(fd, address, &length) == 0);
    assert(length == sizeof(*address));
    assert(address->family == AF_INET && address->port != 0);
    assert(posix_socket_set_nonblocking(fd, 1) == 0);
    return fd;
}

static void receive_packet(int fd, const struct guest_address *sender,
                           const char *expected, int length) {
    struct pollfd ready = {.fd = fd, .events = POLLIN};
    assert(poll(&ready, 1, 1000) == 1 && (ready.revents & POLLIN));
    char buffer[64];
    struct guest_address from;
    int from_length = sizeof(from);
    assert(posix_socket_recvfrom(fd, buffer, sizeof(buffer), 0, &from, &from_length) == length);
    assert(from_length == sizeof(from));
    assert(from.family == sender->family && from.port == sender->port &&
           from.address == sender->address);
    assert(memcmp(buffer, expected, length) == 0);
}

int main(void) {
    struct guest_address server_address, client_address, other_address;
    int server = bound_socket(&server_address);
    int client = bound_socket(&client_address);
    int other = bound_socket(&other_address);

    /* Discovery uses an unconnected datagram socket. */
    const char discovery[] = "discovery";
    assert(posix_socket_sendto(client, discovery, sizeof(discovery), 0,
                              &server_address, sizeof(server_address)) == sizeof(discovery));
    receive_packet(server, &client_address, discovery, sizeof(discovery));

    /* Gameplay connects UDP, but still supplies the server to sendto(). */
    assert(posix_socket_connect(client, &server_address, sizeof(server_address)) == 0);
    const char update[] = "player input";
    for (int i = 0; i < 3; i++) {
        assert(posix_socket_sendto(client, update, sizeof(update), 0,
                                  &server_address, sizeof(server_address)) == sizeof(update));
        assert(posix_socket_last_error() == 0);
        receive_packet(server, &client_address, update, sizeof(update));
    }
    assert(posix_socket_sendto(client, "", 0, 0, &server_address, sizeof(server_address)) == 0);
    receive_packet(server, &client_address, "", 0);
    const char connected[] = "default connected peer";
    assert(posix_socket_sendto(client, connected, sizeof(connected), 0, NULL, 0) == sizeof(connected));
    receive_packet(server, &client_address, connected, sizeof(connected));

    /* Upstream rejects truncated UDP messages instead of parsing a prefix. */
    const char large[] = "a datagram longer than the receiving buffer";
    assert(posix_socket_sendto(client, large, sizeof(large), 0,
                              &server_address, sizeof(server_address)) == sizeof(large));
    struct pollfd ready = {.fd = server, .events = POLLIN};
    assert(poll(&ready, 1, 1000) == 1 && (ready.revents & POLLIN));
    char prefix[4];
    struct guest_address from;
    int from_length = sizeof(from);
    assert(posix_socket_recvfrom(server, prefix, sizeof(prefix), 0,
                                &from, &from_length) == -1);
    assert(posix_socket_last_error() == 10040); /* WSAEMSGSIZE */
    assert(from_length == sizeof(from) && from.family == AF_INET);
    assert(from.port == client_address.port && from.address == client_address.address);

    /* The fallback must never redirect a different destination to the connected peer. */
    assert(posix_socket_sendto(client, update, sizeof(update), 0,
                              &other_address, sizeof(other_address)) == -1);
    assert(posix_socket_last_error() == 10056); /* WSAEISCONN */
    struct guest_address different_ip = server_address;
    different_ip.address = htonl(INADDR_LOOPBACK + 1);
    assert(posix_socket_sendto(client, update, sizeof(update), 0,
                              &different_ip, sizeof(different_ip)) == -1);
    assert(posix_socket_last_error() == 10056);
    struct pollfd receivers[] = {{.fd = server, .events = POLLIN},
                                {.fd = other, .events = POLLIN}};
    assert(poll(receivers, 2, 50) == 0);

    assert(posix_socket_close(other) == 0);
    assert(posix_socket_close(client) == 0);
    assert(posix_socket_close(server) == 0);
    puts("Darwin UDP discovery, connected gameplay sends, and peer validation passed");
    return 0;
}

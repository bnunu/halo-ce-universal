# Mac and iPhone System Link

Build both devices from the same revision with the same map set. Native builds
use protocol version 2 and changed player capacities, so original Xbox games
and older native builds cannot join. See the [shared System Link notes](../port/linux/README.md#system-link)
for protocol details and limits.

## Connect the devices

Put the Mac and iPhone on the same LAN. Find the Mac's Wi-Fi IPv4 address in
System Settings → Wi-Fi → Details → TCP/IP, and the phone's in Settings → Wi-Fi
→ the information button beside the connected network. Allow Halo's local
network access when prompted. Guest networks with client isolation prevent
devices from reaching each other.

The current iPhone build uses explicit peer addresses for discovery. It does
not request Apple's multicast entitlement, which iOS requires for UDP
broadcast/multicast; ordinary unicast to the other device avoids that requirement.
See Apple's [multicast entitlement documentation](https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.developer.networking.multicast).

Quit existing copies of Halo. From the repository root, replace the placeholder
values below with your devices' current addresses:

```sh
MAC_IP=YOUR_MAC_WIFI_IP
PHONE_IP=YOUR_IPHONE_WIFI_IP

open -n \
  --env "HALO_NET_ADDRESS=$MAC_IP" \
  --env "HALO_NET_BROADCAST=$PHONE_IP" \
  "build/macos/Halo CE Universal.app"
```

For the iPhone, set these environment variables in Xcode → Product → Scheme →
Edit Scheme → Run → Arguments, then run the app:

| Variable | Value |
| --- | --- |
| `HALO_NET_ADDRESS` | The iPhone's Wi-Fi IPv4 address |
| `HALO_NET_BROADCAST` | The Mac's Wi-Fi IPv4 address |

Alternatively, install using the [iPhone instructions](../port/ios/README.md#install-on-a-phone)
and launch from the same shell as the Mac command. Replace the device and bundle
identifiers with your own:

```sh
xcrun devicectl device process launch --terminate-existing \
  --device YOUR_DEVICE_ID \
  --environment-variables "{\"HALO_NET_ADDRESS\":\"$PHONE_IP\",\"HALO_NET_BROADCAST\":\"$MAC_IP\"}" \
  com.yourname.halo
```

These environment settings apply only to that launch. To retain them for normal
launches, edit the existing `[network]` section of each device's `config.toml`:
set `address` to that device's IP and `broadcast` to the other device's IP. The
[Mac guide](../port/macos/README.md#launch) and [iPhone guide](../port/ios/README.md#install-on-a-phone)
give the save locations. Update these values if Wi-Fi or DHCP changes the
addresses. Keep personal addresses and generated Xcode schemes out of commits.

## Start a match

1. On the Mac, choose **Multiplayer → System Link**, select a player profile,
   and create a game (Y / Tab). Choose a map and a mode such as Blood Gulch / Slayer.
2. On the iPhone, choose **Multiplayer → System Link**, select a profile and
   join the Mac's advertised game.
3. Wait until both players appear in the lobby, then start the match on the host.

The session should keep running after both maps load, and movement, shots and
damage should agree on both devices. This setup covers LAN multiplayer; it does
not establish campaign co-op, internet matchmaking or compatibility with every
other native platform.

## Diagnosing a disconnect

The Darwin adapter handles Halo's connected UDP sockets specially: Halo still
passes the server address to `sendto()` after connecting, which Apple rejects
with `EISCONN`. The adapter retries with `send()` only if the destination matches
the connected datagram peer. Without this fix, discovery and joining work, but
gameplay packets fail and the match closes shortly after loading. Rebuild both
apps if either predates the fix.

The socket regression probe uses loopback and needs no game data or SDK:

```sh
mkdir -p build/macos/tests
clang -arch arm64 -O2 -Wall -I. -Iport/linux/src \
  port/macos/tests/host_network.c port/macos/host/posix_net.c \
  -o build/macos/tests/host_network
build/macos/tests/host_network
```

It checks discovery sends, connected gameplay sends, empty datagrams, received
addresses and refusal to redirect a mismatched destination to the connected peer.
It also runs as part of `python3 tools/test_macos_runtime.py`.

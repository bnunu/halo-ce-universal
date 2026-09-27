#!/usr/bin/env python3
"""Profile an isolated Mac campaign run, optionally spawning grenade effects.

Uses the game's existing local developer console. Quit other Halo instances
first. Maps are linked read-only by convention; saves and logs stay in --output.
"""
import argparse
import csv
import os
from pathlib import Path
import socket
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--level', choices=['a10', 'a30', 'b30'], default='a30')
    parser.add_argument('--seconds', type=int, default=70)
    parser.add_argument('--effects', action='store_true')
    parser.add_argument('--interval', type=float, default=2.0)
    parser.add_argument('--fullscreen', action='store_true')
    parser.add_argument('--guest', type=Path, default=ROOT / 'build/macos/halo_guest.elf')
    parser.add_argument('--host', type=Path, default=ROOT / 'build/macos/halo')
    args = parser.parse_args()
    try:
        with socket.create_connection(('127.0.0.1', 23), .5):
            raise SystemExit('Another game/debug console is running; quit it first.')
    except ConnectionRefusedError:
        pass
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    data = out / 'data'
    data.mkdir(exist_ok=True)
    if not (data / 'maps').exists():
        (data / 'maps').symlink_to(ROOT / 'assets/maps')
    (data / 'init.txt').write_text(f'map_name levels\\{args.level}\\{args.level}\n')
    settings = dict(os.environ, HALO_DATA_ROOT=str(data), HALO_SAVE_ROOT=str(out / 'saves'),
                    HALO_EXIT_AFTER=str(args.seconds), HALO_PERF_LOG=str(out / 'frames.csv'),
                    HALO_VOLUME='0')
    if not args.fullscreen:
        settings.update(HALO_WINDOWED='1', HALO_SCREEN_WIDTH='640')
    with (out / 'game.log').open('w') as log, (out / 'console.log').open('w') as console_log:
        process = subprocess.Popen([args.host.resolve(), args.guest.resolve()], env=settings,
                                   cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        start = time.monotonic()
        connection = None
        next_effect = start + 20
        try:
            while process.poll() is None and time.monotonic() - start < args.seconds + 40:
                now = time.monotonic()
                if args.effects and now >= next_effect:
                    try:
                        if not connection:
                            connection = socket.create_connection(('127.0.0.1', 23), .5)
                            connection.settimeout(.01)
                            connection.sendall(b'(set cheat_deathless_player true)\r\n')
                        command = '(effect_new_on_object_marker "weapons\\frag grenade\\effects\\explosion" (list_get (players) 0) "")'
                        connection.sendall((command + '\r\n').encode('ascii'))
                        console_log.write(f'\n[{now-start:.2f}s] {command}\n')
                    except OSError as error:
                        console_log.write(f'Console: {error}\n')
                    next_effect = now + max(.05, args.interval)
                if connection:
                    try:
                        response = connection.recv(65536)
                        console_log.write(response.decode('latin1'))
                        console_log.flush()
                    except TimeoutError:
                        pass
                time.sleep(.05)
        finally:
            if connection:
                connection.close()
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=10)
        print(f'Exit {process.returncode}; results: {out}')
    frames = list(csv.DictReader((out / 'frames.csv').open()))
    active = [r for r in frames if int(r['draws']) > 0]
    times = sorted(float(r['frame_ms']) for r in active)
    if times:
        print(f'{len(times)} rendered frames; median {times[len(times)//2]:.2f} ms; '
              f'p95 {times[int(len(times)*.95)]:.2f} ms; p99 {times[int(len(times)*.99)]:.2f} ms; '
              f'max footprint {max(float(r["footprint_mb"]) for r in frames):.0f} MB')
    if process.returncode:
        raise SystemExit(process.returncode)


if __name__ == '__main__':
    main()

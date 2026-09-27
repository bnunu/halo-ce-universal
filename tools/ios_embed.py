#!/usr/bin/env python3
"""Embed a prelinked ARM image in the signed Mach-O __TEXT segment.

The ELF file is build input only. On iOS, code executes from this signed,
read-only section; a separate nonexecutable arena holds guest data.
"""
from pathlib import Path
import argparse
import json
import struct

def embed(source, output):
    data = source.read_bytes()
    if data[:7] != b'\x7fELF\x02\x01\x01' or struct.unpack_from('<H', data, 18)[0] != 183:
        raise ValueError('Expected little-endian AArch64 ELF64')
    entry, phoff = struct.unpack_from('<QQ', data, 24)
    phsize, count = struct.unpack_from('<HH', data, 54)
    if phsize != 56 or phoff + phsize * count > len(data):
        raise ValueError('Invalid ELF program header table')
    segments = []
    for i in range(count):
        kind, flags, offset, address, _, size, memory, _ = struct.unpack_from('<IIQQQQQQ', data, phoff + i * phsize)
        if kind == 1 and address >= 0x88000000:
            if size > memory or offset + size > len(data) or address + memory > 0x90000000:
                raise ValueError('Invalid ELF load segment')
            segments.append((address, offset, size, memory, flags))
    base = min(s[0] for s in segments)
    end = max(s[0] + s[3] for s in segments)
    if base != 0x88000000 or end - base > 0x08000000:
        raise ValueError('Unexpected guest image layout')
    flat = bytearray((end - base + 16383) & ~16383)
    for address, offset, size, _, _ in segments:
        flat[address-base:address-base+size] = data[offset:offset+size]
    output.mkdir(parents=True, exist_ok=True)
    binary = output / 'guest.bin'
    binary.write_bytes(flat)
    (output / 'guest_image.s').write_text(
        '.section __TEXT,__halo,regular,pure_instructions\n.p2align 14\n'
        '.globl _halo_ios_image\n_halo_ios_image:\n'
        f'.incbin {json.dumps(str(binary.resolve()))}\n'
        '.globl _halo_ios_image_end\n_halo_ios_image_end:\n')
    metadata = dict(base=base, entry=entry, size=len(flat), segments=segments)
    (output / 'image.json').write_text(json.dumps(metadata, indent=2) + '\n')
    (output / 'image.h').write_text(
        '#include <stdint.h>\nextern const unsigned char halo_ios_image[], halo_ios_image_end[];\n'
        f'#define HALO_IOS_IMAGE_BASE 0x{base:x}u\n#define HALO_IOS_IMAGE_SIZE {len(flat)}u\n'
        f'#define HALO_IOS_IMAGE_ENTRY 0x{entry:x}u\n')
    return metadata

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('elf', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    print(embed(args.elf, args.output))

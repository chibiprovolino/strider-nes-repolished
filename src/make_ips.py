"""Write an IPS patch from an original ROM and a patched ROM of the same size, and check that it applies.

usage: python src/make_ips.py original.nes patched.nes out.ips
"""
import sys


def make(a, b):
    assert len(a) == len(b), 'the ROMs must have the same size'
    o = bytearray(b'PATCH')
    i = 0
    while i < len(b):
        if b[i] == a[i]:
            i += 1
            continue
        j = i
        # a record runs on over gaps of fewer than 4 unchanged bytes (cheaper than a new 5-byte header)
        while j < len(b) and (b[j] != a[j] or b[j:j + 4] != a[j:j + 4]):
            j += 1
        while i < j:
            k = min(j, i + 0xFFFF)
            assert i != 0x454F46, 'offset collides with the EOF marker'
            o += i.to_bytes(3, 'big') + (k - i).to_bytes(2, 'big') + b[i:k]
            i = k
    return bytes(o + b'EOF')


def apply(rom, ips):
    r = bytearray(rom)
    assert ips[:5] == b'PATCH'
    p = 5
    while ips[p:p + 3] != b'EOF':
        off = int.from_bytes(ips[p:p + 3], 'big')
        n = int.from_bytes(ips[p + 3:p + 5], 'big')
        p += 5
        if n == 0:                                  # RLE record
            n = int.from_bytes(ips[p:p + 2], 'big')
            r[off:off + n] = ips[p + 2:p + 3] * n
            p += 3
        else:
            r[off:off + n] = ips[p:p + n]
            p += n
    return bytes(r)


if __name__ == '__main__':
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    a = open(sys.argv[1], 'rb').read()
    b = open(sys.argv[2], 'rb').read()
    ips = make(a, b)
    open(sys.argv[3], 'wb').write(ips)
    print(f'{sys.argv[3]}: {len(ips)} bytes; applies cleanly: {apply(a, ips) == b}')

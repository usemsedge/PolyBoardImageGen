"""Overlay the projected board tile grid on a saved PNG (Python 3, stdlib only)."""

import argparse
import json
import math
from pathlib import Path
import struct
import zlib


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def load_grid(path):
    grid = json.loads(path.read_text(encoding="utf-8"))
    size = grid.get("size")
    width = grid.get("width")
    height = grid.get("height")
    if type(size) is not int or not 1 <= size <= 100:
        raise ValueError("size must be an integer from 1 to 100")
    if any(type(value) is not int or value <= 0 for value in (width, height)):
        raise ValueError("width and height must be positive integers")

    def point(key):
        value = grid.get(key)
        if (not isinstance(value, list) or len(value) != 2
                or any(type(n) not in (int, float) or not math.isfinite(n) for n in value)):
            raise ValueError(f"{key} must be a pair of finite numbers")
        return tuple(value)

    anchor, step_x, step_y = point("anchor"), point("stepX"), point("stepY")
    determinant = step_x[0] * step_y[1] - step_x[1] * step_y[0]
    if not math.isfinite(determinant) or abs(determinant) < 1e-6:
        raise ValueError("tile step vectors must form a nondegenerate grid")
    return size, width, height, anchor, step_x, step_y


def read_png(path):
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("input is not a PNG")
    offset = len(PNG_SIGNATURE)
    compressed = bytearray()
    width = height = channels = None
    ended = False
    while offset + 12 <= len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        end = offset + 12 + length
        if end > len(data):
            raise ValueError("truncated PNG chunk")
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        crc = struct.unpack_from(">I", data, offset + 8 + length)[0]
        if zlib.crc32(kind + payload) != crc:
            raise ValueError("PNG chunk checksum mismatch")
        offset = end
        if kind == b"IHDR":
            if width is not None or length != 13:
                raise ValueError("invalid PNG header")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", payload)
            if (not width or not height or width * height > 100_000_000
                    or depth != 8 or color not in (2, 6)
                    or compression or filtering or interlace):
                raise ValueError("expected a non-interlaced 8-bit RGB/RGBA PNG")
            channels = 3 if color == 2 else 4
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            ended = True
            break
        elif kind[0] & 0x20 == 0 and kind not in (b"PLTE",):
            raise ValueError(f"unsupported PNG chunk {kind!r}")
    if width is None or not ended or not compressed:
        raise ValueError("incomplete PNG")
    if offset != len(data):
        raise ValueError("unexpected data after PNG")
    stride = width * channels
    expected = height * (stride + 1)
    inflater = zlib.decompressobj()
    raw = inflater.decompress(compressed, expected + 1)
    if len(raw) != expected or not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:
        raise ValueError("invalid PNG image data")
    pixels = bytearray(height * stride)
    previous = bytearray(stride)
    for y in range(height):
        row_start = y * (stride + 1)
        filter_type = raw[row_start]
        row = bytearray(raw[row_start + 1:row_start + 1 + stride])
        if filter_type not in range(5):
            raise ValueError("unsupported PNG row filter")
        for i in range(stride):
            left = row[i - channels] if i >= channels else 0
            above = previous[i]
            upper_left = previous[i - channels] if i >= channels else 0
            if filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = above
            elif filter_type == 3:
                predictor = (left + above) // 2
            elif filter_type == 4:
                p = left + above - upper_left
                distances = (abs(p - left), abs(p - above), abs(p - upper_left))
                predictor = (left, above, upper_left)[distances.index(min(distances))]
            else:
                predictor = 0
            row[i] = (row[i] + predictor) & 255
        pixels[y * stride:(y + 1) * stride] = row
        previous = row
    return width, height, channels, pixels


def write_png(path, width, height, channels, pixels):
    def chunk(kind, payload):
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload)))

    stride = width * channels
    raw = b"".join(b"\0" + pixels[y * stride:(y + 1) * stride] for y in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2 if channels == 3 else 6, 0, 0, 0)
    path.write_bytes(PNG_SIGNATURE + chunk(b"IHDR", header)
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def grid_lines(size, anchor, step_x, step_y):
    def project(x, y):
        return (anchor[0] + x * step_x[0] + y * step_y[0],
                anchor[1] + x * step_x[1] + y * step_y[1])

    # Draw each shared boundary once, including the four outer edges.
    for index in range(size + 1):
        x = index - 0.5
        yield project(x, -0.5), project(x, size - 0.5)
        y = index - 0.5
        yield project(-0.5, y), project(size - 0.5, y)


def draw_line(pixels, width, height, channels, start, end):
    # Clip before rasterizing so bad metadata cannot make the loop enormous.
    x0, y0 = start
    dx, dy = end[0] - x0, end[1] - y0
    low, high = 0.0, 1.0
    for p, q in ((-dx, x0), (dx, width - 1 - x0),
                 (-dy, y0), (dy, height - 1 - y0)):
        if p == 0:
            if q < 0:
                return
        else:
            ratio = q / p
            if p < 0:
                low = max(low, ratio)
            else:
                high = min(high, ratio)
    if low > high:
        return
    x1 = min(max(round(x0 + low * dx), 0), width - 1)
    y1 = min(max(round(y0 + low * dy), 0), height - 1)
    x2 = min(max(round(x0 + high * dx), 0), width - 1)
    y2 = min(max(round(y0 + high * dy), 0), height - 1)
    count = max(abs(x2 - x1), abs(y2 - y1))
    for i in range(count + 1):
        x = round(x1 + (x2 - x1) * i / max(count, 1))
        y = round(y1 + (y2 - y1) * i / max(count, 1))
        at = (y * width + x) * channels
        pixels[at:at + 3] = b"\xff\0\0"
        if channels == 4:
            pixels[at + 3] = 255


def overlay(grid_path, image_path, output_path):
    size, width, height, anchor, step_x, step_y = load_grid(grid_path)
    image_width, image_height, channels, pixels = read_png(image_path)
    if (width, height) != (image_width, image_height):
        raise ValueError("grid dimensions do not match the image")
    if output_path.resolve() == image_path.resolve():
        raise ValueError("output must not overwrite the input image")
    for start, end in grid_lines(size, anchor, step_x, step_y):
        draw_line(pixels, width, height, channels, start, end)
    write_png(output_path, width, height, channels, pixels)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("grid", type=Path, help="<map-name>.grid.json")
    parser.add_argument("image", type=Path, help="<map-name>.png")
    parser.add_argument("output", nargs="?", type=Path, help="output PNG (default: <map-name>.grid.png)")
    args = parser.parse_args()
    output = args.output or args.image.with_name(args.image.stem + ".grid.png")
    try:
        overlay(args.grid, args.image, output)
    except (ValueError, OSError, json.JSONDecodeError, zlib.error) as error:
        parser.exit(1, f"error: {error}\n")
    print(output)


if __name__ == "__main__":
    main()

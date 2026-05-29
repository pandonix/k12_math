"""Render MathType/WMF equation images to tightly-cropped transparent PNGs.

Word stores legacy equation objects (MathType OLE) with a placeable WMF as the
visual fallback that Word actually displays. LibreOffice renders those WMFs
faithfully; we then autocrop the A4 page whitespace and knock out the white
background so the equation sits inline like the original document.

Requires LibreOffice (headless `soffice`) and Pillow.
"""
from __future__ import annotations

import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

# MathType fonts LibreOffice lacks -> a substitute it renders with the same
# single-byte glyph layout. Euclid Extra/MT Extra both map 'V' (0x56) to △;
# Euclid Symbol is a layout clone of Adobe Symbol. Keeps the original glyphs
# instead of falling back to a wrong character (e.g. △ rendering as ∨).
_FONT_REMAP = {
    b"Euclid Extra": b"MT Extra",
    b"Euclid Extra Tiger": b"MT Extra",
    b"MT Extra Tiger": b"MT Extra",
    b"Euclid Symbol": b"Symbol",
    b"Euclid Symbol Tiger": b"Symbol",
    b"Symbol Tiger Expert": b"Symbol",
    b"Symbol Tiger": b"Symbol",
}

# A4 at ~300 DPI — gives crisp equations that downscale well on retina.
_RENDER_DPI = 300
_DISPLAY_DPI = 96  # map the equation's true print size to on-screen CSS pixels
_PIXEL_WIDTH = 2480
_PIXEL_HEIGHT = 3508
_PNG_FILTER = (
    'png:draw_png_Export:{'
    f'"PixelWidth":{{"type":"long","value":{_PIXEL_WIDTH}}},'
    f'"PixelHeight":{{"type":"long","value":{_PIXEL_HEIGHT}}}'
    '}'
)
_WHITE_THRESHOLD = 245
_PAD = 8
_CHUNK = 150  # files per soffice invocation


def remap_missing_fonts(data: bytes) -> bytes:
    """Rewrite CreateFontIndirect facenames for MathType fonts LibreOffice
    lacks, so glyphs (e.g. the △ triangle) render correctly instead of falling
    back to a wrong character."""
    if len(data) < 40 or data[:4] != b"\xd7\xcd\xc6\x9a":
        return data
    buf = bytearray(data)
    cursor = 40  # placeable header (22) + standard WMF header (18)
    while cursor + 6 <= len(buf):
        size_words = struct.unpack_from("<I", buf, cursor)[0]
        function = struct.unpack_from("<H", buf, cursor + 4)[0]
        if size_words < 3 or function == 0:
            break
        if function == 0x02FB:  # META_CREATEFONTINDIRECT
            name_start = cursor + 6 + 18  # after LOGFONT fixed fields
            name_end = cursor + size_words * 2
            field = bytes(buf[name_start:name_end])
            current = field.split(b"\x00", 1)[0]
            replacement = _FONT_REMAP.get(current)
            if replacement:
                padded = replacement[: name_end - name_start].ljust(name_end - name_start, b"\x00")
                buf[name_start:name_end] = padded
        cursor += size_words * 2
    return bytes(buf)


def find_soffice() -> str | None:
    for candidate in (
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        shutil.which("soffice"),
        shutil.which("libreoffice"),
    ):
        if candidate and Path(candidate).exists():
            return candidate
    return None


def _autocrop(png_path: Path, out_path: Path) -> tuple[int, int] | None:
    """Crop whitespace + knock out white background. Returns CSS display size."""
    im = Image.open(png_path).convert("RGBA")
    rgb = im.convert("RGB")
    bg = Image.new("RGB", rgb.size, (255, 255, 255))
    bbox = ImageChops.difference(rgb, bg).getbbox()
    if not bbox:
        return None
    l, t, r, b = bbox
    crop = im.crop(
        (
            max(0, l - _PAD),
            max(0, t - _PAD),
            min(im.width, r + _PAD),
            min(im.height, b + _PAD),
        )
    )
    # Knock out the white page background -> transparent, preserving glyph
    # anti-aliasing (darker pixel = more opaque). Vectorized via point().
    luminance = crop.convert("L")
    alpha = luminance.point(lambda v: 0 if v > _WHITE_THRESHOLD else 255 - v)
    crop.putalpha(alpha)
    crop.save(out_path)
    scale = _DISPLAY_DPI / _RENDER_DPI
    return max(1, round(crop.width * scale)), max(1, round(crop.height * scale))


def render_wmf_batch(
    wmf_bytes_by_rel_id: dict[str, bytes],
    output_dir: Path,
    soffice: str | None = None,
) -> dict[str, tuple[str, int, int]]:
    """Render each WMF to output_dir/{rel_id}.png (cropped, transparent).

    Returns {rel_id: (absolute_png_path, css_width, css_height)} for every
    successfully rendered file. The CSS size is the equation's true print size,
    so it sits inline at the same scale as the surrounding text.
    """
    if not wmf_bytes_by_rel_id:
        return {}
    soffice = soffice or find_soffice()
    if not soffice:
        raise RuntimeError("LibreOffice (soffice) not found; cannot render WMF equations.")

    output_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, tuple[str, int, int]] = {}
    scale = _DISPLAY_DPI / _RENDER_DPI

    # Fast path: reuse already-rendered PNGs (cheap re-imports).
    pending: dict[str, bytes] = {}
    for rel_id, data in wmf_bytes_by_rel_id.items():
        out_path = output_dir / f"{rel_id}.png"
        if out_path.exists():
            with Image.open(out_path) as existing:
                w, h = existing.size
            result[rel_id] = (str(out_path), max(1, round(w * scale)), max(1, round(h * scale)))
        else:
            pending[rel_id] = data
    if not pending:
        return result
    wmf_bytes_by_rel_id = pending

    with tempfile.TemporaryDirectory(prefix="wmf_") as tmp:
        tmp_dir = Path(tmp)
        user_install = (tmp_dir / "lo_profile").as_uri()
        rel_by_stem: dict[str, str] = {}
        wmf_files: list[Path] = []
        for rel_id, data in wmf_bytes_by_rel_id.items():
            wmf_path = tmp_dir / f"{rel_id}.wmf"
            wmf_path.write_bytes(remap_missing_fonts(data))
            rel_by_stem[rel_id] = rel_id
            wmf_files.append(wmf_path)

        png_dir = tmp_dir / "png"
        png_dir.mkdir()
        for i in range(0, len(wmf_files), _CHUNK):
            chunk = wmf_files[i : i + _CHUNK]
            subprocess.run(
                [
                    soffice,
                    f"-env:UserInstallation={user_install}",
                    "--headless",
                    "--convert-to",
                    _PNG_FILTER,
                    "--outdir",
                    str(png_dir),
                    *[str(p) for p in chunk],
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        for rel_id in wmf_bytes_by_rel_id:
            png_path = png_dir / f"{rel_id}.png"
            if not png_path.exists():
                continue
            out_path = output_dir / f"{rel_id}.png"
            size = _autocrop(png_path, out_path)
            if size:
                result[rel_id] = (str(out_path), size[0], size[1])

    return result

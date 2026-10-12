#!/usr/bin/env python3
"""
[INPUT]: 依赖 Pillow 的图像解码、色彩转换与 NumPy 的透明度计算。
[OUTPUT]: 提供 render_icon、verify_png 与 build_preview。
[POS]: scripts 的纯图像边界。不检索应用，不写用户文件。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""
from __future__ import annotations

import io
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms, ImageDraw, ImageFilter, ImageFont, ImageOps

CANVAS = 1024
BODY = 824
MARGIN = 100
EXPONENT = 4.3
SHADOW_OFFSET = 10
SHADOW_BLUR = 14
SHADOW_OPACITY = 72
MARK_SIZE = 560
SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
PROFILE = SRGB.tobytes()


def _mask() -> Image.Image:
    # ==== 双倍采样：固定超椭圆轮廓与抗锯齿边缘 ====
    scale = 2
    length = CANVAS * scale
    center, half = (length - 1) / 2, BODY * scale / 2
    y, x = np.ogrid[:length, :length]
    distance = (np.abs((x - center) / half) ** EXPONENT +
                np.abs((y - center) / half) ** EXPONENT) ** (1 / EXPONENT)
    alpha = np.clip((1 - distance) * half + 0.5, 0, 1) * 255
    return Image.fromarray(alpha.astype(np.uint8)).resize(
        (CANVAS, CANVAS), Image.Resampling.LANCZOS,
    )


def _geometry() -> tuple[Image.Image, Image.Image]:
    mask = _mask()
    shifted = Image.new("L", (CANVAS, CANVAS), 0)
    shifted.paste(mask.point(lambda value: round(value * SHADOW_OPACITY / 255)),
                  (0, SHADOW_OFFSET))
    shadow_alpha = shifted.filter(ImageFilter.GaussianBlur(SHADOW_BLUR))
    shadow = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    shadow.putalpha(shadow_alpha)
    return mask, shadow


def _open_image(raw: bytes) -> Image.Image:
    with Image.open(io.BytesIO(raw)) as source:
        if source.format == "ICNS":
            sizes = source.info.get("sizes", [])
            if sizes:
                width, height, scale = max(sizes, key=lambda size: size[0] * size[2])
                source.size = (width, height)
                source.load(scale=scale)
        if source.width * source.height > 16_777_216:
            raise ValueError("原图超过 4096×4096 像素预算")
        source.load()
        image = ImageOps.exif_transpose(source).convert("RGBA")
        profile = source.info.get("icc_profile")
        if profile:
            try:
                rgb = ImageCms.profileToProfile(
                    image.convert("RGB"), ImageCms.ImageCmsProfile(io.BytesIO(profile)), SRGB,
                    outputMode="RGB",
                )
                rgb.putalpha(image.getchannel("A"))
                image = rgb
            except (ImageCms.PyCMSError, OSError, ValueError) as exc:
                raise ValueError("原图色彩配置无效") from exc
        return image.copy()


def render_icon(raw: bytes) -> tuple[bytes, dict]:
    image = _open_image(raw)
    original_size = list(image.size)
    alpha = np.asarray(image.getchannel("A"))
    visible = np.argwhere(alpha > 10)
    if not visible.size:
        raise ValueError("原图为空或完全透明")
    opaque = np.argwhere(alpha > 240)
    card = False
    if opaque.size:
        y0, x0 = opaque.min(axis=0)
        y1, x1 = opaque.max(axis=0)
        crop_alpha = alpha[y0:y1 + 1, x0:x1 + 1]
        ratio = (x1 - x0 + 1) / (y1 - y0 + 1)
        card = 0.90 <= ratio <= 1.10 and float((crop_alpha > 240).mean()) >= 0.80
    if card:
        # 去除旧图标的外部阴影，仅保留卡片内容。
        image = image.crop((int(x0), int(y0), int(x1) + 1, int(y1) + 1))
        fitted = ImageOps.contain(image, (BODY, BODY), Image.Resampling.LANCZOS)
    else:
        y0, x0 = visible.min(axis=0)
        y1, x1 = visible.max(axis=0)
        image = image.crop((int(x0), int(y0), int(x1) + 1, int(y1) + 1))
        fitted = ImageOps.contain(image, (MARK_SIZE, MARK_SIZE), Image.Resampling.LANCZOS)

    mask, shadow = _geometry()
    body = Image.new("RGBA", (CANVAS, CANVAS), (255, 255, 255, 255))
    body.alpha_composite(fitted, ((CANVAS - fitted.width) // 2, (CANVAS - fitted.height) // 2))
    body.putalpha(mask)
    result = Image.alpha_composite(shadow, body)
    output = io.BytesIO()
    result.save(output, format="PNG", icc_profile=PROFILE, dpi=(144, 144))
    raw_output = output.getvalue()
    spec = verify_png(raw_output)
    if not spec["compliant"]:
        raise ValueError(f"成品未通过规格校验: {spec['reason']}")
    return raw_output, {
        "originalSize": original_size,
        "upscaled": min(image.size) < (BODY if card else MARK_SIZE),
        "contentMode": "app_card" if card else "mark_on_white_card",
        "spec": spec,
    }


def verify_png(value: bytes | Path) -> dict:
    try:
        raw = value if isinstance(value, bytes) else value.read_bytes()
        stream = io.BytesIO(raw)
        with Image.open(stream) as image:
            image.load()
            result = {"compliant": False, "format": image.format,
                      "mode": image.mode, "size": list(image.size)}
            bit_depth = raw[24] if image.format == "PNG" and len(raw) > 24 else None
            if image.format != "PNG" or image.mode != "RGBA" or image.size != (CANVAS, CANVAS) or bit_depth != 8:
                return {**result, "reason": "要求 1024×1024、8-bit RGBA PNG"}
            alpha = np.asarray(image.getchannel("A"), dtype=np.int16)
            mask, shadow = _geometry()
            expected = Image.new("RGBA", image.size, (255, 255, 255, 255))
            expected.putalpha(mask)
            expected_alpha = np.asarray(Image.alpha_composite(shadow, expected).getchannel("A"), dtype=np.int16)
            difference = np.abs(alpha - expected_alpha)
            profile = image.info.get("icc_profile")
            srgb = bool(profile and "srgb" in ImageCms.getProfileDescription(
                ImageCms.ImageCmsProfile(io.BytesIO(profile)),
            ).casefold())
            geometry_ok = int(difference.max()) <= 2
            corners_ok = all(alpha[y, x] == 0 for y, x in (
                (0, 0), (0, CANVAS - 1), (CANVAS - 1, 0), (CANVAS - 1, CANVAS - 1),
            ))
            compliant = geometry_ok and corners_ok and srgb
            return {**result, "compliant": bool(compliant), "bitDepth": bit_depth,
                    "colorSpace": "sRGB" if srgb else "unknown",
                    "bodySize": [BODY, BODY], "margin": MARGIN,
                    "maxAlphaDifference": int(difference.max()),
                    "reason": "符合统一圆角阴影规格" if compliant else "圆角、阴影、透明度或色彩配置不符合统一规格"}
    except Exception as exc:
        return {"compliant": False, "reason": f"无法验证图片: {type(exc).__name__}: {exc}"}


def _font() -> ImageFont.ImageFont:
    fonts = [
        Path("/System/Library/Fonts/PingFang.ttc"),
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyh.ttc",
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ]
    for path in fonts:
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), 18)
            except OSError:
                continue
    return ImageFont.load_default()


def build_preview(paths: list[Path]) -> bytes:
    if not paths:
        raise ValueError("没有已下载图标可供预览")
    cols = min(4, len(paths))
    rows = (len(paths) + cols - 1) // cols
    preview = Image.new("RGB", (cols * 280, rows * 300), (245, 246, 250))
    draw, font = ImageDraw.Draw(preview), _font()
    for index, path in enumerate(paths):
        x, y = (index % cols) * 280, (index // cols) * 300
        with Image.open(path) as image:
            icon = image.convert("RGBA").resize((240, 240), Image.Resampling.LANCZOS)
            preview.paste(icon, (x + 20, y + 8), icon)
        label = path.stem
        while len(label) > 1 and draw.textlength(label, font=font) > 250:
            label = label[:-1]
        draw.text((x + 15, y + 260), label, fill=(30, 30, 35), font=font)
    output = io.BytesIO()
    preview.save(output, format="PNG", icc_profile=PROFILE)
    return output.getvalue()

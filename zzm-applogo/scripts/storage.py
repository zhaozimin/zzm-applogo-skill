#!/usr/bin/env python3
"""
[INPUT]: 依赖 pathlib 与操作系统独占创建、原子替换能力。
[OUTPUT]: 提供 safe_stem 与 save_unique_bytes。
[POS]: scripts 的落盘边界。不覆盖调用者已有文件。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{n}" for prefix in ("COM", "LPT") for n in range(1, 10)
}


def safe_stem(name: str) -> str:
    stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip(" .")
    stem = stem[:100].rstrip(" .") or "AppLogo"
    if stem.split(".", 1)[0].upper() in RESERVED:
        stem = "_" + stem
    return stem


def save_unique_bytes(directory: Path, name: str, content: bytes) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    filename = Path(name)
    stem, suffix = safe_stem(filename.stem), filename.suffix
    existing = {p.name.casefold() for p in directory.iterdir()}
    index = 1
    while True:
        extra = f"-{index}" if index > 1 else ""
        target = directory / f"{stem}{extra}{suffix}"
        if target.name.casefold() in existing:
            index += 1
            continue
        try:
            with target.open("xb"):
                pass
            break
        except FileExistsError:
            index += 1
    temp_path = None
    try:
        fd, temp_name = tempfile.mkstemp(prefix=".applogo-", dir=directory)
        temp_path = Path(temp_name)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, target)
        return target.resolve()
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)

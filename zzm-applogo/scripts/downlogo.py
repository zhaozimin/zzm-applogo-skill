#!/usr/bin/env python3
"""
[INPUT]: 依赖 sources 候选检索、imaging 图像渲染与 storage 原子落盘。
[OUTPUT]: 提供 search、download、normalize、verify 命令与 JSON 报告。
[POS]: zzm-applogo 的唯一执行入口。协调来源与交付状态。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from imaging import build_preview, render_icon, verify_png
from network import HttpClient, SourceError
from sources import (Candidate, SearchResult, choose_candidate, lookup_appstore,
                     search_appstore, search_macosicons)
from storage import safe_stem, save_unique_bytes


def emit(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def find_candidates(client: HttpClient, query: str, args: argparse.Namespace,
                    search_both: bool = False) -> SearchResult:
    result = SearchResult()
    countries = args.country.split(",")
    if getattr(args, "app_id", ""):
        return lookup_appstore(client, query, args.app_id, countries, args.seller)
    if getattr(args, "id", ""):
        return search_macosicons(client, query, args.style, args.id)
    use_apple = args.source in {"auto", "appstore"} and args.style == "standard"
    if use_apple:
        apple = search_appstore(client, query, countries, args.platform, args.seller)
        result.candidates.extend(apple.candidates)
        result.errors.extend(apple.errors)
        if not search_both and any(c.automatic for c in apple.candidates):
            return result
    if args.source in {"auto", "macosicons"}:
        mac = search_macosicons(client, query, args.style)
        result.errors.extend(mac.errors)
        # 在 App Store 只有低置信候选时，优先准确的社区候选。
        result.candidates = (result.candidates + mac.candidates if search_both else
                             mac.candidates + result.candidates)
    return result


def download_candidate(client: HttpClient, candidate: Candidate) -> tuple[bytes, dict, str]:
    errors = []
    low_resolution = None
    for url in candidate.urls:
        try:
            rendered, details = render_icon(client.get(url))
            if not details["upscaled"]:
                return rendered, details, url
            if low_resolution is None:
                low_resolution = (rendered, details, url)
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
    if low_resolution:
        return low_resolution
    raise SourceError("所有原图地址均下载或解码失败: " + "; ".join(errors))


def save_candidate(client: HttpClient, query: str, candidate: Candidate,
                   output_dir: Path, stem: str, warnings: list[str]) -> dict:
    rendered, details, url = download_candidate(client, candidate)
    path = save_unique_bytes(output_dir, safe_stem(stem) + ".png", rendered)
    if details["upscaled"]:
        warnings = warnings + ["原图分辨率不足，成品经过放大；1024×1024 表示输出尺寸"]
    return {"query": query, "status": "ok", "outputPath": str(path),
            "candidate": candidate.report(), "sourceUrl": url,
            **details, "warnings": warnings}


def download_one(client: HttpClient, query: str, args: argparse.Namespace,
                 output_dir: Path, stem: str) -> list[dict]:
    found = find_candidates(client, query, args)
    if args.candidates > 1:
        results = []
        for index, candidate in enumerate(found.candidates[:args.candidates], 1):
            try:
                results.append(save_candidate(client, query, candidate, output_dir,
                                              f"{stem}_候选{index:02d}_{candidate.id}", found.errors))
            except Exception as exc:
                results.append({"query": query, "status": "error", "candidate": candidate.report(),
                                "reason": str(exc), "warnings": found.errors})
        if results:
            return results
    chosen = choose_candidate(found.candidates)
    if chosen is None:
        if found.candidates:
            return [{"query": query, "status": "needs_selection",
                     "reason": "名称匹配不足或存在同名应用；请核对开发者并指定 --app-id 或 --id",
                     "candidates": [c.report() for c in found.candidates[:8]], "warnings": found.errors}]
        return [{"query": query, "status": "source_error" if found.errors else "not_found",
                 "reason": "图源请求失败" if found.errors else "两个指定图源中未找到准确图标",
                 "warnings": found.errors}]
    try:
        return [save_candidate(client, query, chosen, output_dir, stem, found.errors)]
    except Exception as exc:
        # 默认模式下，官方原图传输失败后仍允许第二图源兜底。
        if args.source == "auto" and chosen.source == "appstore" and not args.app_id:
            mac = search_macosicons(client, query, args.style)
            fallback = choose_candidate(mac.candidates)
            if fallback:
                try:
                    return [save_candidate(client, query, fallback, output_dir, stem,
                                           found.errors + mac.errors + [f"App Store 原图失败: {exc}"])]
                except Exception as fallback_exc:
                    return [{"query": query, "status": "error", "reason": str(fallback_exc),
                             "warnings": found.errors + mac.errors + [str(exc)]}]
        return [{"query": query, "status": "error", "reason": str(exc), "warnings": found.errors}]


def cmd_download(args: argparse.Namespace) -> int:
    client = HttpClient()
    output_dir = Path(args.output_dir).expanduser().resolve()
    results = []
    for index, query in enumerate(args.apps, args.start_index):
        print(f"正在检索与下载: {query}", file=sys.stderr)
        stem = args.name or query
        if args.numbered:
            stem = f"{index:02d}_{stem}"
        try:
            results.extend(download_one(client, query, args, output_dir, stem))
        except Exception as exc:
            results.append({"query": query, "status": "error", "reason": str(exc)})
    preview = None
    preview_error = None
    if args.preview:
        paths = [Path(r["outputPath"]) for r in results if r["status"] == "ok"]
        if paths:
            try:
                preview = str(save_unique_bytes(output_dir, "_预览汇总图.png", build_preview(paths)))
            except Exception as exc:
                preview_error = str(exc)
    report = {"skill": "zzm-applogo", "results": results, "previewPath": preview}
    if preview_error:
        report["previewError"] = preview_error
    report_path = save_unique_bytes(output_dir, "download-report.json",
                                   json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8"))
    emit({**report, "reportPath": str(report_path)})
    return 0 if all(r["status"] == "ok" for r in results) and not preview_error else 1


def cmd_search(args: argparse.Namespace) -> int:
    client = HttpClient()
    reports = []
    for query in args.apps:
        found = find_candidates(client, query, args, search_both=True)
        reports.append({"query": query, "candidates": [c.report() for c in found.candidates[:args.limit]],
                        "errors": found.errors})
    emit(reports)
    return 1 if any(r["errors"] and not r["candidates"] for r in reports) else 0


def cmd_normalize(args: argparse.Namespace) -> int:
    raw = HttpClient().get(args.input) if args.input.startswith("https://") else Path(args.input).expanduser().read_bytes()
    rendered, details = render_icon(raw)
    requested = Path(args.output).expanduser().resolve()
    path = save_unique_bytes(requested.parent, requested.name, rendered)
    emit({"status": "ok", "outputPath": str(path), **details})
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    reports = {str(Path(path).expanduser().resolve()): verify_png(Path(path).expanduser()) for path in args.files}
    emit(reports)
    return 0 if all(r["compliant"] for r in reports.values()) else 1


def _source_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("apps", nargs="+", help="应用名称；含空格的名称加引号")
    parser.add_argument("--source", choices=["auto", "appstore", "macosicons"], default="auto")
    parser.add_argument("--country", default="cn,us", help="App Store 地区顺序，逗号分隔")
    parser.add_argument("--platform", choices=["auto", "ios", "mac"], default="auto")
    parser.add_argument("--seller", default="", help="App Store 开发者名称筛选")
    parser.add_argument("--style", choices=["standard", "dark", "light", "liquid-glass"], default="standard")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="双来源应用图标下载：统一透明圆角阴影 PNG")
    sub = parser.add_subparsers(dest="command", required=True)
    search = sub.add_parser("search", help="查找应用与图标候选")
    _source_args(search)
    search.add_argument("--limit", type=int, default=8)
    search.set_defaults(func=cmd_search)
    download = sub.add_parser("download", help="下载并统一图标外观")
    _source_args(download)
    download.add_argument("-o", "--output-dir", default="app-logos")
    download.add_argument("--app-id", default="", help="指定单个 App Store 应用 ID")
    download.add_argument("--id", default="", help="指定单个 macosicons 图标 ID")
    download.add_argument("--name", default="", help="单个应用的输出名称")
    download.add_argument("--numbered", action="store_true")
    download.add_argument("--start-index", type=int, default=1)
    download.add_argument("--preview", action="store_true")
    download.add_argument("--candidates", type=int, default=1, help="下载前 N 个候选供对比")
    download.set_defaults(func=cmd_download)
    normalize = sub.add_parser("normalize", help="将本地图片或 HTTPS 图片统一外观")
    normalize.add_argument("-i", "--input", required=True)
    normalize.add_argument("-o", "--output", required=True)
    normalize.set_defaults(func=cmd_normalize)
    verify = sub.add_parser("verify", help="验证统一尺寸、圆角、阴影与 sRGB")
    verify.add_argument("files", nargs="+")
    verify.set_defaults(func=cmd_verify)
    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if hasattr(args, "source"):
        if not re.fullmatch(r"[a-zA-Z]{2}(?:,[a-zA-Z]{2})*", args.country):
            parser.error("--country 必须为两位地区码，例如 cn,us")
        args.country = args.country.lower()
        if args.source == "appstore" and args.style != "standard":
            parser.error("App Store 只提供常规图源；指定款式请使用 macosicons")
        if not all(query.strip() for query in args.apps):
            parser.error("应用名称不能为空")
    if args.command == "download":
        if (args.app_id or args.id or args.name) and len(args.apps) != 1:
            parser.error("指定 ID 或名称时只能下载一个应用")
        if args.app_id and (not args.app_id.isdigit() or args.source == "macosicons" or args.id):
            parser.error("--app-id 需要数字 ID，不能与 macosicons 来源或 --id 混用")
        if args.id and (not re.fullmatch(r"[A-Za-z0-9_-]+", args.id) or args.source == "appstore"):
            parser.error("--id 需要有效 macosicons 图标 ID，不能与 appstore 来源混用")
        if args.app_id and args.style != "standard":
            parser.error("指定 App Store ID 时只能使用 standard 款式")
        if not 1 <= args.candidates <= 10 or args.start_index < 1:
            parser.error("候选数量应为 1..10，编号起点应大于 0")
        if args.candidates > 1 and (args.id or args.app_id):
            parser.error("指定单个 ID 时不接受多候选下载")
    if args.command == "search" and not 1 <= args.limit <= 20:
        parser.error("候选数量应为 1..20")
    if args.command == "normalize" and Path(args.output).suffix.lower() != ".png":
        parser.error("输出文件必须使用 .png 扩展名")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    validate_args(parser, args)
    try:
        return args.func(args)
    except Exception as exc:
        emit({"status": "error", "reason": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

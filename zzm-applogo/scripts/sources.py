#!/usr/bin/env python3
"""
[INPUT]: 依赖 network 的 HTTPS 客户端与两个图源的公开搜索响应。
[OUTPUT]: 提供 Candidate、SearchResult、双来源搜索与显式 ID 查询。
[POS]: scripts 的图源适配层。保留身份信息，不渲染或写文件。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""
from __future__ import annotations

import math
import re
import unicodedata
import urllib.parse
from dataclasses import asdict, dataclass, field

from network import HttpClient, SourceError

APPLE_SEARCH = "https://itunes.apple.com/search"
APPLE_LOOKUP = "https://itunes.apple.com/lookup"
MAC_SEARCH = "https://macosicons.com/api/search"

# ==== 产品别名：地区产品分开，不把相似品牌视为同一应用 ====
ALIASES = {
    "微信": ["微信", "WeChat"], "wechat": ["WeChat", "微信"],
    "飞书": ["飞书", "Feishu"], "feishu": ["Feishu", "飞书"],
    "剪映": ["剪映", "Jianying"], "jianying": ["Jianying", "剪映"],
    "lark": ["Lark"], "capcut": ["CapCut"],
    "小红书": ["小红书", "Xiaohongshu", "rednote"],
    "钉钉": ["钉钉", "DingTalk"], "哔哩哔哩": ["哔哩哔哩", "Bilibili"],
    "b站": ["哔哩哔哩", "Bilibili"], "豆包": ["豆包", "Doubao"],
    "支付宝": ["支付宝", "Alipay"], "微信读书": ["微信读书", "WeRead"],
    "滴答清单": ["滴答清单", "TickTick"],
    "印象笔记": ["印象笔记"], "evernote": ["Evernote"],
    "网易云音乐": ["网易云音乐", "NetEase Music"],
    "vscode": ["Visual Studio Code", "VS Code"],
    "vs code": ["Visual Studio Code", "VS Code"],
}
PUBLISHERS = {
    "chatgpt": "openai", "claude": "anthropic", "wechat": "tencent", "微信": "tencent",
}
DESKTOP_ONLY = {"cursor", "vscode", "vs code", "visual studio code", "trae"}
VARIANT = re.compile(
    r"\b(dark|black|light|white|neon|retro|transparent|alt|alternative|old|classic|"
    r"beta|nightly|rainbow|pink|purple|green|orange|red|yellow|liquid|glass)\b", re.I,
)


def queries_for(query: str) -> list[str]:
    return ALIASES.get(query.strip().casefold(), [query.strip()])


def normalized(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return "".join(c for c in text if c.isalnum())


def name_match(name: str, queries: list[str]) -> int:
    full = normalized(name)
    core = normalized(re.split(r"\s+[-–—|]\s+|[:：·]|\s+\(", name, maxsplit=1)[0])
    scores = []
    for query in queries:
        q = normalized(query)
        if not q:
            continue
        scores.append(100 if full == q else 90 if core == q else
                      40 if len(q) >= 3 and q in full else 0)
    return max(scores, default=0)


@dataclass
class Candidate:
    source: str
    id: str
    name: str
    urls: list[str]
    match: int
    seller: str = ""
    platform: str = ""
    country: str = ""
    page_url: str = ""
    bundle_id: str = ""
    rank: float = 0
    automatic: bool = False
    metadata: dict = field(default_factory=dict)

    def report(self) -> dict:
        result = asdict(self)
        result.pop("urls")
        result.pop("rank")
        return result


@dataclass
class SearchResult:
    candidates: list[Candidate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _apple_candidate(record: dict, query: str, country: str, platform: str,
                     seller_filter: str = "", explicit: bool = False) -> Candidate | None:
    name = str(record.get("trackName") or "")
    art = str(record.get("artworkUrl512") or record.get("artworkUrl100") or "")
    track_id = str(record.get("trackId") or "")
    if not name or not art or not track_id:
        return None
    match = name_match(name, queries_for(query))
    seller = str(record.get("sellerName") or record.get("artistName") or "")
    publisher = seller_filter or PUBLISHERS.get(query.casefold(), "")
    publisher_ok = not publisher or publisher.casefold() in seller.casefold()
    if (not explicit and match == 0) or not publisher_ok:
        return None
    # CDN 高分辨率地址需在下载时验证，失败后回到接口原地址。
    large = re.sub(r"\d+x\d+bb\.(?:jpg|png|jpeg)(?:$|(?=\?))", "1024x1024bb.png", art)
    return Candidate(
        source="appstore", id=track_id, name=name,
        urls=list(dict.fromkeys([large, art])), match=match,
        seller=seller, country=country, platform=platform,
        page_url=str(record.get("trackViewUrl") or ""),
        bundle_id=str(record.get("bundleId") or ""),
        rank=float(match), automatic=explicit or match >= 90,
        metadata={"identity": "explicit_app_id" if explicit else
                  "name_and_publisher_match" if publisher else "name_match"},
    )


def search_appstore(client: HttpClient, query: str, countries: list[str],
                    platform: str = "auto", seller: str = "") -> SearchResult:
    result = SearchResult()
    seen = set()
    platforms = ["ios", "mac"] if platform == "auto" else [platform]
    if platform == "auto" and query.casefold() in DESKTOP_ONLY:
        platforms = ["mac"]
    for target in platforms:
        for country in countries:
            for term in queries_for(query):
                params = urllib.parse.urlencode({
                    "term": term, "country": country, "limit": 15,
                    "entity": "software" if target == "ios" else "macSoftware",
                })
                try:
                    records = client.json(f"{APPLE_SEARCH}?{params}").get("results")
                    if not isinstance(records, list):
                        raise SourceError("App Store 搜索响应缺少结果列表")
                except SourceError as exc:
                    result.errors.append(f"appstore/{country}/{target}: {exc}")
                    # 同一主机请求失败后停止扩搜，避免按别名重复等待。
                    result.candidates.sort(key=lambda c: c.rank, reverse=True)
                    return result
                for record in records:
                    candidate = _apple_candidate(record, query, country, target, seller)
                    if candidate and candidate.id not in seen:
                        result.candidates.append(candidate)
                        seen.add(candidate.id)
                # 同一响应内保留同名候选。找到准确匹配后停止跨区扩搜。
                if any(c.automatic for c in result.candidates):
                    result.candidates.sort(key=lambda c: c.rank, reverse=True)
                    return result
    result.candidates.sort(key=lambda c: c.rank, reverse=True)
    return result


def lookup_appstore(client: HttpClient, query: str, app_id: str,
                    countries: list[str], seller: str = "") -> SearchResult:
    result = SearchResult()
    for country in countries:
        params = urllib.parse.urlencode({"id": app_id, "country": country})
        try:
            records = client.json(f"{APPLE_LOOKUP}?{params}").get("results")
            if not isinstance(records, list):
                raise SourceError("App Store ID 响应缺少结果列表")
        except SourceError as exc:
            result.errors.append(f"appstore/{country}: {exc}")
            continue
        for record in records:
            if str(record.get("trackId")) != app_id:
                continue
            platform = "mac" if record.get("kind") == "mac-software" else "ios"
            candidate = _apple_candidate(record, query, country, platform, seller, explicit=True)
            if candidate:
                result.candidates.append(candidate)
                return result
    return result


def _mac_candidate(record: dict, query: str, style: str,
                   explicit: bool = False) -> Candidate | None:
    name = str(record.get("appName") or "")
    queries = queries_for(query)
    match = name_match(name, queries)
    urls = [str(record.get(key) or "") for key in ("iOSUrl", "icnsUrl")]
    urls = [url for url in urls if url.startswith("https://")]
    if not name or not urls or not record.get("objectID") or (match == 0 and not explicit):
        return None
    if not explicit and re.search(r"\bfolder\b|\bdrive icon\b", name, re.I):
        if not re.search(r"\bfolder\b|\bdrive icon\b", query, re.I):
            return None
    # 仅检查查询词之外的款式词，保留含颜色词的真实应用名称。
    extra = name.casefold()
    for term in sorted(queries, key=len, reverse=True):
        extra = extra.replace(term.casefold(), "")
    dark = bool(record.get("isDarkMode")) or bool(re.search(r"\b(dark|black)\b", extra))
    glass = bool(record.get("isLiquidGlass")) or "glass" in extra or "(lg)" in extra
    if style == "standard":
        style_ok = not (dark or glass or VARIANT.search(extra))
    elif style == "dark":
        style_ok = dark
    elif style == "liquid-glass":
        style_ok = glass
    else:
        style_ok = bool(re.search(r"\b(light|white)\b", extra))
    if not style_ok and not explicit:
        return None
    downloads = max(0, int(record.get("downloads") or 0))
    official_flag = bool(record.get("isOfficial"))
    return Candidate(
        source="macosicons", id=str(record["objectID"]), name=name,
        urls=list(dict.fromkeys(urls)), match=match, platform="mac",
        page_url=("https://macosicons.com/icon/" + urllib.parse.quote(
            f"{record['appSlug']}-{record['objectID']}",
        ) if record.get("appSlug") else "https://macosicons.com/"),
        rank=match * 100 + (10 if official_flag else 0) + min(9, math.log10(downloads + 1)),
        automatic=explicit or match >= 90,
        metadata={"community": True, "communityOfficialFlag": official_flag,
                  "downloads": downloads, "style": style},
    )


def search_macosicons(client: HttpClient, query: str, style: str = "standard",
                      icon_id: str = "") -> SearchResult:
    result = SearchResult()
    seen = set()
    terms = [""] if icon_id else queries_for(query)
    for term in terms:
        payload = {"query": term, "searchOptions": {
            "hitsPerPage": 1 if icon_id else 50, "page": 1,
            "filters": [f"objectID = {icon_id}"] if icon_id else [],
        }}
        try:
            records = client.json(MAC_SEARCH, payload).get("hits")
            if not isinstance(records, list):
                raise SourceError("macosicons 搜索响应缺少候选列表")
        except SourceError as exc:
            result.errors.append(f"macosicons: {exc}")
            continue
        for record in records:
            if icon_id and str(record.get("objectID")) != icon_id:
                continue
            candidate = _mac_candidate(record, query, style, explicit=bool(icon_id))
            if candidate and candidate.id not in seen:
                result.candidates.append(candidate)
                seen.add(candidate.id)
        if any(c.automatic for c in result.candidates):
            break
    result.candidates.sort(key=lambda c: c.rank, reverse=True)
    return result


def choose_candidate(candidates: list[Candidate]) -> Candidate | None:
    eligible = [c for c in candidates if c.automatic]
    if not eligible:
        return None
    best = eligible[0]
    if best.source == "appstore":
        # 搜索排名与评分数不能证明同名应用身份。
        peers = [c for c in eligible if c.match == best.match]
        if len({(c.bundle_id or c.id) for c in peers}) > 1:
            return None
    return best

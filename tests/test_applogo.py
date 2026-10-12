"""
[INPUT]: 依赖 Skill 的公开函数、内存图片与标准库 mock。
[OUTPUT]: 提供来源识别、渲染、网络和落盘的离线行为验证。
[POS]: 仓库回归入口。验证真实失败边界，不访问源站。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "zzm-applogo/scripts"))
import downlogo
from imaging import PROFILE, build_preview, render_icon, verify_png
from network import HttpClient, SourceError
from sources import choose_candidate, queries_for, search_appstore, search_macosicons
from storage import safe_stem, save_unique_bytes


def picture(size=1024, color=(30, 110, 220, 255), fmt="PNG"):
    image = Image.new("RGBA", (size, size), color)
    ImageDraw.Draw(image).ellipse((size // 3, size // 3, size * 2 // 3, size * 2 // 3),
                                 fill=(255, 255, 255, 255))
    output = io.BytesIO()
    image.save(output, format=fmt)
    return output.getvalue()


def apple(name="ExampleApp", app_id=1, seller="Example Publisher", bundle="example.app"):
    return {"trackName": name, "trackId": app_id, "sellerName": seller, "bundleId": bundle,
            "artworkUrl512": "https://example.com/512x512bb.png",
            "trackViewUrl": f"https://apps.apple.com/app/id{app_id}"}


def mac(name="ExampleApp", icon_id="one", downloads=10, **kwargs):
    return {"appName": name, "objectID": icon_id, "downloads": downloads,
            "iOSUrl": "https://example.com/icon.png", **kwargs}


class FakeClient:
    def __init__(self, apples=None, macs=None, fail_apple=False, assets=None):
        self.apples = apples or []
        self.macs = macs or []
        self.fail_apple = fail_apple
        self.assets = assets
        self.calls = []

    def json(self, url, payload=None):
        self.calls.append(url)
        if "itunes.apple.com" in url:
            if self.fail_apple:
                raise SourceError("模拟断网")
            return {"results": self.apples}
        return {"hits": self.macs}

    def get(self, url):
        if self.assets is None:
            return picture()
        value = self.assets.get(url)
        if value is None:
            raise SourceError("模拟图片失效")
        return value


def arguments(*extra):
    parser = downlogo.build_parser()
    args = parser.parse_args(["download", "ExampleApp", *extra])
    downlogo.validate_args(parser, args)
    return args


class SourceTests(unittest.TestCase):
    def test_related_title_is_not_automatic(self):
        found = search_appstore(FakeClient(apples=[apple("ExampleApp Wallpapers")]),
                                "ExampleApp", ["us"], "ios")
        self.assertEqual(len(found.candidates), 1)
        self.assertIsNone(choose_candidate(found.candidates))

    def test_known_brand_rejects_wrong_publisher(self):
        found = search_appstore(FakeClient(apples=[apple("ChatGPT", seller="Someone Else")]),
                                "ChatGPT", ["us"], "ios")
        self.assertFalse(found.candidates)

    def test_equal_names_with_different_identity_require_selection(self):
        found = search_appstore(FakeClient(apples=[apple(), apple(app_id=2, bundle="other.app")]),
                                "ExampleApp", ["us"], "ios")
        self.assertIsNone(choose_candidate(found.candidates))

    def test_publisher_filter_resolves_equal_names(self):
        records = [apple(seller="Chosen Inc"), apple(app_id=2, seller="Other Inc", bundle="other")]
        found = search_appstore(FakeClient(apples=records), "ExampleApp", ["us"], "ios", "Chosen")
        self.assertEqual(choose_candidate(found.candidates).id, "1")

    def test_distinct_regional_products_are_not_aliases(self):
        self.assertNotIn("CapCut", queries_for("剪映"))
        self.assertNotIn("Lark", queries_for("飞书"))
        self.assertNotIn("Evernote", queries_for("印象笔记"))

    def test_popular_variant_does_not_beat_standard(self):
        found = search_macosicons(FakeClient(macs=[mac("ExampleApp neon", "alt", 1000000), mac()]),
                                  "ExampleApp")
        self.assertEqual([c.id for c in found.candidates], ["one"])

    def test_folder_is_rejected_but_real_google_drive_is_kept(self):
        found = search_macosicons(FakeClient(macs=[mac("ExampleApp Folder")]), "ExampleApp")
        self.assertFalse(found.candidates)
        found = search_macosicons(FakeClient(macs=[mac("Google Drive")]), "Google Drive")
        self.assertTrue(found.candidates)

    def test_explicit_community_id_preserves_user_choice(self):
        found = search_macosicons(FakeClient(macs=[mac("ExampleApp neon", "picked")]),
                                  "ExampleApp", icon_id="picked")
        self.assertEqual(choose_candidate(found.candidates).id, "picked")

    def test_source_error_is_not_empty_search(self):
        found = search_appstore(FakeClient(fail_apple=True), "ExampleApp", ["us"], "ios")
        self.assertFalse(found.candidates)
        self.assertTrue(found.errors)


class ImageTests(unittest.TestCase):
    def test_rendered_icons_have_same_alpha_and_shadow(self):
        first, details = render_icon(picture())
        second, _ = render_icon(picture(color=(220, 50, 10, 255)))
        self.assertTrue(details["spec"]["compliant"])
        with Image.open(io.BytesIO(first)) as a, Image.open(io.BytesIO(second)) as b:
            self.assertEqual(a.size, (1024, 1024))
            self.assertEqual(a.getpixel((0, 0))[3], 0)
            self.assertGreater(a.getpixel((512, 940))[3], 0)
            self.assertLess(a.getpixel((512, 940))[3], 255)
            np.testing.assert_array_equal(np.asarray(a.getchannel("A")), np.asarray(b.getchannel("A")))

    def test_square_without_shadow_is_rejected_even_with_profile(self):
        image = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
        ImageDraw.Draw(image).rectangle((100, 100, 923, 923), fill=(30, 100, 200, 255))
        output = io.BytesIO()
        image.save(output, format="PNG", icc_profile=PROFILE)
        self.assertFalse(verify_png(output.getvalue())["compliant"])

    def test_rounding_without_shadow_is_rejected(self):
        image = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
        ImageDraw.Draw(image).rounded_rectangle((100, 100, 923, 923), radius=180,
                                               fill=(30, 100, 200, 255))
        output = io.BytesIO()
        image.save(output, format="PNG", icc_profile=PROFILE)
        self.assertFalse(verify_png(output.getvalue())["compliant"])

    def test_low_alpha_returns_failure_without_crashing(self):
        raw = picture(color=(20, 30, 40, 50))
        self.assertFalse(verify_png(raw)["compliant"])

    def test_empty_and_corrupt_inputs_fail(self):
        empty = io.BytesIO()
        Image.new("RGBA", (100, 100)).save(empty, format="PNG")
        with self.assertRaises(ValueError):
            render_icon(empty.getvalue())
        self.assertFalse(verify_png(b"not an image")["compliant"])

    def test_low_resolution_is_reported(self):
        _, report = render_icon(picture(size=256))
        self.assertTrue(report["upscaled"])
        self.assertEqual(report["originalSize"], [256, 256])

    def test_icns_uses_largest_frame_without_system_tools(self):
        raw, report = render_icon(picture(fmt="ICNS"))
        self.assertEqual(report["originalSize"], [1024, 1024])
        self.assertTrue(verify_png(raw)["compliant"])

    def test_non_square_mark_keeps_aspect_ratio(self):
        image = Image.new("RGBA", (400, 200), (220, 10, 10, 255))
        output = io.BytesIO()
        image.save(output, format="PNG")
        raw, report = render_icon(output.getvalue())
        self.assertEqual(report["contentMode"], "mark_on_white_card")
        with Image.open(io.BytesIO(raw)) as rendered:
            rgb = np.asarray(rendered)[:, :, :3]
            red = np.argwhere((rgb[:, :, 0] > 180) & (rgb[:, :, 1] < 40))
            y0, x0 = red.min(axis=0)
            y1, x1 = red.max(axis=0)
            self.assertAlmostEqual((x1 - x0 + 1) / (y1 - y0 + 1), 2, places=1)


class PipelineTests(unittest.TestCase):
    def test_auto_falls_back_on_apple_network_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = downlogo.download_one(FakeClient(fail_apple=True, macs=[mac()]),
                                          "ExampleApp", arguments("--country", "us", "--platform", "ios"),
                                          Path(tmp), "ExampleApp")
            self.assertEqual(rows[0]["status"], "ok")
            self.assertEqual(rows[0]["candidate"]["source"], "macosicons")
            self.assertTrue(rows[0]["warnings"])

    def test_explicit_source_does_not_use_other_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(fail_apple=True, macs=[mac()])
            rows = downlogo.download_one(client, "ExampleApp", arguments("--source", "appstore", "--country", "us"),
                                          Path(tmp), "ExampleApp")
            self.assertEqual(rows[0]["status"], "source_error")
            self.assertFalse(any("macosicons" in url for url in client.calls))

    def test_ambiguous_identity_does_not_write_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(apples=[apple(), apple(app_id=2, bundle="other")])
            rows = downlogo.download_one(client, "ExampleApp", arguments(), Path(tmp), "ExampleApp")
            self.assertEqual(rows[0]["status"], "needs_selection")
            self.assertFalse(list(Path(tmp).iterdir()))

    def test_failed_large_artwork_uses_original_and_reports_upscale(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(apples=[apple()], assets={"https://example.com/512x512bb.png": picture(size=512)})
            rows = downlogo.download_one(client, "ExampleApp", arguments(), Path(tmp), "ExampleApp")
            self.assertEqual(rows[0]["status"], "ok")
            self.assertTrue(rows[0]["upscaled"])
            self.assertTrue(rows[0]["warnings"])

    def test_corrupt_image_cannot_return_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient(macs=[mac()], assets={"https://example.com/icon.png": b"bad image"})
            rows = downlogo.download_one(client, "ExampleApp", arguments("--source", "macosicons"), Path(tmp), "ExampleApp")
            self.assertEqual(rows[0]["status"], "error")
            self.assertFalse(list(Path(tmp).iterdir()))

    def test_batch_partial_failure_is_nonzero_and_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = downlogo.build_parser().parse_args(["download", "Good", "Missing", "-o", tmp])
            fake_rows = [[{"query": "Good", "status": "ok", "outputPath": "unused"}],
                         [{"query": "Missing", "status": "not_found"}]]
            with patch.object(downlogo, "download_one", side_effect=fake_rows), contextlib.redirect_stdout(io.StringIO()):
                code = downlogo.cmd_download(args)
            self.assertEqual(code, 1)
            report = json.loads((Path(tmp) / "download-report.json").read_text(encoding="utf-8"))
            self.assertEqual([r["status"] for r in report["results"]], ["ok", "not_found"])


class StorageTests(unittest.TestCase):
    def test_existing_file_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = save_unique_bytes(Path(tmp), "App.png", b"original")
            second = save_unique_bytes(Path(tmp), "App.png", b"new")
            self.assertEqual(first.read_bytes(), b"original")
            self.assertEqual(second.name, "App-2.png")
            self.assertEqual(second.read_bytes(), b"new")

    def test_windows_reserved_names_and_separators(self):
        self.assertEqual(safe_stem("CON"), "_CON")
        self.assertEqual(safe_stem("NUL.txt"), "_NUL.txt")
        self.assertNotIn("/", safe_stem("a/b"))

    def test_preview_is_separate_from_primary_icon_spec(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw, _ = render_icon(picture())
            path = save_unique_bytes(Path(tmp), "测试.png", raw)
            preview = build_preview([path])
            with Image.open(io.BytesIO(preview)) as image:
                self.assertEqual(image.size, (280, 300))
            self.assertFalse(verify_png(preview)["compliant"])


class NetworkTests(unittest.TestCase):
    def test_duplicate_requests_are_cached(self):
        response = io.BytesIO(b"data")
        response.url = "https://example.com/icon.png"
        with patch("network.urllib.request.urlopen", return_value=response) as request:
            client = HttpClient()
            self.assertEqual(client.get(response.url), b"data")
            self.assertEqual(client.get(response.url), b"data")
            self.assertEqual(request.call_count, 1)

    def test_retries_are_bounded(self):
        error = urllib.error.HTTPError("https://example.com", 503, "Unavailable", {}, None)
        with patch("network.urllib.request.urlopen", side_effect=error) as request, patch("network.time.sleep"):
            with self.assertRaises(SourceError):
                HttpClient().get("https://example.com")
            self.assertEqual(request.call_count, 2)


if __name__ == "__main__":
    unittest.main()

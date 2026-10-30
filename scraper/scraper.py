# -*- coding: utf-8 -*-
"""竞品页面爬虫：抓取 AI 短视频生成网站的实际网页资料。

目标站点默认来自调研 md 文件（AI短视频网站页面形式调研.md）的「信息来源」章节；
也可以用 --urls 手动指定。每页输出三类材料：
  - {slug}.html  原始页面快照
  - {slug}.json  结构化摘要（标题/元数据/标题树/段落/CTA/导航/统计）
  - {slug}.png   首屏截图（仅当该页用了浏览器渲染时）
再输出 _manifest.json 统一记录本轮抓取状态。

JS 渲染支持：默认 --render auto，requests 拿到的可见文本少于 300 字
（JS 渲染 SPA / 反爬验证页）时，自动用 Playwright 无头浏览器重抓并截首屏图。
浏览器按顺序尝试：系统 Edge -> 系统 Chrome -> Playwright 自带的 Chromium。

用法：
  python scraper.py                  # 抓一轮（内容过少自动浏览器渲染）
  python scraper.py --render always  # 所有页面都用浏览器渲染
  python scraper.py --render off     # 只用 requests，不用浏览器
  python scraper.py --loop 86400     # 轮询模式：每 86400 秒重抓一轮（Ctrl+C 退出）
  python scraper.py --urls https://a.com https://b.com   # 手动指定 URL
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_MD = BASE_DIR.parent / "AI短视频网站页面形式调研.md"
DEFAULT_OUTDIR = BASE_DIR / "data" / "crawled"
# 浏览器二进制目录（安装 Playwright 自带 Chromium 时用，放项目内便于沙箱环境）
DEFAULT_BROWSERS_PATH = BASE_DIR.parent / ".pw-browsers"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

REQUEST_TIMEOUT = 25
RETRY_TIMES = 2
SLEEP_BETWEEN_PAGES = 1.5
# requests 结果可见文本少于该字数时，判定为"壳子页面"，触发浏览器渲染补抓
THIN_CONTENT_THRESHOLD = 300
RENDER_WAIT_MS = 5000  # 打开页面后等待 JS 渲染的毫秒数
RENDER_TIMEOUT_MS = 60000


def extract_md_links(md_path: Path) -> list:
    """从调研 md 的「信息来源」章节提取 [标题](URL) 链接。"""
    text = md_path.read_text(encoding="utf-8")
    m = re.search(r"^#{1,6}\s*信息来源\s*$.*?(?=^#{1,6}\s|\Z)", text, re.S | re.M)
    section = m.group(0) if m else text
    urls = re.findall(r"\]\((https?://[^)\s]+)\)", section)
    seen, result = set(), []
    for u in urls:
        u = u.strip()
        if u not in seen:
            seen.add(u)
            result.append(u)
    return result


def slugify(url: str) -> str:
    """URL -> 文件 slug（域名替换点 + 路径非字母数字替换下划线）。"""
    p = urlparse(url)
    base = (p.netloc + p.path).rstrip("/")
    s = re.sub(r"[^A-Za-z0-9]+", "_", base).strip("_")
    return (s[:80] or "page") + "_" + hashlib.md5(url.encode()).hexdigest()[:8]


def fetch(url: str) -> str:
    """带重试的 GET，返回解码后的 HTML 文本；失败抛异常。"""
    last_err = None
    for attempt in range(RETRY_TIMES + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
                resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise last_err


def render_with_browser(url: str, screenshot_path: Path) -> str:
    """用 Playwright 无头浏览器渲染页面，返回渲染后的 HTML，并保存首屏截图。

    浏览器按顺序尝试：系统 Edge -> 系统 Chrome -> Playwright 自带 Chromium。
    未安装 playwright 或全部浏览器不可用时抛异常（消息里带解法）。
    """
    try:
        from playwright.sync_api import sync_playwright  # 延迟导入，未安装时给出清晰提示
    except ImportError as e:
        raise RuntimeError(
            "未安装 playwright：pip install playwright；"
            "如需自带浏览器：python -m playwright install chromium"
        ) from e

    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(DEFAULT_BROWSERS_PATH))
    launch_options = [{"channel": "msedge"}, {"channel": "chrome"}, {}]
    last_err = None
    with sync_playwright() as pw:
        for opts in launch_options:
            try:
                browser = pw.chromium.launch(headless=True, **opts)
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
        else:
            raise RuntimeError(
                f"没有可用的 Chromium 内核浏览器（Edge/Chrome/自带 Chromium 均失败，"
                f"最后错误：{last_err}）。可运行：python -m playwright install chromium"
            )
        try:
            page = browser.new_page(
                viewport={"width": 1920, "height": 1080},
                user_agent=HEADERS["User-Agent"],
                locale="zh-CN",
            )
            page.goto(url, wait_until="domcontentloaded", timeout=RENDER_TIMEOUT_MS)
            page.wait_for_timeout(RENDER_WAIT_MS)
            html = page.content()
            page.screenshot(path=str(screenshot_path))
            return html
        finally:
            browser.close()


def _texts(soup, name, min_len=1, limit=None) -> list:
    out, seen = [], set()
    for t in soup.find_all(name):
        s = t.get_text(" ", strip=True)
        if len(s) >= min_len and s not in seen:
            seen.add(s)
            out.append(s)
        if limit and len(out) >= limit:
            break
    return out


def parse_page(html: str, url: str) -> dict:
    """把 HTML 解析成便于直接使用的结构化摘要。"""
    soup = BeautifulSoup(html, "html.parser")

    def meta(name, attr="name"):
        tag = soup.find("meta", attrs={attr: name})
        return (tag.get("content", "").strip() if tag else "")

    def og(prop):
        tag = soup.find("meta", attrs={"property": prop})
        return (tag.get("content", "").strip() if tag else "")

    # CTA / 按钮文案：按钮 + 带 btn 类名的 a + 指向注册/登录/创作/定价等关键路径的 a
    cta_texts, cta_seen = [], set()
    for tag in soup.find_all(["button", "a"]):
        text = tag.get_text(" ", strip=True)
        href = tag.get("href") or ""
        cls = " ".join(tag.get("class", [])) if tag.name == "a" else ""
        is_cta = (
            tag.name == "button"
            or "btn" in cls
            or re.search(r"(login|signin|signup|register|create|generate|app|start|pricing|try)", href, re.I)
        )
        if is_cta and text and text not in cta_seen:
            cta_seen.add(text)
            cta_texts.append(text)
        if len(cta_texts) >= 40:
            break

    return {
        "url": url,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "title": soup.title.get_text(strip=True) if soup.title else "",
        "meta": {
            "description": meta("description"),
            "keywords": meta("keywords"),
            "og_title": og("og:title"),
            "og_description": og("og:description"),
            "og_image": og("og:image"),
        },
        "headings": {
            "h1": _texts(soup, "h1", limit=10),
            "h2": _texts(soup, "h2", limit=60),
            "h3": _texts(soup, "h3", limit=80),
        },
        "paragraphs": _texts(soup, "p", min_len=30, limit=30),
        "cta_texts": cta_texts,
        "nav_links": _texts(soup.find("nav") or soup, "a", limit=40),
        "stats": {
            "image_count": len(soup.find_all("img")),
            "link_count": len(soup.find_all("a")),
            "visible_text_len": len(soup.get_text(" ", strip=True)),
        },
        "status": "ok",
        "error": None,
    }


def empty_result(url: str, error: str) -> dict:
    """占位结果，requests 与浏览器渲染都失败时使用。"""
    return {
        "url": url,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "title": "",
        "meta": {},
        "headings": {"h1": [], "h2": [], "h3": []},
        "paragraphs": [],
        "cta_texts": [],
        "nav_links": [],
        "stats": {"image_count": 0, "link_count": 0, "visible_text_len": 0},
        "status": "error",
        "error": error,
    }


def scrape_once(targets: list, outdir: Path, render: str = "auto") -> Path:
    """抓一轮：每个 URL 产出 slug.json + slug.html（浏览器渲染时另有 slug.png），最后写 _manifest.json。"""
    outdir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "targets": [],
    }
    for i, url in enumerate(targets, 1):
        slug = slugify(url)
        item = {
            "url": url,
            "slug": slug,
            "status": "ok",
            "title": "",
            "error": None,
            "render_used": False,
        }
        print(f"[{i}/{len(targets)}] {url}")
        html, data = None, None

        # 1) 普通请求（--render always 时跳过，直接用浏览器）
        if render != "always":
            try:
                html = fetch(url)
                data = parse_page(html, url)
            except Exception as e:  # noqa: BLE001
                print(f"    requests 失败：{type(e).__name__}: {str(e)[:60]}")

        # 2) 内容过少 / 请求失败 / 指定渲染 时，用浏览器补抓
        is_thin = data is None or data["stats"]["visible_text_len"] < THIN_CONTENT_THRESHOLD
        if render != "off" and (is_thin or render == "always"):
            reason = "指定 --render always" if render == "always" else (
                f"文本仅 {data['stats']['visible_text_len'] if data else 0} 字，判定为 JS 渲染页"
            )
            print(f"    {reason}，用浏览器渲染重抓…")
            try:
                shot_path = outdir / f"{slug}.png"
                html = render_with_browser(url, shot_path)
                data = parse_page(html, url)
                data["render_used"] = True
                data["screenshot"] = shot_path.name
                item["render_used"] = True
                item["screenshot"] = shot_path.name
            except Exception as e:  # noqa: BLE001
                print(f"    浏览器渲染失败：{type(e).__name__}: {str(e)[:80]}（保留原结果）")

        # 3) 落盘
        if data is None:
            item["status"] = "error"
            item["error"] = "requests 与浏览器渲染均失败"
            data = empty_result(url, item["error"])
        else:
            item["title"] = data["title"]
            if html:
                (outdir / f"{slug}.html").write_text(html, encoding="utf-8")
        (outdir / f"{slug}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tag = " [R]" if data.get("render_used") else ""
        print(f"    OK{tag}  {data['title'][:60]} | h1={len(data['headings']['h1'])} "
              f"h2={len(data['headings']['h2'])} 文本={data['stats']['visible_text_len']}字")
        manifest["targets"].append(item)
        time.sleep(SLEEP_BETWEEN_PAGES)

    manifest_path = outdir / "_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = sum(1 for t in manifest["targets"] if t["status"] == "ok")
    rendered = sum(1 for t in manifest["targets"] if t.get("render_used"))
    print(f"\n本轮完成：{ok}/{len(targets)} 成功（其中浏览器渲染 {rendered} 页），材料落在 {outdir}")
    return manifest_path


def main():
    parser = argparse.ArgumentParser(description="抓取竞品页面资料（支持轮询）")
    parser.add_argument("--urls", nargs="*", default=None, help="手动指定 URL，缺省从调研 md 读取")
    parser.add_argument("--md", type=Path, default=DEFAULT_MD, help="调研 md 路径")
    parser.add_argument("--outdir", type=Path, default=None, help="输出目录，缺省 data/crawled/YYYYMMDD")
    parser.add_argument("--loop", type=int, default=0, help=">0 时轮询循环：每 N 秒重抓一轮")
    parser.add_argument(
        "--render",
        choices=["auto", "always", "off"],
        default="auto",
        help="浏览器渲染策略：auto=内容过少时自动补抓（默认）；always=全部浏览器渲染；off=只用 requests",
    )
    args = parser.parse_args()

    targets = args.urls if args.urls else extract_md_links(args.md)
    if not targets:
        print(f"未找到目标 URL（--md={args.md}），请检查「信息来源」章节或使用 --urls")
        sys.exit(1)
    print(f"目标 {len(targets)} 个页面，来源：{'--urls' if args.urls else args.md}")

    day = datetime.now().strftime("%Y%m%d")
    outdir = args.outdir or DEFAULT_OUTDIR / day

    while True:
        scrape_once(targets, outdir, render=args.render)
        if not args.loop:
            break
        print(f"\n轮询模式：{args.loop} 秒后重抓下一轮（Ctrl+C 退出）\n")
        try:
            time.sleep(args.loop)
        except KeyboardInterrupt:
            print("\n已退出轮询。")
            break


if __name__ == "__main__":
    main()
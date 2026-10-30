# -*- coding: utf-8 -*-
"""材料处理器：把爬虫抓取的 JSON 材料汇总成便于直接使用的 Markdown。

用法：
  python process.py                 # 处理 data/crawled 下最新一天的抓取结果
  python process.py --day 20261030  # 处理指定日期目录
输出：{日期目录}/页面实录汇总.md
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent
CRAWLED_DIR = BASE_DIR / "data" / "crawled"

# 域名 -> 产品名，汇总文档里用产品名做小标题
SITE_ALIAS = {
    "kling.ai": "可灵 AI",
    "jimeng.jianying.com": "即梦 AI",
    "vidu.cn": "Vidu",
    "platform.vidu.com": "Vidu（开发者平台）",
    "hailuoai.video": "海螺 AI",
    "runway.com": "Runway",
    "pikaslabs.com": "Pika",
    "openai.com": "OpenAI / Sora",
    "36kr.com": "36氪（媒体）",
    "m.toutiao.com": "人人都是产品经理（媒体）",
    "iqilian.com": "奇连 AI（媒体）",
    "help.openai.com": "OpenAI 帮助中心",
}


def site_name(url: str) -> str:
    host = urlparse(url).netloc.lower()
    for prefix, name in SITE_ALIAS.items():
        if host == prefix or host.endswith("." + prefix):
            return name
    return host


def newest_day() -> Path | None:
    days = sorted([p for p in CRAWLED_DIR.glob("*") if p.is_dir()], reverse=True)
    return days[0] if days else None


def load_materials(day_dir: Path):
    """读 _manifest.json 与所有 {slug}.json。"""
    manifest_path = day_dir / "_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
    pages = []
    for p in sorted(day_dir.glob("*.json")):
        if p.name.startswith("_"):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            data["slug"] = p.stem  # 补上文件名，便于引用快照
            pages.append(data)
        except json.JSONDecodeError:
            continue
    return manifest, pages


def page_section(data: dict) -> str:
    """单个页面 -> md 章节。"""
    head = data["headings"]
    method = "浏览器渲染（Playwright）" if data.get("render_used") else "HTTP 直抓"
    if data.get("screenshot"):
        method += f"，首屏截图 `{data['screenshot']}`"
    lines = [
        f"### {data['title'] or '(无标题)'}",
        "",
        f"- 来源：{data['url']}",
        f"- 抓取时间：{data['fetched_at']}",
        f"- 抓取方式：{method}",
        f"- 快照：`{data['slug']}.html` / `{data['slug']}.json`",
        f"- 规模：图片 {data['stats']['image_count']} 张 | 链接 {data['stats']['link_count']} 条 | 可见文本约 {data['stats']['visible_text_len']} 字",
    ]
    m = data["meta"]
    if m.get("description"):
        lines += ["", "**页面描述（meta description）**：", "", f"> {m['description']}"]
    if any(head.values()):
        lines += ["", "**页面结构（标题树）**：", ""]
        seen = set()
        for level, marker in (("h1", "#"), ("h2", "##"), ("h3", "###")):
            for t in head[level]:
                key, n = level + t, 0
                while key in seen:
                    n += 1
                    key = f"{level}{t}#{n}"
                seen.add(key)
                indent = "  " * (1 if level == "h2" else 2 if level == "h3" else 0)
                lines.append(f"{indent}- {t}")
    if data["cta_texts"]:
        lines += ["", "**CTA / 按钮文案**：", "", ", ".join(data["cta_texts"][:25]) or "（无）"]
    if data["paragraphs"]:
        lines += ["", "**关键段落节选**："]
        for para in data["paragraphs"][:8]:
            text = para if len(para) <= 160 else para[:160] + "…"
            lines += ["", f"- {text}"]
    if data["error"]:
        lines += ["", f"> 抓取失败：{data['error']}"]
    return "\n".join(lines)


def render(fetched_at: str, manifest, pages) -> str:
    ok = [p for p in pages if p["status"] == "ok"]
    failed = manifest["targets"] if manifest else []
    ok_urls = {p["url"] for p in ok}
    failed_items = [t for t in failed if t["status"] != "ok" and t["url"] not in ok_urls]
    lines = [
        "# 竞品页面实测抓取汇总",
        "",
        f"> 抓取时间：{fetched_at} | 成功 {len(ok)} 页 / 失败 {len(failed_items)} 页",
        "> 本文件由 `process.py` 自动生成，可直接复制到调研文档的附录中使用。",
        "",
        "## 抓取总览",
        "",
        "| # | 站点 | 页面标题 | 状态 |",
        "|---|------|----------|------|",
    ]
    for i, t in enumerate(failed, 1):
        if t["status"] == "ok":
            lines.append(f"| {i} | {site_name(t['url'])} | {t['title'][:50]} | ok |")
    for t in failed_items:
        lines.append(
            f"| {len(lines) - 7} | {site_name(t['url'])} | {t['url'][:50]} | 失败：{t['error'][:40]} |"
        )
    lines += ["", "## 页面实录（按站点）", ""]
    for p in pages:
        lines += [f"## {site_name(p['url'])}", "", page_section(p), ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="汇总爬虫材料为 Markdown")
    parser.add_argument("--day", type=str, default=None, help="日期目录名，如 20261030；缺省取最新")
    args = parser.parse_args()

    day_dir = CRAWLED_DIR / args.day if args.day else newest_day()
    if not day_dir or not day_dir.exists():
        print(f"没有可处理的抓取材料（{day_dir}），请先运行 scraper.py")
        sys.exit(1)
    manifest, pages = load_materials(day_dir)
    if not pages:
        print(f"{day_dir} 下没有页面 JSON，请先运行 scraper.py")
        sys.exit(1)

    fetched_at = manifest["fetched_at"] if manifest else datetime.now().isoformat()
    out = day_dir / "页面实录汇总.md"
    out.write_text(render(fetched_at, manifest, pages), encoding="utf-8")
    print(f"已生成：{out}（{len(pages)} 个页面）")


if __name__ == "__main__":
    main()
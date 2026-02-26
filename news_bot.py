"""
每日新聞摘要 Telegram Bot
- 抓取台灣綜合、國際、科技、財經新聞 (RSS)
- 使用 OpenAI API (GPT-4o-mini) 產生中文摘要
- 推播到 Telegram
"""

import os
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.request import urlopen, Request
from urllib.parse import quote

# ─── 設定 ───────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_IDS = [cid.strip() for cid in os.environ["TELEGRAM_CHAT_ID"].split(",")]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

# 台灣時間
TW_TZ = timezone(timedelta(hours=8))

# ─── RSS 新聞來源 ────────────────────────────────────────
RSS_FEEDS = {
    "🇹🇼 台灣綜合": [
        "https://news.ltn.com.tw/rss/all.xml",
        "https://feeds.feedburner.com/ettoday/global",
    ],
    "🌍 國際新聞": [
        "https://news.ltn.com.tw/rss/world.xml",
        "https://www.cna.com.tw/rss/aall.xml",
    ],
    "💻 科技新聞": [
        "https://feeds.feedburner.com/ithome",
        "https://technews.tw/feed/",
    ],
    "🤖 AI 新聞": [
        "https://www.theverge.com/ai-artificial-intelligence/rss/index.xml",  # The Verge AI
        "https://venturebeat.com/ai/feed/",                                    # VentureBeat AI
        "https://techcrunch.com/tag/artificial-intelligence/feed/",            # TechCrunch AI
    ],
    "💰 財經新聞": [
        "https://news.ltn.com.tw/rss/business.xml",
        "https://www.cna.com.tw/rss/aafe.xml",
    ],
}

MAX_ITEMS_PER_FEED = 20  # 多抓一些，過濾日期後再限制數量
MAX_ITEMS_PER_FEED_FINAL = 5  # 過濾後每個來源最多保留幾則


def is_today(pub_date_str: str) -> bool:
    """判斷發布日期是否為今天（台灣時間）。無法解析時回傳 True（保留該則新聞）。"""
    if not pub_date_str:
        return True
    try:
        # RSS 2.0 的 pubDate 格式：RFC 2822，例如 "Mon, 24 Feb 2026 01:00:00 +0800"
        pub_dt = parsedate_to_datetime(pub_date_str)
        pub_tw = pub_dt.astimezone(TW_TZ)
        today_tw = datetime.now(TW_TZ).date()
        return pub_tw.date() == today_tw
    except Exception:
        return True  # 解析失敗時保留，不誤殺


# ─── 工具函式 ────────────────────────────────────────────
def fetch_url(url: str, timeout: int = 15) -> str:
    """取得網頁內容"""
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 DailyNewsBot/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_rss(xml_text: str, max_items: int = MAX_ITEMS_PER_FEED) -> list[dict]:
    """解析 RSS/Atom feed，只保留今天的新聞，回傳 [{title, link, description}]"""
    items = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items

    # 處理不同的 namespace
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    # RSS 2.0
    for item in root.findall(".//item")[:max_items]:
        pub_date = item.findtext("pubDate", "").strip()
        if not is_today(pub_date):
            continue  # ← 跳過非今天的新聞

        title = item.findtext("title", "").strip()
        link = item.findtext("link", "").strip()
        desc = item.findtext("description", "").strip()
        desc = re.sub(r"<[^>]+>", "", desc)[:300]
        if title:
            items.append({"title": title, "link": link, "description": desc})

    # Atom feed
    if not items:
        for entry in root.findall(".//atom:entry", ns)[:max_items]:
            # Atom 的日期欄位是 <updated> 或 <published>
            pub_date = (
                entry.findtext("atom:published", "", ns)
                or entry.findtext("atom:updated", "", ns)
            ).strip()

            # Atom 日期格式是 ISO 8601，需要另外解析
            if pub_date:
                try:
                    pub_dt = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
                    pub_tw = pub_dt.astimezone(TW_TZ)
                    today_tw = datetime.now(TW_TZ).date()
                    if pub_tw.date() != today_tw:
                        continue  # ← 跳過非今天的新聞
                except Exception:
                    pass  # 解析失敗就保留

            title = entry.findtext("atom:title", "", ns).strip()
            link_el = entry.find("atom:link", ns)
            link = link_el.get("href", "") if link_el is not None else ""
            desc = entry.findtext("atom:summary", "", ns).strip()
            desc = re.sub(r"<[^>]+>", "", desc)[:300]
            if title:
                items.append({"title": title, "link": link, "description": desc})

    return items[:MAX_ITEMS_PER_FEED_FINAL]


def fetch_all_news() -> dict[str, list[dict]]:
    """抓取所有分類的新聞"""
    all_news = {}
    for category, feeds in RSS_FEEDS.items():
        category_items = []
        for feed_url in feeds:
            try:
                xml_text = fetch_url(feed_url)
                fetched = parse_rss(xml_text)
                print(f"  📌 {feed_url} → 今天共 {len(fetched)} 則")
                category_items.extend(fetched)
            except Exception as e:
                print(f"⚠️ 無法抓取 {feed_url}: {e}")
        all_news[category] = category_items
    return all_news


def build_prompt(all_news: dict[str, list[dict]]) -> str:
    """組合 prompt 給 GPT 做摘要"""
    news_text = ""
    for category, items in all_news.items():
        news_text += f"\n\n## {category}\n"
        for i, item in enumerate(items, 1):
            news_text += f"{i}. {item['title']}\n"
            if item["description"]:
                news_text += f"   {item['description']}\n"

    today = datetime.now(TW_TZ).strftime("%Y/%m/%d (%A)")

    return f"""你是一位專業的新聞編輯。以下是今天（{today}）從各大媒體抓取的新聞標題與摘要。

請幫我：
1. 每個分類挑出 3-5 則最重要的新聞
2. 用繁體中文撰寫簡短摘要（每則 1-2 句話）
3. 格式使用 Telegram 支援的 HTML 格式

輸出格式範例：
<b>📰 每日新聞摘要 — {today}</b>

<b>🇹🇼 台灣綜合</b>
• <b>標題</b>：一句話摘要
• <b>標題</b>：一句話摘要

（其他分類同上）

結尾加上一句鼓勵的話。

以下是今天的原始新聞：
{news_text}
"""


def call_ai(prompt: str) -> str:
    """呼叫 OpenAI API 取得摘要"""
    body = json.dumps({
        "model": "gpt-4o-mini",
        "max_tokens": 2048,
        "messages": [
            {"role": "system", "content": "你是一位專業的繁體中文新聞編輯。"},
            {"role": "user", "content": prompt},
        ],
    }).encode("utf-8")

    req = Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}",
        },
        method="POST",
    )

    with urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode())

    return data["choices"][0]["message"]["content"]


def send_telegram(text: str):
    """發送訊息到所有 Telegram 用戶"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    for chat_id in TELEGRAM_CHAT_IDS:
        body = json.dumps({
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }).encode("utf-8")

        req = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")

        try:
            with urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode())
                if not result.get("ok"):
                    print(f"⚠️ Telegram 發送失敗 (chat_id: {chat_id}): {result}")
                else:
                    print(f"✅ 訊息已發送到 {chat_id}")
        except Exception as e:
            print(f"⚠️ Telegram 發送失敗 (chat_id: {chat_id}): {e}")


# ─── 主程式 ──────────────────────────────────────────────
def main():
    print("📡 正在抓取新聞...")
    all_news = fetch_all_news()

    total = sum(len(v) for v in all_news.values())
    print(f"📰 今天共抓取 {total} 則新聞")

    if total == 0:
        send_telegram("⚠️ 今天無法抓取新聞，請檢查 RSS 來源。")
        return

    print("🤖 正在用 GPT-4o-mini 產生摘要...")
    summary = call_ai(build_prompt(all_news))

    # Telegram 訊息長度限制 4096 字
    if len(summary) > 4096:
        summary = summary[:4090] + "\n..."

    print("📤 正在發送到 Telegram...")
    send_telegram(summary)
    print("🎉 完成！")


if __name__ == "__main__":
    main()

"""
每日新聞摘要 Telegram Bot
- 抓取台灣綜合、國際、科技、財經新聞 (RSS)
- 使用 Google Gemini API (Gemini 1.5 Flash) 產生中文摘要 — 完全免費
- 推播到 Telegram
"""

import os
import json
import re
import hashlib
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.request import urlopen, Request
from urllib.parse import quote

# ─── 設定 ───────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_IDS = [cid.strip() for cid in os.environ["TELEGRAM_CHAT_ID"].split(",")]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# 台灣時間
TW_TZ = timezone(timedelta(hours=8))

# 手動觸發模式（workflow_dispatch）→ 不做去重複，方便測試
IS_MANUAL = os.environ.get("IS_MANUAL", "false").lower() == "true"

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

# ─── 黑名單（標題含這些關鍵字的新聞直接跳過）─────────────
TITLE_BLACKLIST = [
    "冰與火之歌",
    "權力遊戲",
]

SEEN_FILE = "seen_titles.json"  # 由 GitHub Actions Cache 跨天保留


# ─── 去重複機制 ──────────────────────────────────────────
def title_hash(title: str) -> str:
    """將標題轉成短 hash，避免存太長的字串"""
    return hashlib.md5(title.strip().encode("utf-8")).hexdigest()


def load_seen() -> set:
    """讀取已推播過的標題 hash"""
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r") as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()


def save_seen(seen: set):
    """儲存已推播的標題 hash（只保留最近 500 筆，避免無限膨脹）"""
    seen_list = list(seen)[-500:]
    with open(SEEN_FILE, "w") as f:
        json.dump(seen_list, f)


def filter_seen(items: list[dict], seen: set) -> list[dict]:
    """過濾掉已推播過的新聞"""
    return [item for item in items if title_hash(item["title"]) not in seen]


def mark_seen(items: list[dict], seen: set):
    """將本次推播的標題加入 seen"""
    for item in items:
        seen.add(title_hash(item["title"]))


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


def parse_rss(xml_text: str, max_items: int = MAX_ITEMS_PER_FEED, skip_date_filter: bool = False) -> list[dict]:
    """解析 RSS/Atom feed，回傳 [{title, link, description}]。skip_date_filter=True 時不過濾日期（用於英文來源）"""
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
        if not skip_date_filter and not is_today(pub_date):
            continue  # ← 跳過非今天的新聞

        title = item.findtext("title", "").strip()
        if any(kw in title for kw in TITLE_BLACKLIST):
            continue  # ← 黑名單過濾
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
            if pub_date and not skip_date_filter:
                try:
                    pub_dt = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
                    pub_tw = pub_dt.astimezone(TW_TZ)
                    today_tw = datetime.now(TW_TZ).date()
                    if pub_tw.date() != today_tw:
                        continue  # ← 跳過非今天的新聞
                except Exception:
                    pass  # 解析失敗就保留

            title = entry.findtext("atom:title", "", ns).strip()
            if any(kw in title for kw in TITLE_BLACKLIST):
                continue  # ← 黑名單過濾
            link_el = entry.find("atom:link", ns)
            link = link_el.get("href", "") if link_el is not None else ""
            desc = entry.findtext("atom:summary", "", ns).strip()
            desc = re.sub(r"<[^>]+>", "", desc)[:300]
            if title:
                items.append({"title": title, "link": link, "description": desc})

    return items[:MAX_ITEMS_PER_FEED_FINAL]


# 英文來源不做日期過濾（因為美國時間比台灣晚，早上跑時文章日期還是昨天）
EN_FEEDS = {
    "https://www.theverge.com/ai-artificial-intelligence/rss/index.xml",
    "https://venturebeat.com/ai/feed/",
    "https://techcrunch.com/tag/artificial-intelligence/feed/",
}


def fetch_all_news(seen: set) -> dict[str, list[dict]]:
    """抓取所有分類的新聞，並過濾已推播過的標題"""
    all_news = {}
    for category, feeds in RSS_FEEDS.items():
        category_items = []
        for feed_url in feeds:
            try:
                xml_text = fetch_url(feed_url)
                skip_date = feed_url in EN_FEEDS  # 英文來源不做日期過濾
                fetched = parse_rss(xml_text, skip_date_filter=skip_date)
                if not IS_MANUAL:
                    fetched = filter_seen(fetched, seen)  # ← 自動排程才去重複
                print(f"  📌 {feed_url} → {len(fetched)} 則")
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
    """呼叫 Google Gemini API 取得摘要（免費方案）"""
    system = "你是一位專業的繁體中文新聞編輯。"
    full_prompt = system + "\n\n" + prompt

    body = json.dumps({
        "contents": [{"parts": [{"text": full_prompt}]}],
        "generationConfig": {"maxOutputTokens": 2048},
    }).encode("utf-8")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    req = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode())

    return data["candidates"][0]["content"]["parts"][0]["text"]


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
    seen = load_seen()
    print(f"📋 已記錄 {len(seen)} 則推播過的新聞")

    all_news = fetch_all_news(seen)

    total = sum(len(v) for v in all_news.values())
    print(f"📰 今天共抓取 {total} 則新聞（未推播過）")

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

    # 推播成功後才記錄（手動測試模式不記錄，避免影響明天的自動推播）
    if not IS_MANUAL:
        for items in all_news.values():
            mark_seen(items, seen)
        save_seen(seen)
        print(f"💾 已記錄本次推播標題，總計 {len(seen)} 筆")
    else:
        print("ℹ️ 手動測試模式，不記錄推播標題")
    print("🎉 完成！")


if __name__ == "__main__":
    main()

"""
VoteFlux 每日產業新聞報告
- 爬取各預測市場平台的 RSS/部落格
- 使用 OpenAI GPT-4o 以資深新聞記者角度彙整 10-15 則重要新聞
- 每則附短評，結尾加綜合評論
- 產生 Dark Mode HTML 報告部署到 GitHub Pages
- 推播報告連結到 Telegram（多人支援）
"""

import os
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# ─── 設定 ───────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_IDS = [cid.strip() for cid in os.environ["TELEGRAM_CHAT_ID"].split(",")]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
GITHUB_PAGES_URL = os.environ.get("GITHUB_PAGES_URL", "https://你的帳號.github.io/daily-news-bot")

TW_TZ = timezone(timedelta(hours=8))
TODAY = datetime.now(TW_TZ)
TODAY_STR = TODAY.strftime("%Y/%m/%d (%A)")
TODAY_FILE = TODAY.strftime("%Y-%m-%d")


# ─── 平台設定 ────────────────────────────────────────────
# 固定 6 個平台（含 VoteFlux）+ 1 個隨機競品（由 GPT 決定）
FIXED_PLATFORMS = [
    {
        "name": "Polymarket",
        "url": "https://polymarket.com",
        "rss": "https://news.polymarket.com/feed",          # Substack RSS
        "fallback_search": "Polymarket prediction market news",
    },
    {
        "name": "Kalshi",
        "url": "https://kalshi.com",
        "rss": "https://kalshi.com/blog/rss",
        "fallback_search": "Kalshi prediction market news",
    },
    {
        "name": "VoteFlux",
        "url": "https://voteflux.com/en",
        "rss": None,
        "fallback_search": "VoteFlux prediction market news",
    },
    {
        "name": "Hyperliquid",
        "url": "https://hyperliquid.xyz",
        "rss": None,
        "fallback_search": "Hyperliquid DEX news announcement 2025",
    },
    {
        "name": "Predict.fun",
        "url": "https://predict.fun",
        "rss": None,
        "fallback_search": "Predict.fun prediction market news",
    },
]

# DAILY DISCOVERY 候選池（真實存在的平台）
DISCOVERY_CANDIDATES = [
    "Metaculus", "Manifold Markets", "Hedgehog Markets", "PredictIt",
    "Drift Protocol", "Azuro", "PlotX", "Zeitgeist", "Omen", "Futuur",
    "Smarkets", "Betfair Exchange", "Insight Prediction",
    "Iowa Electronic Markets", "Fantasy Top", "Thales Market", "Overtime Markets",
]


# ─── 工具函式 ────────────────────────────────────────────
def fetch_url(url: str, timeout: int = 15) -> str:
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; VoteFluxBot/2.0)",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    })
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_rss(xml_text: str, max_items: int = 8) -> list[dict]:
    """解析 RSS/Atom，回傳 [{title, link, description, pub_date}]"""
    items = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items

    ns = {"atom": "http://www.w3.org/2005/Atom"}

    # RSS 2.0
    for item in root.findall(".//item")[:max_items]:
        title = item.findtext("title", "").strip()
        link = item.findtext("link", "").strip()
        desc = re.sub(r"<[^>]+>", "", item.findtext("description", "")).strip()[:400]
        pub_date = item.findtext("pubDate", "").strip()
        if title:
            items.append({"title": title, "link": link, "description": desc, "pub_date": pub_date})

    # Atom
    if not items:
        for entry in root.findall(".//atom:entry", ns)[:max_items]:
            title = entry.findtext("atom:title", "", ns).strip()
            link_el = entry.find("atom:link", ns)
            link = link_el.get("href", "") if link_el is not None else ""
            desc = re.sub(r"<[^>]+>", "", entry.findtext("atom:summary", "", ns)).strip()[:400]
            pub_date = entry.findtext("atom:updated", "", ns).strip()
            if title:
                items.append({"title": title, "link": link, "description": desc, "pub_date": pub_date})

    return items


def fetch_platform_news(platform: dict) -> dict:
    """嘗試爬取單一平台的 RSS，回傳結果或空清單"""
    result = {"name": platform["name"], "url": platform["url"], "articles": [], "source": "none"}

    if platform.get("rss"):
        try:
            xml_text = fetch_url(platform["rss"])
            articles = parse_rss(xml_text)
            if articles:
                result["articles"] = articles
                result["source"] = "rss"
                print(f"  ✅ {platform['name']}: RSS 成功，{len(articles)} 則")
                return result
        except Exception as e:
            print(f"  ⚠️ {platform['name']}: RSS 失敗 ({e})")

    # RSS 失敗或無 RSS → 標記為需要 GPT 補充
    result["source"] = "gpt_needed"
    result["search_hint"] = platform.get("fallback_search", platform["name"] + " news")
    print(f"  ℹ️ {platform['name']}: 將由 GPT 補充近況")
    return result


# ─── OpenAI API 呼叫 ────────────────────────────────────
def call_openai(system_prompt: str, user_prompt: str, model: str = "gpt-4o") -> str:
    body = json.dumps({
        "model": model,
        "max_tokens": 4096,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
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

    with urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())

    return data["choices"][0]["message"]["content"]


# ─── 產生報告資料（JSON）───────────────────────────────────
SYSTEM_PROMPT = """你是一位擁有超過 15 年資歷的資深財經科技新聞記者，長期深耕預測市場（Prediction Market）與去中心化金融（DeFi）產業報導。

你的背景：
- 曾任職於主流財經媒體，目前獨立撰稿，專注預測市場、事件合約、鏈上交易等議題
- 你的文章風格：客觀、精準、有洞察力，不炒作，也不手軟
- 你熟悉 Polymarket、Kalshi、Hyperliquid 等主要平台的商業模式與監管環境
- 你關注產業趨勢：法規動向、資金流向、技術演進、用戶行為

你的任務是每天匯整預測市場產業的重要新聞，以記者視角撰寫報告。
所有輸出皆使用繁體中文。你必須以純 JSON 格式回覆，不要輸出任何其他文字。"""


def generate_report_data(platform_data: list[dict]) -> dict:
    # 整理已爬到的內容
    crawled_content = ""
    gpt_needed_platforms = []

    for p in platform_data:
        if p["source"] == "rss" and p["articles"]:
            crawled_content += f"\n\n### {p['name']} (來源: RSS)\n"
            for a in p["articles"]:
                crawled_content += f"- 標題: {a['title']}\n"
                if a.get("description"):
                    crawled_content += f"  摘要: {a['description'][:200]}\n"
                if a.get("pub_date"):
                    crawled_content += f"  日期: {a['pub_date']}\n"
        else:
            gpt_needed_platforms.append(p["name"])

    gpt_needed_str = ""
    if gpt_needed_platforms:
        gpt_needed_str = f"""
以下平台未能爬取 RSS，請根據你的知識補充這些平台截至今日的近期重要動態（最近 2-4 週內的真實事件，若不確定請不要捏造）：
{', '.join(gpt_needed_platforms)}
"""

    # Daily Discovery 平台由 GPT 從候選池挑選
    candidates_str = ", ".join(DISCOVERY_CANDIDATES)

    user_prompt = f"""今天是 {TODAY_STR}。

你需要彙整一份預測市場產業每日新聞報告。

【已爬取的平台新聞】
{crawled_content if crawled_content else "（本次未能爬取到 RSS 內容）"}

{gpt_needed_str}

【DAILY DISCOVERY】
從以下真實存在的平台候選池中挑選今天的 1 個重點平台進行介紹（不能重複選固定的 6 個平台）：
候選平台：{candidates_str}

⚠️ 選的平台必須是真實存在且目前仍在運營的，網址必須真實可連線。

【任務說明】
1. 整合上述所有平台的新聞，從中挑出今天最值得關注的 10-15 則新聞（涵蓋多個平台）
2. 每則新聞附一句話記者短評（客觀、有洞察力、不超過 50 字）
3. 在所有新聞結束後，撰寫一段「今日產業綜合評論」（300-500 字，記者第一人稱，分析整體趨勢）
4. 選出今日 DAILY DISCOVERY 平台

請以嚴格 JSON 格式回覆（不要加 markdown 代碼塊），結構如下：

{{
  "daily_discovery": {{
    "name": "平台名稱",
    "url": "真實網址",
    "category": "平台類型（如：社群預測、合規交易所、DeFi 等）",
    "description": "這平台做什麼（2-3句）",
    "reporter_note": "記者視角的觀察（2-3句，分析其在產業中的定位）"
  }},
  "news_items": [
    {{
      "id": 1,
      "platform": "平台名稱",
      "title": "新聞標題",
      "summary": "新聞摘要（2-3句，客觀描述事件）",
      "reporter_comment": "記者短評（一句話，有洞察力）",
      "source_url": "原文完整 URL（必須以 https:// 開頭；若不確定請填空字串 \"\"，絕對不要填 example.com 或假網址）",
      "importance": "high/medium/low"
    }}
  ],
  "industry_analysis": {{
    "headline": "今日分析標題（一句話破題）",
    "content": "今日產業綜合評論全文（300-500字，繁體中文，記者第一人稱）",
    "key_trends": ["趨勢關鍵字1", "趨勢關鍵字2", "趨勢關鍵字3"]
  }}
}}

news_items 必須包含 10-15 則，importance 欄位用於排版優先級。
只輸出 JSON，不要輸出任何其他文字。"""

    raw = call_openai(SYSTEM_PROMPT, user_prompt)

    # 清理 markdown 包裹
    raw = re.sub(r'^```json?\s*\n?', '', raw.strip())
    raw = re.sub(r'\n?```\s*$', '', raw.strip())

    print(f"🔍 [DEBUG] JSON 長度: {len(raw)} 字元")
    print(f"🔍 [DEBUG] 前 200 字:\n{raw[:200]}")

    return json.loads(raw)


# ─── 組裝 HTML ───────────────────────────────────────────
PLATFORM_COLORS = {
    "Polymarket": "#0066ff",
    "Kalshi": "#00b386",
    "VoteFlux": "#f0883e",
    "Hyperliquid": "#8957e5",
    "Predict.fun": "#d29922",
}

IMPORTANCE_LABELS = {
    "high": ("🔴", "重點"),
    "medium": ("🟡", "一般"),
    "low": ("⚪", "參考"),
}


def get_platform_color(name: str) -> str:
    for key, color in PLATFORM_COLORS.items():
        if key.lower() in name.lower():
            return color
    return "#58a6ff"


def build_html(data: dict) -> str:
    dd = data["daily_discovery"]
    news_items = data["news_items"]
    analysis = data["industry_analysis"]

    # 依 importance 排序：high → medium → low
    importance_order = {"high": 0, "medium": 1, "low": 2}
    sorted_news = sorted(news_items, key=lambda x: importance_order.get(x.get("importance", "medium"), 1))

    # 統計各平台新聞數量
    platform_counts: dict[str, int] = {}
    for item in news_items:
        p = item.get("platform", "其他")
        platform_counts[p] = platform_counts.get(p, 0) + 1

    platform_pills = ""
    for p, count in sorted(platform_counts.items(), key=lambda x: -x[1]):
        color = get_platform_color(p)
        platform_pills += f'<span class="platform-pill" style="border-color:{color};color:{color}">{p} <b>{count}</b></span>'

    # 趨勢標籤
    trend_tags = "".join(f'<span class="trend-tag">{t}</span>' for t in analysis.get("key_trends", []))

    # 新聞卡片
    news_cards = ""
    for item in sorted_news:
        imp = item.get("importance", "medium")
        imp_icon, imp_label = IMPORTANCE_LABELS.get(imp, ("⚪", "參考"))
        color = get_platform_color(item.get("platform", ""))
        source_link = ""
        raw_url = item.get("source_url", "") or ""
        if raw_url.startswith("http://") or raw_url.startswith("https://"):
            source_link = f'<a href="{raw_url}" target="_blank" class="source-link">原文 →</a>'

        news_cards += f"""
        <div class="news-card importance-{imp}">
            <div class="news-header">
                <span class="platform-badge" style="background:rgba({hex_to_rgb(color)},0.15);color:{color};border:1px solid {color}">{item.get('platform','')}</span>
                <span class="importance-badge">{imp_icon} {imp_label}</span>
                {source_link}
            </div>
            <div class="news-title">{item.get('title','')}</div>
            <div class="news-summary">{item.get('summary','')}</div>
            <div class="reporter-comment">
                <span class="comment-icon">🖊</span>
                <span class="comment-text">{item.get('reporter_comment','')}</span>
            </div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VoteFlux 產業新聞日報 — {TODAY_STR}</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        background: #0d1117; color: #c9d1d9;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans TC', sans-serif;
        line-height: 1.7; padding: 20px; max-width: 960px; margin: 0 auto;
    }}
    a {{ color: #58a6ff; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}

    /* Header */
    .header {{
        text-align: center; padding: 36px 0 28px;
        border-bottom: 2px solid #21262d; margin-bottom: 32px;
    }}
    .header h1 {{ color: #e6edf3; font-size: 1.9em; font-weight: 700; letter-spacing: -0.5px; }}
    .header .subtitle {{ color: #8b949e; font-size: 0.95em; margin-top: 6px; }}
    .header .date {{ color: #f0883e; font-size: 1em; margin-top: 10px; font-weight: 600; }}

    /* Section titles */
    h2 {{
        color: #e6edf3; font-size: 1.2em; font-weight: 700;
        margin: 36px 0 16px;
        display: flex; align-items: center; gap: 10px;
    }}
    h2::after {{
        content: ''; flex: 1; height: 1px; background: #21262d;
    }}

    /* Platform pills */
    .platform-summary {{
        display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 24px;
    }}
    .platform-pill {{
        padding: 4px 12px; border-radius: 20px; border: 1px solid;
        font-size: 0.85em; font-weight: 500;
    }}
    .platform-pill b {{ font-weight: 700; }}

    /* Daily Discovery */
    .discovery {{
        background: linear-gradient(135deg, #161b22, #1a2030);
        border: 1px solid #f0883e; border-radius: 12px;
        padding: 24px; margin-bottom: 8px;
    }}
    .discovery-meta {{
        display: flex; align-items: center; gap: 10px; margin-bottom: 14px; flex-wrap: wrap;
    }}
    .discovery-badge {{
        background: #f0883e; color: #0d1117;
        padding: 3px 12px; border-radius: 20px;
        font-size: 0.8em; font-weight: 700; letter-spacing: 1px;
    }}
    .discovery-name {{ color: #f0883e; font-size: 1.3em; font-weight: 700; }}
    .discovery-category {{
        background: rgba(240,136,62,0.1); color: #f0883e;
        padding: 2px 10px; border-radius: 4px; font-size: 0.8em;
    }}
    .discovery-url {{ font-size: 0.85em; margin-bottom: 12px; }}
    .discovery p {{ color: #c9d1d9; margin-bottom: 12px; font-size: 0.95em; }}
    .reporter-note-box {{
        background: rgba(240,136,62,0.07); border-left: 3px solid #f0883e;
        padding: 12px 16px; border-radius: 0 6px 6px 0;
        font-size: 0.9em; color: #e6edf3;
    }}
    .reporter-note-box::before {{
        content: "記者觀察 ── "; font-weight: 700; color: #f0883e;
    }}

    /* News cards */
    .news-list {{ display: flex; flex-direction: column; gap: 12px; }}
    .news-card {{
        background: #161b22; border: 1px solid #21262d;
        border-radius: 10px; padding: 18px 20px;
        transition: border-color 0.2s;
    }}
    .news-card:hover {{ border-color: #30363d; }}
    .news-card.importance-high {{ border-left: 3px solid #f85149; }}
    .news-card.importance-medium {{ border-left: 3px solid #d29922; }}
    .news-card.importance-low {{ border-left: 3px solid #30363d; }}

    .news-header {{
        display: flex; align-items: center; gap: 8px;
        margin-bottom: 10px; flex-wrap: wrap;
    }}
    .platform-badge {{
        padding: 2px 10px; border-radius: 4px;
        font-size: 0.78em; font-weight: 600;
    }}
    .importance-badge {{
        font-size: 0.78em; color: #8b949e;
    }}
    .source-link {{
        margin-left: auto; font-size: 0.8em; color: #58a6ff;
    }}
    .news-title {{
        font-size: 1.0em; font-weight: 600; color: #e6edf3;
        margin-bottom: 8px; line-height: 1.5;
    }}
    .news-summary {{
        font-size: 0.88em; color: #8b949e; margin-bottom: 10px;
        line-height: 1.6;
    }}
    .reporter-comment {{
        display: flex; gap: 8px; align-items: flex-start;
        background: rgba(88,166,255,0.05); border-radius: 6px;
        padding: 8px 12px;
    }}
    .comment-icon {{ flex-shrink: 0; margin-top: 1px; }}
    .comment-text {{
        font-size: 0.88em; color: #79c0ff; font-style: italic;
        line-height: 1.5;
    }}

    /* Industry Analysis */
    .analysis-box {{
        background: linear-gradient(135deg, #161b22, #1a2030);
        border: 1px solid #21262d; border-radius: 12px; padding: 28px;
        margin-top: 8px;
    }}
    .analysis-headline {{
        font-size: 1.15em; font-weight: 700; color: #58a6ff;
        margin-bottom: 16px; line-height: 1.4;
    }}
    .analysis-content {{
        font-size: 0.95em; color: #c9d1d9; line-height: 1.9;
        white-space: pre-line;
    }}
    .trend-tags {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 20px; }}
    .trend-tag {{
        background: rgba(88,166,255,0.1); color: #58a6ff;
        padding: 4px 12px; border-radius: 20px; font-size: 0.82em;
        border: 1px solid rgba(88,166,255,0.3);
    }}

    /* Footer */
    .footer {{
        text-align: center; margin-top: 50px; padding-top: 20px;
        border-top: 1px solid #21262d; color: #484f58; font-size: 0.82em;
    }}

    @media (max-width: 640px) {{
        body {{ padding: 12px; }}
        .header h1 {{ font-size: 1.5em; }}
        .source-link {{ margin-left: 0; }}
    }}
</style>
</head>
<body>

<div class="header">
    <h1>📰 VoteFlux 產業新聞日報</h1>
    <div class="subtitle">PREDICTION MARKET DAILY BRIEFING</div>
    <div class="date">{TODAY_STR}</div>
</div>

<!-- 平台分佈 -->
<div class="platform-summary">
    {platform_pills}
</div>

<!-- Daily Discovery -->
<h2>🔍 今日平台聚焦</h2>
<div class="discovery">
    <div class="discovery-meta">
        <span class="discovery-badge">DAILY DISCOVERY</span>
        <span class="discovery-name">{dd['name']}</span>
        <span class="discovery-category">{dd.get('category','')}</span>
    </div>
    <div class="discovery-url"><a href="{dd.get('url','')}" target="_blank">{dd.get('url','')}</a></div>
    <p>{dd['description']}</p>
    <div class="reporter-note-box">{dd['reporter_note']}</div>
</div>

<!-- 新聞列表 -->
<h2>📋 今日重要新聞（{len(sorted_news)} 則）</h2>
<div class="news-list">
    {news_cards}
</div>

<!-- 綜合評論 -->
<h2>📝 今日產業綜合評論</h2>
<div class="analysis-box">
    <div class="analysis-headline">"{analysis['headline']}"</div>
    <div class="analysis-content">{analysis['content']}</div>
    <div class="trend-tags">{trend_tags}</div>
</div>

<div class="footer">
    <p>© 2026 VoteFlux Daily Intelligence | Generated by AI | 本報告僅供參考，不構成任何投資建議</p>
</div>

</body>
</html>"""


def hex_to_rgb(hex_color: str) -> str:
    """#rrggbb → 'r,g,b'"""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 6:
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        return f"{r},{g},{b}"
    return "88,166,255"


# ─── 檔案儲存 ────────────────────────────────────────────
def save_html_report(html_content: str) -> str:
    os.makedirs("reports", exist_ok=True)

    filename = f"reports/voteflux-{TODAY_FILE}.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html_content)

    with open("reports/index.html", "w", encoding="utf-8") as f:
        f.write(f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="0; url=voteflux-{TODAY_FILE}.html">
<title>VoteFlux 最新日報</title>
</head><body>
<p>正在跳轉到最新報告... <a href="voteflux-{TODAY_FILE}.html">點此前往</a></p>
</body></html>""")

    print(f"📄 報告已儲存: {filename}")
    return filename


# ─── Telegram 多人推播 ───────────────────────────────────
def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    for chat_id in TELEGRAM_CHAT_IDS:
        body = json.dumps({
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
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
            # fallback 純文字
            print(f"⚠️ HTML 格式失敗，嘗試純文字 (chat_id: {chat_id}): {e}")
            try:
                plain = re.sub(r"<[^>]+>", "", text)
                body2 = json.dumps({"chat_id": chat_id, "text": plain}).encode("utf-8")
                req2 = Request(url, data=body2, headers={"Content-Type": "application/json"}, method="POST")
                with urlopen(req2, timeout=15) as resp2:
                    print(f"✅ 純文字已發送到 {chat_id}")
            except Exception as e2:
                print(f"❌ 完全失敗 (chat_id: {chat_id}): {e2}")


# ─── 主程式 ──────────────────────────────────────────────
def main():
    print("=" * 55)
    print(f"📰 VoteFlux 產業新聞日報 — {TODAY_STR}")
    print("=" * 55)

    # Step 1: 爬取各平台 RSS
    print("\n📡 正在爬取各平台新聞來源...")
    platform_data = []
    for platform in FIXED_PLATFORMS:
        result = fetch_platform_news(platform)
        platform_data.append(result)

    rss_success = sum(1 for p in platform_data if p["source"] == "rss")
    print(f"📊 RSS 爬取成功: {rss_success}/{len(FIXED_PLATFORMS)} 個平台")

    # Step 2: GPT-4o 彙整新聞 + 產生報告資料
    print("\n🤖 正在用 GPT-4o 彙整新聞並產生報告資料...")
    try:
        report_data = generate_report_data(platform_data)
        news_count = len(report_data.get("news_items", []))
        print(f"✅ JSON 解析成功，共 {news_count} 則新聞")
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        print(f"❌ JSON 解析失敗: {e}")
        send_telegram(f"⚠️ <b>VoteFlux 產業新聞日報 — {TODAY_STR}</b>\n\n報告產生失敗，請手動檢查 Action log。")
        return

    # Step 3: 組裝 HTML
    print("\n🔨 正在組裝 HTML 報告...")
    html_content = build_html(report_data)
    save_html_report(html_content)

    # Step 4: 推播到 Telegram
    news_count = len(report_data.get("news_items", []))
    discovery_name = report_data.get("daily_discovery", {}).get("name", "")
    report_url = f"{GITHUB_PAGES_URL}/voteflux-{TODAY_FILE}.html"

    message = (
        f"📰 <b>VoteFlux 產業新聞日報 — {TODAY_STR}</b>\n\n"
        f"今日彙整 <b>{news_count} 則</b>重要新聞\n"
        f"🔍 今日聚焦：<b>{discovery_name}</b>\n\n"
        f"🔗 <a href=\"{report_url}\">📖 查看完整報告</a>"
    )

    print("\n📤 正在推播到 Telegram...")
    send_telegram(message)

    print("\n🎉 VoteFlux 產業新聞日報完成！")


if __name__ == "__main__":
    main()

"""
預測市場週報：老司機的真心話

AI 角色：預測市場老司機（十年功力，專門看穿賠率背後的鬼故事）
AI 模型：OpenAI GPT-4o-mini
輸出格式：HTML 報告（GitHub Pages）+ Telegram 推播連結
排程觸發：Cloudflare Workers Cron → GitHub Actions（每週一台灣時間 08:00）

報告內容：
  - 本週大趨勢（The Weekly Vibe）：一句話點破本週市場情緒
  - 跨平台比價地圖（Price Comparison）：同題目跨平台賠率比較，找出划算的一家
  - 社群風向與「鬼故事」（Social Noise）：大戶動向、社群爭議、盤口異常
  - 下週埋伏建議（Veteran's Strategy）：哪邊可進場、哪邊是死路
"""

import os
import json
import re
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request

# ─── 設定 ───────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_IDS = [cid.strip() for cid in os.environ["TELEGRAM_CHAT_ID"].split(",")]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
GITHUB_PAGES_URL = os.environ.get("GITHUB_PAGES_URL", "https://你的帳號.github.io/daily-news-bot")

TW_TZ = timezone(timedelta(hours=8))
TODAY = datetime.now(TW_TZ)
TODAY_STR = TODAY.strftime("%Y/%m/%d (%A)")
TODAY_FILE = TODAY.strftime("%Y-%m-%d")

# 本週範圍（過去 7 天）
WEEK_START = (TODAY - timedelta(days=6)).strftime("%Y/%m/%d")
WEEK_END = TODAY.strftime("%Y/%m/%d")
WEEK_RANGE = f"{WEEK_START} ~ {WEEK_END}"


# ─── OpenAI API 呼叫 ────────────────────────────────────
def call_openai(system_prompt: str, user_prompt: str, model: str = "gpt-4o-mini") -> str:
    """呼叫 OpenAI Chat Completions API。"""
    body = json.dumps({
        "model": model,
        "max_tokens": 3000,
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


# ─── 產生週報內容（JSON）────────────────────────────────
SYSTEM_PROMPT = """你是一位在預測市場（Prediction Market）打滾超過 10 年的老司機。

你的背景：
- 你經歷過 Intrade、PredictIt 到現在的 Polymarket 盛世，什麼大風大浪都見過
- 你不只是個玩家，你還是個「跨平台獵人」，每天掃描全球各地的預測市場，從 Kalshi 到各種剛冒頭的 DeFi 小站都在你守備範圍內
- 你最討厭廢話和官腔，你只看真實數據和大家的錢包反應
- 你說話犀利、大白話、直言不諱，比起新聞，你更看重「錢流向哪裡」

你的任務是每週以「老手週評」的第一人稱視角，撰寫一份《預測市場週報：老司機的真心話》。
所有輸出皆使用繁體中文。你必須以純 JSON 格式回覆，不要輸出任何其他文字。

【人話翻譯規則，必須遵守】
❌ 禁止使用專有術語，一律翻成大白話：
- 「流動性不足」→「沒人玩，買了賣不掉，小心變壁紙」
- 「套利機會」→「這家賣10塊那家賣12塊，兩邊跑穩賺」
- 「深度不夠」→「大單一砸就崩，不適合大戶玩」
- 「OI / Open Interest」→「目前押注總金額」
- 「Slippage」→「下單價和成交價差很多」
- 「做市商」→「幫你找對手盤的中間人」"""


def generate_report_data() -> dict:
    user_prompt = f"""幫我寫這週的預測市場週報《老司機的真心話》。今天是 {TODAY_STR}，週報涵蓋範圍：{WEEK_RANGE}。

內容必須包含以下四大板塊，以 JSON 格式回覆：

1. **weekly_vibe（本週大趨勢）**
   過去 7 天全市場最瘋什麼？是大家都在賭央行降息，還是某場選舉出現大反轉，還是某個 AI 新產品發布？
   - `headline`：一句話點破本週市場情緒（要夠犀利，像在跟老朋友說話）
   - `details`：3~4 條具體觀察，說明資金往哪裡跑、哪個題目最熱、哪個意外冷場
   守備範圍：全球政治/經濟、體育賽事、熱門影劇、科技圈八卦（AI 開發進度等），不限平台不限主題

2. **price_comparison（跨平台比價地圖）**
   掃描 Polymarket、Kalshi、VoteFlux、ForecastEx 等平台，找出同一個題目在不同平台的賠率差異。
   列出 3~4 個比價案例，每個包含：
   - `topic`：題目名稱（用大白話）
   - `comparison`：各平台的賠率或機率（例如「Polymarket 說 65%，Kalshi 說 58%」）
   - `verdict`：老司機建議，哪家划算、有沒有便宜可撿，或是「差太少懶得跑」

3. **social_noise（社群風向與鬼故事）**
   X（Twitter）或 Reddit 上的老玩家在吵什麼？有沒有大戶砸重金、盤口規則漏洞、或是異常的賠率波動？
   列出 2~3 條社群觀察，每條包含：
   - `title`：一句話標題
   - `story`：具體說明發生什麼事，用說故事的方式，不要太正式

4. **veteran_strategy（下週埋伏建議）**
   下週有什麼大事要發生？現在進場哪邊最安全、哪邊是送錢、哪邊是死路？
   列出 3~4 條建議，每條包含：
   - `event`：下週預計發生的事件
   - `signal`：目前市場怎麼看（資金流向、賠率位置）
   - `verdict`：老司機建議，用「可以埋伏」「送錢勿近」「觀望」「死路一條」等直白標籤開頭

只輸出 JSON，結構如下：
{{
  "weekly_vibe": {{
    "headline": "",
    "details": ["", "", ""]
  }},
  "price_comparison": [
    {{"topic": "", "comparison": "", "verdict": ""}}
  ],
  "social_noise": [
    {{"title": "", "story": ""}}
  ],
  "veteran_strategy": [
    {{"event": "", "signal": "", "verdict": ""}}
  ]
}}"""

    raw = call_openai(SYSTEM_PROMPT, user_prompt)

    # 清理 markdown 包裹
    raw = re.sub(r'^```json?\s*\n?', '', raw.strip())
    raw = re.sub(r'\n?```\s*$', '', raw.strip())

    print(f"🔍 [DEBUG] JSON 長度: {len(raw)} 字元")
    print(f"🔍 [DEBUG] 前 300 字:\n{raw[:300]}")

    return json.loads(raw)


# ─── 組裝 HTML ───────────────────────────────────────────
def build_html(data: dict) -> str:
    vibe = data["weekly_vibe"]

    # ── 本週大趨勢 details
    vibe_details_html = "".join(
        f'<div class="vibe-item">📌 {d}</div>' for d in vibe.get("details", [])
    )

    # ── 跨平台比價
    price_html = ""
    for p in data.get("price_comparison", []):
        price_html += f"""<div class="price-card">
            <div class="price-topic">📊 {p['topic']}</div>
            <div class="price-comparison">{p['comparison']}</div>
            <div class="price-verdict">💡 {p['verdict']}</div>
        </div>"""

    # ── 社群風向
    noise_html = ""
    for n in data.get("social_noise", []):
        noise_html += f"""<div class="noise-card">
            <div class="noise-title">🔥 {n['title']}</div>
            <div class="noise-story">{n['story']}</div>
        </div>"""

    # ── 下週埋伏建議
    strategy_html = ""
    for s in data.get("veteran_strategy", []):
        verdict = s['verdict']
        # 根據開頭標籤決定顏色
        if verdict.startswith("可以埋伏"):
            color = "#3fb950"
        elif verdict.startswith("送錢勿近") or verdict.startswith("死路一條"):
            color = "#f85149"
        else:
            color = "#d29922"
        strategy_html += f"""<div class="strategy-card">
            <div class="strategy-event">📅 {s['event']}</div>
            <div class="strategy-signal">📡 {s['signal']}</div>
            <div class="strategy-verdict" style="border-left-color:{color}">⚔️ {verdict}</div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>預測市場週報：老司機的真心話 — {WEEK_RANGE}</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        background: #0d1117; color: #c9d1d9;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        line-height: 1.7; padding: 20px; max-width: 960px; margin: 0 auto;
    }}
    h1 {{ color: #58a6ff; font-size: 1.9em; margin-bottom: 5px; }}
    h2 {{
        color: #58a6ff; font-size: 1.35em; margin: 40px 0 15px;
        padding-bottom: 8px; border-bottom: 2px solid #21262d;
    }}

    .header {{
        text-align: center; padding: 30px 0;
        border-bottom: 3px solid #8957e5; margin-bottom: 30px;
    }}
    .header .week-range {{ color: #8b949e; font-size: 1em; margin-top: 8px; }}
    .header .subtitle {{ color: #8957e5; font-size: 0.9em; margin-top: 5px; letter-spacing: 2px; }}

    /* Weekly Vibe */
    .vibe-box {{
        background: linear-gradient(135deg, #161b22, #1c2333);
        border: 1px solid #8957e5; border-radius: 12px;
        padding: 25px; margin: 20px 0;
    }}
    .vibe-headline {{
        font-size: 1.3em; font-weight: bold; color: #e6edf3;
        margin-bottom: 18px; padding-bottom: 12px;
        border-bottom: 1px solid #21262d;
        font-style: italic;
    }}
    .vibe-headline::before {{ content: "🎯 "; }}
    .vibe-item {{
        padding: 10px 0; border-bottom: 1px solid #21262d;
        font-size: 0.95em; color: #c9d1d9;
    }}
    .vibe-item:last-child {{ border-bottom: none; }}

    /* Price Comparison */
    .price-grid {{
        display: grid; grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
        gap: 15px; margin: 15px 0;
    }}
    .price-card {{
        background: #161b22; border: 1px solid #21262d;
        border-radius: 10px; padding: 18px;
    }}
    .price-topic {{
        font-weight: bold; color: #79c0ff;
        font-size: 1em; margin-bottom: 10px;
    }}
    .price-comparison {{
        color: #c9d1d9; font-size: 0.9em; margin-bottom: 10px;
        padding: 8px 12px; background: #0d1117; border-radius: 6px;
    }}
    .price-verdict {{
        font-size: 0.9em; color: #f0883e; font-style: italic;
    }}

    /* Social Noise */
    .noise-card {{
        background: #161b22; border-left: 4px solid #f85149;
        border-radius: 0 10px 10px 0; padding: 18px 20px; margin: 12px 0;
    }}
    .noise-title {{
        font-weight: bold; color: #ffa198; margin-bottom: 8px; font-size: 1em;
    }}
    .noise-story {{ font-size: 0.93em; color: #c9d1d9; }}

    /* Strategy */
    .strategy-card {{
        background: #161b22; border: 1px solid #21262d;
        border-radius: 10px; padding: 18px; margin: 12px 0;
    }}
    .strategy-event {{
        font-weight: bold; color: #79c0ff; margin-bottom: 8px;
    }}
    .strategy-signal {{
        font-size: 0.9em; color: #8b949e; margin-bottom: 10px;
    }}
    .strategy-verdict {{
        font-size: 0.95em; color: #e6edf3; font-weight: bold;
        padding: 8px 12px; border-left: 4px solid #d29922;
        background: rgba(255,255,255,0.03); border-radius: 0 6px 6px 0;
    }}

    /* Footer */
    .footer {{
        text-align: center; margin-top: 50px; padding-top: 20px;
        border-top: 1px solid #21262d; color: #484f58; font-size: 0.85em;
    }}

    @media (max-width: 768px) {{
        body {{ padding: 12px; }}
        .price-grid {{ grid-template-columns: 1fr; }}
        h1 {{ font-size: 1.5em; }}
    }}
</style>
</head>
<body>

<div class="header">
    <h1>🎰 預測市場週報</h1>
    <div class="subtitle">老司機的真心話</div>
    <div class="week-range">📅 {WEEK_RANGE} &nbsp;｜&nbsp; 發布於 {TODAY_STR}</div>
</div>

<!-- 本週大趨勢 -->
<h2>🌊 本週大趨勢（The Weekly Vibe）</h2>
<div class="vibe-box">
    <div class="vibe-headline">{vibe['headline']}</div>
    {vibe_details_html}
</div>

<!-- 跨平台比價地圖 -->
<h2>🗺️ 跨平台比價地圖（Price Comparison）</h2>
<div class="price-grid">
    {price_html}
</div>

<!-- 社群風向與鬼故事 -->
<h2>👻 社群風向與「鬼故事」（Social Noise）</h2>
{noise_html}

<!-- 下週埋伏建議 -->
<h2>⚔️ 下週埋伏建議（Veteran's Strategy）</h2>
{strategy_html}

<div class="footer">
    <p>© 2026 VoteFlux Weekly Intelligence | Generated by AI | 本報告僅供參考，不構成任何投資建議</p>
</div>

</body>
</html>"""


# ─── 檔案儲存 ────────────────────────────────────────────
def save_html_report(html_content: str) -> str:
    os.makedirs("reports", exist_ok=True)

    filename = f"reports/weekly-{TODAY_FILE}.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html_content)

    with open("reports/weekly-latest.html", "w", encoding="utf-8") as f:
        f.write(f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="0; url=weekly-{TODAY_FILE}.html">
<title>預測市場週報 最新一期</title>
</head><body>
<p>正在跳轉到最新週報... <a href="weekly-{TODAY_FILE}.html">點此前往</a></p>
</body></html>""")

    print(f"📄 週報已儲存: {filename}")
    return filename


# ─── Telegram 發送 ───────────────────────────────────────
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
                    raise RuntimeError(f"Telegram API 錯誤: {result}")
            print(f"✅ 訊息已發送到 {chat_id}")
        except Exception as e:
            print(f"⚠️ Telegram HTML 發送失敗 (chat_id: {chat_id}): {e}")
            plain = re.sub(r'<a href="([^"]+)">[^<]*</a>', r'\1', text)
            plain = re.sub(r'<[^>]+>', '', plain)
            body2 = json.dumps({"chat_id": chat_id, "text": plain}).encode("utf-8")
            req2 = Request(url, data=body2, headers={"Content-Type": "application/json"}, method="POST")
            with urlopen(req2, timeout=15) as resp2:
                pass
            print(f"✅ 訊息已發送到 {chat_id}（純文字 fallback，含 URL）")


# ─── 主程式 ──────────────────────────────────────────────
def main():
    print("=" * 50)
    print(f"🎰 預測市場週報 — {WEEK_RANGE}")
    print("=" * 50)

    # Step 1: 產生週報資料（JSON）
    print("\n📝 正在產生週報資料（GPT-4o-mini → JSON）...")
    try:
        report_data = generate_report_data()
        print("✅ JSON 解析成功")
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        print(f"❌ JSON 解析失敗: {e}")
        send_telegram(f"⚠️ <b>預測市場週報 — {WEEK_RANGE}</b>\n\n週報產生失敗，請手動檢查 Action log。")
        return

    # Step 2: 組裝 HTML
    print("\n🔨 正在組裝 HTML 週報...")
    html_content = build_html(report_data)
    save_html_report(html_content)

    # Step 3: 推播連結到 Telegram
    report_url = f"{GITHUB_PAGES_URL}/weekly-{TODAY_FILE}.html"
    message = (
        f"🎰 <b>預測市場週報：老司機的真心話</b>\n"
        f"📅 {WEEK_RANGE}\n\n"
        f"🔗 <a href=\"{report_url}\">📖 查看完整週報</a>"
    )

    print("\n📤 正在推播到 Telegram...")
    send_telegram(message)

    print("\n🎉 預測市場週報完成！")


if __name__ == "__main__":
    main()

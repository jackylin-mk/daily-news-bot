"""
預測市場週報：老司機的真心話
AI 模型：OpenAI gpt-4o-mini + web_search_preview tool（真實抓取當週新聞）
輸出格式：HTML 報告（GitHub Pages）+ Telegram 推播連結
排程觸發：Cloudflare Workers Cron → GitHub Actions（每週一台灣時間 08:00）

方案 A+B：
  A - Prompt 強制要求「只寫真實存在的市場，不確定就不寫，不能捏造」
  B - 使用 OpenAI Responses API + web_search_preview tool 真實抓取當週新聞
"""

import os
import json
import re
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request

# ─── 設定 ─────────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_IDS  = [cid.strip() for cid in os.environ["TELEGRAM_CHAT_ID"].split(",")]
OPENAI_API_KEY     = os.environ["OPENAI_API_KEY"]
GITHUB_PAGES_URL   = os.environ.get("GITHUB_PAGES_URL", "https://你的帳號.github.io/daily-news-bot")

TW_TZ      = timezone(timedelta(hours=8))
TODAY      = datetime.now(TW_TZ)
TODAY_STR  = TODAY.strftime("%Y/%m/%d (%A)")
TODAY_FILE = TODAY.strftime("%Y-%m-%d")

WEEK_START = (TODAY - timedelta(days=6)).strftime("%Y/%m/%d")
WEEK_END   = TODAY.strftime("%Y/%m/%d")
WEEK_RANGE = f"{WEEK_START} ~ {WEEK_END}"

# ─── OpenAI Responses API（含 web_search_preview tool）───────────────────────
def call_openai_with_search(system_prompt: str, user_prompt: str) -> str:
    """
    呼叫 OpenAI Responses API，附帶 web_search_preview tool。
    OpenAI 會自動搜尋後再回覆。
    """
    body = json.dumps({
        "model": "gpt-4o-mini",
        "tools": [{"type": "web_search_preview"}],
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
    }).encode("utf-8")

    req = Request(
        "https://api.openai.com/v1/responses",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}",
        },
        method="POST",
    )

    with urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())

    # 從 output 陣列中取 message 類型的文字
    for item in data.get("output", []):
        if item.get("type") == "message":
            for block in item.get("content", []):
                if block.get("type") == "output_text":
                    return block["text"]

    raise RuntimeError(f"OpenAI Responses API 回傳格式異常: {json.dumps(data)[:500]}")


# ─── System Prompt ────────────────────────────────────────────────────────────
SYSTEM_PROMPT = f"""你是一位在預測市場（Prediction Market）打滾超過 10 年的老司機。

你的背景：
- 你經歷過 Intrade、PredictIt 到現在的 Polymarket 盛世，什麼大風大浪都見過
- 你是「跨平台獵人」，每天掃描全球各地的預測市場，從 Kalshi 到各種 DeFi 小站都在你守備範圍內
- 你最討厭廢話和官腔，你只看真實數據和大家的錢包反應
- 你說話犀利、大白話、直言不諱

【最重要的規則 - 必須嚴格遵守】
✅ 你有 web_search 工具，撰寫前必須先搜尋本週真實動態
✅ 只寫「本週 {WEEK_RANGE} 真實存在的市場事件」
✅ 跨平台比價必須搜尋確認各平台當前賠率後才能寫
✅ 只寫「目前仍在交易中」的市場，不寫已結算的歷史市場
❌ 絕對禁止捏造、推測、或使用訓練資料中的舊資訊填充
❌ 如果搜尋後找不到確定的資料，該條目寫「本週查無可信資料，略過」

【搜尋策略（照順序執行）】
1. 搜尋「Polymarket trending markets {WEEK_END}」掌握本週熱門市場
2. 搜尋「Kalshi prediction market news this week」找 Kalshi 動態
3. 搜尋具體題目確認各平台的當前賠率（用於比價地圖）
4. 搜尋「prediction market social reddit this week」找社群動態

【人話翻譯規則】
- 「流動性不足」→「沒人玩，買了賣不掉，小心變壁紙」
- 「套利機會」→「這家賣10塊那家賣12塊，兩邊跑穩賺」
- 「深度不夠」→「大單一砸就崩，不適合大戶玩」

所有輸出皆使用繁體中文。搜尋完成後，最終以純 JSON 格式回覆，不要輸出任何其他文字。"""


# ─── 產生週報資料 ──────────────────────────────────────────────────────────────
def generate_report_data() -> dict:
    user_prompt = f"""今天是 {TODAY_STR}，請幫我撰寫這週的預測市場週報《老司機的真心話》。
週報涵蓋範圍：{WEEK_RANGE}

請先使用 web_search 工具搜尋本週真實動態，確認資料後再撰寫 JSON。

嚴格規定：
- 所有事件必須發生在 {WEEK_RANGE} 內
- 比價地圖只放「現在仍在交易中的市場」，不放已結算的市場
- 找不到確定資料的欄位，直接寫「本週查無可信資料，略過」

輸出 JSON 結構：
{{
  "weekly_vibe": {{
    "headline": "一句話點破本週市場情緒（必須基於搜尋結果）",
    "details": ["具體觀察1", "具體觀察2", "具體觀察3"]
  }},
  "price_comparison": [
    {{"topic": "題目（必須是當前開盤中的市場）", "comparison": "各平台真實賠率", "verdict": "老司機建議"}}
  ],
  "social_noise": [
    {{"title": "標題", "story": "具體說明（必須是本週真實發生的事）"}}
  ],
  "veteran_strategy": [
    {{"event": "下週預計發生的事件", "signal": "目前市場怎麼看", "verdict": "可以埋伏／送錢勿近／觀望／死路一條"}}
  ]
}}

只輸出 JSON，不要有任何其他文字。"""

    raw = call_openai_with_search(SYSTEM_PROMPT, user_prompt)

    # 清理 markdown 包裹
    raw = raw.strip()
    raw = re.sub(r'^```json?\s*\n?', '', raw)
    raw = re.sub(r'\n?```\s*$', '', raw)

    print(f"🔍 [DEBUG] JSON 長度: {len(raw)} 字元")
    print(f"🔍 [DEBUG] 前 300 字:\n{raw[:300]}")

    return json.loads(raw)


# ─── 組裝 HTML ─────────────────────────────────────────────────────────────────
def build_html(data: dict) -> str:
    vibe = data["weekly_vibe"]

    vibe_details_html = "".join(
        f'<div class="vibe-item">📌 {d}</div>'
        for d in vibe.get("details", [])
    )

    price_html = ""
    for p in data.get("price_comparison", []):
        price_html += f"""<div class="price-card">
          <div class="price-topic">📊 {p['topic']}</div>
          <div class="price-comparison">{p['comparison']}</div>
          <div class="price-verdict">💡 {p['verdict']}</div>
        </div>"""

    noise_html = ""
    for n in data.get("social_noise", []):
        noise_html += f"""<div class="noise-card">
          <div class="noise-title">🔥 {n['title']}</div>
          <div class="noise-story">{n['story']}</div>
        </div>"""

    strategy_html = ""
    for s in data.get("veteran_strategy", []):
        verdict = s['verdict']
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
    body {{ background: #0d1117; color: #c9d1d9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; line-height: 1.7; padding: 20px; max-width: 960px; margin: 0 auto; }}
    h1 {{ color: #58a6ff; font-size: 1.9em; margin-bottom: 5px; }}
    h2 {{ color: #58a6ff; font-size: 1.35em; margin: 40px 0 15px; padding-bottom: 8px; border-bottom: 2px solid #21262d; }}
    .header {{ text-align: center; padding: 30px 0; border-bottom: 3px solid #8957e5; margin-bottom: 30px; }}
    .header .week-range {{ color: #8b949e; font-size: 1em; margin-top: 8px; }}
    .header .subtitle {{ color: #8957e5; font-size: 0.9em; margin-top: 5px; letter-spacing: 2px; }}
    .search-badge {{ display: inline-block; background: #1c2333; border: 1px solid #3fb950; color: #3fb950; font-size: 0.75em; padding: 3px 10px; border-radius: 20px; margin-top: 10px; }}
    .vibe-box {{ background: linear-gradient(135deg, #161b22, #1c2333); border: 1px solid #8957e5; border-radius: 12px; padding: 25px; margin: 20px 0; }}
    .vibe-headline {{ font-size: 1.3em; font-weight: bold; color: #e6edf3; margin-bottom: 18px; padding-bottom: 12px; border-bottom: 1px solid #21262d; font-style: italic; }}
    .vibe-headline::before {{ content: "🎯 "; }}
    .vibe-item {{ padding: 10px 0; border-bottom: 1px solid #21262d; font-size: 0.95em; color: #c9d1d9; }}
    .vibe-item:last-child {{ border-bottom: none; }}
    .price-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(420px, 1fr)); gap: 15px; margin: 15px 0; }}
    .price-card {{ background: #161b22; border: 1px solid #21262d; border-radius: 10px; padding: 18px; }}
    .price-topic {{ font-weight: bold; color: #79c0ff; font-size: 1em; margin-bottom: 10px; }}
    .price-comparison {{ color: #c9d1d9; font-size: 0.9em; margin-bottom: 10px; padding: 8px 12px; background: #0d1117; border-radius: 6px; }}
    .price-verdict {{ font-size: 0.9em; color: #f0883e; font-style: italic; }}
    .noise-card {{ background: #161b22; border-left: 4px solid #f85149; border-radius: 0 10px 10px 0; padding: 18px 20px; margin: 12px 0; }}
    .noise-title {{ font-weight: bold; color: #ffa198; margin-bottom: 8px; font-size: 1em; }}
    .noise-story {{ font-size: 0.93em; color: #c9d1d9; }}
    .strategy-card {{ background: #161b22; border: 1px solid #21262d; border-radius: 10px; padding: 18px; margin: 12px 0; }}
    .strategy-event {{ font-weight: bold; color: #79c0ff; margin-bottom: 8px; }}
    .strategy-signal {{ font-size: 0.9em; color: #8b949e; margin-bottom: 10px; }}
    .strategy-verdict {{ font-size: 0.95em; color: #e6edf3; font-weight: bold; padding: 8px 12px; border-left: 4px solid #d29922; background: rgba(255,255,255,0.03); border-radius: 0 6px 6px 0; }}
    .footer {{ text-align: center; margin-top: 50px; padding-top: 20px; border-top: 1px solid #21262d; color: #484f58; font-size: 0.85em; }}
    @media (max-width: 768px) {{ body {{ padding: 12px; }} .price-grid {{ grid-template-columns: 1fr; }} h1 {{ font-size: 1.5em; }} }}
  </style>
</head>
<body>
  <div class="header">
    <h1>🎰 預測市場週報</h1>
    <div class="subtitle">老司機的真心話</div>
    <div class="week-range">📅 {WEEK_RANGE} &nbsp;｜&nbsp; 發布於 {TODAY_STR}</div>
    <div class="search-badge">✅ 本期由 AI 即時搜尋真實市場資料生成</div>
  </div>

  <h2>🌊 本週大趨勢（The Weekly Vibe）</h2>
  <div class="vibe-box">
    <div class="vibe-headline">{vibe['headline']}</div>
    {vibe_details_html}
  </div>

  <h2>🗺️ 跨平台比價地圖（Price Comparison）</h2>
  <div class="price-grid">{price_html}</div>

  <h2>👻 社群風向與「鬼故事」（Social Noise）</h2>
  {noise_html}

  <h2>⚔️ 下週埋伏建議（Veteran's Strategy）</h2>
  {strategy_html}

  <div class="footer">
    <p>© 2026 VoteFlux Weekly Intelligence | Powered by GPT-4o-mini + Web Search | 本報告僅供參考，不構成任何投資建議</p>
  </div>
</body>
</html>"""


# ─── 儲存 HTML ─────────────────────────────────────────────────────────────────
def save_html_report(html_content: str) -> str:
    os.makedirs("reports", exist_ok=True)
    filename = f"reports/weekly-{TODAY_FILE}.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html_content)
    with open("reports/weekly-latest.html", "w", encoding="utf-8") as f:
        f.write(f"""<!DOCTYPE html><html><head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="0; url=weekly-{TODAY_FILE}.html">
<title>預測市場週報 最新一期</title>
</head><body><p>正在跳轉... <a href="weekly-{TODAY_FILE}.html">點此前往</a></p></body></html>""")
    print(f"📄 週報已儲存: {filename}")
    return filename


# ─── Telegram ──────────────────────────────────────────────────────────────────
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
            print(f"⚠️ Telegram HTML 發送失敗 ({chat_id}): {e}")
            plain = re.sub(r'<a href="([^"]+)">[^<]*</a>', r'\1', text)
            plain = re.sub(r'<[^>]+>', '', plain)
            body2 = json.dumps({"chat_id": chat_id, "text": plain}).encode("utf-8")
            req2 = Request(url, data=body2, headers={"Content-Type": "application/json"}, method="POST")
            with urlopen(req2, timeout=15):
                pass
            print(f"✅ 訊息已發送到 {chat_id}（純文字 fallback）")


# ─── 主程式 ────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print(f"🎰 預測市場週報 — {WEEK_RANGE}")
    print("=" * 60)

    print("\n🔍 正在使用 GPT-4o-mini + Web Search 搜尋本週真實市場資料...")
    try:
        report_data = generate_report_data()
        print("✅ JSON 解析成功")
    except Exception as e:
        print(f"❌ 週報產生失敗: {e}")
        send_telegram(f"⚠️ <b>預測市場週報 — {WEEK_RANGE}</b>\n\n週報產生失敗，請手動檢查 Action log。")
        return

    print("\n🔨 正在組裝 HTML 週報...")
    html_content = build_html(report_data)
    save_html_report(html_content)

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

"""
VoteFlux 每日戰報
- 使用 OpenAI API (GPT-4o) 分析預測市場（輸出 JSON）
- Python 將 JSON 組裝成完整 HTML 報告
- 部署到 GitHub Pages，推播連結到 Telegram
"""

import os
import json
import re
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request

# ─── 設定 ───────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
GITHUB_PAGES_URL = os.environ.get("GITHUB_PAGES_URL", "https://你的帳號.github.io/daily-news-bot")

TW_TZ = timezone(timedelta(hours=8))
TODAY = datetime.now(TW_TZ)
TODAY_STR = TODAY.strftime("%Y/%m/%d (%A)")
TODAY_FILE = TODAY.strftime("%Y-%m-%d")


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


# ─── 產生報告內容（JSON）─────────────────────────────────
SYSTEM_PROMPT = """你是一位具備 10 年經驗的資深預測市場分析師兼金融科技戰略顧問。
你的風格硬核、犀利、注重數據，並對 Web3 與傳統金融市場有極深洞見。
你必須以 JSON 格式回覆，不要輸出任何其他文字。所有內容使用繁體中文。"""


def generate_report_data() -> dict:
    user_prompt = f"""現在是 {TODAY_STR}，請執行每日市場研究報告。

請以嚴格的 JSON 格式回覆（不要加 markdown 代碼塊），結構如下：

{{
  "daily_discovery": {{
    "name": "平台名稱",
    "url": "網址",
    "description": "平台簡述（2-3句）",
    "expert_comment": "資深分析師點評（2-3句）"
  }},
  "competitors": [
    {{
      "name": "平台名稱",
      "liquidity_analysis": "流動性分析（1-2句）",
      "fee_analysis": "費率滑點分析（1-2句）",
      "speed_analysis": "反應速度分析（1-2句）"
    }}
  ],
  "service_ratings": [
    {{
      "name": "平台名稱",
      "live_chat": "有/無（附說明）",
      "messaging_app": "有/無（附說明）",
      "email_support": "有/無（附說明）"
    }}
  ],
  "action_plan": [
    "建議1：具體可執行的戰術建議",
    "建議2：...",
    "建議3：...",
    "建議4：...",
    "建議5：..."
  ],
  "market_topics": [
    {{
      "market": "印度",
      "topics": ["題目1", "題目2"]
    }},
    {{
      "market": "孟加拉",
      "topics": ["題目1", "題目2"]
    }},
    {{
      "market": "越南",
      "topics": ["題目1", "題目2"]
    }},
    {{
      "market": "馬來西亞",
      "topics": ["題目1", "題目2"]
    }},
    {{
      "market": "菲律賓",
      "topics": ["題目1", "題目2"]
    }},
    {{
      "market": "泰國",
      "topics": ["題目1", "題目2"]
    }}
  ]
}}

competitors 必須包含 6 個對象：VoteFlux, Kalshi, Hyperliquid, Predict.fun, Polymarket, 以及 daily_discovery 中的隨機競品。
service_ratings 也必須包含同樣 6 個對象。
action_plan 要結合 Kalshi（合規）、Hyperliquid（Outcome Trading）、Predict.fun（DeFi 生息）三大邏輯為 VoteFlux 提供建議。

只輸出 JSON，不要輸出任何其他文字。"""

    raw = call_openai(SYSTEM_PROMPT, user_prompt)

    # 清理 markdown 包裹
    raw = re.sub(r'^```json?\s*\n?', '', raw.strip())
    raw = re.sub(r'\n?```\s*$', '', raw.strip())

    print(f"🔍 [DEBUG] JSON 長度: {len(raw)} 字元")
    print(f"🔍 [DEBUG] 前 300 字:\n{raw[:300]}")

    return json.loads(raw)


# ─── 組裝 HTML ───────────────────────────────────────────
def build_html(data: dict) -> str:
    dd = data["daily_discovery"]

    # 競品分析表格
    comp_rows = ""
    for c in data["competitors"]:
        comp_rows += f"""<tr>
            <td><b>{c['name']}</b></td>
            <td>{c['liquidity_analysis']}</td>
            <td>{c['fee_analysis']}</td>
            <td>{c['speed_analysis']}</td>
        </tr>"""

    # 客服評分表格
    svc_rows = ""
    for s in data["service_ratings"]:
        svc_rows += f"""<tr>
            <td><b>{s['name']}</b></td>
            <td>{s['live_chat']}</td>
            <td>{s['messaging_app']}</td>
            <td>{s['email_support']}</td>
        </tr>"""

    # 行動建議
    actions_html = ""
    for i, a in enumerate(data["action_plan"], 1):
        actions_html += f'<div class="action-item">🎯 <b>建議 {i}：</b>{a}</div>\n'

    # 市場題目
    markets_html = ""
    flags = {"印度": "🇮🇳", "孟加拉": "🇧🇩", "越南": "🇻🇳", "馬來西亞": "🇲🇾", "菲律賓": "🇵🇭", "泰國": "🇹🇭"}
    for m in data["market_topics"]:
        flag = flags.get(m["market"], "🌏")
        topics = "".join(f"<li>{t}</li>" for t in m["topics"])
        markets_html += f"""<div class="market-card">
            <h3>{flag} {m['market']}</h3>
            <ul>{topics}</ul>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VoteFlux 每日戰報 — {TODAY_STR}</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        background: #0d1117; color: #c9d1d9;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        line-height: 1.6; padding: 20px; max-width: 1200px; margin: 0 auto;
    }}
    h1 {{ color: #58a6ff; font-size: 2em; margin-bottom: 5px; }}
    h2 {{
        color: #58a6ff; font-size: 1.4em; margin: 30px 0 15px;
        padding-bottom: 8px; border-bottom: 2px solid #21262d;
    }}
    h3 {{ color: #79c0ff; font-size: 1.1em; margin-bottom: 8px; }}
    .header {{
        text-align: center; padding: 30px 0;
        border-bottom: 3px solid #f0883e;
        margin-bottom: 30px;
    }}
    .header .date {{ color: #8b949e; font-size: 1.1em; margin-top: 8px; }}
    .header .subtitle {{ color: #f0883e; font-size: 0.9em; margin-top: 5px; }}

    /* Discovery */
    .discovery {{
        background: linear-gradient(135deg, #161b22, #1c2333);
        border: 1px solid #f0883e; border-radius: 10px;
        padding: 25px; margin: 20px 0;
    }}
    .discovery .badge {{
        display: inline-block; background: #f0883e; color: #0d1117;
        padding: 3px 12px; border-radius: 20px; font-weight: bold;
        font-size: 0.85em; margin-bottom: 15px;
    }}
    .discovery .platform-name {{ color: #f0883e; font-size: 1.3em; font-weight: bold; }}
    .discovery .url {{ color: #58a6ff; font-size: 0.9em; }}
    .discovery p {{ margin-top: 10px; }}
    .discovery .comment {{
        margin-top: 15px; padding-top: 15px;
        border-top: 1px solid #30363d; font-style: italic; color: #8b949e;
    }}

    /* Tables */
    table {{
        width: 100%; border-collapse: collapse;
        background: #161b22; border-radius: 8px; overflow: hidden;
        margin: 15px 0;
    }}
    th {{
        background: #21262d; color: #58a6ff;
        padding: 12px 15px; text-align: left;
        font-weight: 600; font-size: 0.9em;
    }}
    td {{ padding: 12px 15px; border-bottom: 1px solid #21262d; font-size: 0.9em; }}
    tr:hover td {{ background: #1c2333; }}
    tr:last-child td {{ border-bottom: none; }}

    /* Action Plan */
    .action-item {{
        background: #161b22; border-left: 4px solid #3fb950;
        padding: 15px 20px; margin: 10px 0; border-radius: 0 8px 8px 0;
    }}

    /* Market Cards */
    .markets-grid {{
        display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
        gap: 15px; margin: 15px 0;
    }}
    .market-card {{
        background: #161b22; border: 1px solid #21262d;
        border-radius: 8px; padding: 20px;
    }}
    .market-card ul {{ margin-top: 10px; padding-left: 20px; }}
    .market-card li {{ margin: 8px 0; color: #c9d1d9; }}

    /* Footer */
    .footer {{
        text-align: center; margin-top: 40px; padding-top: 20px;
        border-top: 1px solid #21262d; color: #484f58; font-size: 0.85em;
    }}
</style>
</head>
<body>

<div class="header">
    <h1>🤖 VoteFlux 每日戰報</h1>
    <div class="date">{TODAY_STR}</div>
    <div class="subtitle">Prediction Market Intelligence Report</div>
</div>

<!-- DAILY DISCOVERY -->
<h2>🔍 DAILY DISCOVERY</h2>
<div class="discovery">
    <span class="badge">TODAY'S FIND</span>
    <div class="platform-name">{dd['name']}</div>
    <div class="url">{dd.get('url', '')}</div>
    <p>{dd['description']}</p>
    <div class="comment">💬 資深分析師點評：{dd['expert_comment']}</div>
</div>

<!-- 競品分析 -->
<h2>📊 全球競品深度分析</h2>
<table>
    <thead>
        <tr>
            <th>平台</th>
            <th>流動性分析</th>
            <th>費率 / 滑點</th>
            <th>反應速度</th>
        </tr>
    </thead>
    <tbody>
        {comp_rows}
    </tbody>
</table>

<!-- 客服評分 -->
<h2>🎧 客服功能評分表</h2>
<table>
    <thead>
        <tr>
            <th>平台</th>
            <th>網站即時對話框</th>
            <th>即時通訊軟體客服</th>
            <th>非即時客服 (Email)</th>
        </tr>
    </thead>
    <tbody>
        {svc_rows}
    </tbody>
</table>

<!-- 戰略行動建議 -->
<h2>⚔️ 戰略行動建議 (Action Plan)</h2>
{actions_html}

<!-- 目標市場預測題目 -->
<h2>🌏 目標市場預測題目</h2>
<div class="markets-grid">
    {markets_html}
</div>

<div class="footer">
    <p>© 2026 VoteFlux Daily Intelligence Report | Generated by AI</p>
</div>

</body>
</html>"""


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
<title>VoteFlux 最新戰報</title>
</head><body>
<p>正在跳轉到最新報告... <a href="voteflux-{TODAY_FILE}.html">點此前往</a></p>
</body></html>""")

    print(f"📄 報告已儲存: {filename}")
    return filename


# ─── Telegram 發送 ───────────────────────────────────────
def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    body = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
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
        print("✅ Telegram 訊息已發送！")
    except Exception as e:
        print(f"⚠️ Telegram HTML 發送失敗: {e}")
        plain = re.sub(r'<[^>]+>', '', text)
        body2 = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": plain}).encode("utf-8")
        req2 = Request(url, data=body2, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(req2, timeout=15) as resp2:
            pass
        print("✅ Telegram 訊息已發送（純文字 fallback）！")


# ─── 主程式 ──────────────────────────────────────────────
def main():
    print("=" * 50)
    print(f"🤖 VoteFlux 每日戰報 — {TODAY_STR}")
    print("=" * 50)

    # Step 1: 用 GPT-4o 產生報告資料（JSON）
    print("\n📝 正在產生報告資料（GPT-4o → JSON）...")
    try:
        report_data = generate_report_data()
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        print(f"❌ JSON 解析失敗: {e}")
        send_telegram(f"⚠️ <b>VoteFlux 每日戰報 — {TODAY_STR}</b>\n\n報告 JSON 解析失敗，請手動檢查。")
        return

    # Step 2: 組裝 HTML
    print("\n🔨 正在組裝 HTML 報告...")
    html_content = build_html(report_data)
    save_html_report(html_content)

    # Step 3: 推播連結到 Telegram
    report_url = f"{GITHUB_PAGES_URL}/voteflux-{TODAY_FILE}.html"
    message = f"🤖 <b>VoteFlux 每日戰報 — {TODAY_STR}</b>\n\n🔗 <a href=\"{report_url}\">📖 查看完整報告</a>"

    print("\n📤 正在推播到 Telegram...")
    send_telegram(message)

    print("\n🎉 VoteFlux 每日戰報完成！")


if __name__ == "__main__":
    main()

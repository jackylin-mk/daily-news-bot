"""
VoteFlux 競品週報
AI 角色：預測市場資深玩家（10 年老手），風格直接犀利
AI 模型：OpenAI GPT-4o-mini
輸出格式：HTML 報告（GitHub Pages）+ Telegram 推播連結
排程觸發：Cloudflare Workers Cron → GitHub Actions（每週一台灣時間 08:00）
報告內容：
  - WEEKLY DISCOVERY：三步驟競爭選拔本週最值得關注的競品
  - 競品評分總覽：5 大固定平台 + WEEKLY DISCOVERY × 6 固定維度（1-10 分顏色標示）
  - 各平台詳細點評：每個維度分數 + 老玩家犀利評語
  - 本週觀察與碎碎念：第一人稱市場觀察
  - 給 VoteFlux 的建議：實際可執行的改進方向
固定分析維度：流動性深度 · 費用結構 · 出入金便利性 · 盤口豐富度 · 監管合規 · 介面體驗
固定分析平台：Polymarket · Kalshi · VoteFlux · YesNoMarkets · WEEKLY DISCOVERY
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

TW_TZ    = timezone(timedelta(hours=8))
NOW      = datetime.now(TW_TZ)
NOW_STR  = NOW.strftime("%Y/%m/%d (%A)")
NOW_FILE = NOW.strftime("%Y-%m-%d")

# ─── OpenAI API 呼叫 ──────────────────────────────────────────────────────────
def call_openai(system_prompt: str, user_prompt: str, model: str = "gpt-4o-mini") -> str:
    body = json.dumps({
        "model": model,
        "max_tokens": 4096,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
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


# ─── System Prompt ────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """你是一位在預測市場（Prediction Market）打滾超過 10 年的資深玩家。

你的背景：
- 你從 Intrade 時代就開始玩，經歷過 PredictIt、Augur、到現在的 Polymarket 世代
- 你每天在多個平台之間套利，對各平台的流動性、費用結構、出入金速度、盤口深度、介面體驗瞭若指掌
- 你同時熟悉傳統合規路線（如 Kalshi 的 CFTC 監管）和 DeFi/Web3 鏈上預測市場
- 你說話直接、犀利、不廢話，用數據和親身經驗說話
- 你對爛平台毫不留情，對好平台也會指出它的隱患

【YesNoMarkets 背景資訊】
YesNoMarkets（yesnomarkets.com）是一個整合 Polymarket 和 Kalshi 訂單簿的跨平台工具，
提供即時跨平台賠率比較、套利機會識別、以及聰明錢追蹤功能。
它不是獨立的預測市場，而是「賠率聚合 + 套利雷達」，對跨平台玩家非常實用。

你的任務是每週以「老玩家」的第一人稱視角，寫一份預測市場競品週報。
所有輸出皆使用繁體中文。你必須以純 JSON 格式回覆，不要輸出任何其他文字。"""


# ─── 產生報告內容（JSON）──────────────────────────────────────────────────────
def generate_report_data() -> dict:
    user_prompt = (
        f"幫我寫本週的競品週報。規則如下：\n\n"
        f"1. **WEEKLY DISCOVERY**\n"
        f"   用以下流程選出本週的 WEEKLY DISCOVERY 平台：\n"
        f"   步驟一：從候選池中，挑出你認為「本週最活躍」的平台（以近期交易量、社群討論熱度、新功能上線、重大事件等為依據）。\n"
        f"   候選池：Metaculus, Manifold Markets, Hedgehog Markets, PredictIt, Drift Protocol, Azuro, PlotX, Zeitgeist, Omen, Futuur, Smarkets, Betfair Exchange, Insight Prediction, Iowa Electronic Markets, Fantasy Top, Thales Market, Overtime Markets\n"
        f"   步驟二：在候選池之外，主動找一個你認為「近期值得關注」的預測市場平台（不能是 Polymarket、Kalshi、VoteFlux、YesNoMarkets，也不能是候選池內的平台）。\n"
        f"   步驟三：比較步驟一和步驟二的兩個平台，選出「更活躍、更值得本週介紹」的那一個作為 WEEKLY DISCOVERY。\n"
        f"   在 veteran_take 裡說明你的選擇理由，以及另一個落選平台的名稱和落選原因（一句話）。\n"
        f"   ⚠️ 所選平台必須真實存在且仍在運營，網址必須真實可連線，不確定就換一個。\n\n"
        f"2. **競品深度分析**\n"
        f"   固定分析以下 5 個平台，加上 WEEKLY DISCOVERY（共 6 個）：\n"
        f"   Polymarket, Kalshi, VoteFlux, YesNoMarkets, WEEKLY DISCOVERY\n\n"
        f"   【YesNoMarkets 分析重點】\n"
        f"   YesNoMarkets 是跨平台賠率聚合工具（非獨立預測市場），整合 Polymarket + Kalshi 訂單簿。\n"
        f"   分析時請針對它作為「套利工具 / 賠率雷達」的角色來評分，而非傳統預測市場。\n"
        f"   - 流動性深度：反映它整合的 Polymarket+Kalshi 深度，不是自身流動性\n"
        f"   - 費用結構：工具本身是否免費，有無隱藏費用\n"
        f"   - 出入金便利性：不適用（N/A），因為它不直接處理資金\n"
        f"   - 盤口豐富度：能掃描多少個市場的跨平台賠率\n"
        f"   - 監管合規：依賴 Polymarket/Kalshi 合規，自身定位為資訊工具\n"
        f"   - 介面體驗：套利機會是否清晰呈現，操作是否直觀\n\n"
        f"   固定使用以下 6 個維度，每個維度給 1-10 分 + 一句老玩家點評：\n"
        f"   流動性深度、費用結構、出入金便利性、盤口豐富度、監管合規、介面體驗\n\n"
        f"3. **本週觀察與碎碎念**：第一人稱，3-5 條，有個人風格。\n\n"
        f"4. **給 VoteFlux 的建議**：3-5 條實際可執行的建議。\n\n"
        f"本週報告日期：{NOW_STR}\n"
        f'只輸出 JSON，結構：\n'
        f'{{"weekly_discovery":{{"name":"","url":"","description":"","veteran_take":"","runner_up":"落選平台名稱：落選原因一句話"}},'
        f'"analysis_dimensions":[],'
        f'"competitor_analysis":[{{"name":"","scores":{{}},"comments":{{}},"overall_verdict":""}}],'
        f'"weekly_notes":[],"voteflux_advice":[]}}\n'
        f"competitor_analysis 必須包含 6 個平台（Polymarket, Kalshi, VoteFlux, YesNoMarkets, WEEKLY DISCOVERY 的平台名），"
        f"scores/comments 的 key 必須與 analysis_dimensions 完全一致。"
    )

    raw = call_openai(SYSTEM_PROMPT, user_prompt)
    raw = re.sub(r'^```json?\s*\n?', '', raw.strip())
    raw = re.sub(r'\n?```\s*$', '', raw.strip())
    print(f"🔍 [DEBUG] JSON 長度: {len(raw)} 字元")
    print(f"🔍 [DEBUG] 前 300 字:\n{raw[:300]}")
    return json.loads(raw)


# ─── 組裝 HTML ─────────────────────────────────────────────────────────────────
def score_color(score: int) -> str:
    if score >= 8:   return "#3fb950"
    elif score >= 5: return "#d29922"
    else:            return "#f85149"


def build_html(data: dict) -> str:
    dd   = data["weekly_discovery"]
    dims = data["analysis_dimensions"]

    dim_headers = "".join(f"<th>{d}</th>" for d in dims)

    comp_rows = ""
    for c in data["competitor_analysis"]:
        scores_cells = ""
        for d in dims:
            s = c["scores"].get(d, "—")
            if isinstance(s, (int, float)):
                color = score_color(int(s))
                scores_cells += f'<td><span class="score" style="color:{color}">{s}</span></td>'
            else:
                scores_cells += f"<td>{s}</td>"
        comp_rows += f"""<tr>
          <td><b>{c['name']}</b></td>
          {scores_cells}
        </tr>"""

    comp_cards = ""
    for c in data["competitor_analysis"]:
        comments_html = ""
        for d in dims:
            comment = c["comments"].get(d, "")
            s = c["scores"].get(d, "—")
            if isinstance(s, (int, float)):
                color = score_color(int(s))
                comments_html += f'<div class="comment-row"><span class="dim-label">{d}</span> <span class="score" style="color:{color}">{s}/10</span> — {comment}</div>'
            else:
                comments_html += f'<div class="comment-row"><span class="dim-label">{d}</span> <span style="color:#8b949e">N/A</span> — {comment}</div>'
        comp_cards += f"""<div class="comp-card">
          <h3>{c['name']}</h3>
          <div class="verdict">💬 {c['overall_verdict']}</div>
          {comments_html}
        </div>"""

    notes_html  = "".join(f'<div class="note-item">📝 {note}</div>\n' for note in data["weekly_notes"])
    advice_html = "".join(f'<div class="action-item">🎯 <b>#{i}</b> {a}</div>\n' for i, a in enumerate(data["voteflux_advice"], 1))

    runner_up_html = (
        f'<div style="margin-top:10px;font-size:0.85em;color:#8b949e;">🥈 落選候選人：{dd["runner_up"]}</div>'
        if dd.get("runner_up") else ""
    )

    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>VoteFlux 競品週報 — {NOW_STR}</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ background: #0d1117; color: #c9d1d9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; line-height: 1.7; padding: 20px; max-width: 1200px; margin: 0 auto; }}
    h1 {{ color: #58a6ff; font-size: 2em; margin-bottom: 5px; }}
    h2 {{ color: #58a6ff; font-size: 1.4em; margin: 40px 0 15px; padding-bottom: 8px; border-bottom: 2px solid #21262d; }}
    h3 {{ color: #79c0ff; font-size: 1.15em; margin-bottom: 8px; }}
    .header {{ text-align: center; padding: 30px 0; border-bottom: 3px solid #f0883e; margin-bottom: 30px; }}
    .header .date {{ color: #8b949e; font-size: 1.1em; margin-top: 8px; }}
    .header .subtitle {{ color: #f0883e; font-size: 0.9em; margin-top: 5px; letter-spacing: 2px; }}
    .discovery {{ background: linear-gradient(135deg, #161b22, #1c2333); border: 1px solid #f0883e; border-radius: 12px; padding: 25px; margin: 20px 0; }}
    .discovery .badge {{ display: inline-block; background: #f0883e; color: #0d1117; padding: 4px 14px; border-radius: 20px; font-weight: bold; font-size: 0.85em; margin-bottom: 15px; }}
    .discovery .platform-name {{ color: #f0883e; font-size: 1.4em; font-weight: bold; }}
    .discovery .url {{ color: #58a6ff; font-size: 0.85em; word-break: break-all; }}
    .discovery p {{ margin-top: 12px; }}
    .discovery .veteran-take {{ margin-top: 15px; padding: 15px; background: rgba(240,136,62,0.08); border-radius: 8px; border-left: 4px solid #f0883e; font-style: italic; color: #e6edf3; }}
    .discovery .veteran-take::before {{ content: "🎙️ 老玩家說："; font-style: normal; font-weight: bold; display: block; margin-bottom: 5px; color: #f0883e; }}
    table {{ width: 100%; border-collapse: collapse; background: #161b22; border-radius: 10px; overflow: hidden; margin: 15px 0; }}
    th {{ background: #21262d; color: #58a6ff; padding: 14px 15px; text-align: center; font-weight: 600; font-size: 0.9em; }}
    th:first-child {{ text-align: left; }}
    td {{ padding: 12px 15px; border-bottom: 1px solid #21262d; text-align: center; font-size: 0.9em; }}
    td:first-child {{ text-align: left; }}
    tr:hover td {{ background: #1c2333; }}
    tr:last-child td {{ border-bottom: none; }}
    .score {{ font-weight: bold; font-size: 1.1em; }}
    .comp-cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(350px, 1fr)); gap: 15px; margin: 15px 0; }}
    .comp-card {{ background: #161b22; border: 1px solid #21262d; border-radius: 10px; padding: 20px; }}
    .comp-card .verdict {{ margin: 10px 0 15px; padding: 10px; background: rgba(88,166,255,0.06); border-radius: 6px; font-style: italic; color: #8b949e; font-size: 0.95em; }}
    .comment-row {{ margin: 6px 0; font-size: 0.9em; }}
    .dim-label {{ display: inline-block; background: #21262d; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; margin-right: 6px; color: #8b949e; }}
    .note-item {{ background: #161b22; border-left: 4px solid #8957e5; padding: 15px 20px; margin: 10px 0; border-radius: 0 8px 8px 0; font-size: 0.95em; }}
    .action-item {{ background: #161b22; border-left: 4px solid #3fb950; padding: 15px 20px; margin: 10px 0; border-radius: 0 8px 8px 0; }}
    .footer {{ text-align: center; margin-top: 50px; padding-top: 20px; border-top: 1px solid #21262d; color: #484f58; font-size: 0.85em; }}
    @media (max-width: 768px) {{ body {{ padding: 12px; }} .comp-cards {{ grid-template-columns: 1fr; }} table {{ font-size: 0.8em; }} th, td {{ padding: 8px 10px; }} }}
  </style>
</head>
<body>
  <div class="header">
    <h1>🤖 VoteFlux 競品週報</h1>
    <div class="date">{NOW_STR}</div>
    <div class="subtitle">PREDICTION MARKET WEEKLY INTELLIGENCE</div>
  </div>

  <h2>🔍 WEEKLY DISCOVERY</h2>
  <div class="discovery">
    <span class="badge">THIS WEEK'S FIND</span>
    <div class="platform-name">{dd['name']}</div>
    <a class="url" href="{dd.get('url', '#')}" target="_blank">{dd.get('url', '')}</a>
    <p>{dd['description']}</p>
    <div class="veteran-take">{dd['veteran_take']}</div>
    {runner_up_html}
  </div>

  <h2>📊 競品評分總覽</h2>
  <table>
    <thead><tr><th>平台</th>{dim_headers}</tr></thead>
    <tbody>{comp_rows}</tbody>
  </table>

  <h2>🔬 各平台詳細點評</h2>
  <div class="comp-cards">{comp_cards}</div>

  <h2>📝 本週觀察與碎碎念</h2>
  {notes_html}

  <h2>⚔️ 給 VoteFlux 的建議</h2>
  {advice_html}

  <div class="footer">
    <p>© 2026 VoteFlux Weekly Intelligence | Generated by AI | 本報告僅供參考，不構成任何投資建議</p>
  </div>
</body>
</html>"""


# ─── 儲存 HTML ─────────────────────────────────────────────────────────────────
def save_html_report(html_content: str) -> str:
    os.makedirs("reports", exist_ok=True)
    filename = f"reports/voteflux-weekly-{NOW_FILE}.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html_content)
    with open("reports/index.html", "w", encoding="utf-8") as f:
        f.write(f"""<!DOCTYPE html><html><head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="0; url=voteflux-weekly-{NOW_FILE}.html">
<title>VoteFlux 最新競品週報</title>
</head><body><p>正在跳轉... <a href="voteflux-weekly-{NOW_FILE}.html">點此前往</a></p></body></html>""")
    print(f"📄 報告已儲存: {filename}")
    return filename


# ─── Telegram 發送 ────────────────────────────────────────────────────────────
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
    print("=" * 50)
    print(f"🤖 VoteFlux 競品週報 — {NOW_STR}")
    print("=" * 50)

    print("\n📝 正在產生報告資料（GPT-4o-mini → JSON）...")
    try:
        report_data = generate_report_data()
        print("✅ JSON 解析成功")
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        print(f"❌ JSON 解析失敗: {e}")
        send_telegram(f"⚠️ <b>VoteFlux 競品週報 — {NOW_STR}</b>\n\n報告產生失敗，請手動檢查 Action log。")
        return

    print("\n🔨 正在組裝 HTML 報告...")
    html_content = build_html(report_data)
    save_html_report(html_content)

    report_url = f"{GITHUB_PAGES_URL}/voteflux-weekly-{NOW_FILE}.html"
    message = f'🤖 <b>VoteFlux 競品週報 — {NOW_STR}</b>\n\n🔗 <a href="{report_url}">📖 查看完整報告</a>'
    print("\n📤 正在推播到 Telegram...")
    send_telegram(message)
    print("\n🎉 VoteFlux 競品週報完成！")


if __name__ == "__main__":
    main()

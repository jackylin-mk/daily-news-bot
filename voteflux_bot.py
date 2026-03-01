"""
VoteFlux 每日競品戰報

AI 角色：預測市場資深玩家（10 年老手），風格直接犀利
AI 模型：OpenAI GPT-4o-mini
輸出格式：HTML 報告（GitHub Pages）+ Telegram 推播連結
排程觸發：Cloudflare Workers Cron → GitHub Actions（每天台灣時間 08:00）

報告內容：
  - DAILY DISCOVERY：三步驟競爭選拔當日最值得關注的競品
  - 競品評分總覽：6 大平台 × 6 固定維度（1-10 分顏色標示）
  - 各平台詳細點評：每個維度分數 + 老玩家犀利評語
  - 今日觀察與碎碎念：第一人稱市場觀察
  - 給 VoteFlux 的建議：實際可執行的改進方向
  - 各市場熱門題目：印度 · 孟加拉 · 越南 · 馬來西亞 · 菲律賓 · 泰國

固定分析維度：流動性深度 · 費用結構 · 出入金便利性 · 盤口豐富度 · 監管合規 · 介面體驗
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


# ─── OpenAI API 呼叫 ────────────────────────────────────
def fetch_market_topics() -> str:
    """用 OpenAI web search 抓取 Polymarket 和 Kalshi 的熱門題目作為參考"""
    body = json.dumps({
        "model": "gpt-4o-mini",
        "tools": [{"type": "web_search_preview"}],
        "input": (
            "請直接搜尋並瀏覽 Polymarket（polymarket.com）和 Kalshi（kalshi.com）網站，"
            "列出目前交易量最高的熱門預測市場題目，涵蓋以下類型：體育賽事、娛樂/頒獎典禮、"
            "科技/AI產品發布、加密貨幣價格、政治選舉、財經指標。"
            "特別標注與印度、孟加拉、越南、馬來西亞、菲律賓、泰國相關的題目。"
            "直接列出真實題目原文，不要加任何分析或說明，題目格式要和 Polymarket/Kalshi 一致。"
        ),
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

    try:
        with urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
        # 從 output 裡找 message 類型的文字回應
        for item in data.get("output", []):
            if item.get("type") == "message":
                for block in item.get("content", []):
                    if block.get("type") == "output_text":
                        return block.get("text", "")
        return ""
    except Exception as e:
        print(f"⚠️ web search 抓取熱門題目失敗: {e}")
        return ""


def call_openai(system_prompt: str, user_prompt: str, model: str = "gpt-4o-mini") -> str:
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
SYSTEM_PROMPT = """你是一位在預測市場（Prediction Market）打滾超過 10 年的資深玩家。

你的背景：
- 你從 Intrade 時代就開始玩，經歷過 PredictIt、Augur、到現在的 Polymarket 世代
- 你每天在多個平台之間套利，對各平台的流動性、費用結構、出入金速度、盤口深度、介面體驗瞭若指掌
- 你同時熟悉傳統合規路線（如 Kalshi 的 CFTC 監管）和 DeFi/Web3 鏈上預測市場
- 你說話直接、犀利、不廢話，用數據和親身經驗說話
- 你對爛平台毫不留情，對好平台也會指出它的隱患

你的任務是每天以「老玩家」的第一人稱視角，寫一份預測市場競品日報。
所有輸出皆使用繁體中文。你必須以純 JSON 格式回覆，不要輸出任何其他文字。"""


def generate_report_data() -> dict:
    # 先用 web search 抓取 Polymarket / Kalshi 真實熱門題目作為參考
    print("🔍 正在搜尋 Polymarket / Kalshi 熱門題目...")
    market_reference = fetch_market_topics()
    if market_reference:
        print("✅ 取得熱門題目參考資料")
    else:
        print("⚠️ 未取得參考資料，將由 AI 自行生成")

    market_ref_section = f"""
以下是我從 Polymarket 和 Kalshi 搜尋到的真實熱門題目，請參考這些題目的「格式與風格」來出各市場題目：
---
{market_reference}
---
""" if market_reference else ""

    user_prompt = f"""幫我寫今天的競品日報。規則如下：

1. **DAILY DISCOVERY**
   用以下流程選出今天的 DAILY DISCOVERY 平台：

   步驟一：從候選池中，挑出你認為「今天最活躍」的平台（以近期交易量、社群討論熱度、新功能上線、重大事件等為依據）。
   候選池：Metaculus, Manifold Markets, Hedgehog Markets, PredictIt, Drift Protocol, Azuro, PlotX, Zeitgeist, Omen, Futuur, Smarkets, Betfair Exchange, Insight Prediction, Iowa Electronic Markets, Fantasy Top, Thales Market, Overtime Markets

   步驟二：在候選池之外，主動找一個你認為「近期值得關注」的預測市場平台（不能是 Polymarket、Kalshi、VoteFlux、Hyperliquid、Predict.fun，也不能是候選池內的平台）。

   步驟三：比較步驟一和步驟二的兩個平台，選出「更活躍、更值得今天介紹」的那一個作為 DAILY DISCOVERY。
   在 veteran_take 裡說明你的選擇理由，以及另一個落選平台的名稱和落選原因（一句話）。

   ⚠️ 所選平台必須真實存在且仍在運營，網址必須真實可連線，不確定就換一個。

2. **競品深度分析**
   平台：Polymarket, Kalshi, VoteFlux, Hyperliquid, Predict.fun, 加上 DAILY DISCOVERY 的平台（共 6 個）。
   固定使用以下 6 個維度，每個維度給 1-10 分 + 一句老玩家點評：
   流動性深度、費用結構、出入金便利性、盤口豐富度、監管合規、介面體驗

3. **今日觀察與碎碎念**：第一人稱，3-5 條，有個人風格。

4. **給 VoteFlux 的建議**：3-5 條實際可執行的建議。

5. **各市場熱門題目**：印度、孟加拉、越南、馬來西亞、菲律賓、泰國，各 2 題。
   參考上方 Polymarket / Kalshi 真實題目的格式與多元類型，為每個市場出題。
   
   題目類型要多元，不要全部都是政治類，可以包含：
   - 🏏 體育賽事（板球、足球、電競、羽毛球等各國熱門運動）
   - 🎬 娛樂（當地票房、頒獎、選秀節目結果）
   - 💰 財經（股市指數、匯率、央行利率決策）
   - 🗳️ 政治（選舉、政策通過與否）
   - 📱 科技（App 用戶數、產品發布）
   
   題目必須符合以下所有條件：
   - 可以用「是/否（Yes/No）」回答
   - 有唯一、客觀的判斷標準——結果出來後任何人看都只有一個答案，不存在爭議空間
   - 判斷基準必須是以下之一：①具體數字門檻 ②官方正式公告 ③賽事/投票結果 ④特定人物的具體行動
   - 不可推薦已發生的歷史事件（現在是 {TODAY_STR}）
   
   ❌ 不合格範例（對照修正）：
   - 「印度央行是否會在 2026 年第一季度前降低利率？」→ 應改為「印度央行會在 2026 年 4 月例會上將基準利率降至 6% 以下嗎？」
   - 「孟加拉將在 2026 年的國會選舉中通過新的選舉法案嗎？」→ 法案名稱不明，應改為「孟加拉國會將在 2026 年 6 月前正式通過《選舉委員會改革法》嗎？」
   - 「越南的手機市場是否會在 2026 年前成為全球前三大？」→ 應改為「越南 2026 年手機出口額是否會突破 600 億美元？」
   - 「菲律賓籃球聯賽中，哪支球隊會獲得 2026 年冠軍？」→ 這不是 Yes/No 題，應改為「San Miguel Beermen 會獲得 2026 年 PBA 總冠軍嗎？」
   - 「泰國的國際旅遊人數在 2026 年是否會回到疫情前的水準？」→ 應改為「泰國 2026 年全年國際旅遊人數是否會突破 3,900 萬人次？」
   
   ✅ 合格題目的必要元素：主詞明確 + 動作具體 + 數字門檻或官方聲明 + 截止時間點

{market_ref_section}只輸出 JSON，結構：
{{"daily_discovery":{{"name":"","url":"","description":"","veteran_take":"","runner_up":"落選平台名稱：落選原因一句話"}},"analysis_dimensions":[],"competitor_analysis":[{{"name":"","scores":{{}},"comments":{{}},"overall_verdict":""}}],"daily_notes":[],"voteflux_advice":[],"market_topics":[{{"market":"","topics":[]}}]}}

competitor_analysis 必須包含 6 個平台，scores/comments 的 key 必須與 analysis_dimensions 完全一致。今天是 {TODAY_STR}。"""

    raw = call_openai(SYSTEM_PROMPT, user_prompt)

    # 清理 markdown 包裹
    raw = re.sub(r'^```json?\s*\n?', '', raw.strip())
    raw = re.sub(r'\n?```\s*$', '', raw.strip())

    print(f"🔍 [DEBUG] JSON 長度: {len(raw)} 字元")
    print(f"🔍 [DEBUG] 前 300 字:\n{raw[:300]}")

    return json.loads(raw)


# ─── 組裝 HTML ───────────────────────────────────────────
def score_color(score: int) -> str:
    """根據分數回傳顏色"""
    if score >= 8:
        return "#3fb950"  # 綠
    elif score >= 5:
        return "#d29922"  # 黃
    else:
        return "#f85149"  # 紅


def build_html(data: dict) -> str:
    dd = data["daily_discovery"]
    dims = data["analysis_dimensions"]

    # ── 競品分析表頭
    dim_headers = "".join(f"<th>{d}</th>" for d in dims)

    # ── 競品分析表格行
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

    # ── 競品詳細點評卡片
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
                comments_html += f'<div class="comment-row"><span class="dim-label">{d}</span> {comment}</div>'
        comp_cards += f"""<div class="comp-card">
            <h3>{c['name']}</h3>
            <div class="verdict">💬 {c['overall_verdict']}</div>
            {comments_html}
        </div>"""

    # ── 今日觀察
    notes_html = ""
    for i, note in enumerate(data["daily_notes"], 1):
        notes_html += f'<div class="note-item">📝 {note}</div>\n'

    # ── VoteFlux 建議
    advice_html = ""
    for i, a in enumerate(data["voteflux_advice"], 1):
        advice_html += f'<div class="action-item">🎯 <b>#{i}</b> {a}</div>\n'

    # ── 市場題目
    flags = {"印度": "🇮🇳", "孟加拉": "🇧🇩", "越南": "🇻🇳", "馬來西亞": "🇲🇾", "菲律賓": "🇵🇭", "泰國": "🇹🇭"}
    markets_html = ""
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
        line-height: 1.7; padding: 20px; max-width: 1200px; margin: 0 auto;
    }}
    h1 {{ color: #58a6ff; font-size: 2em; margin-bottom: 5px; }}
    h2 {{
        color: #58a6ff; font-size: 1.4em; margin: 40px 0 15px;
        padding-bottom: 8px; border-bottom: 2px solid #21262d;
    }}
    h3 {{ color: #79c0ff; font-size: 1.15em; margin-bottom: 8px; }}

    .header {{
        text-align: center; padding: 30px 0;
        border-bottom: 3px solid #f0883e; margin-bottom: 30px;
    }}
    .header .date {{ color: #8b949e; font-size: 1.1em; margin-top: 8px; }}
    .header .subtitle {{ color: #f0883e; font-size: 0.9em; margin-top: 5px; letter-spacing: 2px; }}

    /* Discovery */
    .discovery {{
        background: linear-gradient(135deg, #161b22, #1c2333);
        border: 1px solid #f0883e; border-radius: 12px;
        padding: 25px; margin: 20px 0;
    }}
    .discovery .badge {{
        display: inline-block; background: #f0883e; color: #0d1117;
        padding: 4px 14px; border-radius: 20px; font-weight: bold;
        font-size: 0.85em; margin-bottom: 15px;
    }}
    .discovery .platform-name {{ color: #f0883e; font-size: 1.4em; font-weight: bold; }}
    .discovery .url {{ color: #58a6ff; font-size: 0.85em; word-break: break-all; }}
    .discovery p {{ margin-top: 12px; }}
    .discovery .veteran-take {{
        margin-top: 15px; padding: 15px;
        background: rgba(240, 136, 62, 0.08); border-radius: 8px;
        border-left: 4px solid #f0883e;
        font-style: italic; color: #e6edf3;
    }}
    .discovery .veteran-take::before {{ content: "🎙️ 老玩家說："; font-style: normal; font-weight: bold; display: block; margin-bottom: 5px; color: #f0883e; }}

    /* Score Table */
    table {{
        width: 100%; border-collapse: collapse;
        background: #161b22; border-radius: 10px; overflow: hidden;
        margin: 15px 0;
    }}
    th {{
        background: #21262d; color: #58a6ff;
        padding: 14px 15px; text-align: center;
        font-weight: 600; font-size: 0.9em;
    }}
    th:first-child {{ text-align: left; }}
    td {{ padding: 12px 15px; border-bottom: 1px solid #21262d; text-align: center; font-size: 0.9em; }}
    td:first-child {{ text-align: left; }}
    tr:hover td {{ background: #1c2333; }}
    tr:last-child td {{ border-bottom: none; }}
    .score {{ font-weight: bold; font-size: 1.1em; }}

    /* Competitor Cards */
    .comp-cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(350px, 1fr)); gap: 15px; margin: 15px 0; }}
    .comp-card {{
        background: #161b22; border: 1px solid #21262d;
        border-radius: 10px; padding: 20px;
    }}
    .comp-card .verdict {{
        margin: 10px 0 15px; padding: 10px;
        background: rgba(88, 166, 255, 0.06); border-radius: 6px;
        font-style: italic; color: #8b949e; font-size: 0.95em;
    }}
    .comment-row {{ margin: 6px 0; font-size: 0.9em; }}
    .dim-label {{
        display: inline-block; background: #21262d;
        padding: 2px 8px; border-radius: 4px; font-size: 0.8em;
        margin-right: 6px; color: #8b949e;
    }}

    /* Notes */
    .note-item {{
        background: #161b22; border-left: 4px solid #8957e5;
        padding: 15px 20px; margin: 10px 0; border-radius: 0 8px 8px 0;
        font-size: 0.95em;
    }}

    /* Action Items */
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
        border-radius: 10px; padding: 20px;
    }}
    .market-card ul {{ margin-top: 10px; padding-left: 20px; }}
    .market-card li {{ margin: 8px 0; color: #c9d1d9; }}

    /* Footer */
    .footer {{
        text-align: center; margin-top: 50px; padding-top: 20px;
        border-top: 1px solid #21262d; color: #484f58; font-size: 0.85em;
    }}

    @media (max-width: 768px) {{
        body {{ padding: 12px; }}
        .comp-cards, .markets-grid {{ grid-template-columns: 1fr; }}
        table {{ font-size: 0.8em; }}
        th, td {{ padding: 8px 10px; }}
    }}
</style>
</head>
<body>

<div class="header">
    <h1>🤖 VoteFlux 每日戰報</h1>
    <div class="date">{TODAY_STR}</div>
    <div class="subtitle">PREDICTION MARKET DAILY INTELLIGENCE</div>
</div>

<!-- DAILY DISCOVERY -->
<h2>🔍 DAILY DISCOVERY</h2>
<div class="discovery">
    <span class="badge">TODAY'S FIND</span>
    <div class="platform-name">{dd['name']}</div>
    <a class="url" href="{dd.get('url', '#')}" target="_blank">{dd.get('url', '')}</a>
    <p>{dd['description']}</p>
    <div class="veteran-take">{dd['veteran_take']}</div>
    {f'<div style="margin-top:10px;font-size:0.85em;color:#8b949e;">🥈 落選候選人：{dd["runner_up"]}</div>' if dd.get('runner_up') else ''}
</div>

<!-- 評分總覽 -->
<h2>📊 競品評分總覽</h2>
<table>
    <thead>
        <tr><th>平台</th>{dim_headers}</tr>
    </thead>
    <tbody>
        {comp_rows}
    </tbody>
</table>

<!-- 詳細點評 -->
<h2>🔬 各平台詳細點評</h2>
<div class="comp-cards">
    {comp_cards}
</div>

<!-- 今日觀察 -->
<h2>📝 今日觀察與碎碎念</h2>
{notes_html}

<!-- VoteFlux 建議 -->
<h2>⚔️ 給 VoteFlux 的建議</h2>
{advice_html}

<!-- 市場題目 -->
<h2>🌏 各市場熱門題目推薦</h2>
<div class="markets-grid">
    {markets_html}
</div>

<div class="footer">
    <p>© 2026 VoteFlux Daily Intelligence | Generated by AI | 本報告僅供參考，不構成任何投資建議</p>
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
            # fallback：保留 <a href> 的 URL，避免連結消失
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
    print(f"🤖 VoteFlux 每日戰報 — {TODAY_STR}")
    print("=" * 50)

    # Step 1: GPT-4o 產生報告資料（JSON）
    print("\n📝 正在產生報告資料（GPT-4o → JSON）...")
    try:
        report_data = generate_report_data()
        print("✅ JSON 解析成功")
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        print(f"❌ JSON 解析失敗: {e}")
        send_telegram(f"⚠️ <b>VoteFlux 每日戰報 — {TODAY_STR}</b>\n\n報告產生失敗，請手動檢查 Action log。")
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

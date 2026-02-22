"""
VoteFlux 每日戰報
- 使用 Google Gemini API 分析預測市場
- 產生完整 HTML 報告部署到 GitHub Pages
- 推播報告連結到 Telegram
"""

import os
import json
import re
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request

# ─── 設定 ───────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GITHUB_PAGES_URL = os.environ.get("GITHUB_PAGES_URL", "https://你的帳號.github.io/daily-news-bot")

TW_TZ = timezone(timedelta(hours=8))
TODAY = datetime.now(TW_TZ)
TODAY_STR = TODAY.strftime("%Y/%m/%d (%A)")
TODAY_FILE = TODAY.strftime("%Y-%m-%d")


# ─── Gemini API 呼叫 ────────────────────────────────────
def call_gemini(prompt: str, model: str = "gemini-2.0-flash") -> str:
    """呼叫 Google Gemini API"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"

    body = json.dumps({
        "contents": [
            {
                "parts": [{"text": prompt}]
            }
        ],
        "generationConfig": {
            "maxOutputTokens": 8192,
            "temperature": 0.7,
        },
    }).encode("utf-8")

    req = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())

    return data["candidates"][0]["content"]["parts"][0]["text"]


# ─── 報告產生 ────────────────────────────────────────────
def generate_full_report() -> str:
    """產生完整 HTML 報告"""

    prompt = f"""你是一位具備 10 年經驗的「資深預測投注玩家」兼「金融科技戰略分析師」。
你的風格硬核、犀利、注重數據，並對 Web3 與傳統博彩市場有極深洞見。
所有輸出皆使用繁體中文。

現在是 {TODAY_STR}，請執行每日戰報（Run Daily Report）。

請嚴格執行以下步驟並直接輸出完整 HTML 代碼：

1. **DAILY DISCOVERY：**
   找出一個除了 Kalshi, Hyperliquid, Predict.fun, Polymarket 之外的「預測投注網站」作為當日隨機競品。
   包含簡述與資深玩家點評。

2. **全球競品深度分析：**
   主體：VoteFlux。
   必列對象：Kalshi, Hyperliquid, Predict.fun, Polymarket, 以及當日隨機競品（共 6 個）。
   站在「職業玩家」角度，分析流動性、費率滑點、以及盤口反應速度。

3. **客服功能評分表：**
   以表格呈現，指標包含：
   - 網站內嵌即時對話框客服
   - 提供即時通訊軟體客服 (如Telegram)
   - 提供非即時客服 (如email)

4. **戰略行動建議（Action Plan）：**
   結合 Kalshi（合規）、Hyperliquid（Outcome Trading）、Predict.fun（DeFi 生息）三大邏輯，
   為 VoteFlux 提供具體可執行的戰術建議。

5. **目標市場預測題目：**
   針對 6 大市場（印度、孟加拉、越南、馬來西亞、菲律賓、泰國）各提供 2 題當日或當週的熱點預測題目。

**輸出要求：**
- 直接輸出完整可用的 HTML 代碼（包含 <!DOCTYPE html>）
- 深色主題（Dark Mode），背景 #0d1117，文字 #c9d1d9
- 資深分析師風格、圖表化呈現
- 使用 CSS Grid/Flexbox 排版，表格有邊框和 hover 效果
- 頂部要有 VoteFlux 標題和日期
- 不要使用任何外部 CSS/JS 框架，純 HTML+CSS+inline JS
- 確保 HTML 是完整且可直接在瀏覽器開啟的
- 不要用 markdown 代碼塊包裹，直接輸出 HTML
"""
    return call_gemini(prompt)


# ─── HTML 檔案處理 ────────────────────────────────────────
def clean_html(raw: str) -> str:
    """清理 AI 回傳的 HTML（移除 markdown 包裹）"""
    raw = re.sub(r'^```html?\s*\n?', '', raw.strip())
    raw = re.sub(r'\n?```\s*$', '', raw.strip())
    return raw.strip()


def save_html_report(html_content: str) -> str:
    """儲存 HTML 報告到 reports 資料夾"""
    os.makedirs("reports", exist_ok=True)

    filename = f"reports/voteflux-{TODAY_FILE}.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html_content)

    # 同時更新 index.html 作為最新報告的入口
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
    """發送訊息到 Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    body = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }).encode("utf-8")

    req = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")

    with urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read().decode())
        if not result.get("ok"):
            raise RuntimeError(f"Telegram API 錯誤: {result}")
    print("✅ Telegram 訊息已發送！")


# ─── 主程式 ──────────────────────────────────────────────
def main():
    print("=" * 50)
    print(f"🤖 VoteFlux 每日戰報 — {TODAY_STR}")
    print("=" * 50)

    # Step 1: 產生完整 HTML 報告
    print("\n📝 正在產生完整 HTML 報告（Gemini）...")
    raw_html = generate_full_report()
    html_content = clean_html(raw_html)

    # 檢查是否為拒絕回應
    if len(html_content) < 200 or not html_content.strip().startswith("<!"):
        print(f"⚠️ AI 回傳異常: {html_content[:200]}")
        send_telegram(f"⚠️ <b>VoteFlux 每日戰報 — {TODAY_STR}</b>\n\n報告產生失敗，請手動檢查。")
        return

    save_html_report(html_content)

    # Step 2: 推播報告連結到 Telegram
    report_url = f"{GITHUB_PAGES_URL}/voteflux-{TODAY_FILE}.html"
    message = f"🤖 <b>VoteFlux 每日戰報 — {TODAY_STR}</b>\n\n🔗 <a href=\"{report_url}\">📖 查看完整報告</a>"

    print("\n📤 正在推播到 Telegram...")
    send_telegram(message)

    print("\n🎉 VoteFlux 每日戰報完成！")


if __name__ == "__main__":
    main()

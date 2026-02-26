# 🤖 Daily News + VoteFlux Intelligence Bot

> 每天早上 08:00 準時推播新聞摘要與預測市場競品戰報到 Telegram，零人工介入。

---

## ✨ 功能總覽

| Bot | 說明 | AI 模型 | 輸出 |
|-----|------|---------|------|
| 📰 **每日新聞摘要** | 台灣綜合 · 國際 · 科技 · AI · 財經 | GPT-4o-mini | Telegram 訊息（多人推播） |
| 📊 **VoteFlux 每日戰報** | 預測市場競品分析（資深玩家視角） | GPT-4o | GitHub Pages + Telegram 連結 |

---

## 🏗️ 系統架構

```
┌─────────────────────────────────────────────────────────────┐
│  ⏰ Cloudflare Workers Cron                                  │
│  每天 UTC 00:00（台灣 08:00）準時觸發 GitHub Actions          │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  📰 News Bot (GitHub Actions)                                │
│  RSS 新聞來源 → 日期過濾 + 去重複 → GPT-4o-mini 摘要          │
│                                   → Telegram 推播（多人）     │
├──────────────────────────────────────────────────────────────┤
│  📊 VoteFlux Bot (GitHub Actions)                            │
│  GPT-4o 分析 (JSON) → Python 組裝 HTML → GitHub Pages        │
│                                          → Telegram 連結      │
└──────────────────────────────────────────────────────────────┘
```

### 為什麼用 Cloudflare Workers？

GitHub Actions 免費排程有 5~30 分鐘延遲。改用 Cloudflare Workers Cron Trigger 後，**誤差在 1 秒內**，且完全免費。

---

## 📰 每日新聞摘要

### 新聞分類與來源

| 分類 | RSS 來源 |
|------|---------|
| 🇹🇼 台灣綜合 | 自由時報 · ETtoday |
| 🌍 國際新聞 | 自由時報國際 · 中央社 |
| 💻 科技新聞 | iThome · 科技新報 |
| 🤖 AI 新聞 | The Verge AI · VentureBeat AI · TechCrunch AI |
| 💰 財經新聞 | 自由時報財經 · 中央社財經 |

### 新聞過濾機制

- **日期過濾**：只保留今天（台灣時間）發布的新聞；英文來源（The Verge、VentureBeat、TechCrunch）因時區問題不做日期過濾
- **去重複**：透過 GitHub Actions Cache 跨天記錄已推播標題，避免同一則新聞重複出現
- **黑名單**：標題含特定關鍵字的新聞直接跳過（可在 `news_bot.py` 的 `TITLE_BLACKLIST` 自行新增）
- **手動測試模式**：`workflow_dispatch` 手動觸發時自動停用去重複，方便反覆測試

### 自訂設定

**新增黑名單關鍵字**：編輯 `news_bot.py` 中的 `TITLE_BLACKLIST`
```python
TITLE_BLACKLIST = [
    "冰與火之歌",
    "權力遊戲",
    "新增其他關鍵字",  # ← 加這裡
]
```

**新增 RSS 來源**：編輯 `news_bot.py` 中的 `RSS_FEEDS`，英文來源記得也加進 `EN_FEEDS`

---

## 📊 VoteFlux 每日戰報

以一位**在預測市場打滾超過 10 年的資深玩家**第一人稱視角撰寫，風格直接、犀利、用數據和親身經驗說話。

### 報告內容

| 區塊 | 內容 |
|------|------|
| 🔍 **DAILY DISCOVERY** | 每天從真實平台候選池中挖掘一個競品 + 老玩家真實評價 |
| 📊 **競品評分總覽** | 6 大平台 × AI 自選維度，1-10 分顏色標示 |
| 🔬 **各平台詳細點評** | 每個維度的分數與一句話犀利點評 + 總結 |
| 📝 **今日觀察與碎碎念** | 第一人稱的市場觀察，像老手寫交易日記 |
| ⚔️ **給 VoteFlux 的建議** | 站在老玩家立場的實際可執行建議 |
| 🌏 **各市場熱門題目** | 印度 · 孟加拉 · 越南 · 馬來西亞 · 菲律賓 · 泰國，各 2 題 |

### 競品清單

| # | 平台 | 類型 |
|---|------|------|
| 1 | **Polymarket** | 鏈上預測市場龍頭 |
| 2 | **Kalshi** | 美國 CFTC 合規 |
| 3 | **VoteFlux** | 主體分析對象 |
| 4 | **Hyperliquid** | Outcome Trading |
| 5 | **Predict.fun** | DeFi 生息預測 |
| 6 | **每日隨機競品** | 從候選池挑選（見下方） |

### DAILY DISCOVERY 候選池

> Metaculus · Manifold Markets · Hedgehog Markets · PredictIt · Drift Protocol · Azuro · PlotX · Zeitgeist · Omen · Futuur · Smarkets · Betfair Exchange · Insight Prediction · Iowa Electronic Markets · Fantasy Top · Thales Market · Overtime Markets

---

## 🚀 快速部署

### Step 1 ─ 建立 Telegram Bot

1. Telegram 搜尋 **@BotFather** → 傳送 `/newbot`
2. 設定名稱和 username（需以 `bot` 結尾）
3. 記下回傳的 **Bot Token**

### Step 2 ─ 取得 Chat ID

1. 對你的 Bot 按 **Start**，傳一則訊息
2. 瀏覽器打開：
   ```
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   ```
3. 找到 `"chat":{"id": 數字}` → 那個數字就是 **Chat ID**
4. 多人推播：用逗號分隔多個 Chat ID（例如 `123456,789012`）

### Step 3 ─ 取得 OpenAI API Key

1. 前往 [platform.openai.com](https://platform.openai.com/)
2. 登入 → API Keys → 建立一組 Key

### Step 4 ─ 部署到 GitHub

```bash
git init
git add .
git commit -m "🚀 初始化 Daily News + VoteFlux Bot"
git remote add origin https://github.com/你的帳號/daily-news-bot.git
git push -u origin main
```

### Step 5 ─ 設定 GitHub Secrets

**Settings → Secrets and variables → Actions**，新增：

| Secret 名稱 | 值 |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot Token |
| `TELEGRAM_CHAT_ID` | Chat ID（多人用逗號分隔） |
| `OPENAI_API_KEY` | OpenAI API Key |

### Step 6 ─ 啟用 GitHub Pages

**Settings → Pages → Source** 選擇 **GitHub Actions** → 儲存

### Step 7 ─ 部署 Cloudflare Workers（準時排程）

1. 註冊 [dash.cloudflare.com](https://dash.cloudflare.com/)（免費）
2. 到 **Workers & Pages → Create application → Start with Hello World**
3. Worker name 設為 `daily-bot-trigger`，點 Deploy
4. 進入 **Edit code**，將程式碼替換為 `cloudflare-worker/worker.js` 的內容，Deploy
5. 到 **Settings → Trigger Events → Cron Triggers**，新增：`0 0 * * *`
6. 到 **Settings → Variables and Secrets**，新增：

   | 名稱 | 值 |
   |------|-----|
   | `GITHUB_OWNER` | 你的 GitHub 帳號 |
   | `GITHUB_REPO` | `daily-news-bot` |
   | `GITHUB_TOKEN` | GitHub Personal Access Token（需 Actions read/write 權限） |

### Step 8 ─ 產生 GitHub Personal Access Token

1. 到 [github.com/settings/tokens?type=beta](https://github.com/settings/tokens?type=beta)
2. **Generate new token** → Fine-grained token
3. Repository access → **Only select repositories** → 選 `daily-news-bot`
4. Permissions → **Actions** → **Read and write**
5. Generate → 複製貼到 Cloudflare 的 `GITHUB_TOKEN`

### Step 9 ─ 測試 🎉

- **手動測試**：GitHub Actions 頁面 → Run workflow（去重複自動停用，可重複跑）
- **排程測試**：Cloudflare Edit code → Schedule → Trigger scheduled event

---

## ⚙️ 自訂設定

### 修改推播時間

編輯 Cloudflare Worker 的 **Cron Triggers**：

| 台灣時間 | cron |
|---------|------|
| 07:00 | `0 23 * * *` |
| **08:00** | **`0 0 * * *`** ← 目前設定 |
| 09:00 | `0 1 * * *` |
| 12:00 | `0 4 * * *` |

### 修改新聞來源

編輯 `news_bot.py` 中的 `RSS_FEEDS`。英文來源記得同步加入 `EN_FEEDS`（不做日期過濾）。

### 新增推播對象

編輯 GitHub Secret `TELEGRAM_CHAT_ID`，用逗號加入新的 Chat ID。

---

## 📁 檔案結構

```
daily-news-bot/
├── 📄 news_bot.py                        # 每日新聞摘要 Bot（支援多人推播）
├── 📄 voteflux_bot.py                    # VoteFlux 每日戰報 Bot
├── 📄 README.md
├── 📂 cloudflare-worker/
│   ├── worker.js                          # 觸發 GitHub Actions 的程式碼
│   └── wrangler.toml                      # Wrangler 設定檔（參考用）
├── 📂 reports/                            # ← 自動產生，不需手動建立
│   ├── index.html
│   └── voteflux-YYYY-MM-DD.html
└── 📂 .github/workflows/
    ├── daily-news.yml                     # Action: 每日新聞推播
    └── voteflux-report.yml                # Action: VoteFlux 戰報 + GitHub Pages
```

---

## 💰 費用估算

| 項目 | 費用 |
|------|------|
| Cloudflare Workers | ✅ 免費（每日 10 萬次請求） |
| GitHub Actions | ✅ 免費（每月 2,000 分鐘） |
| GitHub Pages | ✅ 免費 |
| Telegram Bot API | ✅ 免費 |
| OpenAI API | ~$0.03 - $0.06 / 天 |

> **💡 每月約 $1 ~ $2 美元**

---

## 🛠️ 技術細節

| 項目 | 說明 |
|------|------|
| **語言** | Python 3.12（零外部套件）+ JavaScript（Worker） |
| **排程** | Cloudflare Workers Cron（秒級精準） |
| **新聞來源** | 自由時報 · 中央社 · ETtoday · iThome · 科技新報 · The Verge · VentureBeat · TechCrunch |
| **AI 模型** | GPT-4o-mini（新聞摘要）· GPT-4o（戰報分析） |
| **去重複** | GitHub Actions Cache 跨天保留已推播標題 hash |
| **報告架構** | GPT-4o → JSON → Python HTML 模板 |
| **部署** | GitHub Actions + GitHub Pages + Cloudflare Workers |
| **推播** | Telegram Bot API（多人 · HTML + 純文字 fallback） |

---

<p align="center">
  <sub>Built with ❤️ by Claude × GitHub Actions × OpenAI × Cloudflare Workers</sub>
</p>

# 🤖 Daily News + VoteFlux Intelligence Bot
> 每天早上 08:00 準時推播新聞摘要與預測市場競品戰報；每週一早上 08:00 推播預測市場週報。全程零人工介入。

---

## ✨ 功能總覽

| Bot | 說明 | AI 模型 | 輸出 | 排程 |
|-----|------|---------|------|------|
| 📰 **每日新聞摘要** | 台灣綜合 · 國際 · 科技 · AI · 財經 | GPT-4o-mini | Telegram 訊息（多人推播） | 每天 08:00 |
| 📊 **VoteFlux 每日戰報** | 預測市場競品分析（資深玩家視角） | GPT-4o-mini | GitHub Pages + Telegram 連結 | 每天 08:00 |
| 🎰 **預測市場週報** | 老司機真心話：趨勢 · 比價 · 社群 · 埋伏建議 | GPT-4o-mini | GitHub Pages + Telegram 連結 | 每週一 08:00 |

---

## 🏗️ 系統架構

```
┌──────────────────────────────────────────────────────────────┐
│  ⏰ Cloudflare Workers Cron                                   │
│                                                              │
│  daily-bot-trigger     每天 UTC 00:00（台灣 08:00）           │
│  weekly-report-trigger 每週一 UTC 00:00（台灣 08:00）         │
└──────────┬──────────────────────────────┬────────────────────┘
           ▼                              ▼
┌──────────────────────┐   ┌─────────────────────────────────────┐
│  📰 每日新聞推播       │   │  📊 VoteFlux 每日戰報                │
│  RSS → 過濾去重       │   │  GPT-4o-mini (JSON)                 │
│  → GPT-4o-mini 摘要  │   │  → Python HTML → GitHub Pages       │
│  → Telegram 推播      │   │  → Telegram 連結                     │
└──────────────────────┘   └─────────────────────────────────────┘
                                          ▼（每週一）
                            ┌─────────────────────────────────────┐
                            │  🎰 預測市場週報                      │
                            │  GPT-4o-mini (JSON)                 │
                            │  → Python HTML → GitHub Pages       │
                            │  → Telegram 連結                     │
                            └─────────────────────────────────────┘
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
| 🔍 **DAILY DISCOVERY** | 三步驟競爭選拔：候選池最活躍 vs AI 場外自選，勝出者登場 + 落選理由 |
| 📊 **競品評分總覽** | 6 大平台 × 6 固定維度（流動性深度 · 費用結構 · 出入金便利性 · 盤口豐富度 · 監管合規 · 介面體驗），1-10 分顏色標示 |
| 🔬 **各平台詳細點評** | 每個維度的分數與一句話犀利點評 + 總結 |
| 📝 **今日觀察與碎碎念** | 第一人稱的市場觀察，像老手寫交易日記 |
| ⚔️ **給 VoteFlux 的建議** | 站在老玩家立場的實際可執行建議 |

### 競品清單

| # | 平台 | 類型 |
|---|------|------|
| 1 | **Polymarket** | 鏈上預測市場龍頭 |
| 2 | **Kalshi** | 美國 CFTC 合規 |
| 3 | **VoteFlux** | 主體分析對象 |
| 4 | **Hyperliquid** | Outcome Trading |
| 5 | **Predict.fun** | DeFi 生息預測 |
| 6 | **DAILY DISCOVERY** | 三步驟競爭選拔（見下方） |

### DAILY DISCOVERY 選拔機制
每天透過三步驟競爭決定當日 DAILY DISCOVERY：
1. **步驟一**：從候選池挑出「今天最活躍」的平台（依交易量、社群熱度、新功能、重大事件等）
2. **步驟二**：AI 在候選池外主動找一個「近期值得關注」的平台
3. **步驟三**：兩者比較，選出更活躍的那個登場，並在報告中說明落選原因

**候選池**：Metaculus · Manifold Markets · Hedgehog Markets · PredictIt · Drift Protocol · Azuro · PlotX · Zeitgeist · Omen · Futuur · Smarkets · Betfair Exchange · Insight Prediction · Iowa Electronic Markets · Fantasy Top · Thales Market · Overtime Markets

### 分析維度（固定 6 項）

| 維度 | 說明 |
|------|------|
| **流動性深度** | 最影響實際交易體驗 |
| **費用結構** | 直接影響獲利 |
| **出入金便利性** | 東南亞市場特別重要 |
| **盤口豐富度** | 決定用戶黏著度 |
| **監管合規** | 影響平台長期生存 |
| **介面體驗** | 新用戶轉換率關鍵 |

---

## 🎰 預測市場週報：老司機的真心話

以一位**跨平台獵人、十年老司機**的第一人稱視角撰寫，犀利、大白話、直言不諱，比起新聞更看重「錢流向哪裡」。每週一發布，涵蓋過去 7 天全球市場動態。

### 週報內容

| 區塊 | 內容 |
|------|------|
| 🌊 **本週大趨勢** | 一句話點破本週市場情緒，3~4 條具體資金流向觀察 |
| 🗺️ **跨平台比價地圖** | 掃描 Polymarket · Kalshi · VoteFlux · ForecastEx，找出同題目跨平台賠率差異與划算的一家 |
| 👻 **社群風向與鬼故事** | X（Twitter）· Reddit 大戶動向、盤口異常、社群爭議 |
| ⚔️ **下週埋伏建議** | 哪邊可進場、哪邊送錢、哪邊死路一條，直接給結論 |

### 寫作風格
所有專有術語一律翻成大白話：
- 「流動性不足」→「沒人玩，買了賣不掉，小心變壁紙」
- 「套利機會」→「這家賣 10 塊那家賣 12 塊，兩邊跑穩賺」
- 「深度不夠」→「大單一砸就崩，不適合大戶玩」

### 週報網址格式
每週 Telegram 推播連結即為當週固定網址：
```
https://jackylin-mk.github.io/daily-news-bot/weekly-YYYY-MM-DD.html
```

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

### Step 7 ─ 部署 Cloudflare Workers

需建立**兩個獨立 Worker**，共用同一組 GitHub Token。

#### Worker 1：daily-bot-trigger（每日觸發）
1. 註冊 [dash.cloudflare.com](https://dash.cloudflare.com/)（免費）
2. Workers & Pages → Create application → Start with Hello World
3. Worker name：`daily-bot-trigger` → Deploy
4. Edit code → 貼上 `cloudflare-worker/worker.js` 內容 → Deploy
5. Settings → Trigger Events → Cron Triggers → 新增：`0 0 * * *`
6. Settings → Variables and Secrets → 新增：

   | 名稱 | 值 |
   |------|-----|
   | `GITHUB_OWNER` | 你的 GitHub 帳號 |
   | `GITHUB_REPO` | `daily-news-bot` |
   | `GITHUB_TOKEN` | GitHub Personal Access Token |

#### Worker 2：weekly-report-trigger（週報觸發）
1. 同上步驟建立，Worker name：`weekly-report-trigger`
2. Edit code → 貼上 `cloudflare-worker/weekly-worker.js` 內容 → Deploy
3. Settings → Trigger Events → Cron Triggers → 新增：`0 0 * * 1`（每週一）
4. Settings → Variables and Secrets → 新增同樣三個變數（`GITHUB_TOKEN` 同一組即可）

### Step 8 ─ 產生 GitHub Personal Access Token
1. 到 [github.com/settings/tokens?type=beta](https://github.com/settings/tokens?type=beta)
2. **Generate new token** → Fine-grained token
3. Repository access → **Only select repositories** → 選 `daily-news-bot`
4. Permissions → **Actions** → **Read and write**
5. Generate → 複製貼到兩個 Cloudflare Worker 的 `GITHUB_TOKEN`

> ⚠️ Token 加密後無法查看明文。若需要同時設定兩個 Worker，請在產生後立刻複製，或之後到 GitHub 對同一個 token 點 **Regenerate**，再同步更新兩個 Worker。

### Step 9 ─ 測試 🎉
- **手動測試**：GitHub Actions 頁面 → 選擇對應 workflow → Run workflow
- **週報手動觸發**：打開 `weekly-report-trigger` Worker URL + `/trigger`

---

## ⚙️ 自訂設定

### 修改推播時間
編輯對應 Cloudflare Worker 的 **Cron Triggers**：

| 台灣時間 | cron |
|---------|------|
| 07:00 | `0 23 * * *` |
| **08:00** | **`0 0 * * *`** ← 目前設定 |
| 09:00 | `0 1 * * *` |
| 12:00 | `0 4 * * *` |

週報固定每週一，如需改為其他星期：`0 0 * * 2`（週二）、`0 0 * * 5`（週五）

### 修改新聞來源
編輯 `news_bot.py` 中的 `RSS_FEEDS`。英文來源記得同步加入 `EN_FEEDS`（不做日期過濾）。

### 新增推播對象
編輯 GitHub Secret `TELEGRAM_CHAT_ID`，用逗號加入新的 Chat ID。

---

## 📁 檔案結構

```
daily-news-bot/
├── 📄 news_bot.py                        # 每日新聞摘要 Bot
├── 📄 voteflux_daily.py                  # VoteFlux 每日戰報 Bot
├── 📄 voteflux_weekly.py                 # 預測市場週報 Bot
├── 📄 README.md
├── 📂 cloudflare-worker/
│   ├── worker.js                          # 每日觸發器
│   └── weekly-worker.js                   # 週報觸發器
└── 📂 .github/workflows/
    ├── daily-news.yml                     # Action: 每日新聞推播
    ├── voteflux-report.yml                # Action: VoteFlux 每日戰報
    └── voteflux-weekly-report.yml         # Action: 預測市場週報
```

> `reports/` 資料夾由 GitHub Actions 自動產生並部署到 GitHub Pages，不會出現在 repo 檔案列表中。

---

## 💰 費用估算

| 項目 | 費用 |
|------|------|
| Cloudflare Workers（×2） | ✅ 免費（每日 10 萬次請求） |
| GitHub Actions | ✅ 免費（每月 2,000 分鐘） |
| GitHub Pages | ✅ 免費 |
| Telegram Bot API | ✅ 免費 |
| OpenAI API（日報 + 週報） | ~$0.01 - $0.02 / 天 |

> **💡 每月約 $0.3 ~ $0.6 美元**

---

## 🛠️ 技術細節

| 項目 | 說明 |
|------|------|
| **語言** | Python 3.12（零外部套件）+ JavaScript（Worker） |
| **排程** | Cloudflare Workers Cron（秒級精準） |
| **新聞來源** | 自由時報 · 中央社 · ETtoday · iThome · 科技新報 · The Verge · VentureBeat · TechCrunch |
| **AI 模型** | GPT-4o-mini（新聞摘要 + 日報分析 + 週報撰寫） |
| **去重複** | GitHub Actions Cache 跨天保留已推播標題 hash |
| **報告架構** | GPT-4o-mini → JSON → Python HTML 模板 → GitHub Pages artifact 部署 |
| **部署** | GitHub Actions + GitHub Pages + Cloudflare Workers |
| **推播** | Telegram Bot API（多人 · HTML + 純文字 fallback） |

---

<p align="center">
  <sub>Built with ❤️ by Claude × GitHub Actions × OpenAI × Cloudflare Workers</sub>
</p>

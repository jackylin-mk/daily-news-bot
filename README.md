# 🤖 Daily News + VoteFlux Intelligence Bot

> 每天早上自動推播新聞摘要與預測市場競品戰報到 Telegram，零人工介入。

---

## ✨ 功能總覽

| Bot | 說明 | AI 模型 | 輸出 |
|-----|------|---------|------|
| 📰 **每日新聞摘要** | 台灣綜合 · 國際 · 科技 · 財經 | GPT-4o-mini | Telegram 訊息 |
| 📊 **VoteFlux 每日戰報** | 預測市場競品分析（資深玩家視角） | GPT-4o | GitHub Pages + Telegram 連結 |

---

## 🏗️ 系統架構

```
┌──────────────────────────────────────────────────────────┐
│  📰 News Bot                                             │
│  RSS 新聞來源 → GPT-4o-mini 摘要 → Telegram 推播         │
├──────────────────────────────────────────────────────────┤
│  📊 VoteFlux Bot                                         │
│  GPT-4o 分析 (JSON) → Python 組裝 HTML → GitHub Pages    │
│                                          → Telegram 連結  │
└──────────────────────────────────────────────────────────┘
                          ⬆
            GitHub Actions ─ 每日 08:00 (台灣時間)
```

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

每日報告固定分析 6 個平台：

| # | 平台 | 類型 |
|---|------|------|
| 1 | **Polymarket** | 鏈上預測市場龍頭 |
| 2 | **Kalshi** | 美國 CFTC 合規 |
| 3 | **VoteFlux** | 主體分析對象 |
| 4 | **Hyperliquid** | Outcome Trading |
| 5 | **Predict.fun** | DeFi 生息預測 |
| 6 | **每日隨機競品** | 從候選池挑選（見下方） |

### DAILY DISCOVERY 候選池

AI 從以下真實平台中挑選（不限於此清單）：

> Metaculus · Manifold Markets · Hedgehog Markets · PredictIt · Drift Protocol · Azuro · PlotX · Zeitgeist · Omen · Futuur · Smarkets · Betfair Exchange · Insight Prediction · Iowa Electronic Markets · Fantasy Top · Thales Market · Overtime Markets

### 分析維度

由 AI 每天自行決定 4-6 個最值得關注的面向，可能包含但不限於：

> 流動性深度 · 出入金便利性 · 手續費/滑點 · 盤口種類豐富度 · 結算速度 · UX/UI 體驗 · 安全性 · 監管合規 · 社群活躍度 ……

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
| `TELEGRAM_CHAT_ID` | Chat ID |
| `OPENAI_API_KEY` | OpenAI API Key |

### Step 6 ─ 啟用 GitHub Pages

**Settings → Pages → Source** 選擇 **GitHub Actions** → 儲存

### Step 7 ─ 測試 🎉

到 **Actions** 分頁，分別手動執行：

- `每日新聞推播` → 確認 Telegram 收到新聞摘要
- `VoteFlux 每日戰報` → 確認 Telegram 收到報告連結

---

## ⚙️ 自訂設定

### 修改推播時間

編輯 `.github/workflows/` 裡的 cron：

```yaml
schedule:
  - cron: '0 0 * * *'   # UTC 00:00 = 台灣 08:00
```

| 台灣時間 | cron |
|---------|------|
| 07:00 | `0 23 * * *` |
| **08:00** | **`0 0 * * *`** ← 目前設定 |
| 09:00 | `0 1 * * *` |
| 12:00 | `0 4 * * *` |

> ⚠️ GitHub Actions 排程可能有 5~30 分鐘延遲，這是免費方案的已知限制。

### 修改新聞來源

編輯 `news_bot.py` 中的 `RSS_FEEDS` 字典。

### 修改戰報風格

編輯 `voteflux_bot.py` 中的 `SYSTEM_PROMPT`（角色設定）和 `generate_report_data()` 內的 prompt（報告指令）。

### 修改 DAILY DISCOVERY 候選池

編輯 `voteflux_bot.py` 中 prompt 裡的候選平台清單，新增或移除平台。

---

## 📁 檔案結構

```
daily-news-bot/
├── 📄 news_bot.py                        # 每日新聞摘要 Bot
├── 📄 voteflux_bot.py                    # VoteFlux 每日戰報 Bot
├── 📄 README.md
├── 📂 reports/                            # ← 自動產生，不需手動建立
│   ├── index.html                         #    跳轉最新報告
│   └── voteflux-YYYY-MM-DD.html          #    每日 HTML 報告
└── 📂 .github/workflows/
    ├── daily-news.yml                     # Action: 每日新聞推播
    └── voteflux-report.yml                # Action: VoteFlux 戰報 + GitHub Pages
```

---

## 💰 費用估算

| 項目 | 費用 |
|------|------|
| GitHub Actions | ✅ 免費（每月 2,000 分鐘） |
| GitHub Pages | ✅ 免費 |
| Telegram Bot API | ✅ 免費 |
| OpenAI API | ~$0.03 - $0.06 / 天 |

> **💡 每月約 $1 ~ $2 美元**

---

## 🛠️ 技術細節

| 項目 | 說明 |
|------|------|
| **語言** | Python 3.12（零外部套件依賴） |
| **新聞來源** | 自由時報 · 中央社 · ETtoday · iThome · 科技新報 等 RSS |
| **AI 模型** | GPT-4o-mini（新聞摘要）· GPT-4o（戰報分析） |
| **報告架構** | GPT-4o → JSON 資料 → Python 組裝 HTML 模板 |
| **部署** | GitHub Actions 排程 + GitHub Pages 靜態托管 |
| **推播** | Telegram Bot API（HTML 格式 + 純文字 fallback） |

---

<p align="center">
  <sub>Built with ❤️ by Claude × GitHub Actions × OpenAI</sub>
</p>

# 🤖 Daily News + VoteFlux Intelligence Bot

> 每天早上自動推播新聞摘要與預測市場競品分析到 Telegram，零人工介入。

---

## ✨ 功能總覽

| 🤖 Bot | 說明 | AI 模型 | 輸出 |
|---------|------|---------|------|
| **📰 每日新聞摘要** | 台灣綜合 · 國際 · 科技 · 財經 | GPT-4o-mini | Telegram 訊息 |
| **📊 VoteFlux 每日戰報** | 預測市場競品分析報告 | GPT-4o | GitHub Pages + Telegram 連結 |

---

## 🏗️ 系統架構

```
┌──────────────────────────────────────────────────────┐
│  📰 News Bot                                         │
│  RSS 新聞來源 → GPT-4o-mini 摘要 → Telegram 推播     │
├──────────────────────────────────────────────────────┤
│  📊 VoteFlux Bot                                     │
│  GPT-4o 分析 (JSON) → Python 組裝 HTML → GitHub Pages│
│                                        → Telegram 連結│
└──────────────────────────────────────────────────────┘
                        ⬆
          GitHub Actions ─ 每日 08:00 (台灣時間)
```

---

## 📡 VoteFlux 戰報內容

每日自動產生的 Dark Mode HTML 報告包含：

| 區塊 | 內容 |
|------|------|
| 🔍 **DAILY DISCOVERY** | 每天發現一個新的預測市場平台 + 專業點評 |
| 📊 **六大平台深度分析** | VoteFlux / Kalshi / Hyperliquid / Predict.fun / Polymarket + 隨機競品 |
| 🎧 **客服功能評分表** | 即時對話框 · 通訊軟體客服 · Email 客服 |
| ⚔️ **戰略行動建議** | 結合合規、Outcome Trading、DeFi 生息三大邏輯 |
| 🌏 **目標市場預測題目** | 印度 · 孟加拉 · 越南 · 馬來西亞 · 菲律賓 · 泰國，各 2 題 |

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

到 repo 的 **Settings → Secrets and variables → Actions**，新增：

| Secret 名稱 | 值 |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot Token |
| `TELEGRAM_CHAT_ID` | Chat ID |
| `OPENAI_API_KEY` | OpenAI API Key |

### Step 6 ─ 啟用 GitHub Pages

**Settings → Pages → Source** 選擇 **GitHub Actions** → 儲存

### Step 7 ─ 測試 🎉

到 **Actions** 分頁，分別手動執行兩個 Workflow：
- `每日新聞推播` → 確認 Telegram 收到新聞
- `VoteFlux 每日戰報` → 確認 Telegram 收到報告連結

---

## ⚙️ 自訂設定

### 修改推播時間

編輯 `.github/workflows/` 裡的 cron 設定：

```yaml
schedule:
  - cron: '0 0 * * *'   # UTC 00:00 = 台灣 08:00
```

| 台灣時間 | cron 設定 |
|---------|-----------|
| 07:00 | `0 23 * * *` |
| **08:00** | **`0 0 * * *`** ← 目前設定 |
| 09:00 | `0 1 * * *` |
| 12:00 | `0 4 * * *` |

> ⚠️ GitHub Actions 排程可能有 5~30 分鐘延遲，這是免費方案的已知限制。

### 修改新聞來源

編輯 `news_bot.py` 中的 `RSS_FEEDS` 字典，新增或移除 RSS 來源。

### 修改戰報 Prompt

編輯 `voteflux_bot.py` 中的 `generate_report_data()` 函式內的 prompt。

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
| GitHub Actions | ✅ 免費 (每月 2,000 分鐘) |
| GitHub Pages | ✅ 免費 |
| Telegram Bot API | ✅ 免費 |
| OpenAI API (GPT-4o-mini × 1 + GPT-4o × 1 / 天) | ~$0.03 - $0.06 / 天 |

> **💡 每月約 $1 ~ $2 美元**

---

## 🛠️ 技術細節

- **語言**：Python 3.12（無外部套件依賴）
- **新聞來源**：自由時報、中央社、ETtoday、iThome、科技新報 等 RSS
- **AI 摘要**：OpenAI GPT-4o-mini（新聞）/ GPT-4o（戰報）
- **報告架構**：GPT-4o 產生 JSON → Python 組裝 HTML 模板（避免 AI 拒絕產生程式碼）
- **部署**：GitHub Actions 定時排程 + GitHub Pages 靜態托管
- **推播**：Telegram Bot API（支援 HTML 格式 + 純文字 fallback）

---

<p align="center">
  <sub>Built with ❤️ by Claude × GitHub Actions × OpenAI</sub>
</p>

# 📰 每日新聞摘要 Telegram Bot

# 📰 每日新聞 + VoteFlux 戰報 Telegram Bot

每天早上自動推播兩份報告到 Telegram：

1. **📰 每日新聞摘要** — 台灣綜合、國際、科技、財經新聞，由 GPT-4o-mini 整理重點
2. **🤖 VoteFlux 每日戰報** — 預測市場競品分析、評分表、戰略建議、目標市場題目

VoteFlux 戰報同時產生完整 HTML 報告，部署到 GitHub Pages 供瀏覽。

## 🏗️ 架構

```
┌─ 新聞 Bot ──────────────────────────────────┐
│  RSS 新聞來源 → GPT-4o-mini 摘要 → Telegram  │
└─────────────────────────────────────────────┘

┌─ VoteFlux Bot ──────────────────────────────┐
│  GPT-4o 完整分析 → HTML 報告 → GitHub Pages  │
│  GPT-4o-mini 摘要 → Telegram（附報告連結）     │
└─────────────────────────────────────────────┘
           ↑
  GitHub Actions 每日 08:00 (台灣時間) 排程
```
                    ↑
           GitHub Actions 每日排程
```

## 🚀 部署步驟

### 1️⃣ 建立 Telegram Bot

1. 在 Telegram 搜尋 **@BotFather**，傳送 `/newbot`
2. 設定 Bot 名稱和 username（username 需以 `bot` 結尾）
3. 記下回傳的 **Bot Token**

### 2️⃣ 取得 Chat ID

1. 開啟你的 Bot，按 **Start**，傳一則訊息
2. 瀏覽器打開：`https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
3. 找到 `"chat":{"id": 數字}` 中的數字，就是你的 **Chat ID**

### 3️⃣ 取得 OpenAI API Key

1. 前往 [platform.openai.com](https://platform.openai.com/)
2. 登入後，到 API Keys 頁面建立一組 Key

### 4️⃣ 部署到 GitHub

1. 在 GitHub 建立一個新的 **Public** repo（GitHub Pages 免費版需要 Public）
2. 把本專案的檔案推上去：
   ```bash
   git init
   git add .
   git commit -m "初始化每日新聞 + VoteFlux Bot"
   git remote add origin https://github.com/你的帳號/你的repo.git
   git push -u origin main
   ```

3. 到 repo 的 **Settings → Secrets and variables → Actions**，新增三個 Secret：

   | Secret 名稱 | 值 |
   |---|---|
   | `TELEGRAM_BOT_TOKEN` | 你的 Bot Token |
   | `TELEGRAM_CHAT_ID` | 你的 Chat ID |
   | `OPENAI_API_KEY` | 你的 OpenAI API Key |

### 5️⃣ 啟用 GitHub Pages

1. 到 repo 的 **Settings → Pages**
2. Source 選擇 **GitHub Actions**
3. 儲存

### 6️⃣ 測試

到 repo 的 **Actions** 分頁 → 選擇「每日新聞推播」→ 點 **Run workflow** 手動執行一次，確認 Telegram 有收到訊息。

## ⚙️ 自訂設定

### 修改推播時間

編輯 `.github/workflows/daily-news.yml` 中的 cron：

```yaml
schedule:
  - cron: '0 0 * * *'  # UTC 00:00 = 台灣 08:00
```

常用時間對照：
| 台灣時間 | UTC cron |
|---------|----------|
| 07:00 | `0 23 * * *` |
| 08:00 | `0 0 * * *` |
| 09:00 | `0 1 * * *` |

### 修改新聞來源

編輯 `news_bot.py` 中的 `RSS_FEEDS` 字典，可以新增或移除 RSS 來源。

### 修改摘要風格

編輯 `news_bot.py` 中的 `build_prompt()` 函式，調整給 Claude 的 prompt。

## 💰 費用估算

| 項目 | 費用 |
|------|------|
| GitHub Actions | ✅ 免費（公開/私人 repo 每月 2000 分鐘） |
| Telegram Bot API | ✅ 免費 |
| OpenAI API | 約 $0.03-0.06 / 天（新聞用 mini + 戰報用 GPT-4o） |

**每月約 $1 ~ $2 美元**，非常便宜。

## 📁 檔案結構

```
daily-news-bot/
├── news_bot.py                    # 每日新聞摘要
├── voteflux_bot.py                # VoteFlux 每日戰報
├── reports/                       # HTML 報告（自動產生，部署到 GitHub Pages）
│   ├── index.html                 # 自動跳轉最新報告
│   └── voteflux-YYYY-MM-DD.html  # 每日報告
├── .github/
│   └── workflows/
│       └── daily-news.yml         # GitHub Actions 排程
└── README.md                      # 本文件
```

## 📡 VoteFlux 戰報內容

每日自動產生的戰報包含：

- **DAILY DISCOVERY** — 每天發現一個新的預測市場平台
- **六大平台深度分析** — VoteFlux / Kalshi / Hyperliquid / Predict.fun / Polymarket + 隨機競品
- **多維度評分表（1-10）** — ADV、流動性、費率滑點、盤口多樣性、客服
- **戰略行動建議** — 結合合規、Outcome Trading、DeFi 生息三大邏輯
- **目標市場預測題目** — 印度、孟加拉、越南、馬來西亞、菲律賓、泰國各 2 題

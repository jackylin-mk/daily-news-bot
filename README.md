# 🤖 Daily News + VoteFlux Intelligence Bot
> 每天早上 08:00 準時推播新聞摘要；每週一早上 08:00 推播競品週報與預測市場週報。全程零人工介入。

---

## ✨ 功能總覽

| Bot | 說明 | AI 模型 | 輸出 | 排程 |
|-----|------|---------|------|------|
| 📰 **每日新聞摘要（付費版）** | 台灣綜合 · 國際 · 科技 · AI · 財經 · 娛樂 | GPT-4o-mini | Telegram 訊息 | 每天 08:00 |
| 📰 **每日新聞摘要（免費版）** | 台灣綜合 · 國際 · 科技 · AI · 財經 · 娛樂 | Gemini 2.5 Flash | Telegram 訊息 | 每天 08:00 |
| 📊 **VoteFlux 競品週報** | 預測市場競品分析（資深玩家視角） | GPT-4o-mini | GitHub Pages + Telegram 連結 | 每週一 08:00 |
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
           ▼ 每天                          ▼ 每週一
┌──────────────────────┐   ┌─────────────────────────────────────┐
│  📰 每日新聞推播       │   │  📊 VoteFlux 競品週報                │
│  RSS → 過濾去重       │   │  GPT-4o-mini (JSON)                 │
│  → AI 摘要           │   │  → Python HTML → GitHub Pages       │
│  → Telegram 推播      │   │  → Telegram 連結                     │
└──────────────────────┘   ├─────────────────────────────────────┤
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

提供**付費版**（OpenAI）與**免費版**（Gemini）兩個版本，功能相同，差別只在 AI 模型。

### 新聞分類與來源

| 分類 | RSS 來源 |
|------|---------|
| 🇹🇼 台灣綜合 | 自由時報 · ETtoday |
| 🌍 國際新聞 | 自由時報國際 · 中央社 |
| 💻 科技新聞 | iThome · 科技新報 |
| 🤖 AI 新聞 | The Verge AI · VentureBeat AI · TechCrunch AI · OpenAI · Google AI · DeepMind · HuggingFace · CNA |
| 💰 財經新聞 | 自由時報財經 · 中央社財經 |
| 🎭 娛樂休閒 | 自由時報娛樂 · ETtoday星光（免費版限定） |

### 新聞過濾機制
- **日期過濾**：只保留今天（台灣時間）發布的新聞；英文來源不做日期過濾
- **去重複**：透過 GitHub Actions Cache 跨天記錄已推播標題，避免重複出現
- **黑名單**：標題含特定關鍵字的新聞直接跳過（可在 `TITLE_BLACKLIST` 自行新增）
- **手動測試模式**：`workflow_dispatch` 手動觸發時自動停用去重複，方便反覆測試

### 版本比較

| | 付費版 `news_bot.py` | 免費版 `news_bot_gemini.py` |
|--|--|--|
| AI 模型 | GPT-4o-mini | Gemini 2.5 Flash |
| 每月費用 | ~$0.3 美元 | 完全免費 |
| API 呼叫次數/天 | 1 次（所有分類一起） | 6 次（每分類各 1 次） |
| 新聞分類 | 台灣 · 國際 · 科技 · AI · 財經 · 娛樂 | 台灣 · 國際 · 科技 · AI · 財經 · 娛樂 |
| 摘要品質 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |

---

## 📊 VoteFlux 競品週報

以一位**在預測市場打滾超過 10 年的資深玩家**第一人稱視角撰寫，風格直接、犀利、用數據和親身經驗說話。每週一發布。

### 報告內容

| 區塊 | 內容 |
|------|------|
| 🔍 **WEEKLY DISCOVERY** | 三步驟競爭選拔：候選池最活躍 vs AI 場外自選，勝出者登場 + 落選理由 |
| 📊 **競品評分總覽** | 6 大平台 × 6 固定維度（流動性深度 · 費用結構 · 出入金便利性 · 盤口豐富度 · 監管合規 · 介面體驗），1-10 分顏色標示 |
| 🔬 **各平台詳細點評** | 每個維度的分數與一句話犀利點評 + 總結 |
| 📝 **本週觀察與碎碎念** | 第一人稱的市場觀察，像老手寫交易日記 |
| ⚔️ **給 VoteFlux 的建議** | 站在老玩家立場的實際可執行建議 |

### 競品清單

| # | 平台 | 類型 |
|---|------|------|
| 1 | **Polymarket** | 鏈上預測市場龍頭 |
| 2 | **Kalshi** | 美國 CFTC 合規 |
| 3 | **VoteFlux** | 主體分析對象 |
| 4 | **Hyperliquid** | Outcome Trading |
| 5 | **Predict.fun** | DeFi 生息預測 |
| 6 | **WEEKLY DISCOVERY** | 三步驟競爭選拔（每週輪換） |

### WEEKLY DISCOVERY 選拔機制
每週透過三步驟競爭決定本週 WEEKLY DISCOVERY：
1. **步驟一**：從候選池挑出「本週最活躍」的平台
2. **步驟二**：AI 在候選池外主動找一個「近期值得關注」的平台
3. **步驟三**：兩者比較，選出更活躍的那個登場，並說明落選原因

**候選池**：Metaculus · Manifold Markets · Hedgehog Markets · PredictIt · Drift Protocol · Azuro · PlotX · Zeitgeist · Omen · Futuur · Smarkets · Betfair Exchange · Insight Prediction · Iowa Electronic Markets · Fantasy Top · Thales Market · Overtime Markets

---

## 🎰 預測市場週報：老司機的真心話

以一位**跨平台獵人、十年老司機**的第一人稱視角撰寫，犀利、大白話、直言不諱。每週一發布，涵蓋過去 7 天全球市場動態。

### 週報內容

| 區塊 | 內容 |
|------|------|
| 🌊 **本週大趨勢** | 一句話點破本週市場情緒，3~4 條具體資金流向觀察 |
| 🗺️ **跨平台比價地圖** | 掃描 Polymarket · Kalshi · VoteFlux · ForecastEx，找出賠率差異與套利機會 |
| 👻 **社群風向與鬼故事** | X · Reddit 大戶動向、盤口異常、社群爭議 |
| ⚔️ **下週埋伏建議** | 哪邊可進場、哪邊送錢、哪邊死路一條，直接給結論 |

### 週報網址格式
每週 Telegram 推播連結即為當週固定網址：
```
https://jackylin-mk.github.io/daily-news-bot/weekly-YYYY-MM-DD.html
```

---

## 🚀 快速部署

> 📖 給朋友分享用的完整新手教學請看 **[QUICKSTART.md](QUICKSTART.md)**

### GitHub Secrets 設定

**Settings → Secrets and variables → Actions**，新增：

| Secret 名稱 | 說明 |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token |
| `TELEGRAM_CHAT_ID` | Chat ID（多人用逗號分隔） |
| `OPENAI_API_KEY` | OpenAI API Key（付費版用） |
| `GEMINI_API_KEY` | Gemini API Key（免費版用） |

### Cloudflare Workers

需建立**兩個獨立 Worker**：

| Worker 名稱 | Cron | 觸發 Workflow |
|---|---|---|
| `daily-bot-trigger` | `0 0 * * *` | 每日新聞 |
| `weekly-report-trigger` | `0 0 * * 1` | VoteFlux 競品週報 + 預測市場週報 |

每個 Worker 都需要設定：`GITHUB_OWNER`、`GITHUB_REPO`、`GITHUB_TOKEN`

### GitHub Token 產生
1. [github.com/settings/tokens?type=beta](https://github.com/settings/tokens?type=beta) → Fine-grained token
2. Repository access → `daily-news-bot`
3. Permissions → **Actions: Read and write**

> ⚠️ Token 加密後無法查看。如需同時設定兩個 Worker，產生後立刻複製，或之後 Regenerate 再同步更新兩個 Worker。

---

## ⚙️ 自訂設定

### 修改推播時間

| 台灣時間 | Cron |
|---------|------|
| 07:00 | `0 23 * * *` |
| **08:00** | **`0 0 * * *`** ← 目前設定 |
| 09:00 | `0 1 * * *` |
| 12:00 | `0 4 * * *` |

### 新增黑名單關鍵字
編輯 `news_bot.py` 或 `news_bot_gemini.py` 中的 `TITLE_BLACKLIST`：
```python
TITLE_BLACKLIST = [
    "冰與火之歌",
    "新增其他關鍵字",  # ← 加這裡
]
```

### 新增推播對象
編輯 GitHub Secret `TELEGRAM_CHAT_ID`，用逗號加入新的 Chat ID。

---

## 📁 檔案結構

```
daily-news-bot/
├── 📄 news_bot.py                        # 每日新聞摘要 Bot（付費版，OpenAI）
├── 📄 news_bot_gemini.py                 # 每日新聞摘要 Bot（免費版，Gemini 2.5 Flash）
├── 📄 voteflux_bot.py                    # VoteFlux 競品週報 Bot
├── 📄 voteflux_weekly.py                 # 預測市場週報 Bot
├── 📄 README.md
├── 📄 QUICKSTART.md                      # 給朋友的新手設定教學
├── 📂 cloudflare-worker/
│   ├── worker.js                          # 每日觸發器
│   └── weekly-worker.js                   # 週報觸發器
└── 📂 .github/workflows/
    ├── daily-news.yml                     # Action: 每日新聞推播
    ├── voteflux-report.yml                # Action: VoteFlux 競品週報
    ├── voteflux-weekly-report.yml         # Action: 預測市場週報
    └── daily-news-gemini-test.yml         # Action: Gemini 免費版測試
```

> `reports/` 資料夾由 GitHub Actions 自動產生並部署到 GitHub Pages，不會出現在 repo 檔案列表中。

---

## 💰 費用估算

| 項目 | 費用 |
|------|------|
| Cloudflare Workers（×2） | ✅ 免費 |
| GitHub Actions | ✅ 免費 |
| GitHub Pages | ✅ 免費 |
| Telegram Bot API | ✅ 免費 |
| Gemini API（免費版新聞摘要） | ✅ 免費 |
| OpenAI API（付費版新聞 + VoteFlux 競品週報 + 預測市場週報） | ~$0.01 / 週 + $0.003 / 天 |

> **💡 每月約 $0.15 ~ $0.3 美元**（僅 OpenAI 用量，週報改為每週後費用減半）

---

## 🛠️ 技術細節

| 項目 | 說明 |
|------|------|
| **語言** | Python 3.12（零外部套件）+ JavaScript（Worker） |
| **排程** | Cloudflare Workers Cron（秒級精準） |
| **AI 模型** | GPT-4o-mini（VoteFlux 競品週報 + 預測市場週報）· Gemini 2.5 Flash（免費版新聞） |
| **去重複** | GitHub Actions Cache 跨天保留已推播標題 hash |
| **報告架構** | AI → JSON → Python HTML 模板 → GitHub Pages artifact 部署 |
| **推播** | Telegram Bot API（多人 · HTML + 純文字 fallback） |

---

<p align="center">
  <sub>Built with ❤️ by Claude × GitHub Actions × OpenAI × Gemini × Cloudflare Workers</sub>
</p>

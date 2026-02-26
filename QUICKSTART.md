# 🚀 新手指引：每天早上自動收到 AI 新聞摘要

> 完全免費 · 不需要寫程式 · 設定一次，每天自動推播到 Telegram

---

## 你會得到什麼？

每天早上 **08:00**，Telegram 自動收到一則 AI 整理好的新聞摘要，涵蓋：

- 🇹🇼 台灣綜合新聞
- 🌍 國際新聞
- 💻 科技新聞
- 🤖 AI 新聞（Claude、Gemini、OpenAI、nVidia 等）
- 💰 財經新聞

---

## 費用

| 項目 | 費用 |
|------|------|
| Telegram Bot | ✅ 免費 |
| GitHub | ✅ 免費 |
| Cloudflare Workers | ✅ 免費 |
| Google Gemini API | ✅ 免費（每天 1,500 次，每天只用 1 次） |
| **合計** | **完全免費** |

---

## 開始之前，你需要準備

- [ ] **Telegram 帳號**（手機 App 即可）
- [ ] **GitHub 帳號**（[免費註冊](https://github.com/signup)）
- [ ] **Google 帳號**（申請 Gemini API 用）
- [ ] **Cloudflare 帳號**（[免費註冊](https://dash.cloudflare.com/sign-up)）

整個設定過程約 **20~30 分鐘**。

---

## Step 1 ─ 建立你的 Telegram Bot

1. 打開 Telegram，搜尋 **@BotFather**
2. 傳送 `/newbot`
3. 輸入 Bot 名稱（例如：`我的每日新聞`）
4. 輸入 Bot username（需以 `bot` 結尾，例如：`my_daily_news_bot`）
5. BotFather 會回傳一串 **Token**，格式像這樣：
   ```
   123456789:ABCdefGHIjklMNOpqrsTUVwxyz
   ```
   **📌 把這串 Token 複製起來備用**

---

## Step 2 ─ 取得你的 Telegram Chat ID

1. 在 Telegram 找到你剛建立的 Bot，按 **Start**，隨便傳一則訊息
2. 用瀏覽器打開以下網址（把 `YOUR_TOKEN` 換成你的 Token）：
   ```
   https://api.telegram.org/botYOUR_TOKEN/getUpdates
   ```
3. 頁面會出現一串 JSON，找到 `"chat":{"id":` 後面的數字：
   ```json
   "chat": {"id": 123456789, ...}
   ```
   **📌 把這個數字複製起來備用（這是你的 Chat ID）**

> 💡 如果頁面是空的，回去 Telegram 再傳一則訊息，然後重新整理頁面。

---

## Step 3 ─ 申請 Gemini API Key（免費）

1. 前往 [aistudio.google.com](https://aistudio.google.com/)
2. 用 Google 帳號登入
3. 點右上角 **Get API Key** → **Create API Key**
4. 選擇 **Create API key in new project**
5. 複製產生的 API Key（格式類似 `AIzaSy...`）

   **📌 把這串 Key 複製起來備用**

> ✅ 免費方案每天有 1,500 次請求額度，這個 Bot 每天只用 1 次，完全夠用。
> 不需要綁信用卡。

---

## Step 4 ─ Fork 專案到你的 GitHub

1. 前往本專案的 GitHub 頁面
2. 點右上角 **Fork** → **Create Fork**
3. 現在你的 GitHub 帳號下有一份自己的副本了

---

## Step 5 ─ 填入你的 API Keys

1. 進入你 Fork 後的 repo
2. 點上方 **Settings** → 左側 **Secrets and variables** → **Actions**
3. 點 **New repository secret**，依序新增以下 3 個：

| Secret 名稱 | 填入的值 |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Step 1 取得的 Bot Token |
| `TELEGRAM_CHAT_ID` | Step 2 取得的 Chat ID |
| `GEMINI_API_KEY` | Step 3 取得的 Gemini API Key |

> 💡 想同時推播給多人？`TELEGRAM_CHAT_ID` 用逗號隔開多個 ID，例如：`123456,789012`

---

## Step 6 ─ 部署 Cloudflare Workers（讓它每天準時自動跑）

> 這個步驟讓 Bot 每天早上 08:00 自動執行，不需要你手動觸發。

1. 登入 [dash.cloudflare.com](https://dash.cloudflare.com/)
2. 左側選 **Workers & Pages** → **Create** → **Hello World** → Deploy
3. Worker 名稱設為 `daily-bot-trigger`
4. 進入 **Edit code**，把程式碼全部替換成專案裡 `cloudflare-worker/worker.js` 的內容 → **Deploy**
5. 到 **Settings → Trigger Events → Cron Triggers** → 新增：`0 0 * * *`
6. 到 **Settings → Variables and Secrets** → 新增以下 3 個：

| 名稱 | 填入的值 |
|------|-----|
| `GITHUB_OWNER` | 你的 GitHub 帳號名稱 |
| `GITHUB_REPO` | `daily-news-bot` |
| `GITHUB_TOKEN` | 下一步取得的 Token |

---

## Step 7 ─ 產生 GitHub Token（讓 Cloudflare 能觸發 GitHub）

1. 前往 [github.com/settings/tokens?type=beta](https://github.com/settings/tokens?type=beta)
2. **Generate new token** → **Fine-grained token**
3. Token name 隨意填，例如 `cloudflare-trigger`
4. **Repository access** → **Only select repositories** → 選 `daily-news-bot`
5. **Permissions** → **Actions** → 選 **Read and write**
6. **Generate token** → 複製 Token

   **📌 把 Token 填入 Step 6 的 `GITHUB_TOKEN`**

---

## Step 8 ─ 測試看看！🎉

1. 前往你的 GitHub repo → 點上方 **Actions**
2. 左側點 **每日新聞推播**
3. 右側點 **Run workflow** → **Run workflow**
4. 等約 1 分鐘，Telegram 應該會收到第一則新聞摘要！

---

## 常見問題

**Q：Telegram 沒收到訊息怎麼辦？**
到 GitHub Actions 頁面，點那次執行記錄，看 log 裡有沒有紅色錯誤訊息。最常見的原因是 Secret 填錯或 Chat ID 有誤。

**Q：可以修改推播時間嗎？**
到 Cloudflare Workers → Cron Triggers 修改，台灣時間 07:00 = `0 23 * * *`，09:00 = `0 1 * * *`。

**Q：可以加自己想看的新聞來源嗎？**
編輯 repo 裡的 `news_bot.py`，在 `RSS_FEEDS` 加入你想要的 RSS 網址即可。

**Q：Gemini 免費額度夠用嗎？**
完全夠。免費方案每天 1,500 次請求，這個 Bot 每天只呼叫 1 次。

---


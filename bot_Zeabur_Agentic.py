import os, sys, re, signal, glob, random, time, json, logging, threading, asyncio
from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler
from http.server import BaseHTTPRequestHandler, HTTPServer
from collections import defaultdict, Counter
from urllib.parse import urlparse, parse_qs
from openai import OpenAI
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
try:
    from telegram import BufferedInputFile
except ImportError:
    BufferedInputFile = None   # fallback handled at send time

try:
    import mysql.connector
    from mysql.connector import pooling as mysql_pooling
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False

try:
    import psycopg2
    PG_AVAILABLE = True
except ImportError:
    PG_AVAILABLE = False

# --- 1. 設定區 ---
INSTANCE_ID     = random.randint(1000, 9999)
OPENAI_API_KEY  = os.environ.get("OPENAI_API_KEY",   "").strip()
TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_TOKEN",   "").strip()
MY_USER_ID      = int(os.environ.get("MY_USER_ID",   "0").strip())
CS_CHAT_ID      = int(os.environ.get("CS_CHAT_ID",   "0").strip())  # 客服通知目標（帳號或群組 chat_id）
DASHBOARD_TOKEN = os.environ.get("DASHBOARD_TOKEN",  "").strip()   # 可選：保護 /api/analytics
_port_raw       = os.environ.get("PORT", "8080")
try:
    DASHBOARD_PORT = int(_port_raw)
except ValueError:
    DASHBOARD_PORT = 8080

client            = OpenAI(api_key=OPENAI_API_KEY)

# AsyncOpenAI client 供 async 函式使用（classify_intent、主對話並行）
try:
    from openai import AsyncOpenAI
    async_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
except ImportError:
    async_client = None
PG_URL            = os.environ.get("PG_URL", "").strip()  # postgresql://user:pass@host:port/db
knowledge_base    = ""   # 全文備用（fallback）
knowledge_chunks  = []   # [{source, text, embedding}] 記憶體快取

# ── KB缺口管理 session（全域，同時只有一個 active session）──
_gap_session: dict = {}
# 結構：{
#   "groups": [{"id":1, "label":"提款流程", "count":7, "rep":"提款要多久？",
#               "questions":[], "draft_zh":"...", "draft_en":"..."}],
#   "status": {1: "pending"|"approved"|"ignored"|"editing"},
#   "days": 7,
#   "edit_target": None   # 正在編輯哪個 group id
# }
knowledge_summary = ""   # 各檔案前 200 字摘要，固定 prefix 供 Prompt Caching

# --- 1b. Phase 1：意圖分類設定 ---

# 需要真人處理的意圖（觸發人工升級）
HUMAN_INTENTS = {"withdrawal", "bet_dispute", "account_op", "payment_issue"}

# 意圖分類 Prompt（極短，token 消耗可忽略）
INTENT_CLASSIFIER_PROMPT = """\
You are a customer service intent classifier for PredictGO, a prediction market platform.
Classify the user message into ONE of these categories. Return ONLY valid JSON, no markdown, no explanation.

Categories:
- faq          # General how-to questions, platform info, rules, referral info, "how do I deposit/withdraw", "how to top up FP"
- withdrawal   # User REPORTING an actual problem: deposit not received, withdrawal stuck, GP balance missing, funds lost
- bet_dispute  # User REPORTING an actual problem: wrong bet result, settlement error, cancelled event dispute
- account_op   # User REPORTING an actual problem: can't login, account locked, KYC failure, security breach
- payment_issue # User REPORTING an actual problem: payment rejected, UPI failed, USDT transfer error
- greeting     # Greetings, small talk, thanks

IMPORTANT: "How to deposit?", "How to withdraw?", "How to top up GP?" = faq, NOT withdrawal or payment_issue.
Only classify as withdrawal/payment_issue/bet_dispute/account_op when the user is reporting something went WRONG.

Response format: {"intent": "<category>", "confidence": <0.0-1.0>}
"""

async def classify_intent(user_message: str) -> dict:
    """
    輕量意圖分類器（async，與 RAG 搜尋並行執行）。
    回傳 {"intent": str, "confidence": float}
    失敗時 fallback 到 {"intent": "faq", "confidence": 0.0}
    """
    try:
        ac = async_client or __import__('openai').AsyncOpenAI(api_key=OPENAI_API_KEY)
        resp = await ac.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": INTENT_CLASSIFIER_PROMPT},
                {"role": "user",   "content": user_message[:300]},
            ],
            temperature=0.0,
            max_tokens=60,
            timeout=10,
        )
        raw = resp.choices[0].message.content.strip()
        result = json.loads(raw)
        return result
    except Exception as e:
        print(f"[{INSTANCE_ID}] ⚠️ classify_intent 失敗，fallback faq: {e}", flush=True)
        return {"intent": "faq", "confidence": 0.0}


async def handle_human_escalation(update: Update, uid: int, un: str, ul: str,
                                   ut: str, intent: str, is_zh: bool):
    """
    Phase 1 人工升級流程：
    1. 立即回覆用戶，告知已建立工單
    2. 推送通知到管理員（含對話上下文）
    3. 記錄到 log
    """
    # ── 生成工單號 ──
    ticket_id = f"CS-{datetime.now().strftime('%Y%m%d%H%M')}-{uid % 10000:04d}"

    # ── 意圖中文標籤 ──
    intent_labels = {
        "withdrawal":    "💸 提款 / 存款問題",
        "bet_dispute":   "🎰 注單 / 結算爭議",
        "account_op":    "👤 帳戶操作問題",
        "payment_issue": "💳 付款問題",
    }
    intent_label = intent_labels.get(intent, "❓ 其他需人工處理")

    # ── 1. 回覆用戶 ──
    bt = "👨‍💻 點我聯繫真人客服" if is_zh else "👨‍💻 Contact Human Support"
    rm = InlineKeyboardMarkup([[InlineKeyboardButton(bt, url="https://t.me/PredictGO_CS")]])

    detected = "zh" if is_zh else "en"
    # 從 update 取語言（handle_human_escalation 無 detected_lang，用 ul 判斷）
    _ul = ul or "en"
    if _ul.startswith("zh"):     detected = "zh"
    elif _ul.startswith("hi"):   detected = "hi"
    elif _ul.startswith("ur") or _ul.startswith("pa"): detected = "ur"

    if detected == "zh":
        user_msg = (
            f"您好！您的問題需要專員協助處理 🙏\n\n"
            f"工單號：<code>{ticket_id}</code>\n"
            f"類型：{intent_label}\n\n"
            f"請點擊下方按鈕直接聯繫我們的客服專員，"
            f"他們已收到您的問題，將盡快為您處理。"
        )
    elif detected == "hi":
        user_msg = (
            f"आपकी समस्या के लिए हमारी सहायता टीम आपकी मदद करेगी 🙏\n\n"
            f"टिकट नंबर: <code>{ticket_id}</code>\n\n"
            f"नीचे दिए बटन पर क्लिक करके हमारी सहायता टीम से संपर्क करें।"
        )
    elif detected == "ur":
        user_msg = (
            f"آپ کی مدد کے لیے ہماری سپورٹ ٹیم موجود ہے 🙏\n\n"
            f"ٹکٹ نمبر: <code>{ticket_id}</code>\n\n"
            f"براہ کرم نیچے دیے گئے بٹن پر کلک کریں۔"
        )
    else:
        user_msg = (
            f"Hi! Your request requires assistance from our support team 🙏\n\n"
            f"Ticket: <code>{ticket_id}</code>\n"
            f"Type: {intent_label}\n\n"
            f"Please click below to connect with our support team — "
            f"they've been notified and will assist you shortly."
        )

    await update.message.reply_text(user_msg, parse_mode='HTML', reply_markup=rm)

    # ── 2. 推送通知到管理員 ──
    # 通知目標：優先用 CS_CHAT_ID（客服帳號/群組），未設定則 fallback 到 MY_USER_ID
    notify_target = CS_CHAT_ID if CS_CHAT_ID else MY_USER_ID
    if notify_target:
        # 帶上近期對話記憶（最近 3 輪）供客服參考
        mem = get_memory(uid)
        context_lines = []
        for m in mem[-6:]:
            role_label = "用戶" if m["role"] == "user" else "Bot"
            context_lines.append(f"  [{role_label}] {m['content'][:100]}")
        context_str = "\n".join(context_lines) if context_lines else "  （無先前對話記錄）"

        admin_msg = (
            f"🔔 <b>新工單 {ticket_id}</b>\n\n"
            f"👤 用戶：{un}（UID: <code>{uid}</code>）\n"
            f"🏷 意圖：{intent_label}\n"
            f"🌐 語言：{ul}\n"
            f"💬 用戶訊息：\n  {ut[:200]}\n\n"
            f"📋 近期對話：\n{context_str}\n\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        try:
            from telegram import Bot
            bot = Bot(token=TELEGRAM_TOKEN)
            await bot.send_message(
                chat_id=notify_target,
                text=admin_msg,
                parse_mode='HTML'
            )
        except Exception as e:
            print(f"[{INSTANCE_ID}] ⚠️ 管理員通知發送失敗: {e}", flush=True)

    # ── 3. 記錄 log ──
    log_conversation(uid, un, ul, ut, f"[Phase1 人工升級｜{ticket_id}｜{intent}]")
    print(f"[{INSTANCE_ID}] 🎫 工單建立：{ticket_id}｜{intent}｜{uid}({un})", flush=True)


# --- 2. MySQL 資料庫 Logger ---
# 連線設定（從 Zeabur 環境變數讀取）
_DB_CONFIG = {
    "host":     os.environ.get("MYSQL_HOST",     "localhost"),
    "port":     int(os.environ.get("MYSQL_PORT", 3306)),
    "user":     os.environ.get("MYSQL_USERNAME", "root"),
    "password": os.environ.get("MYSQL_PASSWORD", ""),
    "database": os.environ.get("MYSQL_DATABASE", "bot_logs"),
    "charset":  "utf8mb4",
}

_db_pool      = None
_db_pool_lock = threading.Lock()

def _get_db_pool():
    global _db_pool
    if not MYSQL_AVAILABLE:
        return None
    with _db_pool_lock:
        if _db_pool is None:
            try:
                _db_pool = mysql_pooling.MySQLConnectionPool(
                    pool_name="bot_pool",
                    pool_size=3,
                    **_DB_CONFIG,
                )
                print(f"[{INSTANCE_ID}] ✅ MySQL 連線池初始化成功", flush=True)
            except Exception as e:
                print(f"[{INSTANCE_ID}] ❌ MySQL 連線池初始化失敗: {e}", flush=True)
        return _db_pool

def _ensure_tables():
    """確保資料表存在（bot 啟動時執行一次）"""
    pool = _get_db_pool()
    if pool is None:
        return
    try:
        conn   = pool.get_connection()
        cursor = conn.cursor()
        # 對話記錄主表
        # UNIQUE KEY (conversation_at, user_id)：防重複寫入的最終保障
        # 即使 log_import_history 失效，INSERT IGNORE 也不會產生重複資料
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversation_logs (
                id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                conversation_at DATETIME     NOT NULL COMMENT '對話時間',
                user_name       VARCHAR(255) NOT NULL COMMENT '使用者名稱',
                user_id         VARCHAR(64)  NOT NULL COMMENT '使用者 ID',
                user_lang       VARCHAR(20)  NOT NULL DEFAULT '' COMMENT '使用者語言（如 zh-hant, zh-hans, en）',
                user_message    TEXT         NOT NULL COMMENT '使用者提問',
                bot_reply       TEXT         NOT NULL COMMENT '機器人回覆',
                created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '寫入時間',
                UNIQUE KEY uq_time_user (conversation_at, user_id),
                INDEX idx_user_id (user_id),
                INDEX idx_user_lang (user_lang)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        # Log 檔掃描快取表（效能用）
        # 記錄「已全數匯入完畢」的 log 檔，避免每次都重新讀取舊檔案
        # 注意：此表只是效能快取，真正防重複靠上方的 UNIQUE KEY + INSERT IGNORE
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS log_import_history (
                id            INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                log_filename  VARCHAR(100) NOT NULL UNIQUE COMMENT '已完整匯入的 log 檔名',
                rows_imported INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '匯入筆數',
                imported_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '完成時間'
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        conn.commit()
        cursor.close()
        conn.close()
        print(f"[{INSTANCE_ID}] ✅ DB 資料表確認完成（conversation_logs + log_import_history）", flush=True)
    except Exception as e:
        print(f"[{INSTANCE_ID}] ❌ _ensure_tables 失敗: {e}", flush=True)

def _get_rotated_log_files() -> list:
    """
    回傳所有「已輪替完成」的 log 檔（排除當前小時的檔案）。
    TimedRotatingFileHandler suffix = %Y-%m-%d_%H，
    輪替後的檔名格式：chat.log.2026-02-23_14
    """
    current = f"chat.log.{datetime.now().strftime('%Y-%m-%d_%H')}"
    files = []
    for fp in sorted(glob.glob(os.path.join(LOG_DIR, "chat.log.*"))):
        fname = os.path.basename(fp)
        if fname != current:
            files.append((fname, fp))
    return files  # [(filename, full_path), ...]

def _parse_log_file_to_rows(filepath: str) -> list:
    """
    解析一個已輪替的 log 檔，回傳可直接 INSERT 的 tuple list：
    [(conversation_at, user_name, user_id, user_lang, user_message, bot_reply), ...]
    """
    rows = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        for block in content.split("─" * 60):
            block = block.strip()
            if not block:
                continue
            try:
                h = re.search(
                    r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] 用戶: (.+?) \(ID: (\d+), Lang: (.+?)\)',
                    block
                )
                q = re.search(r'❓ 問題: (.+)', block)
                r = re.search(r'🤖 回覆: (.+)', block)
                if not h or not q:
                    continue
                rows.append((
                    datetime.strptime(h.group(1), "%Y-%m-%d %H:%M:%S"),
                    h.group(2).strip(),                # user_name
                    h.group(3).strip(),                # user_id
                    h.group(4).strip(),                # user_lang（如 zh-hant, zh-hans, en）
                    q.group(1).strip(),                # user_message
                    r.group(1).strip() if r else "",   # bot_reply
                ))
            except Exception:
                continue
    except Exception as e:
        print(f"[{INSTANCE_ID}] ⚠️ 解析 log 檔失敗 {filepath}: {e}", flush=True)
    return rows

def db_import_rotated_logs():
    """
    掃描已輪替的 log 檔，解析後用 INSERT IGNORE 寫入 conversation_logs。

    雙層防護：
      第一層（效能）：log_import_history 記錄已完整處理的檔案，直接跳過不重複讀取。
      第二層（正確性）：UNIQUE KEY (conversation_at, user_id) + INSERT IGNORE，
        即使第一層失效（如中途中斷），也絕對不會產生重複資料。
    """
    pool = _get_db_pool()
    if pool is None:
        return

    rotated_files = _get_rotated_log_files()
    if not rotated_files:
        return

    try:
        conn   = pool.get_connection()
        cursor = conn.cursor()

        # 一次撈出所有已完整匯入的檔名，避免逐一查詢
        cursor.execute("SELECT log_filename FROM log_import_history")
        already_done = {row[0] for row in cursor.fetchall()}
        for filename, filepath in rotated_files:
            # 第一層：已完整匯入 → 直接跳過，不讀檔
            if filename in already_done:
                continue

            rows = _parse_log_file_to_rows(filepath)
            if not rows:
                # 空檔案也記錄，避免重複掃描
                cursor.execute(
                    "INSERT IGNORE INTO log_import_history (log_filename, rows_imported) VALUES (%s, 0)",
                    (filename,)
                )
                conn.commit()
                continue

            # 第二層：INSERT IGNORE，(conversation_at, user_id) 重複的自動略過
            cursor.executemany("""
                INSERT IGNORE INTO conversation_logs
                    (conversation_at, user_name, user_id, user_lang, user_message, bot_reply)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, rows)

            inserted = cursor.rowcount
            skipped  = len(rows) - inserted
            conn.commit()

            # 無論 inserted 是幾，只要處理完就標記為已完成
            cursor.execute(
                "INSERT IGNORE INTO log_import_history (log_filename, rows_imported) VALUES (%s, %s)",
                (filename, inserted)
            )
            conn.commit()

            if skipped > 0:
                print(f"[{INSTANCE_ID}] 📝 {filename}：新增 {inserted} 筆，略過重複 {skipped} 筆", flush=True)
            else:
                print(f"[{INSTANCE_ID}] 📝 {filename}：新增 {inserted} 筆", flush=True)

        cursor.close()
        conn.close()
    except Exception as e:
        print(f"[{INSTANCE_ID}] ❌ db_import_rotated_logs 失敗: {e}", flush=True)

# --- 2b. 記憶體管理 ---
_mem_lock        = threading.Lock()
user_memories    = {}      # uid -> [{"role":..,"content":..}, ...]
user_last_active = {}      # uid -> datetime

def get_memory(uid: int) -> list:
    with _mem_lock:
        return list(user_memories.get(uid, []))

def update_memory(uid: int, role: str, content: str):
    with _mem_lock:
        user_last_active[uid] = datetime.now()
        mem = user_memories.setdefault(uid, [])
        mem.append({"role": role, "content": content})
        if len(mem) > 10:
            user_memories[uid] = mem[-10:]

def evict_stale_memories(max_idle_hours: int = 24):
    """清除超過 max_idle_hours 未活動的用戶記憶，防止記憶體洩漏"""
    cutoff = datetime.now() - timedelta(hours=max_idle_hours)
    with _mem_lock:
        stale = [uid for uid, t in user_last_active.items() if t < cutoff]
        for uid in stale:
            user_memories.pop(uid, None)
            user_last_active.pop(uid, None)
    if stale:
        pass  # 閒置記憶清除為靜默操作

# --- 3. Log 系統 ---
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

def setup_logger():
    import re as _re
    logger = logging.getLogger("chat_log")
    logger.setLevel(logging.INFO)
    h = TimedRotatingFileHandler(
        filename=os.path.join(LOG_DIR, "chat.log"),
        when="H", interval=1, backupCount=48, encoding="utf-8"
    )
    h.suffix   = "%Y-%m-%d_%H"
    h.extMatch = _re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}$")  # 與 suffix 對應，修正輪替識別
    h.setLevel(logging.INFO)
    h.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(h)
    return logger

def recover_unrotated_logs():
    """
    Redeploy 後補救：檢查 chat.log 內每一行的時間戳，
    找出所有「已跨過整點但尚未輪替」的小時，逐一補包成 chat.log.YYYY-MM-DD_HH。
    完成後把屬於「當前小時」的行留在 chat.log，其餘行清空。
    """
    log_path = os.path.join(LOG_DIR, "chat.log")
    if not os.path.exists(log_path):
        return

    import re
    ts_pat = re.compile(r"\[(\d{4}-\d{2}-\d{2} \d{2}):\d{2}:\d{2}\]")
    now_hour = datetime.now().strftime("%Y-%m-%d_%H")  # 當前小時 key

    # 讀取全部行
    with open(log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    if not lines:
        return

    # 把每行歸屬到對應的小時 key（找不到 timestamp 的行跟著上一行走）
    buckets = {}      # hour_key -> [lines]
    current_key = None
    for line in lines:
        m = ts_pat.search(line)
        if m:
            current_key = m.group(1).replace(" ", "_")   # "2026-02-25_01"
        if current_key:
            buckets.setdefault(current_key, []).append(line)

    # 找出需要補包的小時（非當前小時）
    past_hours = [k for k in buckets if k != now_hour]
    if not past_hours:
        return

    # 逐一寫出補包檔
    for hour_key in sorted(past_hours):
        dest = os.path.join(LOG_DIR, f"chat.log.{hour_key}")
        if os.path.exists(dest):
            # 已存在就 append（避免重複）
            with open(dest, "a", encoding="utf-8") as f:
                f.writelines(buckets[hour_key])
        else:
            with open(dest, "w", encoding="utf-8") as f:
                f.writelines(buckets[hour_key])
        print(f"[{INSTANCE_ID}] 📦 補救輪替 → {os.path.basename(dest)} ({len(buckets[hour_key])} 行)", flush=True)

    # 把 chat.log 只保留當前小時的行（或清空）
    current_lines = buckets.get(now_hour, [])
    with open(log_path, "w", encoding="utf-8") as f:
        f.writelines(current_lines)
    print(f"[{INSTANCE_ID}] ✅ chat.log 保留 {len(current_lines)} 行（當前小時 {now_hour}）", flush=True)


chat_logger = setup_logger()
recover_unrotated_logs()   # Redeploy 後自動補救輪替

def log_conversation(user_id, user_name, user_lang, user_text, bot_reply):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    chat_logger.info(
        f"[{ts}] 用戶: {user_name} (ID: {user_id}, Lang: {user_lang})\n"
        f"  ❓ 問題: {user_text}\n"
        f"  🤖 回覆: {bot_reply}\n{'─'*60}"
    )

# --- 知識庫缺口偵測 ---

# --- 知識庫缺口管理（聚類 / 起草 / 驗證）---

def _cluster_gaps(gaps: list, threshold: float = 0.75) -> list:
    """
    用 embedding cosine similarity 把缺口問題聚類。
    threshold: 同群組的相似度門檻（越高越嚴格）
    回傳 list of groups:
    [{"label": str, "rep": str, "questions": [str], "count": int}, ...]
    """
    if not gaps:
        return []
    questions = [g["question"] for g in gaps]
    try:
        embeddings = _embed(questions)
    except Exception as e:
        print(f"[{INSTANCE_ID}] ⚠️ _cluster_gaps embedding 失敗: {e}", flush=True)
        # fallback：每題獨立一群
        return [{"label": q[:20], "rep": q, "questions": [q], "count": 1}
                for q in questions]

    groups = []   # [{indices: [int], rep_idx: int}]
    assigned = [False] * len(questions)

    for i in range(len(questions)):
        if assigned[i]:
            continue
        group_indices = [i]
        assigned[i] = True
        for j in range(i + 1, len(questions)):
            if assigned[j]:
                continue
            if _cosine(embeddings[i], embeddings[j]) >= threshold:
                group_indices.append(j)
                assigned[j] = True
        groups.append(group_indices)

    result = []
    for g_indices in sorted(groups, key=len, reverse=True):
        qs = [questions[i] for i in g_indices]
        rep = qs[0]   # 代表問題用第一筆（出現最早）
        # 嘗試用最短的問題當代表（更簡潔）
        shortest = min(qs, key=len)
        if len(shortest) >= 4:
            rep = shortest
        result.append({
            "label": rep[:20] + ("…" if len(rep) > 20 else ""),
            "rep":   rep,
            "questions": qs,
            "count": len(qs),
        })
    return result


def _draft_kb_chunk(group: dict, existing_kb_zh: str, existing_kb_en: str) -> tuple[str, str]:
    """
    針對一個缺口群組，生成中英文 KB chunk 草稿。
    同時參考現有知識庫，避免重複，若現有內容存在但措辭不清則標記修改建議。
    回傳 (draft_zh, draft_en)
    """
    questions_str = "\n".join(f"- {q}" for q in group["questions"][:5])
    prompt = f"""You are a knowledge base writer for PredictGO, a prediction market platform on Telegram.

Users asked these questions but the bot couldn't answer them:
{questions_str}

Current knowledge base excerpt (Chinese):
{existing_kb_zh[:3000]}

Current knowledge base excerpt (English):
{existing_kb_en[:3000]}

Tasks:
1. Check if similar content already exists. If yes, suggest an update instead of new content.
2. If no similar content exists, write a new KB chunk.

Output ONLY a JSON object with these exact keys:
{{
  "action": "new" or "update",
  "draft_zh": "中文知識庫 chunk，格式參考現有知識庫的 ## 標題風格，包含 --- 分隔線",
  "draft_en": "English KB chunk, same format as existing KB",
  "note": "brief note in Chinese about what was done or updated"
}}
No explanation outside the JSON."""

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.3,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
        )
        import json as _json
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"^```[a-z]*\n?|\n?```$", "", raw).strip()
        data = _json.loads(raw)
        return data.get("draft_zh", ""), data.get("draft_en", ""), data.get("action", "new"), data.get("note", "")
    except Exception as e:
        print(f"[{INSTANCE_ID}] ⚠️ _draft_kb_chunk 失敗: {e}", flush=True)
        fallback_zh = f"\n\n---\n\n## {group['rep']}\n\n（草稿生成失敗，請手動補充）\n"
        fallback_en = f"\n\n---\n\n## {group['rep']}\n\n（Draft generation failed, please add manually）\n"
        return fallback_zh, fallback_en, "new", "草稿生成失敗"


def _build_full_kb_with_drafts(approved_groups: list) -> dict:
    """
    讀取現有知識庫檔案，把 approved 草稿 append 到對應檔案末尾。
    回傳 {filename: full_content} dict。
    """
    kb_files = {}
    for pattern in ["knowledge/*.txt", "knowledge/*.md"]:
        for fp in sorted(glob.glob(pattern)):
            try:
                with open(fp, 'r', encoding='utf-8') as f:
                    kb_files[os.path.basename(fp)] = f.read()
            except Exception as e:
                print(f"[{INSTANCE_ID}] ⚠️ 讀取知識庫失敗: {fp} — {e}", flush=True)

    for g in approved_groups:
        draft_zh = g.get("draft_zh", "")
        draft_en = g.get("draft_en", "")
        if draft_zh and "notebookLM.txt" in kb_files:
            kb_files["notebookLM.txt"] = kb_files["notebookLM.txt"].rstrip() + "\n\n" + draft_zh.strip() + "\n"
        if draft_en and "notebookLM_en.txt" in kb_files:
            kb_files["notebookLM_en.txt"] = kb_files["notebookLM_en.txt"].rstrip() + "\n\n" + draft_en.strip() + "\n"

    return kb_files


async def _send_full_kb_files(bot, kb_files: dict):
    """已 approve 的草稿合併後，推送完整知識庫檔案給管理員。"""
    target = MY_USER_ID
    if not target:
        return
    await bot.send_message(
        chat_id=target,
        text="✅ <b>所有缺口處理完畢！</b>\n\n以下是已合併草稿的完整知識庫檔案，請直接覆蓋 repo 對應檔案後 git push。",
        parse_mode='HTML'
    )
    for filename, content in kb_files.items():
        try:
            if BufferedInputFile:
                doc = BufferedInputFile(content.encode('utf-8'), filename=filename)
            else:
                import io
                doc = io.BytesIO(content.encode('utf-8'))
                doc.name = filename
            await bot.send_document(
                chat_id=target,
                document=doc,
                caption=f"📎 {filename}"
            )
        except Exception as e:
            print(f"[{INSTANCE_ID}] ❌ 推送檔案失敗 {filename}: {e}", flush=True)


async def _verify_after_rebuild(bot):
    """
    RAG rebuild 完成後自動驗證：
    把所有 approved 群組的代表問題重跑 search_knowledge，
    確認 Top-1 similarity score ≥ 0.5。
    """
    global _gap_session
    approved = [
        g for g in _gap_session.get("groups", [])
        if _gap_session.get("status", {}).get(g["id"]) == "approved"
    ]
    if not approved or not knowledge_chunks:
        return

    target = MY_USER_ID
    if not target:
        return

    lines = ["🔍 <b>知識庫修復驗證結果</b>\n"]
    for g in approved:
        try:
            q_emb = _embed([g["rep"]])[0]
            best_score = max(_cosine(q_emb, c["embedding"]) for c in knowledge_chunks)
            if best_score >= 0.5:
                lines.append(f"✅ #{g['id']}「{g['label']}」— similarity {best_score:.2f} 已修復")
            else:
                lines.append(f"⚠️ #{g['id']}「{g['label']}」— similarity {best_score:.2f} 仍不足，建議再補充")
        except Exception as e:
            lines.append(f"❓ #{g['id']}「{g['label']}」— 驗證失敗: {e}")

    await bot.send_message(
        chat_id=target,
        text="\n".join(lines),
        parse_mode='HTML'
    )
    # 清空 session
    _gap_session = {}
    print(f"[{INSTANCE_ID}] ✅ KB修復驗證完成", flush=True)



# ─────────────────────────────────────────────
# gap_handled：已處理缺口黑名單（MySQL）
# ─────────────────────────────────────────────

def _gap_handled_init():
    """確保 gap_handled table 存在"""
    pool = _get_db_pool()
    if not pool:
        return
    try:
        conn = pool.get_connection()
        cur  = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS gap_handled (
                id           INT AUTO_INCREMENT PRIMARY KEY,
                question_hash VARCHAR(64) NOT NULL UNIQUE,
                rep_question  TEXT        NOT NULL,
                handled_at    DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                action        VARCHAR(16) NOT NULL DEFAULT 'approved',
                INDEX idx_hash (question_hash),
                INDEX idx_handled_at (handled_at)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
        """)
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        print(f"[{INSTANCE_ID}] ⚠️ gap_handled_init 失敗: {e}", flush=True)

def _gap_mark_handled(rep_question: str, action: str = "approved"):
    """將 cluster 代表問題標記為已處理（upsert）"""
    import hashlib
    pool = _get_db_pool()
    if not pool:
        return
    try:
        h    = hashlib.md5(rep_question.strip().lower().encode()).hexdigest()
        conn = pool.get_connection()
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO gap_handled (question_hash, rep_question, action)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE handled_at = CURRENT_TIMESTAMP, action = %s
        """, (h, rep_question.strip(), action, action))
        conn.commit()
        cur.close(); conn.close()
        print(f"[{INSTANCE_ID}] ✅ gap_handled: [{action}] {rep_question[:60]}", flush=True)
    except Exception as e:
        print(f"[{INSTANCE_ID}] ⚠️ gap_mark_handled 失敗: {e}", flush=True)

def _gap_get_handled_hashes(expire_days: int = 30) -> set:
    """回傳未過期的已處理問題 hash set"""
    import hashlib
    pool = _get_db_pool()
    if not pool:
        return set()
    try:
        conn = pool.get_connection()
        cur  = conn.cursor()
        cur.execute("""
            SELECT rep_question FROM gap_handled
            WHERE handled_at >= NOW() - INTERVAL %s DAY
        """, (expire_days,))
        rows = cur.fetchall()
        cur.close(); conn.close()
        return {hashlib.md5(r[0].strip().lower().encode()).hexdigest() for r in rows}
    except Exception as e:
        print(f"[{INSTANCE_ID}] ⚠️ gap_get_handled_hashes 失敗: {e}", flush=True)
        return set()

def detect_kb_gaps(days: int = 7) -> list:
    """
    從 MySQL conversation_logs 撈出最近 N 天含 [KB_GAP] 標記的對話，
    並排除「缺口發生在最後一次知識庫重建之前」的記錄（視為已修復）。

    判斷邏輯：
      從 pgvector kb_meta 讀取 kb_rebuilt_at（最後一次 RAG 重建時間）。
      若缺口的 conversation_at < kb_rebuilt_at，代表知識庫已在缺口後更新過
      → 視為已修復，不列入報告。
      若 kb_rebuilt_at 無法取得，退回保守策略：全部列出。

    回傳 list of dict: [{"at": str, "user": str, "question": str, "reply": str}, ...]
    """
    # ── Step 1：取得最後一次 KB rebuild 時間 ──
    kb_rebuilt_at = None
    try:
        import psycopg2
        PG_URL = os.environ.get("PGVECTOR_URL", "")
        if PG_URL:
            pg = psycopg2.connect(PG_URL)
            cur = pg.cursor()
            cur.execute("SELECT value FROM kb_meta WHERE key = 'kb_rebuilt_at'")
            row = cur.fetchone()
            if row:
                from datetime import datetime as _dt
                kb_rebuilt_at = _dt.strptime(row[0], "%Y-%m-%d %H:%M:%S")
            cur.close(); pg.close()
    except Exception as e:
        print(f"[{INSTANCE_ID}] ⚠️ 無法取得 kb_rebuilt_at: {e}", flush=True)

    # ── Step 2：撈 MySQL 缺口記錄 ──
    pool = _get_db_pool()
    if not pool:
        return []
    try:
        conn = pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT conversation_at, user_name, user_message, bot_reply
            FROM conversation_logs
            WHERE bot_reply LIKE %s
              AND conversation_at >= NOW() - INTERVAL %s DAY
            ORDER BY conversation_at DESC
        """, ("%[KB_GAP]%", days))
        rows = cursor.fetchall()
        cursor.close(); conn.close()

        # ── Step 3：載入已處理黑名單 ──
        import hashlib
        handled_hashes = _gap_get_handled_hashes(expire_days=30)

        result = []
        seen_hashes = set()  # 同一問題去重
        for r in rows:
            gap_time = r["conversation_at"]
            # 若能取得 kb_rebuilt_at，且缺口發生在重建之前 → 已修復，跳過
            if kb_rebuilt_at and gap_time < kb_rebuilt_at:
                continue
            # 已在黑名單 → 跳過
            q_hash = hashlib.md5(r["user_message"].strip().lower().encode()).hexdigest()
            if q_hash in handled_hashes:
                continue
            # 同一問題在這次結果中去重
            if q_hash in seen_hashes:
                continue
            seen_hashes.add(q_hash)
            result.append({
                "at":       str(gap_time),
                "user":     r["user_name"],
                "question": r["user_message"],
                "reply":    r["bot_reply"].replace("[KB_GAP]", "").strip(),
            })
        return result

    except Exception as e:
        print(f"[{INSTANCE_ID}] ❌ detect_kb_gaps 失敗: {e}", flush=True)
        return []

async def send_kb_gap_report(bot, days: int = 7):
    """
    完整知識庫缺口流程：
    1. 偵測缺口 → 2. 聚類 → 3. 起草草稿 → 4. 推送摘要 + 檔案 + Inline Buttons
    """
    global _gap_session
    target = MY_USER_ID
    if not target:
        print(f"[{INSTANCE_ID}] ⚠️ send_kb_gap_report: MY_USER_ID 未設定，跳過", flush=True)
        return

    today = datetime.now().strftime("%Y-%m-%d")
    gaps  = detect_kb_gaps(days)

    if not gaps:
        await bot.send_message(
            chat_id=target,
            text=(f"✅ <b>知識庫缺口報告｜{today}</b>\n\n"
                  f"過去 <b>{days} 天</b>沒有偵測到 bot 無法回答的問題，知識庫覆蓋良好！🎉"),
            parse_mode='HTML'
        )
        return

    # ── 通知開始處理 ──
    await bot.send_message(
        chat_id=target,
        text=f"⏳ 偵測到 <b>{len(gaps)}</b> 筆缺口，正在聚類分析並生成草稿...",
        parse_mode='HTML'
    )

    # ── 聚類 ──
    raw_groups = await asyncio.to_thread(_cluster_gaps, gaps)

    # ── 讀取現有知識庫供草稿參考 ──
    def _read_kb(filename):
        try:
            with open(f"knowledge/{filename}", 'r', encoding='utf-8') as f:
                return f.read()
        except Exception:
            return ""

    kb_zh = await asyncio.to_thread(_read_kb, "notebookLM.txt")
    kb_en = await asyncio.to_thread(_read_kb, "notebookLM_en.txt")

    # ── 為每個群組生成草稿 ──
    groups = []
    for i, rg in enumerate(raw_groups, 1):
        draft_zh, draft_en, action, note = await asyncio.to_thread(
            _draft_kb_chunk, rg, kb_zh, kb_en
        )
        groups.append({
            "id":       i,
            "label":    rg["label"],
            "rep":      rg["rep"],
            "questions": rg["questions"],
            "count":    rg["count"],
            "draft_zh": draft_zh,
            "draft_en": draft_en,
            "action":   action,
            "note":     note,
        })

    # ── 初始化 session ──
    _gap_session = {
        "groups": groups,
        "status": {g["id"]: "pending" for g in groups},
        "days":   days,
        "edit_target": None,
    }

    # ── 組合草稿檔案（所有群組先全部放進去，approve/ignore 後再重推完整版）──
    all_draft_zh = "\n\n".join(g["draft_zh"] for g in groups if g["draft_zh"])
    all_draft_en = "\n\n".join(g["draft_en"] for g in groups if g["draft_en"])

    # ── 推送摘要訊息 ──
    summary_lines = [f"📋 <b>知識庫缺口報告｜{today}</b>",
                     f"過去 <b>{days} 天</b>共 <b>{len(gaps)}</b> 筆，聚類為 <b>{len(groups)}</b> 個群組：\n"]
    for g in groups:
        action_tag = "🆕 新增" if g["action"] == "new" else "✏️ 修改建議"
        summary_lines.append(
            f"<b>#{g['id']}</b>「{g['label']}」— {g['count']} 筆 | {action_tag}\n"
            f"  代表問題：{g['rep']}\n"
            f"  {g['note']}"
        )
    await bot.send_message(
        chat_id=target,
        text="\n".join(summary_lines),
        parse_mode='HTML'
    )

    # ── 推送草稿檔案 ──
    for filename, content in [("gap_draft_zh.txt", all_draft_zh), ("gap_draft_en.txt", all_draft_en)]:
        if not content.strip():
            continue
        try:
            if BufferedInputFile:
                doc = BufferedInputFile(content.encode('utf-8'), filename=filename)
            else:
                import io
                doc = io.BytesIO(content.encode('utf-8'))
                doc.name = filename
            await bot.send_document(
                chat_id=target,
                document=doc,
                caption=f"📎 草稿預覽 — {filename}（請看完再決定 approve / ignore）"
            )
        except Exception as e:
            print(f"[{INSTANCE_ID}] ❌ 推送草稿失敗 {filename}: {e}", flush=True)

    # ── 推送 Inline Buttons ──
    keyboard = []
    # 全部 approve 快捷鍵
    keyboard.append([InlineKeyboardButton("✅ 全部 Approve", callback_data="gap_approve_all")])
    # 每個群組一行
    for g in groups:
        keyboard.append([
            InlineKeyboardButton(f"✅ #{g['id']}", callback_data=f"gap_approve_{g['id']}"),
            InlineKeyboardButton(f"✏️ #{g['id']}", callback_data=f"gap_edit_{g['id']}"),
            InlineKeyboardButton(f"❌ #{g['id']}", callback_data=f"gap_ignore_{g['id']}"),
        ])

    await bot.send_message(
        chat_id=target,
        text="請對每個群組選擇操作：\n✅ Approve　✏️ 優化草稿　❌ 忽略",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    print(f"[{INSTANCE_ID}] 📋 KB缺口報告已推送：{len(gaps)} 筆 → {len(groups)} 群組", flush=True)

# --- 4. Log 分析引擎（資料來源：MySQL conversation_logs）---

def load_all_logs_from_db(days: int = 30) -> list:
    """
    從 MySQL conversation_logs 讀取近 N 天的對話記錄，
    回傳與原 parse_log_entry 相同結構的 dict list，
    讓 run_analysis() 完全不需要改動。
    """
    pool = _get_db_pool()
    if pool is None:
        return []
    try:
        conn   = pool.get_connection()
        cursor = conn.cursor(dictionary=True)
        # 注意：避免在有 %s 參數的 SQL 裡使用 DATE_FORMAT（%% 跳脫問題）
        # 改用 CAST 直接轉字串，再由 Python 端格式化
        cursor.execute("""
            SELECT
                CAST(conversation_at AS CHAR)  AS timestamp,
                user_name,
                user_id,
                user_lang  AS lang,
                user_message AS question,
                bot_reply  AS reply
            FROM conversation_logs
            WHERE conversation_at >= %s
            ORDER BY conversation_at ASC
        """, (datetime.now() - timedelta(days=days),))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        # CAST 回傳格式為 "2026-02-23 04:02:38"，與原 log 格式一致，直接使用
        return rows
    except Exception as e:
        print(f"[{INSTANCE_ID}] ⚠️ load_all_logs_from_db: {e}", flush=True)
        return []

def run_analysis():
    entries = load_all_logs_from_db(30)
    today   = datetime.now()
    daily, hourly = defaultdict(int), defaultdict(int)
    ai_c, hu_c, err_c = 0, 0, 0
    d_ai, d_hu = defaultdict(int), defaultdict(int)
    u_days, d_users = defaultdict(set), defaultdict(set)
    hr_c, tp_c = Counter(), Counter()
    d_topics = defaultdict(lambda: defaultdict(int))  # {date: {cat: count}}
    ts_matrix = []   # [{ts, uid}] — 供前端時區轉換用
    cats = {
        "新手引導": [
            "怎麼玩", "如何玩", "怎麼用", "如何用", "教學", "get started", "how to play",
            "how to use", "如何開始", "第一次", "新手", "入門", "guide", "tutorial",
            "規則", "遊戲規則", "下載 app", "下載app", "怎麼開始",
            "需要下載", "do i need to download",
            "手機可以玩", "電腦也可以玩", "電腦可以玩", "可以用電腦",
            "支援哪些語言", "語言支援", "支援語言", "有哪些語言",
            "註冊",
        ],
        "平台與存取": [
            "voteflux是什麼", "什麼是voteflux", "voteflux 是什麼",
            "mini app", "telegram mini app", "tma",
            "連不上", "打不開", "官網", "網址",
            "登入", "login", "如何登入", "登入方式", "google登入", "登入問題",
            "how to login", "log in",
            "註冊帳號", "如何註冊", "sign up", "register",
            "電腦瀏覽器", "手機瀏覽器", "是否支援電腦", "電腦版", "手機版",
            "desktop version", "desktop browser", "mobile browser",
            "只能用手機", "只能用telegram",
            "not open", "open the page", "cannot open", "page not", "homepage", "not working",
            "app not", "can't open", "unable to open", "not load",
            "平台可信嗎", "平台準確嗎", "正確性", "reliable", "trustworthy", "help", "ratio", "exchange rate",
            "用戶名", "username", "設定用戶名",
            "密碼會被", "密碼安全", "看到密碼", "錢包地址是我專屬", "safe here",
            "prompt", "你的prompt", "system prompt", "聰明", "跟你一樣",
        ],
        "USDT/GP 資金": [
            "usdt", "game points", "game point", "gp", "flux points", "flux point", "fp",
            "入金", "出金", "deposit", "withdraw", "withdrawal", "cash out",
            "提款", "提款需要", "提款流程", "提款時間", "提領",
            "winnings", "贏了錢", "拿出來", "換回現金", "領獎金",
            "inr", "盧比", "rupee", "upi", "paytm", "phonepe",
            "銀行轉帳", "bank transfer", "換匯", "exchange rate", "匯率",
            "imps", "jeepay",
            "充值", "入帳", "存款", "儲值", "儲值方式",
            "trc-20", "tron network", "轉帳地址", "到帳時間", "最低存款",
            "存錢", "哪些貨幣", "換回usdt", "換回inr", "現金提領",
            "流水", "turnover", "trading volume",
            "信用卡", "credit card", "debit card",
            "external wallet", "外部錢包",
            "貨幣", "用什麼貨幣", "哪些貨幣可以", "currencies available", "available currency", "currencies supported", "what currencies",
            "fee", "any fee", "fees", "charge", "charges", "手續費", "收費",
            "贏了可以拿", "贏了拿多少", "輸了損失", "輸了會損失",
            "win but no", "no points", "points not", "didn't receive", "not credited", "not received points",
            "i win", "settlement not", "haven't received",
        ],
        "預測下注機制": [
            "如何下注", "怎麼下注", "下注方式", "下注金額",
            "下注紀錄", "投注記錄", "bet history", "我的下注",
            "bet", "wager", "賠率", "odds",
            "yes股份", "no股份", "yes和no", "yes 和 no", "買yes", "買no",
            "股份是什麼", "股份意思",
            "本金", "輸了多少", "贏了多少", "持倉",
            "my bets", "持有股份", "shares", "outcome",
            "中獎條件", "板球", "cricket", "ipl", "比賽結果", "誰會贏",
            "同時下注", "下多個注", "同時下多", "leverage", "margin", "槓桿", "保證金",
            "下注後可以反悔", "反悔取消", "輸了", "輸多少",
        ],
        "交易與流動性": [
            "掛單", "限價單", "市價單", "市價下單",
            "limit order", "instant buy", "market order",
            "滑點", "slippage", "滑價", "價格跟畫面不一樣", "價格衝擊", "price impact",
            "流動性", "liquidity", "amm", "cpmm", "做市",
            "成交價", "深度", "order book",
            "取消訂單", "取消掛單", "取消還沒成交", "錢會退給我嗎", "pending order",
            "exit position", "賣出持倉", "提前賣出", "離場",
            "訂單沒有完全成交", "沒有完全成交", "部分成交", "partially filled",
            "匯出交易記錄", "匯出記錄", "交易記錄", "export",
            "走勢圖", "價格走勢", "時間區間", "k線", "chart",
            "套利", "arbitrage",
            "手續費", "maker fee", "taker fee", "交易費", "settlement fee",
            "gas fee", "volume rebate",
        ],
        "市場結算與爭議": [
            "市場結算", "何時結算", "結算時間", "結算規則", "settlement", "when.*settlement",
            "get my settlement", "when can i get", "helo when", "結算了嗎", "幾時結算",
            "resolution", "oracle", "預言機", "uma",
            "爭議", "dispute", "對結果有異議", "結果有問題",
            "賽事取消", "市場取消", "延期", "cancelled market", "postponed",
            "無效市場", "void", "判定標準", "資料來源",
            "創建市場", "create market", "建立市場", "建立新市場", "市場審核",
            "create my own market", "how can i create", "要怎麼建立",
            "開市", "開題", "市場押金", "市場分潤",
            "市場分類", "market categories", "有哪些市場", "active market",
            "預測哪些事件", "可以預測哪些", "哪些事件可以預測",
            "最紅的題目", "熱門題目", "熱門市場", "popular market", "trending market", "hot market",
        ],
        "獎勵與推廣": [
            "推薦計畫", "推薦獎勵計劃", "推薦獎勵計画", "referral program", "referral code", "推薦碼",
            "佣金", "commission", "邀請朋友", "invite friend",
            "下線", "downline", "分潤", "返佣",
            "推薦等級", "bronze", "silver", "gold", "agent tier",
            "領取佣金", "claim commission", "pending commission",
            "推廣活動", "活動獎勵", "bonus", "bonuses", "reward", "promotion", "offer", "offered",
            "怎麼推薦", "推薦朋友", "如何推薦", "推薦自己", "self-referral",
            "升級", "升等", "晉級", "銀牌", "金牌", "銅牌", "tier upgrade",
            # 移除: "獎金"(資金問題重複)、"reward"(太廣)、"referral"(保留更精確版)、
            #        "推薦"(太廣)、"邀請"(太廣)、"loyalty"(交易重複)、
            #        "rebate"(交易重複)、"領取"/"claim"(太廣)、
            #        "invite code"→"referral code"、"活動"(太廣)
        ],
        "帳戶安全與管理": [
            "帳戶設定", "account settings", "修改帳號", "change name",
            "忘記密碼", "reset password", "密碼問題",
            "kyc", "身份驗證",
            "帳號安全", "account security", "帳號被盜", "帳號鎖定",
            "compromised", "locked account",
            "hack", "被駭", "二步驗證", "2fa", "兩步驗證",
            "錢包安全", "錢包地址是每個人", "錢包地址是我專屬", "我的錢放在這裡安全嗎",
            "資產安全", "is it safe", "safe here",
            "帳號被鎖定", "鎖定帳號", "密碼會被", "密碼安全",
            "帳號可以轉讓", "多個帳號", "一個人幾個帳號",
            # 移除: "帳戶"/"account"(太廣)、"設定"/"setting"(太廣)、
            #        "密碼"/"password"(保留更精確版)、"語言"(太廣)、
            #        "安全"/"security"/"secure"(太廣)、"被盜"→"帳號被盜"、
            #        "鎖定"→"帳號鎖定"、"保護"/"protect"(太廣)、"驗證碼"(太廣)
        ],
        "客服轉接": [
            "真人客服", "human support", "human agent", "real human",
            "聯繫客服", "找客服", "客服在哪", "客服時間", "幾點上班",
            "真人", "人工客服", "轉真人", "speak to human", "talk to human", "customer support", "contact support", "support team",
            "need human", "want human", "real person", "contact support", "contact admin"
            # 移除: "人工"(太廣，"人工智慧"、"人工審核"等)→"人工客服"
            #        "轉接"(太廣)→"轉真人"
        ],
        "開發者/API": [
            "api", "websocket", "rest api", "developer", "sdk", "endpoint", "webhook",
            "bot自動", "自動下注", "自動交易", "automated", "script",
        ],
        "法律與條款": [
            "合法嗎", "是否合法", "legal", "合規", "india legal",
            "服務條款", "terms of service", "條款", "隱私政策", "privacy policy",
            "年齡限制", "地區限制", "banned country", "稅務", "tax"
            # 移除: "合法"→"合法嗎"、"terms"(太廣)、"隱私"(太廣)→"隱私政策"、
            #        "privacy"(太廣)→"privacy policy"
        ],
        "寒暄/問候": [
            # 問候
            "你好", "hello", "hi", "嗨", "哈囉", "hey", "早安", "晚安", "午安",
            "good morning", "good night", "good afternoon", "good evening",
            # 感謝 / 回應
            "thanks", "thank you", "謝謝", "感謝", "多謝", "thx",
            "好的", "好喔", "好啊", "okay", "ok", "👍", "了解", "明白", "收到",
            "有人嗎", "有人在嗎", "anyone here", "is anyone there",
            # 閒聊 / 離題
            "外星人", "alien", "幽浮", "ufo",
            "有沒有神", "信神", "有沒有鬼", "鬼故事",
            "天氣如何", "今天天氣", "今天幾度", "下雨了嗎",
            "吃什麼好", "午餐吃", "晚餐吃", "早餐吃",
            "無聊", "好無聊", "哈哈", "lol", "😂", "🤣",
            "你是誰", "who are you", "你是ai", "你是機器人", "are you a bot", "are you human",
            "你幾歲", "how old are you", "你叫什麼", "what's your name",
            "閒聊", "隨便聊", "有趣嗎",
            "加油", "讚啦", "好棒",
            # 移除: "聊天"/"chat"(太廣，"contact support via chat")、
            #        "random"、"interesting"(太廣)、"fighting"、"nice"、
            #        "great"/"awesome"/"cool"(太廣，"great platform"等)、
            #        "food"/"hungry"(太廣)、"天氣"/"weather"(太廣)→更精確版、
            #        "吃什麼"→更精確版
        ],
    }
    for e in entries:
        try:
            dt = datetime.strptime(e["timestamp"], "%Y-%m-%d %H:%M:%S")
            d  = dt.strftime("%Y-%m-%d")
            daily[d] += 1; hourly[dt.strftime("%H")] += 1; hr_c[dt.hour] += 1
            u_days[e["user_id"]].add(d); d_users[d].add(e["user_id"])
            ts_matrix.append({"t": int(dt.timestamp()), "u": str(e["user_id"])})
            rp = e.get("reply", "")
            if any(kw in rp for kw in ["觸發真人客服攔截","AI 投降","需要真人協助","Phase1 人工升級"]):
                hu_c += 1; d_hu[d] += 1
            elif rp.startswith("[錯誤:"):
                err_c += 1
            else:
                ai_c += 1; d_ai[d] += 1
            q = e["question"].lower().strip()
            skip_btn = any(q.startswith(p) for p in ["💰","🔍","🏆","❓","🎲","🎁","🚀","💼"])
            if not q.startswith("/") and not skip_btn:
                # 完整字串比對（單字訊息如「好」「嗨」直接歸寒暄）
                exact_greet = {"好","嗨","哈囉","hi","hello","hey","ok","okay","👍","thanks","謝謝","好的","好喔","yes","no","how","what","why","helo","heloo"}
                if q in exact_greet:
                    tp_c["寒暄/問候"] += 1
                    d_topics[d]["寒暄/問候"] += 1
                else:
                    matched = False
                    for cat, kws in cats.items():
                        if any(kw in q for kw in kws):
                            tp_c[cat] += 1
                            d_topics[d][cat] += 1
                            matched = True; break
                    if not matched:
                        tp_c["其他"] += 1
                        d_topics[d]["其他"] += 1
                        print(f"[{INSTANCE_ID}] 🔎 其他: {repr(e['question'])}", flush=True)
        except Exception as ex:
            print(f"[{INSTANCE_ID}] ⚠️ run_analysis entry: {ex}", flush=True)
    def d30(i): return (today - timedelta(days=29-i)).strftime("%Y-%m-%d")
    tu = len(u_days)
    ot = sum(1 for v in u_days.values() if len(v) == 1)
    rt = sum(1 for v in u_days.values() if len(v) >= 2)
    ly = sum(1 for v in u_days.values() if len(v) >= 5)
    seen, nr = set(), []
    for i in range(30):
        d  = d30(i); du = d_users.get(d, set())
        nr.append({"date": d, "new": len(du - seen), "returning": len(du & seen)})
        seen.update(du)
    ma = hr_c.most_common(1)[0] if hr_c else (0, 0)
    ds = set(e["timestamp"][:10] for e in entries)
    return {
        "summary": {
            "total_conversations": len(entries), "total_users": tu,
            "total_days": len(ds), "avg_daily": round(len(entries)/max(len(ds),1), 1),
            "ai_resolution_rate": round(ai_c/max(len(entries),1)*100, 1),
            "most_active_hour": f"{ma[0]:02d}:00",
            "analysis_time": today.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "usage_trend": {
            "daily":  [{"date": d30(i), "count": daily.get(d30(i), 0)} for i in range(30)],
            "hourly": [{"hour": f"{h:02d}", "count": hourly.get(f"{h:02d}", 0)} for h in range(24)],
        },
        "ai_vs_human": {
            "total": {"ai": ai_c, "human": hu_c, "error": err_c},
            "daily_trend": [{"date": d30(i), "ai": d_ai.get(d30(i),0), "human": d_hu.get(d30(i),0)} for i in range(30)],
        },
        "retention": {
            "total_users": tu, "one_time": ot, "returning": rt, "loyal": ly,
            "dau_trend": [{"date": d30(i), "dau": len(d_users.get(d30(i), set()))} for i in range(30)],
            "daily_new_vs_return": nr,
        },
        "popular_topics": {
            "ranking": [{"topic": t, "count": c} for t, c in sorted(tp_c.items(), key=lambda x: x[1], reverse=True)],
            "daily": [{"date": d30(i), "topics": dict(d_topics.get(d30(i), {}))} for i in range(30)]
        },
        "ts_matrix": ts_matrix,
    }

# --- 5. Dashboard Server ---
_cache_lock = threading.Lock()
_cache      = {"data": None, "time": None}

def update_analytics_cache():
    print(f"[{INSTANCE_ID}] 📊 執行 log 分析...", flush=True)
    result = run_analysis()
    with _cache_lock:
        _cache["data"] = result
        _cache["time"] = datetime.now()
    total = result['summary']['total_conversations']
    # 查詢 MySQL 最新一筆對話時間
    try:
        pool = _get_db_pool()
        conn = pool.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(conversation_at) FROM conversation_logs")
        latest = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        latest_str = latest.strftime("%Y/%m/%d %H:%M:%S") if latest else "無資料"
    except Exception:
        latest_str = "查詢失敗"
    print(f"[{INSTANCE_ID}] ✅ 分析完成！{total} 筆對話｜MySQL 對話資料至 {latest_str}", flush=True)

def analytics_scheduler():
    """
    每 5 分鐘執行一次。各時間點任務：
    - xx:10  → db_import_rotated_logs()：匯入上一小時 log 檔到 MySQL
    - xx:15  → update_analytics_cache()：從 MySQL 重新跑分析（確保匯入完再分析）
    - xx:00  → evict_stale_memories()：清除閒置用戶記憶
    重新部署後啟動時立即補匯入 + 重跑分析。
    """
    time.sleep(5)
    try:
        update_analytics_cache()
        evict_stale_memories()
        db_import_rotated_logs()
    except Exception as e:
        print(f"[{INSTANCE_ID}] ❌ 啟動初始化排程失敗: {e}", flush=True)

    while True:
        now     = datetime.now()
        seconds = now.second
        # 對齊到下一個整 5 分鐘刻度（:00, :05, :10, :15, ...）
        next_tick = (5 - now.minute % 5) * 60 - seconds
        if next_tick <= 0:
            next_tick += 300
        time.sleep(next_tick)

        now = datetime.now()
        try:
            if now.minute == 0:
                print(f"[{INSTANCE_ID}] ⏰ 排程觸發：evict_stale_memories", flush=True)
                evict_stale_memories()
                # 每天 09:00 自動推送知識庫缺口報告
                if now.hour == 9:
                    print(f"[{INSTANCE_ID}] ⏰ 排程觸發：send_kb_gap_report", flush=True)
                    if _main_loop and _main_loop.is_running() and _bot_instance:
                        asyncio.run_coroutine_threadsafe(
                            send_kb_gap_report(_bot_instance), _main_loop
                        )
            elif now.minute == 10:
                print(f"[{INSTANCE_ID}] ⏰ 排程觸發：db_import_rotated_logs", flush=True)
                db_import_rotated_logs()
            elif now.minute == 15:
                print(f"[{INSTANCE_ID}] ⏰ 排程觸發：update_analytics_cache", flush=True)
                update_analytics_cache()   # 從 MySQL 重跑分析
        except Exception as e:
            print(f"[{INSTANCE_ID}] ❌ 排程失敗: {e}", flush=True)

_EMPTY_ANALYTICS = {
    "summary":       {"total_conversations":0,"total_users":0,"total_days":0,"avg_daily":0,
                      "ai_resolution_rate":0,"most_active_hour":"--:--","analysis_time":"啟動中..."},
    "usage_trend":   {"daily":[],"hourly":[]},
    "ai_vs_human":   {"total":{"ai":0,"human":0,"error":0},"daily_trend":[]},
    "retention":     {"total_users":0,"one_time":0,"returning":0,"loyal":0,"dau_trend":[],"daily_new_vs_return":[]},
    "popular_topics":{"ranking":[]},
}

def get_analytics():
    with _cache_lock:
        return _cache["data"] if _cache["data"] is not None else _EMPTY_ANALYTICS

def _load_dashboard_html():
    """每次請求讀最新版 HTML，改 dashboard.html 不需重啟 bot"""
    path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return "<html><body><h1>dashboard.html not found.</h1></body></html>"

class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path
        query  = parse_qs(parsed.query)

        if path in ('/', '/dashboard', '/dashboard.html'):
            html = _load_dashboard_html()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))

        elif path == '/api/analytics':
            if DASHBOARD_TOKEN:
                token = query.get('token', [''])[0]
                if token != DASHBOARD_TOKEN:
                    self.send_response(401)
                    self.end_headers()
                    self.wfile.write(b'Unauthorized')
                    return
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(get_analytics(), ensure_ascii=False).encode('utf-8'))

        elif path == '/health':
            self.send_response(200)
            self.end_headers()
            self.wfile.write(f"Bot {INSTANCE_ID} OK".encode())

        else:
            self.send_response(404)
            self.end_headers()

    def do_HEAD(self):
        self.send_response(200); self.end_headers()
    def log_message(self, f, *a): pass

def run_dashboard_server():
    HTTPServer(("0.0.0.0", DASHBOARD_PORT), DashboardHandler).serve_forever()

# --- 6. 知識庫 + RAG ---

EMBED_MODEL        = "text-embedding-3-small"
CHUNK_SIZE         = 300
CHUNK_OVERLAP      = 50
TOP_K              = 8      # ② 從 5 提高到 8
SIM_THRESHOLD      = 0.30   # ② 過濾低相關 chunk
HYBRID_KW_WEIGHT   = 0.30   # ③ 關鍵字分數權重（向量分數佔 0.70）

# ── 6a. 工具函式 ──

def _embed(texts: list) -> list:
    """呼叫 OpenAI embedding API，批次回傳向量 list"""
    resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return [item.embedding for item in resp.data]

def _cosine(a: list, b: list) -> float:
    """純 Python cosine similarity，~150 chunks < 5ms"""
    dot = sum(x * y for x, y in zip(a, b))
    na  = sum(x * x for x in a) ** 0.5
    nb  = sum(x * x for x in b) ** 0.5
    return dot / (na * nb + 1e-9)

def _split_chunks(text: str) -> list:
    """優先依 --- 分隔線切，超長段落再依字數切"""
    raw = re.split(r'\n---\n', text)
    chunks = []
    for sec in raw:
        sec = sec.strip()
        if not sec:
            continue
        if len(sec) <= CHUNK_SIZE:
            chunks.append(sec)
        else:
            i = 0
            while i < len(sec):
                chunks.append(sec[i:i + CHUNK_SIZE])
                i += CHUNK_SIZE - CHUNK_OVERLAP
    return [c.strip() for c in chunks if c.strip()]

def _get_pg_conn():
    """取得 psycopg2 連線，失敗回傳 None"""
    if not PG_AVAILABLE or not PG_URL:
        return None
    try:
        return psycopg2.connect(PG_URL)
    except Exception as e:
        print(f"[{INSTANCE_ID}] ⚠️ PostgreSQL 連線失敗: {e}", flush=True)
        return None

def _kb_hash() -> str:
    """計算所有知識庫檔案的 MD5 hash（內容變更即不同）"""
    import hashlib
    h = hashlib.md5()
    for pattern in ["knowledge/*.txt", "knowledge/*.md"]:
        for fp in sorted(glob.glob(pattern)):
            try:
                h.update(open(fp, "rb").read())
            except Exception:
                pass
    return h.hexdigest()

def _get_stored_hash(conn) -> str:
    """從 pgvector 讀取上次建立索引時的 KB hash"""
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kb_meta (
                key   VARCHAR(64) PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.commit()
        cur.execute("SELECT value FROM kb_meta WHERE key = 'kb_hash'")
        row = cur.fetchone()
        cur.close()
        return row[0] if row else ""
    except Exception:
        return ""

def _save_hash(conn, h: str):
    """將目前 KB hash 與 rebuild 時間戳存入 pgvector"""
    try:
        cur = conn.cursor()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(
            "INSERT INTO kb_meta (key, value) VALUES ('kb_hash', %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (h,)
        )
        cur.execute(
            "INSERT INTO kb_meta (key, value) VALUES ('kb_rebuilt_at', %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (now_str,)
        )
        conn.commit()
        cur.close()
    except Exception as e:
        print(f"[{INSTANCE_ID}] ⚠️ 儲存 kb_hash 失敗: {e}", flush=True)

# ── 6b. 知識庫載入（全文 + RAG 同步） ──

def load_all_knowledge():
    """載入全文（fallback 用）+ 建立 RAG 索引"""
    global knowledge_base, knowledge_summary
    ft, summary_parts = [], []
    for pattern in ["knowledge/*.txt", "knowledge/*.md"]:
        for fp in sorted(glob.glob(pattern)):
            try:
                with open(fp, 'r', encoding='utf-8') as f:
                    raw = "\n".join(l.strip() for l in f if l.strip())
                ft.append(f"--- 來源: {os.path.basename(fp)} ---\n{raw}")
                # ── Prompt Cache 優化：summary 只列檔名 + 頂層標題，省 ~130 tokens ──
                # 原本取前 200 字的做法會把不穩定的段落文字放進 fixed prefix，
                # 改為只擷取 ## 標題行（每檔約 10–15 個），既精簡又穩定。
                headings = [l.strip() for l in raw.splitlines() if l.strip().startswith("##")]
                summary_parts.append(f"[{os.path.basename(fp)}]\n" + "\n".join(f"  {h}" for h in headings))  # 全部標題，確保 prefix ≥ 1024 tokens 觸發 Prompt Cache
            except Exception as e:
                print(f"[{INSTANCE_ID}] ❌ 讀取失敗: {fp} — {e}", flush=True)
    knowledge_base    = "\n\n".join(ft)
    knowledge_summary = "\n".join(summary_parts)
    print(f"[{INSTANCE_ID}] ✅ 知識庫 {len(knowledge_base)} 字（共 {len(ft)} 個檔案）", flush=True)
    # RAG：優先從 DB 載入（省 embedding 費用），DB 空時重建
    load_knowledge_index_from_db()

# ── 6c. RAG 索引建立（/reload 或首次啟動 DB 無資料時呼叫） ──

def build_knowledge_index():
    """切 chunk → embedding → 寫入 pgvector → 載入記憶體"""
    global knowledge_chunks
    all_chunks = []
    for pattern in ["knowledge/*.txt", "knowledge/*.md"]:
        for fp in sorted(glob.glob(pattern)):
            try:
                with open(fp, 'r', encoding='utf-8') as f:
                    raw = "\n".join(l.strip() for l in f if l.strip())
                fname = os.path.basename(fp)
                for idx, chunk in enumerate(_split_chunks(raw)):
                    all_chunks.append({"source": fname, "idx": idx, "text": chunk})
            except Exception as e:
                print(f"[{INSTANCE_ID}] ❌ RAG 讀取失敗: {fp} — {e}", flush=True)

    if not all_chunks:
        print(f"[{INSTANCE_ID}] ⚠️ RAG：沒有知識庫檔案", flush=True)
        return

    # 批次 embedding（每批 20 避免超時）
    texts = [c["text"] for c in all_chunks]
    embeddings = []
    for i in range(0, len(texts), 20):
        embeddings.extend(_embed(texts[i:i + 20]))
    print(f"[{INSTANCE_ID}] ✅ RAG embedding 完成：{len(embeddings)} 向量", flush=True)

    # 寫入 pgvector（全量重建）
    conn = _get_pg_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM knowledge_chunks")
            for c, emb in zip(all_chunks, embeddings):
                cur.execute(
                    "INSERT INTO knowledge_chunks (source, chunk_index, chunk_text, embedding) "
                    "VALUES (%s, %s, %s, %s::vector)",
                    (c["source"], c["idx"], c["text"], str(emb))
                )
            conn.commit()
            cur.close()
            # 寫入成功後儲存 hash，下次啟動比對用
            _save_hash(conn, _kb_hash())
            conn.close()
            print(f"[{INSTANCE_ID}] ✅ RAG 寫入 pgvector：{len(all_chunks)} chunks", flush=True)
        except Exception as e:
            print(f"[{INSTANCE_ID}] ⚠️ RAG 寫入 pgvector 失敗: {e}", flush=True)
    else:
        print(f"[{INSTANCE_ID}] ⚠️ RAG：無 pgvector，僅記憶體快取", flush=True)

    # 載入記憶體快取
    knowledge_chunks = [
        {"source": c["source"], "text": c["text"], "embedding": emb}
        for c, emb in zip(all_chunks, embeddings)
    ]
    print(f"[{INSTANCE_ID}] ✅ RAG 索引完成：{len(knowledge_chunks)} chunks", flush=True)
    # rebuild 完成後觸發修復驗證（若有 active gap session）
    if _gap_session.get("groups") and _bot_instance:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_verify_after_rebuild(_bot_instance))
        except RuntimeError:
            # 在 thread 中執行（非 async 環境），用 asyncio.run
            threading.Thread(
                target=lambda: (
                    asyncio.run_coroutine_threadsafe(_verify_after_rebuild(_bot_instance), _main_loop)
                    if _main_loop and _main_loop.is_running() else None
                ),
                daemon=True
            ).start()

# ── 6d. bot 重啟時從 pgvector 載入（省 embedding 費用） ──

def _kb_file_mtime() -> datetime | None:
    """回傳 knowledge/ 目錄下最新的檔案修改時間（本地時間）"""
    import os as _os
    latest = None
    for pattern in ["knowledge/*.txt", "knowledge/*.md"]:
        for fp in glob.glob(pattern):
            try:
                mt = datetime.fromtimestamp(_os.path.getmtime(fp))
                if latest is None or mt > latest:
                    latest = mt
            except Exception:
                pass
    return latest

def _rag_rebuilt_at() -> datetime | None:
    """從 pgvector kb_meta 讀取最後一次 RAG 重建時間"""
    try:
        conn = _get_pg_conn()
        if not conn:
            return None
        cur = conn.cursor()
        cur.execute("SELECT value FROM kb_meta WHERE key = 'kb_rebuilt_at'")
        row = cur.fetchone()
        cur.close(); conn.close()
        if row:
            return datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    return None

def load_knowledge_index_from_db():
    """從 pgvector 讀取已建立的 embedding，省去重新呼叫 embedding API
    若知識庫內容有變更（hash 不符），自動重建索引。
    """
    global knowledge_chunks
    conn = _get_pg_conn()
    if not conn:
        # 無 pgvector → 直接 build（純記憶體模式）
        build_knowledge_index()
        return
    try:
        # ── KB 檔案 / RAG 時間印出 ──
        kb_mtime    = _kb_file_mtime()
        rag_rebuilt = _rag_rebuilt_at()
        kb_mtime_s  = kb_mtime.strftime("%Y-%m-%d %H:%M:%S")    if kb_mtime    else "無法取得"
        rag_s       = rag_rebuilt.strftime("%Y-%m-%d %H:%M:%S") if rag_rebuilt else "無紀錄"
        print(f"[{INSTANCE_ID}] 📚 KB 檔案最後修改：{kb_mtime_s}", flush=True)
        print(f"[{INSTANCE_ID}] 🗄️  RAG 最後重建：  {rag_s}",      flush=True)

        # ── hash 比對：知識庫有變動就自動重建 ──
        current_hash  = _kb_hash()
        stored_hash   = _get_stored_hash(conn)
        if current_hash != stored_hash:
            print(f"[{INSTANCE_ID}] 🔄 KB hash 不同 → 自動重建 RAG 索引...", flush=True)
            conn.close()
            build_knowledge_index()
            return

        # ── hash 相同：判斷是否建議 reload ──
        if kb_mtime and rag_rebuilt:
            diff_minutes = (kb_mtime - rag_rebuilt).total_seconds() / 60
            if diff_minutes > 0:
                # KB 比 RAG 新，但 hash 一致 → 內容真的沒變，不需要 reload
                print(f"[{INSTANCE_ID}] ✅ hash 一致（KB 比 RAG 新 {diff_minutes:.0f} 分鐘，但內容未變）→ 不需要 reload", flush=True)
            else:
                diff_hours = abs(diff_minutes) / 60
                if diff_hours > 24:
                    # RAG 比 KB 舊超過 24 小時，可能異常
                    print(f"[{INSTANCE_ID}] ⚠️  RAG 比 KB 舊 {diff_hours:.1f} 小時，hash 一致 → 建議執行 /reload 確認", flush=True)
                else:
                    print(f"[{INSTANCE_ID}] ✅ hash 一致，RAG 正常 → 從 DB 載入", flush=True)
        else:
            print(f"[{INSTANCE_ID}] ✅ hash 一致 → 從 DB 載入", flush=True)

        cur = conn.cursor()
        cur.execute(
            "SELECT source, chunk_text, embedding FROM knowledge_chunks ORDER BY source, chunk_index"
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        if not rows:
            print(f"[{INSTANCE_ID}] ℹ️ RAG：DB 無資料，重新建立索引...", flush=True)
            build_knowledge_index()
            return
        knowledge_chunks = []
        for r in rows:
            raw_emb = r[2]
            # pgvector 回傳可能是字串 "[0.1,0.2,...]"、list、或 psycopg2 自訂型別
            if isinstance(raw_emb, str):
                emb = [float(x) for x in raw_emb.strip("[]").split(",")]
            elif hasattr(raw_emb, "__iter__"):
                emb = [float(x) for x in raw_emb]
            else:
                emb = list(raw_emb)
            knowledge_chunks.append({"source": r[0], "text": r[1], "embedding": emb})
        print(f"[{INSTANCE_ID}] ✅ RAG 從 DB 載入：{len(knowledge_chunks)} chunks", flush=True)
    except Exception as e:
        print(f"[{INSTANCE_ID}] ⚠️ RAG DB 載入失敗，重新建立: {e}", flush=True)
        build_knowledge_index()

# ── 6e. 查詢 ──

def _expand_query(query: str) -> list[str]:
    """
    ① Query Expansion：用 GPT 把用戶問題改寫成 3 個語意角度，
    提升 embedding 命中率。同步呼叫（在 to_thread 內執行）。
    失敗時 fallback 僅用原始 query。
    """
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0,
            max_tokens=120,
            messages=[{
                "role": "user",
                "content": (
                    "You are a query rewriter for a prediction market support chatbot.\n"
                    "Rewrite the following user question into 3 different phrasings "
                    "that capture the same intent from different angles. "
                    "Output ONLY a JSON array of 3 strings, no explanation.\n\n"
                    f"Question: {query}"
                )
            }]
        )
        import json as _json
        raw = resp.choices[0].message.content.strip()
        # 去除可能的 markdown fences
        raw = re.sub(r"^```[a-z]*\n?|\n?```$", "", raw).strip()
        variants = _json.loads(raw)
        if isinstance(variants, list) and len(variants) >= 2:
            # 原始 query 放第一位，確保不丟失
            return [query] + [v for v in variants if isinstance(v, str)][:3]
    except Exception as e:
        print(f"[{INSTANCE_ID}] ⚠️ _expand_query 失敗，使用原始 query: {e}", flush=True)
    return [query]

def _hybrid_score(vec_score: float, chunk_text: str, query: str) -> float:
    """
    ③ Hybrid Search：向量分數 × 0.70 + 關鍵字分數 × 0.30
    關鍵字分數：用戶 query 裡的詞在 chunk 中出現的比例
    """
    tokens = re.findall(r'[a-zA-Z0-9]+|[\u4e00-\u9fff]{2,}', query.lower())
    if not tokens:
        return vec_score
    chunk_lower = chunk_text.lower()
    hit = sum(1 for t in tokens if t in chunk_lower)
    kw_score = hit / len(tokens)
    return vec_score * (1 - HYBRID_KW_WEIGHT) + kw_score * HYBRID_KW_WEIGHT

def search_knowledge(query: str, k: int = TOP_K) -> str:
    """
    升級版 RAG 搜尋，整合三項優化：
    ① Query Expansion  — 多角度 query 提升命中率
    ② TOP_K 8 + Threshold 0.30 — 撈更多但過濾低分 chunk
    ③ Hybrid Search    — 向量分數 × 0.70 + 關鍵字分數 × 0.30
    失敗時 fallback 全文知識庫。
    """
    if not knowledge_chunks:
        return knowledge_base
    try:
        # ① 展開 query
        queries = _expand_query(query)
        print(f"[{INSTANCE_ID}] 🔍 Query Expansion: {len(queries)} 個角度", flush=True)

        embeddings = _embed(queries)

        # 每個 query 各自搜尋，chunk 保留最高 hybrid 分數
        best: dict[int, float] = {}
        for q_text, q_emb in zip(queries, embeddings):
            for idx, c in enumerate(knowledge_chunks):
                vec_s    = _cosine(q_emb, c["embedding"])
                hybrid_s = _hybrid_score(vec_s, c["text"], q_text)  # ③
                if hybrid_s > best.get(idx, 0):
                    best[idx] = hybrid_s

        # ② 過濾低分 + Top-K
        filtered = [(idx, s) for idx, s in best.items() if s >= SIM_THRESHOLD]
        top = sorted(filtered, key=lambda x: x[1], reverse=True)[:k]

        if not top:
            print(f"[{INSTANCE_ID}] ⚠️ 所有 chunk 低於 threshold，fallback 全文", flush=True)
            return knowledge_base

        print(
            f"[{INSTANCE_ID}] ✅ RAG Top-{len(top)} "
            f"(scores: {[round(s,3) for _,s in top[:3]]})",
            flush=True
        )
        results = [knowledge_chunks[idx] for idx, _ in top]
        return "\n\n---\n\n".join(f"[{c['source']}]\n{c['text']}" for c in results)

    except Exception as e:
        print(f"[{INSTANCE_ID}] ⚠️ search_knowledge 失敗，fallback 全文: {e}", flush=True)
        return knowledge_base

# --- 7. Telegram 指令 ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    un = update.effective_user.first_name
    ul = update.message.from_user.language_code or 'en'
    photo = "https://i.postimg.cc/43qvTbvR/banner.png"
    if ul.startswith('zh'):
        t  = f"<b>哈囉 {un}！歡迎來到 PredictGO 官方助手 🚀</b>\n\n我是您的專屬 AI 客服。很高興為您服務！😊\n無論是關於平台操作、Game Points 儲值提領或是推薦獎勵，我都能為您解答喔！\n\n👇 <b>請點擊下方選單開始探索：</b>"
        kb = [['🚀 如何開始？','💰 存款 / 提款'],['🎲 如何下注？','🎁 推薦獎勵？']]
    elif ul.startswith('hi'):
        t  = f"<b>नमस्ते {un}! PredictGO में आपका स्वागत है 🚀</b>\n\nमैं आपका AI सहायक <b>Vofu</b> हूं। आपकी मदद करके खुशी होगी! 😊\nGP जमा/निकासी, बाज़ार, या रेफरल पुरस्कारों के बारे में कुछ भी पूछें।\n\n👇 <b>नीचे दिए बटन पर क्लिक करें:</b>"
        kb = [['🚀 शुरू कैसे करें?','💰 जमा / निकासी'],['🎲 दांव कैसे लगाएं?','🎁 रेफरल पुरस्कार?']]
    elif ul.startswith('ur') or ul.startswith('pa'):
        t  = f"<b>السلام علیکم {un}! PredictGO میں خوش آمدید 🚀</b>\n\nمیں آپ کا AI معاون <b>Vofu</b> ہوں۔ آپ کی مدد کرنے میں خوشی ہوگی! 😊\nGP جمع/نکاسی، مارکیٹ، یا ریفرل انعامات کے بارے میں کچھ بھی پوچھیں۔\n\n👇 <b>نیچے دیے گئے بٹن پر کلک کریں:</b>"
        kb = [['🚀 شروع کیسے کریں?','💰 جمع / نکاسی'],['🎲 شرط کیسے لگائیں?','🎁 ریفرل انعامات?']]
    else:
        t  = f"<b>Hello {un}! Welcome to PredictGO Official Assistant 🚀</b>\n\nI'm your AI assistant <b>Vofu</b>. Glad to help! 😊\nFeel free to ask about platform operations, Game Points (GP) deposits/withdrawals, or referral rewards.\n\n👇 <b>Please click a button below to explore:</b>"
        kb = [['🚀 How to get started?','💰 Deposit / Withdraw'],['🎲 How to bet?','🎁 Referral rewards?']]
    rm = ReplyKeyboardMarkup(kb, resize_keyboard=True, one_time_keyboard=False)
    try:
        await context.bot.send_photo(chat_id=update.effective_chat.id, photo=photo, caption=t, parse_mode='HTML', reply_markup=rm)
    except Exception as e:
        print(f"[{INSTANCE_ID}] ⚠️ send_photo: {e}", flush=True)
        await update.message.reply_text(t, parse_mode='HTML', reply_markup=rm)
    log_conversation(update.effective_user.id, un, ul, "/start", "[歡迎訊息]")

async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != MY_USER_ID: return
    await update.message.reply_text(f"🕵️ ID:[{INSTANCE_ID}]")

async def reset_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    ul  = update.message.from_user.language_code or 'en'
    with _mem_lock:
        user_memories[uid] = []
        user_last_active.pop(uid, None)
    if ul.startswith('zh'):   r = "🧹 記憶已清空！"
    elif ul.startswith('hi'): r = "🧹 मेमोरी साफ़ हो गई!"
    elif ul.startswith('ur') or ul.startswith('pa'): r = "🧹 میموری صاف ہو گئی!"
    else:                      r = "🧹 Memory cleared!"
    await update.message.reply_text(r)
    log_conversation(uid, update.effective_user.first_name, ul, "/reset", r)

async def refresh_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """管理員指令：對最近 30 天有對話的用戶批次推送新快捷按鈕選單"""
    if update.message.from_user.id != MY_USER_ID:
        return
    await update.message.reply_text("🔄 開始推送新按鈕選單，請稍候...")
    try:
        pool = _get_db_pool()
        conn = pool.get_connection()
        cur  = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT user_id, user_lang, MAX(user_name) AS user_name
            FROM conversation_logs
            WHERE conversation_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
            GROUP BY user_id, user_lang
        """)
        rows = cur.fetchall()
        cur.close(); conn.close()
    except Exception as e:
        await update.message.reply_text(f"❌ 撈取用戶失敗：{e}")
        return

    ok, fail = 0, 0
    for row in rows:
        uid = row["user_id"]
        ul  = row["user_lang"] or "en"
        if uid == MY_USER_ID:
            continue
        if ul.startswith("zh"):
            kb  = [["🚀 如何開始？","💰 存款 / 提款"],["🎲 如何下注？","🎁 推薦獎勵？"]]
            msg = "✨ 我們已更新快捷選單，請使用下方按鈕繼續探索！"
        elif ul.startswith("hi"):
            kb  = [["🚀 शुरू कैसे करें?","💰 जमा / निकासी"],["🎲 दांव कैसे लगाएं?","🎁 रेफरल पुरस्कार?"]]
            msg = "✨ शॉर्टकट मेनू अपडेट हो गया है! नीचे दिए बटन का उपयोग करें।"
        elif ul.startswith("ur") or ul.startswith("pa"):
            kb  = [["🚀 شروع کیسے کریں?","💰 جمع / نکاسی"],["🎲 شرط کیسے لگائیں?","🎁 ریفرل انعامات?"]]
            msg = "✨ شارٹ کٹ مینو اپڈیٹ ہو گیا ہے! نیچے دیے بٹن استعمال کریں۔"
        else:
            kb  = [["🚀 How to get started?","💰 Deposit / Withdraw"],["🎲 How to bet?","🎁 Referral rewards?"]]
            msg = "✨ We've updated the shortcut menu! Use the buttons below to explore."
        rm = ReplyKeyboardMarkup(kb, resize_keyboard=True, one_time_keyboard=False)
        try:
            await context.bot.send_message(chat_id=uid, text=msg, reply_markup=rm)
            ok += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail += 1

    await update.message.reply_text(
        f"✅ 推送完成！成功 {ok} 人，失敗 {fail} 人（用戶可能已封鎖 bot）"
    )

async def refresh_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """管理員指令：對最近 30 天有對話的用戶批次推送新快捷按鈕選單"""
    if update.message.from_user.id != MY_USER_ID:
        return
    await update.message.reply_text("🔄 開始推送新按鈕選單，請稍候...")
    try:
        pool = _get_db_pool()
        conn = pool.get_connection()
        cur  = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT user_id, user_lang, MAX(user_name) AS user_name
            FROM conversation_logs
            WHERE conversation_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
            GROUP BY user_id, user_lang
        """)
        rows = cur.fetchall()
        cur.close(); conn.close()
    except Exception as e:
        await update.message.reply_text(f"❌ 撈取用戶失敗：{e}")
        return
    ok, fail = 0, 0
    for row in rows:
        uid = row["user_id"]
        ul  = row["user_lang"] or "en"
        if uid == MY_USER_ID:
            continue
        if ul.startswith("zh"):
            kb  = [["🚀 如何開始？","💰 存款 / 提款"],["🎲 如何下注？","🎁 推薦獎勵？"]]
            msg = "✨ 我們已更新快捷選單，請使用下方按鈕繼續探索！"
        elif ul.startswith("hi"):
            kb  = [["🚀 शुरू कैसे करें?","💰 जमा / निकासी"],["🎲 दांव कैसे लगाएं?","🎁 रेफरल पुरस्कार?"]]
            msg = "✨ शॉर्टकट मेनू अपडेट हो गया है! नीचे दिए बटन का उपयोग करें।"
        elif ul.startswith("ur") or ul.startswith("pa"):
            kb  = [["🚀 شروع کیسے کریں?","💰 جمع / نکاسی"],["🎲 شرط کیسے لگائیں?","🎁 ریفرل انعامات?"]]
            msg = "✨ شارٹ کٹ مینو اپڈیٹ ہو گیا ہے! نیچے دیے بٹن استعمال کریں۔"
        else:
            kb  = [["🚀 How to get started?","💰 Deposit / Withdraw"],["🎲 How to bet?","🎁 Referral rewards?"]]
            msg = "✨ We've updated the shortcut menu! Use the buttons below to explore."
        rm = ReplyKeyboardMarkup(kb, resize_keyboard=True, one_time_keyboard=False)
        try:
            await context.bot.send_message(chat_id=uid, text=msg, reply_markup=rm)
            ok += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail += 1
    await update.message.reply_text(f"✅ 推送完成！成功 {ok} 人，失敗 {fail} 人（用戶可能已封鎖 bot）")


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    管理員廣播指令，兩步驟：
    步驟 1：/broadcast → bot 提示輸入內容
    步驟 2：管理員 reply 該提示訊息 → bot 發送給所有近 30 天用戶
    """
    if update.message.from_user.id != MY_USER_ID:
        return

    # 步驟 2：管理員 reply 了 bot 的提示訊息
    if (update.message.reply_to_message
            and update.message.reply_to_message.text == BROADCAST_PROMPT):
        msg_text = update.message.text.strip()
        if not msg_text:
            await update.message.reply_text("❌ 訊息內容不能為空。")
            return

        await update.message.reply_text(f"📤 開始廣播，請稍候...\n\n預覽：\n{msg_text}")

        try:
            pool = _get_db_pool()
            conn = pool.get_connection()
            cur  = conn.cursor(dictionary=True)
            cur.execute("""
                SELECT DISTINCT user_id
                FROM conversation_logs
                WHERE user_id != %s
            """, (MY_USER_ID,))
            rows = cur.fetchall()
            cur.close(); conn.close()
        except Exception as e:
            await update.message.reply_text(f"❌ 撈取用戶失敗：{e}")
            return

        ok, fail = 0, 0
        for row in rows:
            try:
                await context.bot.send_message(chat_id=row["user_id"], text=msg_text, parse_mode="HTML")
                ok += 1
                await asyncio.sleep(0.05)
            except Exception:
                fail += 1

        await update.message.reply_text(f"✅ 廣播完成！\n• 成功：{ok} 人\n• 失敗：{fail} 人（已封鎖 bot 或帳號異常）")
        return

    # 步驟 1：初次發 /broadcast，提示輸入
    await update.message.reply_text(BROADCAST_PROMPT)


async def reload_kb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """管理員指令：熱更新知識庫 + 強制重建 RAG 索引，不需重啟 bot"""
    if update.message.from_user.id != MY_USER_ID: return
    await update.message.reply_text("⏳ 重載知識庫並重建 RAG 索引...")
    load_all_knowledge()     # 重新讀取全文 + summary
    build_knowledge_index()  # 強制重建 embedding（/reload 永遠重建，不比對 hash）
    await update.message.reply_text(
        f"✅ 知識庫已重載，{len(knowledge_base)} 字｜RAG: {len(knowledge_chunks)} chunks"
    )

async def force_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """管理員指令：立即重跑分析並更新 Dashboard 快取"""
    if update.message.from_user.id != MY_USER_ID: return
    print(f"[{INSTANCE_ID}] 📊 手動觸發分析 by {update.message.from_user.id}", flush=True)
    await update.message.reply_text("⏳ 分析中...")
    threading.Thread(target=update_analytics_cache, daemon=True).start()
    await update.message.reply_text("✅ 分析完成，Dashboard 已更新")

async def gaps_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    管理員指令：手動觸發知識庫缺口報告。
    用法：/gaps        → 預設查最近 7 天
          /gaps 14    → 查最近 14 天
          /gaps 30    → 查最近 30 天
    """
    if update.message.from_user.id != MY_USER_ID: return
    args = context.args
    try:
        days = int(args[0]) if args else 7
        days = max(1, min(days, 90))
    except (ValueError, IndexError):
        days = 7
    print(f"[{INSTANCE_ID}] 📋 手動觸發 KB缺口報告 ({days}天) by {update.message.from_user.id}", flush=True)
    await update.message.reply_text(f"⏳ 正在查詢最近 {days} 天的知識庫缺口...")
    await send_kb_gap_report(context.bot, days=days)


async def gap_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理缺口管理的 Inline Button 回調（approve / ignore / edit / approve_all）"""
    global _gap_session
    query = update.callback_query
    if not query or query.from_user.id != MY_USER_ID:
        return
    try:
        await query.answer()
    except Exception:
        pass  # callback query 已過期或 event loop 已關閉，靜默忽略

    data = query.data  # e.g. "gap_approve_1", "gap_ignore_2", "gap_edit_3", "gap_approve_all"
    groups  = _gap_session.get("groups", [])
    status  = _gap_session.get("status", {})

    if not groups:
        await query.edit_message_text("⚠️ 目前沒有進行中的缺口 session，請重新執行 /gaps")
        return

    if data == "gap_approve_all":
        for g in groups:
            status[g["id"]] = "approved"
            _gap_mark_handled(g["rep"], action="approved")
        await query.edit_message_text("✅ 已全部 Approve！正在產生完整知識庫檔案...")
        await _finalize_gap_session(context.bot)
        return

    parts = data.split("_")   # ["gap", "approve"|"ignore"|"edit", "1"]
    if len(parts) != 3:
        return
    action_type = parts[1]
    try:
        gid = int(parts[2])
    except ValueError:
        return

    if action_type == "approve":
        status[gid] = "approved"
        group = next((g for g in groups if g["id"] == gid), None)
        if group:
            _gap_mark_handled(group["rep"], action="approved")
        await query.answer(f"✅ #{gid} 已 Approve")

    elif action_type == "ignore":
        status[gid] = "ignored"
        group = next((g for g in groups if g["id"] == gid), None)
        if group:
            _gap_mark_handled(group["rep"], action="ignored")
        await query.answer(f"❌ #{gid} 已忽略")

    elif action_type == "edit":
        status[gid] = "editing"
        _gap_session["edit_target"] = gid
        group = next((g for g in groups if g["id"] == gid), None)
        if group:
            await context.bot.send_message(
                chat_id=MY_USER_ID,
                text=(
                    f"✏️ <b>優化 #{gid}「{group['label']}」草稿</b>\n\n"
                    f"目前草稿：\n<pre>{group['draft_zh'][:500]}...</pre>\n\n"
                    f"請直接回覆你的修改意見或新草稿內容，bot 會重新生成。"
                ),
                parse_mode='HTML'
            )
        return

    # 更新按鈕狀態顯示
    _gap_session["status"] = status
    keyboard = _build_gap_keyboard(groups, status)
    try:
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        pass

    # 檢查是否全部處理完（沒有 pending）
    if all(status.get(g["id"]) in ("approved", "ignored") for g in groups):
        await context.bot.send_message(
            chat_id=MY_USER_ID,
            text="⏳ 所有群組已處理完畢，正在產生完整知識庫檔案...",
            parse_mode='HTML'
        )
        await _finalize_gap_session(context.bot)


async def gap_edit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    處理 ✏️ 優化後的文字回覆：重新生成對應群組的草稿。
    只在 edit_target 有效時觸發（避免干擾一般對話）。
    """
    global _gap_session
    if update.message.from_user.id != MY_USER_ID:
        return
    if not _gap_session.get("edit_target"):
        return   # 沒有 editing 狀態，交給一般 handle_message 處理

    gid     = _gap_session["edit_target"]
    groups  = _gap_session.get("groups", [])
    group   = next((g for g in groups if g["id"] == gid), None)
    if not group:
        return

    user_feedback = update.message.text
    await update.message.reply_text(f"⏳ 正在根據你的意見重新生成 #{gid} 草稿...")

    def _redraft():
        prompt = (
            f"Rewrite this KB chunk based on user feedback.\n\n"
            f"Original draft (Chinese):\n{group['draft_zh']}\n\n"
            f"User feedback: {user_feedback}\n\n"
            f"Output ONLY JSON: {{\"draft_zh\": \"...\", \"draft_en\": \"...\"}}"
        )
        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini", temperature=0.3, max_tokens=600,
                messages=[{"role": "user", "content": prompt}]
            )
            import json as _json
            raw = resp.choices[0].message.content.strip()
            raw = re.sub(r"^```[a-z]*\n?|\n?```$", "", raw).strip()
            return _json.loads(raw)
        except Exception as e:
            return {"draft_zh": group["draft_zh"], "draft_en": group["draft_en"]}

    new_draft = await asyncio.to_thread(_redraft)
    group["draft_zh"] = new_draft.get("draft_zh", group["draft_zh"])
    group["draft_en"] = new_draft.get("draft_en", group["draft_en"])
    _gap_session["status"][gid] = "approved"
    _gap_session["edit_target"] = None

    await update.message.reply_text(
        f"✅ #{gid} 草稿已更新並標記為 Approve！\n\n"
        f"預覽（中文）：\n{group['draft_zh'][:300]}..."
    )

    # 如果全部處理完就自動 finalize
    status = _gap_session.get("status", {})
    if all(status.get(g["id"]) in ("approved", "ignored") for g in groups):
        await update.message.reply_text("⏳ 所有群組處理完畢，正在產生完整知識庫檔案...")
        await _finalize_gap_session(context.bot)


def _build_gap_keyboard(groups: list, status: dict) -> list:
    """根據當前 status 產生 Inline Keyboard，已處理的顯示狀態符號"""
    keyboard = []
    # 只要還有 pending 就顯示全部 approve 按鈕
    if any(status.get(g["id"]) == "pending" for g in groups):
        keyboard.append([InlineKeyboardButton("✅ 全部 Approve", callback_data="gap_approve_all")])
    for g in groups:
        s = status.get(g["id"], "pending")
        if s == "approved":
            row = [InlineKeyboardButton(f"✅ #{g['id']}「{g['label']}」已 Approve", callback_data="noop")]
        elif s == "ignored":
            row = [InlineKeyboardButton(f"❌ #{g['id']}「{g['label']}」已忽略", callback_data="noop")]
        elif s == "editing":
            row = [InlineKeyboardButton(f"✏️ #{g['id']}「{g['label']}」編輯中...", callback_data="noop")]
        else:
            row = [
                InlineKeyboardButton(f"✅ #{g['id']}", callback_data=f"gap_approve_{g['id']}"),
                InlineKeyboardButton(f"✏️ #{g['id']}", callback_data=f"gap_edit_{g['id']}"),
                InlineKeyboardButton(f"❌ #{g['id']}", callback_data=f"gap_ignore_{g['id']}"),
            ]
        keyboard.append(row)
    return keyboard


async def _finalize_gap_session(bot):
    """所有群組處理完後，推送 approved 草稿純文字摘要給管理員。"""
    global _gap_session
    groups = _gap_session.get("groups", [])
    status = _gap_session.get("status", {})
    approved = [g for g in groups if status.get(g["id"]) == "approved"]

    if not approved:
        await bot.send_message(
            chat_id=MY_USER_ID,
            text="ℹ️ 所有缺口均已忽略，無需更新知識庫。",
            parse_mode='HTML'
        )
        _gap_session = {}
        return

    # 組合純文字草稿摘要
    lines = [f"✅ <b>知識庫草稿摘要｜共 {len(approved)} 個群組</b>\n"
             f"請將以下內容交給 Claude.ai 整合進知識庫檔案。\n"]

    for g in approved:
        lines.append(f"{'─'*28}")
        lines.append(f"<b>#{g['id']}「{g['label']}」</b>（{g['count']} 筆缺口）")
        lines.append(f"代表問題：{g['rep']}\n")
        lines.append(f"📝 <b>中文草稿：</b>\n<pre>{g['draft_zh'][:600]}</pre>")
        lines.append(f"📝 <b>英文草稿：</b>\n<pre>{g['draft_en'][:600]}</pre>")

    lines.append(f"{'─'*28}")
    lines.append("💡 下一步：將以上草稿交給 Claude.ai 優化並整合進 notebookLM.txt / notebookLM_en.txt，完成後 git push 即可。")

    # 超過 4096 字元自動分段
    msg = "\n".join(lines)
    chunk_size = 3800
    for i in range(0, len(msg), chunk_size):
        await bot.send_message(
            chat_id=MY_USER_ID,
            text=msg[i:i+chunk_size],
            parse_mode='HTML'
        )

    _gap_session = {}
    print(f"[{INSTANCE_ID}] 📋 KB草稿摘要已推送（{len(approved)} 個群組 approved）", flush=True)

# --- 8. 對話 ---
async def _keep_typing(bot, chat_id: int, stop_event: asyncio.Event):
    """立刻送第一次 typing，之後每 4 秒續送，stop_event set 後立刻停止"""
    try:
        while not stop_event.is_set():
            await bot.send_chat_action(chat_id=chat_id, action="typing")
            # 用 wait_for 讓 stop_event 可以在 sleep 期間提早中斷
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=4)
                break   # stop_event 被 set，立刻跳出
            except asyncio.TimeoutError:
                pass    # 4 秒到了，繼續下一輪
    except asyncio.CancelledError:
        pass
    except Exception:
        pass

async def _call_openai_with_retry(msgs: list, max_retries: int = 3) -> str:
    """帶 exponential backoff 重試的 OpenAI 呼叫"""
    last_err = None
    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=msgs,
                temperature=0.2,
                max_tokens=500,
                timeout=30,
            )
            return resp.choices[0].message.content
        except Exception as e:
            last_err = e
            if attempt < max_retries - 1:
                wait = 2 ** attempt   # 1s → 2s → 失敗才丟
                print(f"[{INSTANCE_ID}] ⚠️ OpenAI retry {attempt+1}/{max_retries} in {wait}s: {e}", flush=True)
                await asyncio.sleep(wait)
    raise last_err

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    un  = update.effective_user.first_name
    ut  = update.message.text
    ul  = update.message.from_user.language_code or 'en'
    iz  = ul.startswith('zh')

    # ── 優先攔截：管理員的廣播內容 reply ──
    if (uid == MY_USER_ID
            and update.message.reply_to_message
            and update.message.reply_to_message.text == BROADCAST_PROMPT):
        await broadcast(update, context)
        return

    # ── 優先攔截：管理員的 KB缺口草稿編輯回覆 ──
    if uid == MY_USER_ID and _gap_session.get("edit_target"):
        await gap_edit_handler(update, context)
        return

    ut_log = " ".join(ut.split())   # 換行/多空白壓成單行，log 更易讀
    print(f"[{INSTANCE_ID}] 📩 {uid}({ul}): {ut_log}", flush=True)

    # 用戶送出訊息後立刻顯示 typing，不等任何判斷
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # 依訊息內容偵測語言（比 Telegram 帳號語言設定更準確）
    def _detect_lang(text: str) -> str:
        for c in text:
            if '一' <= c <= '鿿': return "zh"   # 中文
            if 'ऀ' <= c <= 'ॿ': return "hi"   # Hindi 天城文
            if '؀' <= c <= 'ۿ': return "ur"   # Urdu 阿拉伯文
        return "en"

    detected_lang = _detect_lang(ut)
    is_zh = detected_lang == "zh"

    if detected_lang == "zh":
        bt = "👨‍💻 點我聯繫真人客服"
    elif detected_lang == "hi":
        bt = "👨‍💻 मानव सहायता से संपर्क करें"
    elif detected_lang == "ur":
        bt = "👨‍💻 انسانی سپورٹ سے رابطہ کریں"
    else:
        bt = "👨‍💻 Contact Human Support"
    rm = InlineKeyboardMarkup([[InlineKeyboardButton(bt, url="https://t.me/PredictGO_CS")]])

    # ── 快捷按鈕偵測：直接走 RAG，不進意圖分類器 ──
    # 用戶按下快捷按鈕是「想了解」而非「要操作」，屬於 FAQ 場景
    QUICK_BTN_PREFIXES = ("🚀", "💰", "🎲", "🎁")
    if ut.startswith(QUICK_BTN_PREFIXES):
        rag_context = await asyncio.to_thread(search_knowledge, ut)
        intent, confidence = "faq", 1.0
        print(f"[{INSTANCE_ID}] 🔘 快捷按鈕 → 強制 faq | {uid}: {ut_log[:30]}", flush=True)
    else:
        # ── Phase 1：明確關鍵字攔截（快速路徑，不需呼叫分類器）──
        kws = ["轉接客服","找真人","找客服","人工客服","聯絡管理員","我要真人","轉交人工",
               "human support","human agent","real person","contact admin","customer service",
               "speak to human","talk to human","talk to a person","need human","want human",
               "人工服務","要真人","找人工"]
        if any(k in ut.lower() for k in kws):
            await handle_human_escalation(update, uid, un, ul, ut, "manual_request", is_zh)
            return

        # ── Phase 1：意圖分類 + RAG 搜尋 並行執行，節省一個 RTT ──
        classification, rag_context = await asyncio.gather(
            classify_intent(ut),
            asyncio.to_thread(search_knowledge, ut),
        )
        intent     = classification.get("intent", "faq")
        confidence = classification.get("confidence", 0.0)

        print(f"[{INSTANCE_ID}] 🏷 意圖: {intent} ({confidence:.2f}) | {uid}({ul}): {ut_log[:50]}", flush=True)

        # 需要人工處理：confidence 足夠 + 屬於 HUMAN_INTENTS
        # confidence < 0.6 時保守走 RAG，寧可多回答一次也不誤觸人工
        if intent in HUMAN_INTENTS and confidence >= 0.75:
            await handle_human_escalation(update, uid, un, ul, ut, intent, is_zh)
            return

    # 其餘（faq / greeting / low confidence / 快捷按鈕）→ 繼續走 RAG ──

    # ── Prompt Cache 優化：三層結構 ──
    # [1] knowledge_summary  → 固定，✅ 快取
    # [2] SYS_PROMPT_SHARED  → 固定（中英共用規則），✅ 快取  ← 新增
    # [3] sys_prompt_lang    → 小型語言指令（~80 tokens）← 縮小動態部分
    # [4] rag_context        → 動態
    # [5] mem[-6:]           → 動態
    # [6] user message       → 動態

    # ── [2] 固定共用層（不隨語言變，永遠放 knowledge_summary 之後）──
    SYS_PROMPT_SHARED = (
        "You are PredictGO's customer support assistant 'Vofu'. Always answer based on the knowledge base.\n"
        "【Terminology — replace with plain language】\n"
        "  - bcrypt / bcrypt hashing → password is encrypted; plain-text password is never stored\n"
        "  - HD Wallet → every user has their own unique deposit address, never shared\n"
        "  - Unrealized Profit → paper gains from open positions, not yet settled, may change\n"
        "  - JWT / JWT token → login verification that ensures only you can access your account\n"
        "  - UMA Oracle → independent dispute system with a challenge period for verifying outcomes\n"
        "  - Rounded DOWN → decimals are truncated in your favor\n"
        "【Platform nouns — use as-is】PredictGO, Game Points, GP, USDT, TRC-20, INR, UPI, CPMM, EntitySport API\n"
        "【Game Points / GP】\n"
        "  - Exchange rate: 1 USDT = 100 GP (no fee). Withdraw: 100 GP = 1 USDT, fee: 2 USDT per transaction. Withdrawal range: 2,000–1,000,000 GP.\n"
        "  - Deposit path: Wallet → My Wallet → GP → Deposit → choose From USDT, From INR, or From PKR.\n"
        "  - INR: via JeePay/UPI. Deposit ₹500–₹50,000. Withdrawal min ₹500.\n"
        "  - PKR: via JeePay/easypaisa. Deposit Rs.100–Rs.100,000. Withdrawal Rs.500–Rs.100,000.\n"
        "  - Withdrawal requires minimum cumulative trading volume (turnover) to be reached first.\n"
        "【Human handoff】Only reply 【需要真人協助】 when user explicitly asks for human AND knowledge base truly cannot help.\n"
        "【No hallucination】Base ALL answers strictly on the knowledge base. Never invent features or details.\n"
        "【Concise】2–4 sentences for simple questions.\n"
        "【Special topic handling — reply warmly without speculation】\n"
        "  - Investment advice (which market to buy): Do not give buy/sell recommendations. Say: \"投資決策建議依個人判斷，我無法提供買賣建議喔！有其他問題隨時問我 😊\" or \"I can't provide investment advice — that's entirely up to you! Feel free to ask me anything else 😊\"\n"
        "  - Tax questions: Do not speculate on tax rules. Say: \"稅務規定因地而異，建議諮詢當地稅務顧問或會計師。\" or \"Tax rules vary by location — we recommend consulting a local tax advisor or accountant.\"\n"
        "  - Legal/compliance questions: Do not speculate. Say: \"法律合規問題建議查閱平台官方服務條款，或聯繫客服團隊。\" or \"For legal and compliance questions, please refer to our official Terms of Service or contact the support team.\"\n"
        "  - Competitor comparisons (e.g. vs Polymarket): Do not compare. Say: \"兩個平台各有特色，建議親自體驗看看！😄\" or \"Both platforms have their strengths — best to experience them for yourself! 😄\"\n"
        "  - Business model / investor inquiries: Say: \"商業合作歡迎聯繫真人客服團隊洽談 😊\" or \"For business partnerships, feel free to reach out to our support team 😊\"\n"
        "【Formatting — Telegram HTML only】\n"
        "  - Bold: <b>important terms, numbers, amounts</b>. E.g. <b>100 GP = 1 USDT</b>\n"
        "  - Steps (3+): numbered lines. Parallel items: • bullets, one per line.\n"
        "  - Code/addresses: <code>monospace</code>\n"
        "  - NEVER use markdown (**bold**, __underline__, # headings) or HTML tables — Telegram does not support them.\n"
        "  - Short answers (1–2 sentences): no formatting, keep natural.\n"
        "  - End with a warm closing line."
    )

    # ── [3] 語言層（小型，僅語言/語氣規則，~80 tokens）──
    if detected_lang == "zh":
        sys_prompt_lang = (
            "【語言規則 — 最高優先】用戶使用中文，你必須 100% 用繁體中文回覆。\n"
            "  除必要專有名詞 (PredictGO, USDT, TRC-20, CPMM, JWT, HD Wallet, GP) 外，嚴禁出現英文。\n"
            "【白話優先】把技術術語翻譯成白話文。公式改說原理，\n"
            "  例如：不說 price_yes = K / pool_no，改說「YES 的價格會隨著買的人越多而上漲」。\n"
            "  術語難以避免時，先白話後括號補術語，例如：「區塊鏈自動結算（透過 EntitySport API）」。\n"
            "【語氣】親切有溫度，多用『您好』、『喔』、『囉』、『呢』等助詞，像朋友解釋一樣。\n"
            "【回答策略 — 非常重要】盡力從知識庫找答案，中英文內容都要參考。\n"
            "  - 有部分相關資訊時，用現有內容給出有幫助的回覆。\n"
            "  - 完全找不到相關資訊時，親切道歉並建議聯繫客服，絕對不可以說「資料庫沒有」這類內部用語。\n"
            "【找不到答案】親切道歉，說明目前無法回答，並告知用戶「如需真人協助，請輸入『人工客服』或點擊下方按鈕」。回覆結尾必須加上隱藏標記 [KB_GAP]（用戶不會看到，系統用來追蹤知識庫缺口）。"
        )
    elif detected_lang == "hi":
        sys_prompt_lang = (
            "【भाषा नियम — सर्वोच्च प्राथमिकता】उपयोगकर्ता हिंदी में लिख रहा है। 100% हिंदी में उत्तर दें।\n"
            "  केवल आवश्यक तकनीकी शब्द (PredictGO, GP, USDT, TRC-20, INR, JeePay) अंग्रेज़ी में रखें।\n"
            "【सरल भाषा】तकनीकी शब्दों को आम भाषा में समझाएं। सूत्र सीधे न दें।\n"
            "【उत्तर रणनीति】ज्ञान आधार से उत्तर देने की पूरी कोशिश करें। आंशिक जानकारी होने पर भी उपयोगी उत्तर दें।\n"
            "【स्वर】मैत्रीपूर्ण और गर्मजोशी से भरा — किसी दोस्त को समझाने जैसा।\n"
            "【INR जमा/निकासी】INR जमा: ₹500–₹50,000 (JeePay/UPI)। निकासी: न्यूनतम ₹500।\n"
            "【उत्तर न मिले】विनम्रता से माफी मांगें और सहायता टीम से संपर्क करने का सुझाव दें। उत्तर के अंत में [KB_GAP] छिपा हुआ मार्कर जोड़ें।"
        )
    elif detected_lang == "ur":
        sys_prompt_lang = (
            "【زبان کا قاعدہ — اعلیٰ ترین ترجیح】صارف اردو میں لکھ رہا ہے۔ 100% اردو میں جواب دیں۔\n"
            "  صرف ضروری تکنیکی الفاظ (PredictGO, GP, USDT, TRC-20, PKR, JeePay, easypaisa) انگریزی میں رکھیں۔\n"
            "【سادہ زبان】تکنیکی اصطلاحات کو عام زبان میں سمجھائیں۔\n"
            "【جواب کی حکمت عملی】نالج بیس سے جواب دینے کی پوری کوشش کریں۔ جزوی معلومات ہوں تو بھی مفید جواب دیں۔\n"
            "【لہجہ】دوستانہ اور گرمجوش — کسی دوست کو سمجھانے جیسا۔\n"
            "【PKR جمع/نکاسی】PKR جمع: Rs.100–Rs.100,000 (JeePay/easypaisa)۔ نکاسی: Rs.500–Rs.100,000۔\n"
            "【جواب نہ ملے】شائستگی سے معذرت کریں اور سپورٹ ٹیم سے رابطے کا مشورہ دیں۔ جواب کے آخر میں [KB_GAP] شامل کریں۔"
        )
    else:
        sys_prompt_lang = (
            "【Language Rule — TOP PRIORITY】User is writing in English. Reply 100% in English. No Chinese characters except proper nouns.\n"
            "【Plain Language】Translate jargon to everyday words. Never paste raw formulas.\n"
            "  If unavoidable, explain in plain language first, then add the term in parentheses.\n"
            "【Answer Strategy】ALWAYS try to answer from the knowledge base (search both Chinese and English content).\n"
            "  If partially covered, use what's available.\n"
            "  As a last resort, apologize warmly and suggest contacting support — never say 'not in the database' or use internal system language.\n"
            "【Tone】Warm and approachable — like explaining to a friend, not writing a manual.\n"
            "【Not found】Apologize warmly, say you're unable to help with this at the moment, and tell the user: 'Type human support or tap the button below to reach our team'. Always append the hidden marker [KB_GAP] at the very end of the reply (invisible to users, used by the system to track knowledge base gaps)."
        )

    mem  = get_memory(uid)
    # rag_context 已由上方 asyncio.gather 並行取得，此處直接使用
    msgs = [
        # ── 固定 prefix（Prompt Caching 命中區，順序不能變）──
        {"role": "system", "content": f"Knowledge Base Index / 知識庫目錄:\n{knowledge_summary}"},   # [1] 固定，✅ 快取
        {"role": "system", "content": SYS_PROMPT_SHARED},                                             # [2] 固定，✅ 快取
        # ── 動態內容（每次不同，必須放固定 prefix 之後）──
        {"role": "system", "content": sys_prompt_lang},                                               # [3] 語言層（~80 tokens）
        {"role": "system", "content": f"Relevant Knowledge / 相關知識段落:\n{rag_context}"},          # [4] RAG 動態段落
        *mem[-6:],                                                                                     # [5] 對話記憶
        {"role": "user",   "content": ut},                                                            # [6] 用戶訊息
    ]

    # 所有同步準備完成後才啟動 typing，確保第一個 typing 能立刻送出
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_keep_typing(context.bot, update.effective_chat.id, stop_typing))
    await asyncio.sleep(0)   # yield 讓 typing task 送出第一個 send_chat_action

    try:
        ans = await _call_openai_with_retry(msgs)
        # 偵測知識庫缺口標記（[KB_GAP] 保留在 log，對用戶不顯示）
        is_kb_gap = "[KB_GAP]" in ans
        ans_display = ans.replace("[KB_GAP]", "").strip()
        if "【需要真人協助】" in ans:
            if detected_lang == "zh":
                st = "抱歉，這個問題超出了我的能力範圍 😓\n<i>如需真人協助，請輸入「人工客服」或點擊下方按鈕。</i>"
            elif detected_lang == "hi":
                st = "क्षमा करें, यह मेरी क्षमता से बाहर है 😓\n<i>सहायता के लिए 'मानव सहायता' टाइप करें या नीचे दिया बटन दबाएं।</i>"
            elif detected_lang == "ur":
                st = "معذرت، یہ میری صلاحیت سے باہر ہے 😓\n<i>مدد کے لیے 'انسانی مدد' ٹائپ کریں یا نیچے دیا بٹن دبائیں۔</i>"
            else:
                st = "Sorry, this is beyond my knowledge 😓\n<i>Type 'human support' or tap the button below to reach our team.</i>"
            await update.message.reply_text(st, parse_mode='HTML', reply_markup=rm)
            log_conversation(uid, un, ul, ut, "[AI 投降]")
        else:
            try:
                await update.message.reply_text(ans_display, parse_mode='HTML')
            except Exception:
                import re as _re
                plain = _re.sub(r'<[^>]+>', '', ans_display)
                await update.message.reply_text(plain)
            # KB_GAP：bot 找不到答案，附加客服引導小字 + 按鈕
            if is_kb_gap:
                if detected_lang == "zh":
                    gap_hint = "<i>如需真人協助，請輸入「人工客服」或點擊下方按鈕。</i>"
                elif detected_lang == "hi":
                    gap_hint = "<i>सहायता के लिए 'मानव सहायता' टाइप करें या नीचे दिया बटन दबाएं।</i>"
                elif detected_lang == "ur":
                    gap_hint = "<i>مدد کے لیے 'انسانی مدد' ٹائپ کریں یا نیچے دیا بٹن دبائیں۔</i>"
                else:
                    gap_hint = "<i>Type 'human support' or tap the button below to reach our team.</i>"
                try:
                    await update.message.reply_text(gap_hint, parse_mode='HTML', reply_markup=rm)
                except Exception:
                    pass
            # log 保留原始 ans（含 [KB_GAP] 標記，供後續查詢）
            log_conversation(uid, un, ul, ut, ans)
        update_memory(uid, "user",      ut)
        update_memory(uid, "assistant", ans)
    except Exception as e:
        print(f"[{INSTANCE_ID}] ❌ OpenAI 全部重試失敗: {e}", flush=True)
        await update.message.reply_text(
            "抱歉，連線稍慢，請再試一次。" if is_zh else "Sorry, please try again."
        )
        log_conversation(uid, un, ul, ut, f"[錯誤:{e}]")
    finally:
        stop_typing.set()         # 通知 loop 停止
        typing_task.cancel()       # 取消 task
        try:
            await typing_task      # 等待 task 真正結束，避免殘留
        except (asyncio.CancelledError, Exception):
            pass

# --- 9. 主程式 ---
_bot_instance = None   # 供排程器呼叫 send_kb_gap_report 使用
_main_loop    = None   # 主 event loop，供 thread 內 run_coroutine_threadsafe 使用
BROADCAST_PROMPT = "📢 請輸入要廣播的訊息內容（回覆此訊息）："  # 廣播提示，兩邊比對用
_main_loop    = None   # 主 event loop，供 thread 內 run_coroutine_threadsafe 使用

def main():
    global _bot_instance, _main_loop
    print(f"🚀 [{INSTANCE_ID}] Bot+Dashboard on :{DASHBOARD_PORT}", flush=True)
    threading.Thread(target=run_dashboard_server, daemon=True).start()
    threading.Thread(target=analytics_scheduler,  daemon=True).start()
    _ensure_tables()     # 啟動時確保 MySQL 資料表存在
    _gap_handled_init()  # 確保 gap_handled 黑名單 table 存在
    load_all_knowledge()
    time.sleep(3)
    try:
        app = Application.builder().token(TELEGRAM_TOKEN).build()
        _main_loop    = asyncio.get_event_loop()   # 儲存主 loop 供 thread 使用
        _bot_instance = app.bot                     # 儲存 bot 實例供排程器使用
        app.add_handler(CommandHandler("start",    start))
        app.add_handler(CommandHandler("id",       get_id))
        app.add_handler(CommandHandler("reset",    reset_memory))
        app.add_handler(CommandHandler("reload",     reload_kb))
        app.add_handler(CommandHandler("refresh",    refresh_keyboard))
        app.add_handler(CommandHandler("broadcast",  broadcast))
        app.add_handler(CommandHandler("refresh",  refresh_keyboard))
        app.add_handler(CommandHandler("analysis", force_analysis))
        app.add_handler(CommandHandler("gaps",     gaps_report))
        app.add_handler(CallbackQueryHandler(gap_callback, pattern="^gap_"))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        signal.signal(signal.SIGTERM, lambda *a: os._exit(0))
        app.run_polling(drop_pending_updates=True)
    except Exception as e:
        print(f"❌ [{INSTANCE_ID}] 啟動失敗: {e}", flush=True)

if __name__ == '__main__':
    main()
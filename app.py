import os
import random
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

# 雲端伺服器時間可能不是台灣時區，統一用台北時間記錄時間戳記
TAIPEI_TZ = ZoneInfo("Asia/Taipei")


def now_str() -> str:
    return datetime.now(TAIPEI_TZ).strftime("%Y-%m-%d %H:%M:%S")

# ----------------------------
# 基本設定
# ----------------------------
st.set_page_config(page_title="個人行為模式追蹤儀表板", page_icon=None, layout="centered")

# ============================================================
# Demo 模式偵測（網址後加 ?demo=true 即進入示範模式）
# 示範模式下所有資料存在當次瀏覽的記憶體中，不會讀寫 Google Sheets
# ============================================================
IS_DEMO = st.query_params.get("demo", "").lower() in ("1", "true", "yes")

# 示範起始點數：設計成再點幾下「登高」按鈕就能解鎖「喜相逢餐席」，製造驚喜感
DEMO_INITIAL_EARNED = 4500

# 示範模式的假圖表數據（讓行為分析圖表有內容可看）
DEMO_FAKE_RECORDS = [
    ("2026-06-01 08:00:00", "看書", 500),
    ("2026-06-01 20:00:00", "書法", 500),
    ("2026-06-02 09:00:00", "帶貓散步", 500),
    ("2026-06-02 18:00:00", "擺棋", 300),
    ("2026-06-03 07:30:00", "晨興與讀經", 300),
    ("2026-06-03 11:00:00", "幫貓梳毛", 150),
    ("2026-06-04 10:00:00", "探索 AI", 150),
    ("2026-06-04 14:00:00", "讀英文", 150),
    ("2026-06-05 08:00:00", "健身", 300),
    ("2026-06-05 15:00:00", "單車遊騎", 500),
    ("2026-06-06 09:00:00", "看書", 500),
    ("2026-06-06 17:00:00", "家事（打掃/洗衣）", 300),
    ("2026-06-07 08:30:00", "稱讚他人", 150),
    ("2026-06-07 11:00:00", "書法", 500),
]

# 示範模式 Session State 初始化（只在第一次載入時執行一次）
if IS_DEMO and "demo_initialized" not in st.session_state:
    st.session_state.demo_initialized = True
    st.session_state.demo_earned = DEMO_INITIAL_EARNED
    st.session_state.demo_spent = 0
    st.session_state.demo_redeemed = set()
    st.session_state.demo_records = []  # 本次 session 中新增的行為紀錄

# 活動清單與點數權重（已硬編碼，畫面不再提供動態新增功能）
ACTIVITIES = {
    "登高": {
        "看書": 500,
        "書法": 500,
        "帶貓散步": 500,
        "單車遊騎": 500,
    },
    "乘興": {
        "家事（打掃/洗衣）": 300,
        "擺棋": 300,
        "晨興與讀經": 300,
        "健身": 300,
    },
    "拾趣": {
        "幫貓梳毛": 150,
        "稱讚他人": 150,
        "探索 AI": 150,
        "讀英文": 150,
    },
}

# 江戶傳統色系，用於圖表配色
EDO_COLORS = ["#2C2C2C", "#E34234", "#2A5CAA", "#8C9E5E"]

# 大賞閣：點數經濟兌換品項（已硬編碼，圖片請放在 app.py 同一個資料夾）
# image 為「不含副檔名」的檔名，實際讀取時會自動嘗試 .png / .jpg / .jpeg
REWARDS = [
    {"label": "夢幻樂高組合", "price": 20000, "image": "lego"},
    {"label": "頂級私廚：喜相逢尊榮席", "price": 6000, "image": "restaurant"},
    {"label": "傳奇殿堂：百達翡麗名錶", "price": 1500000, "image": "watch"},
]

# 圖片可能是 .png、.jpg 或 .jpeg，依序尋找第一個存在的檔案
IMAGE_EXTS = (".png", ".jpg", ".jpeg")


def find_image(base_name: str):
    """依序尋找 base_name.png / .jpg / .jpeg，回傳第一個存在的檔案路徑；找不到則回傳 None。"""
    for ext in IMAGE_EXTS:
        path = base_name + ext
        if os.path.exists(path):
            return path
    return None

# ----------------------------
# 隨機圖卡彩蛋設定
# ----------------------------
EASTER_EGG_DIR = "cat_easter_eggs"
EASTER_EGG_EXTS = (".png", ".jpg", ".jpeg")

# 點擊以下活動時，有機會觸發貓咪圖卡彩蛋
EASTER_EGG_TRIGGERS = {"帶貓散步", "幫貓梳毛"}

EASTER_EGG_PHRASES = [
    "主子表示滿意！",
    "獲得一次極致的心靈療癒～",
    "貓咪偷偷蓋了一個肉球印章給你",
    "今日份的快樂已自動存檔",
    "你今天又多了一個被貓喜歡的理由",
    "叮～恭喜獲得限定款治癒畫面",
    "毛茸茸能量 +1，繼續加油吧",
    "這是貓咪給你的小小獎勵",
]

# 確保彩蛋圖庫資料夾存在，方便使用者放圖片
os.makedirs(EASTER_EGG_DIR, exist_ok=True)

# 金句分享：使用者可在此檔案放自己 flomo 收集的金句，每行一句
QUOTES_FILE = "quotes.txt"
if not os.path.exists(QUOTES_FILE):
    with open(QUOTES_FILE, "w", encoding="utf-8") as f:
        f.write(
            "把這裡換成你 flomo 裡的金句，一行一句即可\n"
            "今天的小事，都是未來回憶裡的大事\n"
            "慢慢來，比較快\n"
        )

# ----------------------------
# Google Sheets 連線設定
# ----------------------------
GSHEET_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# 用 tuple 而非 list，是因為下面的 get_worksheet 會被 @st.cache_resource 快取，
# 快取的參數必須是「可雜湊（hashable）」的型態，tuple 才符合資格。
BEHAVIOR_HEADERS = ("timestamp", "activity", "points")
EGG_HEADERS = ("timestamp", "image", "quote")
REDEMPTION_HEADERS = ("timestamp", "item", "cost")


@st.cache_resource(show_spinner=False)
def get_spreadsheet():
    """連線到 Google Sheets，並回傳整份試算表物件。

    需要在 .streamlit/secrets.toml（本機）或 Streamlit Cloud 的
    Secrets 設定中，提供 [gcp_service_account] 區塊與 gsheet_url。
    若尚未設定，會顯示中文提示並停止執行。
    """
    try:
        creds_dict = dict(st.secrets["gcp_service_account"])
        sheet_url = st.secrets["gsheet_url"]
    except KeyError:
        st.error(
            "尚未設定 Google Sheets 連線資訊。\n\n"
            "請依照「Google試算表設定指南.md」完成服務帳號與 secrets 設定後，再重新整理這個頁面。"
        )
        st.stop()

    try:
        creds = Credentials.from_service_account_info(creds_dict, scopes=GSHEET_SCOPES)
        client = gspread.authorize(creds)
        return client.open_by_url(sheet_url)
    except Exception as e:
        st.error(
            "無法連線到 Google Sheets，請檢查：\n"
            "1. secrets 內容是否完整正確\n"
            "2. 該 Google 試算表是否已分享給服務帳號信箱（編輯者權限）\n\n"
            f"錯誤訊息：{e}"
        )
        st.stop()


@st.cache_resource(show_spinner=False)
def get_worksheet(name: str, headers: tuple):
    """取得指定名稱的工作表，若不存在則自動建立並寫入標題列。

    這裡用 @st.cache_resource 快取「工作表物件」本身：gspread 每次呼叫
    sh.worksheet(name) 都會額外打一次 API 去查詢試算表結構，互動一多
    很容易撞到 Google Sheets 的請求配額（429 錯誤）。快取後同一個工作表
    在整個 App 生命週期只會查詢一次。
    """
    sh = get_spreadsheet()
    try:
        ws = sh.worksheet(name)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=name, rows=2000, cols=max(len(headers), 3))
        ws.append_row(list(headers))
    return ws


def safe_get_all_records(ws) -> list:
    """讀取工作表所有紀錄；遇到 Google Sheets API 暫時性錯誤（例如配額超限）
    時顯示溫和提示並回傳空清單，避免整個頁面崩潰。
    """
    try:
        return ws.get_all_records()
    except gspread.exceptions.APIError:
        st.warning("Google Sheets 目前連線忙碌（可能是短時間內操作太頻繁），請稍候約 1 分鐘後重新整理頁面。")
        return []


def safe_append_row(ws, row: list) -> bool:
    """寫入一列資料；遇到 Google Sheets API 暫時性錯誤時顯示溫和提示，不中斷頁面。"""
    try:
        ws.append_row(row, value_input_option="USER_ENTERED")
        return True
    except gspread.exceptions.APIError:
        st.warning("Google Sheets 目前連線忙碌，這筆紀錄可能尚未儲存成功，請稍候再試一次。")
        return False


# ----------------------------
# 資料讀寫
# ----------------------------
def load_data() -> pd.DataFrame:
    ws = get_worksheet("behavior_log", BEHAVIOR_HEADERS)
    records = safe_get_all_records(ws)
    df = pd.DataFrame(records, columns=BEHAVIOR_HEADERS)
    if not df.empty:
        df["points"] = pd.to_numeric(df["points"], errors="coerce").fillna(0).astype(int)
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    return df


def append_record(activity: str, points: int) -> None:
    ws = get_worksheet("behavior_log", BEHAVIOR_HEADERS)
    safe_append_row(ws, [now_str(), activity, int(points)])


def load_egg_log() -> pd.DataFrame:
    ws = get_worksheet("easter_egg_log", EGG_HEADERS)
    records = safe_get_all_records(ws)
    df = pd.DataFrame(records, columns=EGG_HEADERS)
    if "quote" not in df.columns:
        df["quote"] = None
    if not df.empty:
        df["quote"] = df["quote"].replace("", pd.NA)
    return df


def log_easter_egg(image_path: str, quote) -> None:
    ws = get_worksheet("easter_egg_log", EGG_HEADERS)
    safe_append_row(ws, [now_str(), os.path.basename(image_path), quote or ""])


def load_redemptions() -> pd.DataFrame:
    """讀取大賞閣兌換紀錄，用來計算已花費點數與已解鎖的戰利品。"""
    ws = get_worksheet("redemptions", REDEMPTION_HEADERS)
    records = safe_get_all_records(ws)
    df = pd.DataFrame(records, columns=REDEMPTION_HEADERS)
    if not df.empty:
        df["cost"] = pd.to_numeric(df["cost"], errors="coerce").fillna(0).astype(int)
    return df


def log_redemption(item: str, cost: int) -> None:
    ws = get_worksheet("redemptions", REDEMPTION_HEADERS)
    safe_append_row(ws, [now_str(), item, int(cost)])


# ----------------------------
# 彩蛋相關函式
# ----------------------------
def get_random_easter_egg():
    """從 cat_easter_eggs 資料夾隨機挑一張圖片，找不到就回傳 None（不報錯）。"""
    try:
        if not os.path.isdir(EASTER_EGG_DIR):
            return None
        files = [
            f for f in os.listdir(EASTER_EGG_DIR)
            if f.lower().endswith(EASTER_EGG_EXTS)
        ]
        if not files:
            return None
        return os.path.join(EASTER_EGG_DIR, random.choice(files))
    except Exception:
        return None


def get_random_quote():
    """從 quotes.txt 隨機挑一句金句，找不到/沒內容就回傳 None（不報錯）。"""
    try:
        if not os.path.exists(QUOTES_FILE):
            return None
        with open(QUOTES_FILE, "r", encoding="utf-8") as f:
            quotes = [line.strip() for line in f if line.strip()]
        if not quotes:
            return None
        return random.choice(quotes)
    except Exception:
        return None


def trigger_easter_egg() -> None:
    """隨機抽取一張貓咪圖卡並記錄；找不到圖片時改顯示提示。
    供「帶貓散步」「幫貓梳毛」與大賞閣兌換成功時共用。
    """
    egg_path = get_random_easter_egg()
    if egg_path:
        quote = get_random_quote()
        if not IS_DEMO:  # 示範模式下不寫入真實的 Google Sheets
            log_easter_egg(egg_path, quote)
        st.session_state["easter_egg"] = {
            "image": egg_path,
            "phrase": random.choice(EASTER_EGG_PHRASES),
            "quote": quote,
        }
    else:
        st.session_state["egg_hint"] = True


@st.dialog("抽到隱藏圖卡！")
def show_easter_egg_dialog(image_path, phrase, quote):
    st.image(image_path, use_container_width=True)
    st.markdown(f"<h3 style='text-align:center;'>{phrase}</h3>", unsafe_allow_html=True)
    if quote:
        st.markdown(
            f"<p style='text-align:center; color:#888; font-style:italic;'>「{quote}」</p>",
            unsafe_allow_html=True,
        )
    if st.button("收下這份心意", use_container_width=True):
        st.session_state.pop("easter_egg", None)
        st.rerun()


# ----------------------------
# 手機版排版優化（CSS）
# ----------------------------
st.markdown(
    """
    <style>
    /* 載入思源宋體 (Noto Serif TC) */
    @import url('https://fonts.googleapis.com/css2?family=Noto+Serif+TC:wght@400;500;600;700&display=swap');

    /* 全域字體：強制套用思源宋體，營造典雅的版畫質感 */
    html, body, [class*="st-"], p, div, span, li, label,
    h1, h2, h3, h4, h5, h6,
    div.stButton > button {
        font-family: 'Noto Serif TC', serif !important;
    }

    /* 還原圖示用字型：避免展開箭頭、checkbox 勾勾等圖示
       被思源宋體覆蓋後顯示成 "arrow_xxx" 之類的文字 */
    [data-testid="stIconMaterial"],
    [data-testid="stExpanderToggleIcon"],
    span[class*="material-symbols"],
    .material-symbols-outlined,
    .material-symbols-rounded {
        font-family: 'Material Symbols Rounded', 'Material Symbols Outlined' !important;
    }

    /* 標題字距加寬，增加呼吸感 */
    h1, h2, h3, h4, h5, h6 {
        letter-spacing: 0.05em;
    }

    /* 整體內容區在小螢幕上左右留白縮小，畫面更寬敞 */
    .block-container {
        padding-top: 1.2rem;
        padding-bottom: 2rem;
        padding-left: 1rem;
        padding-right: 1rem;
        max-width: 720px;
    }

    /* 按鈕加大，手指更好點，文字可換行避免被裁切 */
    div.stButton > button {
        min-height: 3.2em;
        width: 100%;
        font-size: 1.05rem;
        line-height: 1.3;
        white-space: normal;
        word-break: keep-all;
        border-radius: 12px;
        letter-spacing: 0.05em;
        padding: 0.6em 1em;
    }

    /* 進度條加高，手機上更清楚 */
    div[data-testid="stProgress"] > div > div {
        height: 1rem;
        border-radius: 6px;
    }

    /* 圖片/圖表角落圓角，視覺更柔和 */
    div[data-testid="stImage"] img {
        border-radius: 12px;
    }

    /* 氣韻存摺：莊重醒目的大字點數顯示 */
    .qiyun-balance {
        font-family: 'Noto Serif TC', serif;
        font-size: 2rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        color: #2C2C2C;
        margin: 0.1em 0 0.2em 0;
    }

    /* 大賞閣：已擁有的戰利品標記 */
    .reward-owned-badge {
        display: inline-block;
        background-color: #E34234;
        color: #FDFBF7;
        font-size: 0.8rem;
        font-weight: 600;
        letter-spacing: 0.15em;
        padding: 0.2em 0.9em;
        border-radius: 999px;
        margin: 0.4em 0;
    }

    /* 和紙紋理卡片容器：淺灰底 + 極淡的纖維紋理，營造「紙張」的層次感 */
    .wood-card-marker {
        display: none;
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.wood-card-marker) {
        background-color: #F0EBE1;
        background-image: url("data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIzMDAiIGhlaWdodD0iMzAwIj4KPGZpbHRlciBpZD0ibiI+CjxmZVR1cmJ1bGVuY2UgdHlwZT0iZnJhY3RhbE5vaXNlIiBiYXNlRnJlcXVlbmN5PSIwLjg1IiBudW1PY3RhdmVzPSI0IiBzdGl0Y2hUaWxlcz0ic3RpdGNoIiByZXN1bHQ9Im5vaXNlIi8+CjxmZUNvbG9yTWF0cml4IGluPSJub2lzZSIgdHlwZT0ibWF0cml4IiB2YWx1ZXM9IjAgMCAwIDAgMC4xNyAgMCAwIDAgMCAwLjE3ICAwIDAgMCAwIDAuMTcgIDAgMCAwIDAuMTggMCIvPgo8L2ZpbHRlcj4KPHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsdGVyPSJ1cmwoI24pIi8+Cjwvc3ZnPgo=");
        background-size: 300px 300px;
        background-repeat: repeat;
        border-radius: 16px;
    }

    /* 窄螢幕（手機）進一步調整字級與間距 */
    @media (max-width: 480px) {
        /* 內容整體往下推，避免 Streamlit Cloud 在手機上的管理工具列蓋到橫幅圖片 */
        .block-container {
            padding-top: 3.5rem;
        }
        h1 {
            font-size: 1.5rem !important;
        }
        h2, h3 {
            font-size: 1.15rem !important;
        }
        div.stButton > button {
            font-size: 0.95rem;
            min-height: 3.4em;
            padding: 0.4em 0.3em;
        }
        .stCaption, .stMarkdown p {
            font-size: 0.9rem;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ----------------------------
# 介面
# ----------------------------
# 置頂橫幅圖片（把 banner.jpg 或 banner.png 放在 app.py 同一個資料夾即可顯示；沒有圖片時自動略過，不會報錯）
for _banner_name in ("banner.jpg", "banner.jpeg", "banner.png"):
    if os.path.exists(_banner_name):
        st.image(_banner_name, use_container_width=True)
        break

st.title("浮世貓百景：日常行為繪卷")
st.caption("落子、掃拭、賞貓，鐫刻專屬的行為版畫")

if IS_DEMO:
    st.info("目前為示範模式 — 數據僅在此次瀏覽中有效，不會影響真實紀錄。重新整理頁面即可重置。")

# 加到手機主畫面教學
with st.expander("把這個網頁加到手機主畫面，當 App 使用"):
    st.markdown(
        """
**iPhone（Safari 瀏覽器）**
1. 用 Safari 打開這個網頁
2. 點下方工具列中間的「分享」圖示（方框＋向上箭頭）
3. 往下滑，點選「加入主畫面」
4. 右上角按「新增」即完成

**Android（Chrome 瀏覽器）**
1. 用 Chrome 打開這個網頁
2. 點右上角「⋮」選單
3. 選擇「加到主畫面」或「安裝應用程式」
4. 按「新增」/「安裝」即完成

完成後，手機桌面會出現一個圖示，點它就能直接打開，使用體驗就像一個獨立的 App。
        """
    )

# 若有待顯示的彩蛋，先彈出對話框並施放氣球
if "easter_egg" in st.session_state:
    st.balloons()
    egg = st.session_state["easter_egg"]
    show_easter_egg_dialog(egg["image"], egg["phrase"], egg.get("quote"))

# 找不到圖庫資料夾/沒有圖片時的溫和提示（只顯示一次）
if st.session_state.pop("egg_hint", False):
    st.info("請將專屬畫作放入 cat_easter_eggs 資料夾以解鎖彩蛋")

if IS_DEMO:
    # 示範模式：全從 session_state 讀取，不碰 Google Sheets
    total_earned = st.session_state.get("demo_earned", DEMO_INITIAL_EARNED)
    total_spent = st.session_state.get("demo_spent", 0)
    redeemed_items = st.session_state.get("demo_redeemed", set())
    available_points = total_earned - total_spent

    _all_records = DEMO_FAKE_RECORDS + st.session_state.get("demo_records", [])
    df = pd.DataFrame(_all_records, columns=BEHAVIOR_HEADERS)
    df["points"] = pd.to_numeric(df["points"], errors="coerce").fillna(0).astype(int)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
else:
    df = load_data()
    total_earned = int(df["points"].sum()) if not df.empty else 0

    redemptions_df = load_redemptions()
    total_spent = int(redemptions_df["cost"].sum()) if not redemptions_df.empty else 0
    redeemed_items = set(redemptions_df["item"]) if not redemptions_df.empty else set()

    available_points = total_earned - total_spent

# 1. 氣韻存摺，包在和紙紋理容器中
with st.container(border=True):
    st.markdown('<div class="wood-card-marker"></div>', unsafe_allow_html=True)

    st.markdown(
        f'<div class="qiyun-balance">目前積蓄的氣韻：{available_points:,}</div>',
        unsafe_allow_html=True,
    )
    st.caption(f"歷史總累積點數：{total_earned:,}")

# 2. 一鍵紀錄按鈕（每個分類各自一個和紙紋理容器，按鈕等寬並排）
st.subheader("點擊紀錄")

for zone, items in ACTIVITIES.items():
    with st.container(border=True):
        st.markdown('<div class="wood-card-marker"></div>', unsafe_allow_html=True)

        st.markdown(f"**【{zone}】（每次 {list(items.values())[0]} 點）**")
        cols = st.columns(len(items))
        for col, (label, pts) in zip(cols, items.items()):
            if col.button(label, use_container_width=True, key=f"btn_{label}"):
                if IS_DEMO:
                    st.session_state.demo_earned = st.session_state.get("demo_earned", DEMO_INITIAL_EARNED) + pts
                    st.session_state.demo_records = st.session_state.get("demo_records", []) + [(now_str(), label, pts)]
                else:
                    append_record(label, pts)
                st.toast(f"已記錄：{label} (+{pts} 點)")

                # 觸發貓咪圖卡彩蛋
                if label in EASTER_EGG_TRIGGERS:
                    trigger_easter_egg()

                st.rerun()

st.divider()

# 大賞閣：常駐畫廊，三圖並立，永久陳列目標牆
st.subheader("【大賞閣】")

with st.container(border=True):
    st.markdown('<div class="wood-card-marker"></div>', unsafe_allow_html=True)

    cols = st.columns(len(REWARDS))
    for col, (idx, reward) in zip(cols, enumerate(REWARDS)):
        label, price, image = reward["label"], reward["price"], reward["image"]
        owned = label in redeemed_items

        with col:
            img_path = find_image(image)
            if img_path:
                st.image(img_path, use_container_width=True)

            st.markdown(f"**{label}**")
            st.caption(f"{price:,} 點")

            if owned:
                st.markdown('<div class="reward-owned-badge">已擁有</div>', unsafe_allow_html=True)
                st.button(
                    "✅ 已將此賞存入繪卷",
                    use_container_width=True,
                    disabled=True,
                    key=f"redeemed_{idx}",
                )
            else:
                if st.button(
                    "兌換",
                    use_container_width=True,
                    disabled=available_points < price,
                    key=f"redeem_{idx}",
                ):
                    if IS_DEMO:
                        st.session_state.demo_spent = st.session_state.get("demo_spent", 0) + price
                        _redeemed = st.session_state.get("demo_redeemed", set())
                        _redeemed.add(label)
                        st.session_state.demo_redeemed = _redeemed
                    else:
                        log_redemption(label, price)
                    trigger_easter_egg()
                    st.rerun()

st.divider()

# 3. 行為模式視覺化
st.subheader("行為模式分析（各項目累積次數）")

if not df.empty:
    import plotly.express as px

    counts = df["activity"].value_counts().reset_index()
    counts.columns = ["activity", "count"]

    chart_type = st.radio("圖表類型", ["長條圖", "圓餅圖"], horizontal=True, label_visibility="collapsed")

    if chart_type == "長條圖":
        fig = px.bar(
            counts.sort_values("count"),
            x="count",
            y="activity",
            orientation="h",
            text="count",
            color="activity",
            color_discrete_sequence=EDO_COLORS,
            labels={"count": "次數", "activity": ""},
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(
            yaxis=dict(tickfont=dict(size=14)),
            margin=dict(l=10, r=10, t=10, b=10),
            showlegend=False,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        fig = px.pie(counts, values="count", names="activity", color_discrete_sequence=EDO_COLORS)
        fig.update_traces(textinfo="percent+label", textfont_size=14)
        fig.update_layout(
            margin=dict(l=10, r=10, t=10, b=10),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, use_container_width=True)
else:
    st.info("尚無紀錄，點擊上方按鈕開始記錄吧！")

st.divider()

# 4. 我的圖卡收藏
st.subheader("我的圖卡收藏")

# 示範模式下不讀真實的 Google Sheets 圖卡紀錄，回傳空表即可
egg_log = pd.DataFrame(columns=EGG_HEADERS) if IS_DEMO else load_egg_log()
if not egg_log.empty:
    collected = egg_log["image"].value_counts()
    st.caption(f"已收集 {len(collected)} 款不同圖卡，累積抽中 {len(egg_log)} 次")

    cards = list(collected.items())
    cards_per_row = 3
    for i in range(0, len(cards), cards_per_row):
        cols = st.columns(cards_per_row)
        for col, (img_name, count) in zip(cols, cards[i:i + cards_per_row]):
            img_path = os.path.join(EASTER_EGG_DIR, img_name)
            if os.path.exists(img_path):
                col.image(img_path, use_container_width=True)
                col.caption(f"x{count}")

                # 顯示這張圖卡最近一次抽到時搭配的金句
                quotes_for_img = egg_log.loc[
                    (egg_log["image"] == img_name) & egg_log["quote"].notna(),
                    "quote",
                ]
                if not quotes_for_img.empty:
                    col.markdown(
                        f"<p style='font-size:0.85em; color:#888; font-style:italic;'>「{quotes_for_img.iloc[-1]}」</p>",
                        unsafe_allow_html=True,
                    )
else:
    st.caption("還沒有抽到任何圖卡，去點「帶貓散步」或「幫貓梳毛」試試運氣吧！")

st.divider()

# 5. 原始數據與下載
with st.expander("點擊展開原始數據紀錄"):
    if not df.empty:
        display_df = df.sort_values("timestamp", ascending=False).reset_index(drop=True)
        st.dataframe(display_df, use_container_width=True)

        csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            label="下載 CSV 數據",
            data=csv_bytes,
            file_name="behavior_log.csv",
            mime="text/csv",
            use_container_width=True,
        )
    else:
        st.write("目前沒有任何紀錄。")

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
st.set_page_config(page_title="個人行為模式追蹤儀表板", page_icon="🌱", layout="centered")

SEASON_GOAL = 10000  # 本季目標總點數

# 活動清單與點數權重
ACTIVITIES = {
    "高阻力區": {
        "📖 看書（40頁）": 500,
        "🖌️ 寫書法": 500,
        "🐱 帶貓散步": 500,
    },
    "心流區": {
        "🧹 打掃（清動線）": 300,
        "♟️ 擺棋": 300,
        "📜 讀聖經": 300,
    },
    "微小溫暖區": {
        "🐾 幫貓梳毛": 150,
        "👍 稱讚別人": 150,
    },
}

ZONE_COLOR = {
    "高阻力區": "🔥",
    "心流區": "🌊",
    "微小溫暖區": "☀️",
}

# ----------------------------
# 隨機圖卡彩蛋設定
# ----------------------------
EASTER_EGG_DIR = "cat_easter_eggs"
EASTER_EGG_EXTS = (".png", ".jpg", ".jpeg")

# 點擊以下活動時，有機會觸發貓咪圖卡彩蛋
EASTER_EGG_TRIGGERS = {"🐱 帶貓散步", "🐾 幫貓梳毛"}

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

BEHAVIOR_HEADERS = ["timestamp", "activity", "points"]
EGG_HEADERS = ["timestamp", "image", "quote"]
CUSTOM_HEADERS = ["label", "points"]


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
            "⚠️ 尚未設定 Google Sheets 連線資訊。\n\n"
            "請依照「Google試算表設定指南.md」完成服務帳號與 secrets 設定後，再重新整理這個頁面。"
        )
        st.stop()

    try:
        creds = Credentials.from_service_account_info(creds_dict, scopes=GSHEET_SCOPES)
        client = gspread.authorize(creds)
        return client.open_by_url(sheet_url)
    except Exception as e:
        st.error(
            "⚠️ 無法連線到 Google Sheets，請檢查：\n"
            "1. secrets 內容是否完整正確\n"
            "2. 該 Google 試算表是否已分享給服務帳號信箱（編輯者權限）\n\n"
            f"錯誤訊息：{e}"
        )
        st.stop()


def get_worksheet(name: str, headers: list):
    """取得指定名稱的工作表，若不存在則自動建立並寫入標題列。"""
    sh = get_spreadsheet()
    try:
        ws = sh.worksheet(name)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=name, rows=2000, cols=max(len(headers), 3))
        ws.append_row(headers)
    return ws


# ----------------------------
# 資料讀寫
# ----------------------------
def load_data() -> pd.DataFrame:
    ws = get_worksheet("behavior_log", BEHAVIOR_HEADERS)
    records = ws.get_all_records()
    df = pd.DataFrame(records, columns=BEHAVIOR_HEADERS)
    if not df.empty:
        df["points"] = pd.to_numeric(df["points"], errors="coerce").fillna(0).astype(int)
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    return df


def append_record(activity: str, points: int) -> None:
    ws = get_worksheet("behavior_log", BEHAVIOR_HEADERS)
    ws.append_row([now_str(), activity, int(points)], value_input_option="USER_ENTERED")


def remove_last_record() -> None:
    ws = get_worksheet("behavior_log", BEHAVIOR_HEADERS)
    total_rows = len(ws.get_all_values())
    if total_rows > 1:  # 第 1 列是標題列
        ws.delete_rows(total_rows)


def load_egg_log() -> pd.DataFrame:
    ws = get_worksheet("easter_egg_log", EGG_HEADERS)
    records = ws.get_all_records()
    df = pd.DataFrame(records, columns=EGG_HEADERS)
    if "quote" not in df.columns:
        df["quote"] = None
    if not df.empty:
        df["quote"] = df["quote"].replace("", pd.NA)
    return df


def log_easter_egg(image_path: str, quote) -> None:
    ws = get_worksheet("easter_egg_log", EGG_HEADERS)
    ws.append_row(
        [now_str(), os.path.basename(image_path), quote or ""],
        value_input_option="USER_ENTERED",
    )


def load_custom_activities() -> list:
    ws = get_worksheet("custom_activities", CUSTOM_HEADERS)
    records = ws.get_all_records()
    items = []
    for r in records:
        label = str(r.get("label", "")).strip()
        if not label:
            continue
        try:
            pts = int(float(r.get("points", 0)))
        except (TypeError, ValueError):
            pts = 0
        items.append({"label": label, "points": pts})
    return items


def save_custom_activities(items: list) -> None:
    ws = get_worksheet("custom_activities", CUSTOM_HEADERS)
    ws.clear()
    rows = [CUSTOM_HEADERS] + [[item["label"], item["points"]] for item in items]
    ws.update(rows)


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


@st.dialog("🎁 抽到隱藏圖卡！")
def show_easter_egg_dialog(image_path, phrase, quote):
    st.image(image_path, use_container_width=True)
    st.markdown(f"<h3 style='text-align:center;'>{phrase}</h3>", unsafe_allow_html=True)
    if quote:
        st.markdown(
            f"<p style='text-align:center; color:#888; font-style:italic;'>「{quote}」</p>",
            unsafe_allow_html=True,
        )
    if st.button("收下這份心意 💖", use_container_width=True):
        st.session_state.pop("easter_egg", None)
        st.rerun()


# ----------------------------
# 手機版排版優化（CSS）
# ----------------------------
st.markdown(
    """
    <style>
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

    /* 窄螢幕（手機）進一步調整字級與間距 */
    @media (max-width: 480px) {
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

# 加到手機主畫面教學
with st.expander("📱 把這個網頁加到手機主畫面，當 App 使用"):
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
    st.info("📂 請將專屬畫作放入 cat_easter_eggs 資料夾以解鎖彩蛋", icon="🐈")

df = load_data()
total_points = int(df["points"].sum()) if not df.empty else 0

# 1. 總點數與進度條
st.subheader(f"🎯 目前累積總點數：{total_points:,} / {SEASON_GOAL:,}")
progress = min(total_points / SEASON_GOAL, 1.0)
st.progress(progress)
st.caption(f"本季進度：{progress * 100:.1f}%")

st.divider()

# 2. 一鍵紀錄按鈕
st.subheader("✅ 點擊紀錄")

for zone, items in ACTIVITIES.items():
    st.markdown(f"**{ZONE_COLOR[zone]} {zone}（每次 {list(items.values())[0]} 點）**")
    cols = st.columns(len(items))
    for col, (label, pts) in zip(cols, items.items()):
        if col.button(label, use_container_width=True, key=f"btn_{label}"):
            append_record(label, pts)
            st.toast(f"已記錄：{label} (+{pts} 點)", icon="✅")

            # 觸發貓咪圖卡彩蛋
            if label in EASTER_EGG_TRIGGERS:
                egg_path = get_random_easter_egg()
                if egg_path:
                    quote = get_random_quote()
                    log_easter_egg(egg_path, quote)
                    st.session_state["easter_egg"] = {
                        "image": egg_path,
                        "phrase": random.choice(EASTER_EGG_PHRASES),
                        "quote": quote,
                    }
                else:
                    st.session_state["egg_hint"] = True

            st.rerun()

# 自訂項目
custom_items = load_custom_activities()

if custom_items:
    st.markdown("**✨ 自訂項目**")
    for i in range(0, len(custom_items), 3):
        cols = st.columns(3)
        for col, item in zip(cols, custom_items[i:i + 3]):
            c_label, c_pts = item["label"], item["points"]
            if col.button(f"{c_label}（{c_pts}點）", use_container_width=True, key=f"btn_custom_{i}_{c_label}"):
                append_record(c_label, c_pts)
                st.toast(f"已記錄：{c_label} (+{c_pts} 點)", icon="✅")
                st.rerun()

with st.expander("➕ 新增/管理自訂項目"):
    with st.form("add_custom_activity", clear_on_submit=True):
        new_label = st.text_input("項目名稱")
        new_points = st.number_input("點數", min_value=1, max_value=10000, value=100, step=10)
        if st.form_submit_button("新增") and new_label.strip():
            custom_items.append({"label": new_label.strip(), "points": int(new_points)})
            save_custom_activities(custom_items)
            st.rerun()

    if custom_items:
        st.markdown("**目前自訂項目：**")
        for idx, item in enumerate(custom_items):
            c1, c2 = st.columns([4, 1])
            c1.write(f"{item['label']}（{item['points']} 點）")
            if c2.button("刪除", key=f"del_custom_{idx}"):
                custom_items.pop(idx)
                save_custom_activities(custom_items)
                st.rerun()

# 撤銷上一筆（避免手滑誤點）
if not df.empty:
    with st.expander("⚙️ 其他操作"):
        if st.button("↩️ 撤銷最後一筆紀錄"):
            remove_last_record()
            st.rerun()

st.divider()

# 3. 行為模式視覺化
st.subheader("📊 行為模式分析（各項目累積次數）")

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
            labels={"count": "次數", "activity": ""},
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(yaxis=dict(tickfont=dict(size=14)), margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
    else:
        fig = px.pie(counts, values="count", names="activity")
        fig.update_traces(textinfo="percent+label", textfont_size=14)
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
else:
    st.info("尚無紀錄，點擊上方按鈕開始記錄吧！")

st.divider()

# 4. 我的圖卡收藏
st.subheader("📚 我的圖卡收藏")

egg_log = load_egg_log()
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
st.subheader("📁 原始數據紀錄")

if not df.empty:
    display_df = df.sort_values("timestamp", ascending=False).reset_index(drop=True)
    st.dataframe(display_df, use_container_width=True)

    csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label="⬇️ 下載 CSV 數據",
        data=csv_bytes,
        file_name="behavior_log.csv",
        mime="text/csv",
        use_container_width=True,
    )
else:
    st.write("目前沒有任何紀錄。")

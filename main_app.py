import streamlit as st
import pandas as pd
import re
import uuid
from datetime import datetime, timezone, timedelta
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io
import time
import extra_streamlit_components as stx

# 자동 번역으로 인한 글자 깨짐 방지
st.markdown('<meta name="google" content="notranslate">', unsafe_allow_html=True)


# ==========================================
# 🇰🇷 한국 표준시(KST) 구하기 함수
# ==========================================
def get_kst_now():
    kst = timezone(timedelta(hours=9))
    return datetime.now(kst).strftime("%Y-%m-%d %H:%M")


def generate_request_id():
    ts = datetime.now(timezone(timedelta(hours=9))).strftime("%y%m%d%H%M%S")
    return f"{ts}-{uuid.uuid4().hex[:5]}"


def col_letter(n):
    letters = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


# ==========================================
# 0. 페이지 기본 설정 및 쿠키 매니저 초기화
# ==========================================
st.set_page_config(
    page_title="러셀대치학원 시설보수 및 재고관리 시스템",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded"
)

def get_cookie_manager():
    return stx.CookieManager(key="cookie_manager")

cookie_manager = get_cookie_manager()

# ==========================================
# Custom CSS (디자인 및 시각성 개선)
# ==========================================
st.markdown("""
    <style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');

    /* 글로벌 폰트 및 배경 설정 */
    html, body, [class*="css"], .stApp {
        font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, Roboto, sans-serif !important;
        background-color: #F4F7FB !important; /* 약간 더 밝고 시원한 배경색 */
        color: #1e293b !important;
        font-size: 15.5px;
        line-height: 1.6;
        letter-spacing: -0.015em;
        -webkit-font-smoothing: antialiased;
        text-rendering: optimizeLegibility;
    }

    .block-container {
        padding-top: 1.8rem !important;
        max-width: 1280px; /* 가로폭 조금 더 넓게 */
    }

    /* 사이드바 스타일 개선 */
    [data-testid="stSidebar"] {
        background-color: #111827 !important; /* 조금 더 다크한 네이비 */
        border-right: 1px solid #1f2937;
    }
    [data-testid="stSidebar"] * {
        color: #f3f4f6 !important;
    }
    [data-testid="stSidebar"] hr { border-color: #374151 !important; margin: 1.5rem 0; }

    /* 사이드바 라디오 버튼 */
    [data-testid="stSidebar"] [data-testid="stRadio"] label p {
        color: #f3f4f6 !important;
        font-weight: 500 !important;
        font-size: 0.95rem !important;
    }
    [data-testid="stSidebar"] [data-testid="stRadio"] div[role="radiogroup"] > label {
        padding: 12px 14px;
        border-radius: 8px;
        margin-bottom: 8px;
        background-color: transparent;
        transition: all 0.2s ease;
    }
    [data-testid="stSidebar"] [data-testid="stRadio"] div[role="radiogroup"] > label:hover {
        background-color: #1f2937 !important;
    }
    [data-testid="stSidebar"] [data-testid="stRadio"] div[role="radiogroup"] > label[aria-checked="true"] {
        background-color: #2563eb !important; /* 선택된 메뉴 파란색 강조 */
    }

    /* 🔥 본문 메인 영역 라디오 버튼 (알약 형태) */
    .stMainBlockContainer [data-testid="stRadio"] label p,
    .stMainBlockContainer [data-testid="stRadio"] div[role="radiogroup"] label p {
        color: #334155 !important;
        font-weight: 600 !important;
        font-size: 0.95rem !important;
    }
    .stMainBlockContainer [data-testid="stRadio"] div[role="radiogroup"] > label {
        background-color: #ffffff !important;
        border: 1px solid #e2e8f0 !important;
        padding: 8px 16px !important;
        border-radius: 99px !important; /* 완전한 둥근 알약형 */
        margin-right: 8px !important;
        box-shadow: 0 1px 2px rgba(0,0,0,0.03);
        transition: all 0.2s ease;
    }
    .stMainBlockContainer [data-testid="stRadio"] div[role="radiogroup"] > label:hover {
        background-color: #f8fafc !important;
        border-color: #cbd5e1 !important;
    }
    .stMainBlockContainer [data-testid="stRadio"] div[role="radiogroup"] > label[aria-checked="true"] {
        background-color: #e0e7ff !important;
        border-color: #4f46e5 !important;
    }
    .stMainBlockContainer [data-testid="stRadio"] div[role="radiogroup"] > label[aria-checked="true"] p {
        color: #4338ca !important;
    }

    /* 유저 카드 (사이드바) */
    .user-card {
        background: linear-gradient(135deg, #1e3a8a, #3b82f6);
        border-radius: 12px;
        padding: 16px;
        margin-bottom: 20px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }
    .user-card .u-name { font-size: 1.1rem; font-weight: 700; color: white !important;}
    .user-card .u-role {
        display: inline-block;
        margin-top: 6px;
        font-size: 0.75rem;
        font-weight: 600;
        background: rgba(255,255,255,0.2);
        padding: 3px 10px;
        border-radius: 999px;
        color: white !important;
    }
    .clock-box {
        font-size: 0.85rem;
        color: #9ca3af !important;
        margin-bottom: 12px;
        font-weight: 500;
    }

    /* 타이포그래피 */
    h1, h2, h3, h4, h5, h6 {
        color: #0f172a !important;
        font-weight: 700 !important;
        letter-spacing: -0.02em !important;
    }
    h1 { font-size: 1.75rem !important; margin-bottom: 1rem !important; }
    h2 { font-size: 1.35rem !important; border-bottom: 2px solid #e2e8f0; padding-bottom: 0.5rem; margin-bottom: 1rem;}
    h3 { font-size: 1.15rem !important; }

    [data-testid="stCaptionContainer"], .stCaption {
        font-size: 0.85rem !important;
        color: #64748b !important;
    }

    /* 폼 인풋 스타일 */
    .stTextInput input, .stSelectbox div[data-baseweb="select"],
    .stNumberInput input, .stTextArea textarea {
        background-color: #ffffff !important;
        color: #1e293b !important;
        border: 1px solid #cbd5e1 !important;
        border-radius: 8px !important;
        padding: 10px 12px;
        transition: border-color 0.15s ease, box-shadow 0.15s ease;
    }
    .stTextInput input:focus, .stSelectbox div[data-baseweb="select"]:focus-within,
    .stNumberInput input:focus, .stTextArea textarea:focus {
        border-color: #3b82f6 !important;
        box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2) !important;
    }

    /* 버튼 스타일 */
    .stButton>button, .stFormSubmitButton>button {
        border-radius: 8px;
        font-weight: 600;
        background-color: #1e40af !important;
        color: #ffffff !important;
        border: none;
        padding: 0.6rem 1.2rem;
        transition: all 0.2s ease;
        box-shadow: 0 1px 2px rgba(0,0,0,0.05);
    }
    .stButton>button:hover, .stFormSubmitButton>button:hover {
        background-color: #1d4ed8 !important;
        transform: translateY(-1px);
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }
    .stButton>button:active, .stFormSubmitButton>button:active {
        transform: translateY(0);
    }

    /* 탭 스타일 */
    .stTabs [data-baseweb="tab-list"] { 
        gap: 8px; 
        border-bottom: 1px solid #e2e8f0;
        padding-bottom: 2px;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: transparent;
        border: none;
        padding: 10px 16px;
        font-weight: 600;
        color: #64748b !important;
        border-radius: 6px 6px 0 0;
    }
    .stTabs [aria-selected="true"] {
        background-color: transparent !important;
        color: #1e40af !important;
        border-bottom: 3px solid #1e40af;
    }
    .stTabs [aria-selected="true"] p { color: #1e40af !important; }

    /* 메인 카드 섹션 */
    .section-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 24px;
        margin-bottom: 24px;
        box-shadow: 0 4px 6px -1px rgba(0,0,0,0.02), 0 2px 4px -1px rgba(0,0,0,0.02);
    }

    /* 뱃지 */
    .badge { display:inline-block; padding: 4px 12px; border-radius:6px; font-size:0.75rem; font-weight:700; letter-spacing: 0.02em;}
    .badge-접수완료 { background:#dbeafe; color:#1e40af !important; border: 1px solid #bfdbfe; }
    .badge-처리중 { background:#fef3c7; color:#92400e !important; border: 1px solid #fde68a;}
    .badge-완료 { background:#dcfce7; color:#166534 !important; border: 1px solid #bbf7d0;}

    /* 로그인/메인 패널 */
    .brand-panel {
        background: linear-gradient(135deg, #0f172a, #1e3a8a);
        border-radius: 16px;
        padding: 40px;
        height: 100%;
        color: #fff !important;
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
    }
    .brand-panel * { color: #fff !important; }
    .brand-panel h1 { font-size: 1.8rem !important; margin-bottom: 12px !important; line-height: 1.3;}
    .brand-panel p { color: #cbd5e1 !important; font-size: 0.95rem; line-height: 1.6; }

    /* 재고 부족 필 */
    .low-stock-pill {
        display:inline-block; background:#fee2e2; color:#991b1b !important;
        padding: 4px 10px; border-radius: 6px; font-size:0.8rem; font-weight:600; margin: 4px 4px 0 0;
        border: 1px solid #fca5a5;
    }

    /* 테이블 스타일링 */
    .scroll-table { overflow-x: auto; -webkit-overflow-scrolling: touch; border-radius: 8px; border: 1px solid #e2e8f0; }
    .scroll-table table { width: 100%; border-collapse: collapse; background-color: white;}
    .scroll-table th { background-color: #f8fafc; font-weight: 600; color: #475569; text-transform: uppercase; font-size: 0.75rem; padding: 12px 16px; border-bottom: 2px solid #e2e8f0;}
    .scroll-table td { padding: 12px 16px; border-bottom: 1px solid #e2e8f0; font-size: 0.85rem; color: #334155; }
    .scroll-table tr:hover { background-color: #f1f5f9; }

    /* 메트릭 박스 */
    [data-testid="stMetric"] {
        background-color: white;
        border: 1px solid #e2e8f0;
        padding: 15px 20px;
        border-radius: 12px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }
    [data-testid="stMetricValue"] { font-weight: 800 !important; color: #0f172a !important;}
    [data-testid="stMetricLabel"] { font-weight: 600 !important; color: #64748b !important; font-size: 0.85rem;}

    @media (max-width: 640px) {
        .block-container { padding-left: 1rem !important; padding-right: 1rem !important; }
        .brand-panel { padding: 24px; border-radius: 12px; }
        .brand-panel h1 { font-size: 1.4rem !important; }
        .section-card { padding: 16px; border-radius: 8px; }
    }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 구글 API 연동
# ==========================================
@st.cache_resource
def get_google_services():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_dict = dict(st.secrets["gcp_service_account"])
    if "private_key" in creds_dict:
        pk = str(creds_dict["private_key"])
        pk = pk.replace("\\n", "\n")
        creds_dict["private_key"] = pk

    credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(credentials)
    drive_service = build('drive', 'v3', credentials=credentials)
    return gc, drive_service

try:
    with st.spinner("시스템 연결 중..."):
        gc, drive_service = get_google_services()
        sh = gc.open("러셀대치_통합DB")
        ws_users = sh.worksheet("users")
        ws_facility = sh.worksheet("facility")
        ws_inventory = sh.worksheet("inventory")
except Exception as e:
    st.error(f"⚠️️ 구글 시트 및 드라이브 연동에 실패했습니다: {e}")
    st.stop()

# 선택적 "config" 시트
try:
    ws_config = sh.worksheet("config")
except Exception:
    ws_config = None

try:
    FACILITY_HEADER = ws_facility.row_values(1)
except Exception:
    FACILITY_HEADER = []
FACILITY_HAS_ID = "요청ID" in FACILITY_HEADER


# ==========================================
# 캐시된 데이터 읽기 (예외 처리 추가)
# ==========================================
@st.cache_data(ttl=20, show_spinner=False)
def get_facility_records():
    try:
        return ws_facility.get_all_records()
    except Exception:
        return []

@st.cache_data(ttl=20, show_spinner=False)
def get_inventory_records():
    try:
        return ws_inventory.get_all_records()
    except Exception:
        return []

@st.cache_data(ttl=60, show_spinner=False)
def get_users_records():
    try:
        return ws_users.get_all_records()
    except Exception:
        return []

@st.cache_data(ttl=60, show_spinner=False)
def get_config_records():
    if ws_config is None:
        return []
    try:
        return ws_config.get_all_records()
    except Exception:
        return []


def find_facility_row_by_id(row_id):
    try:
        cell = ws_facility.find(str(row_id))
        return cell.row
    except Exception:
        return None


MAX_PHOTO_MB = 8

def photo_too_large(uploaded_file):
    return uploaded_file is not None and uploaded_file.size > MAX_PHOTO_MB * 1024 * 1024

def upload_photo_to_drive(uploaded_file):
    if uploaded_file is None:
        return ""
    if photo_too_large(uploaded_file):
        st.warning(f"사진 용량이 {MAX_PHOTO_MB}MB를 초과해 업로드를 건너뛰었습니다.")
        return ""
    try:
        img_bytes = uploaded_file.getvalue()
        mime_type = uploaded_file.type

        try:
            from PIL import Image
            img = Image.open(io.BytesIO(img_bytes))
            img.thumbnail((1600, 1600))
            buf = io.BytesIO()
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.save(buf, format="JPEG", quality=85, optimize=True)
            img_bytes = buf.getvalue()
            mime_type = "image/jpeg"
        except Exception:
            pass

        file_metadata = {'name': f"facility_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uploaded_file.name}"}
        media = MediaIoBaseUpload(io.BytesIO(img_bytes), mimetype=mime_type)
        file = drive_service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        drive_service.permissions().create(
            fileId=file.get('id'),
            body={'role': 'reader', 'type': 'anyone'}
        ).execute()
        return file.get('webViewLink', '')
    except Exception as e:
        st.warning(f"사진 업로드 실패: {e}")
        return ""

def clean_phone(phone_str):
    if pd.isna(phone_str):
        return ""
    return re.sub(r"[^0-9]", "", str(phone_str))

def status_badge(status):
    status = str(status).strip() or "접수완료"
    return f'<span class="badge badge-{status}">{status}</span>'


# ==========================================
# 물품/공간/분류 목록
# ==========================================
CONSUMABLES_BASE = [
    "A4용지", "A3용지", "B4용지", "미색A4용지", "미색A3용지",
    "분필(백)", "분필(청)", "분필(빨)", "분필(노)",
    "점보롤", "핸드타월", "물티슈", "각티슈", "물비누",
    "종이컵", "세모금컵", "생수", "AAA건전지", "AA건전지", "마이크 커버"
]

FLOORS = ["2층", "6층", "7층"]

# 구글 시트 열 헤더용 품목 전체 (층 구분 포함)
ALL_SHEET_ITEMS = [f"{item} ({floor})" for item in CONSUMABLES_BASE for floor in FLOORS] + [
    "노트북", "출결리더기", "보조배터리", "캠코더",
    "삼각대 및 플레이트", "SD카드", "빔포인터", "빔리모콘", "에어컨리모콘"
]

EQUIPMENT_DEFAULT = [
    "노트북", "출결리더기", "보조배터리", "캠코더",
    "삼각대 및 플레이트", "SD카드", "빔포인터", "빔리모콘", "에어컨리모콘"
]

SPACES_DEFAULT = {
    "강의실": ["대형강의실", "201호", "202호", "203호", "204호", "601호", "602호", "701호", "702호", "703호", "704호"],
    "자습관": ["3-1관", "3-2관", "3-3관", "3-4관", "3-5관", "4-1관", "4-2관", "4-3관", "4-4관", "4-5관", "5-1관", "5-2관", "5-3관", "6-1관", "6-2관", "7-1관"],
    "화장실": ["2층 남자화장실", "2층 여자화장실", "3층 남자화장실", "3층 여자화장실", "5층 남자화장실", "5층 여자화장실", "6층 남자화장실", "6층 여자화장실", "7층 남자화장실", "7층 여자화장실"],
    "기타공간": ["기타공간 (복도/엘리베이터/로비/사무실 등)"]
}

CATEGORY_BY_SPACE_DEFAULT = {
    "강의실": ["빔프로젝터/음향", "냉난방/환기", "조명/전기", "책상/의자/칠판", "문/창문/열쇠", "신규 물품 구매 요청", "기타 시설"],
    "자습관": ["자습관 책상/시디즈 의자", "스탠드/전기/콘센트", "냉난방/공기청정기", "공용 스탠딩 책상", "문/창문/소음 문제", "신규 물품 구매 요청", "기타 시설"],
    "화장실": ["대변기 (막힘/고장/부속)", "소변기 (막힘/자동센서/누수)", "세면대/수도꼭지", "휴지걸이/비누디스펜서", "조명/환풍기", "바닥 배수구/타일", "신규 물품 구매 요청", "기타 시설"],
    "기타공간": ["엘리베이터", "복도/계단/난간", "정수기/음료대", "자동문/출입문", "조명/전기", "신규 물품 구매 요청", "기타 시설"]
}

def _config_list(category, fallback):
    rows = get_config_records()
    items = [str(r.get("항목값", "")).strip() for r in rows
             if str(r.get("카테고리", "")).strip() == category and str(r.get("항목값", "")).strip()]
    return items if items else fallback

CONSUMABLES = _config_list("소모품", CONSUMABLES_BASE)
EQUIPMENT = _config_list("비품", EQUIPMENT_DEFAULT)

SPACES = {k: _config_list(f"공간_{k}", v) for k, v in SPACES_DEFAULT.items()}
CATEGORY_BY_SPACE = {k: _config_list(f"분류_{k}", v) for k, v in CATEGORY_BY_SPACE_DEFAULT.items()}

LOW_STOCK_THRESHOLDS = {"생수": 10, "물티슈": 5, "각티슈": 5}
DEFAULT_LOW_STOCK = {"consumable": 5, "equipment": 2}

def get_threshold(item):
    base_item = item.split(" (")[0]
    if base_item in LOW_STOCK_THRESHOLDS:
        return LOW_STOCK_THRESHOLDS[base_item]
    return DEFAULT_LOW_STOCK["consumable"] if base_item in CONSUMABLES else DEFAULT_LOW_STOCK["equipment"]

STATUS_OPTIONS = ["접수완료", "처리중", "완료"]

# 세션 초기화
if "logged_in" not in st.session_state: st.session_state["logged_in"] = False
if "user_name" not in st.session_state: st.session_state["user_name"] = ""
if "user_phone" not in st.session_state: st.session_state["user_phone"] = ""
if "user_role" not in st.session_state: st.session_state["user_role"] = ""


# ==========================================
# 🔑 자동 로그인 검증 (쿠키 기반)
# ==========================================
if not st.session_state["logged_in"]:
    cookie_phone = cookie_manager.get(cookie="russel_user_phone")
    if cookie_phone:
        df_u = pd.DataFrame(get_users_records())
        if not df_u.empty:
            for idx, row in df_u.iterrows():
                if clean_phone(str(row.get("전화번호", ""))) == clean_phone(cookie_phone):
                    st.session_state["logged_in"] = True
                    st.session_state["user_name"] = str(row.get("이름", "")).strip()
                    st.session_state["user_phone"] = clean_phone(cookie_phone)
                    st.session_state["user_role"] = str(row.get("분류", "직원")).strip()
                    st.rerun()


# ==========================================
# 1. 로그인 & 회원가입
# ==========================================
if not st.session_state["logged_in"]:
    left, right = st.columns([1, 1.3], gap="large")

    with left:
        st.markdown("""
            <div class="brand-panel">
                <h1>🏢 러셀대치학원<br>통합 관리 시스템</h1>
                <p>시설 고장 신고, 물품 구매 요청, 소모품·비품 재고를<br>
                한 곳에서 빠르고 직관적으로 관리하세요.</p>
                <div style="margin-top: 30px; font-size: 0.9rem; opacity: 0.8;">
                ✓ 시설 보수 신고 <br> ✓ 구매 요청 <br> ✓ 재고 관리
                </div>
            </div>
        """, unsafe_allow_html=True)

    with right:
        tab_login, tab_signup = st.tabs(["🔑 로그인", "📝 회원가입"])

        with tab_login:
            with st.form("login_form"):
                st.markdown("### 로그인")
                st.markdown("<p style='color:#64748b; font-size:0.9rem; margin-bottom: 20px;'>등록된 이름과 전화번호로 접속해주세요.</p>", unsafe_allow_html=True)
                login_name = st.text_input("이름", placeholder="예: 홍길동")
                login_phone = st.text_input("전화번호", type="password", placeholder="숫자만 입력 (- 없이)")
                auto_login = st.checkbox("🔑 로그인 상태 유지 (자동 로그인)", value=True)
                st.write("")
                submitted = st.form_submit_button("로그인하기", use_container_width=True)

            if submitted:
                c_name = login_name.strip()
                c_phone = clean_phone(login_phone)

                if not c_name or not c_phone:
                    st.error("이름과 전화번호를 모두 입력해 주세요.")
                else:
                    df_u = pd.DataFrame(get_users_records())
                    matched = None
                    if not df_u.empty:
                        for idx, row in df_u.iterrows():
                            if str(row.get("이름", "")).strip() == c_name and clean_phone(str(row.get("전화번호", ""))) == c_phone:
                                matched = row
                                break

                    if matched is not None:
                        st.session_state["logged_in"] = True
                        st.session_state["user_name"] = c_name
                        st.session_state["user_phone"] = c_phone
                        st.session_state["user_role"] = str(matched.get("분류", "직원")).strip()

                        if auto_login:
                            cookie_manager.set("russel_user_phone", c_phone, expires_at=datetime.now() + timedelta(days=30))
                            time.sleep(0.2)

                        st.success(f"🎉 {c_name}님 환영합니다!")
                        st.rerun()
                    else:
                        st.error("이름 또는 전화번호가 일치하지 않습니다. 처음이시라면 회원가입 탭을 이용해 주세요.")

        with tab_signup:
            st.markdown("### 신규 회원가입")
            st.markdown("<p style='color:#64748b; font-size:0.9rem; margin-bottom: 20px;'>시스템 사용을 위해 계정을 생성합니다.</p>", unsafe_allow_html=True)

            signup_role = st.selectbox("가입 구분", ["직원", "강사", "교무팀", "조교"])
            
            if signup_role == "교무팀":
                st.info("💡 **교무팀**: 시설요청 상태변경 및 재고 관리 전체 권한이 부여됩니다.")
            elif signup_role == "조교":
                st.info("💡 **조교**: 시설보수/구매요청 및 마감 재고 실사 등록 권한이 부여됩니다.")
            else:
                st.write("")

            signup_name = st.text_input("이름", key="s_name", placeholder="예: 홍길동")
            signup_phone = st.text_input("전화번호", key="s_phone", placeholder="숫자만 입력 (- 없이)")
            st.caption("전화번호는 로그인 시 비밀번호처럼 사용됩니다. 8자리 이상 입력해 주세요.")
            
            st.write("")
            if st.button("회원가입 완료", use_container_width=True, key="signup_btn"):
                c_name = signup_name.strip()
                c_phone = clean_phone(signup_phone)

                if not c_name:
                    st.error("이름을 입력해 주세요.")
                elif len(c_phone) < 8:
                    st.error("전화번호는 숫자 8자리 이상으로 입력해 주세요.")
                else:
                    now_str = get_kst_now()
                    ws_users.append_row([c_name, f"'{c_phone}", signup_role, now_str])
                    get_users_records.clear()
                    
                    cookie_manager.set("russel_user_phone", c_phone, expires_at=datetime.now() + timedelta(days=30))
                    time.sleep(0.2)
                    st.session_state["logged_in"] = True
                    st.session_state["user_name"] = c_name
                    st.session_state["user_phone"] = c_phone
                    st.session_state["user_role"] = signup_role
                    st.success("✅ 회원가입 및 로그인 완료!")
                    st.rerun()
    st.stop()

# ==========================================
# 2. 메인 화면 및 메뉴
# ==========================================
st.sidebar.markdown(f"""
    <div class="user-card">
        <div style="font-size: 0.8rem; opacity: 0.8; margin-bottom: 4px;">{get_kst_now()} (KST)</div>
        <div class="u-name">👤 {st.session_state['user_name']}</div>
        <span class="u-role">{st.session_state['user_role']}</span>
    </div>
""", unsafe_allow_html=True)

if st.sidebar.button("🚪 로그아웃", use_container_width=True):
    cookie_manager.delete("russel_user_phone")
    st.session_state["logged_in"] = False
    st.session_state["user_name"] = ""
    st.session_state["user_phone"] = ""
    st.session_state["user_role"] = ""
    time.sleep(0.2)
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown("<h4 style='color: white !important; font-size: 1rem; margin-bottom: 10px;'>메뉴 이동</h4>", unsafe_allow_html=True)

user_role = st.session_state["user_role"]
is_full_admin = (user_role == "교무팀")
is_silsa_staff = (user_role == "조교")
can_access_inventory = is_full_admin or is_silsa_staff

menu_options = ["🛠️ 시설 보수 및 구매 요청"]
if can_access_inventory:
    menu_options.append("📦 물품/비품 재고 관리")

menu = st.sidebar.radio("Navigation", menu_options, label_visibility="collapsed")

# ==========================================
# 3. 요청 등록
# ==========================================
if menu == "🛠️ 시설 보수 및 구매 요청":
    st.title("🛠️ 시설 보수 및 물품 구매 요청")
    tab1, tab2 = st.tabs(["📝 새로운 요청 등록", "📋 진행 현황 확인"])

    with tab1:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown("### 어떤 요청을 하시겠습니까?")
        req_type = st.radio("요청 유형 선택", ["🔧 시설 보수 요청", "🛒 신규 물품/비품 구매 요청"], horizontal=True, label_visibility="collapsed")
        
        st.write("")
        col_a, col_b = st.columns(2)
        with col_a:
            space_cat = st.selectbox("공간 구분", list(SPACES.keys()))
        with col_b:
            det_space = st.selectbox("세부 위치", SPACES[space_cat])

        st.markdown("---")
        
        if req_type == "🔧 시설 보수 요청":
            st.markdown("#### 고장/보수 내용 입력")
            cat = st.selectbox("보수 분류", [c for c in CATEGORY_BY_SPACE[space_cat] if c != "신규 물품 구매 요청"])
            details = st.text_area("상세 고장 내용", placeholder="예: 에어컨에서 이상한 소음이 나고 냉방이 잘 안됩니다.", height=120)
            
            st.write("")
            photo_file = st.file_uploader("📷 현장 사진 첨부 (선택사항, 8MB 이하)", type=["png", "jpg", "jpeg"])
            if photo_file is not None:
                st.image(photo_file, caption="첨부 미리보기", width=240)
                if photo_too_large(photo_file):
                    st.error(f"사진 용량이 {MAX_PHOTO_MB}MB를 초과합니다. 더 작은 파일로 첨부해 주세요.")

            st.write("")
            if st.button("보수 요청 제출하기", use_container_width=True):
                if photo_too_large(photo_file):
                    st.error(f"사진 용량이 {MAX_PHOTO_MB}MB를 초과합니다. 첨부 파일을 확인해 주세요.")
                elif details.strip():
                    with st.spinner("요청을 등록하고 있습니다..."):
                        photo_url = upload_photo_to_drive(photo_file)
                        now_str = get_kst_now()
                        base_row = [now_str, space_cat, det_space, f"[보수] {cat}", details, photo_url, "접수완료", st.session_state['user_name']]
                        row = ([generate_request_id()] + base_row) if FACILITY_HAS_ID else base_row
                        ws_facility.append_row(row)
                        get_facility_records.clear()
                    st.success("✅ 요청이 성공적으로 등록되었습니다. '진행 현황 확인' 탭에서 처리 상태를 확인하세요.")
                    st.balloons()
                else:
                    st.error("상세 내용을 입력해 주세요.")
        else:
            st.markdown("#### 구매 물품 정보 입력")
            col_i1, col_i2 = st.columns([3, 1])
            with col_i1:
                item_n = st.text_input("구매 물품명", placeholder="예: 무선 마우스")
            with col_i2:
                item_q = st.number_input("수량", min_value=1, value=1)
                
            item_r = st.text_area("구매 사유 및 목적", placeholder="예: 기존 마우스 고장으로 교체 필요", height=100)
            
            st.write("")
            photo_file = st.file_uploader("📷 참고 사진/자료 첨부 (선택사항, 8MB 이하)", type=["png", "jpg", "jpeg"])
            if photo_file is not None:
                st.image(photo_file, caption="첨부 미리보기", width=240)
                if photo_too_large(photo_file):
                    st.error(f"사진 용량이 {MAX_PHOTO_MB}MB를 초과합니다. 더 작은 파일로 첨부해 주세요.")

            st.write("")
            if st.button("구매 요청 제출하기", use_container_width=True):
                if photo_too_large(photo_file):
                    st.error(f"사진 용량이 {MAX_PHOTO_MB}MB를 초과합니다. 첨부 파일을 확인해 주세요.")
                elif item_n.strip() and item_r.strip():
                    with st.spinner("요청을 등록하고 있습니다..."):
                        photo_url = upload_photo_to_drive(photo_file)
                        now_str = get_kst_now()
                        full_d = f"[구매물품] {item_n} ({item_q}개)\n[사유] {item_r}"
                        base_row = [now_str, space_cat, det_space, "[구매요청] 물품구매", full_d, photo_url, "접수완료", st.session_state['user_name']]
                        row = ([generate_request_id()] + base_row) if FACILITY_HAS_ID else base_row
                        ws_facility.append_row(row)
                        get_facility_records.clear()
                    st.success("✅ 구매 요청이 성공적으로 등록되었습니다.")
                    st.balloons()
                else:
                    st.error("물품명과 구매 사유를 모두 입력해 주세요.")
        st.markdown('</div>', unsafe_allow_html=True)

    with tab2:
        df_f = pd.DataFrame(get_facility_records())

        if df_f.empty:
            st.info("등록된 요청 내역이 없습니다.")
        else:
            st.markdown('<div class="section-card" style="padding-bottom: 10px;">', unsafe_allow_html=True)
            f1, f2, f3 = st.columns([1, 1, 2])
            with f1:
                space_filter = st.selectbox("공간 필터", ["전체"] + list(SPACES.keys()))
            with f2:
                status_filter = st.selectbox("상태 필터", ["전체"] + STATUS_OPTIONS)
            with f3:
                keyword = st.text_input("🔍 내용/작성자 검색", placeholder="검색어를 입력하세요")

            show_mine = st.checkbox("🙋 내가 작성한 요청만 보기", value=(not is_full_admin))
            st.markdown('</div>', unsafe_allow_html=True)

            df_view = df_f.copy()
            if space_filter != "전체" and "공간구분" in df_view.columns:
                df_view = df_view[df_view["공간구분"] == space_filter]
            if status_filter != "전체" and "상태" in df_view.columns:
                df_view = df_view[df_view["상태"] == status_filter]
            if show_mine and "작성자" in df_view.columns:
                df_view = df_view[df_view["작성자"] == st.session_state["user_name"]]
            if keyword:
                mask = df_view.astype(str).apply(lambda r: r.str.contains(keyword, case=False, na=False)).any(axis=1)
                df_view = df_view[mask]

            df_view = df_view.iloc[::-1]

            m1, m2, m3 = st.columns(3)
            m1.metric("총 요청 건수", f"{len(df_f)} 건")
            m2.metric("접수완료", f"{int((df_f.get('상태') == '접수완료').sum()) if '상태' in df_f.columns else 0} 건")
            m3.metric("처리완료", f"{int((df_f.get('상태') == '완료').sum()) if '상태' in df_f.columns else 0} 건")
            st.write("")

            st.markdown(f"**검색 결과: {len(df_view)}건**")

            if is_full_admin and "상태" in df_view.columns:
                st.info("💡 **관리자 안내**: 표 안의 '상태' 셀을 클릭하여 진행상황을 변경한 뒤, 아래 저장 버튼을 누르세요.")
                edited = st.data_editor(
                    df_view,
                    use_container_width=True,
                    hide_index=True,
                    disabled=[c for c in df_view.columns if c != "상태"],
                    column_config={
                        "상태": st.column_config.SelectboxColumn("상태", options=STATUS_OPTIONS)
                    },
                    key="facility_editor"
                )
                if st.button("💾 상태 변경사항 저장하기", use_container_width=True):
                    updates = []
                    changes = 0
                    status_col_num = list(df_f.columns).index("상태") + 1
                    status_col_letter = col_letter(status_col_num)
                    for i in edited.index:
                        new_status = edited.loc[i, "상태"]
                        old_status = df_view.loc[i, "상태"]
                        if new_status != old_status:
                            row_num = None
                            if "요청ID" in edited.columns and edited.loc[i, "요청ID"]:
                                row_num = find_facility_row_by_id(edited.loc[i, "요청ID"])
                            if row_num is None:
                                row_num = i + 2
                            updates.append({"range": f"{status_col_letter}{row_num}", "values": [[new_status]]})
                            changes += 1

                    if updates:
                        with st.spinner("변경 사항을 서버에 저장 중입니다..."):
                            ws_facility.batch_update(updates)
                        get_facility_records.clear()
                        st.success(f"✅ {changes}건의 상태가 정상적으로 업데이트되었습니다.")
                        st.rerun()
                    else:
                        st.warning("변경된 내용이 없습니다.")
            else:
                if "상태" in df_view.columns:
                    df_show = df_view.drop(columns=["요청ID"], errors="ignore").copy()
                    df_show["상태"] = df_show["상태"].apply(status_badge)
                    st.markdown(
                        f'<div class="scroll-table">{df_show.to_html(escape=False, index=False)}</div>',
                        unsafe_allow_html=True
                    )
                else:
                    st.dataframe(df_view, use_container_width=True, hide_index=True)

            st.write("")
            st.download_button(
                "⬇️ 현재 목록 CSV 다운로드",
                df_view.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"시설요청현황_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )

# ==========================================
# 4. 재고 관리 
# ==========================================
elif menu == "📦 물품/비품 재고 관리":
    st.title("📦 재고 통합 관리")

    if is_full_admin:
        tab1, tab2, tab3 = st.tabs(["📝 마감 실사 등록", "📥 입·출고 내역 등록", "📊 재고 대시보드"])
    else:
        st.info("🔒 **조교 계정**은 '마감 재고 실사'만 등록 가능합니다. 입/출고 및 재고 현황 조회는 교무팀 계정을 이용해 주세요.")
        tab1 = st.container()

    def get_safe_inventory_df():
        try:
            records = get_inventory_records()
            return pd.DataFrame(records)
        except Exception:
            all_cols = ["일시", "구분", "작성자"] + ALL_SHEET_ITEMS + ["비고"]
            return pd.DataFrame(columns=all_cols)

    def get_last_silsa_values():
        df = get_safe_inventory_df()
        if df.empty or "구분" not in df.columns:
            return {}
        df_silsa = df[df["구분"] == "실사"]
        if df_silsa.empty:
            return {}
        last_row = df_silsa.iloc[-1]
        result = {}
        for item in ALL_SHEET_ITEMS:
            if item in df_silsa.columns:
                result[item] = float(pd.to_numeric(last_row.get(item, 0.0), errors="coerce") or 0.0)
        return result

    # 탭 1: 마감 재고 실사
    with tab1:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown("### 일일 마감 실사 등록")
        st.caption("※ 각 층별 소모품 수량을 입력하면 총수량이 자동으로 계산됩니다. (소수점 입력 가능)")
        now_str = get_kst_now()
        
        st.markdown(f"**작성 정보** &nbsp;|&nbsp; 🗓️ {now_str} &nbsp;|&nbsp; 👤 {st.session_state['user_name']}")
        st.write("")
        
        last_vals = get_last_silsa_values()

        consumable_rows = []
        for item in CONSUMABLES:
            def safe_float(val):
                try:
                    if pd.isna(val) or val is None or str(val).strip() == "":
                        return 0.0
                    return float(val)
                except (ValueError, TypeError):
                    return 0.0

            v2 = safe_float(last_vals.get(f"{item} (2층)"))
            v6 = safe_float(last_vals.get(f"{item} (6층)"))
            v7 = safe_float(last_vals.get(f"{item} (7층)"))
            
            consumable_rows.append({
                "소모품 명": item,
                "2층 수량": v2,
                "6층 수량": v6,
                "7층 수량": v7,
                "총 수량 (자동합산)": v2 + v6 + v7
            })

        df_c_input = pd.DataFrame(consumable_rows)

        st.markdown("#### 🧻 층별 소모품 재고")
        edited_c = st.data_editor(
            df_c_input,
            use_container_width=True,
            hide_index=True,
            disabled=["소모품 명", "총 수량 (자동합산)"],
            column_config={
                "2층 수량": st.column_config.NumberColumn("2층", min_value=0.0, step=0.1, default=0.0, format="%.2f"),
                "6층 수량": st.column_config.NumberColumn("6층", min_value=0.0, step=0.1, default=0.0, format="%.2f"),
                "7층 수량": st.column_config.NumberColumn("7층", min_value=0.0, step=0.1, default=0.0, format="%.2f"),
                "총 수량 (자동합산)": st.column_config.NumberColumn("총 수량 (합계)", format="%.2f")
            },
            key="c_silsa_editor"
        )

        edited_c["2층 수량"] = edited_c["2층 수량"].fillna(0.0)
        edited_c["6층 수량"] = edited_c["6층 수량"].fillna(0.0)
        edited_c["7층 수량"] = edited_c["7층 수량"].fillna(0.0)
        edited_c["총 수량 (자동합산)"] = edited_c["2층 수량"] + edited_c["6층 수량"] + edited_c["7층 수량"]

        st.markdown("---")
        st.markdown("#### 💻 공용 비품 및 기기 재고")

        equipment_rows = []
        for item in EQUIPMENT:
            equipment_rows.append({
                "비품 품목명": item,
                "현재 수량": float(last_vals.get(item, 0.0))
            })

        df_e_input = pd.DataFrame(equipment_rows)

        edited_e = st.data_editor(
            df_e_input,
            use_container_width=True,
            hide_index=True,
            disabled=["비품 품목명"],
            column_config={
                "현재 수량": st.column_config.NumberColumn("실사 확인 수량", min_value=0.0, step=0.1, format="%.2f")
            },
            key="e_silsa_editor"
        )

        st.write("")
        if st.button("📝 마감 실사 데이터 저장하기", use_container_width=True):
            sheet_values = {}

            for _, r in edited_c.iterrows():
                item = r["소모품 명"]
                sheet_values[f"{item} (2층)"] = float(r["2층 수량"])
                sheet_values[f"{item} (6층)"] = float(r["6층 수량"])
                sheet_values[f"{item} (7층)"] = float(r["7층 수량"])

            for _, r in edited_e.iterrows():
                sheet_values[r["비품 품목명"]] = float(r["현재 수량"])

            row = [now_str, "실사", st.session_state['user_name']]
            for item in ALL_SHEET_ITEMS:
                row.append(sheet_values.get(item, 0.0))
            row.append("정기 마감 실사")

            with st.spinner("데이터를 서버에 동기화 중입니다..."):
                ws_inventory.append_row(row)
                get_inventory_records.clear()
            st.success("✅ 오늘자 마감 실사 데이터가 정상적으로 저장되었습니다!")
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    # 탭 2: 입고 및 출고 등록
    if is_full_admin:
        with tab2:
            st.markdown('<div class="section-card">', unsafe_allow_html=True)
            st.markdown("### 입고 및 출고(사용) 단건 등록")
            st.caption("※ 새로운 물품이 들어오거나 사용된 경우 수량 변동 내역만 간편하게 등록합니다.")

            inout_type = st.radio("작업 구분", ["📥 입고 (재고 추가)", "📤 출고 (재고 차감/사용)"], horizontal=True)
            
            st.write("")
            col1, col2 = st.columns([2, 1])
            with col1:
                target_item = st.selectbox("물품 선택 (층 구분 포함)", ALL_SHEET_ITEMS)
            with col2:
                qty = st.number_input("변동 수량", min_value=0.01, value=1.0, step=0.1, format="%.2f")
                
            memo = st.text_input("비고/사유 (선택)", placeholder="예: 문구점 대량 구매, 2층 자습관 형광등 교체 등")

            st.write("")
            if st.button("내역 등록하기", use_container_width=True):
                now_str = get_kst_now()
                is_in = "입고" in inout_type
                action_label = "입고" if is_in else "출고"
                record_qty = float(qty) if is_in else -float(qty)

                row_data = [now_str, action_label, st.session_state['user_name']]
                for item in ALL_SHEET_ITEMS:
                    row_data.append(record_qty if item == target_item else 0.0)
                row_data.append(memo)

                with st.spinner("내역을 기록하고 있습니다..."):
                    ws_inventory.append_row(row_data)
                    get_inventory_records.clear()
                st.success(f"🎉 [{target_item}] {qty}개 {action_label} 처리가 완료되었습니다!")
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

    # 탭 3: 현황 및 누적 계산
    if is_full_admin:
        with tab3:
            df_i = get_safe_inventory_df()

            if df_i.empty:
                st.info("아직 등록된 재고 데이터가 없습니다.")
            else:
                df_silsa = df_i[df_i["구분"] == "실사"]

                if not df_silsa.empty:
                    last_silsa_idx = df_silsa.index[-1]
                    last_silsa_date = df_i.loc[last_silsa_idx, "일시"]
                    
                    st.markdown("### 📊 실시간 재고 현황")
                    st.caption(f"💡 가장 최근 실사일({last_silsa_date})을 기준으로 이후의 입/출고 내역이 자동 계산된 현재 수량입니다.")

                    df_calc = df_i.loc[last_silsa_idx:].copy()

                    current_stock = {}
                    for item in ALL_SHEET_ITEMS:
                        if item in df_calc.columns:
                            current_stock[item] = float(pd.to_numeric(df_calc[item], errors='coerce').fillna(0.0).sum())
                        else:
                            current_stock[item] = 0.0

                    consumable_totals = {}
                    for item in CONSUMABLES:
                        total_q = (current_stock.get(f"{item} (2층)", 0.0) +
                                   current_stock.get(f"{item} (6층)", 0.0) +
                                   current_stock.get(f"{item} (7층)", 0.0))
                        consumable_totals[item] = total_q

                    low_stock_items = [i for i, q in consumable_totals.items() if q <= get_threshold(i)]
                    if low_stock_items:
                        st.markdown(
                            "⚠️ **재고 부족 알림** (기준치 이하 품목) <br>" + "".join(
                                [f'<span class="low-stock-pill">{i} ({consumable_totals[i]:.2f})</span>' for i in low_stock_items]
                            ),
                            unsafe_allow_html=True
                        )
                    else:
                        st.success("✅ 현재 기준치 이하로 부족한 품목이 없습니다.")

                    st.write("")
                    col1, col2 = st.columns(2, gap="large")
                    with col1:
                        st.markdown("#### 📄 소모품 총 재고 (층별 합계)")
                        df_c_stock = pd.DataFrame([{"품목명": k, "현재 보유량": round(v, 2)} for k, v in consumable_totals.items()])
                        st.dataframe(df_c_stock, use_container_width=True, hide_index=True)

                    with col2:
                        st.markdown("#### 💻 비품/기기 현재 재고")
                        df_e_stock = pd.DataFrame([{"품목명": k, "현재 보유량": round(v, 2)} for k, v in current_stock.items() if k in EQUIPMENT])
                        st.dataframe(df_e_stock, use_container_width=True, hide_index=True)
                else:
                    st.warning("⚠️ 등록된 '마감 실사' 데이터의 기준점이 없습니다. 먼저 [마감 실사 등록] 탭에서 실사 데이터를 입력해 주세요.")

                st.markdown("---")
                st.markdown("### 📋 물품 입출고 및 실사 이력")

                h1, h2 = st.columns([1, 2])
                with h1:
                    type_filter = st.selectbox("조회 구분", ["전체보기", "실사", "입고", "출고"])
                with h2:
                    item_keyword = st.text_input("🔍 이력 검색", placeholder="품목명, 작성자, 비고 등을 검색하세요")

                df_hist = df_i.copy()
                if type_filter != "전체보기":
                    df_hist = df_hist[df_hist["구분"] == type_filter]
                if item_keyword:
                    mask = df_hist.astype(str).apply(lambda r: r.str.contains(item_keyword, case=False, na=False)).any(axis=1)
                    df_hist = df_hist[mask]

                df_hist = df_hist.iloc[::-1]

                st.write("")
                st.dataframe(df_hist, use_container_width=True, hide_index=True)
                
                st.write("")
                st.download_button(
                    "⬇️ 조회된 이력 CSV 다운로드",
                    df_hist.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"재고변동이력_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv"
                )
import streamlit as st
import pandas as pd
import re
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 0. 페이지 기본 및 구글 시트 연동 설정
# ==========================================
st.set_page_config(
    page_title="러셀대치학원 시설보수 및 재고관리 시스템", 
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
    <style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
    html, body, [class*="css"] { font-family: 'Pretendard', sans-serif; }
    .stApp { background-color: #f8f9fa; }
    .stButton>button { border-radius: 8px; font-weight: 600; background-color: #1e3a8a; color: #ffffff; border: none; }
    .stButton>button:hover { background-color: #1d4ed8; color: #ffffff; }
    [data-testid="stMetricValue"] { font-size: 1.5rem !important; font-weight: 700; color: #1e3a8a; }
    </style>
""", unsafe_allow_html=True)

# 구글 시트 API 연결 함수
@st.cache_resource
def get_gspread_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    # Secrets 정보 불러오기
    creds_dict = dict(st.secrets["gcp_service_account"])
    
    # private_key가 문자열일 경우 이중 역슬래시 및 양끝 따옴표 예외 처리
    if "private_key" in creds_dict:
        pk = str(creds_dict["private_key"])
        pk = pk.replace("\\n", "\n")  # \\n 문자열을 실제 줄바꿈으로 변환
        creds_dict["private_key"] = pk
        
    credentials = Credentials.from_service_account_info(
        creds_dict,
        scopes=scopes
    )
    return gspread.authorize(credentials)

try:
    gc = get_gspread_client()
    # 구글 시트 이름 지정
    sh = gc.open("러셀대치_통합DB")
    ws_users = sh.worksheet("users")
    ws_facility = sh.worksheet("facility")
    ws_inventory = sh.worksheet("inventory")
except Exception as e:
    st.error(f"⚠️ 구글 시트 연동에 실패했습니다. Secrets 설정을 확인해 주세요: {e}")
    st.stop()

def clean_phone(phone_str):
    if pd.isna(phone_str): return ""
    return re.sub(r"[^0-9]", "", str(phone_str))

CONSUMABLES = [
    "A4용지", "A3용지", "B4용지", "미색A4용지", "미색A3용지",
    "분필(백)", "분필(청)", "분필(빨)", "분필(노)",
    "점보롤", "핸드타월", "물티슈", "각티슈", "물비누",
    "종이컵", "세모금컵", "생수", "AAA건전지", "AA건전지", "마이크 커버"
]
EQUIPMENT = [
    "노트북", "출결리더기", "보조배터리", "캠코더", 
    "삼각대 및 플레이트", "SD카드", "빔포인터", "빔리모콘", "에어컨리모콘"
]
ALL_ITEMS = CONSUMABLES + EQUIPMENT

SPACES = {
    "강의실": ["대형강의실", "201호", "202호", "203호", "204호", "601호", "602호", "701호", "702호", "703호", "704호"],
    "자습관": ["3-1관", "3-2관", "3-3관", "3-4관", "3-5관", "4-1관", "4-2관", "4-3관", "4-4관", "4-5관", "5-1관", "5-2관", "5-3관", "6-1관", "6-2관", "7-1관"],
    "화장실": ["2층 남자화장실", "2층 여자화장실", "3층 남자화장실", "3층 여자화장실", "5층 남자화장실", "5층 여자화장실", "6층 남자화장실", "6층 여자화장실", "7층 남자화장실", "7층 여자화장실"],
    "기타공간": ["기타공간 (복도/엘리베이터/로비/사무실 등)"]
}

CATEGORY_BY_SPACE = {
    "강의실": ["빔프로젝터/음향", "냉난방/환기", "조명/전기", "책상/의자/칠판", "문/창문/열쇠", "신규 물품 구매 요청", "기타 시설"],
    "자습관": ["자습관 책상/시디즈 의자", "스탠드/전기/콘센트", "냉난방/공기청정기", "공용 스탠딩 책상", "문/창문/소음 문제", "신규 물품 구매 요청", "기타 시설"],
    "화장실": ["대변기 (막힘/고장/부속)", "소변기 (막힘/자동센서/누수)", "세면대/수도꼭지", "휴지걸이/비누디스펜서", "조명/환풍기", "바닥 배수구/타일", "신규 물품 구매 요청", "기타 시설"],
    "기타공간": ["엘리베이터", "복도/계단/난간", "정수기/음료대", "자동문/출입문", "조명/전기", "신규 물품 구매 요청", "기타 시설"]
}

# 세션 초기화
if "logged_in" not in st.session_state: st.session_state["logged_in"] = False
if "user_name" not in st.session_state: st.session_state["user_name"] = ""
if "user_phone" not in st.session_state: st.session_state["user_phone"] = ""
if "user_role" not in st.session_state: st.session_state["user_role"] = ""

# ==========================================
# 1. 로그인 & 회원가입
# ==========================================
if not st.session_state["logged_in"]:
    st.markdown("<h2 style='text-align: center; color: #1e3a8a;'>🏢 러셀대치학원 시설보수 및 재고관리 시스템</h2>", unsafe_allow_html=True)
    tab_login, tab_signup = st.tabs(["🔑 로그인", "📝 회원가입"])

    with tab_login:
        st.subheader("로그인")
        login_name = st.text_input("이름", key="l_name")
        login_phone = st.text_input("전화번호", type="password", key="l_phone")
        
        if st.button("로그인하기", use_container_width=True):
            c_name = login_name.strip()
            c_phone = clean_phone(login_phone)
            
            users_data = ws_users.get_all_records()
            df_u = pd.DataFrame(users_data)
            
            matched = None
            if not df_u.empty:
                for idx, row in df_u.iterrows():
                    if str(row.get("이름","")).strip() == c_name and clean_phone(row.get("전화번호","")) == c_phone:
                        matched = row
                        break
            
            if matched is not None:
                st.session_state["logged_in"] = True
                st.session_state["user_name"] = c_name
                st.session_state["user_phone"] = c_phone
                st.session_state["user_role"] = str(matched.get("분류",""))
                st.success(f"🎉 {c_name}님 환영합니다!")
                st.rerun()
            else:
                st.error("이름 또는 전화번호가 일치하지 않습니다.")

    with tab_signup:
        st.subheader("신규 회원가입")
        signup_role = st.selectbox("구분", ["교무팀", "조교", "직원", "강사"])
        signup_name = st.text_input("이름", key="s_name")
        signup_phone = st.text_input("전화번호", key="s_phone")

        if st.button("회원가입 완료", use_container_width=True):
            c_name = signup_name.strip()
            c_phone = clean_phone(signup_phone)
            if c_name and len(c_phone) >= 8:
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                ws_users.append_row([c_name, c_phone, signup_role, now_str])
                st.success("✅ 회원가입이 완료되었습니다! 구글 시트에 안전히 저장되었습니다.")
            else:
                st.error("올바른 정보를 입력해 주세요.")
    st.stop()

# ==========================================
# 2. 메인 화면 및 메뉴
# ==========================================
st.sidebar.markdown("### 🏢 러셀대치학원 시스템")
st.sidebar.info(f"👤 **{st.session_state['user_name']}** ({st.session_state['user_role']})")

if st.sidebar.button("🚪 로그아웃", use_container_width=True):
    st.session_state["logged_in"] = False
    st.rerun()

user_role = st.session_state["user_role"]
menu_options = ["🛠️ 시설 보수 및 물품 구매 요청", "📦 물품/비품 재고 관리"] if user_role in ["교무팀", "조교"] else ["🛠️ 시설 보수 및 물품 구매 요청"]
menu = st.sidebar.radio("메뉴 이동", menu_options)

# ==========================================
# 3. 요청 등록 및 시트 저장
# ==========================================
if menu == "🛠️ 시설 보수 및 물품 구매 요청":
    st.title("🛠️ 시설 보수 및 물품 구매 요청")
    tab1, tab2 = st.tabs(["📝 요청 등록", "📋 현황 확인"])

    with tab1:
        req_type = st.radio("요청 유형", ["🔧 시설 보수 요청", "🛒 신규 물품/비품 구매 요청"], horizontal=True)
        space_cat = st.selectbox("공간 구분", list(SPACES.keys()))
        det_space = st.selectbox("세부 위치", SPACES[space_cat])

        if req_type == "🔧 시설 보수 요청":
            cat = st.selectbox("보수 분류", [c for c in CATEGORY_BY_SPACE[space_cat] if c != "신규 물품 구매 요청"])
            details = st.text_area("상세 내용")
            if st.button("제출하기", use_container_width=True):
                if details.strip():
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                    ws_facility.append_row([now_str, space_cat, det_space, f"[보수] {cat}", details, "", "접수완료", st.session_state['user_name']])
                    st.success("✅ 구글 시트에 영구 저장되었습니다.")
                else:
                    st.error("상세 내용을 입력해 주세요.")
        else:
            item_n = st.text_input("구매 물품명")
            item_q = st.number_input("수량", min_value=1, value=1)
            item_r = st.text_area("구매 사유")
            if st.button("구매 요청 제출", use_container_width=True):
                if item_n.strip() and item_r.strip():
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                    full_d = f"[구매물품] {item_n} ({item_q}개)\n[사유] {item_r}"
                    ws_facility.append_row([now_str, space_cat, det_space, "[구매요청] 물품구매", full_d, "", "접수완료", st.session_state['user_name']])
                    st.success("✅ 구글 시트에 영구 저장되었습니다.")

    with tab2:
        records = ws_facility.get_all_records()
        df_f = pd.DataFrame(records)
        st.dataframe(df_f, use_container_width=True)

# ==========================================
# 4. 재고 관리 및 시트 저장
# ==========================================
elif menu == "📦 물품/비품 재고 관리":
    st.title("📦 재고 관리 System")
    tab1, tab2 = st.tabs(["📝 마감 재고 등록", "📊 현황 조회"])

    with tab1:
        with st.form("inv_form"):
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            st.write(f"등록일시: {now_str}")
            
            c_vals = {item: st.number_input(f"{item} (BOX)", min_value=0, value=0) for item in CONSUMABLES}
            e_vals = {item: st.number_input(f"{item} (개)", min_value=0, value=0) for item in EQUIPMENT}

            if st.form_submit_button("마감 재고 제출"):
                all_v = {**c_vals, **e_vals}
                row = [now_str, st.session_state['user_name']] + [all_v[i] for i in ALL_ITEMS]
                ws_inventory.append_row(row)
                st.success("✅ 구글 시트에 재고 기록이 반영되었습니다.")

    with tab2:
        df_i = pd.DataFrame(ws_inventory.get_all_records())
        st.dataframe(df_i, use_container_width=True)
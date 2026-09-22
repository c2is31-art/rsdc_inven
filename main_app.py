import streamlit as st
import pandas as pd
import os
import re
from datetime import datetime

# ==========================================
# 0. 페이지 기본 및 CSS 스타일링 설정 (모바일/태블릿 반응형)
# ==========================================
st.set_page_config(
    page_title="러셀대치학원 시설보수 및 재고관리 시스템", 
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS (Pretendard 폰트, 카드형 UI, 모바일 반응형)
st.markdown("""
    <style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
    
    html, body, [class*="css"] {
        font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, Roboto, sans-serif;
    }
    
    .stApp {
        background-color: #f8f9fa;
    }
    
    .stButton>button {
        border-radius: 8px;
        font-weight: 600;
        background-color: #1e3a8a;
        color: #ffffff;
        border: none;
        padding: 0.5rem 1rem;
        transition: all 0.2s;
    }
    .stButton>button:hover {
        background-color: #1d4ed8;
        color: #ffffff;
    }
    
    [data-testid="stMetricValue"] {
        font-size: 1.5rem !important;
        font-weight: 700;
        color: #1e3a8a;
    }
    
    @media (max-width: 768px) {
        .block-container {
            padding-top: 1rem;
            padding-left: 0.8rem;
            padding-right: 0.8rem;
        }
    }
    </style>
""", unsafe_allow_html=True)

# 파일 및 폴더 경로 설정
FACILITY_FILE = "facility_requests.csv"
INVENTORY_FILE = "inventory_data.csv"
USER_FILE = "users.csv"
UPLOAD_DIR = "uploads"

if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

def clean_phone(phone_str):
    if pd.isna(phone_str):
        return ""
    return re.sub(r"[^0-9]", "", str(phone_str))

# CSV 파일 초기화
if not os.path.exists(USER_FILE):
    pd.DataFrame(columns=["이름", "전화번호", "분류", "가입일시"]).to_csv(USER_FILE, index=False, encoding="utf-8-sig")

if not os.path.exists(FACILITY_FILE):
    pd.DataFrame(columns=["접수시간", "구분", "세부위치", "보수분류", "상세내용", "사진파일명", "처리상태", "요청자"]).to_csv(FACILITY_FILE, index=False, encoding="utf-8-sig")

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

KEYWORD_MAP = {
    "미색A4용지": ["미색 A4", "미색a4", "미색복사지 A4"],
    "미색A3용지": ["미색 A3", "미색a3", "미색복사지 A3"],
    "A4용지": ["A4", "a4", "복사지 A4", "밀크 A4", "탐사 A4"],
    "A3용지": ["A3", "a3", "복사지 A3", "밀크 A3"],
    "B4용지": ["B4", "b4", "복사지 B4"],
    "분필(백)": ["백색 분필", "흰색 분필", "흰색분필", "백색분필"],
    "분필(청)": ["청색 분필", "파란 분필", "파란색 분필", "청색분필"],
    "분필(빨)": ["적색 분필", "빨간 분필", "빨간색 분필", "적색분필"],
    "분필(노)": ["황색 분필", "노란 분필", "노랑 분필", "노란색 분필"],
    "점보롤": ["점보롤", "화장지 점보"],
    "핸드타월": ["핸드타올", "핸드타월", "손닦는 휴지"],
    "물티슈": ["물티슈", "웨트티슈"],
    "각티슈": ["각티슈", "곽티슈", "미용티슈"],
    "물비누": ["물비누", "핸드워시", "아이깨끗해"],
    "종이컵": ["종이컵", "자판기 컵"],
    "세모금컵": ["세모금", "삼각종이컵", "세모금 컵"],
    "생수": ["생수", "삼다수", "아이시스", "평창수", "탐사수"],
    "AAA건전지": ["AAA 건전지", "AAA건전지", "AAA 알카라인"],
    "AA건전지": ["AA 건전지", "AA건전지", "AA 알카라인"],
    "마이크 커버": ["마이크 커버", "마이크 덮개", "위생 마이크"],
    "노트북": ["노트북", "맥북", "그램"],
    "출결리더기": ["출결", "리더기", "지문인식"],
    "보조배터리": ["보조배터리", "보조 배터리"],
    "캠코더": ["캠코더", "비디오카메라"],
    "삼각대 및 플레이트": ["삼각대", "플레이트"],
    "SD카드": ["SD카드", "SD 카드리더기", "샌디스크 SD"],
    "빔포인터": ["포인터", "레이저포인터", "프리젠터"],
    "빔리모콘": ["빔프로젝터 리모컨", "빔 리모컨", "프로젝터 리모콘"],
    "에어컨리모콘": ["에어컨 리모컨", "에어컨 만능리모컨"]
}

if not os.path.exists(INVENTORY_FILE):
    pd.DataFrame(columns=["등록일시", "작성자"] + ALL_ITEMS).to_csv(INVENTORY_FILE, index=False, encoding="utf-8-sig")

# 공간 구분 정의
SPACES = {
    "강의실": ["대형강의실", "201호", "202호", "203호", "204호", "601호", "602호", "701호", "702호", "703호", "704호"],
    "자습관": ["3-1관", "3-2관", "3-3관", "3-4관", "3-5관", "4-1관", "4-2관", "4-3관", "4-4관", "4-5관", "5-1관", "5-2관", "5-3관", "6-1관", "6-2관", "7-1관"],
    "화장실": ["2층 남자화장실", "2층 여자화장실", "3층 남자화장실", "3층 여자화장실", "5층 남자화장실", "5층 여자화장실", "6층 남자화장실", "6층 여자화장실", "7층 남자화장실", "7층 여자화장실"],
    "기타공간": ["기타공간 (복도/엘리베이터/로비/사무실 등)"]
}

# 장소별 보수 및 구매 분류
CATEGORY_BY_SPACE = {
    "강의실": ["빔프로젝터/음향", "냉난방/환기", "조명/전기", "책상/의자/칠판", "문/창문/열쇠", "신규 물품 구매 요청", "기타 시설"],
    "자습관": ["자습관 책상/시디즈 의자", "스탠드/전기/콘센트", "냉난방/공기청정기", "공용 스탠딩 책상", "문/창문/소음 문제", "신규 물품 구매 요청", "기타 시설"],
    "화장실": ["대변기 (막힘/고장/부속)", "소변기 (막힘/자동센서/누수)", "세면대/수도꼭지", "휴지걸이/비누디스펜서", "조명/환풍기", "바닥 배수구/타일", "신규 물품 구매 요청", "기타 시설"],
    "기타공간": ["엘리베이터", "복도/계단/난간", "정수기/음료대", "자동문/출입문", "조명/전기", "신규 물품 구매 요청", "기타 시설"]
}

# 세션 초기화
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
if "user_name" not in st.session_state:
    st.session_state["user_name"] = ""
if "user_phone" not in st.session_state:
    st.session_state["user_phone"] = ""
if "user_role" not in st.session_state:
    st.session_state["user_role"] = ""

# ==========================================
# 1. 로그인 & 회원가입 모듈
# ==========================================
if not st.session_state["logged_in"]:
    st.markdown("<h2 style='text-align: center; color: #1e3a8a;'>🏢 러셀대치학원 시설보수 및 재고관리 시스템</h2>", unsafe_allow_html=True)
    st.caption("<p style='text-align: center;'>학원 시설 및 재고 관리를 위해 로그인해 주세요.</p>", unsafe_allow_html=True)

    tab_login, tab_signup, tab_debug = st.tabs(["🔑 로그인", "📝 회원가입", "🔍 등록 회원 확인"])

    with tab_login:
        st.subheader("로그인")
        login_name = st.text_input("이름", placeholder="예: 송재룡", key="login_name_input")
        login_phone = st.text_input("전화번호", type="password", placeholder="숫자만 입력 (예: 01057906453)", key="login_phone_input")
        
        if st.button("로그인하기", use_container_width=True):
            clean_input_name = login_name.strip()
            clean_input_phone = clean_phone(login_phone)
            
            if not clean_input_name or not clean_input_phone:
                st.error("이름과 전화번호를 모두 입력해 주세요.")
            else:
                if os.path.exists(USER_FILE):
                    df_users = pd.read_csv(USER_FILE, dtype=str, encoding="utf-8-sig")
                    matched_user = None
                    for idx, row in df_users.iterrows():
                        if str(row["이름"]).strip() == clean_input_name and clean_phone(row["전화번호"]) == clean_input_phone:
                            matched_user = row
                            break
                    
                    if matched_user is not None:
                        st.session_state["logged_in"] = True
                        st.session_state["user_name"] = str(matched_user["이름"]).strip()
                        st.session_state["user_phone"] = clean_phone(matched_user["전화번호"])
                        st.session_state["user_role"] = str(matched_user["분류"]).strip()
                        st.success(f"🎉 {matched_user['이름']}님 환영합니다!")
                        st.rerun()
                    else:
                        st.error("이름 또는 전화번호가 일치하지 않습니다.")
                else:
                    st.error("등록된 회원 데이터가 없습니다.")

    with tab_signup:
        st.subheader("신규 회원가입")
        signup_role = st.selectbox("구분 (직분 선택)", ["교무팀", "조교", "직원", "강사"])
        signup_name = st.text_input("이름 입력", placeholder="예: 송재룡", key="signup_name_input")
        signup_phone = st.text_input("전화번호 입력", placeholder="예: 01057906453", key="signup_phone_input")

        if st.button("회원가입 완료", use_container_width=True):
            clean_input_name = signup_name.strip()
            clean_input_phone = clean_phone(signup_phone)
            
            if not clean_input_name:
                st.error("이름을 입력해 주세요.")
            elif not clean_input_phone or len(clean_input_phone) < 8:
                st.error("올바른 전화번호를 입력해 주세요.")
            else:
                df_users = pd.read_csv(USER_FILE, dtype=str, encoding="utf-8-sig") if os.path.exists(USER_FILE) else pd.DataFrame(columns=["이름", "전화번호", "분류", "가입일시"])
                is_dup = any(str(row["이름"]).strip() == clean_input_name and clean_phone(row["전화번호"]) == clean_input_phone for _, row in df_users.iterrows())
                
                if is_dup:
                    st.warning("이미 가입된 회원 정보입니다.")
                else:
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                    new_user = pd.DataFrame([[clean_input_name, clean_input_phone, signup_role, now_str]], columns=["이름", "전화번호", "분류", "가입일시"])
                    pd.concat([df_users, new_user], ignore_index=True).to_csv(USER_FILE, index=False, encoding="utf-8-sig")
                    st.success("✅ 회원가입 완료! 로그인 탭에서 로그인해 주세요.")

    with tab_debug:
        if os.path.exists(USER_FILE):
            st.dataframe(pd.read_csv(USER_FILE, dtype=str, encoding="utf-8-sig")[["이름", "전화번호", "분류", "가입일시"]], use_container_width=True)

    st.stop()

# ==========================================
# 2. 사이드바 및 권한별 메뉴 구성
# ==========================================
st.sidebar.markdown(f"### 🏢 러셀대치학원 시스템")
st.sidebar.info(f"👤 **{st.session_state['user_name']}** 님\n\n📌 **권한:** `{st.session_state['user_role']}`")

if st.sidebar.button("🚪 로그아웃", use_container_width=True):
    st.session_state["logged_in"] = False
    st.session_state["user_name"] = ""
    st.session_state["user_phone"] = ""
    st.session_state["user_role"] = ""
    st.rerun()

st.sidebar.divider()

user_role = st.session_state["user_role"]

if user_role in ["교무팀", "조교"]:
    menu_options = ["🛠️ 시설 보수 및 물품 구매 요청", "📦 물품/비품 재고 관리"]
else: # 직원, 강사
    menu_options = ["🛠️ 시설 보수 및 물품 구매 요청"]

menu = st.sidebar.radio("메뉴 이동", menu_options)

# ==========================================
# 3. [메뉴 1] 시설 보수 및 물품 구매 요청
# ==========================================
if menu == "🛠️ 시설 보수 및 물품 구매 요청":
    st.title("🛠️ 시설 보수 및 물품 구매 요청")
    tab1, tab2 = st.tabs(["📝 보수/구매 요청 등록", "📋 접수 및 처리 현황"])

    with tab1:
        st.subheader("📍 요청 유형 및 상세 내용 입력")
        
        request_type = st.radio("요청 유형 선택", ["🔧 시설 보수 요청", "🛒 신규 물품/비품 구매 요청"], horizontal=True)
        
        space_category = st.selectbox("1. 공간 구분 선택", list(SPACES.keys()))
        detailed_space = st.selectbox("2. 세부 위치 선택", SPACES[space_category])
        
        if request_type == "🔧 시설 보수 요청":
            category_options = CATEGORY_BY_SPACE.get(space_category, ["기타 시설"])
            category = st.selectbox("3. 보수 분류 선택", [c for c in category_options if c != "신규 물품 구매 요청"])
            details = st.text_area("4. 상세 보수 요청 내용", placeholder="현장 상황을 상세히 기술해 주세요. (예: 201호 빔프로젝터 화면 잔상 발생)")
            uploaded_file = st.file_uploader("5. 현장 사진 첨부 (선택)", type=["png", "jpg", "jpeg"])
            
            if st.button("🚨 보수 요청 제출", use_container_width=True):
                if not details.strip():
                    st.error("상세 내용을 입력해 주세요.")
                else:
                    now_dt = datetime.now()
                    saved_filename = ""
                    if uploaded_file is not None:
                        file_ext = uploaded_file.name.split(".")[-1]
                        saved_filename = f"photo_{now_dt.strftime('%Y%m%d_%H%M%S')}.{file_ext}"
                        with open(os.path.join(UPLOAD_DIR, saved_filename), "wb") as f:
                            f.write(uploaded_file.getbuffer())

                    new_data = pd.DataFrame([[now_dt.strftime("%Y-%m-%d %H:%M"), space_category, detailed_space, f"[보수] {category}", details, saved_filename, "접수완료", st.session_state['user_name']]], columns=["접수시간", "구분", "세부위치", "보수분류", "상세내용", "사진파일명", "처리상태", "요청자"])
                    pd.concat([pd.read_csv(FACILITY_FILE, encoding="utf-8-sig"), new_data], ignore_index=True).to_csv(FACILITY_FILE, index=False, encoding="utf-8-sig")
                    st.success("✅ 보수 요청이 정상 접수되었습니다.")
                    st.balloons()
                    
        else: # 🛒 신규 물품/비품 구매 요청
            item_name = st.text_input("3. 구매 희망 물품명", placeholder="예: 무선 마이크, HDMI 케이블 5m 등")
            item_qty = st.number_input("4. 필요 수량", min_value=1, value=1, step=1)
            item_url = st.text_input("5. 참고 링크 또는 쿠팡 URL (선택)", placeholder="https://...")
            item_reason = st.text_area("6. 구매 사유 및 세부 스펙", placeholder="예: 202호 마이크 고장으로 인한 대체품 필요")
            uploaded_file = st.file_uploader("7. 참고 사진 첨부 (선택)", type=["png", "jpg", "jpeg"])
            
            if st.button("🛒 물품 구매 요청 제출", use_container_width=True):
                if not item_name.strip() or not item_reason.strip():
                    st.error("물품명과 구매 사유를 입력해 주세요.")
                else:
                    now_dt = datetime.now()
                    saved_filename = ""
                    if uploaded_file is not None:
                        file_ext = uploaded_file.name.split(".")[-1]
                        saved_filename = f"photo_{now_dt.strftime('%Y%m%d_%H%M%S')}.{file_ext}"
                        with open(os.path.join(UPLOAD_DIR, saved_filename), "wb") as f:
                            f.write(uploaded_file.getbuffer())

                    full_details = f"[구매물품] {item_name} ({item_qty}개)\n[구매사유] {item_reason}"
                    if item_url.strip():
                        full_details += f"\n[참고링크] {item_url}"

                    new_data = pd.DataFrame([[now_dt.strftime("%Y-%m-%d %H:%M"), space_category, detailed_space, "[구매요청] 물품구매", full_details, saved_filename, "접수완료", st.session_state['user_name']]], columns=["접수시간", "구분", "세부위치", "보수분류", "상세내용", "사진파일명", "처리상태", "요청자"])
                    pd.concat([pd.read_csv(FACILITY_FILE, encoding="utf-8-sig"), new_data], ignore_index=True).to_csv(FACILITY_FILE, index=False, encoding="utf-8-sig")
                    st.success("✅ 물품 구매 요청이 정상 접수되었습니다.")
                    st.balloons()

    with tab2:
        df_facility = pd.read_csv(FACILITY_FILE, encoding="utf-8-sig")
        if len(df_facility) == 0:
            st.info("등록된 요청이 없습니다.")
        else:
            filter_cat = st.selectbox("공간별 필터", ["전체보기"] + list(SPACES.keys()))
            display_df = df_facility[df_facility["구분"] == filter_cat] if filter_cat != "전체보기" else df_facility
            st.dataframe(display_df, use_container_width=True)

            if user_role == "교무팀":
                st.divider()
                st.subheader("🔧 [교무팀 전용] 처리 상태 업데이트")
                col1, col2 = st.columns(2)
                with col1:
                    status_idx = st.number_input("행 번호 (Index)", min_value=0, max_value=len(df_facility)-1, step=1)
                with col2:
                    new_status = st.selectbox("변경 상태", ["접수완료", "진행중(업체/구매예정)", "보수/구매완료", "보류/반려"])
                
                if st.button("상태 저장"):
                    df_facility.loc[status_idx, "처리상태"] = new_status
                    df_facility.to_csv(FACILITY_FILE, index=False, encoding="utf-8-sig")
                    st.success("상태가 성공적으로 업데이트되었습니다.")
                    st.rerun()

# ==========================================
# 4. [메뉴 2] 물품/비품 재고 관리
# ==========================================
elif menu == "📦 물품/비품 재고 관리":
    st.title("📦 재고 관리 System")
    tab1, tab2 = st.tabs(["📝 마감 재고 등록", "📊 현황 및 입고"])

    with tab1:
        st.subheader("📋 일일 마감 재고 입력")
        with st.form("inventory_form"):
            today_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            st.text_input("일시", value=today_str, disabled=True)
            
            st.markdown("#### 🧻 소모품 (BOX)")
            c_inputs = {}
            c_cols = st.columns(2 if st.sidebar.button else 4)
            for idx, item in enumerate(CONSUMABLES):
                with c_cols[idx % len(c_cols)]:
                    c_inputs[item] = st.number_input(f"{item}", min_value=0, value=0, step=1, key=f"c_{item}")

            st.markdown("#### 📷 비품 (개)")
            e_inputs = {}
            e_cols = st.columns(2 if st.sidebar.button else 3)
            for idx, item in enumerate(EQUIPMENT):
                with e_cols[idx % len(e_cols)]:
                    e_inputs[item] = st.number_input(f"{item}", min_value=0, value=0, step=1, key=f"e_{item}")

            if st.form_submit_button("🚨 마감 재고 제출"):
                all_val = {**c_inputs, **e_inputs}
                row_data = [today_str, st.session_state['user_name']] + [all_val[item] for item in ALL_ITEMS]
                df_inv = pd.read_csv(INVENTORY_FILE, encoding="utf-8-sig")
                pd.concat([df_inv, pd.DataFrame([row_data], columns=["등록일시", "작성자"] + ALL_ITEMS)], ignore_index=True).to_csv(INVENTORY_FILE, index=False, encoding="utf-8-sig")
                st.success("✅ 마감 재고가 등록되었습니다.")

    with tab2:
        if user_role == "교무팀":
            st.subheader("🛒 [교무팀 전용] 쿠팡 엑셀 자동 입고")
            c_file = st.file_uploader("쿠팡 주문내역 파일 (CSV, XLSX)", type=["csv", "xlsx"])
            if c_file is not None and st.button("⚡ 입고 자동 반영"):
                try:
                    df_c = pd.read_csv(c_file) if c_file.name.endswith('.csv') else pd.read_excel(c_file)
                    df_inv = pd.read_csv(INVENTORY_FILE, encoding="utf-8-sig")
                    last_row = df_inv.iloc[-1].to_dict() if len(df_inv) > 0 else {item: 0 for item in ALL_ITEMS}
                    incoming = {item: 0 for item in ALL_ITEMS}

                    for _, row in df_c.iterrows():
                        row_text = " ".join(row.astype(str)).lower()
                        qty = 1
                        for col in df_c.columns:
                            if any(q in str(col).lower() for q in ["수량", "qty", "개수"]):
                                try: qty = int(row[col])
                                except: qty = 1
                                break
                        for m_item, kws in KEYWORD_MAP.items():
                            if any(kw.lower() in row_text for kw in kws):
                                incoming[m_item] += qty
                                break

                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                    new_row = [now_str, f"쿠팡입고({st.session_state['user_name']})"] + [int(last_row.get(item,0)) + incoming[item] for item in ALL_ITEMS]
                    pd.concat([df_inv, pd.DataFrame([new_row], columns=["등록일시", "작성자"] + ALL_ITEMS)], ignore_index=True).to_csv(INVENTORY_FILE, index=False, encoding="utf-8-sig")
                    st.success("🎉 쿠팡 입고 반영이 완료되었습니다.")
                    st.rerun()
                except Exception as e:
                    st.error(f"오류 발생: {e}")
            st.divider()

        df_inv = pd.read_csv(INVENTORY_FILE, encoding="utf-8-sig")
        if len(df_inv) > 0:
            latest = df_inv.iloc[-1]
            st.caption(f"📅 최근 기록: {latest['등록일시']} (작성자: {latest['작성자']})")
            
            st.subheader("🧻 소모품 잔여 현황")
            m_c = st.columns(4)
            for idx, item in enumerate(CONSUMABLES):
                with m_c[idx % 4]:
                    st.metric(label=item, value=f"{latest.get(item, 0)} BOX")
                    
            st.subheader("📷 비품 잔여 현황")
            m_e = st.columns(3)
            for idx, item in enumerate(EQUIPMENT):
                with m_e[idx % 3]:
                    st.metric(label=item, value=f"{latest.get(item, 0)} 개")

            if user_role == "교무팀":
                st.divider()
                st.download_button(
                    label="📥 전체 재고 기록 엑셀 다운로드",
                    data=df_inv.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
                    file_name=f"재고기록_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv"
                )
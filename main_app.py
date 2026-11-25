import html
import hashlib
import io
import re
import time
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import gspread
import pandas as pd
import requests
import streamlit as st
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from gspread.utils import absolute_range_name, numericise_all

try:
    import extra_streamlit_components as stx
except ImportError:
    stx = None

# ==========================================
# 0. 페이지 기본 설정 (가장 먼저 호출)
# ==========================================
st.set_page_config(
    page_title="러셀대치학원 시설보수 및 재고관리 시스템",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 자동 번역으로 인한 글자 깨짐 방지
st.markdown('<meta name="google" content="notranslate">', unsafe_allow_html=True)

# ==========================================
# 앱 버전 및 업데이트 이력 정의
# ==========================================
APP_VERSION = "v2.3.0"
LAST_UPDATED = "2026-11-25"
UPDATE_HISTORY = [
    {
        "version": "v2.3.0",
        "date": "2026.11.25",
        "changes": [
            "공간구분 확장: 강의실 '603호' 추가 및 기타공간(층별 복도·로비, 3~7층 담임공간, 201~204·6~7층 강사교무실, 7층 원장실) 전면 추가",
            "UI/UX 전면 개선: 상단 히어로 배너, 4종 KPI 상태 카드, 원터치 공간 선택 알약 버튼, 선택 위치별 QR URL 생성기 추가",
            "재고 관리 UX 고도화: 마감 실사 전산 대비 변동·부족 예측 미리보기, 일괄 입출고 실시간 요약, 대시보드 품목 필터 및 상태 배지(정상/발주필요) 추가",
            "현황 및 관리자 UX 개선: 미처리 건 전용 필터, 상태별 컬러 강조 모바일 카드, 사용자 역할 KPI 및 검색 필터 추가",
        ],
    },
    {
        "version": "v2.2.1",
        "date": "2026.11.25",
        "changes": [
            "두레이(Dooray) 웹훅 미수신 원인 해결: Secrets 하위 TOML 섹션([gcp_service_account] 등) 및 config 시트 자동 탐색 지원",
            "두레이 페이로드/헤더 표준화(UTF-8 JSON, 외부 아이콘 URL 제거) 및 HTTP/JSON 응답 검증 추가",
            "교무팀 관리자 화면에 '두레이 웹훅 연동 상태 확인 및 테스트 메시지 발송' UI 추가",
        ],
    },
    {
        "version": "v2.2.0",
        "date": "2026.11.25",
        "changes": [
            "구글 시트 API 429 할당량 초과 오류 해결 (워크시트 리소스 캐시, batchGet 단일 일괄 조회, 지수 백오프 재시도, 장애 시 캐시 유지 폴백)",
            "전화번호 앞자리 '0' 누락 방지 및 private_key_id 기반 해시 토큰 솔트 정상 적용",
            "쿠키 삭제 예외 방어, 수동 새로고침 버튼 추가 및 모바일 카드 HTML 안전 이스케이프",
            "로그인 화면·사이드바·장애 안내 화면 전체에 버전 및 업데이트 내용 상시 표기",
        ],
    },
    {
        "version": "v2.1.0",
        "date": "2026.11.25",
        "changes": [
            "학원 공용/관리자 가입 코드 검증, 중복 가입 방지, SHA-256 해시 토큰 자동 로그인",
            "교무팀 전용 사용자 권한 관리 UI (비활성 차단) 및 조교 재고 대시보드 열람 허용",
            "실시간 전산재고 연동 마감 실사, 일괄 입·출고 등록, 층별 재고 비교, 발주 필요 목록 CSV",
            "시설보수 중복 신고 알림, 처리메모 편집, 사진 링크, QR 자동 선택, 모바일 카드 뷰, 두레이 알림 연동",
        ],
    },
]


# ==========================================
# 🇰🇷 한국 표준시(KST) 및 공통 유틸리티
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


def clean_phone(phone_str):
    if pd.isna(phone_str) or phone_str is None:
        return ""
    return re.sub(r"[^0-9]", "", str(phone_str))


def canonical_phone(phone_str):
    c = clean_phone(phone_str)
    if not c:
        return ""
    if not c.startswith("0") and len(c) in (9, 10) and c[0] in ("1", "2", "3", "4", "5", "6", "7"):
        return "0" + c
    return c


def phone_variants(phone_str):
    c = clean_phone(phone_str)
    if not c:
        return set()
    variants = {c, canonical_phone(c)}
    if c.startswith("0") and len(c) in (10, 11):
        variants.add(c[1:])
    return variants


def _find_secret_recursive(mapping_obj, target_keys_lower, path=""):
    try:
        items = list(mapping_obj.items())
    except Exception:
        return None, ""

    for k, v in items:
        if str(k).strip().lower() in target_keys_lower and not isinstance(v, Mapping):
            val = str(v).strip().strip('"').strip("'")
            if val:
                loc = f"{path}.{k}" if path else str(k)
                return val, loc

    for k, v in items:
        if isinstance(v, Mapping):
            sub_path = f"{path}.{k}" if path else str(k)
            found, loc = _find_secret_recursive(v, target_keys_lower, sub_path)
            if found:
                return found, loc

    return None, ""


def get_secret(key, default=None):
    try:
        if key in st.secrets:
            return st.secrets[key]
        found, _ = _find_secret_recursive(st.secrets, {key.lower()})
        return found if found is not None else default
    except Exception:
        return default


# ==========================================
# 🔔 두레이(Dooray) 웹훅 알림 헬퍼 함수
# ==========================================
def get_dooray_webhook_info():
    """Secrets(최상위 및 [gcp_service_account] 등 하위 섹션 포함)와 config 시트에서 웹훅 URL 탐색"""
    candidate_keys = {"dooray_webhook_url", "dooray_webhook", "webhook_url"}
    try:
        url, loc = _find_secret_recursive(st.secrets, candidate_keys)
        if url:
            return url, f"Streamlit Secrets ({loc})"
    except Exception:
        pass

    try:
        for r in get_config_records():
            cat = str(r.get("카테고리", "")).strip().lower()
            val = str(r.get("항목값", "")).strip().strip('"').strip("'")
            if cat in ("dooray_webhook_url", "두레이웹훅", "두레이_웹훅") and val:
                return val, "구글 시트 (config)"
    except Exception:
        pass

    return "", ""


def send_dooray_alert(message: str):
    """두레이 인커밍 웹훅으로 메시지를 전송하고 (성공여부, 상세결과)를 반환합니다."""
    webhook_url, source = get_dooray_webhook_info()
    if not webhook_url:
        return False, "웹훅 URL 미설정"

    if not webhook_url.startswith(("http://", "https://")):
        return False, f"올바르지 않은 URL 형식 ({source})"

    try:
        payload = {
            "botName": "러셀대치 통합관리 시스템",
            "text": str(message),
        }
        headers = {"Content-Type": "application/json; charset=utf-8"}
        resp = requests.post(webhook_url, json=payload, headers=headers, timeout=10)
        body_text = (resp.text or "").strip()

        if 200 <= resp.status_code < 300:
            try:
                data = resp.json()
                if isinstance(data, dict):
                    if data.get("isSuccessful") is False:
                        return False, f"Dooray 거부: {body_text}"
                    hdr = data.get("header")
                    if isinstance(hdr, dict) and hdr.get("isSuccessful") is False:
                        return False, f"Dooray 거부: {hdr.get('resultMessage') or body_text}"
            except Exception:
                pass
            return True, f"HTTP {resp.status_code} ({source})"

        return False, f"HTTP {resp.status_code}: {body_text[:200]}"
    except Exception as e:
        return False, f"전송 예외: {e}"


# ==========================================
# 🔒 보안 인증 솔트 및 해시 토큰 생성
# ==========================================
def get_secret_salt():
    creds = get_secret("gcp_service_account", {})
    if isinstance(creds, Mapping) and "private_key_id" in creds:
        return str(creds["private_key_id"])
    return str(get_secret("auth_salt", "russel_secret_salt_2026"))


def generate_auth_token(phone: str) -> str:
    canon_p = canonical_phone(phone)
    salt = get_secret_salt()
    return hashlib.sha256(f"{canon_p}:{salt}".encode("utf-8")).hexdigest()


# ==========================================
# 🍪 쿠키 매니저 초기화 (절대 @st.cache_resource 미사용)
# ==========================================
def get_cookie_manager():
    if stx is None:
        return None
    return stx.CookieManager(key="cookie_manager")


cookie_manager = get_cookie_manager()


def safe_get_cookie(name: str):
    if cookie_manager is None:
        return None
    try:
        return cookie_manager.get(cookie=name)
    except Exception:
        return None


def safe_set_cookie(name: str, value: str, days: int = 30):
    if cookie_manager is None:
        return
    try:
        cookie_manager.set(name, value, expires_at=datetime.now() + timedelta(days=days))
    except Exception:
        pass


def safe_delete_cookie(name: str):
    if cookie_manager is None:
        return
    try:
        if cookie_manager.get(cookie=name) is not None:
            cookie_manager.delete(name)
    except Exception:
        pass


# ==========================================
# Custom CSS (모던 UI/UX 디자인 시스템)
# ==========================================
st.markdown("""
    <style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');

    /* 글로벌 폰트 및 배경 설정 */
    html, body, [class*="css"], .stApp {
        font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, Roboto, sans-serif !important;
        background-color: #F4F7FB !important;
        color: #1e293b !important;
        font-size: 15.5px;
        line-height: 1.6;
        letter-spacing: -0.015em;
        -webkit-font-smoothing: antialiased;
        text-rendering: optimizeLegibility;
    }

    .block-container {
        padding-top: 1.6rem !important;
        padding-bottom: 2.5rem !important;
        max-width: 1320px;
    }

    /* 사이드바 스타일 개선 */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0f172a 0%, #111827 100%) !important;
        border-right: 1px solid #1f2937;
    }
    [data-testid="stSidebar"] * {
        color: #f3f4f6 !important;
    }
    [data-testid="stSidebar"] hr { border-color: #334155 !important; margin: 1.1rem 0; }

    /* 사이드바 라디오 버튼 */
    [data-testid="stSidebar"] [data-testid="stRadio"] label p {
        color: #f3f4f6 !important;
        font-weight: 500 !important;
        font-size: 0.94rem !important;
    }
    [data-testid="stSidebar"] [data-testid="stRadio"] div[role="radiogroup"] > label {
        padding: 11px 14px;
        border-radius: 10px;
        margin-bottom: 6px;
        background-color: transparent;
        transition: all 0.2s ease;
    }
    [data-testid="stSidebar"] [data-testid="stRadio"] div[role="radiogroup"] > label:hover {
        background-color: #1e293b !important;
    }
    [data-testid="stSidebar"] [data-testid="stRadio"] div[role="radiogroup"] > label[aria-checked="true"] {
        background: linear-gradient(90deg, #2563eb, #1d4ed8) !important;
        box-shadow: 0 4px 12px rgba(37, 99, 235, 0.35);
    }

    /* 🔥 본문 메인 영역 라디오 버튼 (반응형 알약 형태) */
    .stMainBlockContainer [data-testid="stRadio"] div[role="radiogroup"] {
        display: flex !important;
        flex-wrap: wrap !important;
        gap: 8px !important;
    }
    .stMainBlockContainer [data-testid="stRadio"] label p,
    .stMainBlockContainer [data-testid="stRadio"] div[role="radiogroup"] label p {
        color: #334155 !important;
        font-weight: 600 !important;
        font-size: 0.92rem !important;
    }
    .stMainBlockContainer [data-testid="stRadio"] div[role="radiogroup"] > label {
        background-color: #ffffff !important;
        border: 1.5px solid #e2e8f0 !important;
        padding: 8px 16px !important;
        border-radius: 99px !important;
        margin-right: 0 !important;
        box-shadow: 0 1px 2px rgba(0,0,0,0.03);
        transition: all 0.18s ease;
    }
    .stMainBlockContainer [data-testid="stRadio"] div[role="radiogroup"] > label:hover {
        background-color: #f8fafc !important;
        border-color: #94a3b8 !important;
    }
    .stMainBlockContainer [data-testid="stRadio"] div[role="radiogroup"] > label[aria-checked="true"] {
        background-color: #eff6ff !important;
        border-color: #2563eb !important;
        box-shadow: 0 2px 6px rgba(37, 99, 235, 0.14);
    }
    .stMainBlockContainer [data-testid="stRadio"] div[role="radiogroup"] > label[aria-checked="true"] p {
        color: #1d4ed8 !important;
    }

    /* 히어로 헤더 배너 */
    .hero-header {
        background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 60%, #2563eb 100%);
        color: #ffffff !important;
        border-radius: 16px;
        padding: 22px 26px;
        margin-bottom: 20px;
        box-shadow: 0 10px 24px -6px rgba(30, 58, 138, 0.25);
        display: flex;
        justify-content: space-between;
        align-items: center;
        flex-wrap: wrap;
        gap: 12px;
    }
    .hero-header * { color: #ffffff !important; }
    .hero-title {
        font-size: 1.45rem;
        font-weight: 800;
        letter-spacing: -0.02em;
        margin: 0;
        line-height: 1.25;
    }
    .hero-sub {
        font-size: 0.88rem;
        color: #dbeafe !important;
        margin-top: 5px;
    }
    .hero-badges {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        align-items: center;
    }
    .hero-pill {
        background: rgba(255,255,255,0.16);
        border: 1px solid rgba(255,255,255,0.28);
        padding: 5px 13px;
        border-radius: 999px;
        font-size: 0.78rem;
        font-weight: 600;
    }

    /* 반응형 KPI 카드 그리드 */
    .kpi-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
        gap: 12px;
        margin-bottom: 18px;
    }
    .kpi-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 14px 18px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.03);
        border-top: 3px solid #3b82f6;
    }
    .kpi-card.kpi-blue { border-top-color: #2563eb; }
    .kpi-card.kpi-amber { border-top-color: #d97706; }
    .kpi-card.kpi-green { border-top-color: #16a34a; }
    .kpi-card.kpi-red { border-top-color: #dc2626; }
    .kpi-card.kpi-slate { border-top-color: #475569; }
    .kpi-label {
        font-size: 0.8rem;
        font-weight: 600;
        color: #64748b;
        margin-bottom: 4px;
    }
    .kpi-value {
        font-size: 1.45rem;
        font-weight: 800;
        color: #0f172a;
        line-height: 1.2;
    }
    .kpi-sub {
        font-size: 0.75rem;
        color: #94a3b8;
        margin-top: 3px;
    }

    /* 위치 요약 배너 & 단계 라벨 */
    .step-badge {
        display: inline-block;
        background: #e0e7ff;
        color: #3730a3 !important;
        font-size: 0.75rem;
        font-weight: 700;
        padding: 3px 10px;
        border-radius: 999px;
        margin-bottom: 8px;
    }
    .loc-banner {
        background: #f8fafc;
        border: 1px solid #cbd5e1;
        border-left: 4px solid #2563eb;
        border-radius: 8px;
        padding: 10px 14px;
        margin: 10px 0 14px 0;
        font-size: 0.9rem;
        color: #1e293b;
    }

    /* 유저 카드 (사이드바) */
    .user-card {
        background: linear-gradient(135deg, #1e3a8a, #3b82f6);
        border-radius: 12px;
        padding: 16px;
        margin-bottom: 14px;
        box-shadow: 0 4px 10px -1px rgba(0, 0, 0, 0.18);
    }
    .user-card .u-name { font-size: 1.1rem; font-weight: 700; color: white !important;}
    .user-card .u-role {
        display: inline-block;
        margin-top: 6px;
        font-size: 0.75rem;
        font-weight: 600;
        background: rgba(255,255,255,0.22);
        padding: 3px 10px;
        border-radius: 999px;
        color: white !important;
    }

    /* 타이포그래피 */
    h1, h2, h3, h4, h5, h6 {
        color: #0f172a !important;
        font-weight: 700 !important;
        letter-spacing: -0.02em !important;
    }
    h1 { font-size: 1.7rem !important; margin-bottom: 0.9rem !important; }
    h2 { font-size: 1.3rem !important; border-bottom: 2px solid #e2e8f0; padding-bottom: 0.45rem; margin-bottom: 0.9rem;}
    h3 { font-size: 1.12rem !important; }

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
        border-radius: 10px !important;
        transition: border-color 0.15s ease, box-shadow 0.15s ease;
    }
    .stTextInput input:focus, .stSelectbox div[data-baseweb="select"]:focus-within,
    .stNumberInput input:focus, .stTextArea textarea:focus {
        border-color: #2563eb !important;
        box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.15) !important;
    }

    /* 버튼 스타일 */
    .stButton>button, .stFormSubmitButton>button {
        border-radius: 10px;
        min-height: 44px;
        font-weight: 600;
        background-color: #1e40af !important;
        color: #ffffff !important;
        border: none;
        padding: 0.55rem 1.2rem;
        transition: all 0.2s ease;
        box-shadow: 0 2px 4px rgba(30, 64, 175, 0.15);
    }
    .stButton>button:hover, .stFormSubmitButton>button:hover {
        background-color: #1d4ed8 !important;
        transform: translateY(-1px);
        box-shadow: 0 6px 12px -2px rgba(29, 78, 216, 0.25);
    }
    .stButton>button:active, .stFormSubmitButton>button:active {
        transform: translateY(0);
    }

    /* 사이드바 내부 버튼은 컴팩트하게 유지 */
    [data-testid="stSidebar"] .stButton>button {
        min-height: 38px;
        background-color: #1e293b !important;
        border: 1px solid #334155 !important;
        font-size: 0.85rem;
    }
    [data-testid="stSidebar"] .stButton>button:hover {
        background-color: #334155 !important;
    }

    /* 탭 스타일 */
    .stTabs [data-baseweb="tab-list"] { 
        gap: 6px; 
        border-bottom: 2px solid #e2e8f0;
        padding-bottom: 0;
        flex-wrap: wrap;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: transparent;
        border: none;
        padding: 10px 16px;
        font-weight: 600;
        color: #64748b !important;
        border-radius: 8px 8px 0 0;
    }
    .stTabs [aria-selected="true"] {
        background-color: #eff6ff !important;
        color: #1e40af !important;
        border-bottom: 3px solid #1e40af;
    }
    .stTabs [aria-selected="true"] p { color: #1e40af !important; }

    /* 메인 카드 섹션 & 폼 컨테이너 */
    .section-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 14px;
        padding: 22px 24px;
        margin-bottom: 20px;
        box-shadow: 0 4px 10px -2px rgba(15, 23, 42, 0.04);
    }
    [data-testid="stForm"] {
        background: #ffffff !important;
        border: 1px solid #e2e8f0 !important;
        border-radius: 14px !important;
        padding: 22px 24px !important;
        box-shadow: 0 4px 10px -2px rgba(15, 23, 42, 0.04) !important;
    }

    /* 뱃지 */
    .badge { display:inline-block; padding: 4px 12px; border-radius:999px; font-size:0.75rem; font-weight:700; letter-spacing: 0.02em;}
    .badge-접수완료 { background:#dbeafe; color:#1e40af !important; border: 1px solid #bfdbfe; }
    .badge-처리중 { background:#fef3c7; color:#92400e !important; border: 1px solid #fde68a;}
    .badge-완료 { background:#dcfce7; color:#166534 !important; border: 1px solid #bbf7d0;}

    /* 로그인/메인 패널 */
    .brand-panel {
        background: linear-gradient(145deg, #0f172a 0%, #1e3a8a 70%, #1d4ed8 100%);
        border-radius: 18px;
        padding: 36px;
        height: 100%;
        color: #fff !important;
        box-shadow: 0 14px 28px -8px rgba(15, 23, 42, 0.28);
    }
    .brand-panel * { color: #fff !important; }
    .brand-panel h1 { font-size: 1.8rem !important; margin-bottom: 12px !important; line-height: 1.3;}
    .brand-panel p { color: #cbd5e1 !important; font-size: 0.95rem; line-height: 1.6; }
    .feature-chip {
        display: inline-block;
        background: rgba(255,255,255,0.14);
        border: 1px solid rgba(255,255,255,0.22);
        padding: 5px 12px;
        border-radius: 999px;
        font-size: 0.8rem;
        font-weight: 600;
        margin: 4px 6px 4px 0;
    }

    /* 재고 부족 필 */
    .low-stock-pill {
        display:inline-block; background:#fee2e2; color:#991b1b !important;
        padding: 4px 11px; border-radius: 999px; font-size:0.8rem; font-weight:600; margin: 4px 4px 0 0;
        border: 1px solid #fca5a5;
    }

    /* 모바일 시설 요청 카드 스타일 (상태별 컬러 라인) */
    .req-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-left: 5px solid #2563eb;
        border-radius: 12px;
        padding: 16px 18px;
        margin-bottom: 14px;
        box-shadow: 0 2px 6px rgba(15, 23, 42, 0.04);
        transition: transform 0.15s ease, box-shadow 0.15s ease;
    }
    .req-card.req-card-접수완료 { border-left-color: #2563eb; }
    .req-card.req-card-처리중 { border-left-color: #d97706; }
    .req-card.req-card-완료 { border-left-color: #16a34a; }
    .req-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 14px rgba(15, 23, 42, 0.08);
    }
    .req-card-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 1px solid #f1f5f9;
        padding-bottom: 8px;
        margin-bottom: 10px;
    }
    .req-card-meta {
        font-size: 0.85rem;
        color: #475569;
        margin-bottom: 8px;
        line-height: 1.55;
    }
    .req-card-body {
        font-size: 0.94rem;
        color: #0f172a;
        white-space: pre-line;
        background: #f8fafc;
        padding: 12px 14px;
        border-radius: 8px;
        margin-bottom: 8px;
        border: 1px solid #f1f5f9;
    }
    .req-card-memo {
        font-size: 0.85rem;
        color: #0369a1;
        background: #e0f2fe;
        border: 1px solid #bae6fd;
        padding: 8px 12px;
        border-radius: 8px;
        margin-bottom: 8px;
    }
    .req-photo-link {
        display: inline-block;
        font-size: 0.82rem;
        font-weight: 600;
        color: #1d4ed8 !important;
        text-decoration: none;
        padding: 6px 12px;
        border: 1px solid #bfdbfe;
        border-radius: 8px;
        background-color: #eff6ff;
    }
    .req-photo-link:hover {
        background-color: #dbeafe;
    }

    /* 메트릭 박스 */
    [data-testid="stMetric"] {
        background-color: white;
        border: 1px solid #e2e8f0;
        padding: 14px 18px;
        border-radius: 12px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }
    [data-testid="stMetricValue"] { font-weight: 800 !important; color: #0f172a !important;}
    [data-testid="stMetricLabel"] { font-weight: 600 !important; color: #64748b !important; font-size: 0.85rem;}

    @media (max-width: 640px) {
        .block-container { padding-left: 0.9rem !important; padding-right: 0.9rem !important; padding-top: 1rem !important; }
        .brand-panel { padding: 22px; border-radius: 14px; }
        .brand-panel h1 { font-size: 1.4rem !important; }
        .hero-header { padding: 16px 18px; border-radius: 12px; }
        .hero-title { font-size: 1.2rem; }
        .section-card { padding: 16px; border-radius: 12px; }
        .kpi-grid { grid-template-columns: repeat(2, 1fr); gap: 8px; }
    }
    </style>
""", unsafe_allow_html=True)


# ==========================================
# 구글 API 연동 및 할당량(429) 방어 캐시 계층
# ==========================================
def is_quota_or_transient_error(err: Exception) -> bool:
    s = str(err)
    return any(
        tok in s
        for tok in ("429", "Quota exceeded", "Rate Limit", "500", "502", "503", "504", "timed out", "ConnectionReset")
    )


def call_with_retry(fn, max_retries: int = 3, base_delay: float = 1.0):
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if is_quota_or_transient_error(e) and attempt < max_retries:
                time.sleep(base_delay * (2 ** attempt))
                continue
            raise
    raise last_err


@st.cache_resource
def get_google_services():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_dict = dict(st.secrets["gcp_service_account"])
    if "private_key" in creds_dict:
        pk = str(creds_dict["private_key"]).replace("\\n", "\n")
        creds_dict["private_key"] = pk

    credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(credentials)
    drive_service = build('drive', 'v3', credentials=credentials)
    return gc, drive_service


@st.cache_resource(ttl=3600, show_spinner=False)
def get_spreadsheet_bundle():
    """스프레드시트 및 워크시트 메타데이터를 1시간 동안 1회만 조회하여 429 할당량 소모 차단"""
    gc, drive_service = get_google_services()
    sh = call_with_retry(lambda: gc.open("러셀대치_통합DB"), max_retries=3, base_delay=1.2)
    all_ws = call_with_retry(lambda: sh.worksheets(), max_retries=3, base_delay=1.2)
    ws_map = {ws.title: ws for ws in all_ws}

    ws_users = ws_map.get("users")
    ws_facility = ws_map.get("facility")
    ws_inventory = ws_map.get("inventory")
    ws_config = ws_map.get("config")

    if not ws_users or not ws_facility or not ws_inventory:
        missing = [k for k, v in [("users", ws_users), ("facility", ws_facility), ("inventory", ws_inventory)] if not v]
        raise RuntimeError(f"필수 워크시트를 찾을 수 없습니다: {', '.join(missing)}")

    return {
        "gc": gc,
        "drive_service": drive_service,
        "sh": sh,
        "ws_users": ws_users,
        "ws_facility": ws_facility,
        "ws_inventory": ws_inventory,
        "ws_config": ws_config,
    }


@st.cache_resource
def _get_sheet_store():
    """모든 세션이 공유하는 메모리 캐시 + 장애 시 Stale 데이터 폴백 저장소"""
    return {
        "users": {"records": None, "header": [], "row_nums": [], "ts": 0.0, "ttl": 180},
        "facility": {"records": None, "header": [], "row_nums": [], "ts": 0.0, "ttl": 60},
        "inventory": {"records": None, "header": [], "row_nums": [], "ts": 0.0, "ttl": 60},
        "config": {"records": None, "header": [], "row_nums": [], "ts": 0.0, "ttl": 600},
        "using_stale": False,
        "last_error": "",
    }


def _parse_sheet_matrix(values, numericise=False):
    if not values or values == [[]]:
        return [], [], []
    raw_header = [str(h).strip() for h in values[0]]
    while raw_header and raw_header[-1] == "":
        raw_header.pop()
    if not raw_header:
        return [], [], []

    num_cols = len(raw_header)
    seen = {}
    header = []
    for idx, h in enumerate(raw_header):
        key = h if h else f"col_{idx + 1}"
        if key in seen:
            seen[key] += 1
            key = f"{key}_{seen[key]}"
        else:
            seen[key] = 0
        header.append(key)

    records = []
    row_nums = []
    for sheet_row_idx, raw_row in enumerate(values[1:], start=2):
        padded = list(raw_row[:num_cols]) + [""] * max(0, num_cols - len(raw_row))
        if all(str(cell).strip() == "" for cell in padded):
            continue
        if numericise:
            padded = numericise_all(padded, empty2zero=False, default_blank="")
        records.append(dict(zip(header, padded)))
        row_nums.append(sheet_row_idx)

    return header, records, row_nums


def invalidate_sheet(name: str):
    store = _get_sheet_store()
    if name in store:
        store[name]["ts"] = 0.0


def invalidate_all_sheets():
    store = _get_sheet_store()
    for name in ("users", "facility", "inventory", "config"):
        store[name]["ts"] = 0.0


def sync_sheets(bundle, sheet_names=None, force: bool = False) -> bool:
    """
    만료된 시트만 선별하여 복수 시트일 경우 values_batch_get 단일 API 호출로 일괄 동기화합니다.
    429 등 일시 장애 시 기존 캐시 데이터를 유지하여 접속 불능(st.stop)을 방지합니다.
    """
    store = _get_sheet_store()
    now = time.time()
    all_names = ["users", "facility", "inventory"]
    if bundle.get("ws_config") is not None:
        all_names.append("config")
    elif store["config"]["records"] is None:
        store["config"]["records"] = []
        store["config"]["ts"] = now

    targets = sheet_names if sheet_names is not None else all_names
    targets = [n for n in targets if n in all_names]

    if force:
        stale = list(targets)
    else:
        stale = [
            n for n in targets
            if store[n]["records"] is None or (now - store[n]["ts"]) >= store[n]["ttl"]
        ]

    if not stale:
        return True

    sh = bundle["sh"]
    try:
        if len(stale) > 1:
            ranges = [absolute_range_name(n) for n in stale]
            resp = call_with_retry(lambda: sh.values_batch_get(ranges), max_retries=2, base_delay=1.0)
            value_ranges = resp.get("valueRanges", [])
            for idx, name in enumerate(stale):
                vr = value_ranges[idx] if idx < len(value_ranges) else {}
                values = vr.get("values", [[]])
                header, recs, row_nums = _parse_sheet_matrix(values, numericise=(name == "inventory"))
                store[name]["header"] = header
                store[name]["records"] = recs
                store[name]["row_nums"] = row_nums
                store[name]["ts"] = now
        else:
            name = stale[0]
            ws = bundle.get(f"ws_{name}")
            if ws is not None:
                values = call_with_retry(lambda: ws.get_all_values(), max_retries=2, base_delay=1.0)
                header, recs, row_nums = _parse_sheet_matrix(values, numericise=(name == "inventory"))
                store[name]["header"] = header
                store[name]["records"] = recs
                store[name]["row_nums"] = row_nums
                store[name]["ts"] = now

        store["using_stale"] = False
        store["last_error"] = ""
        return True
    except Exception as e:
        store["last_error"] = str(e)
        all_have_cache = all(store[n]["records"] is not None for n in stale)
        for n in stale:
            if store[n]["records"] is not None:
                store[n]["ts"] = now - store[n]["ttl"] + 15
        if all_have_cache:
            store["using_stale"] = True
            return True
        return False


def _render_connection_recovery_ui(err_msg: str):
    """초기 연결 실패 시에도 버전 정보와 복구 버튼을 제공하여 접속 가능성 보장"""
    latest = UPDATE_HISTORY[0]
    changes_html = "".join([f"<li>{html.escape(c)}</li>" for c in latest["changes"]])
    st.markdown(f"""
        <div class="section-card">
            <h3>🏢 러셀대치학원 시설보수 및 재고관리 시스템 ({APP_VERSION})</h3>
            <p style="color:#64748b; font-size:0.9rem;">최종 업데이트: {LAST_UPDATED}</p>
            <ul style="font-size:0.88rem; color:#334155;">{changes_html}</ul>
        </div>
    """, unsafe_allow_html=True)
    st.error(f"⚠️ 구글 시트 연결이 일시적으로 지연되고 있습니다: {err_msg}")
    st.info("💡 구글 API 분당 읽기 할당량 초과(429)인 경우 약 30초~1분 후 자동 회복됩니다. 아래 버튼을 눌러 다시 연결해 주세요.")
    if st.button("🔄 지금 다시 연결하기", use_container_width=True):
        get_spreadsheet_bundle.clear()
        invalidate_all_sheets()
        st.rerun()
    st.stop()


try:
    bundle = get_spreadsheet_bundle()
    gc = bundle["gc"]
    drive_service = bundle["drive_service"]
    sh = bundle["sh"]
    ws_users = bundle["ws_users"]
    ws_facility = bundle["ws_facility"]
    ws_inventory = bundle["ws_inventory"]
    ws_config = bundle["ws_config"]

    sync_ok = sync_sheets(bundle)
    if not sync_ok:
        _render_connection_recovery_ui(_get_sheet_store()["last_error"])
except Exception as e:
    _render_connection_recovery_ui(str(e))

_store_state = _get_sheet_store()
if _store_state.get("using_stale"):
    st.toast("⏳ 구글 시트 API 요청 한도 초과로 최근 캐시 데이터를 표시 중입니다.", icon="⚠️")

FACILITY_HEADER = _store_state["facility"]["header"]
FACILITY_HAS_ID = "요청ID" in FACILITY_HEADER


# ==========================================
# 캐시된 데이터 접근 래퍼
# ==========================================
def get_facility_records_with_rows():
    sync_sheets(bundle, ["facility"])
    entry = _get_sheet_store()["facility"]
    return list(entry["records"] or []), list(entry["row_nums"] or [])


def get_facility_records():
    recs, _ = get_facility_records_with_rows()
    return recs


def get_inventory_records():
    sync_sheets(bundle, ["inventory"])
    return list(_get_sheet_store()["inventory"]["records"] or [])


def get_users_records_with_rows():
    sync_sheets(bundle, ["users"])
    entry = _get_sheet_store()["users"]
    return list(entry["records"] or []), list(entry["row_nums"] or [])


def get_users_records():
    recs, _ = get_users_records_with_rows()
    return recs


def get_config_records():
    sync_sheets(bundle, ["config"])
    return list(_get_sheet_store()["config"]["records"] or [])


def refresh_sheet_now(name: str):
    invalidate_sheet(name)
    sync_sheets(bundle, [name], force=True)


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


def status_badge(status):
    status = html.escape(str(status).strip() or "접수완료")
    return f'<span class="badge badge-{status}">{status}</span>'


def render_hero(title: str, subtitle: str, badges: list):
    badges_html = "".join([f'<span class="hero-pill">{html.escape(str(b))}</span>' for b in badges])
    st.markdown(f"""
        <div class="hero-header">
            <div>
                <div class="hero-title">{html.escape(title)}</div>
                <div class="hero-sub">{html.escape(subtitle)}</div>
            </div>
            <div class="hero-badges">{badges_html}</div>
        </div>
    """, unsafe_allow_html=True)


def render_kpi_cards(items: list):
    cards = []
    for it in items:
        color = it.get("color", "blue")
        label = html.escape(str(it.get("label", "")))
        value = html.escape(str(it.get("value", "")))
        sub = html.escape(str(it.get("sub", "")))
        sub_html = f'<div class="kpi-sub">{sub}</div>' if sub else ""
        cards.append(
            f'<div class="kpi-card kpi-{color}">'
            f'<div class="kpi-label">{label}</div>'
            f'<div class="kpi-value">{value}</div>'
            f'{sub_html}</div>'
        )
    st.markdown(f'<div class="kpi-grid">{"".join(cards)}</div>', unsafe_allow_html=True)


# ==========================================
# 물품/공간/분류 목록 (확장된 공간 구성 반영)
# ==========================================
CONSUMABLES_BASE = [
    "A4용지", "A3용지", "B4용지", "미색A4용지", "미색A3용지",
    "분필(백)", "분필(청)", "분필(빨)", "분필(노)",
    "점보롤", "핸드타월", "물티슈", "각티슈", "물비누",
    "종이컵", "세모금컵", "생수", "AAA건전지", "AA건전지", "마이크 커버"
]

FLOORS = ["2층", "6층", "7층"]

ALL_SHEET_ITEMS = [f"{item} ({floor})" for item in CONSUMABLES_BASE for floor in FLOORS] + [
    "노트북", "출결리더기", "보조배터리", "캠코더",
    "삼각대 및 플레이트", "SD카드", "빔포인터", "빔리모콘", "에어컨리모콘"
]

EQUIPMENT_DEFAULT = [
    "노트북", "출결리더기", "보조배터리", "캠코더",
    "삼각대 및 플레이트", "SD카드", "빔포인터", "빔리모콘", "에어컨리모콘"
]

SPACES_DEFAULT = {
    "강의실": [
        "대형강의실",
        "201호", "202호", "203호", "204호",
        "601호", "602호", "603호",
        "701호", "702호", "703호", "704호"
    ],
    "자습관": [
        "3-1관", "3-2관", "3-3관", "3-4관", "3-5관",
        "4-1관", "4-2관", "4-3관", "4-4관", "4-5관",
        "5-1관", "5-2관", "5-3관",
        "6-1관", "6-2관", "7-1관"
    ],
    "화장실": [
        "2층 남자화장실", "2층 여자화장실",
        "3층 남자화장실", "3층 여자화장실",
        "5층 남자화장실", "5층 여자화장실",
        "6층 남자화장실", "6층 여자화장실",
        "7층 남자화장실", "7층 여자화장실"
    ],
    "기타공간": [
        "3층 담임공간", "4층 담임공간", "5층 담임공간", "6층 담임공간", "7층 담임공간",
        "201 강사교무실", "202 강사교무실", "203 강사교무실", "204 강사교무실",
        "6층 강사교무실", "7층 강사교무실", "7층 원장실",
        "2층 로비", "3층 로비", "4층 로비", "5층 로비", "6층 로비", "7층 로비",
        "2층 복도", "3층 복도", "4층 복도", "5층 복도", "6층 복도", "7층 복도",
        "기타공간 (복도/엘리베이터/로비/사무실 등)"
    ]
}

CATEGORY_BY_SPACE_DEFAULT = {
    "강의실": ["빔프로젝터/음향", "냉난방/환기", "조명/전기", "책상/의자/칠판", "문/창문/열쇠", "신규 물품 구매 요청", "기타 시설"],
    "자습관": ["자습관 책상/시디즈 의자", "스탠드/전기/콘센트", "냉난방/공기청정기", "공용 스탠딩 책상", "문/창문/소음 문제", "신규 물품 구매 요청", "기타 시설"],
    "화장실": ["대변기 (막힘/고장/부속)", "소변기 (막힘/자동센서/누수)", "세면대/수도꼭지", "휴지걸이/비누디스펜서", "조명/환풍기", "바닥 배수구/타일", "신규 물품 구매 요청", "기타 시설"],
    "기타공간": [
        "조명/전기", "냉난방/환기", "책상/의자/사무집기", "네트워크/프린터/OA",
        "엘리베이터", "복도/계단/난간", "정수기/음료대", "자동문/출입문",
        "문/출입문/열쇠", "신규 물품 구매 요청", "기타 시설"
    ]
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

# 가입 코드 (st.secrets 우선, 미설정 시 기본값)
SIGNUP_CODE = str(get_secret("signup_code", "russel2026"))
ADMIN_SIGNUP_CODE = str(get_secret("admin_signup_code", "russeladmin2026"))

# 세션 초기화
if "logged_in" not in st.session_state: st.session_state["logged_in"] = False
if "user_name" not in st.session_state: st.session_state["user_name"] = ""
if "user_phone" not in st.session_state: st.session_state["user_phone"] = ""
if "user_role" not in st.session_state: st.session_state["user_role"] = ""


# ==========================================
# 🔑 자동 로그인 검증 (쿠키 해시 토큰 기반)
# ==========================================
if not st.session_state["logged_in"]:
    cookie_token = safe_get_cookie("russel_auth_token")
    cookie_phone = safe_get_cookie("russel_user_phone")

    target_token = cookie_token
    if not target_token and cookie_phone:
        target_token = generate_auth_token(cookie_phone)

    if target_token:
        users_list = get_users_records()
        users_cache_loaded = _get_sheet_store()["users"]["records"] is not None
        df_u = pd.DataFrame(users_list)
        matched = None
        if not df_u.empty:
            for _, row in df_u.iterrows():
                raw_p = str(row.get("전화번호", ""))
                if any(generate_auth_token(v) == target_token for v in phone_variants(raw_p)):
                    matched = row
                    break

        if matched is not None:
            role = str(matched.get("분류", "직원")).strip()
            if role == "비활성":
                safe_delete_cookie("russel_auth_token")
                safe_delete_cookie("russel_user_phone")
            else:
                st.session_state["logged_in"] = True
                st.session_state["user_name"] = str(matched.get("이름", "")).strip()
                st.session_state["user_phone"] = canonical_phone(str(matched.get("전화번호", "")))
                st.session_state["user_role"] = role
                if not cookie_token:
                    safe_set_cookie("russel_auth_token", target_token, days=30)
                st.rerun()
        elif users_cache_loaded and not _get_sheet_store().get("using_stale"):
            safe_delete_cookie("russel_auth_token")
            safe_delete_cookie("russel_user_phone")


# ==========================================
# 1. 로그인 & 회원가입
# ==========================================
if not st.session_state["logged_in"]:
    left, right = st.columns([1.05, 1.25], gap="large")

    with left:
        latest_update = UPDATE_HISTORY[0]
        latest_bullets = "".join([f"<div style='margin-bottom:5px;'>• {html.escape(c)}</div>" for c in latest_update["changes"][:3]])
        st.markdown(f"""
            <div class="brand-panel">
                <h1>🏢 러셀대치학원<br>통합 관리 시스템</h1>
                <p>시설 고장 신고, 물품 구매 요청, 소모품·비품 재고를<br>
                한 곳에서 빠르고 직관적으로 관리하세요.</p>
                <div style="margin-top: 18px;">
                    <span class="feature-chip">🔧 시설 보수 신고</span>
                    <span class="feature-chip">🛒 구매 요청</span>
                    <span class="feature-chip">📦 전산연동 재고</span>
                    <span class="feature-chip">📱 QR 원스톱 접수</span>
                </div>
                <div style="margin-top: 24px; padding: 14px 16px; background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.18); border-radius: 12px; font-size: 0.8rem;">
                    <div style="font-weight: 700; margin-bottom: 7px;">📌 버전: {APP_VERSION} ({latest_update['date']} 업데이트)</div>
                    <div style="opacity: 0.92; line-height: 1.5;">{latest_bullets}</div>
                </div>
            </div>
        """, unsafe_allow_html=True)

    with right:
        tab_login, tab_signup = st.tabs(["🔑 로그인", "📝 회원가입"])

        with tab_login:
            with st.form("login_form"):
                st.markdown("### 로그인")
                st.caption("등록된 이름과 전화번호로 바로 접속하세요.")
                login_name = st.text_input("이름", placeholder="예: 홍길동")
                login_phone = st.text_input("전화번호", type="password", placeholder="숫자만 입력 (- 없이)")
                auto_login = st.checkbox("🔑 로그인 상태 유지 (30일 자동 로그인)", value=True)
                st.write("")
                submitted = st.form_submit_button("로그인하기", use_container_width=True)

            if submitted:
                c_name = login_name.strip()
                c_phone = canonical_phone(login_phone)

                if not c_name or not c_phone:
                    st.error("이름과 전화번호를 모두 입력해 주세요.")
                else:
                    df_u = pd.DataFrame(get_users_records())
                    matched = None
                    input_variants = phone_variants(login_phone)
                    if not df_u.empty:
                        for _, row in df_u.iterrows():
                            row_name = str(row.get("이름", "")).strip()
                            row_variants = phone_variants(str(row.get("전화번호", "")))
                            if row_name == c_name and (input_variants & row_variants):
                                matched = row
                                break

                    if matched is not None:
                        u_role = str(matched.get("분류", "직원")).strip()
                        if u_role == "비활성":
                            st.error("🔒 비활성화된 계정입니다. 교무팀 관리자에게 문의하세요.")
                        else:
                            st.session_state["logged_in"] = True
                            st.session_state["user_name"] = c_name
                            st.session_state["user_phone"] = c_phone
                            st.session_state["user_role"] = u_role

                            if auto_login:
                                auth_token = generate_auth_token(c_phone)
                                safe_set_cookie("russel_auth_token", auth_token, days=30)
                                time.sleep(0.2)

                            st.success(f"🎉 {c_name}님 환영합니다!")
                            st.rerun()
                    else:
                        st.error("이름 또는 전화번호가 일치하지 않습니다. 처음이시라면 회원가입 탭을 이용해 주세요.")

        with tab_signup:
            with st.container(border=True):
                st.markdown("### 신규 회원가입")
                st.caption("학원 내부 구성원 인증 후 계정을 생성합니다.")

                signup_role = st.selectbox("가입 구분", ["직원", "강사", "교무팀", "조교"])

                if signup_role == "교무팀":
                    st.info("💡 **교무팀**: 시설요청 상태·메모 관리, 사용자 권한 관리, 재고 전체 관리 권한 (관리자 가입 코드 필요)")
                elif signup_role == "조교":
                    st.info("💡 **조교**: 시설보수/구매요청, 마감 실사 등록 및 재고 대시보드 열람 권한 (관리자 가입 코드 필요)")
                else:
                    st.info("💡 **직원/강사**: 시설보수 및 물품 구매 요청 등록·진행현황 조회 가능 (학원 가입 코드 필요)")

                col_su1, col_su2 = st.columns(2)
                with col_su1:
                    signup_name = st.text_input("이름", key="s_name", placeholder="예: 홍길동")
                with col_su2:
                    signup_phone = st.text_input("전화번호", key="s_phone", placeholder="숫자만 입력 (- 없이)")
                st.caption("전화번호는 로그인 비밀번호로 사용되며 8자리 이상 입력해 주세요.")

                signup_code_input = st.text_input(
                    "학원 가입 코드",
                    type="password",
                    key="s_code",
                    placeholder="학원에서 안내받은 가입 코드 입력"
                )

                st.write("")
                if st.button("회원가입 완료", use_container_width=True, key="signup_btn"):
                    c_name = signup_name.strip()
                    c_phone = canonical_phone(signup_phone)
                    c_code = signup_code_input.strip()

                    if not c_name:
                        st.error("이름을 입력해 주세요.")
                    elif len(clean_phone(signup_phone)) < 8:
                        st.error("전화번호는 숫자 8자리 이상으로 입력해 주세요.")
                    elif not c_code:
                        st.error("학원 가입 코드를 입력해 주세요.")
                    elif signup_role in ["교무팀", "조교"] and c_code != ADMIN_SIGNUP_CODE:
                        st.error("🔒 관리자(교무팀/조교) 가입 코드가 일치하지 않습니다. 교무팀에 문의해 주세요.")
                    elif signup_role not in ["교무팀", "조교"] and c_code != SIGNUP_CODE:
                        st.error("🔒 학원 가입 코드가 일치하지 않습니다. 관리자에게 문의해 주세요.")
                    else:
                        df_u = pd.DataFrame(get_users_records())
                        input_vars = phone_variants(c_phone)
                        is_duplicate = False
                        if not df_u.empty and "전화번호" in df_u.columns:
                            for p in df_u["전화번호"]:
                                if input_vars & phone_variants(str(p)):
                                    is_duplicate = True
                                    break

                        if is_duplicate:
                            st.error("이미 등록된 전화번호입니다. 로그인 탭을 이용해 주세요.")
                        else:
                            now_str = get_kst_now()
                            call_with_retry(lambda: ws_users.append_row([c_name, f"'{c_phone}", signup_role, now_str]))
                            refresh_sheet_now("users")

                            auth_token = generate_auth_token(c_phone)
                            safe_set_cookie("russel_auth_token", auth_token, days=30)
                            time.sleep(0.2)
                            st.session_state["logged_in"] = True
                            st.session_state["user_name"] = c_name
                            st.session_state["user_phone"] = c_phone
                            st.session_state["user_role"] = signup_role
                            st.success("✅ 회원가입 및 로그인 완료!")
                            st.rerun()

        with st.expander("📜 최근 업데이트 내역 보기"):
            for item in UPDATE_HISTORY:
                st.markdown(f"**{item['version']}** ({item['date']})")
                for ch in item["changes"]:
                    st.markdown(f"- {ch}")
    st.stop()


# ==========================================
# 2. 메인 화면 및 사이드바 메뉴
# ==========================================
sync_badge_text = "🟡 캐시 모드" if _store_state.get("using_stale") else "🟢 실시간 연동"
st.sidebar.markdown(f"""
    <div class="user-card">
        <div style="display:flex; justify-content:space-between; font-size: 0.76rem; opacity: 0.85; margin-bottom: 4px;">
            <span>{get_kst_now()} (KST)</span>
            <span>{sync_badge_text}</span>
        </div>
        <div class="u-name">👤 {html.escape(st.session_state['user_name'])}</div>
        <span class="u-role">{html.escape(st.session_state['user_role'])}</span>
    </div>
""", unsafe_allow_html=True)

col_sb1, col_sb2 = st.sidebar.columns(2)
with col_sb1:
    if st.button("🔄 새로고침", use_container_width=True, help="구글 시트 최신 데이터를 즉시 불러옵니다"):
        sync_sheets(bundle, force=True)
        st.rerun()
with col_sb2:
    if st.button("🚪 로그아웃", use_container_width=True):
        safe_delete_cookie("russel_auth_token")
        safe_delete_cookie("russel_user_phone")
        st.session_state["logged_in"] = False
        st.session_state["user_name"] = ""
        st.session_state["user_phone"] = ""
        st.session_state["user_role"] = ""
        time.sleep(0.2)
        st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown("<h4 style='color: white !important; font-size: 0.95rem; margin-bottom: 8px;'>메뉴 이동</h4>", unsafe_allow_html=True)

user_role = st.session_state["user_role"]
is_full_admin = (user_role == "교무팀")
is_silsa_staff = (user_role == "조교")
can_access_inventory = is_full_admin or is_silsa_staff

if is_full_admin:
    menu_options = ["📦 물품/비품 재고 관리", "🛠️ 시설 보수 및 구매 요청", "👥 사용자 권한 관리"]
elif can_access_inventory:
    menu_options = ["📦 물품/비품 재고 관리", "🛠️ 시설 보수 및 구매 요청"]
else:
    menu_options = ["🛠️ 시설 보수 및 구매 요청"]

menu = st.sidebar.radio("Navigation", menu_options, label_visibility="collapsed")

# 사이드바 하단 버전 정보 및 업데이트 내역 상시 표기
st.sidebar.markdown("---")
latest_ver = UPDATE_HISTORY[0]
st.sidebar.markdown(f"""
    <div style="background: rgba(255,255,255,0.06); border: 1px solid #334155; border-radius: 10px; padding: 12px; margin-top: 6px;">
        <div style="color: #60a5fa; font-weight: 700; font-size: 0.84rem; margin-bottom: 5px;">
            📌 버전: {APP_VERSION} ({latest_ver['date']} 업데이트)
        </div>
        <div style="color: #cbd5e1; font-size: 0.74rem; line-height: 1.48;">
            • 603호·담임공간·교무실·원장실·복도·로비 추가<br>
            • 히어로 배너·KPI 카드·원터치 위치 UI 개편<br>
            • 두레이 웹훅 탐색·테스트 UI & 429 방어<br>
            • 전산연동 실사·일괄 입출고·발주목록 CSV
        </div>
    </div>
""", unsafe_allow_html=True)

with st.sidebar.expander("📜 전체 업데이트 상세 보기"):
    for item in UPDATE_HISTORY:
        st.markdown(f"**{item['version']}** ({item['date']})")
        for ch in item["changes"]:
            st.markdown(f"- {ch}")

if "dooray_flash" in st.session_state:
    flash_kind, flash_msg = st.session_state.pop("dooray_flash")
    if flash_kind == "ok":
        st.toast(flash_msg, icon="🔔")
    elif flash_kind == "warn":
        st.warning(flash_msg)


# ==========================================
# 3. 요청 등록 (시설 보수 및 구매 요청)
# ==========================================
if menu == "🛠️ 시설 보수 및 구매 요청":
    render_hero(
        "🛠️ 시설 보수 및 물품 구매 요청",
        "고장 신고 및 비품 구매 요청을 빠르게 접수하고 실시간 처리 현황을 확인하세요.",
        [f"👤 {st.session_state['user_name']} ({user_role})", f"📌 {APP_VERSION}"]
    )
    tab1, tab2 = st.tabs(["📝 새로운 요청 등록", "📋 진행 현황 확인"])

    with tab1:
        with st.container(border=True):
            st.markdown('<span class="step-badge">STEP 1 · 요청 유형 선택</span>', unsafe_allow_html=True)
            req_type = st.radio(
                "요청 유형 선택",
                ["🔧 시설 보수 요청", "🛒 신규 물품/비품 구매 요청"],
                horizontal=True,
                label_visibility="collapsed"
            )

            st.write("")
            st.markdown('<span class="step-badge">STEP 2 · 공간 및 위치 선택</span>', unsafe_allow_html=True)

            # QR코드 쿼리 파라미터 확인 (?space=강의실&detail=603호)
            try:
                qp = st.query_params
                param_space = qp.get("space", None)
                param_detail = qp.get("detail", None)
            except Exception:
                try:
                    qp = st.experimental_get_query_params()
                    param_space = qp.get("space", [None])[0]
                    param_detail = qp.get("detail", [None])[0]
                except Exception:
                    param_space, param_detail = None, None

            space_keys = list(SPACES.keys())
            def_space_idx = space_keys.index(param_space) if (param_space and param_space in space_keys) else 0

            space_cat = st.radio("공간 구분", space_keys, index=def_space_idx, horizontal=True)

            det_options = SPACES[space_cat]
            def_detail_idx = det_options.index(param_detail) if (param_detail and param_detail in det_options) else 0
            det_space = st.selectbox("세부 위치 (직접 검색 가능)", det_options, index=def_detail_idx)

            st.markdown(
                f'<div class="loc-banner">📍 선택된 위치: <b>{html.escape(space_cat)}</b> &rsaquo; <b>{html.escape(det_space)}</b></div>',
                unsafe_allow_html=True
            )

            # 중복 신고 방지 알림 검사
            df_facility_all = pd.DataFrame(get_facility_records())
            if not df_facility_all.empty and "세부위치" in df_facility_all.columns and "상태" in df_facility_all.columns:
                unresolved = df_facility_all[
                    (df_facility_all["세부위치"] == det_space) &
                    (df_facility_all["상태"].isin(["접수완료", "처리중"]))
                ]
                if not unresolved.empty:
                    st.warning(f"⚠️ **[중복 접수 주의]** 선택하신 위치(**'{det_space}'**)에 이미 처리 중인 요청이 **{len(unresolved)}건** 있습니다:")
                    for _, un_row in unresolved.tail(3).iterrows():
                        u_dt = html.escape(str(un_row.get("일시", "-")))
                        u_cat = html.escape(str(un_row.get("분류", "-")))
                        u_st = html.escape(str(un_row.get("상태", "-")))
                        u_name = html.escape(str(un_row.get("작성자", "-")))
                        u_desc = html.escape(str(un_row.get("상세내용", "-"))[:70])
                        st.markdown(f"- 🗓️ `{u_dt}` | **{u_cat}** | `{u_st}` | 작성자: `{u_name}`<br>&nbsp;&nbsp;↳ *{u_desc}*", unsafe_allow_html=True)

            if is_full_admin or is_silsa_staff:
                with st.expander("🔗 이 위치 전용 QR 접속 링크 확인"):
                    qr_link = f"https://rsdc-inven.streamlit.app/?space={quote(space_cat)}&detail={quote(det_space)}"
                    st.caption("아래 링크를 QR코드로 생성해 부착하면 스캔 즉시 해당 공간이 자동 선택됩니다.")
                    st.code(qr_link, language="text")

            st.markdown("---")
            st.markdown('<span class="step-badge">STEP 3 · 상세 내용 및 사진 첨부</span>', unsafe_allow_html=True)

            if req_type == "🔧 시설 보수 요청":
                cat = st.selectbox("보수 분류", [c for c in CATEGORY_BY_SPACE[space_cat] if c != "신규 물품 구매 요청"])
                details = st.text_area("상세 고장 내용", placeholder="예: 에어컨에서 이상한 소음이 나고 냉방이 잘 안됩니다.", height=120)

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
                            call_with_retry(lambda: ws_facility.append_row(row))
                            refresh_sheet_now("facility")

                            dooray_msg = (
                                f"🚨 [신규 시설 보수 요청]\n"
                                f"• 위치: {space_cat} > {det_space}\n"
                                f"• 분류: [보수] {cat}\n"
                                f"• 작성자: {st.session_state['user_name']}\n"
                                f"• 상세내용:\n{details.strip()}"
                            )
                            alert_ok, alert_detail = send_dooray_alert(dooray_msg)

                        st.success("✅ 요청이 성공적으로 등록되었습니다. '진행 현황 확인' 탭에서 처리 상태를 확인하세요.")
                        if get_dooray_webhook_info()[0]:
                            if alert_ok:
                                st.toast("🔔 두레이 알림이 발송되었습니다.", icon="✅")
                            else:
                                st.warning(f"⚠️ 요청은 저장되었으나 두레이 알림 전송에 실패했습니다: {alert_detail}")
                        st.balloons()
                    else:
                        st.error("상세 내용을 입력해 주세요.")
            else:
                col_i1, col_i2 = st.columns([3, 1])
                with col_i1:
                    item_n = st.text_input("구매 물품명", placeholder="예: 무선 마우스")
                with col_i2:
                    item_q = st.number_input("수량", min_value=1, value=1)

                item_r = st.text_area("구매 사유 및 목적", placeholder="예: 기존 마우스 고장으로 교체 필요", height=100)

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
                            call_with_retry(lambda: ws_facility.append_row(row))
                            refresh_sheet_now("facility")

                            dooray_msg = (
                                f"🛒 [신규 물품 구매 요청]\n"
                                f"• 위치: {space_cat} > {det_space}\n"
                                f"• 물품명: {item_n} ({item_q}개)\n"
                                f"• 작성자: {st.session_state['user_name']}\n"
                                f"• 구매사유:\n{item_r.strip()}"
                            )
                            alert_ok, alert_detail = send_dooray_alert(dooray_msg)

                        st.success("✅ 구매 요청이 성공적으로 등록되었습니다.")
                        if get_dooray_webhook_info()[0]:
                            if alert_ok:
                                st.toast("🔔 두레이 알림이 발송되었습니다.", icon="✅")
                            else:
                                st.warning(f"⚠️ 요청은 저장되었으나 두레이 알림 전송에 실패했습니다: {alert_detail}")
                        st.balloons()
                    else:
                        st.error("물품명과 구매 사유를 모두 입력해 주세요.")

    with tab2:
        f_records, f_row_nums = get_facility_records_with_rows()
        df_f = pd.DataFrame(f_records)

        if df_f.empty:
            st.info("등록된 요청 내역이 없습니다.")
        else:
            sheet_row_map = {idx: f_row_nums[idx] for idx in range(len(f_row_nums))}

            total_cnt = len(df_f)
            recv_cnt = int((df_f.get("상태") == "접수완료").sum()) if "상태" in df_f.columns else 0
            prog_cnt = int((df_f.get("상태") == "처리중").sum()) if "상태" in df_f.columns else 0
            done_cnt = int((df_f.get("상태") == "완료").sum()) if "상태" in df_f.columns else 0

            render_kpi_cards([
                {"label": "전체 요청", "value": f"{total_cnt}건", "color": "slate"},
                {"label": "🔵 접수완료", "value": f"{recv_cnt}건", "color": "blue"},
                {"label": "🟡 처리중", "value": f"{prog_cnt}건", "color": "amber"},
                {"label": "🟢 처리완료", "value": f"{done_cnt}건", "color": "green"},
            ])

            with st.container(border=True):
                f1, f2, f3 = st.columns([1, 1, 2])
                with f1:
                    space_filter = st.selectbox("공간 필터", ["전체"] + list(SPACES.keys()))
                with f2:
                    status_filter = st.selectbox("상태 필터", ["전체"] + STATUS_OPTIONS)
                with f3:
                    keyword = st.text_input("🔍 위치/내용/작성자 검색", placeholder="검색어를 입력하세요 (예: 603호, 담임공간)")

                col_sub1, col_sub2, col_sub3 = st.columns([1.2, 1.2, 1.6])
                with col_sub1:
                    show_mine = st.checkbox("🙋 내가 작성한 요청만 보기", value=(not is_full_admin))
                with col_sub2:
                    only_unresolved = st.checkbox("⏳ 미처리(접수·처리중)만 보기", value=False)
                with col_sub3:
                    view_mode = st.radio("보기 모드", ["📋 표 보기", "📱 모바일 카드 보기"], horizontal=True, label_visibility="collapsed")

            df_view = df_f.copy()
            if space_filter != "전체" and "공간구분" in df_view.columns:
                df_view = df_view[df_view["공간구분"] == space_filter]
            if status_filter != "전체" and "상태" in df_view.columns:
                df_view = df_view[df_view["상태"] == status_filter]
            if only_unresolved and "상태" in df_view.columns:
                df_view = df_view[df_view["상태"].isin(["접수완료", "처리중"])]
            if show_mine and "작성자" in df_view.columns:
                df_view = df_view[df_view["작성자"] == st.session_state["user_name"]]
            if keyword:
                mask = df_view.astype(str).apply(lambda r: r.str.contains(keyword, case=False, na=False)).any(axis=1)
                df_view = df_view[mask]

            df_view = df_view.iloc[::-1]

            st.markdown(f"**검색 결과: `{len(df_view)}건`**")

            photo_col = "현장사진" if "현장사진" in df_view.columns else ("사진" if "사진" in df_view.columns else None)
            has_memo_col = "처리메모" in df_view.columns

            if view_mode == "📱 모바일 카드 보기":
                if df_view.empty:
                    st.info("조건에 맞는 요청 건이 없습니다.")
                else:
                    for _, row in df_view.iterrows():
                        r_status = str(row.get("상태", "접수완료")).strip()
                        r_dt = html.escape(str(row.get("일시", "-")))
                        r_space = html.escape(str(row.get("공간구분", "")))
                        r_det = html.escape(str(row.get("세부위치", "")))
                        r_cat = html.escape(str(row.get("분류", "-")))
                        r_user = html.escape(str(row.get("작성자", "-")))
                        r_desc = html.escape(str(row.get("상세내용", "-")))
                        r_photo_raw = str(row.get(photo_col, "")).strip() if photo_col else ""
                        r_memo_raw = str(row.get("처리메모", "")).strip() if has_memo_col else ""

                        photo_html = (
                            f'<div style="margin-top: 8px;"><a href="{html.escape(r_photo_raw)}" target="_blank" class="req-photo-link">📷 첨부사진 보기</a></div>'
                            if r_photo_raw.startswith("http") else ''
                        )
                        memo_html = (
                            f'<div class="req-card-memo">💬 <b>교무팀 처리메모:</b> {html.escape(r_memo_raw)}</div>'
                            if r_memo_raw else ''
                        )

                        card_html = f"""
                            <div class="req-card req-card-{html.escape(r_status)}">
                                <div class="req-card-header">
                                    <div><span style="font-size: 0.84rem; color: #64748b;">🗓️ {r_dt}</span></div>
                                    <div>{status_badge(r_status)}</div>
                                </div>
                                <div class="req-card-meta">
                                    📍 <b>위치:</b> {r_space} &rsaquo; {r_det} &nbsp;|&nbsp; 🏷️ <b>분류:</b> {r_cat} &nbsp;|&nbsp; 👤 <b>작성자:</b> {r_user}
                                </div>
                                <div class="req-card-body">{r_desc}</div>
                                {memo_html}
                                {photo_html}
                            </div>
                        """
                        st.markdown(card_html, unsafe_allow_html=True)
            else:
                if is_full_admin and "상태" in df_view.columns:
                    st.info("💡 **관리자 안내**: 표 안의 '상태' 또는 '처리메모' 셀을 더블 클릭하여 수정한 뒤, 아래 저장 버튼을 누르세요.")

                    editor_cols = list(df_view.columns)
                    editable_cols = ["상태"]
                    if has_memo_col:
                        editable_cols.append("처리메모")
                    disabled_cols = [c for c in editor_cols if c not in editable_cols]

                    column_cfg = {
                        "상태": st.column_config.SelectboxColumn("상태", options=STATUS_OPTIONS)
                    }
                    if has_memo_col:
                        column_cfg["처리메모"] = st.column_config.TextColumn("처리메모", width="large")
                    if photo_col:
                        column_cfg[photo_col] = st.column_config.LinkColumn(photo_col, display_text="📷 사진보기")

                    edited = st.data_editor(
                        df_view,
                        use_container_width=True,
                        hide_index=True,
                        disabled=disabled_cols,
                        column_config=column_cfg,
                        key="facility_editor"
                    )

                    if st.button("💾 상태 및 처리메모 변경사항 저장하기", use_container_width=True):
                        updates = []
                        changes = 0
                        status_col_num = list(df_f.columns).index("상태") + 1
                        status_col_letter = col_letter(status_col_num)

                        memo_col_letter = None
                        if has_memo_col:
                            memo_col_num = list(df_f.columns).index("처리메모") + 1
                            memo_col_letter = col_letter(memo_col_num)

                        for i in edited.index:
                            row_num = sheet_row_map.get(i, i + 2)

                            new_status = edited.loc[i, "상태"]
                            old_status = df_view.loc[i, "상태"]
                            if new_status != old_status:
                                updates.append({"range": f"{status_col_letter}{row_num}", "values": [[new_status]]})
                                changes += 1

                            if has_memo_col and memo_col_letter:
                                new_memo = str(edited.loc[i, "처리메모"]) if pd.notna(edited.loc[i, "처리메모"]) else ""
                                old_memo = str(df_view.loc[i, "처리메모"]) if pd.notna(df_view.loc[i, "처리메모"]) else ""
                                if new_memo != old_memo:
                                    updates.append({"range": f"{memo_col_letter}{row_num}", "values": [[new_memo]]})
                                    changes += 1

                        if updates:
                            with st.spinner("변경 사항을 서버에 저장 중입니다..."):
                                call_with_retry(lambda: ws_facility.batch_update(updates))
                            refresh_sheet_now("facility")
                            st.success(f"✅ 총 {changes}건의 변경사항이 정상적으로 업데이트되었습니다.")
                            st.rerun()
                        else:
                            st.warning("변경된 내용이 없습니다.")
                else:
                    column_cfg = {}
                    if photo_col:
                        column_cfg[photo_col] = st.column_config.LinkColumn(photo_col, display_text="📷 사진보기")

                    df_show = df_view.drop(columns=["요청ID"], errors="ignore").copy()
                    st.dataframe(df_show, use_container_width=True, hide_index=True, column_config=column_cfg)

            st.write("")
            st.download_button(
                "⬇️ 현재 목록 CSV 다운로드",
                df_view.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"시설요청현황_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv"
            )


# ==========================================
# 4. 재고 관리 (물품/비품 재고 관리)
# ==========================================
elif menu == "📦 물품/비품 재고 관리":
    def get_safe_inventory_df():
        try:
            records = get_inventory_records()
            return pd.DataFrame(records)
        except Exception:
            all_cols = ["일시", "구분", "작성자"] + ALL_SHEET_ITEMS + ["비고"]
            return pd.DataFrame(columns=all_cols)

    def get_current_calculated_stock():
        df_i = get_safe_inventory_df()
        current_stock = {item: 0.0 for item in ALL_SHEET_ITEMS}
        last_silsa_date = "없음"
        has_silsa_base = False

        if df_i.empty or "구분" not in df_i.columns:
            return current_stock, last_silsa_date, has_silsa_base

        df_work = df_i.copy()
        df_work["_orig_order"] = range(len(df_work))
        if "일시" in df_work.columns:
            df_work["_dt"] = pd.to_datetime(df_work["일시"], errors="coerce")
            df_work = df_work.sort_values(
                by=["_dt", "_orig_order"], kind="mergesort", na_position="first"
            ).reset_index(drop=True)

        df_silsa = df_work[df_work["구분"].astype(str).str.strip() == "실사"]
        if not df_silsa.empty:
            has_silsa_base = True
            last_silsa_idx = df_silsa.index[-1]
            last_silsa_date = str(df_work.loc[last_silsa_idx, "일시"]) if "일시" in df_work.columns else "없음"
            last_silsa_row = df_work.loc[last_silsa_idx]

            for item in ALL_SHEET_ITEMS:
                if item in df_work.columns:
                    current_stock[item] = float(pd.to_numeric(last_silsa_row.get(item, 0.0), errors="coerce") or 0.0)

            df_after = df_work.loc[last_silsa_idx + 1:]
            for item in ALL_SHEET_ITEMS:
                if item in df_after.columns:
                    add_vals = pd.to_numeric(df_after[item], errors="coerce").fillna(0.0).sum()
                    current_stock[item] += float(add_vals)
        else:
            for item in ALL_SHEET_ITEMS:
                if item in df_work.columns:
                    current_stock[item] = float(pd.to_numeric(df_work[item], errors="coerce").fillna(0.0).sum())

        return current_stock, last_silsa_date, has_silsa_base

    calc_stock, last_silsa_date, has_silsa = get_current_calculated_stock()

    low_count_preview = 0
    for item in CONSUMABLES:
        tot_p = calc_stock.get(f"{item} (2층)", 0.0) + calc_stock.get(f"{item} (6층)", 0.0) + calc_stock.get(f"{item} (7층)", 0.0)
        if tot_p <= get_threshold(item):
            low_count_preview += 1
    for item in EQUIPMENT:
        if calc_stock.get(item, 0.0) <= get_threshold(item):
            low_count_preview += 1

    stock_pill = f"🚨 발주필요 {low_count_preview}건" if low_count_preview > 0 else "✅ 전 품목 정상"
    render_hero(
        "📦 물품/비품 재고 통합 관리",
        "전산 재고와 연동된 일일 마감 실사, 일괄 입·출고 등록, 층별 재고 현황을 한눈에 확인하세요.",
        [f"🗓️ 최근 실사: {last_silsa_date}", stock_pill]
    )

    if is_full_admin:
        tab1, tab2, tab3 = st.tabs(["📝 마감 실사 등록", "📥 입·출고 내역 등록", "📊 재고 대시보드"])
    else:
        st.info("🔒 **조교 계정**은 '마감 실사 등록'과 '재고 대시보드' 조회가 가능합니다. 입/출고 등록은 교무팀 계정을 이용해 주세요.")
        tab1, tab3 = st.tabs(["📝 마감 실사 등록", "📊 재고 대시보드"])

    # 탭 1: 마감 재고 실사
    with tab1:
        with st.container(border=True):
            st.markdown("### 일일 마감 실사 등록")
            st.caption("※ 기본값은 낮 동안의 입·출고가 반영된 '현재 실시간 전산 재고'입니다. 실제 창고 수량과 다를 경우 해당 셀을 수정해 주세요.")
            now_str = get_kst_now()

            st.markdown(f"**작성 정보** &nbsp;|&nbsp; 🗓️ {now_str} &nbsp;|&nbsp; 👤 {html.escape(st.session_state['user_name'])} ({html.escape(st.session_state['user_role'])})")
            st.write("")

            def safe_float(val):
                try:
                    if pd.isna(val) or val is None or str(val).strip() == "":
                        return 0.0
                    return float(val)
                except (ValueError, TypeError):
                    return 0.0

            consumable_rows = []
            for item in CONSUMABLES:
                v2 = safe_float(calc_stock.get(f"{item} (2층)", 0.0))
                v6 = safe_float(calc_stock.get(f"{item} (6층)", 0.0))
                v7 = safe_float(calc_stock.get(f"{item} (7층)", 0.0))
                comp_total = v2 + v6 + v7

                consumable_rows.append({
                    "소모품 명": item,
                    "전산재고 (합계)": round(comp_total, 2),
                    "2층 수량": round(v2, 2),
                    "6층 수량": round(v6, 2),
                    "7층 수량": round(v7, 2),
                    "총 실사 수량": round(comp_total, 2)
                })

            df_c_input = pd.DataFrame(consumable_rows)

            st.markdown("#### 🧻 층별 소모품 실사")
            edited_c = st.data_editor(
                df_c_input,
                use_container_width=True,
                hide_index=True,
                disabled=["소모품 명", "전산재고 (합계)", "총 실사 수량"],
                column_config={
                    "소모품 명": st.column_config.TextColumn("소모품 명"),
                    "전산재고 (합계)": st.column_config.NumberColumn("전산재고 (합계)", format="%.2f", help="낮 동안의 입/출고가 반영된 실시간 전산 수량"),
                    "2층 수량": st.column_config.NumberColumn("2층 실사", min_value=0.0, step=0.1, default=0.0, format="%.2f"),
                    "6층 수량": st.column_config.NumberColumn("6층 실사", min_value=0.0, step=0.1, default=0.0, format="%.2f"),
                    "7층 수량": st.column_config.NumberColumn("7층 실사", min_value=0.0, step=0.1, default=0.0, format="%.2f"),
                    "총 실사 수량": st.column_config.NumberColumn("총 실사 수량 (합계)", format="%.2f")
                },
                key="c_silsa_editor"
            )

            edited_c["2층 수량"] = edited_c["2층 수량"].fillna(0.0)
            edited_c["6층 수량"] = edited_c["6층 수량"].fillna(0.0)
            edited_c["7층 수량"] = edited_c["7층 수량"].fillna(0.0)
            edited_c["총 실사 수량"] = edited_c["2층 수량"] + edited_c["6층 수량"] + edited_c["7층 수량"]

            st.markdown("---")
            st.markdown("#### 💻 공용 비품 및 기기 실사")

            equipment_rows = []
            for item in EQUIPMENT:
                curr_eq = float(calc_stock.get(item, 0.0))
                equipment_rows.append({
                    "비품 품목명": item,
                    "전산 수량": round(curr_eq, 2),
                    "현재 수량": round(curr_eq, 2)
                })

            df_e_input = pd.DataFrame(equipment_rows)

            edited_e = st.data_editor(
                df_e_input,
                use_container_width=True,
                hide_index=True,
                disabled=["비품 품목명", "전산 수량"],
                column_config={
                    "비품 품목명": st.column_config.TextColumn("비품 품목명"),
                    "전산 수량": st.column_config.NumberColumn("전산 수량", format="%.2f"),
                    "현재 수량": st.column_config.NumberColumn("실사 확인 수량", min_value=0.0, step=0.1, format="%.2f")
                },
                key="e_silsa_editor"
            )

            # 실시간 오차 및 부족 품목 미리보기
            diff_notes = []
            preview_low = []
            for _, r in edited_c.iterrows():
                comp_v = float(r["전산재고 (합계)"])
                real_v = float(r["총 실사 수량"])
                if abs(real_v - comp_v) > 1e-6:
                    diff_notes.append(f"{r['소모품 명']} ({comp_v:.2f}→{real_v:.2f})")
                if real_v <= get_threshold(r["소모품 명"]):
                    preview_low.append(r["소모품 명"])
            for _, r in edited_e.iterrows():
                comp_v = float(r["전산 수량"])
                real_v = float(r["현재 수량"])
                if abs(real_v - comp_v) > 1e-6:
                    diff_notes.append(f"{r['비품 품목명']} ({comp_v:.2f}→{real_v:.2f})")
                if real_v <= get_threshold(r["비품 품목명"]):
                    preview_low.append(r["비품 품목명"])

            if diff_notes:
                st.info(f"✏️ **전산 대비 수량 조정 ({len(diff_notes)}건)**: " + ", ".join(diff_notes[:8]) + (" ..." if len(diff_notes) > 8 else ""))
            if preview_low:
                st.warning(f"⚠️ **저장 시 두레이 발주 알림 예정 ({len(preview_low)}건)**: " + ", ".join(preview_low))

            st.write("")
            if st.button("📝 마감 실사 데이터 저장하기", use_container_width=True):
                sheet_values = {}
                low_stock_alerts = []

                for _, r in edited_c.iterrows():
                    item = r["소모품 명"]
                    q2 = float(r["2층 수량"])
                    q6 = float(r["6층 수량"])
                    q7 = float(r["7층 수량"])
                    tot_silsa = q2 + q6 + q7
                    sheet_values[f"{item} (2층)"] = q2
                    sheet_values[f"{item} (6층)"] = q6
                    sheet_values[f"{item} (7층)"] = q7

                    thresh = get_threshold(item)
                    if tot_silsa <= thresh:
                        low_stock_alerts.append(f"• {item}: 실사 {tot_silsa:.2f}개 (기준치: {thresh}개, 부족: {thresh - tot_silsa:.2f}개)")

                for _, r in edited_e.iterrows():
                    eq_item = r["비품 품목명"]
                    eq_q = float(r["현재 수량"])
                    sheet_values[eq_item] = eq_q

                    thresh = get_threshold(eq_item)
                    if eq_q <= thresh:
                        low_stock_alerts.append(f"• {eq_item}: 실사 {eq_q:.2f}개 (기준치: {thresh}개, 부족: {thresh - eq_q:.2f}개)")

                row = [now_str, "실사", st.session_state['user_name']]
                for item in ALL_SHEET_ITEMS:
                    row.append(sheet_values.get(item, 0.0))
                row.append("정기 마감 실사")

                with st.spinner("데이터를 서버에 동기화 중입니다..."):
                    call_with_retry(lambda: ws_inventory.append_row(row))
                    refresh_sheet_now("inventory")

                    if low_stock_alerts:
                        alert_text = (
                            f"🚨 [마감 재고 실사 알림 - 부족 품목 감지]\n"
                            f"• 일시: {now_str}\n"
                            f"• 실사 담당자: {st.session_state['user_name']}\n"
                            f"• 발주 필요 품목 리스트:\n" + "\n".join(low_stock_alerts)
                        )
                        alert_ok, alert_detail = send_dooray_alert(alert_text)
                        if get_dooray_webhook_info()[0]:
                            if alert_ok:
                                st.session_state["dooray_flash"] = ("ok", "부족 품목 두레이 알림이 발송되었습니다.")
                            else:
                                st.session_state["dooray_flash"] = ("warn", f"⚠️ 실사는 저장되었으나 두레이 부족 품목 알림 전송에 실패했습니다: {alert_detail}")

                st.success("✅ 오늘자 마감 실사 데이터가 정상적으로 저장되었습니다!")
                st.rerun()

    # 탭 2: 일괄 입고 및 출고 등록 (교무팀 전용)
    if is_full_admin:
        with tab2:
            with st.container(border=True):
                st.markdown("### 📥/📤 일괄 입고 및 출고 등록")
                st.caption("※ 여러 품목의 입고 또는 출고 변동 수량을 한 번에 입력하고 일괄 등록할 수 있습니다.")

                inout_type = st.radio("작업 구분", ["📥 입고 (재고 추가)", "📤 출고 (재고 차감/사용)"], horizontal=True)
                is_in = "입고" in inout_type
                action_label = "입고" if is_in else "출고"

                memo = st.text_input("비고/사유 (선택)", placeholder="예: 문구점 대량 구매, 2층 자습관 형광등 교체 등")
                st.write("")

                st.markdown("#### 🧻 소모품 변동 수량 입력 (0보다 큰 수량만 등록)")
                inout_c_rows = [
                    {
                        "소모품 명": item,
                        "2층 변동수량": 0.0,
                        "6층 변동수량": 0.0,
                        "7층 변동수량": 0.0
                    }
                    for item in CONSUMABLES
                ]
                df_inout_c = pd.DataFrame(inout_c_rows)

                edited_inout_c = st.data_editor(
                    df_inout_c,
                    use_container_width=True,
                    hide_index=True,
                    disabled=["소모품 명"],
                    column_config={
                        "소모품 명": st.column_config.TextColumn("소모품 명"),
                        "2층 변동수량": st.column_config.NumberColumn("2층 수량", min_value=0.0, step=0.1, default=0.0, format="%.2f"),
                        "6층 변동수량": st.column_config.NumberColumn("6층 수량", min_value=0.0, step=0.1, default=0.0, format="%.2f"),
                        "7층 변동수량": st.column_config.NumberColumn("7층 수량", min_value=0.0, step=0.1, default=0.0, format="%.2f"),
                    },
                    key="inout_c_editor"
                )

                st.markdown("---")
                st.markdown("#### 💻 비품/기기 변동 수량 입력 (0보다 큰 수량만 등록)")
                inout_e_rows = [{"비품 품목명": item, "변동수량": 0.0} for item in EQUIPMENT]
                df_inout_e = pd.DataFrame(inout_e_rows)

                edited_inout_e = st.data_editor(
                    df_inout_e,
                    use_container_width=True,
                    hide_index=True,
                    disabled=["비품 품목명"],
                    column_config={
                        "비품 품목명": st.column_config.TextColumn("비품 품목명"),
                        "변동수량": st.column_config.NumberColumn("변동 수량", min_value=0.0, step=0.1, default=0.0, format="%.2f")
                    },
                    key="inout_e_editor"
                )

                preview_changes = {}
                for _, r in edited_inout_c.iterrows():
                    item = r["소모품 명"]
                    v2 = float(r["2층 변동수량"]) if pd.notna(r["2층 변동수량"]) else 0.0
                    v6 = float(r["6층 변동수량"]) if pd.notna(r["6층 변동수량"]) else 0.0
                    v7 = float(r["7층 변동수량"]) if pd.notna(r["7층 변동수량"]) else 0.0
                    if v2 > 0: preview_changes[f"{item} (2층)"] = v2
                    if v6 > 0: preview_changes[f"{item} (6층)"] = v6
                    if v7 > 0: preview_changes[f"{item} (7층)"] = v7
                for _, r in edited_inout_e.iterrows():
                    item = r["비품 품목명"]
                    ve = float(r["변동수량"]) if pd.notna(r["변동수량"]) else 0.0
                    if ve > 0: preview_changes[item] = ve

                if preview_changes:
                    sign = "+" if is_in else "-"
                    summary_txt = ", ".join([f"{k} ({sign}{v:.2f})" for k, v in list(preview_changes.items())[:8]])
                    st.info(f"📦 **현재 입력된 {action_label} 품목 ({len(preview_changes)}건)**: {summary_txt}" + (" ..." if len(preview_changes) > 8 else ""))

                st.write("")
                btn_label = f"일괄 {action_label} 내역 등록하기"
                if st.button(btn_label, use_container_width=True):
                    if not preview_changes:
                        st.warning("⚠️ 입력된 변동 수량이 없습니다. 0보다 큰 수량을 하나 이상 입력해 주세요.")
                    else:
                        now_str = get_kst_now()
                        row_data = [now_str, action_label, st.session_state['user_name']]
                        for item in ALL_SHEET_ITEMS:
                            if item in preview_changes:
                                qty_val = preview_changes[item]
                                row_data.append(qty_val if is_in else -qty_val)
                            else:
                                row_data.append(0.0)
                        row_data.append(memo)

                        with st.spinner("내역을 기록하고 있습니다..."):
                            call_with_retry(lambda: ws_inventory.append_row(row_data))
                            refresh_sheet_now("inventory")
                        st.success(f"🎉 총 {len(preview_changes)}개 품목의 {action_label} 처리가 성공적으로 등록되었습니다!")
                        st.rerun()

    # 탭 3: 현황 및 누적 계산 (교무팀 및 조교 모두 열람 가능)
    if can_access_inventory:
        with tab3:
            df_i = get_safe_inventory_df()

            if df_i.empty:
                st.info("아직 등록된 재고 데이터가 없습니다.")
            else:
                consumable_totals = {}
                floor_comparison_data = []

                for item in CONSUMABLES:
                    q2 = calc_stock.get(f"{item} (2층)", 0.0)
                    q6 = calc_stock.get(f"{item} (6층)", 0.0)
                    q7 = calc_stock.get(f"{item} (7층)", 0.0)
                    total_q = q2 + q6 + q7
                    th = get_threshold(item)
                    consumable_totals[item] = total_q
                    floor_comparison_data.append({
                        "소모품명": item,
                        "2층 재고": round(q2, 2),
                        "6층 재고": round(q6, 2),
                        "7층 재고": round(q7, 2),
                        "총 합계": round(total_q, 2),
                        "최소 기준": th,
                        "상태": "🚨 발주필요" if total_q <= th else "✅ 정상"
                    })

                order_needed_list = []
                for item in CONSUMABLES:
                    tot = consumable_totals[item]
                    th = get_threshold(item)
                    if tot <= th:
                        order_needed_list.append({
                            "구분": "소모품",
                            "품목명": item,
                            "현재 보유량": round(tot, 2),
                            "최소 기준치": th,
                            "부족 수량(발주필요)": round(th - tot, 2)
                        })

                for item in EQUIPMENT:
                    eq_q = calc_stock.get(item, 0.0)
                    th = get_threshold(item)
                    if eq_q <= th:
                        order_needed_list.append({
                            "구분": "비품",
                            "품목명": item,
                            "현재 보유량": round(eq_q, 2),
                            "최소 기준치": th,
                            "부족 수량(발주필요)": round(th - eq_q, 2)
                        })

                df_order_needed = pd.DataFrame(order_needed_list)

                render_kpi_cards([
                    {"label": "소모품 종류", "value": f"{len(CONSUMABLES)}종", "color": "blue"},
                    {"label": "비품 종류", "value": f"{len(EQUIPMENT)}종", "color": "slate"},
                    {"label": "🚨 발주 필요 품목", "value": f"{len(df_order_needed)}건", "color": "red" if len(df_order_needed) > 0 else "green"},
                    {"label": "최근 실사 기준", "value": last_silsa_date.split(" ")[0] if last_silsa_date != "없음" else "없음", "sub": last_silsa_date if last_silsa_date != "없음" else "실사 미등록", "color": "amber"},
                ])

                if not has_silsa:
                    st.warning("⚠️ 등록된 '마감 실사' 데이터의 기준점이 없습니다. 전체 이력을 기준으로 단순 합산 표시 중입니다.")

                if not df_order_needed.empty:
                    pills = "".join([
                        f'<span class="low-stock-pill">{html.escape(str(r["품목명"]))} (보유: {r["현재 보유량"]:.2f})</span>'
                        for _, r in df_order_needed.iterrows()
                    ])
                    st.markdown(f"⚠️ **재고 부족 알림 (기준치 이하 품목)**<br>{pills}", unsafe_allow_html=True)
                    st.write("")

                    with st.expander("🛒 **[발주 필요 목록]** 상세 보기 및 다운로드", expanded=True):
                        st.dataframe(df_order_needed, use_container_width=True, hide_index=True)
                        st.download_button(
                            "⬇️ 발주 필요 목록 CSV 다운로드",
                            df_order_needed.to_csv(index=False).encode("utf-8-sig"),
                            file_name=f"발주필요목록_{datetime.now().strftime('%Y%m%d')}.csv",
                            mime="text/csv"
                        )
                else:
                    st.success("✅ 현재 기준치 이하로 부족한 품목이 없습니다. 모든 재고가 충분합니다.")

                st.write("")
                st.markdown("#### 🏢 층별 소모품 재고 현황 (2층 / 6층 / 7층 비교)")
                dash_item_filter = st.text_input("🔍 품목명 빠른 검색", placeholder="소모품 또는 비품 이름을 입력하세요 (예: A4, 생수, 노트북)", key="dash_item_search")

                df_floor_comp = pd.DataFrame(floor_comparison_data)
                if dash_item_filter:
                    df_floor_comp = df_floor_comp[df_floor_comp["소모품명"].str.contains(dash_item_filter, case=False, na=False)]
                st.dataframe(df_floor_comp, use_container_width=True, hide_index=True)

                st.write("")
                col1, col2 = st.columns(2, gap="large")
                with col1:
                    st.markdown("#### 📄 소모품 총 재고 (전체 합계)")
                    df_c_stock = pd.DataFrame([
                        {
                            "품목명": k,
                            "현재 보유량": round(v, 2),
                            "기준치": get_threshold(k),
                            "상태": "🚨 부족" if v <= get_threshold(k) else "✅ 정상"
                        }
                        for k, v in consumable_totals.items()
                    ])
                    if dash_item_filter:
                        df_c_stock = df_c_stock[df_c_stock["품목명"].str.contains(dash_item_filter, case=False, na=False)]
                    st.dataframe(df_c_stock, use_container_width=True, hide_index=True)

                with col2:
                    st.markdown("#### 💻 비품/기기 현재 재고")
                    df_e_stock = pd.DataFrame([
                        {
                            "품목명": k,
                            "현재 보유량": round(calc_stock.get(k, 0.0), 2),
                            "기준치": get_threshold(k),
                            "상태": "🚨 부족" if calc_stock.get(k, 0.0) <= get_threshold(k) else "✅ 정상"
                        }
                        for k in EQUIPMENT
                    ])
                    if dash_item_filter:
                        df_e_stock = df_e_stock[df_e_stock["품목명"].str.contains(dash_item_filter, case=False, na=False)]
                    st.dataframe(df_e_stock, use_container_width=True, hide_index=True)

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
                for meta_col in ("일시", "구분", "작성자", "비고"):
                    if meta_col in df_hist.columns:
                        df_hist[meta_col] = df_hist[meta_col].fillna("").astype(str)

                st.write("")
                st.dataframe(df_hist, use_container_width=True, hide_index=True)

                st.write("")
                st.download_button(
                    "⬇️ 조회된 이력 CSV 다운로드",
                    df_hist.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"재고변동이력_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv"
                )


# ==========================================
# 5. 사용자 권한 관리 (교무팀 전용)
# ==========================================
elif menu == "👥 사용자 권한 관리" and is_full_admin:
    render_hero(
        "👥 사용자 권한 및 알림 관리",
        "가입 직원의 직책 권한 관리, 비활성 계정 차단 및 두레이 웹훅 연동 상태를 점검하세요.",
        [f"🔑 교무팀 관리자: {st.session_state['user_name']}", f"📌 {APP_VERSION}"]
    )

    u_records, u_row_nums = get_users_records_with_rows()
    df_users_raw = pd.DataFrame(u_records)

    if not df_users_raw.empty and "분류" in df_users_raw.columns:
        roles_ser = df_users_raw["분류"].astype(str).str.strip()
        render_kpi_cards([
            {"label": "전체 가입자", "value": f"{len(df_users_raw)}명", "color": "slate"},
            {"label": "교무팀", "value": f"{int((roles_ser == '교무팀').sum())}명", "color": "blue"},
            {"label": "조교", "value": f"{int((roles_ser == '조교').sum())}명", "color": "amber"},
            {"label": "직원·강사", "value": f"{int(roles_ser.isin(['직원', '강사']).sum())}명", "color": "green"},
            {"label": "비활성 차단", "value": f"{int((roles_ser == '비활성').sum())}명", "color": "red"},
        ])

    with st.container(border=True):

        if df_users_raw.empty:
            st.info("등록된 사용자 정보가 없습니다.")
        else:
            u_sheet_row_map = {idx: u_row_nums[idx] for idx in range(len(u_row_nums))}
            st.markdown("### 📋 가입자 목록 및 권한 설정")
            st.info("💡 **안내**: '분류' 열을 더블 클릭하여 직책을 변경할 수 있습니다. `비활성`으로 변경된 계정은 즉시 시스템 로그인 및 자동 로그인이 차단됩니다.")

            user_search = st.text_input("🔍 이름 또는 전화번호 검색", placeholder="찾으시는 사용자 이름이나 연락처 일부를 입력하세요", key="user_mgmt_search")
            df_users_view = df_users_raw.copy()
            if user_search:
                u_mask = df_users_view.astype(str).apply(lambda r: r.str.contains(user_search, case=False, na=False)).any(axis=1)
                df_users_view = df_users_view[u_mask]

            user_cols = list(df_users_raw.columns)
            has_role_col = "분류" in user_cols

            if has_role_col:
                role_col_idx = user_cols.index("분류") + 1
                role_col_letter = col_letter(role_col_idx)

                disabled_cols = [c for c in user_cols if c != "분류"]
                edited_users = st.data_editor(
                    df_users_view,
                    use_container_width=True,
                    hide_index=True,
                    disabled=disabled_cols,
                    column_config={
                        "분류": st.column_config.SelectboxColumn(
                            "권한 분류",
                            options=["직원", "강사", "교무팀", "조교", "비활성"],
                            required=True
                        )
                    },
                    key="users_role_editor"
                )

                st.write("")
                if st.button("💾 사용자 권한 변경사항 저장하기", use_container_width=True):
                    batch_updates = []
                    changes = 0

                    for i in edited_users.index:
                        old_role = str(df_users_raw.loc[i, "분류"]).strip()
                        new_role = str(edited_users.loc[i, "분류"]).strip()
                        if old_role != new_role:
                            row_num = u_sheet_row_map.get(i, i + 2)
                            batch_updates.append({
                                "range": f"{role_col_letter}{row_num}",
                                "values": [[new_role]]
                            })
                            changes += 1

                    if batch_updates:
                        with st.spinner("사용자 권한을 저장하고 있습니다..."):
                            call_with_retry(lambda: ws_users.batch_update(batch_updates))
                            refresh_sheet_now("users")
                        st.success(f"✅ 총 {changes}명의 사용자 권한이 성공적으로 수정되었습니다.")
                        st.rerun()
                    else:
                        st.warning("변경된 내용이 없습니다.")
            else:
                st.warning("users 시트에 '분류' 컬럼이 존재하지 않습니다.")
                st.dataframe(df_users_view, use_container_width=True)


    # 두레이 웹훅 연동 상태 진단 및 테스트 발송 UI
    with st.container(border=True):
        st.markdown("### 🔔 두레이(Dooray) 웹훅 연동 상태 및 테스트")
        hook_url, hook_source = get_dooray_webhook_info()
        if hook_url:
            masked_url = f"{hook_url[:36]}...{hook_url[-6:]}" if len(hook_url) > 45 else hook_url
            st.success(f"✅ 두레이 웹훅이 연결되어 있습니다. (인식 위치: `{hook_source}`)")
            st.caption(f"등록된 웹훅 URL: `{masked_url}`")
            if st.button("📨 두레이 테스트 메시지 발송하기", key="test_dooray_btn", use_container_width=True):
                with st.spinner("두레이 채널로 테스트 메시지를 발송하고 있습니다..."):
                    test_ok, test_detail = send_dooray_alert(
                        f"🔔 [연동 테스트] 러셀대치 통합관리 시스템({APP_VERSION}) 두레이 웹훅 테스트 메시지입니다.\n"
                        f"• 발송 시각: {get_kst_now()} (KST)\n"
                        f"• 실행자: {st.session_state['user_name']}"
                    )
                if test_ok:
                    st.success(f"🎉 두레이 테스트 메시지 발송 성공! ({test_detail})")
                else:
                    st.error(f"❌ 두레이 발송 실패: {test_detail}")
        else:
            st.warning("⚠️ 현재 `dooray_webhook_url` 설정이 감지되지 않았습니다.")
            st.markdown("""
            **설정 방법 (Streamlit Cloud → Settings → Secrets 또는 구글 시트 `config` 탭):**
            1. Streamlit Secrets에 아래와 같이 추가한 뒤 앱을 **Reboot** 해 주세요:
            ```toml
            dooray_webhook_url = "https://hook.dooray.com/services/..."

            [gcp_service_account]
            ...
            ```
            2. 또는 `러셀대치_통합DB` 시트의 `config` 탭에 `카테고리 = dooray_webhook_url`, `항목값 = https://hook.dooray.com/services/...` 로 등록해도 즉시 적용됩니다.
            """)

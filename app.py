"""숨:ON — 학생을 위한 금연 동행 앱

배포 안내 (이 파일과 requirements.txt, 두 파일만 필요합니다)
1. GitHub 저장소에 app (5).py, requirements.txt를 업로드합니다. 학생 개인정보,
   실제 DB 파일, 접속 코드, Secrets는 절대로 GitHub에 올리지 마세요.
2. Streamlit Community Cloud에서 GitHub 저장소를 선택하고 main file을
   app (5).py로 지정한 뒤 배포합니다. 로컬 실행: streamlit run app (5).py
3. 영구 저장: Supabase/Neon 등의 PostgreSQL 데이터베이스를 만들고,
   Streamlit 앱 Settings > Secrets에 다음 값을 설정합니다.
   DATABASE_URL = "postgresql://USER:PASSWORD@HOST:PORT/DB?sslmode=require"
   APP_URL = "https://실제배포주소.streamlit.app"
   Supabase는 제공되는 pooler 연결 주소 사용을 권장합니다.
   값은 서비스가 발급한 실제 주소로 바꿔야 합니다. 암호화된 DB 연결을 사용하세요.
4. DATABASE_URL이 없으면 로컬 SQLite 체험 모드입니다. 클라우드에서는
   재시작/재배포로 SQLite 데이터가 사라질 수 있으므로 영구 저장으로 사용하지 마세요.
   DATABASE_URL이 잘못되면 SQLite로 몰래 전환하지 않고 오류를 표시합니다.
5. 앱의 '내 정보' 화면에서 APP_URL의 QR을 표시/다운로드할 수 있습니다.
   QR은 설치 파일이 아니라 웹앱 링크입니다. 스마트폰 카메라로 접속합니다.
6. 회원가입 입력은 학교·학번·이름뿐입니다. 가입 시 무작위 개인 접속 코드를
   발급합니다. 이 코드를 따로 보관하고 이후 로그인에 사용하세요.
   학교/학번/이름만으로 로그인시키지 않아 타인의 기록 조회를 방지합니다.
   코드 분실 시 자동 복구는 제공하지 않습니다. 로그아웃 후 재로그인 가능합니다.
7. 게스트 기록은 현재 세션만 유지됩니다. 가입 시 현재 체험 기록을 이어갑니다.
8. 운영 전 학교의 개인정보 수집 동의·보유기간·미성년자 관련 절차를 별도로
   확인하세요. 최소 정보만 수집하고 학교 승인 없이 학생의 실데이터를 모으지 마세요.
   이 앱은 상담/진료를 대체하지 않으며 담임·교사에게 기록을 자동 공유하지 않습니다.

DB 테이블은 최초 접속 시 자동 생성됩니다. 무료 DB/호스팅의 휴면·용량 정책은
각 서비스 조건을 따릅니다. DB 백업과 관리 권한 설정은 운영자가 수행해야 합니다.
"""
from __future__ import annotations

import copy
import hashlib
import html
import io
import json
import math
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlparse

import streamlit as st

# QR 기능의 선택 의존성이 누락되어도 전체 앱의 실행을 막지 않습니다.
try:
    import qrcode
except ImportError:
    qrcode = None

st.set_page_config(page_title="숨:ON | 금연 동행", page_icon="🌿", layout="centered", initial_sidebar_state="collapsed")
KST = ZoneInfo("Asia/Seoul")
SOURCE = "https://www.cdc.gov/tobacco/about/benefits-of-quitting.html"


def config(key):
    try:
        return str(st.secrets.get(key, os.getenv(key, ""))).strip()
    except Exception:
        return os.getenv(key, "").strip()


DB_URL = config("DATABASE_URL")
POSTGRES = bool(DB_URL)


def now():
    return datetime.now(KST)


def fresh():
    return {"start": now().isoformat(), "daily": 10, "price": 4500,
            "pack": 20, "reason": "내 몸과 미래를 위해", "logs": [], "checks": {}}


@contextmanager
def connection():
    if POSTGRES:
        import psycopg
        conn = psycopg.connect(DB_URL, connect_timeout=10)
    else:
        conn = sqlite3.connect("quit_on.sqlite3", timeout=15)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def sql(conn, query, args=()):
    return conn.execute(query.replace("?", "%s") if POSTGRES else query, args)


@st.cache_resource
def initialize_db():
    with connection() as conn:
        sql(conn, """CREATE TABLE IF NOT EXISTS quiton_users (
            id TEXT PRIMARY KEY, school TEXT NOT NULL, student TEXT NOT NULL,
            name TEXT NOT NULL, code_hash TEXT NOT NULL UNIQUE,
            state TEXT NOT NULL, created TEXT NOT NULL,
            UNIQUE(school, student))""")
    return True


def digest(code):
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


def checkpoint(label):
    st.session_state.pending_change = (label, copy.deepcopy(st.session_state.data))


def persist():
    if st.session_state.uid:
        try:
            with connection() as conn:
                sql(conn, "UPDATE quiton_users SET state=? WHERE id=?",
                    (json.dumps(st.session_state.data, ensure_ascii=False), st.session_state.uid))
        except Exception:
            st.error("저장하지 못했습니다. 연결을 확인하고 다시 저장해 주세요. 현재 화면의 기록은 세션에 남아 있습니다.")
            pending = st.session_state.pop("pending_change", None)
            if pending:
                st.session_state.data = pending[1]
            return False
    pending = st.session_state.pop("pending_change", None)
    if pending and pending[1] != st.session_state.data:
        st.session_state.undo_stack.append(pending)
        st.session_state.undo_stack = st.session_state.undo_stack[-20:]
        st.session_state.revision += 1
        st.session_state.notice = "저장했어요. ↶ 실행 취소로 되돌릴 수 있어요."
        st.rerun()
    return True


def escape(text):
    return html.escape(str(text))


def goto(page):
    if page != st.session_state.page:
        st.session_state.history.append(st.session_state.page)
        st.session_state.history = st.session_state.history[-30:]
    st.session_state.page = page
    st.rerun()


def go_back():
    st.session_state.page = st.session_state.history.pop() if st.session_state.history else "홈"
    st.rerun()


def undo_last():
    label, previous = st.session_state.undo_stack.pop()
    current = copy.deepcopy(st.session_state.data)
    st.session_state.data = previous
    if persist():
        st.session_state.revision += 1
        st.session_state.notice = f"{label} 취소했어요."
    else:
        st.session_state.data = current
        st.session_state.undo_stack.append((label, previous))
    st.rerun()


def elapsed_seconds(data):
    return max(0, (now() - datetime.fromisoformat(data["start"])).total_seconds())


def duration(seconds):
    total = max(0, int(seconds))
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{days}일 {hours:02d}시간 {minutes:02d}분 {seconds:02d}초"


MILESTONES = [
    (20 * 60, "20분", "심박수가 낮아지기 시작할 수 있어요.", "금연 후 수분 내에 시작되는 변화입니다. 20분은 앱의 초기 체크포인트입니다."),
    (86400, "24시간", "혈중 니코틴 수치가 0으로 내려갑니다.", "니코틴 대체제를 사용하지 않는 일반적인 경우의 설명입니다."),
    (3 * 86400, "며칠", "혈중 일산화탄소가 비흡연자 수준으로 감소합니다.", "‘며칠’을 앱에서 3일 체크포인트로 표시합니다. 정확한 도달일은 개인마다 다릅니다."),
    (30 * 86400, "1~12개월", "기침과 숨 가쁨이 줄어들 수 있어요.", "1개월은 회복 구간의 시작을 보여주는 체크포인트이며 완료 시점이 아닙니다."),
    (365 * 86400, "1~2년", "심장마비 위험이 크게 낮아집니다.", "연구에서 관찰되는 일반적인 회복 범위이며 개인의 위험을 측정한 값은 아닙니다."),
    (3 * 365 * 86400, "3~6년", "관상동맥질환의 추가 위험이 절반으로 줄어듭니다.", "비흡연자 대비 추가 위험에 대한 설명이며 전체 위험이 절반이라는 뜻은 아닙니다."),
    (5 * 365 * 86400, "5~10년", "구강·인후·후두암의 추가 위험이 절반으로 줄고 뇌졸중 위험이 낮아집니다.", "개인별 시점과 변화는 다를 수 있습니다."),
    (10 * 365 * 86400, "10~15년", "폐암의 추가 위험이 절반으로 줄어듭니다.", "10년은 이 회복 범위에 진입하는 체크포인트입니다."),
]

st.markdown("""<style>
:root{color-scheme:light;--ink:#193832;--mint:#217663;--muted:#637a73;}
.stApp{background:#eaf0ed;color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;}
header[data-testid="stHeader"]{background:transparent;}
.block-container{max-width:480px;min-height:100dvh;background:#f8faf8;padding:2.8rem 20px 110px;box-shadow:0 0 50px #183d3410;}
h1,h2,h3{color:var(--ink);letter-spacing:-.05em;}
h1{font-size:1.7rem!important;}h2{font-size:1.45rem!important;}h3{font-size:1.18rem!important;}
p{font-size:.94rem;line-height:1.55;word-break:keep-all;}
.logo{display:flex;align-items:center;gap:9px;height:46px;font-size:24px;font-weight:850;letter-spacing:-1.4px;color:#163f34;}
.logo-mark{display:grid;place-items:center;width:38px;height:38px;border-radius:13px;background:#d9eee2;font-size:24px;letter-spacing:0;}
.logo small{font-size:10px;letter-spacing:1.4px;font-weight:650;color:#6a7f74;display:block;line-height:12px;}
.hero{background:#174d3e;color:#fff;padding:26px 22px;border-radius:28px;margin:12px 0 18px;position:relative;overflow:hidden;}
.hero:after{content:'';position:absolute;right:-45px;top:-50px;width:170px;height:170px;border:24px solid #ffffff0b;border-radius:50%;pointer-events:none;}
.hero h2,.hero h3{color:#fff;position:relative;z-index:1;line-height:1.5;}
.hero p{color:#d6ece0;font-size:13px;margin:6px 0;}
.tag{font-size:10px;letter-spacing:2px;color:#bfdfc9;font-weight:600;}
.day-number{font-size:70px;line-height:1.1;font-weight:800;letter-spacing:-4px;margin-top:12px;}
.day-number small{font-size:20px;letter-spacing:0;font-weight:500;}
.card{background:white;border:1px solid #e2ebe4;padding:18px 20px;border-radius:22px;margin:12px 0;color:#213d35;}
.small{font-size:12px;color:#637a73;}
.card p{margin:8px 0 0;}
.stButton button,.stDownloadButton button,.stLinkButton a{border-radius:16px;min-height:48px;border-color:#dce8df;font-weight:650;box-shadow:none;}
.stButton button[kind="primary"],button[kind="primaryFormSubmit"]{background:#217663;border-color:#217663;color:#fff;}
[data-testid="stMetric"]{background:#fff;border:1px solid #e2ebe4;border-radius:22px;padding:16px 12px;}
[data-testid="stMetricLabel"]{color:#637a73;font-size:12px;}
[data-testid="stMetricValue"]{font-size:1.55rem!important;letter-spacing:-1px;}
[data-testid="stForm"]{border:1px solid #e2ebe4;border-radius:22px;background:#fff;padding:18px;}
[data-baseweb="input"],[data-baseweb="textarea"]{border-radius:12px!important;background:#f2f6f2!important;}
[data-testid="stCaptionContainer"] p{font-size:12px;color:#637a73;}
.st-key-actions button{min-height:34px;font-size:12px;background:transparent;border:0;color:#637a73;}
.st-key-topbar button{min-height:40px;font-size:13px;}
.st-key-bottom_nav{position:fixed!important;bottom:0;left:50%;transform:translateX(-50%);width:min(480px,100%);background:#fffffff5;backdrop-filter:blur(16px);z-index:999;padding:10px 10px max(12px,env(safe-area-inset-bottom));border-top:1px solid #e2ebe4;box-shadow:0 -8px 26px #183d3408;}
.st-key-bottom_nav button{border:0;background:transparent;min-height:52px;padding:4px 0;border-radius:15px;}
.st-key-bottom_nav button p{font-size:12px!important;white-space:pre-line;text-align:center;line-height:1.7;}
.st-key-bottom_nav button[kind="primary"]{color:#17614a;background:#e6f2e9;}
[data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;gap:10px;}
[data-testid="stHorizontalBlock"]>[data-testid="stColumn"]{min-width:0!important;flex:1 1 0!important;width:0!important;}
@media(max-width:480px){.block-container{padding:2.4rem 16px 110px;box-shadow:none;}.day-number{font-size:62px;}.hero{padding:24px 20px;}[data-testid="stHorizontalBlock"]{gap:8px;}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;}}
</style>""", unsafe_allow_html=True)

for key, value in {"uid": None, "profile": None, "data": fresh(), "page": "홈", "db_ok": False, "history": [], "undo_stack": [], "revision": 0}.items():
    if key not in st.session_state:
        st.session_state[key] = value
try:
    initialize_db()
    st.session_state.db_ok = True
except Exception:
    st.session_state.db_ok = False
    st.warning("저장소에 연결할 수 없습니다. 게스트 체험은 가능하지만 가입·로그인·영구 저장은 연결 복구 후 이용해 주세요.")

profile = st.session_state.profile
data = st.session_state.data
page = st.session_state.page
with st.container(key="topbar"):
    brand, account = st.columns([3, 1])
    brand.markdown('<div class="logo"><span class="logo-mark">❧</span><div>숨:ON<small>ONE MORE BREATH</small></div></div>', unsafe_allow_html=True)
    if account.button("내 계정" if profile else "로그인", use_container_width=True, key="account_top"):
        goto("계정")
with st.container(key="actions"):
    back, undo = st.columns(2)
    if back.button("‹ 뒤로가기", disabled=not st.session_state.history, use_container_width=True):
        go_back()
    if undo.button("↶ 실행 취소", disabled=not st.session_state.undo_stack, use_container_width=True, help="최근 저장한 설정·실천·마음 기록을 되돌려요. 최대 20회, 현재 로그인 세션에서만 가능해요."):
        undo_last()
if st.session_state.get("notice"):
    st.success(st.session_state.pop("notice"))

if page == "홈":
    st.caption(f"{profile['name']} 님, 오늘도 가볍게 시작해요." if profile else "오늘은 어제보다 가벼운 숨.")
    days = int(elapsed_seconds(data) // 86400)
    st.markdown(f'<div class="hero"><div class="tag">MY SMOKE-FREE JOURNEY</div><div class="day-number">{days}<small> 일째</small></div><h2>금연, 잘하고 있어요.</h2><p>오늘의 작은 선택이 내일의 나를 바꿔요.</p></div>', unsafe_allow_html=True)
    if st.button("지금 금연 현황 보기 →", type="primary", use_container_width=True):
        goto("현황")
    a, b = st.columns(2)
    if a.button("🌊 5분 버티기", use_container_width=True):
        goto("실천")
    if b.button("💚 몸의 변화", use_container_width=True):
        goto("회복")
    st.markdown(f'<div class="card"><span class="small">MY REASON</span><p><b>{escape(data["reason"])}</b></p></div>', unsafe_allow_html=True)
    if st.button("⚙ 시작 시간 설정", use_container_width=True):
        goto("내 정보")
    if not profile:
        st.caption("가입 없이 체험 중 · 계속 보관하려면 로그인하세요.")

elif page == "현황":
    st.header("나의 금연 현황")

    @st.fragment(run_every="1s")
    def live_stats():
        d = st.session_state.data
        sec = elapsed_seconds(d)
        avoided = sec / 86400 * d["daily"]
        saving = avoided * d["price"] / d["pack"]
        st.markdown(f'<div class="hero"><div class="tag">SMOKE-FREE TIME</div><h3>{duration(sec)}</h3><p>시작 · {escape(datetime.fromisoformat(d["start"]).strftime("%Y.%m.%d %H:%M:%S"))} (한국 시간)</p></div>', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        c1.metric("피우지 않은 담배 · 추정", f"{math.floor(avoided):,}개비")
        c2.metric("절약한 금액 · 추정", f"₩{math.floor(saving):,}")
        st.caption("설정한 흡연량·가격 기준 추정치예요.")
        target = next((m for m in MILESTONES if sec < m[0]), None)
        if target:
            st.write(f"다음 체크포인트 · **{target[1]}**")
            st.progress(min(1.0, sec / target[0]))
            st.caption(f"남은 시간 {duration(target[0] - sec)} · 건강 측정값이 아닌 시간 기준 진행률")
        else:
            st.success("모든 시간 체크포인트를 지났어요. 오늘도 금연을 이어가요!")
    live_stats()
    st.subheader("최근 마음 기록")
    if not data["logs"]:
        st.caption("아직 기록이 없어요. 실천 화면에서 오늘의 기분을 남겨 보세요.")
    for entry in reversed(data["logs"][-5:]):
        st.markdown(f'<div class="card"><b>{escape(entry["time"])} · 욕구 {entry["urge"]}/10</b><p>{escape(entry["note"])}</p></div>', unsafe_allow_html=True)

elif page == "실천":
    st.header("지금, 5분만 함께해요")
    st.caption("카드 안을 스크롤해 나에게 맞는 방법을 골라요.")
    tips = [
        ("⏳ 5분만 미루기", "흡연 충동이 오면 바로 행동하지 않고 타이머를 켜 보세요. 자리를 바꾸거나 물을 마시며 잠시 기다려요."),
        ("💧 물 천천히 마시기", "물을 조금씩 마시며 입과 손의 습관을 바꿔 보세요."),
        ("🌬️ 편안하게 호흡하기", "편한 자세로 천천히 들이마시고 더 길게 내쉬어요. 어지러우면 중단하고 평소처럼 호흡하세요."),
        ("🚶 가볍게 움직이기", "가능한 환경에서 5~10분 걷거나 스트레칭해요. 흡연 장소는 피하세요."),
        ("🍬 대체 행동 준비하기", "무설탕 껌, 물병, 손으로 만질 작은 물건 등 나에게 맞는 대안을 준비해요."),
        ("🧭 유혹 상황 바꾸기", "식사 후 양치하기, 편의점 대신 다른 길 걷기 등 흡연과 연결된 일상 동선을 바꿔요."),
        ("🤝 도움 요청하기", "친구·보호자·보건교사에게 지금의 어려움을 말해요. 니코틴 제품이나 약은 스스로 시작하지 말고 의료진과 상담하세요."),
        ("🌱 다시 시작하기", "한 번 피웠다고 모든 노력이 사라지지 않아요. 원인을 적고 시작 시간을 다시 설정해요. 과거 마음 기록은 유지됩니다."),
    ]
    with st.container(height=360, border=True):
        for title, text in tips:
            st.markdown(f"#### {title}")
            st.write(text)
            st.divider()
    st.subheader("5분 버티기 도우미")
    left, right = st.columns(2)
    if left.button("▶ 5분 시작", use_container_width=True):
        st.session_state.timer_end = (now() + timedelta(minutes=5)).isoformat()
    if right.button("타이머 종료", use_container_width=True):
        st.session_state.pop("timer_end", None)

    @st.fragment(run_every="1s")
    def timer():
        end = st.session_state.get("timer_end")
        if end:
            remaining = max(0, int((datetime.fromisoformat(end) - now()).total_seconds()))
            if remaining:
                st.info(f"함께 버티는 중 · {remaining // 60:02d}:{remaining % 60:02d} · 물 한 모금, 천천히 호흡해요.")
            else:
                st.success("5분을 해냈어요! 지금의 나에게 칭찬 한마디를 남겨 주세요.")
    timer()
    st.subheader("오늘의 작은 약속")
    today = now().date().isoformat()
    saved = data["checks"].get(today, [])
    with st.form("daily_check"):
        choices = ["흡연 유혹을 한 번 미뤘어요", "물을 마시고 가볍게 움직였어요", "도움을 청하거나 나를 칭찬했어요"]
        checked = [x for i, x in enumerate(choices) if st.checkbox(x, value=x in saved, key=f"check_{today}_{i}_{st.session_state.revision}")]
        if st.form_submit_button("오늘의 실천 저장", use_container_width=True):
            checkpoint("오늘의 실천 저장을")
            data["checks"][today] = checked
            if persist():
                st.success("오늘의 실천을 저장했어요." if st.session_state.uid else "현재 게스트 세션에 저장했어요.")
    with st.form("journal", clear_on_submit=True):
        st.markdown("**마음 기록**")
        urge = st.slider("지금 흡연 욕구", 0, 10, 3)
        note = st.text_area("오늘의 한 줄", max_chars=500, placeholder="예: 식사 후 생각이 났지만 친구와 산책했어요.")
        if st.form_submit_button("마음 기록 남기기", use_container_width=True):
            if note.strip():
                checkpoint("마음 기록 저장을")
                data["logs"].append({"time": now().strftime("%Y.%m.%d %H:%M:%S"), "urge": urge, "note": note.strip()})
                data["logs"] = data["logs"][-300:]
                if persist():
                    st.success("마음 기록을 남겼어요.")
            else:
                st.warning("한 줄만 적어 주세요.")
    st.caption("한 계정당 최근 마음 기록 300개를 보관합니다.")

elif page == "회복":
    st.header("내 몸의 회복 여정")
    st.caption("일반적인 회복 정보 · 개인차가 있으며 진단 결과가 아니에요.")
    sec = elapsed_seconds(data)
    for threshold, label, title, detail in MILESTONES:
        passed = sec >= threshold
        with st.expander(f"{'✅' if passed else '○'} {label} · {title}", expanded=False):
            st.write(detail)
            st.caption("시간 체크포인트 도달" if passed else f"체크포인트까지 {duration(threshold-sec)}")
    st.link_button("건강 정보 출처 · 미국 CDC", SOURCE, use_container_width=True)
    st.info("흡연 욕구가 심하거나 금단 증상이 힘들면 보건교사·보건소·의료기관에 상담하세요. 흉통이나 심한 호흡곤란 등 응급 증상이 있으면 119에 도움을 요청하세요.")

elif page == "계정":
    st.header("내 계정" if profile else "반가워요 👋")
    if st.session_state.uid:
        st.success(f"{profile['school']} · {profile['student']} · {profile['name']} 님으로 로그인 중")
        if st.button("로그아웃", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
    else:
        st.caption("가입은 선택이에요. 로그인은 개인 접속 코드로 간편하게.")
        login, signup = st.tabs(["로그인", "선택 회원가입"])
        with login:
            with st.form("login"):
                code = st.text_input("개인 접속 코드", type="password", help="가입 때 받은 QON-으로 시작하는 코드를 입력하세요.")
                submit = st.form_submit_button("로그인", use_container_width=True, disabled=not st.session_state.db_ok)
                if submit:
                    try:
                        with connection() as conn:
                            row = sql(conn, "SELECT id,school,student,name,state FROM quiton_users WHERE code_hash=?", (digest(code),)).fetchone()
                        if row:
                            st.session_state.undo_stack = []
                            st.session_state.history = []
                            st.session_state.revision += 1
                            st.session_state.uid = row[0]
                            st.session_state.profile = dict(zip(["school", "student", "name"], row[1:4]))
                            st.session_state.data = json.loads(row[4])
                            st.session_state.pop("timer_end", None)
                            st.session_state.pop("new_code", None)
                            st.rerun()
                        else:
                            st.error("접속 코드가 일치하지 않습니다. 가입 시 보관한 코드를 확인하세요.")
                    except Exception:
                        st.error("로그인 저장소에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.")
        with signup:
            with st.form("signup"):
                school = st.text_input("학교", max_chars=80)
                student = st.text_input("학번", max_chars=30)
                name = st.text_input("이름", max_chars=40)
                consent = st.checkbox("학교·학번·이름과 금연 기록을 계정 유지 목적으로 저장하는 데 동의합니다. 탈퇴 시 삭제됩니다. (선택 가입)")
                registered = st.form_submit_button("현재 기록으로 가입하기", use_container_width=True, disabled=not st.session_state.db_ok)
                if registered:
                    if not all(x.strip() for x in [school, student, name]) or not consent:
                        st.warning("학교·학번·이름과 저장 동의를 확인해 주세요.")
                    else:
                        new_code = "QON-" + secrets.token_hex(16).upper()
                        uid = secrets.token_hex(16)
                        try:
                            with connection() as conn:
                                exists = sql(conn, "SELECT id FROM quiton_users WHERE school=? AND student=?", (school.strip(), student.strip())).fetchone()
                                if exists:
                                    st.error("해당 학교·학번은 이미 가입되어 있습니다. 기존 접속 코드로 로그인하세요.")
                                else:
                                    sql(conn, "INSERT INTO quiton_users (id,school,student,name,code_hash,state,created) VALUES (?,?,?,?,?,?,?)", (uid, school.strip(), student.strip(), name.strip(), digest(new_code), json.dumps(data, ensure_ascii=False), now().isoformat()))
                            if not exists:
                                st.session_state.undo_stack = []
                                st.session_state.revision += 1
                                st.session_state.uid = uid
                                st.session_state.profile = {"school": school.strip(), "student": student.strip(), "name": name.strip()}
                                st.session_state.new_code = new_code
                                st.rerun()
                        except Exception:
                            st.error("가입을 저장하지 못했습니다. 중복 가입 여부 또는 저장소 연결을 확인해 주세요.")
    if st.session_state.get("new_code"):
        st.warning("이 개인 접속 코드는 다시 보여드릴 수 없습니다. 지금 복사하거나 내려받아 안전한 곳에 보관하세요. 타인에게 공유하지 마세요.")
        st.code(st.session_state.new_code, language=None)
        st.download_button("개인 접속 코드 보관", st.session_state.new_code, "quiton-access-code.txt", "text/plain", use_container_width=True)
        if st.button("보관했어요 · 코드 숨기기"):
            del st.session_state.new_code
            st.rerun()

elif page == "내 정보":
    st.header("나의 설정")
    if not profile:
        st.caption("게스트 이용 중 · 기록은 현재 세션에만 남아요.")
    if not POSTGRES:
        st.caption("체험용 저장소 · 클라우드 영구 보관은 외부 DB 연결이 필요해요.")
    st.subheader("금연 시작")
    start = datetime.fromisoformat(data["start"]).astimezone(KST)
    with st.form("settings"):
        start_date = st.date_input("금연 시작 날짜 · 한국 시간", value=start.date(), min_value=datetime(1950, 1, 1).date(), max_value=now().date())
        start_time = st.time_input("금연 시작 시각 · 초 단위", value=start.time().replace(tzinfo=None), step=timedelta(seconds=1))
        daily = st.number_input("금연 전 하루 평균 흡연량 (개비)", 0, 200, int(data["daily"]))
        price = st.number_input("담배 한 갑 가격 (원)", 0, 100000, int(data["price"]), step=100)
        pack = st.number_input("한 갑의 개비 수", 1, 100, int(data["pack"]))
        reason = st.text_input("내가 금연하는 이유", value=data["reason"], max_chars=140)
        if st.form_submit_button("설정 저장", type="primary", use_container_width=True):
            proposed = datetime.combine(start_date, start_time).replace(tzinfo=KST)
            if proposed > now():
                st.error("미래 시각은 금연 시작 시각으로 저장할 수 없습니다.")
            else:
                checkpoint("시작·생활 설정 변경을")
                data.update(start=proposed.isoformat(), daily=int(daily), price=int(price), pack=int(pack), reason=reason.strip() or "내 몸과 미래를 위해")
                if persist():
                    st.success("설정을 저장했어요.")
    st.caption("다시 시작할 때 위의 시작 날짜·시각을 바꾸세요. 기존 마음 기록은 삭제하지 않습니다.")

    st.subheader("QR로 스마트폰에서 열기")
    app_url = config("APP_URL")
    if not app_url:
        app_url = st.text_input("배포된 앱의 공개 주소", placeholder="https://나의앱.streamlit.app", help="공유용 앱 주소만 입력하세요. 접속 코드나 개인정보가 포함된 주소를 쓰지 마세요.")
    parsed = urlparse(app_url)
    if app_url and parsed.scheme == "https" and parsed.netloc and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment:
        if qrcode is None:
            st.warning("앱은 정상 이용할 수 있지만 QR 생성 패키지가 설치되지 않았습니다. GitHub의 실행 파일과 같은 폴더에 정확한 이름의 requirements.txt를 올린 뒤 Streamlit 앱을 재시작하세요.")
            st.code("streamlit>=1.41,<2\npsycopg[binary]>=3.2,<4\nqrcode[pil]>=8.0,<9\nPillow>=10.4,<13", language="text")
            st.caption("설치가 끝날 때까지 아래 앱 주소를 복사하거나 링크로 접속할 수 있습니다. 외부 QR 서비스로 주소를 전송하지 않습니다.")
        else:
            try:
                img = qrcode.make(app_url)
                buffer = io.BytesIO()
                img.save(buffer, format="PNG")
                st.image(buffer.getvalue(), width=220, caption="휴대폰 카메라로 스캔하세요 · 개인정보 미포함")
                st.download_button("공유용 QR 내려받기", buffer.getvalue(), "quiton-qr.png", "image/png", use_container_width=True)
            except Exception:
                st.warning("QR 이미지를 생성하지 못했습니다. 아래 링크로 앱에 접속할 수 있습니다. requirements.txt의 qrcode[pil]과 Pillow 설치 상태를 확인하세요.")
        st.code(app_url, language=None)
        st.link_button("앱 주소 열기", app_url, use_container_width=True)
    elif app_url:
        st.warning("개인정보·쿼리·인증 정보가 없는 https 공개 주소를 입력하세요.")
    else:
        st.caption("GitHub → Streamlit 배포 후 발급된 주소를 입력하면 실제 접속 가능한 QR이 생성됩니다.")

    with st.expander("기록 내보내기와 개인정보"):
        st.write("기록은 로그인 계정 또는 현재 게스트 세션에만 연결됩니다. 교사·다른 학생에게 공개하지 않습니다. 계정 데이터는 DB에 저장되며, 운영자는 DB 접근 권한을 제한해야 합니다. 접속 코드는 원문 대신 해시로 저장합니다. 공용 기기에서는 꼭 로그아웃하세요.")
        st.download_button("나의 금연 기록 내보내기", json.dumps(data, ensure_ascii=False, indent=2), "quiton-my-records.json", "application/json", use_container_width=True)
        if st.session_state.uid:
            confirmed = st.checkbox("내 계정과 모든 금연 기록을 영구 삭제하는 데 동의합니다.")
            if st.button("회원 탈퇴 · 기록 삭제", disabled=not confirmed, use_container_width=True):
                try:
                    with connection() as conn:
                        sql(conn, "DELETE FROM quiton_users WHERE id=?", (st.session_state.uid,))
                except Exception:
                    st.error("삭제하지 못했습니다. 연결을 확인하고 다시 시도하세요.")
                else:
                    for key in list(st.session_state.keys()):
                        del st.session_state[key]
                    st.rerun()
    with st.expander("배포 방법 · GitHub / Streamlit"):
        st.write("1. app (5).py와 requirements.txt를 GitHub 저장소에 업로드합니다.\n2. Streamlit Community Cloud에서 저장소와 app (5).py를 선택하여 배포합니다.\n3. Settings → Secrets에 DATABASE_URL(외부 PostgreSQL)과 APP_URL(배포 주소)을 설정합니다.\n4. QR을 내려받아 공유합니다. 자세한 설정은 app (5).py 맨 위 설명을 확인하세요.")
        st.caption("코드만으로 외부 서비스 계정 생성과 실제 공개 배포를 대신할 수는 없습니다. 영구 저장은 외부 DB 연결 후 적용됩니다.")

with st.container(key="bottom_nav"):
    pages = [("⌂", "홈"), ("◷", "현황"), ("≈", "실천"), ("♡", "회복"), ("⚙", "내 정보")]
    columns = st.columns(5, gap="small")
    for col, (icon, label) in zip(columns, pages):
        title = "설정" if label == "내 정보" else label
        if col.button(f"{icon}\n{title}", key=f"nav_{label}", use_container_width=True, type="primary" if page == label else "secondary"):
            goto(label)

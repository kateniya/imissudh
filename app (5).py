"""숨:ON — 학생을 위한 금연 동행 앱

배포 안내 (이 파일과 requirements.txt, 두 파일만 필요합니다)
1. GitHub 저장소에 app.py, requirements.txt를 업로드합니다. 학생 개인정보,
   실제 DB 파일, 접속 코드, Secrets는 절대로 GitHub에 올리지 마세요.
2. Streamlit Community Cloud에서 GitHub 저장소를 선택하고 main file을
   app.py로 지정한 뒤 배포합니다. 로컬 실행: streamlit run app.py
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

import qrcode
import streamlit as st

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


def persist():
    if st.session_state.uid:
        try:
            with connection() as conn:
                sql(conn, "UPDATE quiton_users SET state=? WHERE id=?",
                    (json.dumps(st.session_state.data, ensure_ascii=False), st.session_state.uid))
        except Exception:
            st.error("저장하지 못했습니다. 연결을 확인하고 다시 저장해 주세요. 현재 화면의 기록은 세션에 남아 있습니다.")
            return False
    return True


def escape(text):
    return html.escape(str(text))


def goto(page):
    st.session_state.page = page
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
:root {color-scheme:light;}
.stApp {background:#f4f8f7;}
.block-container {max-width:850px;padding-top:1.7rem;padding-bottom:7rem;}
h1,h2,h3 {color:#153f38;letter-spacing:-.04em;}
.hero {background:linear-gradient(120deg,#123f37,#236e5b);color:white;padding:28px;border-radius:24px;margin:14px 0 22px;}
.hero h2,.hero h3 {color:white;margin:5px 0 10px;}
.hero p {color:#e3f4ee;margin:5px 0;}
.tag {font-size:12px;letter-spacing:.13em;color:#afe5cf;}
.card {background:white;border:1px solid #dce9e3;padding:18px;border-radius:18px;margin:10px 0; color:#213d35;}
.small {font-size:13px;color:#526c62;}
[data-testid="stMetric"] {background:white;border:1px solid #dce9e3;border-radius:16px;padding:14px;}
[data-testid="stMetricLabel"] {color:#425e54;}
.stButton button,.stDownloadButton button {border-radius:12px;min-height:44px;}
div[data-testid="stVerticalBlock"]:has(> div > div > div#bottom-nav) {
position:fixed;bottom:0;left:50%;transform:translateX(-50%);width:min(850px,100%);
background:#ffffff;z-index:999;padding:8px 12px max(10px,env(safe-area-inset-bottom));
border-top:1px solid #dce9e3;box-shadow:0 -4px 18px #143e3710;}
@media(max-width:600px){.block-container{padding-left:1rem;padding-right:1rem;} .hero{padding:21px;} [data-testid="stMetricValue"]{font-size:1.45rem;} }
</style>""", unsafe_allow_html=True)

for key, value in {"uid": None, "profile": None, "data": fresh(), "page": "홈", "db_ok": False}.items():
    if key not in st.session_state:
        st.session_state[key] = value
try:
    initialize_db()
    st.session_state.db_ok = True
except Exception:
    st.session_state.db_ok = False
    st.warning("저장소에 연결할 수 없습니다. 게스트 체험은 가능하지만 가입·로그인·영구 저장은 연결 복구 후 이용해 주세요.")

if not POSTGRES:
    st.caption("🧪 로컬 체험 저장소 · 클라우드 영구 보관은 DATABASE_URL 설정이 필요합니다.")

st.markdown("### 🌿 숨:ON")
profile = st.session_state.profile
st.caption(f"{profile['name']} 님의 금연 동행" if profile else "회원가입 없이 시작하는, 나를 위한 작은 변화")
data = st.session_state.data
page = st.session_state.page

if page == "홈":
    st.markdown('<div class="hero"><div class="tag">BREATHE BETTER · LIVE LIGHTER</div><h2>오늘의 한 번을 넘기면,<br>내일의 숨이 달라져요.</h2><p>작은 실천을 기록하고 나의 회복 시간을 함께 확인하세요.</p></div>', unsafe_allow_html=True)
    a, b = st.columns(2)
    if a.button("▶ 나의 금연 현황", use_container_width=True, type="primary"):
        goto("현황")
    if b.button("🌊 지금 흡연 욕구가 있어요", use_container_width=True):
        goto("실천")
    st.markdown(f'<div class="card"><b>내가 금연하는 이유</b><p>{escape(data["reason"])}</p><span class="small">의지가 약한 것이 아니에요. 도움을 받아도 괜찮아요.</span></div>', unsafe_allow_html=True)
    st.subheader("처음이라면 이렇게")
    st.write("① 내 정보에서 시작 날짜와 시간을 정해요. ② 실천 화면에서 오늘의 행동을 골라요. ③ 현황과 회복 화면에서 변화를 확인해요.")
    st.info("가입은 선택입니다. 게스트 기록은 현재 접속 세션에만 남습니다. 계속 보관하려면 내 정보에서 가입하고 개인 접속 코드를 보관하세요.")

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
        st.caption("가입 전 설정한 하루 흡연량 × 금연 경과일 기준 추정치입니다. 실제 금액과 다를 수 있습니다. 수명 증가량은 개인별로 추정하지 않습니다.")
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
    st.header("흡연 대신, 나를 돌보는 시간")
    st.caption("아래 카드 영역 안에서 스크롤하세요. 한 번에 하나만 실천해도 충분해요.")
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
        checked = [x for i, x in enumerate(choices) if st.checkbox(x, value=x in saved, key=f"check_{today}_{i}")]
        if st.form_submit_button("오늘의 실천 저장", use_container_width=True):
            data["checks"][today] = checked
            if persist():
                st.success("오늘의 실천을 저장했어요." if st.session_state.uid else "현재 게스트 세션에 저장했어요.")
    with st.form("journal", clear_on_submit=True):
        st.markdown("**마음 기록**")
        urge = st.slider("지금 흡연 욕구", 0, 10, 3)
        note = st.text_area("어떤 상황이었고, 무엇을 해봤나요?", max_chars=500, placeholder="예: 식사 후 생각이 났지만 친구와 산책했어요.")
        if st.form_submit_button("마음 기록 남기기", use_container_width=True):
            if note.strip():
                data["logs"].append({"time": now().strftime("%Y.%m.%d %H:%M:%S"), "urge": urge, "note": note.strip()})
                data["logs"] = data["logs"][-300:]
                if persist():
                    st.success("마음 기록을 남겼어요.")
            else:
                st.warning("한 줄만 적어 주세요.")
    st.caption("한 계정당 최근 마음 기록 300개를 보관합니다.")

elif page == "회복":
    st.header("내 몸의 회복 여정")
    st.warning("아래 내용은 일반적인 건강 정보입니다. 경과 시간만으로 내 몸의 회복이나 질병 위험을 진단할 수 없습니다. 개인차가 있으며 니코틴 제품 사용, 기존 질환 등에 따라 달라집니다.")
    sec = elapsed_seconds(data)
    for threshold, label, title, detail in MILESTONES:
        passed = sec >= threshold
        with st.expander(f"{'✅' if passed else '○'} {label} · {title}", expanded=passed):
            st.write(detail)
            st.caption("시간 체크포인트 도달" if passed else f"체크포인트까지 {duration(threshold-sec)}")
    st.link_button("건강 정보 출처 · 미국 CDC", SOURCE, use_container_width=True)
    st.info("흡연 욕구가 심하거나 금단 증상이 힘들면 보건교사·보건소·의료기관에 상담하세요. 흉통이나 심한 호흡곤란 등 응급 증상이 있으면 119에 도움을 요청하세요.")

elif page == "내 정보":
    st.header("내 정보와 시작 설정")
    if st.session_state.uid:
        st.success(f"{profile['school']} · {profile['student']} · {profile['name']} 님으로 로그인 중")
        if st.button("로그아웃", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
    else:
        st.caption("선택 가입 · 학교·학번·이름으로 가입하고, 발급받은 개인 접속 코드로 재로그인해요.")
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

    st.subheader("금연 시작과 생활 설정")
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
        img = qrcode.make(app_url)
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        st.image(buffer.getvalue(), width=220, caption="휴대폰 카메라로 스캔하세요 · 개인정보 미포함")
        st.download_button("공유용 QR 내려받기", buffer.getvalue(), "quiton-qr.png", "image/png", use_container_width=True)
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
        st.write("1. app.py와 requirements.txt를 GitHub 저장소에 업로드합니다.\n2. Streamlit Community Cloud에서 저장소와 app.py를 선택하여 배포합니다.\n3. Settings → Secrets에 DATABASE_URL(외부 PostgreSQL)과 APP_URL(배포 주소)을 설정합니다.\n4. QR을 내려받아 공유합니다. 자세한 설정은 app.py 맨 위 설명을 확인하세요.")
        st.caption("코드만으로 외부 서비스 계정 생성과 실제 공개 배포를 대신할 수는 없습니다. 영구 저장은 외부 DB 연결 후 적용됩니다.")

st.caption("숨:ON · 오늘도 한 번 더, 나를 위한 선택 🌿")
with st.container():
    st.markdown('<div id="bottom-nav"></div>', unsafe_allow_html=True)
    pages = [("🏠", "홈"), ("⏱", "현황"), ("🌊", "실천"), ("💚", "회복"), ("👤", "내 정보")]
    columns = st.columns(5, gap="small")
    for col, (icon, label) in zip(columns, pages):
        if col.button(f"{icon} {label}", key=f"nav_{label}", use_container_width=True, type="primary" if page == label else "secondary"):
            goto(label)

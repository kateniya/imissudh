"""케어포켓 — 모바일 간호조무사 업무 보조. 실행: streamlit run app.py"""
from __future__ import annotations

import html
import json
import math
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit

import streamlit as st

APP_NAME = "케어포켓"
SCHEMA_VERSION = 1
MAX_TASKS = 80
MAX_NOTES = 40


def now_kst():
    return datetime.now(ZoneInfo("Asia/Seoul"))


def default_tasks():
    return [
        {"id": uuid.uuid4().hex, "text": text, "group": group, "done": False}
        for text, group in [
            ("근무 인계 및 오늘의 지시 확인", "근무 시작"),
            ("손 위생 및 보호구 준비 확인", "근무 시작"),
            ("사용 물품·환경 상태 확인", "근무 중"),
            ("지시받은 보조 업무 완료 확인", "근무 중"),
            ("미완료 업무 담당자에게 전달", "근무 마무리"),
            ("물품 정리 및 인계 확인", "근무 마무리"),
        ]
    ]


def validate_url(value):
    value = value.strip()
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if parsed.scheme != "https" or not host or parsed.username or parsed.password:
            return None
        if host == "localhost" or host.startswith("127.") or "." not in host:
            return None
        if len(value) > 2048:
            return None
        return value
    except ValueError:
        return None


def parse_backup(raw):
    if len(raw) > 200_000:
        raise ValueError("200KB 이하 파일만 복원할 수 있어요.")
    obj = json.loads(raw)
    if not isinstance(obj, dict) or obj.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("케어포켓 백업 파일이 아니에요.")
    tasks, notes = obj.get("tasks"), obj.get("notes")
    if not isinstance(tasks, list) or not isinstance(notes, list):
        raise ValueError("업무 또는 인계 데이터 형식이 잘못됐어요.")
    if len(tasks) > MAX_TASKS or len(notes) > MAX_NOTES:
        raise ValueError("허용 개수를 초과했어요.")
    clean_tasks, clean_notes = [], []
    for t in tasks:
        if not isinstance(t, dict) or not isinstance(t.get("text"), str):
            raise ValueError("업무 데이터가 올바르지 않아요.")
        text = t["text"].strip()
        if not text or len(text) > 60 or type(t.get("done")) is not bool:
            raise ValueError("업무 내용 또는 완료 표시를 확인해 주세요.")
        group = t.get("group")
        if group not in ["근무 시작", "근무 중", "근무 마무리"]:
            raise ValueError("업무 분류가 올바르지 않아요.")
        clean_tasks.append(dict(id=uuid.uuid4().hex, text=text, group=group, done=t["done"]))
    for n in notes:
        if not isinstance(n, dict):
            raise ValueError("인계 형식이 잘못됐어요.")
        text, level = n.get("text"), n.get("level")
        if not isinstance(text, str) or not text.strip() or len(text) > 160:
            raise ValueError("인계는 1~160자로 작성해 주세요.")
        if level not in ["일반", "확인 필요"] or type(n.get("done")) is not bool:
            raise ValueError("인계 상태가 올바르지 않아요.")
        clean_notes.append(dict(id=uuid.uuid4().hex, text=text.strip(), level=level,
                                done=n["done"], time=str(n.get("time", ""))[:30]))
    day = obj.get("work_date", "")
    if not isinstance(day, str):
        raise ValueError("날짜 형식이 잘못됐어요.")
    datetime.strptime(day, "%Y-%m-%d")
    shift = obj.get("shift", "주간")
    if shift not in ["주간", "저녁", "야간"]:
        raise ValueError("근무 구분이 잘못됐어요.")
    return clean_tasks, clean_notes, day, shift


def export_backup(state):
    return json.dumps({"schema_version": SCHEMA_VERSION, "work_date": state.work_date,
                       "shift": state.shift, "tasks": state.tasks, "notes": state.notes},
                      ensure_ascii=False, indent=2).encode("utf-8")


def main():
    st.set_page_config(page_title="케어포켓 · 나의 근무 파트너", page_icon="🩺",
                       layout="centered", initial_sidebar_state="collapsed")
    st.markdown('''<style>
    :root{--ink:#17332f;--green:#087e70;--muted:#536c66}
    html,body,[class*="css"]{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
    .stApp{background:#f3f7f5;color:var(--ink)}
    header[data-testid="stHeader"]{background:transparent;height:0}
    #MainMenu,footer{visibility:hidden}
    .block-container{max-width:470px;padding:1.1rem 1rem 6.5rem!important}
    h1{font-size:1.65rem!important;letter-spacing:-.06em;padding-top:0!important}
    h2,h3{font-size:1.03rem!important;letter-spacing:-.035em}
    p,li,label{font-size:.88rem!important}
    .stCaption p{font-size:.76rem!important;color:var(--muted)}
    [data-testid="stVerticalBlock"]{gap:.65rem}
    .brand{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}
    .brand b{font-size:18px;letter-spacing:-.7px}.brand span{font-size:11px;color:#536c66}
    .hero{background:linear-gradient(130deg,#075e56,#0c8878);color:#fff;
       border-radius:24px;padding:22px 21px;margin-bottom:4px}
    .hero small{font-size:12px;color:#d7f4eb}.hero h1{color:#fff!important;margin:7px 0 1px}
    .hero p{color:#e1f4ed;margin:0;font-size:13px!important}
    .pill{display:inline-block;padding:5px 10px;border-radius:20px;background:#e2eee9;
       color:#245b4d;font-size:11px;margin-bottom:5px}
    .stats{display:grid;grid-template-columns:1fr 1fr;gap:10px}
    .stat{background:white;border:1px solid #e2ebe5;border-radius:18px;padding:14px}
    .stat span{font-size:12px;color:#536c66}.stat strong{display:block;font-size:25px;margin-top:2px}
    .mini{border:1px solid #dfe9e2;border-radius:16px;padding:12px 14px;background:white;
       font-size:13px;overflow-wrap:anywhere}.mini small{color:#536c66;font-size:11px}
    .stButton button,.stDownloadButton button{border-radius:12px;min-height:42px;font-weight:600}
    [data-testid="stForm"]{border-radius:18px;background:#fff;padding:12px}
    [data-testid="stExpander"]{background:#fff;border-radius:14px}
    .st-key-bottom{position:fixed;bottom:0;left:50%;transform:translateX(-50%);width:min(100%,470px);
      z-index:999;background:rgba(255,255,255,.98);border-top:1px solid #e0e9e4;
      padding:8px 10px calc(9px + env(safe-area-inset-bottom));box-shadow:0 -6px 25px #17332f09}
    .st-key-bottom [data-testid="stRadio"]>label{display:none}
    .st-key-bottom [role="radiogroup"]{display:flex!important;flex-wrap:nowrap!important;
       justify-content:space-between;gap:2px!important}
    .st-key-bottom [role="radiogroup"] label{margin:0!important;padding:9px 5px;border-radius:10px;
       flex:1;justify-content:center;min-width:0;background:#f2f7f4}
    .st-key-bottom [role="radiogroup"] label>div:first-child{display:none}
    .st-key-bottom [role="radiogroup"] label:has(input:checked){background:#d2f0e5;color:#075e56}
    .st-key-bottom [role="radiogroup"] p{font-size:12px!important;font-weight:700;white-space:nowrap}
    @media(max-width:360px){.block-container{padding-left:12px!important;padding-right:12px!important}
      .st-key-bottom [role="radiogroup"] p{font-size:11px!important}}

    /* Reference-led mobile home: mint header and two-by-two white action tiles. */
    *{box-sizing:border-box}
    .stApp{background:#f5f8f8}
    .block-container{max-width:430px;padding:1.15rem 20px 6rem!important}
    .brand{margin-bottom:8px}.brand b{font-size:16px}.brand span{font-size:9px;letter-spacing:1px}
    .welcome{padding:12px 3px 25px;color:white}
    .welcome span{font-size:11px;opacity:.92}
    .welcome h1{font-size:27px!important;line-height:1.3;letter-spacing:-1.1px;color:white!important;margin:10px 0 8px;padding:0!important}
    .welcome p{font-size:12px!important;color:#f1ffff;margin:0}
    .st-key-homegrid [data-testid="stHorizontalBlock"]{display:flex!important;flex-wrap:nowrap!important;gap:12px!important}
    .st-key-homegrid [data-testid="stColumn"]{width:calc(50% - 6px)!important;flex:1 1 0!important;min-width:0!important}
    .st-key-homegrid [data-testid="stVerticalBlock"]{gap:10px}
    .st-key-tile0,.st-key-tile1,.st-key-tile2,.st-key-tile3{background:white;border:1px solid #e9f1f0;border-radius:15px;
      padding:16px 12px 13px;min-height:151px;box-shadow:0 4px 12px #1a666509;position:relative}
    .st-key-homegrid .tile-icon{font-size:28px;height:38px;line-height:38px;font-family:Arial,sans-serif;margin-bottom:4px}
    .tile-icon.mint{color:#4aa5a0}.tile-icon.blue{color:#739eaf}
    .st-key-homegrid .stButton button{border:0;background:transparent;color:#263e42;padding:0;min-height:28px;justify-content:flex-start;box-shadow:none!important}
    .st-key-homegrid .stButton button p{font-size:15px!important;font-weight:750;letter-spacing:-.5px}
    .st-key-homegrid .stButton button:after{content:"";position:absolute;inset:0;border-radius:15px}
    .st-key-homegrid .stCaption p{font-size:10px!important;line-height:1.4;color:#7a8c8d;margin:0;word-break:keep-all}
    .st-key-homegrid .stButton button:hover{color:#278e8e;background:transparent}
    .st-key-homegrid .stButton button:focus-visible{outline:2px solid #258d89}
    .shift-strip{display:flex;align-items:center;justify-content:space-between;background:#e9f3f2;border-radius:14px;padding:13px 17px;margin-top:5px}
    .shift-strip small{font-size:11px;color:#678080;display:block}.shift-strip strong{font-size:22px;color:#244b4c;display:block;margin-top:2px}
    .shift-strip em{font-size:12px;font-style:normal;font-weight:500;color:#668080}
    .progress-ring{width:47px;height:47px;border-radius:50%;background:conic-gradient(#56b8b3 var(--progress),#d5e6e4 0);display:flex;align-items:center;justify-content:center}
    .progress-ring b{width:37px;height:37px;border-radius:50%;background:#e9f3f2;display:flex;align-items:center;justify-content:center;font-size:11px;color:#377271}
    .st-key-bottom{max-width:430px;border-radius:0;padding:8px 14px calc(10px + env(safe-area-inset-bottom));box-shadow:0 -3px 16px #294a4805}
    .st-key-bottom [role="radiogroup"] label{background:transparent!important;position:relative;padding:3px 7px!important;min-height:48px;color:#8b999b!important}
    .st-key-bottom [role="radiogroup"] label:has(input:checked){background:transparent!important;color:#287d7c!important}
    .st-key-bottom [role="radiogroup"] label:has(input:checked):after{content:"";position:absolute;top:0;left:40%;right:40%;height:2px;border-radius:4px;background:#54b9b4}
    .st-key-bottom [role="radiogroup"] p{white-space:pre-line!important;text-align:center;line-height:1.6;font-size:10px!important}
    @media(max-width:360px){.block-container{padding-left:15px!important;padding-right:15px!important}.welcome h1{font-size:24px!important}.st-key-homegrid .stCaption p{font-size:9px!important}.st-key-tile0,.st-key-tile1,.st-key-tile2,.st-key-tile3{padding:13px 10px;min-height:140px}}
    </style>''', unsafe_allow_html=True)
    s = st.session_state
    for k, v in {"tasks": default_tasks(), "notes": [], "work_date": now_kst().date().isoformat(),
                 "shift": "주간", "page": "홈", "task_page": 1, "note_page": 1}.items():
        if k not in s:
            s[k] = v
    def go(page):
        s.page = page
    def go_card(page, section):
        s.page = page
        if page == "설명서":
            s.help_section = section
    st.markdown('<div class="brand"><b>✚ 케어포켓</b><span>CARE POCKET</span></div>', unsafe_allow_html=True)
    if s.page == "홈":
        st.markdown('<style>.stApp{background:linear-gradient(180deg,#59c3c5 0px,#59c3c5 255px,#f5f8f8 255px)}.brand b,.brand span{color:white!important}</style>', unsafe_allow_html=True)
    # 먼저 생성해도 CSS로 하단 고정. 클릭 시 해당 실행에서 바로 화면이 전환됩니다.
    with st.container(key="bottom"):
        st.radio("화면 이동", ["홈", "업무", "인계", "설명서"], horizontal=True,
                 key="page", label_visibility="collapsed",
                 format_func=lambda x: {"홈": "⌂\n홈", "업무": "☑\n업무", "인계": "▤\n인계", "설명서": "ⓘ\n설명서"}[x])
    done = sum(t["done"] for t in s.tasks)
    total = len(s.tasks)
    pending_notes = sum(not n["done"] for n in s.notes)
    if s.work_date != now_kst().date().isoformat():
        st.caption(f"이전 기록 · {s.work_date} | 설명서 → 새 근무 시작")

    if s.page == "홈":
        percentage = round(done / total * 100) if total else 0
        st.markdown(f'<div class="welcome"><span>{html.escape(s.work_date)} · {html.escape(s.shift)} 근무</span>'
                    '<h1>오늘도 든든하게,<br>케어포켓</h1>'
                    '<p>필요한 업무를 한눈에 확인하세요.</p></div>', unsafe_allow_html=True)
        with st.container(key="homegrid"):
            for row in range(2):
                cols = st.columns(2, gap="small")
                cards = [
                    ("☑", "업무 체크", f"남은 업무 {total-done}개", "업무", "mint"),
                    ("▤", "인계 메모", f"확인할 메모 {pending_notes}개", "인계", "blue"),
                    ("↧", "기록 백업", "내 기록 안전하게 보관", "설명서", "blue"),
                    ("ⓘ", "사용 설명서", "처음이라면 확인해요", "설명서", "mint"),
                ]
                for col, i in zip(cols, range(row*2,row*2+2)):
                    icon, title, detail, page, tone = cards[i]
                    with col:
                        with st.container(key=f"tile{i}"):
                            st.markdown(f'<div class="tile-icon {tone}">{icon}</div>', unsafe_allow_html=True)
                            st.button(title, key=f"home_action_{i}", on_click=go_card,
                                      args=(page, "백업 · 복원" if i == 2 else "빠른 사용법"),
                                      use_container_width=True)
                            st.caption(detail)
        st.markdown(f'<div class="shift-strip"><div><small>오늘의 업무</small><strong>{done}<em> / {total} 완료</em></strong></div>'
                    f'<div class="progress-ring" style="--progress:{percentage}%"><b>{percentage}%</b></div></div>', unsafe_allow_html=True)
        st.caption("개인 업무 보조용 · 환자 정보 입력 금지")

    elif s.page == "업무":
        st.title("업무 체크")
        group = st.segmented_control("분류", ["전체", "근무 시작", "근무 중", "근무 마무리"],
                                     default="전체", label_visibility="collapsed", key="task_group")
        group = group or "전체"
        filtered = [t for t in s.tasks if group == "전체" or t["group"] == group]
        page_count = max(1, math.ceil(len(filtered) / 4))
        s.task_page = min(s.task_page, page_count)
        st.caption(f"{done}/{total} 완료 · {s.task_page}/{page_count} 페이지")
        for t in filtered[(s.task_page-1)*4:s.task_page*4]:
            with st.container(border=True):
                a, b = st.columns([8, 1], vertical_alignment="center")
                checked = a.checkbox(t["text"], value=t["done"], key="task_"+t["id"])
                if checked != t["done"]:
                    t["done"] = checked
                    st.rerun()
                if b.button("×", key="delete_"+t["id"], help="업무 삭제"):
                    s.tasks = [x for x in s.tasks if x["id"] != t["id"]]
                    st.rerun()
        if not filtered:
            st.info("등록된 업무가 없어요.")
        if page_count > 1:
            a, b = st.columns(2)
            if a.button("← 이전", disabled=s.task_page <= 1, use_container_width=True):
                s.task_page -= 1
                st.rerun()
            if b.button("다음 →", disabled=s.task_page >= page_count, use_container_width=True):
                s.task_page += 1
                st.rerun()
        with st.expander("＋ 업무 추가"):
            with st.form("add_task", clear_on_submit=True):
                text = st.text_input("할 일", max_chars=60, placeholder="예: 소모품 재고 확인")
                category = st.selectbox("분류", ["근무 시작", "근무 중", "근무 마무리"])
                if st.form_submit_button("추가", use_container_width=True):
                    if not text.strip():
                        st.warning("할 일을 입력해 주세요.")
                    elif len(s.tasks) >= MAX_TASKS:
                        st.warning("업무는 최대 80개예요.")
                    else:
                        s.tasks.append(dict(id=uuid.uuid4().hex, text=text.strip(), group=category, done=False))
                        st.rerun()

    elif s.page == "인계":
        st.title("인계 메모")
        st.caption("물품·환경·미완료 업무만 · 환자 이름/병실/의료정보 금지")
        with st.expander("＋ 새 메모", expanded=not s.notes):
            with st.form("add_note", clear_on_submit=True):
                text = st.text_area("전달할 내용", max_chars=160, height=85,
                                    placeholder="예: 소모품 보충 요청 전달 필요")
                level = st.selectbox("상태", ["일반", "확인 필요"])
                if st.form_submit_button("메모 저장", type="primary", use_container_width=True):
                    if not text.strip():
                        st.warning("내용을 입력해 주세요.")
                    elif len(s.notes) >= MAX_NOTES:
                        st.warning("메모는 최대 40개예요.")
                    else:
                        s.notes.insert(0, dict(id=uuid.uuid4().hex, text=text.strip(), level=level,
                                              done=False, time=now_kst().strftime("%m/%d %H:%M")))
                        st.rerun()
        pages = max(1, math.ceil(len(s.notes)/3))
        s.note_page = min(s.note_page, pages)
        for n in s.notes[(s.note_page-1)*3:s.note_page*3]:
            with st.container(border=True):
                st.caption(f'{n["time"]} · {n["level"]}')
                st.write(n["text"])
                a, b = st.columns([3, 1])
                confirmed = a.checkbox("전달 확인", value=n["done"], key="note_"+n["id"])
                if confirmed != n["done"]:
                    n["done"] = confirmed
                    st.rerun()
                if b.button("삭제", key="nd_"+n["id"]):
                    s.notes = [x for x in s.notes if x["id"] != n["id"]]
                    st.rerun()
        if not s.notes:
            st.info("전달할 업무를 짧게 기록해 보세요.")
        if pages > 1:
            st.caption(f"{s.note_page}/{pages} 페이지")
            a, b = st.columns(2)
            if a.button("← 이전", disabled=s.note_page <= 1, use_container_width=True):
                s.note_page -= 1
                st.rerun()
            if b.button("다음 →", disabled=s.note_page >= pages, use_container_width=True):
                s.note_page += 1
                st.rerun()

    else:
        st.title("사용 설명서")
        section = st.selectbox("도움말", ["빠른 사용법", "백업 · 복원", "새 근무 시작", "안전 안내", "설치 방법"], key="help_section")
        if section == "빠른 사용법":
            st.markdown("**1 · 홈** 오늘의 진행 상황 확인\n\n**2 · 업무** 할 일 체크, 추가·삭제\n\n**3 · 인계** 업무 메모 작성 후 전달 확인\n\n**4 · 설명서** 백업·복원과 새 근무 준비")
            st.info("기록은 현재 접속 세션에서만 유지돼요. 종료·새로고침 전에 백업하세요.")
        elif section == "백업 · 복원":
            st.caption("자동 영구저장 없음 · 본인 기기에 파일로 보관")
            st.download_button("내 기록 백업 ↓", export_backup(s),
                               f"carepocket-{s.work_date}.json", "application/json", use_container_width=True)
            upload = st.file_uploader("백업 파일 복원", type=["json"])
            replace = st.checkbox("현재 기록이 백업 내용으로 교체됨을 확인했어요")
            if st.button("복원하기", disabled=not upload or not replace, use_container_width=True):
                try:
                    tasks, notes, day, shift = parse_backup(upload.getvalue())
                    s.tasks, s.notes, s.work_date, s.shift = tasks, notes, day, shift
                    s.task_page = s.note_page = 1
                    st.success("복원했어요. 하단 메뉴에서 기록을 확인하세요.")
                except (ValueError, TypeError, KeyError, UnicodeDecodeError, OverflowError):
                    st.error("복원 실패: 올바른 케어포켓 백업 파일인지 확인해 주세요.")
        elif section == "새 근무 시작":
            st.caption("진행 중인 기록을 먼저 백업하세요.")
            with st.form("new_shift"):
                day = st.date_input("근무일", value=now_kst().date())
                shift = st.selectbox("근무 시간대", ["주간", "저녁", "야간"])
                keep = st.checkbox("내 업무 목록 유지", value=True)
                confirm = st.checkbox("기존 완료 표시와 인계 메모를 지워도 괜찮아요")
                if st.form_submit_button("새 근무 시작", type="primary", use_container_width=True):
                    if not confirm:
                        st.warning("초기화 동의를 확인해 주세요.")
                    else:
                        s.tasks = [dict(t, done=False) for t in s.tasks] if keep else default_tasks()
                        s.notes = []
                        s.work_date, s.shift = day.isoformat(), shift
                        s.task_page = s.note_page = 1
                        for key in list(s.keys()):
                            if key.startswith(("task_", "note_")) and key not in ("task_page", "note_page", "task_group"):
                                del s[key]
                        st.success("새 근무를 준비했어요. 홈으로 이동하세요.")
        elif section == "안전 안내":
            st.markdown("- 개인 업무 보조용이며 전자의무기록이 아니에요.\n- 환자 이름·병실·연락처·진료정보를 입력하지 마세요.\n- 진단·투약·처치 판단을 제공하지 않아요.\n- 업무는 기관 지침과 담당 의료인의 지시를 따르세요.\n- 응급 상황은 앱이 아닌 기관 비상 대응 절차를 따르세요.")
            st.caption("알림 푸시·직원 간 실시간 공유·자동 저장 기능은 없어요.")
        else:
            st.markdown("**배포** GitHub에 app.py와 requirements.txt 업로드 → Streamlit Community Cloud에서 저장소 연결 → app.py 선택 → Deploy.\n\n**휴대폰 접속** 배포된 앱 주소를 휴대폰 브라우저에서 열어 주세요.\n\n**홈 화면** 휴대폰 브라우저의 ‘홈 화면에 추가’를 사용하세요.")
            st.caption("웹 바로가기이며 네이티브 앱·오프라인 앱은 아니에요.")


if __name__ == "__main__":
    main()

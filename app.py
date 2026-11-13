"""통합 영농 도우미 — 실행: streamlit run app.py"""
from __future__ import annotations

import io
import json
import uuid
from datetime import date, datetime
from urllib.parse import urlparse

import pandas as pd
import qrcode
import streamlit as st

st.set_page_config(page_title="통합 영농 도우미", page_icon="🌱", layout="wide")

# 사용자별 브라우저 연결 세션 안에서만 보관합니다. 전역 캐시/공유 파일을 사용하지 않습니다.
LOG_COLS = ["id", "날짜", "작물", "밭·시설", "작업", "비용", "수확량", "메모"]
TASK_COLS = ["id", "예정일", "작물", "할 일", "완료"]
VERSION = 1

def new_id():
    return str(uuid.uuid4())


def csv_bytes(rows, columns):
    return pd.DataFrame(rows, columns=columns).to_csv(index=False).encode("utf-8-sig")


def text_value(value, maximum=2000):
    if value is None:
        return ""
    return str(value).strip()[:maximum]


def validate_rows(rows, kind):
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ValueError("목록 형식이 아니거나 10,000건을 초과합니다.")
    clean = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("행의 형식이 올바르지 않습니다.")
        if kind == "logs":
            d = date.fromisoformat(str(row["날짜"]))
            cost, harvest = float(row["비용"]), float(row["수확량"])
            if not (0 <= cost <= 1e15 and 0 <= harvest <= 1e12):
                raise ValueError("비용·수확량은 유효한 0 이상의 숫자여야 합니다.")
            item = {"id": new_id(), "날짜": d.isoformat(), "작물": text_value(row["작물"], 100),
                    "밭·시설": text_value(row.get("밭·시설", ""), 100), "작업": text_value(row["작업"], 100),
                    "비용": cost, "수확량": harvest, "메모": text_value(row.get("메모", ""))}
            if not item["작물"] or not item["작업"]:
                raise ValueError("작물과 작업은 필수입니다.")
        else:
            d = date.fromisoformat(str(row["예정일"]))
            completed = row.get("완료", False)
            if not isinstance(completed, bool):
                if str(completed).lower() not in ("true", "false", "1", "0"):
                    raise ValueError("완료 값은 True 또는 False여야 합니다.")
                completed = str(completed).lower() in ("true", "1")
            item = {"id": new_id(), "예정일": d.isoformat(), "작물": text_value(row.get("작물", ""), 100),
                    "할 일": text_value(row["할 일"], 300), "완료": completed}
            if not item["할 일"]:
                raise ValueError("할 일은 필수입니다.")
        clean.append(item)
    return clean


for key, default in (("logs", []), ("tasks", [])):
    if key not in st.session_state:
        st.session_state[key] = default

st.title("🌱 통합 영농 도우미")
st.caption("영농일지 · 예상 수익 · 작업 체크리스트 · QR 접속")
st.info("기록은 현재 접속 세션에만 보관됩니다. 새로고침·연결 종료 시 사라질 수 있으니 사용 후 반드시 백업하세요. 다른 휴대폰과 자동 공유되지 않습니다.")

with st.sidebar:
    st.header("📦 백업·복원")
    backup = {"version": VERSION, "exported_at": datetime.now().isoformat(),
              "logs": st.session_state.logs, "tasks": st.session_state.tasks}
    st.download_button("전체 기록 백업 (JSON)", json.dumps(backup, ensure_ascii=False, indent=2).encode("utf-8"),
                       file_name=f"farm_backup_{date.today().isoformat()}.json", mime="application/json", use_container_width=True)
    st.download_button("영농일지 CSV 저장", csv_bytes(st.session_state.logs, LOG_COLS),
                       file_name="farm_logs.csv", mime="text/csv", use_container_width=True)
    st.download_button("작업 목록 CSV 저장", csv_bytes(st.session_state.tasks, TASK_COLS),
                       file_name="farm_tasks.csv", mime="text/csv", use_container_width=True)
    uploaded = st.file_uploader("전체 백업 JSON 복원", type=["json"])
    agree = st.checkbox("복원하면 현재 일지와 작업 목록이 교체됩니다.")
    if st.button("JSON 복원", disabled=uploaded is None or not agree):
        try:
            if uploaded.size > 5 * 1024 * 1024:
                raise ValueError("5MB 이하 파일만 가능합니다.")
            data = json.loads(uploaded.getvalue().decode("utf-8-sig"))
            if not isinstance(data, dict) or data.get("version") != VERSION:
                raise ValueError("지원하지 않는 백업 형식입니다.")
            logs = validate_rows(data["logs"], "logs")
            tasks = validate_rows(data["tasks"], "tasks")
            st.session_state.logs, st.session_state.tasks = logs, tasks
            st.rerun()
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            st.error(f"복원 실패: {exc}")
    st.divider()
    csv_kind = st.selectbox("CSV 가져오기 종류", ["영농일지", "작업 목록"])
    csv_file = st.file_uploader("이 앱에서 저장한 CSV 가져오기", type=["csv"])
    st.caption("CSV 가져오기는 선택한 종류의 현재 기록을 교체합니다. 먼저 JSON 백업을 권장합니다.")
    csv_agree = st.checkbox("선택한 종류의 기록 교체에 동의합니다.")
    if st.button("CSV 가져오기", disabled=csv_file is None or not csv_agree):
        try:
            if csv_file.size > 5 * 1024 * 1024:
                raise ValueError("5MB 이하 파일만 가능합니다.")
            frame = pd.read_csv(csv_file, encoding="utf-8-sig", keep_default_na=False)
            key = "logs" if csv_kind == "영농일지" else "tasks"
            st.session_state[key] = validate_rows(frame.to_dict("records"), key)
            st.rerun()
        except (ValueError, KeyError, TypeError, OverflowError, pd.errors.ParserError) as exc:
            st.error(f"CSV 가져오기 실패: {exc}")

home, diary, profit, tasks_tab, qr_tab = st.tabs(["🏠 현황", "📝 영농일지", "💰 수익 계산", "✅ 작업 관리", "📱 QR 접속"])

with home:
    st.subheader("나의 영농 현황")
    cols = st.columns(3)
    cols[0].metric("영농일지", f"{len(st.session_state.logs):,}건")
    cols[1].metric("기록 비용 합계", f"{sum(r['비용'] for r in st.session_state.logs):,.0f}원")
    pending = [r for r in st.session_state.tasks if not r["완료"]]
    cols[2].metric("남은 작업", f"{len(pending):,}건")
    st.caption("비용 합계는 필터와 무관한 전체 일지 기준입니다. 수확량 단위는 kg로 통일합니다.")
    st.markdown("#### 다가오는 작업")
    if pending:
        upcoming = pd.DataFrame(sorted(pending, key=lambda r: r["예정일"])[:10]).drop(columns="id")
        st.dataframe(upcoming, hide_index=True, use_container_width=True)
    else:
        st.success("남은 작업이 없습니다. 작업 관리에서 새 작업을 등록하세요.")
    st.markdown("#### 사용 순서")
    st.write("① 영농일지에 기록 → ② 작업 등록·완료 표시 → ③ 예상 수익 계산 → ④ JSON 백업")

with diary:
    st.subheader("영농일지 등록")
    with st.form("log_form", clear_on_submit=True):
        left, right = st.columns(2)
        log_date = left.date_input("작업 날짜", date.today())
        crop = right.text_input("작물 *", max_chars=100, placeholder="예: 고추")
        field = left.text_input("밭·시설", max_chars=100, placeholder="예: 1번 하우스")
        work = right.selectbox("작업 *", ["파종", "정식", "관수", "시비", "제초", "방제", "수확", "시설 관리", "기타"])
        cost = left.number_input("이 작업의 비용 (원)", min_value=0, max_value=1000000000000, step=1000)
        harvest = right.number_input("이 작업의 수확량 (kg)", min_value=0.0, max_value=1000000000.0, step=0.1)
        memo = st.text_area("메모", max_chars=2000, placeholder="작업 내용, 날씨 등을 적으세요.")
        if st.form_submit_button("일지 등록", use_container_width=True):
            if not crop.strip():
                st.error("작물을 입력해 주세요.")
            else:
                st.session_state.logs.append({"id": new_id(), "날짜": log_date.isoformat(), "작물": crop.strip(),
                    "밭·시설": field.strip(), "작업": work, "비용": cost, "수확량": harvest, "메모": memo.strip()})
                st.rerun()
    st.divider()
    st.subheader("일지 조회")
    if st.session_state.logs:
        df = pd.DataFrame(st.session_state.logs)
        crop_filter = st.selectbox("조회 작물", ["전체"] + sorted(df["작물"].unique().tolist()))
        a, b = st.columns(2)
        start = a.date_input("조회 시작일", date.fromisoformat(df["날짜"].min()))
        end = b.date_input("조회 종료일", max(date.today(), date.fromisoformat(df["날짜"].max())))
        if start > end:
            st.warning("시작일은 종료일보다 늦을 수 없습니다.")
        else:
            filtered = df[(df["날짜"] >= start.isoformat()) & (df["날짜"] <= end.isoformat())]
            if crop_filter != "전체":
                filtered = filtered[filtered["작물"] == crop_filter]
            filtered = filtered.sort_values("날짜", ascending=False)
            st.dataframe(filtered.drop(columns="id"), hide_index=True, use_container_width=True)
            st.caption(f"조회 {len(filtered):,}건 · 비용 {filtered['비용'].sum():,.0f}원 · 수확량 {filtered['수확량'].sum():,.1f}kg")
            st.download_button("조회 결과 CSV", filtered.drop(columns="id").to_csv(index=False).encode("utf-8-sig"),
                               "filtered_logs.csv", "text/csv")
        with st.expander("일지 한 건 삭제"):
            lookup = {r["id"]: f"{r['날짜']} | {r['작물']} | {r['작업']} | {r['id'][:8]}" for r in st.session_state.logs}
            delete_id = st.selectbox("삭제할 일지", list(lookup), format_func=lookup.get)
            confirm = st.checkbox("선택한 일지를 삭제합니다.")
            if st.button("선택 일지 삭제", disabled=not confirm):
                st.session_state.logs = [r for r in st.session_state.logs if r["id"] != delete_id]
                st.rerun()
    else:
        st.info("등록된 일지가 없습니다.")

with profit:
    st.subheader("예상 수익 계산기")
    st.caption("입력값 기반의 단순 추정이며 세금·감가상각·금융비용 등은 입력한 경우에만 반영됩니다. 시세를 자동 조회하지 않습니다.")
    a, b = st.columns(2)
    quantity = a.number_input("예상 판매량 (kg)", min_value=0.0, max_value=1000000000.0, value=1000.0, step=10.0)
    price = b.number_input("kg당 판매 가격 (원)", min_value=0.0, max_value=1000000000.0, value=3000.0, step=100.0)
    use_logs = st.checkbox("전체 영농일지 비용을 기본 비용으로 사용")
    if use_logs:
        base = float(sum(r["비용"] for r in st.session_state.logs))
        st.info(f"전체 일지 비용 {base:,.0f}원을 사용합니다. 작물·기간 구분 없이 전체 기록이 포함됩니다.")
    else:
        materials = a.number_input("종자·비료·자재비 (원)", min_value=0.0, max_value=1e12, step=1000.0)
        labor = b.number_input("인건비 (원)", min_value=0.0, max_value=1e12, step=1000.0)
        facility = a.number_input("임차·시설·장비비 (원)", min_value=0.0, max_value=1e12, step=1000.0)
        base = materials + labor + facility
    other = b.number_input("추가 비용 (원)", min_value=0.0, max_value=1e12, step=1000.0,
                           help="운송·수수료·세금 등. 이미 포함한 비용을 중복 입력하지 마세요.")
    revenue = quantity * price
    total = base + other
    net = revenue - total
    a, b, c = st.columns(3)
    a.metric("예상 매출", f"{revenue:,.0f}원")
    b.metric("총비용", f"{total:,.0f}원")
    c.metric("예상 순수익", f"{net:,.0f}원")
    st.write(f"매출 대비 수익률: {net / revenue * 100:,.1f}%" if revenue > 0 else "매출 대비 수익률: 매출이 0원이므로 계산할 수 없습니다.")
    st.write(f"손익분기 판매 단가: {total / quantity:,.0f}원/kg" if quantity > 0 else "손익분기 판매 단가: 판매량이 0kg이므로 계산할 수 없습니다.")
    if net < 0:
        st.warning("현재 가정에서는 비용이 매출보다 큽니다.")
    result = [{"판매량_kg": quantity, "판매단가_원": price, "예상매출_원": revenue,
               "총비용_원": total, "예상순수익_원": net}]
    st.download_button("계산 결과 CSV", pd.DataFrame(result).to_csv(index=False).encode("utf-8-sig"),
                       "profit_estimate.csv", "text/csv")
    st.caption("계산기 입력값은 전체 JSON 백업에 포함되지 않습니다. 계산 결과 CSV를 별도로 저장하세요.")

with tasks_tab:
    st.subheader("작업 체크리스트")
    with st.form("task_form", clear_on_submit=True):
        due = st.date_input("작업 예정일", date.today())
        task_crop = st.text_input("대상 작물", max_chars=100)
        title = st.text_input("할 일 *", max_chars=300, placeholder="예: 1번 하우스 관수 상태 확인")
        if st.form_submit_button("작업 추가", use_container_width=True):
            if not title.strip():
                st.error("할 일을 입력해 주세요.")
            else:
                st.session_state.tasks.append({"id": new_id(), "예정일": due.isoformat(),
                    "작물": task_crop.strip(), "할 일": title.strip(), "완료": False})
                st.rerun()
    if st.session_state.tasks:
        only_pending = st.checkbox("미완료 작업만 표시")
        for task in sorted(st.session_state.tasks, key=lambda r: (r["완료"], r["예정일"])):
            if only_pending and task["완료"]:
                continue
            overdue = not task["완료"] and task["예정일"] < date.today().isoformat()
            label = f"{'⏰ 지연 | ' if overdue else ''}{task['예정일']} | {task['작물'] or '공통'} | {task['할 일']}"
            left, right = st.columns([6, 1])
            state = left.checkbox(label, value=task["완료"], key=f"done_{task['id']}")
            if state != task["완료"]:
                task["완료"] = state
                st.rerun()
            if right.button("삭제", key=f"delete_{task['id']}"):
                st.session_state.tasks = [r for r in st.session_state.tasks if r["id"] != task["id"]]
                st.rerun()
        st.caption("작업 삭제는 즉시 반영됩니다. 중요한 기록은 먼저 백업하세요.")
    else:
        st.info("작업을 추가하면 완료 체크를 할 수 있습니다.")

with qr_tab:
    st.subheader("스마트폰 QR 접속")
    st.write("Streamlit 배포 완료 후 실제 앱 주소를 입력하세요. 생성된 QR을 휴대폰 카메라로 스캔하면 앱이 열립니다.")
    st.caption("QR에는 앱 주소만 들어갑니다. 현재 사용자의 일지·작업 기록은 포함되거나 공유되지 않습니다.")
    url = st.text_input("배포된 앱 URL", placeholder="https://내앱이름.streamlit.app")
    if url.strip():
        target = url.strip()
        try:
            parsed = urlparse(target)
            valid = parsed.scheme in ("https", "http") and bool(parsed.hostname) and not parsed.username and not any(c.isspace() for c in target)
        except ValueError:
            valid = False
        if not valid or len(target) > 2000:
            st.error("http:// 또는 https://로 시작하는 올바른 앱 주소를 입력해 주세요. 주소는 2,000자 이하여야 합니다.")
        else:
            qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=4)
            qr.add_data(target)
            qr.make(fit=True)
            image = qr.make_image(fill_color="black", back_color="white")
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            png = buffer.getvalue()
            st.image(png, caption="휴대폰 카메라로 스캔하세요.", width=280)
            st.link_button("앱 주소 열기", target)
            st.download_button("QR 이미지 다운로드", png, "farm_app_qr.png", "image/png")
    st.warning("localhost·127.0.0.1 주소는 다른 휴대폰에서 접속할 수 없습니다. 배포된 공개 주소를 사용하세요. 비공개 앱은 접속 권한이 필요합니다.")

st.divider()
st.caption("통합 영농 도우미 | 단위: 원·kg | 농약·비료 사용 처방을 제공하지 않습니다. 개인정보를 기록하지 마세요.")

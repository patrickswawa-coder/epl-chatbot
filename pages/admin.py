"""관리자 화면: 처리 기록 확인 (비밀번호 필요). 주소: /admin"""
import hashlib
import hmac
import os
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from query_logger import error_counts, read_logs  # noqa: E402
from theme import apply_theme  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

st.set_page_config(page_title="관리자 · 처리 기록", page_icon="🛠️", layout="wide")
apply_theme()
st.page_link("app.py", label="챗봇으로 돌아가기")
st.title("관리자 · 처리 기록")


def _same(a: str, b: str) -> bool:
    salt = b"epl-admin"
    ha = hashlib.pbkdf2_hmac("sha256", a.encode(), salt, 100_000)
    hb = hashlib.pbkdf2_hmac("sha256", b.encode(), salt, 100_000)
    return hmac.compare_digest(ha, hb)


expected = os.getenv("ADMIN_PASSWORD", "")
if not expected:
    st.warning(".env 파일에 ADMIN_PASSWORD=원하는비밀번호 를 추가한 뒤 다시 실행하세요.")
    st.stop()

if not st.session_state.get("admin_ok"):
    pw = st.text_input("관리자 비밀번호", type="password")
    if pw:
        if _same(pw, expected):
            st.session_state.admin_ok = True
            st.rerun()
        else:
            st.error("비밀번호가 맞지 않습니다.")
    st.stop()

cols, rows = read_logs(500)
if not rows:
    st.info("아직 처리 기록이 없습니다. 메인 화면에서 질문을 해보세요.")
    st.stop()

df = pd.DataFrame(rows, columns=cols)
df["처리 방식"] = (
    df["sql_text"].fillna("").str.startswith("-- FAST PATH").map({True: "빠른 경로", False: "GPT 경로"})
)
c1, c2, c3, c4 = st.columns(4)
c1.metric("총 질문 수", len(df))
c2.metric("오류 발생", int(df["error_code"].notna().sum()))
c3.metric("평균 응답(ms)", int(df["latency_ms"].mean()))
c4.metric("빠른 경로 비율", f"{(df['처리 방식'] == '빠른 경로').mean() * 100:.0f}%")

st.subheader("처리 방식별 비교")
by_path = (
    df.groupby("처리 방식")
    .agg(질문수=("question", "count"), 평균_응답ms=("latency_ms", "mean"), 오류=("error_code", lambda x: int(x.notna().sum())))
    .round(0)
)
st.dataframe(by_path, use_container_width=True)

st.subheader("자주 묻는 질문 TOP 10")
top_q = df["question"].value_counts().head(10).rename_axis("질문").reset_index(name="횟수")
st.dataframe(top_q, use_container_width=True, hide_index=True)

failed = df[df["error_code"].notna()][["created_at", "question", "error_code", "answer_preview"]]
if not failed.empty:
    st.subheader("실패·주의 질문")
    st.dataframe(failed, use_container_width=True, hide_index=True)

st.subheader("오류 코드별 건수")
ec = pd.DataFrame(error_counts(), columns=["코드", "건수"]).set_index("코드")
st.bar_chart(ec, color="#C6FF3D")

st.subheader("최근 기록")
st.dataframe(df, use_container_width=True, hide_index=True)
st.download_button(
    "CSV 내려받기", df.to_csv(index=False).encode("utf-8-sig"), "query_logs.csv", "text/csv"
)

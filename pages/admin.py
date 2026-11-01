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
c1, c2, c3 = st.columns(3)
c1.metric("총 질문 수", len(df))
c2.metric("오류 발생", int(df["error_code"].notna().sum()))
c3.metric("평균 응답(ms)", int(df["latency_ms"].mean()))

st.subheader("오류 코드별 건수")
ec = pd.DataFrame(error_counts(), columns=["코드", "건수"]).set_index("코드")
st.bar_chart(ec)

st.subheader("최근 기록")
st.dataframe(df, use_container_width=True, hide_index=True)
st.download_button(
    "CSV 내려받기", df.to_csv(index=False).encode("utf-8-sig"), "query_logs.csv", "text/csv"
)

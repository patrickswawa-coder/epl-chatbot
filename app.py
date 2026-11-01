"""
⚽ EPL 데이터 챗봇 - 공모전 제출용 Streamlit UI

실행:
    streamlit run app.py

구성:
    - 자연어 질문 → SQL 변환 → SQLite 조회
    - 대화 기록을 활용한 후속 질문
    - SQL / 원본 데이터 확인
    - 결과에 따른 자동 차트
    - 예시 질문 버튼
    - 데이터베이스 현황 표시
    - 오류 발생 시 사용자 친화적인 안내
"""

import sqlite3
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

import time
import uuid

from error_codes import error_message
from query_logger import log_query
from rate_limiter import check_and_count
from text_to_sql import answer_question


# =========================================================
# 기본 설정
# =========================================================

st.set_page_config(
    page_title="EPL 데이터 챗봇",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "football_history.db"


# =========================================================
# CSS - 공모전 발표용 UI
# =========================================================

st.markdown(
    """
    <style>
    /* 전체 배경 */
    .stApp {
        background:
            radial-gradient(circle at 10% 10%, rgba(255,255,255,0.10), transparent 25%),
            linear-gradient(135deg, #0b3d2e 0%, #116149 45%, #0a2f24 100%);
    }

    /* 상단 여백 */
    .block-container {
        max-width: 1180px;
        padding-top: 2rem;
        padding-bottom: 3rem;
    }

    /* 메인 히어로 */
    .hero {
        position: relative;
        overflow: hidden;
        padding: 2.2rem 2rem;
        margin-bottom: 1.2rem;
        border-radius: 24px;
        background: linear-gradient(135deg, rgba(0,0,0,0.28), rgba(255,255,255,0.08));
        border: 1px solid rgba(255,255,255,0.18);
        box-shadow: 0 14px 40px rgba(0,0,0,0.20);
    }

    .hero::after {
        content: "⚽";
        position: absolute;
        right: 35px;
        top: 12px;
        font-size: 6rem;
        opacity: 0.10;
        transform: rotate(-12deg);
    }

    .hero-title {
        position: relative;
        z-index: 2;
        margin: 0;
        color: #ffffff;
        font-size: 2.45rem;
        font-weight: 800;
        letter-spacing: -0.04em;
    }

    .hero-subtitle {
        position: relative;
        z-index: 2;
        margin: 0.55rem 0 0;
        color: #d9f4e9;
        font-size: 1.05rem;
        line-height: 1.6;
    }

    /* 소개 카드 */
    .info-card {
        background: rgba(255,255,255,0.96);
        border-radius: 18px;
        padding: 1rem 1.2rem;
        margin-bottom: 1rem;
        box-shadow: 0 8px 24px rgba(0,0,0,0.12);
    }

    .info-title {
        color: #0b3d2e;
        font-weight: 800;
        font-size: 1rem;
        margin-bottom: 0.35rem;
    }

    .info-text {
        color: #46534f;
        line-height: 1.55;
        font-size: 0.92rem;
    }

    /* 채팅 메시지 */
    [data-testid="stChatMessage"] {
        background: rgba(255,255,255,0.97) !important;
        border-radius: 16px;
        padding: 0.85rem 1rem;
        margin-bottom: 0.7rem;
        box-shadow: 0 5px 18px rgba(0,0,0,0.10);
        border: 1px solid rgba(0,0,0,0.05);
    }

    [data-testid="stChatMessageContent"] {
        color: #1d2622 !important;
        overflow: visible !important;
        max-height: none !important;
    }

    [data-testid="stChatMessage"] p,
    [data-testid="stChatMessage"] li,
    [data-testid="stChatMessage"] span,
    [data-testid="stChatMessage"] div {
        color: #1d2622 !important;
    }

    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
        border-left: 5px solid #d94b4b;
    }

    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) {
        border-left: 5px solid #f0c34a;
    }

    /* 입력창 */
    [data-testid="stChatInput"] textarea {
        background: #ffffff !important;
        color: #17211d !important;
        border: 2px solid rgba(255,255,255,0.65) !important;
        border-radius: 14px !important;
    }

    [data-testid="stChatInput"] textarea::placeholder {
        color: #6b756f !important;
    }

    /* 추천 질문 버튼 */
    .stButton > button {
        width: 100%;
        min-height: 44px;
        border-radius: 12px;
        border: 1px solid #d8e3de !important;
        background: #ffffff !important;
        color: #17352b !important;
        font-weight: 700;
        box-shadow: 0 2px 7px rgba(0,0,0,0.06);
        transition: all 0.15s ease;
    }

    .stButton > button:hover {
        background: #e9f6ef !important;
        color: #0b5d3f !important;
        border-color: #7fc6a5 !important;
        box-shadow: 0 4px 12px rgba(11,93,63,0.12);
    }

    .stButton > button:focus,
    .stButton > button:focus-visible,
    .stButton > button:active {
        background: #e9f6ef !important;
        color: #0b5d3f !important;
        border-color: #63ad8b !important;
        box-shadow: 0 0 0 2px rgba(99,173,139,0.20) !important;
    }

    .stButton > button p,
    .stButton > button span,
    .stButton > button div {
        color: inherit !important;
    }

    /* 사이드바 */
    [data-testid="stSidebar"] {
        background: #f5f7f6;
    }

    [data-testid="stSidebar"] * {
        color: #17211d;
    }

    /* expander */
    [data-testid="stExpander"] {
        background: rgba(255,255,255,0.96);
        border-radius: 12px;
        border: 1px solid rgba(0,0,0,0.08);
    }

    /* expander 헤더(접혀있을 때 보이는 막대) - 기본 다크 테마 배경을 덮어씀 */
    [data-testid="stExpander"] summary,
    [data-testid="stExpander"] summary:hover,
    [data-testid="stExpander"] details > summary {
        background: #ffffff !important;
        color: #17352b !important;
        border-radius: 12px;
    }

    [data-testid="stExpander"] summary * {
        color: #17352b !important;
        fill: #17352b !important;
    }

    /* 밝은 조회 결과 표 */
    .result-table-wrap {
        width: 100%;
        overflow-x: auto;
        margin: 0.25rem 0 0.8rem;
        border: 1px solid #dfe7e3;
        border-radius: 12px;
        background: #ffffff;
        box-shadow: 0 4px 14px rgba(0,0,0,0.06);
    }

    .result-table {
        width: 100%;
        border-collapse: collapse;
        background: #ffffff;
        color: #1d2622;
        font-size: 0.90rem;
    }

    .result-table th {
        background: #eef5f1;
        color: #17352b;
        font-weight: 800;
        text-align: left;
        padding: 0.75rem 0.65rem;
        border-bottom: 2px solid #d7e3dd;
        white-space: nowrap;
    }

    .result-table td {
        color: #29332f;
        padding: 0.68rem 0.65rem;
        border-bottom: 1px solid #e7ece9;
        background: #ffffff;
        white-space: nowrap;
    }

    .result-table tbody tr:nth-child(even) td {
        background: #f8faf9;
    }

    .result-table tbody tr:hover td {
        background: #eef8f2;
    }

    /* [교체됨] 생성된 SQL 표시용 커스텀 박스 (st.code 대신 사용)
       - st.code()는 최신 Streamlit에서 내부 렌더링 구조상 CSS로 배경/글자색을
         덮어쓸 수 없는 경우가 있어, 결과 표(result-table)와 동일한 방식으로
         직접 HTML/CSS를 만들어 사용합니다. */
    .sql-block-wrap {
        width: 100%;
        overflow-x: auto;
        margin: 0.25rem 0 0.8rem;
        border: 1px solid #dfe7e3;
        border-radius: 12px;
        background: #ffffff;
        box-shadow: 0 4px 14px rgba(0,0,0,0.06);
    }

    .sql-block {
        margin: 0;
        padding: 0.9rem 1rem;
        background: #ffffff;
        color: #1d2622;
        font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
        font-size: 0.88rem;
        line-height: 1.55;
        white-space: pre-wrap;
        word-break: break-word;
    }

    /* [NEW] 답변 뒤에 붙는 추가 인사이트 박스 */
    .insight-box {
        margin: 0.5rem 0 0.2rem;
        padding: 0.65rem 0.95rem;
        background: #fff8e1;
        border-left: 4px solid #f0c34a;
        border-radius: 10px;
        color: #5c4a12;
        font-size: 0.88rem;
        line-height: 1.55;
    }

    /* [NEW] DB로 확인되지 않은 GPT 지식 기반 답변 경고 배지 */
    .fallback-badge {
        margin: 0 0 0.6rem;
        padding: 0.6rem 0.95rem;
        background: #fdecea;
        border-left: 4px solid #e05252;
        border-radius: 10px;
        color: #7a2020;
        font-size: 0.85rem;
        line-height: 1.5;
    }

    /* 작은 안내 문구 */
    .muted {
        color: #d9f4e9;
        font-size: 0.82rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# =========================================================
# 결과 표시
# =========================================================

def render_result_table(df: pd.DataFrame) -> None:
    """공모전 발표 화면에 맞는 밝은 결과 표를 렌더링한다."""
    if df.empty:
        return

    display_df = df.copy()

    # 너무 긴 텍스트가 화면을 밀어내지 않도록 표시용으로만 일부 축약
    for col in display_df.columns:
        display_df[col] = display_df[col].map(
            lambda value: (
                str(value)[:80] + "…"
                if isinstance(value, str) and len(value) > 81
                else value
            )
        )

    header_html = "".join(
        f"<th>{str(col)}</th>" for col in display_df.columns
    )

    rows_html = []
    for _, row in display_df.iterrows():
        cells = "".join(
            f"<td>{str(value) if pd.notna(value) else '-'}</td>"
            for value in row
        )
        rows_html.append(f"<tr>{cells}</tr>")

    table_html = f'''
    <div class="result-table-wrap">
        <table class="result-table">
            <thead><tr>{header_html}</tr></thead>
            <tbody>{"".join(rows_html)}</tbody>
        </table>
    </div>
    '''

    st.markdown(table_html, unsafe_allow_html=True)


def render_sql_block(sql: str) -> None:
    """
    생성된 SQL을 밝은 배경의 커스텀 박스로 표시한다.

    st.code()는 Streamlit 버전에 따라 내부 렌더링 구조상 CSS로
    배경/글자색을 덮어쓸 수 없는 경우가 있어, 결과 표와 동일하게
    직접 HTML로 렌더링한다.
    """
    sql = sql or ""
    escaped_sql = escape(sql)

    st.markdown(
        f'<div class="sql-block-wrap"><pre class="sql-block">{escaped_sql}</pre></div>',
        unsafe_allow_html=True,
    )


def render_insight(insight: str | None) -> None:
    """[NEW] 답변 뒤에 붙는 추가 인사이트 한 줄을 밝은 강조 박스로 표시한다."""
    if not insight:
        return

    st.markdown(
        f'<div class="insight-box">💡 {escape(insight)}</div>',
        unsafe_allow_html=True,
    )


def render_fallback_badge(answer_source: str | None) -> None:
    """
    [NEW] DB 조회가 실패해서 GPT의 일반 지식으로 답한 경우, 그 사실을
    명확히 알리는 경고 배지를 표시한다. DB로 검증된 답변과 절대 혼동되지
    않도록 답변 바로 위에 렌더링한다.
    """
    if answer_source != "gpt_fallback":
        return

    st.markdown(
        '<div class="fallback-badge">⚠️ 이 답변은 데이터베이스로 확인되지 '
        '않았습니다. GPT의 일반 지식을 기반으로 한 답변이라 부정확할 수 '
        '있으니 참고용으로만 활용해주세요.</div>',
        unsafe_allow_html=True,
    )


# =========================================================
# DB 현황
# =========================================================

def get_db_stats() -> dict:
    """현재 SQLite DB의 기본 통계를 가져온다."""
    stats = {
        "matches": 0,
        "events": 0,
        "seasons": 0,
    }

    if not DB_PATH.exists():
        return stats

    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM matches")
        stats["matches"] = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM match_events")
        stats["events"] = cur.fetchone()[0]

        cur.execute(
            "SELECT COUNT(DISTINCT season) FROM matches "
            "WHERE season IS NOT NULL AND season != ''"
        )
        stats["seasons"] = cur.fetchone()[0]

    except Exception:
        pass
    finally:
        if conn:
            conn.close()

    return stats


# =========================================================
# 세션 상태
# =========================================================

if "session_id" not in st.session_state:
    st.session_state.session_id = uuid.uuid4().hex[:12]

# 자동 생성되는 페이지 메뉴(관리자 화면 링크)는 숨겨 기존 화면을 그대로 유지한다
st.markdown(
    "<style>[data-testid='stSidebarNav']{display:none}</style>",
    unsafe_allow_html=True,
)

if "messages" not in st.session_state:
    st.session_state.messages = []

if "last_result" not in st.session_state:
    st.session_state.last_result = None

if "followup_questions" not in st.session_state:
    st.session_state.followup_questions = []


# =========================================================
# 사이드바
# =========================================================

with st.sidebar:
    st.markdown("## ⚽ EPL Chatbot")

    st.divider()

    example_questions = [
        "손흥민이 넣은 골의 개수는?",
        "골을 가장 많이 넣은 선수 10명 보여줘",
        "아스날과 맨시티의 경기 결과를 보여줘",
        "손흥민의 골이 가장 많이 나온 시간대는?",
        "어시스트를 가장 많이 한 선수는 누구야?",
    ]

    # [NEW] 대화가 시작되면 고정 예시 대신, 방금 나눈 대화를 기반으로
    # GPT가 만든 후속 질문을 보여준다. 대화 시작 전에는 기존 고정 예시를 그대로 사용.
    if st.session_state.followup_questions:
        st.markdown("### 🔄 이어서 물어보면 좋은 질문")
        st.caption("방금 대화를 기반으로 추천해드려요")

        for i, followup in enumerate(st.session_state.followup_questions):
            if st.button(followup, use_container_width=True, key=f"followup_{i}"):
                st.session_state.pending_question = followup
    else:
        st.markdown("### 💡 추천 질문")

        for i, example in enumerate(example_questions):
            if st.button(example, use_container_width=True, key=f"example_{i}"):
                st.session_state.pending_question = example

    st.divider()

    stats = get_db_stats()

    st.markdown("### 📊 데이터 현황")
    col1, col2 = st.columns(2)

    with col1:
        st.metric("경기", f"{stats['matches']:,}")
    with col2:
        st.metric("이벤트", f"{stats['events']:,}")

    st.metric("시즌", f"{stats['seasons']:,}")

    st.divider()

    st.markdown("### 🔎 제공 기능")
    st.markdown(
        """
        - 자연어 → SQL 변환
        - EPL 경기 데이터 조회
        - 득점 / 어시스트 / 카드 분석
        - 조회 결과 표와 차트
        - 이전 대화를 활용한 후속 질문
        """
    )

    st.divider()

    if st.button("🗑️ 대화 내용 초기화", use_container_width=True):
        st.session_state.messages = []
        st.session_state.last_result = None
        st.session_state.followup_questions = []
        st.rerun()

    st.caption("※ 답변은 연결된 EPL 데이터베이스를 기준으로 생성됩니다.")


# =========================================================
# 헤더
# =========================================================

st.markdown(
    """
    <div class="hero">
        <p class="hero-title">⚽ EPL 데이터 챗봇</p>
        <p class="hero-subtitle">
            축구 데이터를 자연어로 질문하면
            <b>GPT가 SQL을 생성하고 SQLite 데이터를 조회</b>하여 답변합니다.
        </p>
        <p class="muted">
            경기 결과 · 득점자 · 어시스트 · 득점 시간 · 선수 기록
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)


# =========================================================
# 첫 화면 안내
# =========================================================

if not st.session_state.messages:
    st.markdown(
        """
        <div class="info-card">
            <div class="info-title">👋 EPL 데이터를 자유롭게 질문해보세요</div>
            <div class="info-text">
                예를 들어 <b>“손흥민이 넣은 골의 개수는?”</b>처럼
                평소 사용하는 말로 질문할 수 있습니다.
                조회 결과는 데이터베이스에 실제 저장된 값을 기준으로 표시합니다.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div style="background:rgba(255,255,255,0.14);
                    border:1px solid rgba(255,255,255,0.28);
                    border-radius:14px;padding:16px 22px;
                    color:#F5F3EA;font-size:16px;">
            💬 왼쪽의 예시 질문을 클릭하거나 아래 입력창에서 직접 질문해보세요.
        </div>
        """,
        unsafe_allow_html=True,
    )


# =========================================================
# 기존 대화 출력
# =========================================================

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

        # 이전 결과가 저장되어 있다면 해당 메시지의 상세 정보 표시
        if msg.get("result"):
            result = msg["result"]

            render_fallback_badge(result.get("answer_source"))
            render_insight(result.get("insight"))

            if result.get("rows"):
                df = pd.DataFrame(
                    result["rows"],
                    columns=result["columns"],
                )

                with st.expander(f"📋 조회 결과 보기 ({len(df)}행)"):
                    render_result_table(df)

            if result.get("sql"):
                with st.expander("🔍 생성된 SQL 보기"):
                    render_sql_block(result.get("sql", ""))


# =========================================================
# 질문 입력
# =========================================================

typed_question = st.chat_input(
    "예: 손흥민의 득점 수를 알려줘 (200자 이내)",
)

pending_question = st.session_state.pop("pending_question", None)
question = typed_question or pending_question


# =========================================================
# 질문 처리
# =========================================================

if question:
    # 현재 질문을 제외한 이전 대화만 LLM history로 전달
    history = [
        {
            "role": msg["role"],
            "content": msg["content"],
        }
        for msg in st.session_state.messages
        if msg["role"] in ("user", "assistant")
    ]

    # 사용자 질문 표시
    user_message = {
        "role": "user",
        "content": question,
    }
    st.session_state.messages.append(user_message)

    with st.chat_message("user"):
        st.markdown(question)

    # 답변 생성
    with st.chat_message("assistant"):
        with st.spinner("⚽ EPL 데이터를 분석하고 있습니다..."):
            _t0 = time.monotonic()
            if not check_and_count(st.session_state.session_id):
                # [E08] 호출 한도 초과 (분당 5회 / 하루 200회)
                result = {
                    "sql": "",
                    "columns": [],
                    "rows": [],
                    "answer": None,
                    "answer_source": None,
                    "followups": [],
                    "error": error_message("E08"),
                    "error_code": "E08",
                }
            else:
                try:
                    result = answer_question(
                        question,
                        history=history,
                        max_retries=1,
                    )
                except Exception as exc:
                    result = {
                        "sql": "",
                        "columns": [],
                        "rows": [],
                        "answer": None,
                        "answer_source": None,
                        "followups": [],
                        "error": error_message("E09", str(exc)),
                        "error_code": "E09",
                    }
            log_query(
                st.session_state.session_id,
                question,
                result,
                (time.monotonic() - _t0) * 1000,
            )

        # 오류 처리
        if result.get("error"):
            error_text = str(result["error"])

            # 오류 코드가 있으면 "[E01] 안내문구"를 그대로 보여준다.
            if result.get("error_code"):
                st.error(error_text)
            else:
                st.error("데이터 조회 중 문제가 발생했습니다.")

            if "quota" in error_text.lower() or "credit" in error_text.lower():
                st.warning(
                    "OpenAI API 사용량 또는 크레딧을 확인해주세요."
                )
            elif "rate" in error_text.lower():
                st.warning(
                    "API 요청이 일시적으로 제한되었습니다. 잠시 후 다시 시도해주세요."
                )
            else:
                st.info(
                    "질문 표현을 조금 바꿔 다시 시도해보세요. "
                    "예: '손흥민의 EPL 득점 수는?'"
                )

            if result.get("sql"):
                with st.expander("🔍 생성된 SQL 확인"):
                    render_sql_block(result["sql"])

            # 오류 코드가 있으면 "[E02] ..." 안내문을 기록에도 그대로 남긴다.
            # (이 메시지가 st.rerun() 후 대화 기록에서 다시 보이는 문구)
            if result.get("error_code") and result.get("error"):
                assistant_text = str(result["error"])
            else:
                assistant_text = "조회에 실패했습니다. 질문을 조금 다르게 표현해보세요."

        else:
            assistant_text = result.get("answer") or "조회 결과가 없습니다."

            render_fallback_badge(result.get("answer_source"))
            st.markdown(assistant_text)

            render_insight(result.get("insight"))

            # 결과 테이블
            if result.get("rows"):
                df = pd.DataFrame(
                    result["rows"],
                    columns=result["columns"],
                )

                with st.expander(f"📋 조회 결과 보기 ({len(df)}행)"):
                    render_result_table(df)

                # 숫자 + 문자 컬럼이 함께 있을 경우 간단한 차트 표시
                numeric_cols = df.select_dtypes(
                    include="number"
                ).columns.tolist()

                text_cols = [
                    col for col in df.columns
                    if col not in numeric_cols
                ]

                if numeric_cols and text_cols and len(df) >= 2:
                    label_col = text_cols[0]
                    value_col = numeric_cols[0]

                    chart_df = (
                        df[[label_col, value_col]]
                        .dropna()
                        .drop_duplicates()
                        .sort_values(value_col, ascending=False)
                        .head(20)
                        .set_index(label_col)
                    )

                    if not chart_df.empty:
                        with st.expander("📈 결과 시각화 보기"):
                            st.bar_chart(chart_df)

            # SQL은 기본적으로 접어서 제공
            with st.expander("🔍 생성된 SQL 보기"):
                render_sql_block(result.get("sql", ""))

            # 데이터가 없을 때 (단, GPT 지식 기반 폴백으로 이미 답변한 경우는 제외)
            if (
                not result.get("rows")
                and result.get("answer_source") != "gpt_fallback"
                and result.get("error_code") != "E04"  # E04 안내문은 답변에 이미 표시됨
            ):
                st.info(
                    "조건에 맞는 데이터가 없습니다. "
                    "선수명, 팀명, 시즌 등을 조금 다르게 표현해보세요."
                )

        # 다음 후속 질문을 위한 메시지 저장
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": assistant_text,
                "result": result,
            }
        )

        st.session_state.last_result = result

        # [NEW] 방금 결과에서 나온 후속 질문 추천을 사이드바에 반영
        # (실패했거나 없으면 빈 리스트 -> 다음 렌더링부터는 다시 고정 예시로 복귀)
        st.session_state.followup_questions = result.get("followups") or []

    # 사이드바에 새로 반영된 후속 질문을 즉시 보여주기 위해 재실행
    st.rerun()
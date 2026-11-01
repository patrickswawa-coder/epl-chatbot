"""화면 디자인(B안: 밤 경기장 스코어보드). 모든 페이지가 apply_theme()로 같은 스타일을 쓴다."""
import streamlit as st

_PITCH_SVG = (
    "data:image/svg+xml;utf8,"
    "<svg xmlns='http://www.w3.org/2000/svg' width='900' height='900' viewBox='0 0 900 900' fill='none'>"
    "<circle cx='450' cy='450' r='330' stroke='%2314281F' stroke-width='2'/>"
    "<circle cx='450' cy='450' r='14' fill='%2314281F'/>"
    "<path d='M450 0v900' stroke='%2314281F' stroke-width='2'/></svg>"
)

THEME_CSS = (
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Black+Han+Sans&family=Noto+Sans+KR:wght@400;500;700&display=swap');

:root {
    --bg: #07110D;
    --panel: #0B1812;
    --line: #1A2E24;
    --line2: #2A4538;
    --text: #EEF2EA;
    --soft: #D5DFD8;
    --mute: #7E9488;
    --lime: #C6FF3D;
    --ink: #07110D;
    --num: 'Bebas Neue', 'Noto Sans KR', sans-serif;
    --head: 'Black Han Sans', 'Noto Sans KR', sans-serif;
}

/* ---------- 바탕 ---------- */
html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
    font-family: 'Noto Sans KR', sans-serif;
    color: var(--text);
}
.stApp {
    background-color: var(--bg);
    background-image: url("__PITCH__");
    background-repeat: no-repeat;
    background-position: right -260px bottom -300px;
    background-attachment: fixed;
}
[data-testid="stHeader"] { background: transparent; }
.block-container { max-width: 900px; padding-top: 2.2rem; padding-bottom: 3rem; }

/* ---------- 상단 소개 ---------- */
.hero { padding: 0 0 1.4rem; margin-bottom: 1.4rem; border-bottom: 1px solid var(--line); }
.stApp .hero .hero-kicker { font-family: var(--num); letter-spacing: .32em; font-size: .95rem !important; color: var(--lime); margin: 0 0 .35rem; }
.stApp .hero .hero-title { font-family: var(--head); font-size: 2.6rem !important; line-height: 1.15 !important; margin: 0; color: var(--text); letter-spacing: -.01em; font-weight: 400; }
.stApp .hero .hero-subtitle { margin: .7rem 0 0; color: var(--soft); font-size: 1rem; line-height: 1.65; }
.hero-subtitle b { color: var(--text); font-weight: 700; }
.stApp .hero .muted { color: var(--mute); font-size: .85rem; margin: .5rem 0 0; }

.info-card { background: var(--panel); border-top: 3px solid var(--lime); padding: 1.1rem 1.4rem; margin-bottom: 1rem; }
.info-title { font-weight: 700; color: var(--text); font-size: 1rem; margin-bottom: .35rem; }
.info-text { color: var(--soft); line-height: 1.65; font-size: .92rem; }
.info-text b { color: var(--lime); }
.hint-line { color: var(--mute); font-size: .9rem; padding: .4rem 0; }

/* ---------- 채팅 ---------- */
[data-testid="stChatMessage"] {
    background: transparent !important; border: 0 !important; box-shadow: none !important;
    padding: 0 !important; margin-bottom: 1.2rem; width: 100%;
}
[data-testid^="stChatMessageAvatar"], [data-testid^="chatAvatarIcon"] { display: none !important; }
[data-testid="stChatMessageContent"] { color: var(--soft); width: 100%; overflow: visible !important; }
[data-testid="stChatMessage"] p, [data-testid="stChatMessage"] li { color: var(--soft); line-height: 1.65; }

/* 사용자 질문: 오른쪽, 밝은 칩 */
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]),
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) { display: flex; justify-content: flex-end; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"],
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) [data-testid="stChatMessageContent"] {
    background: var(--text); width: fit-content !important; flex: 0 1 auto !important; max-width: 72%; margin: 0 0 0 auto !important; padding: .8rem 1.1rem;
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) p,
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) p { color: var(--ink); font-weight: 500; }

/* 답변: 어두운 패널 + 라임 윗선 */
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) [data-testid="stChatMessageContent"],
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) [data-testid="stChatMessageContent"] {
    background: var(--panel); border-top: 3px solid var(--lime); padding: 1.1rem 1.5rem 1.2rem;
}

/* ---------- 스코어보드(큰 숫자) ---------- */
.score-label { font-family: var(--num); letter-spacing: .24em; font-size: .85rem; color: var(--mute); margin: 0 0 .1rem; }
.score-row { display: flex; align-items: flex-end; gap: .9rem; flex-wrap: wrap; margin: 0 0 .4rem; }
.score-num { font-family: var(--num); font-size: 7.5rem; line-height: .86; color: var(--lime); letter-spacing: .01em; }
.score-unit { font-family: var(--head); font-weight: 400; font-size: 1.7rem; color: var(--text); padding-bottom: .35rem; }

/* ---------- 부가 정보 ---------- */
.insight-box {
    margin: .7rem 0 .3rem; padding: .75rem 0 .2rem; border-top: 1px solid var(--line);
    color: var(--soft); font-size: .92rem; line-height: 1.6;
}
.insight-box::before { content: "NOTE"; font-family: var(--num); letter-spacing: .24em; color: var(--lime); margin-right: .9rem; font-size: .95rem; }
.fallback-badge {
    margin: 0 0 .7rem; padding: .7rem 1rem; background: #2A1210; border: 1px solid #7A2A22;
    color: #FFB4AB; font-size: .88rem; line-height: 1.55;
}
.fallback-badge::before { content: "CAUTION"; font-family: var(--num); letter-spacing: .24em; color: #FF8A7A; margin-right: .9rem; }

/* ---------- expander ---------- */
[data-testid="stExpander"] { background: transparent; border: 1px solid var(--line) !important; border-radius: 0 !important; margin-top: .5rem; }
[data-testid="stExpander"] summary, [data-testid="stExpander"] details > summary {
    background: var(--panel) !important; color: var(--text) !important; border-radius: 0 !important; min-height: 44px;
}
[data-testid="stExpander"] summary:hover { color: var(--lime) !important; }
[data-testid="stExpander"] summary * { color: inherit !important; }

/* ---------- 조회 결과 표 / SQL ---------- */
.result-table-wrap, .sql-block-wrap { width: 100%; overflow-x: auto; margin: .3rem 0 .6rem; border: 1px solid var(--line); background: var(--panel); }
.result-table { width: 100%; border-collapse: collapse; font-size: .9rem; color: var(--soft); }
.result-table th { background: #0F1F18; color: var(--lime); font-weight: 700; text-align: left; padding: .7rem .75rem; border-bottom: 1px solid var(--line2); white-space: nowrap; }
.result-table td { color: var(--soft); padding: .65rem .75rem; border-bottom: 1px solid var(--line); background: var(--panel); white-space: nowrap; }
.result-table tbody tr:nth-child(even) td { background: #0D1C15; }
.result-table tbody tr:hover td { background: #12261C; }
.sql-block { margin: 0; padding: .9rem 1rem; background: #050C09; color: #C9E8B8; font-family: 'SFMono-Regular', Consolas, Menlo, monospace; font-size: .86rem; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }

/* ---------- 입력창 ---------- */
[data-testid="stBottom"], [data-testid="stBottom"] > div, [data-testid="stBottomBlockContainer"] { background: var(--bg) !important; }
[data-testid="stChatInput"] { background: var(--panel) !important; border: 1px solid var(--line2) !important; border-radius: 0 !important; }
[data-testid="stChatInput"]:focus-within { border-color: var(--lime) !important; box-shadow: none !important; }
[data-testid="stChatInput"] > div { background: transparent !important; border: 0 !important; border-radius: 0 !important; }
[data-testid="stChatInput"] textarea { background: transparent !important; color: var(--text) !important; font-family: 'Noto Sans KR', sans-serif; }
[data-testid="stChatInput"] textarea::placeholder { color: var(--mute) !important; }
[data-testid="stChatInputSubmitButton"] { background: var(--lime) !important; color: var(--ink) !important; border-radius: 0 !important; }
[data-testid="stChatInputSubmitButton"] svg { fill: var(--ink) !important; color: var(--ink) !important; }

/* ---------- 사이드바 ---------- */
[data-testid="stSidebar"] { background: #060E0A; border-right: 1px solid var(--line); }
[data-testid="stSidebar"] * { color: var(--soft); }
.brand-kicker { font-family: var(--num); letter-spacing: .2em; font-size: .85rem; white-space: nowrap; color: var(--lime) !important; margin: 0 0 .2rem; }
.brand-name { font-family: var(--head); font-weight: 400; font-size: 1.9rem; line-height: 1.1; color: var(--text) !important; margin: 0; }
.side-label { font-family: var(--num); letter-spacing: .24em; font-size: .9rem; color: var(--mute) !important; margin: 1.4rem 0 .4rem; }
.stat-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1px; background: var(--line); margin: .3rem 0 .5rem; }
.stat-cell { background: var(--panel); padding: .7rem .5rem; min-width: 0; }
.stat-num { white-space: nowrap; font-family: var(--num); font-size: 1.35rem; line-height: 1; color: var(--text) !important; letter-spacing: .02em; }
.stat-name { font-size: .72rem; color: var(--mute) !important; margin-top: .15rem; }
.side-note { font-size: .78rem; color: var(--mute) !important; line-height: 1.5; }

/* 추천 질문·후속 질문 = 번호 붙은 목록 */
[data-testid="stSidebar"] .stButton > button {
    width: 100%; justify-content: flex-start; text-align: left; min-height: 44px;
    background: transparent !important; border: 0 !important; border-top: 1px solid var(--line) !important;
    border-radius: 0 !important; box-shadow: none !important; padding: .7rem 0 !important;
    color: var(--soft) !important; font-weight: 400; font-size: .92rem; line-height: 1.45;
}
[data-testid="stSidebar"] .stButton > button:hover { color: var(--lime) !important; background: transparent !important; }
[data-testid="stSidebar"] .stButton > button:focus, [data-testid="stSidebar"] .stButton > button:active {
    background: transparent !important; color: var(--lime) !important; box-shadow: none !important;
}
[data-testid="stSidebar"] .stButton > button > div { justify-content: flex-start !important; width: 100%; }
[data-testid="stSidebar"] .stButton > button p { color: inherit !important; text-align: left !important; margin: 0; }
[data-testid="stSidebar"] .st-key-reset_btn button {
    border: 1px solid var(--line2) !important; justify-content: center; text-align: center; margin-top: 1rem; padding: .7rem 1rem !important;
}
[data-testid="stSidebar"] .st-key-reset_btn button > div { justify-content: center !important; }
[data-testid="stSidebar"] .st-key-reset_btn button p { text-align: center !important; }

/* 관리자 버튼 */
[data-testid="stPageLink"] a, [data-testid="stPageLink-NavLink"] {
    border: 1px solid var(--line2) !important; border-radius: 0 !important; background: transparent !important;
    min-height: 44px; justify-content: center; color: var(--text) !important;
}
[data-testid="stPageLink"] a:hover, [data-testid="stPageLink-NavLink"]:hover { border-color: var(--lime) !important; }
[data-testid="stPageLink"] a *, [data-testid="stPageLink-NavLink"] * { color: var(--text) !important; }

/* 자동 페이지 메뉴 숨김 */
[data-testid="stSidebarNav"] { display: none; }

/* 좁은 화면 */
@media (max-width: 640px) {
    .block-container { padding-left: 1rem; padding-right: 1rem; padding-top: 1.2rem; }
    .hero-title { font-size: 2rem; }
    .score-num { font-size: 5.6rem; }
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"],
    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) [data-testid="stChatMessageContent"] { max-width: 88%; }
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) [data-testid="stChatMessageContent"],
    [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) [data-testid="stChatMessageContent"] { padding: 1rem 1.1rem; }
}
</style>
""".replace("__PITCH__", _PITCH_SVG)
)


def apply_theme() -> None:
    st.markdown(THEME_CSS, unsafe_allow_html=True)

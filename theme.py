"""화면 디자인(B안: 밤 경기장 스코어보드). 모든 페이지가 apply_theme()로 같은 스타일을 쓴다."""
import streamlit as st

_PITCH_SVG = (
    "data:image/svg+xml;utf8,"
    "<svg xmlns='http://www.w3.org/2000/svg' width='900' height='900' viewBox='0 0 900 900' fill='none'>"
    "<circle cx='450' cy='450' r='330' stroke='%23102219' stroke-width='2'/></svg>"
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
/* 사이드바 제목(EPL 챗봇) = 첫 화면으로 돌아가는 버튼 */
[data-testid="stSidebar"] .st-key-brand_home button {
    background: transparent !important; border: 0 !important; border-radius: 0 !important; box-shadow: none !important;
    min-height: 0 !important; padding: 0 !important; width: auto;
}
[data-testid="stSidebar"] .st-key-brand_home button p { font-family: var(--head); font-size: 1.9rem !important; line-height: 1.1; color: var(--text) !important; }
[data-testid="stSidebar"] .st-key-brand_home button:hover p { color: var(--lime) !important; }
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


/* ---------- 빠른 경로 카드 (프로필·비교·상대전적) ---------- */
.pcard { background: var(--panel); border-top: 3px solid var(--lime); margin: 0 0 .8rem; }
.pcard-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 1rem; padding: 1.3rem 1.6rem 1rem; }
.pcard-kicker { font-family: var(--num); letter-spacing: .22em; font-size: .9rem; color: var(--mute); }
.pcard-kicker.mute { color: var(--mute); }
.pcard-name { font-family: var(--head); font-weight: 400; font-size: 2.3rem; line-height: 1.1; color: var(--text); margin-top: .25rem; }
.pcard-name.sm { font-size: 1.8rem; margin-top: 0; }
.pcard-en { font-family: var(--num); letter-spacing: .18em; font-size: .95rem; color: var(--lime); }
.pcard-sub { font-size: .75rem; color: var(--mute); text-align: right; line-height: 1.5; }
.pcard-sec { padding: 1.2rem 1.6rem .9rem; border-top: 1px solid var(--line); }
.hi { color: var(--lime) !important; }

.stat3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1px; background: var(--line); border-top: 1px solid var(--line); }
.stat3 .cell { background: var(--panel); padding: 1.1rem 1.6rem; }
.stat3 .n { font-family: var(--num); font-size: 4.2rem; line-height: .9; color: var(--text); }
.stat3 .l { font-size: .8rem; color: var(--mute); margin-top: .3rem; }

.bars { display: flex; align-items: flex-end; gap: .6rem; margin-top: .8rem; }
.bcol { flex: 1 1 0; min-width: 0; display: flex; flex-direction: column; align-items: center; gap: .3rem; }
.bv { font-family: var(--num); font-size: 1.15rem; color: var(--soft); }
.btrack { width: 100%; height: 130px; display: flex; align-items: flex-end; }
.bfill { width: 100%; background: var(--line2); }
.bfill.hi { background: var(--lime); }
.bl { font-size: .7rem; color: var(--mute); }
.bl .short { display: none; }
.bnote { margin-top: .6rem; font-size: .72rem; color: var(--mute); display: none; }

.cmp-names { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 4px; padding: .2rem 1.6rem 1rem; }
.cmp-name { padding-left: .6rem; }
.cmp-name.left { text-align: right; padding-left: 0; padding-right: .6rem; }
.cmp-row { border-top: 1px solid var(--line); padding: .8rem 1.6rem 1rem; }
.cmp-label { text-align: center; font-size: .8rem; color: var(--mute); margin-bottom: .4rem; }
.cmp-bars { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 4px; align-items: center; }
.cmp-side { display: flex; align-items: center; gap: .8rem; min-width: 0; }
.cmp-side.left { justify-content: flex-end; }
.cmp-side.right { justify-content: flex-start; }
.cfill { height: 20px; flex: 0 1 auto; min-width: 4px; background: var(--line2); }
.cfill.hi { background: var(--lime); }
.cv { font-family: var(--num); font-size: 2.6rem; line-height: 1; color: var(--text); flex: 0 0 auto; white-space: nowrap; }
.cmp-side.left .cv { text-align: right; min-width: 0; }
.cmp-side.right .cv { min-width: 0; }

.h2h-top { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); align-items: center; gap: 1rem; padding: .4rem 1.6rem 0; }
.h2h-team.r { text-align: right; }
.h2h-score { display: flex; align-items: flex-end; gap: .8rem; font-family: var(--num); font-size: 6rem; line-height: .88; color: var(--text); }
.h2h-score i { font-style: normal; font-size: 3rem; color: var(--line2); padding-bottom: .3rem; }
.h2h-cap { text-align: center; font-size: .75rem; color: var(--mute); padding: .3rem 0 1rem; }
.wdl-wrap { padding: 0 1.6rem 1.2rem; }
.wdl { display: flex; height: 14px; gap: 2px; }
.wdl .w { background: var(--lime); }
.wdl .d { background: #4A6356; }
.wdl .l { background: #1F3A2D; }
.wdl-l { display: flex; justify-content: space-between; margin-top: .5rem; font-size: .8rem; color: var(--soft); }
.wdl-l b { font-family: var(--num); font-size: 1.4rem; font-weight: 400; color: var(--text); margin-right: .15rem; }
.recent { margin-top: .5rem; }
.rrow { display: grid; grid-template-columns: 110px minmax(0, 1fr) 90px minmax(0, 1fr); gap: .8rem; align-items: center; padding: .6rem 0; border-top: 1px solid var(--line); font-size: .9rem; color: var(--soft); }
.rrow .rd { color: var(--mute); }
.rrow .rh { text-align: right; }
.rrow .rs { font-family: var(--num); font-size: 1.4rem; text-align: center; letter-spacing: .06em; color: var(--text); }

@media (max-width: 640px) {
    .pcard-head { padding: 1rem 1rem .8rem; flex-direction: column; align-items: flex-start; gap: .4rem; }
    .pcard-sub { text-align: left; }
    .pcard-name { font-size: 1.9rem; }
    .pcard-name.sm { font-size: 1.3rem; }
    .pcard-sec { padding: 1rem 1rem .8rem; }
    .stat3 .cell { padding: .8rem .8rem; }
    .stat3 .n { font-size: 3rem; }
    .stat3 .l { font-size: .7rem; }
    .bars { gap: .25rem; }
    .btrack { height: 100px; }
    .bv { font-size: .95rem; }
    .bl .long { display: none; }
    .bl .short { display: inline; }
    .bnote { display: block; }
    .pcard-en { letter-spacing: .08em; font-size: .78rem; }
    .cmp-names { padding: .2rem 1rem .8rem; }
    .cmp-row { padding: .7rem 1rem .8rem; }
    .cv { font-size: 2rem; }
    .cfill { height: 14px; }
    .cmp-side { gap: .4rem; }
    .h2h-top { padding: .2rem 1rem 0; gap: .5rem; }
    .h2h-score { font-size: 3.8rem; gap: .4rem; }
    .h2h-score i { font-size: 2rem; }
    .wdl-wrap { padding: 0 1rem 1rem; }
    .wdl-l { font-size: .72rem; }
    .rrow { grid-template-columns: 1fr auto 1fr; grid-template-areas: "d d d" "h s a"; gap: .1rem .5rem; padding: .55rem 0; }
    .rrow .rd { grid-area: d; font-size: .7rem; }
    .rrow .rh { grid-area: h; text-align: left; }
    .rrow .rs { grid-area: s; font-size: 1.25rem; }
    .rrow .ra { grid-area: a; text-align: right; }
}

/* 자동 페이지 메뉴 숨김 */
[data-testid="stSidebarNav"] { display: none; }

/* ---------- 상단: 작은 관리자 링크, 대화 중 축소 헤더 ---------- */
.st-key-adminlink { align-items: flex-end; margin-bottom: -2.6rem; position: relative; z-index: 3; }
.st-key-adminlink > div { width: auto !important; }
.st-key-adminlink [data-testid="stPageLink"] { width: auto !important; }
.st-key-adminlink [data-testid="stPageLink"] a, .st-key-adminlink [data-testid="stPageLink-NavLink"] {
    min-height: 30px !important; padding: .1rem .85rem !important; border-color: var(--line) !important;
}
.st-key-adminlink [data-testid="stPageLink"] a *, .st-key-adminlink [data-testid="stPageLink-NavLink"] * {
    font-size: .78rem !important; color: var(--mute) !important; letter-spacing: .04em;
}
.st-key-adminlink [data-testid="stPageLink"] a:hover * { color: var(--lime) !important; }
.hero.compact { padding-bottom: .9rem; margin-bottom: 1.2rem; }
/* AI 해설 상자 · 문서 근거(RAG) 출처 줄 */
.ai-comment { border: 1px solid var(--line); border-left: 3px solid var(--lime); background: var(--panel); padding: .85rem 1.1rem; margin: .6rem 0 .4rem; }
.ai-comment .h { display: flex; align-items: baseline; gap: .7rem; flex-wrap: wrap; margin-bottom: .35rem; }
.ai-comment .k { font-family: var(--num); letter-spacing: .2em; color: var(--lime); font-size: .9rem; }
.ai-comment .t { font-size: .74rem; color: var(--mute); }
.ai-comment p { margin: 0; color: var(--text); line-height: 1.75; font-size: .95rem; }
[class*="st-key-aibtn_"] button { background: transparent !important; border: 1px solid var(--lime) !important; color: var(--lime) !important; border-radius: 0 !important; padding: .35rem .9rem !important; min-height: 0 !important; }
[class*="st-key-aibtn_"] button:hover { background: var(--lime) !important; color: var(--ink) !important; }
[class*="st-key-aibtn_"] button p { color: inherit !important; font-size: .86rem; letter-spacing: .02em; }
[class*="st-key-aibtn_"] button p::before { content: "✦ "; }
.doc-src { font-size: .8rem; color: var(--mute); margin: .5rem 0 .2rem; line-height: 1.6; }
.doc-src .k { font-family: var(--num); letter-spacing: .2em; color: var(--lime); margin-right: .6rem; }

/* 대화 중 상단 제목 = 첫 화면으로 돌아가는 버튼 */
.st-key-herohome { gap: .45rem !important; padding-bottom: .9rem; margin-bottom: 1.2rem; border-bottom: 1px solid var(--line); }
.st-key-herohome [data-testid="stMarkdownContainer"] p.home-kicker { font-family: var(--num); letter-spacing: .32em; font-size: .95rem; line-height: 1.3; color: var(--lime); margin: 0 !important; }
.st-key-herohome [data-testid="stElementContainer"], .st-key-herohome .stMarkdown, .st-key-herohome [data-testid="stMarkdownContainer"] { margin: 0 !important; }
.st-key-home_title button { background: transparent !important; border: 0 !important; box-shadow: none !important; padding: 0 !important; min-height: 0 !important; }
.st-key-home_title button > div { justify-content: flex-start !important; }
.st-key-home_title button p { font-family: var(--head); font-size: 1.6rem !important; line-height: 1.15; color: var(--text); margin: 0; }
.st-key-home_title button p::after { content: "← 처음 화면"; font-family: 'Noto Sans KR', sans-serif; font-size: .75rem; color: var(--mute); margin-left: .8rem; vertical-align: middle; letter-spacing: 0; }
.st-key-home_title button:hover p, .st-key-home_title button:hover p::after { color: var(--lime); }

.stApp .hero.compact .hero-title { font-size: 1.6rem !important; }
.hero-chips { display: flex; flex-wrap: wrap; gap: .4rem; margin-top: .8rem; }
.hero-chips span { border: 1px solid var(--line2); color: var(--soft); font-size: .76rem; padding: .2rem .6rem; }
.hero-chips span b { color: var(--lime); font-weight: 500; margin-right: .3rem; font-family: var(--num); letter-spacing: .08em; font-size: .85rem; }

/* ---------- 첫 화면 ---------- */
.home-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; background: var(--line); border: 1px solid var(--line); margin: 0 0 1.4rem; }
.home-stats > div { background: var(--panel); padding: .9rem 1.1rem .8rem; min-width: 0; }
.home-stats .n { font-family: var(--num); font-size: 2.4rem; line-height: .95; color: var(--text); white-space: nowrap; }
.home-stats .n.hi { color: var(--lime); }
.home-stats .l { font-size: .75rem; color: var(--mute); margin-top: .25rem; }
.sec-label { font-family: var(--num); letter-spacing: .24em; font-size: .9rem; color: var(--mute); margin: .2rem 0 .6rem; }
.sec-label b { color: var(--soft); font-family: 'Noto Sans KR', sans-serif; font-weight: 500; letter-spacing: .02em; font-size: .82rem; margin-left: .5rem; }

[class*="st-key-qs_card_"] { background: var(--panel); border-top: 2px solid var(--line2); padding: 1rem 1.1rem .7rem; gap: .2rem !important; height: 100%; }
[class*="st-key-qs_card_"]:hover { border-top-color: var(--lime); }
.qs-kicker { font-family: var(--num); letter-spacing: .22em; font-size: .82rem; color: var(--lime); }
.qs-title { font-weight: 700; color: var(--text); font-size: 1.02rem; margin: .1rem 0 .15rem; }
.qs-desc { color: var(--mute); font-size: .8rem; line-height: 1.5; padding-bottom: .8rem; }
.st-key-scrolltop { display: none; }
[class*="st-key-qs_card_"] .stButton > button {
    width: 100%; justify-content: flex-start; text-align: left; min-height: 40px;
    background: transparent !important; border: 0 !important; border-top: 1px solid var(--line) !important; border-radius: 0 !important;
    padding: .5rem 0 !important; box-shadow: none !important; color: var(--soft) !important;
}
[class*="st-key-qs_card_"] .stButton > button > div { justify-content: flex-start !important; width: 100%; }
[class*="st-key-qs_card_"] .stButton > button p { font-size: .9rem; text-align: left !important; margin: 0; color: inherit !important; }
[class*="st-key-qs_card_"] .stButton > button p::after { content: "  →"; color: var(--line2); }
[class*="st-key-qs_card_"] .stButton > button:hover { color: var(--lime) !important; }
[class*="st-key-qs_card_"] .stButton > button:hover p::after { color: var(--lime); }

.leaders { background: var(--panel); border: 1px solid var(--line); margin: 1.4rem 0 .4rem; }
.leaders-head { display: flex; justify-content: space-between; align-items: baseline; gap: 1rem; padding: .9rem 1.1rem .5rem; }
.leaders-head .t { font-family: var(--num); letter-spacing: .22em; font-size: .9rem; color: var(--mute); }
.leaders-head .t b { font-family: 'Noto Sans KR', sans-serif; letter-spacing: .02em; font-weight: 500; color: var(--soft); font-size: .85rem; margin-left: .5rem; }
.leaders-head .s { font-size: .75rem; color: var(--mute); }

/* ---------- 순위형 결과 (리더보드) ---------- */
.lb { margin: .4rem 0 .6rem; }
.lb-row { display: grid; grid-template-columns: 2.2rem minmax(0, 1fr) minmax(0, 38%) 4.2rem; align-items: center; gap: .8rem; padding: .5rem 1.1rem; border-top: 1px solid var(--line); }
.lb .lb-row:first-child { border-top: 0; }
.lb-rank { font-family: var(--num); font-size: 1.35rem; color: var(--mute); }
.lb-row.top .lb-rank { color: var(--lime); }
.lb-name { min-width: 0; color: var(--text); font-size: .95rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.lb-name small { display: block; color: var(--mute); font-size: .72rem; margin-top: .05rem; overflow: hidden; text-overflow: ellipsis; }
.lb-track { height: 8px; background: #0F1F18; }
.lb-fill { height: 100%; background: var(--line2); }
.lb-row.top .lb-fill { background: var(--lime); }
.lb-val { font-family: var(--num); font-size: 1.6rem; text-align: right; color: var(--text); white-space: nowrap; }
.lb-val i { font-style: normal; font-family: 'Noto Sans KR', sans-serif; font-size: .72rem; color: var(--mute); margin-left: .15rem; }
.lb-more { padding: .4rem 1.1rem .6rem; font-size: .75rem; color: var(--mute); border-top: 1px solid var(--line); }
[data-testid="stChatMessageContent"] .lb { margin: .6rem -1.5rem .4rem; }
[data-testid="stChatMessageContent"] .lb-row { padding-left: 1.5rem; padding-right: 1.5rem; }

/* ---------- 경기 목록 결과 ---------- */
.mlist { margin: .6rem -1.5rem .4rem; }
.mlist .rrow { padding-left: 1.5rem; padding-right: 1.5rem; }
.mlist .lb-more { padding-left: 1.5rem; }

/* ---------- 답변 메타 정보 ---------- */
.meta-row { display: flex; flex-wrap: wrap; gap: .35rem; margin: 0 0 .8rem; }
.meta-row span { font-size: .72rem; color: var(--mute); border: 1px solid var(--line); padding: .15rem .55rem; line-height: 1.5; }
.meta-row span.ok { color: var(--lime); border-color: #3D5A1A; }
.meta-row span.warn { color: #FF8A7A; border-color: #7A2A22; }

/* 답변 패널 안의 카드는 패널과 하나로 (라임 선 겹침 제거) */
[data-testid="stChatMessageContent"] .pcard { border-top: 0; background: transparent; margin: -.4rem -1.5rem .6rem; }

/* 진행 중 경기 (LIVE) */
.live-box { background: var(--panel); border: 1px solid var(--line); border-top: 2px solid var(--lime); margin: 0 0 1.4rem; }
.live-head { display: flex; align-items: center; gap: .6rem; flex-wrap: wrap; padding: .8rem 1.1rem .5rem; }
.live-head .t { font-family: var(--num); letter-spacing: .22em; font-size: .95rem; color: var(--lime); }
.live-head .t b { font-family: 'Noto Sans KR', sans-serif; letter-spacing: .02em; font-weight: 500; color: var(--soft); font-size: .85rem; margin-left: .5rem; }
.live-head .s { margin-left: auto; font-size: .72rem; color: var(--mute); }
.live-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--lime); box-shadow: 0 0 0 0 rgba(200,255,61,.6); animation: livepulse 1.6s infinite; }
@keyframes livepulse { 0% { box-shadow: 0 0 0 0 rgba(200,255,61,.55); } 70% { box-shadow: 0 0 0 9px rgba(200,255,61,0); } 100% { box-shadow: 0 0 0 0 rgba(200,255,61,0); } }
.live-row { display: grid; grid-template-columns: 70px minmax(0, 1fr) 90px minmax(0, 1fr); gap: .8rem; align-items: center; padding: .55rem 1.1rem; border-top: 1px solid var(--line); font-size: .92rem; color: var(--soft); }
.live-row .live-min { font-family: var(--num); color: var(--lime); font-size: 1.05rem; letter-spacing: .05em; }
.live-row .rh { text-align: right; }
.live-row .rh, .live-row .ra { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; word-break: keep-all; }
.live-row .rs { font-family: var(--num); font-size: 1.5rem; text-align: center; color: var(--lime); letter-spacing: .06em; }

/* 사이드바 추천 질문 그룹 */
.side-group { font-size: .72rem; color: var(--lime) !important; margin: .9rem 0 .1rem; letter-spacing: .04em; }
[data-testid="stSidebar"] .stButton > button { min-height: 38px; padding: .45rem 0 !important; font-size: .88rem; }

@media (max-width: 900px) {
    .stApp { background-image: none; }
}
@media (max-width: 640px) {
    .block-container { padding-top: 3.6rem !important; }
    .st-key-adminlink { margin-bottom: -2.2rem; }
    [data-testid="stHeader"] { background: rgba(7, 17, 13, .94); }
    .leaders-head { flex-direction: column; gap: .2rem; }
    .h2h-team .pcard-name.sm { font-size: 1.15rem; }
    .live-head .s { margin-left: 0; width: 100%; }
    .live-row { grid-template-columns: 2.1rem minmax(0, 1fr) auto minmax(0, 1fr); gap: .35rem; padding: .5rem .8rem; font-size: .78rem; }
    .live-row .live-min { font-size: .95rem; }
    .live-row .rs { font-size: 1.25rem; }
    .home-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .home-stats .n { font-size: 2rem; }
    .lb-row { grid-template-columns: 1.8rem minmax(0, 1fr) 3.6rem; gap: .5rem; }
    .lb-track { display: none; }
    [data-testid="stChatMessageContent"] .lb, .mlist, [data-testid="stChatMessageContent"] .pcard { margin-left: -1.1rem; margin-right: -1.1rem; }
    [data-testid="stChatMessageContent"] .lb-row, .mlist .rrow { padding-left: 1.1rem; padding-right: 1.1rem; }
}

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

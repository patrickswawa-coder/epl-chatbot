"""답변 화면 보조 블록(메타 정보, 순위형 결과, 경기 목록, 첫 화면 데이터)을 HTML 문자열로 만든다.

cards.py와 같은 이유로 모든 HTML은 줄바꿈 없이 한 줄로 이어 붙인다.
(st.markdown에서 빈 줄이나 4칸 들여쓰기가 있으면 코드 블록으로 깨진다)
"""
from __future__ import annotations

import sqlite3
from html import escape

import pandas as pd

from database.aliases import PLAYERS, TEAMS

_KO = {db: ko for ko, _, db in PLAYERS}
_KO.update({db: ko for ko, _, db in TEAMS})

_UNITS = [
    ("assist", "도움"), ("goal", "골"), ("win", "승"), ("draw", "무"), ("loss", "패"), ("lose", "패"),
    ("match", "경기"), ("game", "경기"), ("played", "경기"), ("card", "장"), ("point", "점"), ("minute", "분"),
]


def ko_name(value) -> str:
    """DB의 영문 선수·팀 이름을 한국어로(사전에 있으면). 없으면 그대로."""
    text = str(value)
    return _KO.get(text, text)


def _unit(col: str) -> str:
    low = col.lower()
    for key, unit in _UNITS:
        if key in low:
            return unit
    return ""


def _fmt(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return escape(str(v))
    return f"{int(f):,}" if f.is_integer() else f"{f:,.2f}"


# ---------------------------------------------------------------
# 답변 위 메타 정보 (출처 · 처리 경로 · 행 수 · 걸린 시간)
# ---------------------------------------------------------------

def meta_html(result: dict) -> str:
    if not result or result.get("error"):
        return ""
    tags = []
    src = result.get("answer_source")
    if src == "db":
        tags.append('<span class="ok">DB 조회 결과</span>')
    elif src == "gpt_fallback":
        tags.append('<span class="warn">GPT 일반 지식 · 참고용</span>')
    if result.get("fast_path"):
        tags.append("<span>빠른 경로 · 고정 SQL</span>")
    elif result.get("sql"):
        tags.append("<span>AI가 만든 SQL</span>")
    if result.get("rows"):
        tags.append(f"<span>{len(result['rows'])}행 조회</span>")
    ms = result.get("elapsed_ms")
    if isinstance(ms, (int, float)) and ms > 0:
        tags.append(f"<span>{ms / 1000:.2f}초</span>" if ms < 1000 else f"<span>{ms / 1000:.1f}초</span>")
    return f'<div class="meta-row">{"".join(tags)}</div>' if tags else ""


# ---------------------------------------------------------------
# 순위형 결과: 이름 + 숫자 (예: 득점 TOP 10, 시간대별 골)
# ---------------------------------------------------------------

def leaderboard_html(df: pd.DataFrame, limit: int = 10) -> str | None:
    if df is None or not (1 <= len(df) <= 30):
        return None
    num_cols = df.select_dtypes(include="number").columns.tolist()
    text_cols = [c for c in df.columns if c not in num_cols]
    if not num_cols or not (1 <= len(text_cols) <= 2):
        return None
    label_col, value_col = text_cols[0], num_cols[0]
    sub_col = text_cols[1] if len(text_cols) == 2 else None
    if df[label_col].duplicated().any():
        return None

    values = pd.to_numeric(df[value_col], errors="coerce").fillna(0)
    top = values.max() or 1
    unit = _unit(str(value_col))
    rows = []
    for i, (idx, row) in enumerate(df.head(limit).iterrows()):
        v = values.loc[idx]
        is_top = v == top
        label = str(row[label_col])
        ko = ko_name(label)
        subs = []
        if ko != label:
            subs.append(label)
        if sub_col is not None and pd.notna(row[sub_col]):
            subs.append(ko_name(row[sub_col]))
        sub = f'<small>{escape(" · ".join(subs))}</small>' if subs else ""
        pct = max(2, round(v / top * 100)) if top > 0 else 2
        rows.append(
            f'<div class="lb-row{" top" if is_top else ""}"><span class="lb-rank">{i + 1:02d}</span>'
            f'<div class="lb-name">{escape(ko)}{sub}</div>'
            f'<div class="lb-track"><div class="lb-fill" style="width:{pct}%"></div></div>'
            f'<span class="lb-val">{_fmt(row[value_col])}<i>{escape(unit)}</i></span></div>'
        )
    more = ""
    if len(df) > limit:
        more = f'<div class="lb-more">외 {len(df) - limit}개 · 전체는 아래 조회 결과에서 볼 수 있습니다</div>'
    return f'<div class="lb">{"".join(rows)}{more}</div>'


# ---------------------------------------------------------------
# 경기 목록 결과: 날짜 · 홈팀 · 스코어 · 원정팀
# ---------------------------------------------------------------

def _find(cols: list[str], *must: str, any_of: tuple[str, ...] = ()) -> str | None:
    for c in cols:
        low = c.lower()
        if all(m in low for m in must) and (not any_of or any(a in low for a in any_of)):
            return c
    return None


def matchlist_html(df: pd.DataFrame, limit: int = 10) -> str | None:
    if df is None or len(df) < 1:
        return None
    cols = [str(c) for c in df.columns]
    hs = _find(cols, "home", any_of=("score", "goal"))
    as_ = _find(cols, "away", any_of=("score", "goal"))
    ht = _find(cols, "home", any_of=("team", "club")) or ("home" if "home" in cols else None)
    at = _find(cols, "away", any_of=("team", "club")) or ("away" if "away" in cols else None)
    dt = _find(cols, "date")
    if not (hs and as_ and ht and at) or hs in (ht, at) or as_ in (ht, at):
        return None
    rows = []
    for _, r in df.head(limit).iterrows():
        try:
            h, a = int(r[hs]), int(r[as_])
            score = f"{h} - {a}"
        except (TypeError, ValueError):
            score = "vs"
        date = str(r[dt])[:10] if dt and pd.notna(r[dt]) else ""
        rows.append(
            f'<div class="rrow"><span class="rd">{escape(date)}</span>'
            f'<span class="rh">{escape(ko_name(r[ht]))}</span>'
            f'<span class="rs">{escape(score)}</span>'
            f'<span class="ra">{escape(ko_name(r[at]))}</span></div>'
        )
    more = ""
    if len(df) > limit:
        more = f'<div class="lb-more">외 {len(df) - limit}경기 · 전체는 아래 조회 결과에서 볼 수 있습니다</div>'
    return f'<div class="mlist">{"".join(rows)}{more}</div>'


# ---------------------------------------------------------------
# 첫 화면 데이터
# ---------------------------------------------------------------

def home_numbers(db_path) -> dict:
    out = {"matches": 0, "goals": 0, "seasons": 0, "last_date": ""}
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            cur = conn.cursor()
            out["matches"], out["seasons"], last = cur.execute(
                "SELECT COUNT(*), COUNT(DISTINCT season), MAX(date) FROM matches WHERE home_score IS NOT NULL"
            ).fetchone()
            out["last_date"] = (last or "")[:10]
            out["goals"] = cur.execute("SELECT COUNT(*) FROM match_events WHERE event_type = 'goal'").fetchone()[0]
    except Exception:
        pass
    return out


def home_stats_html(n: dict) -> str:
    last = n.get("last_date") or "-"
    last_short = last[2:].replace("-", ".") if len(last) == 10 else last
    return (
        '<div class="home-stats">'
        f'<div><div class="n hi">{n["matches"]:,}</div><div class="l">경기 기록</div></div>'
        f'<div><div class="n">{n["goals"]:,}</div><div class="l">골 기록</div></div>'
        f'<div><div class="n">{n["seasons"]:,}</div><div class="l">시즌 (2014-15~)</div></div>'
        f'<div><div class="n">{escape(last_short)}</div><div class="l">마지막 경기 반영일</div></div>'
        "</div>"
    )


def season_leaders_html(db_path, limit: int = 5) -> str:
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            cur = conn.cursor()
            season, played, last = cur.execute(
                "SELECT season, COUNT(*), MAX(date) FROM matches WHERE home_score IS NOT NULL "
                "AND season = (SELECT MAX(season) FROM matches WHERE home_score IS NOT NULL)"
            ).fetchone()
            rows = cur.execute(
                "SELECT e.player, e.team, COUNT(*) AS goals FROM match_events e "
                "JOIN matches m ON m.match_id = e.match_id "
                "WHERE m.season = ? AND e.event_type = 'goal' AND e.player IS NOT NULL "
                "GROUP BY e.player ORDER BY goals DESC, e.player LIMIT ?",
                (season, limit),
            ).fetchall()
    except Exception:
        return ""
    if not rows:
        return ""
    df = pd.DataFrame(rows, columns=["player", "team", "goals"])
    board = leaderboard_html(df, limit=limit) or ""
    label = f"20{season[:2]}-{season[2:]}" if season and len(season) == 4 else str(season)
    sub = f"{played}경기 진행 · {str(last)[:10]} 기준"
    return (
        '<div class="leaders"><div class="leaders-head">'
        f'<span class="t">TOP SCORERS<b>{escape(label)} 시즌 득점 선두</b></span>'
        f'<span class="s">{escape(sub)}</span></div>'
        f"{board}</div>"
    )

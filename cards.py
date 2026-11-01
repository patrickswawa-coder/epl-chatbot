"""빠른 경로 결과 카드(프로필·시즌별 골·선수 비교·팀 상대전적)를 HTML 문자열로 만든다.

주의: st.markdown으로 그릴 때 빈 줄이나 4칸 이상 들여쓰기가 있으면 코드 블록으로 깨지므로
모든 HTML은 줄바꿈 없이 한 줄로 이어 붙인다. 스타일은 theme.py의 .pcard 계열 클래스.
"""
from __future__ import annotations

from html import escape


def _season_long(code: str) -> str:
    return f"20{code[:2]}-{code[2:]}"


def _fmt(n) -> str:
    return f"{int(n):,}"


def _profile_html(card: dict) -> str:
    seasons = card.get("by_season") or []
    peak = max((g for _, g in seasons), default=0) or 1
    best = set(card.get("best_seasons") or [])
    is_seasons = card.get("type") == "seasons"

    bars = []
    for code, g in seasons:
        hi = " hi" if code in best else ""
        pct = max(4, round(g / peak * 100))
        long_lbl = f"{code[:2]}-{code[2:]}"
        bars.append(
            f'<div class="bcol"><span class="bv{hi}">{g}</span>'
            f'<div class="btrack"><div class="bfill{hi}" style="height:{pct}%"></div></div>'
            f'<span class="bl{hi}"><span class="long">{long_lbl}</span><span class="short">{code[2:]}</span></span></div>'
        )

    kicker = "GOALS BY SEASON · FROM DATABASE" if is_seasons else "PLAYER PROFILE · FROM DATABASE"
    stats = (
        f'<div class="stat3"><div class="cell"><div class="n hi">{_fmt(card["goals"])}</div><div class="l">통산 골</div></div>'
        f'<div class="cell"><div class="n">{_fmt(card["assists"])}</div><div class="l">통산 어시스트</div></div>'
        f'<div class="cell"><div class="n">{_fmt(card["seasons_scored"])}</div><div class="l">골을 넣은 시즌 수</div></div></div>'
    )
    return (
        '<div class="pcard">'
        '<div class="pcard-head"><div>'
        f'<div class="pcard-kicker">{kicker}</div>'
        f'<div class="pcard-name">{escape(card["name_ko"])}</div>'
        f'<div class="pcard-en">{escape(card["name_en"].upper())}</div></div>'
        '<div class="pcard-sub">프리미어리그<br>2014-15 시즌 이후 기록 기준</div></div>'
        f"{stats}"
        '<div class="pcard-sec"><div class="pcard-kicker mute">GOALS BY SEASON · 시즌별 골</div>'
        f'<div class="bars">{"".join(bars)}</div>'
        '<div class="bnote">시즌 종료 연도 기준 (예: 22 = 2021-22)</div></div>'
        "</div>"
    )


def _compare_html(card: dict) -> str:
    a, b = card["players"]
    rows_def = [
        ("통산 골", "goals"),
        ("통산 어시스트", "assists"),
        ("골을 넣은 시즌 수", "seasons_scored"),
        ("한 시즌 최다 골", "best_goals"),
    ]
    rows = []
    for label, key in rows_def:
        va, vb = a[key], b[key]
        top = max(va, vb) or 1
        hia = " hi" if va >= vb else ""
        hib = " hi" if vb >= va else ""
        # 막대는 값(숫자) 자리를 남기기 위해 칸의 70%까지만 쓴다
        wa, wb = max(3, round(va / top * 70)), max(3, round(vb / top * 70))
        rows.append(
            f'<div class="cmp-row"><div class="cmp-label">{label}</div><div class="cmp-bars">'
            f'<div class="cmp-side left"><span class="cv{hia}">{_fmt(va)}</span>'
            f'<div class="cfill{hia}" style="width:{wa}%"></div></div>'
            f'<div class="cmp-side right"><div class="cfill{hib}" style="width:{wb}%"></div>'
            f'<span class="cv{hib}">{_fmt(vb)}</span></div></div></div>'
        )
    return (
        '<div class="pcard">'
        '<div class="pcard-head"><div>'
        '<div class="pcard-kicker">PLAYER COMPARISON · FROM DATABASE</div></div>'
        '<div class="pcard-sub">프리미어리그 · 2014-15 시즌 이후 기록 기준</div></div>'
        '<div class="cmp-names">'
        f'<div class="cmp-name left"><div class="pcard-name sm">{escape(a["name_ko"])}</div><div class="pcard-en">{escape(a["name_en"].upper())}</div></div>'
        f'<div class="cmp-name"><div class="pcard-name sm">{escape(b["name_ko"])}</div><div class="pcard-en">{escape(b["name_en"].upper())}</div></div>'
        "</div>"
        f'{"".join(rows)}'
        "</div>"
    )


def _h2h_html(card: dict) -> str:
    total = card["w"] + card["d"] + card["l"] or 1
    recent = []
    for r in card["recent"]:
        a_goals = r["hs"] if r["a_home"] else r["as"]
        b_goals = r["as"] if r["a_home"] else r["hs"]
        win = " hi" if a_goals > b_goals else ""
        recent.append(
            f'<div class="rrow"><span class="rd">{escape(r["date"])}</span>'
            f'<span class="rh">{escape(r["home"])}</span>'
            f'<span class="rs{win}">{r["hs"]} - {r["as"]}</span>'
            f'<span class="ra">{escape(r["away"])}</span></div>'
        )
    return (
        '<div class="pcard">'
        '<div class="pcard-head"><div><div class="pcard-kicker">HEAD TO HEAD · FROM DATABASE</div></div>'
        f'<div class="pcard-sub">프리미어리그 · 2014-15 시즌 이후 {card["total"]}경기</div></div>'
        '<div class="h2h-top">'
        f'<div class="h2h-team"><div class="pcard-name sm">{escape(card["a"])}</div><div class="pcard-en">{escape(card["a_en"].upper())}</div></div>'
        f'<div class="h2h-score"><span class="hi">{card["gf"]}</span><i>:</i><span>{card["ga"]}</span></div>'
        f'<div class="h2h-team r"><div class="pcard-name sm">{escape(card["b"])}</div><div class="pcard-en">{escape(card["b_en"].upper())}</div></div>'
        "</div>"
        '<div class="h2h-cap">통산 득점 합계</div>'
        '<div class="wdl-wrap"><div class="wdl">'
        f'<div class="w" style="flex:{card["w"]} 1 0"></div>'
        f'<div class="d" style="flex:{card["d"]} 1 0"></div>'
        f'<div class="l" style="flex:{card["l"]} 1 0"></div></div>'
        '<div class="wdl-l">'
        f'<span><b class="hi">{card["w"]}</b> {escape(card["a"])} 승</span>'
        f'<span><b>{card["d"]}</b> 무</span>'
        f'<span><b>{card["l"]}</b> {escape(card["b"])} 승</span></div></div>'
        '<div class="pcard-sec"><div class="pcard-kicker mute">RECENT 5 · 최근 5경기</div>'
        f'<div class="recent">{"".join(recent)}</div></div>'
        "</div>"
    )


def card_html(card: dict | None) -> str | None:
    """카드 데이터 -> HTML. 알 수 없는 유형이면 None."""
    if not card:
        return None
    kind = card.get("type")
    if kind in ("profile", "seasons"):
        return _profile_html(card)
    if kind == "compare":
        return _compare_html(card)
    if kind == "h2h":
        return _h2h_html(card)
    return None

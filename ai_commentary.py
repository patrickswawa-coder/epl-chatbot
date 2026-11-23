"""
AI 해설: 빠른 경로 카드(선수 프로필·시즌별 골, 선수 비교, 팀 상대전적) 아래에 GPT가 쓴 짧은 해설을 붙인다.

- 사실은 코드가 DB에서 직접 모은다 (GPT가 SQL을 만들거나 숫자를 계산하지 않는다).
- GPT는 그 [기록]만 가지고 3~4문장의 기사형 해설을 쓴다.
- 해설 속 숫자가 [기록]에 하나라도 없으면 한 번 다시 쓰게 하고, 그래도 틀리면 해설을 보여주지 않는다.
- 같은 기록이면 같은 해설을 재사용한다 (비용 절약, 답 일관성).
"""
from __future__ import annotations

import hashlib
import re
import sqlite3

from database.aliases import PLAYERS, TEAMS
from database.db_utils import DB_PATH, EVENT_SEASON_FROM, MATCH_SEASON_FROM

SUPPORTED = {"profile", "seasons", "compare", "h2h"}
_PLAYER_KO = {db: ko for ko, _, db in PLAYERS}
_TEAM_KO = {db: ko for ko, _, db in TEAMS}
_cache: dict[str, dict] = {}

SYSTEM_PROMPT = """
당신은 EPL 기록 해설가입니다. 사용자 메시지의 [기록]에 적힌 사실만 사용해 한국어 해설을 씁니다.

규칙
1. [기록]에 없는 숫자, 날짜, 사실(이적, 국적, 현재 소속팀, 수상, 경기 장면, 감독)을 절대 쓰지 마세요.
2. 숫자는 [기록]에 있는 값을 그대로 쓰세요. 새로 계산한 비율·평균·합계·차이는 쓰지 마세요.
3. 3~4문장, 한 문단. 기사처럼 자연스럽게 쓰되 과장하지 마세요. 목록·마크다운·이모지는 쓰지 마세요.
4. 기록 기간(예: "2014-15 시즌 이후 기록 기준")을 한 번 언급하세요.
""".strip()


def _season(code: str) -> str:
    return f"20{code[:2]}-{code[2:]}"


def _team(db: str) -> str:
    return _TEAM_KO.get(db, db)


def _player(db: str) -> str:
    return _PLAYER_KO.get(db, db)


def _conn():
    return sqlite3.connect(DB_PATH.resolve().as_uri() + "?mode=ro", uri=True)


# ---------------------------------------------------------------- 사실 모으기
def _player_extra(conn, db: str) -> list[str]:
    lines = []
    teams = conn.execute(
        "SELECT team, COUNT(*) FROM match_events WHERE player = ? AND event_type = 'goal' "
        "GROUP BY team ORDER BY 2 DESC", (db,)).fetchall()
    if teams:
        lines.append("골을 넣은 소속팀: " + ", ".join(f"{_team(t)} {n}골" for t, n in teams if t))
    opp = conn.execute(
        "SELECT CASE WHEN e.team = m.home_team THEN m.away_team ELSE m.home_team END AS opp, COUNT(*) "
        "FROM match_events e JOIN matches m ON m.match_id = e.match_id "
        "WHERE e.player = ? AND e.event_type = 'goal' GROUP BY opp ORDER BY 2 DESC, opp LIMIT 1", (db,)).fetchone()
    if opp and opp[0]:
        lines.append(f"가장 많은 골을 넣은 상대 팀: {_team(opp[0])} ({opp[1]}골)")
    bucket = conn.execute(
        "SELECT CASE WHEN minute <= 15 THEN '0~15분' WHEN minute <= 30 THEN '16~30분' "
        "WHEN minute <= 45 THEN '31~45분' WHEN minute <= 60 THEN '46~60분' WHEN minute <= 75 THEN '61~75분' "
        "ELSE '76분 이후' END AS b, COUNT(*) FROM match_events WHERE player = ? AND event_type = 'goal' "
        "AND minute IS NOT NULL GROUP BY b ORDER BY 2 DESC LIMIT 1", (db,)).fetchone()
    if bucket:
        lines.append(f"골이 가장 많이 나온 시간대: {bucket[0]} ({bucket[1]}골)")
    partner = conn.execute(
        "SELECT assist_player, COUNT(*) FROM match_events WHERE player = ? AND event_type = 'goal' "
        "AND assist_player IS NOT NULL AND assist_player != '' GROUP BY assist_player ORDER BY 2 DESC LIMIT 1",
        (db,)).fetchone()
    if partner:
        lines.append(f"이 선수의 골을 가장 많이 도운 동료: {_player(partner[0])} ({partner[1]}번)")
    helped = conn.execute(
        "SELECT player, COUNT(*) FROM match_events WHERE assist_player = ? AND event_type = 'goal' "
        "GROUP BY player ORDER BY 2 DESC LIMIT 1", (db,)).fetchone()
    if helped:
        lines.append(f"이 선수가 가장 많이 도운 동료: {_player(helped[0])} ({helped[1]}골)")
    return lines


def _player_lines(p: dict) -> list[str]:
    lines = [
        f"선수: {p['name_ko']} ({p['name_en']})",
        f"통산 골: {p['goals']}",
        f"통산 어시스트: {p['assists']}",
        f"골을 넣은 시즌 수: {p['seasons_scored']}",
    ]
    if p.get("best_seasons"):
        lines.append(f"한 시즌 최다 골: {p['best_goals']} ({', '.join(_season(s) for s in p['best_seasons'])} 시즌)")
    elif p.get("best_goals"):
        lines.append(f"한 시즌 최다 골: {p['best_goals']}")
    if p.get("by_season"):
        lines.append("시즌별 골: " + ", ".join(f"{_season(s)} {g}골" for s, g in p["by_season"]))
    return lines


def build_facts(card: dict) -> dict | None:
    """카드에 맞는 [기록] 문장들을 DB에서 모은다. 지원하지 않는 카드면 None."""
    kind = (card or {}).get("type")
    if kind not in SUPPORTED:
        return None
    conn = _conn()
    try:
        if kind in ("profile", "seasons"):
            lines = [f"기록 기간: 프리미어리그 {EVENT_SEASON_FROM} 시즌 이후"] + _player_lines(card)
            lines += _player_extra(conn, card["name_en"])
            key = card["name_en"]
        elif kind == "compare":
            a, b = card["players"]
            lines = [f"기록 기간: 프리미어리그 {EVENT_SEASON_FROM} 시즌 이후"]
            for p in (a, b):
                lines += _player_lines(p)
            lines.append(f"두 선수의 통산 골 차이: {abs(a['goals'] - b['goals'])}")
            lines.append(f"두 선수의 통산 어시스트 차이: {abs(a['assists'] - b['assists'])}")
            key = f"{a['name_en']}|{b['name_en']}"
        else:  # h2h
            lines = _h2h_lines(conn, card)
            key = f"{card['a_en']}|{card['b_en']}"
    finally:
        conn.close()
    text = "\n".join(f"- {line}" for line in lines)
    return {"kind": kind, "key": key, "text": text}


def _h2h_lines(conn, card: dict) -> list[str]:
    a, b, da, db_ = card["a"], card["b"], card["a_en"], card["b_en"]
    lines = [
        f"기록 기간: 프리미어리그 {MATCH_SEASON_FROM} 시즌 이후 경기 결과",
        f"맞대결: {a} 대 {b}, 모두 {card['total']}경기",
        f"{a} 승리 {card['w']}, 무승부 {card['d']}, {b} 승리 {card['l']}",
        f"득점: {a} {card['gf']}골, {b} {card['ga']}골",
    ]
    if card.get("recent"):
        rec = [f"{r['date']} {r['home']} {r['hs']}-{r['as']} {r['away']}" for r in card["recent"]]
        lines.append("최근 맞대결(최신순): " + " / ".join(rec))
    rows = conn.execute(
        "SELECT match_id, date, home_team, away_team, home_score, away_score FROM matches "
        "WHERE ((home_team = ? AND away_team = ?) OR (home_team = ? AND away_team = ?)) "
        "AND home_score IS NOT NULL ORDER BY date DESC", (da, db_, db_, da)).fetchall()
    for team_db, label in ((da, a), (db_, b)):
        best = None
        for _, date, home, away, hs, as_ in rows:
            mine, theirs = (hs, as_) if home == team_db else (as_, hs)
            if mine > theirs and (best is None or mine - theirs > best[0]):
                best = (mine - theirs, date[:10], _team(home), hs, as_, _team(away))
        if best:
            lines.append(f"{label}의 가장 큰 승리: {best[1]} {best[2]} {best[3]}-{best[4]} {best[5]}")
    if rows:
        mid, date, home, away, hs, as_ = rows[0]
        goals = conn.execute(
            "SELECT minute, player, team FROM match_events WHERE match_id = ? AND event_type IN ('goal', 'own_goal') "
            "ORDER BY minute", (mid,)).fetchall()
        if goals:
            scorers = ", ".join(f"{_player(p)}({m}분)" for m, p, _ in goals if p)
            lines.append(f"가장 최근 맞대결 득점자: {date[:10]} {_team(home)} {hs}-{as_} {_team(away)} - {scorers}")
    return lines


# ---------------------------------------------------------------- 검증
def _numbers(text: str) -> set[float]:
    out = set()
    for m in re.findall(r"\d[\d,]*\.?\d*", text or ""):
        try:
            out.add(float(m.replace(",", "").rstrip(".")))
        except ValueError:
            pass
    return out


def unsupported_numbers(commentary: str, facts_text: str) -> list[str]:
    """해설에 나왔지만 [기록]에는 없는 숫자 목록."""
    allowed = _numbers(facts_text)
    bad = sorted(_numbers(commentary) - allowed)
    return [f"{x:g}" for x in bad]


# ---------------------------------------------------------------- 생성
def _default_chat():
    from text_to_sql import OPENAI_MODEL, client

    if client is None:
        return None

    def chat(messages):
        resp = client.chat.completions.create(model=OPENAI_MODEL, messages=messages, temperature=0.3)
        return resp.choices[0].message.content or ""

    return chat


def generate_commentary(card: dict, chat=None) -> dict:
    """{'ok', 'text', 'facts', 'error'}를 돌려준다. ok가 False면 text는 비어 있다."""
    facts = build_facts(card)
    if facts is None:
        return {"ok": False, "text": "", "facts": "", "error": "해설을 지원하지 않는 결과입니다."}
    cache_key = hashlib.sha1(f"{facts['kind']}|{facts['text']}".encode()).hexdigest()
    if cache_key in _cache:
        return _cache[cache_key]

    chat = chat or _default_chat()
    if chat is None:
        return {"ok": False, "text": "", "facts": facts["text"], "error": "OpenAI 키가 없어 해설을 만들 수 없습니다."}

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"[기록]\n{facts['text']}\n\n위 기록으로 해설을 써 주세요."},
    ]
    error = ""
    for _ in range(2):  # 처음 + 숫자가 틀렸을 때 한 번 더
        try:
            text = (chat(messages) or "").strip()
        except Exception as exc:
            return {"ok": False, "text": "", "facts": facts["text"], "error": f"AI 호출 실패: {type(exc).__name__}"}
        bad = unsupported_numbers(text, facts["text"])
        if text and not bad:
            result = {"ok": True, "text": text, "facts": facts["text"], "error": ""}
            if len(_cache) > 300:
                _cache.clear()
            _cache[cache_key] = result
            return result
        error = f"기록에 없는 숫자({', '.join(bad[:5])})가 들어가 해설을 표시하지 않습니다." if bad else "빈 응답"
        messages += [
            {"role": "assistant", "content": text},
            {"role": "user", "content": f"[기록]에 없는 숫자 {', '.join(bad)}를 썼습니다. [기록]의 숫자만 써서 다시 써 주세요."},
        ]
    return {"ok": False, "text": "", "facts": facts["text"], "error": error}

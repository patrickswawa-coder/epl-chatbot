"""
빠른 경로(FAST PATH): 자주 묻는 질문은 GPT 없이, 검증된 고정 SQL로 DB를 직접 조회한다.

대상 유형 (질문이 정확히 맞을 때만 처리하고, 애매하면 None을 돌려 기존 GPT 경로로 넘긴다)
  - 선수 1명 + "골/득점 몇 개"            -> goals    (큰 숫자)
  - 선수 1명 + "어시스트 몇 개"            -> assists  (큰 숫자)
  - 선수 1명 + "알려줘/프로필/기록"         -> profile  (카드)
  - 선수 1명 + "시즌별 골"                 -> seasons  (카드)
  - 선수 2명 + "비교"                      -> compare  (카드)
  - 팀 2개   + "상대전적/맞대결/전적"       -> h2h      (카드)

안전 규칙
  - 질문에 시즌·연도·"이번/최근" 같은 기간 표현이나 홈/원정/상대 같은 추가 조건이 있으면 처리하지 않는다.
  - 선수·팀 이름은 aliases.py 사전으로만 인식한다. DB에 기록이 없으면 처리하지 않는다.
  - 모든 숫자는 DB 조회값이며 문장도 코드가 직접 만든다 (GPT가 쓰지 않는다).
"""
from __future__ import annotations

import re
import sqlite3

from database.aliases import ALIAS, PLAYERS, TEAMS, _FIND, season_codes
from database.db_utils import DB_PATH

NOTE_RANGE = "\n\n※ 데이터베이스에 수록된 2014-15 시즌 이후 기록 기준입니다."

# 이 표현이 있으면 단순 조회가 아니므로 빠른 경로를 쓰지 않는다
_EXCLUDE = re.compile(
    r"시간|분에|전반|후반|처음|마지막|최초|가장|최다|최고|최저|순위|랭킹|언제|경기|홈|원정|상대|"
    r"페널티|패널티|헤더|발로|연속|해트트릭|평균|비율|이상|이하|넘|동안|사이|때|팀|우승|"
    r"골키퍼|골대|리그컵|FA컵|챔피언스|어디|몇 번째|\bvs\b"
)
_PERIOD = re.compile(r"이번|올해|올 시즌|작년|지난|최근|현재|지금|어제|오늘|20\d{2}|\d{2}\s*[-/]\s*\d{2}")
_GOAL = re.compile(r"골|득점")
_ASSIST = re.compile(r"어시스트|도움|어시")
_COUNT = re.compile(r"몇|개수|갯수|총|통산|합계|얼마|알려|보여|(?<!선)수|넣었|기록했")
_PROFILE = re.compile(r"프로필|소개|기록|스탯|성적|알려|정보")
_SEASONS = re.compile(r"시즌\s?별|매\s?시즌|해마다|연도별|년도별")
_COMPARE = re.compile(r"비교|대결|누가\s?더\s?(많|넣)|둘\s?중|중\s?.*더\s?(많|넣)")
_H2H = re.compile(r"상대\s?전적|맞대결|전적|h2h|H2H")

_PLAYER_EN = {db: ko for ko, _, db in PLAYERS}
_TEAM_KO = {db: ko for ko, _, db in TEAMS}


# ---------------------------------------------------------------- 공통 도우미
def _josa(word: str, with_final: str, without_final: str) -> str:
    """받침 유무에 따라 조사 선택 (예: 아스날+과, 맨시티+와)."""
    ch = word[-1]
    if "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 != 0:
        return word + with_final
    return word + without_final


def _season_label(code: str) -> str:
    return f"20{code[:2]}-{code[2:]}"


def _conn():
    conn = sqlite3.connect(DB_PATH.resolve().as_uri() + "?mode=ro", uri=True)
    return conn


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _entities(question: str) -> list[tuple[str, str, str]]:
    """질문에 나온 (종류, 한글이름, DB이름) 목록 (등장 순서, 중복 제거)."""
    out, seen = [], set()
    for m in _FIND.finditer(question):
        kind, ko, db = ALIAS[m.group(0)]
        if db not in seen:
            seen.add(db)
            out.append((kind, ko, db))
    return out


def _player_stats(conn, db: str) -> dict | None:
    goals = conn.execute(
        "SELECT COUNT(*) FROM match_events WHERE player = ? AND event_type = 'goal'", (db,)
    ).fetchone()[0]
    assists = conn.execute(
        "SELECT COUNT(*) FROM match_events WHERE assist_player = ? AND event_type = 'goal'", (db,)
    ).fetchone()[0]
    if goals == 0 and assists == 0:
        return None
    by_season = conn.execute(
        "SELECT m.season, COUNT(*) FROM match_events e JOIN matches m ON m.match_id = e.match_id "
        "WHERE e.player = ? AND e.event_type = 'goal' GROUP BY m.season ORDER BY m.season",
        (db,),
    ).fetchall()
    best = max((g for _, g in by_season), default=0)
    best_seasons = [s for s, g in by_season if g == best] if best else []
    return {
        "goals": goals,
        "assists": assists,
        "by_season": [(s, g) for s, g in by_season],
        "seasons_scored": len(by_season),
        "best_goals": best,
        "best_seasons": best_seasons,
    }


def _sql_goals(db: str) -> str:
    return f"SELECT COUNT(*) AS goal_count FROM match_events WHERE player = {_quote(db)} AND event_type = 'goal'"


def _sql_assists(db: str) -> str:
    return f"SELECT COUNT(*) AS assist_count FROM match_events WHERE assist_player = {_quote(db)} AND event_type = 'goal'"


def _sql_seasons(db: str) -> str:
    return (
        "SELECT m.season, COUNT(*) AS goals FROM match_events e JOIN matches m ON m.match_id = e.match_id "
        f"WHERE e.player = {_quote(db)} AND e.event_type = 'goal' GROUP BY m.season ORDER BY m.season"
    )


def _base_result(kind: str, sql: str) -> dict:
    return {
        "sql": f"-- FAST PATH: {kind} (GPT 호출 없이 고정 SQL로 조회)\n{sql}",
        "columns": [],
        "rows": [],
        "answer": None,
        "answer_source": "db",
        "insight": None,
        "followups": [],
        "error": None,
        "error_code": None,
        "fast_path": kind,
        "card": None,
    }


# ---------------------------------------------------------------- 유형별 처리
def _single_player(question: str, ko: str, db: str) -> dict | None:
    q = question
    if _EXCLUDE.search(q):
        return None
    goal, assist = bool(_GOAL.search(q)), bool(_ASSIST.search(q))

    conn = _conn()
    try:
        st = _player_stats(conn, db)
    finally:
        conn.close()
    if not st:
        return None

    followups = [f"{ko} 시즌별 골 수", f"{ko} 어시스트는 몇 개야?"]

    # 시즌별 골
    if _SEASONS.search(q) and not assist:
        res = _base_result("seasons", _sql_seasons(db))
        res["columns"] = ["시즌", "골 수"]
        res["rows"] = [(_season_label(s), g) for s, g in st["by_season"]]
        res["answer"] = f"{ko} 선수의 시즌별 골 수입니다. 통산 {st['goals']}골입니다." + NOTE_RANGE
        res["card"] = _profile_card(ko, db, st, kind="seasons")
        res["insight"] = _best_note(st)
        res["followups"] = [f"{ko} 알려줘", f"{ko} 어시스트는 몇 개야?"]
        return res

    # 골 + 어시스트를 함께 물으면 프로필
    if goal and assist:
        return _profile(ko, db, st)

    if goal and _COUNT.search(q):
        res = _base_result("goals", _sql_goals(db))
        res["columns"], res["rows"] = ["goal_count"], [(st["goals"],)]
        res["answer"] = f"{ko} 선수의 프리미어리그 통산 득점은 {st['goals']}골입니다." + NOTE_RANGE
        res["followups"] = followups[:1] + [f"{ko} 알려줘"]
        return res

    if assist and _COUNT.search(q):
        res = _base_result("assists", _sql_assists(db))
        res["columns"], res["rows"] = ["assist_count"], [(st["assists"],)]
        res["answer"] = f"{ko} 선수의 프리미어리그 통산 어시스트는 {st['assists']}개입니다." + NOTE_RANGE
        res["followups"] = [f"{ko} 알려줘", followups[0]]
        return res

    if not goal and not assist and _PROFILE.search(q):
        return _profile(ko, db, st)

    return None


def _best_note(st: dict) -> str | None:
    if not st["best_seasons"]:
        return None
    labels = ", ".join(_season_label(s) for s in st["best_seasons"])
    return f"가장 많은 골을 넣은 시즌은 {labels} 시즌({st['best_goals']}골)입니다."


def _profile_card(ko: str, db: str, st: dict, kind: str = "profile") -> dict:
    return {
        "type": kind,
        "name_ko": ko,
        "name_en": db,
        "goals": st["goals"],
        "assists": st["assists"],
        "seasons_scored": st["seasons_scored"],
        "by_season": st["by_season"],
        "best_goals": st["best_goals"],
        "best_seasons": st["best_seasons"],
    }


def _profile(ko: str, db: str, st: dict) -> dict:
    sql = _sql_goals(db) + ";\n" + _sql_assists(db) + ";\n" + _sql_seasons(db)
    res = _base_result("profile", sql)
    res["columns"] = ["골", "어시스트", "골을 넣은 시즌 수"]
    res["rows"] = [(st["goals"], st["assists"], st["seasons_scored"])]
    res["answer"] = (
        f"{ko} 선수는 프리미어리그 통산 {st['goals']}골, {st['assists']}어시스트를 기록했고 "
        f"{st['seasons_scored']}개 시즌에서 골을 넣었습니다." + NOTE_RANGE
    )
    res["card"] = _profile_card(ko, db, st)
    res["insight"] = _best_note(st)
    res["followups"] = [f"{ko} 시즌별 골 수", f"{ko} 어시스트는 몇 개야?"]
    return res


def _compare(question: str, players: list[tuple[str, str, str]]) -> dict | None:
    if _EXCLUDE.search(question):
        return None
    conn = _conn()
    try:
        stats = [_player_stats(conn, db) for _, _, db in players]
    finally:
        conn.close()
    if not all(stats):
        return None
    (ka, _, da), (kb, _, db_) = [(p[1], p[0], p[2]) for p in players]
    sa, sb = stats

    sql = "-- 선수별 통산 기록\n" + ";\n".join(
        _sql_goals(d) + ";\n" + _sql_assists(d) + ";\n" + _sql_seasons(d) for d in (da, db_)
    )
    res = _base_result("compare", sql)
    res["columns"] = ["선수", "골", "어시스트", "골을 넣은 시즌 수", "한 시즌 최다 골"]
    res["rows"] = [
        (f"{ka} ({da})", sa["goals"], sa["assists"], sa["seasons_scored"], sa["best_goals"]),
        (f"{kb} ({db_})", sb["goals"], sb["assists"], sb["seasons_scored"], sb["best_goals"]),
    ]
    res["answer"] = (
        f"{ka} 선수는 {sa['goals']}골 {sa['assists']}어시스트, "
        f"{kb} 선수는 {sb['goals']}골 {sb['assists']}어시스트를 기록했습니다." + NOTE_RANGE
    )
    parts = []
    for label, key, unit in (("골", "goals", "골"), ("어시스트", "assists", "어시스트")):
        if sa[key] > sb[key]:
            parts.append(f"{label}은 {_josa(ka, '이', '가')} 더 많습니다")
        elif sa[key] < sb[key]:
            parts.append(f"{label}은 {_josa(kb, '이', '가')} 더 많습니다")
        else:
            parts.append(f"{label}은 같습니다")
    res["insight"] = ", ".join(parts) + ". 라임색이 더 큰 값입니다."
    res["card"] = {
        "type": "compare",
        "players": [
            {"name_ko": ka, "name_en": da, **{k: sa[k] for k in ("goals", "assists", "seasons_scored", "best_goals")}},
            {"name_ko": kb, "name_en": db_, **{k: sb[k] for k in ("goals", "assists", "seasons_scored", "best_goals")}},
        ],
    }
    res["followups"] = [f"{ka} 알려줘", f"{kb} 알려줘"]
    return res


def _h2h(question: str, teams: list[tuple[str, str, str]]) -> dict | None:
    if re.search(r"홈|원정|시즌|골|득점|선수|어시", question) or _PERIOD.search(question):
        return None
    (ka, _, da), (kb, _, db_) = [(t[1], t[0], t[2]) for t in teams]
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT date, home_team, away_team, home_score, away_score FROM matches "
            "WHERE ((home_team = ? AND away_team = ?) OR (home_team = ? AND away_team = ?)) "
            "AND home_score IS NOT NULL ORDER BY date DESC",
            (da, db_, db_, da),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return None

    def tally(subset):
        w = d = l = gf = ga = 0
        for _, home, _, hs, as_ in subset:
            a_goals, b_goals = (hs, as_) if home == da else (as_, hs)
            gf, ga = gf + a_goals, ga + b_goals
            if a_goals > b_goals:
                w += 1
            elif a_goals == b_goals:
                d += 1
            else:
                l += 1
        return w, d, l, gf, ga

    w, d, l, gf, ga = tally(rows)
    rw, rd, rl, _, _ = tally(rows[:5])

    def name(db):
        return _TEAM_KO.get(db, db)

    recent = [
        {
            "date": r[0][:10],
            "home": name(r[1]),
            "away": name(r[2]),
            "hs": r[3],
            "as": r[4],
            "a_home": r[1] == da,
        }
        for r in rows[:5]
    ]
    sql = (
        "SELECT date, home_team, away_team, home_score, away_score FROM matches "
        f"WHERE ((home_team = {_quote(da)} AND away_team = {_quote(db_)}) "
        f"OR (home_team = {_quote(db_)} AND away_team = {_quote(da)})) "
        "AND home_score IS NOT NULL ORDER BY date DESC"
    )
    res = _base_result("h2h", sql)
    res["columns"] = ["날짜", "홈팀", "원정팀", "홈 득점", "원정 득점"]
    res["rows"] = [(r[0][:10], name(r[1]), name(r[2]), r[3], r[4]) for r in rows[:20]]
    res["answer"] = (
        f"{_josa(ka, '과', '와')} {kb}는 2014-15 시즌 이후 프리미어리그에서 {len(rows)}번 맞붙었습니다. "
        f"{ka} {w}승, {kb} {l}승, 무승부 {d}번이고, 득점은 {ka} {gf}골, {kb} {ga}골입니다." + NOTE_RANGE
    )
    res["insight"] = f"최근 {min(5, len(rows))}경기에서는 {ka} {rw}승 {rd}무 {rl}패입니다."
    res["card"] = {
        "type": "h2h",
        "a": ka,
        "b": kb,
        "a_en": da,
        "b_en": db_,
        "total": len(rows),
        "w": w,
        "d": d,
        "l": l,
        "gf": gf,
        "ga": ga,
        "recent": recent,
    }
    res["followups"] = [f"{_josa(ka, '과', '와')} {kb} 경기 결과 보여줘"]
    return res


# ---------------------------------------------------------------- 진입점
def try_fast_path(question: str) -> dict | None:
    """빠른 경로로 답할 수 있으면 결과 dict, 아니면 None(기존 GPT 경로로 진행)."""
    q = (question or "").strip()
    if not q:
        return None
    # 기간 표현이 있거나 '시즌'이 '시즌별' 이외로 쓰였으면 기존 경로가 더 정확하다
    if season_codes(q) or _PERIOD.search(q):
        return None
    if re.search(r"시즌", q) and not _SEASONS.search(q):
        return None

    ents = _entities(q)
    players = [e for e in ents if e[0] == "player"]
    teams = [e for e in ents if e[0] == "team"]

    if len(players) == 1 and not teams:
        return _single_player(q, players[0][1], players[0][2])
    if len(players) == 2 and not teams and _COMPARE.search(q):
        return _compare(q, players)
    if len(teams) == 2 and not players and _H2H.search(q):
        return _h2h(q, teams)
    return None

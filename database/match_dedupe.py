"""
Understat 경기와 API-Football 경기가 같은 경기인지 찾는 공용 함수.

두 소스는 같은 경기를 서로 다른 match_id, 날짜 형식, 팀 이름 표기로 저장합니다.
(예: 'Wolves' / 'Wolverhampton Wanderers', 'Newcastle' / 'Newcastle United')
그래서 match_id가 아니라 [날짜 ±1일 + 팀 이름 + 스코어]로 같은 경기를 찾습니다.
"""

# API-Football 표기(소문자) -> Understat 표기(소문자)
TEAM_ALIASES = {
    "wolves": "wolverhampton wanderers",
    "newcastle": "newcastle united",
    "man city": "manchester city",
    "man united": "manchester united",
    "spurs": "tottenham",
    "tottenham hotspur": "tottenham",
    "west ham united": "west ham",
    "brighton & hove albion": "brighton",
    "leicester city": "leicester",
    "ipswich town": "ipswich",
}


def norm_team(name):
    key = (name or "").strip().lower()
    return TEAM_ALIASES.get(key, key)


def find_understat_match(conn, date, home, away, home_score=None, away_score=None):
    """
    같은 경기의 Understat match_id를 반환합니다. 없거나 불확실하면 None.

    1순위: 홈·원정 팀 이름이 모두 같은 경기
    2순위: 팀 이름이 한쪽만 같고 스코어가 같은 경기 (후보가 정확히 1개일 때만)
    """
    day = (date or "")[:10]
    if not day:
        return None

    rows = conn.execute(
        """
        SELECT match_id, home_team, away_team, home_score, away_score
        FROM matches
        WHERE source = 'understat'
          AND ABS(julianday(substr(date, 1, 10)) - julianday(?)) <= 1
        """,
        (day,),
    ).fetchall()

    h, a = norm_team(home), norm_team(away)

    exact = [r for r in rows if norm_team(r[1]) == h and norm_team(r[2]) == a]
    if len(exact) == 1:
        return exact[0][0]

    if home_score is not None and away_score is not None:
        loose = [
            r for r in rows
            if (norm_team(r[1]) == h or norm_team(r[2]) == a)
            and r[3] == home_score and r[4] == away_score
        ]
        if len(loose) == 1:
            return loose[0][0]

    return None

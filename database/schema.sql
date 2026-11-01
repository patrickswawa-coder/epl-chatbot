-- 경기 기본 정보 (스코어, 팀, 날짜)
CREATE TABLE IF NOT EXISTS matches (
    match_id        TEXT PRIMARY KEY,   -- 소스별 고유 ID (예: understat_12345)
    season          TEXT,               -- 예: "2024-2025"
    date            TEXT,               -- YYYY-MM-DD
    home_team       TEXT,
    away_team       TEXT,
    home_score      INTEGER,
    away_score      INTEGER,
    source          TEXT                -- "understat" / "api_football"
);

-- 경기 내 이벤트 (골, 카드 등) - 득점자/어시스트/시간 핵심 테이블
CREATE TABLE IF NOT EXISTS match_events (
    event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id        TEXT,               -- matches.match_id 참조
    minute          INTEGER,            -- 발생 시간 (분)
    team            TEXT,               -- 이 이벤트를 일으킨 팀
    event_type       TEXT,               -- "goal", "yellow_card", "red_card", "own_goal" 등
    player          TEXT,               -- 득점자 / 카드 받은 선수
    assist_player   TEXT,               -- 어시스트 선수 (없으면 NULL)
    xg              REAL,               -- Understat 전용, 없으면 NULL
    source          TEXT,               -- "understat" / "api_football"
    FOREIGN KEY (match_id) REFERENCES matches (match_id)
);

CREATE INDEX IF NOT EXISTS idx_events_match ON match_events(match_id);
CREATE INDEX IF NOT EXISTS idx_events_player ON match_events(player);
CREATE INDEX IF NOT EXISTS idx_matches_teams ON matches(home_team, away_team);

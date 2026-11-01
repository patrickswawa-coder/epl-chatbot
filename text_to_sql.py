"""
EPL 데이터 챗봇 - 자연어 → SQLite SQL → 자연어 답변

공모전 시연용 개선 버전
- GPT를 이용한 자연어 → SQL 변환
- SELECT 전용 SQL 검증
- 단일/다중 SQL 문장 실행 차단
- 허용 테이블(matches, match_events) 외 접근 차단
- SQL 오류 발생 시 1회 재생성
- API 오류/크레딧 부족 시 Streamlit이 죽지 않도록 안전 처리
- 단순 집계 결과는 GPT를 한 번 더 호출하지 않고 직접 답변하여 비용 절감
- 복수 행 결과만 GPT로 자연어 요약
- [NEW] 임베딩 기반 선수/팀 이름 매칭으로 하드코딩 매핑을 보완
- [NEW] 답변 뒤에 붙는 "추가 인사이트" 한 줄 자동 생성 (실패 시 조용히 생략)
"""

import os
import re
import sqlite3
import time
from typing import Any

from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)

from database.db_utils import get_connection
from error_codes import MAX_QUESTION_LENGTH, error_message


class ScopeError(Exception):
    """질문이 EPL 기록 범위 밖이거나 의미를 알 수 없을 때 (오류 코드 E02)."""


class NotInDBError(Exception):
    """축구 관련 질문이지만 DB 기록(경기·득점·어시스트·카드)으로는 답할 수 없을 때."""


class LLMError(RuntimeError):
    """OpenAI 호출 실패. code는 E05(LLM 오류) 또는 E08(호출 제한)."""

    def __init__(self, message: str, code: str = "E05"):
        super().__init__(message)
        self.code = code
from database.entity_resolver import format_hint, resolve_entities
from database.aliases import (
    expand_for_answer,
    expand_for_sql,
    mentioned_kinds,
    missing_entities,
    season_codes,
)


# ============================================================
# 1. OpenAI 설정
# ============================================================

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# 자동 재시도는 우리가 SQL 오류 재생성 로직으로 직접 관리합니다.
# API 호출이 무한히 반복되지 않도록 SDK 재시도는 최소화합니다.
client = (
    OpenAI(
        api_key=OPENAI_API_KEY,
        timeout=30.0,
        max_retries=0,
    )
    if OPENAI_API_KEY
    else None
)


# ============================================================
# 2. DB 스키마 / 이름 매핑
# ============================================================

SCHEMA_DESCRIPTION = """
테이블 1: matches (경기 기본 정보)
- match_id (TEXT, PK)
- season (TEXT, 형식 주의: "YYYY-YYYY"가 아니라 시작연도 뒤 2자리+종료연도 뒤 2자리,
  예: 2024-2025 시즌 -> "2425", 2019-2020 시즌 -> "1920", 2014-2015 시즌 -> "1415")
- date (TEXT, YYYY-MM-DD)
- home_team (TEXT)
- away_team (TEXT)
- home_score (INTEGER)
- away_score (INTEGER)
- source (TEXT, 'understat' / 'api_football')

테이블 2: match_events (경기 내 이벤트)
- event_id (INTEGER, PK)
- match_id (TEXT, matches.match_id 참조)
- minute (INTEGER, 이벤트 발생 시간)
- team (TEXT, 이벤트를 일으킨 팀)
- event_type (TEXT, 'goal' / 'own_goal' / 'yellow_card' / 'red_card' 등)
- player (TEXT, 득점자/해당 선수)
- assist_player (TEXT, 어시스트 선수, 없으면 NULL)
- xg (REAL, Understat 데이터에만 존재)
- source (TEXT, 'understat' / 'api_football')

두 테이블은 match_id로 JOIN 가능.
"""

TEAM_NAME_MAP = """
한글 팀 별명 -> 실제 DB 저장명 매핑:
- 맨시티, 맨체스터시티 -> Manchester City
- 맨유, 맨체스터유나이티드 -> Manchester United
- 아스날, 아스널 -> Arsenal
- 첼시 -> Chelsea
- 리버풀 -> Liverpool
- 토트넘, 토트넘 홋스퍼, 스퍼스 -> Tottenham
- 뉴캐슬 -> Newcastle
- 브라이튼 -> Brighton
- 웨스트햄 -> West Ham
- 에버튼 -> Everton
- 울버햄튼, 울브스 -> Wolverhampton
- 크리스탈팰리스 -> Crystal Palace
- 풀럼 -> Fulham
- 브렌트포드 -> Brentford
- 노팅엄포레스트 -> Nottingham Forest
- 애스턴빌라 -> Aston Villa
- 본머스 -> Bournemouth
"""

PLAYER_NAME_MAP = """
주요 선수 한글 이름 -> 실제 DB 저장명 검색어:
- 손흥민, 쏘니 -> %Heung-Min%
- 홀란드, 홀란 -> %Haaland%
- 살라, 모하메드 살라 -> %Salah%
- 덕배, 덕베, 데브라위너, 케빈 데브라위너 -> %De Bruyne%
- 사카, 부카요 사카 -> %Saka%
- 포든, 필 포든 -> %Foden%
- 외데고르, 마르틴 외데고르 -> %Odegaard%

주의:
- "Son", "Smith", "Silva", "James"처럼 흔하거나 모호한 이름/성만 단독 검색하지 마세요.
- PLAYER_NAME_MAP에 없는 선수는 가능한 경우 전체 영문 이름을 추론하되,
  확실하지 않은 경우 너무 넓은 LIKE 검색을 만들지 마세요.
- 아래 [임베딩 기반 이름 후보] 힌트가 함께 제공된 경우, PLAYER_NAME_MAP/TEAM_NAME_MAP에
  없는 이름에 한해 해당 힌트를 참고하여 정확한 DB 저장명으로 검색 조건을 만드세요.
"""

FEW_SHOT_EXAMPLES = """
예시 1)
질문: 손흥민이 넣은 골 개수는?
SQL:
SELECT COUNT(*) AS goal_count
FROM match_events
WHERE player LIKE '%Heung-Min%'
  AND event_type = 'goal';

예시 2)
질문: 맨시티와 첼시의 최근 맞대결 5경기 보여줘
SQL:
SELECT
    date || ' ' || home_team || ' vs ' || away_team AS match_label,
    home_score,
    away_score
FROM matches
WHERE (home_team LIKE '%Manchester City%' AND away_team LIKE '%Chelsea%')
   OR (home_team LIKE '%Chelsea%' AND away_team LIKE '%Manchester City%')
ORDER BY date DESC
LIMIT 5;

예시 3)
질문: 2024-2025 시즌 득점 순위 5명 보여줘
SQL:
SELECT player, COUNT(*) AS goal_count
FROM match_events
WHERE event_type = 'goal'
  AND match_id IN (
      SELECT match_id
      FROM matches
      WHERE season = '2425'
  )
  AND player IS NOT NULL
GROUP BY player
ORDER BY goal_count DESC
LIMIT 5;
"""


SYSTEM_PROMPT = f"""
당신은 EPL 축구 데이터베이스를 조회하는 SQLite 전문가입니다.
사용자의 한글 질문을 데이터베이스에 존재하는 정보만 사용하여
하나의 SQLite SELECT 쿼리로 변환하세요.

[범위 밖 질문 처리]
1) 축구와 전혀 관련이 없거나, 의미를 알 수 없는 글자의 나열이면
   SQL을 만들지 말고 정확히 OUT_OF_SCOPE 라는 단어 하나만 출력하세요.
2) 축구(EPL) 관련 질문이지만 위 스키마의 기록(경기 결과, 득점, 어시스트, 카드)으로는
   답할 수 없는 질문(선수 소개, 이적, 감독, 연봉, 전술 설명, 축구 규칙·용어 설명 등)이면
   SQL을 만들지 말고 정확히 NOT_IN_DB 라는 단어 하나만 출력하세요.
   (오프사이드 같은 축구 규칙·용어·일반 상식 질문도 NOT_IN_DB 입니다.)
3) "통산", "역대", "전체", "가장 많은" 같은 기록 질문은 NOT_IN_DB가 아닙니다.
   데이터베이스에 담긴 기간(2014-15 시즌~현재) 안에서 집계하는 SQL을 만드세요.

[데이터베이스 스키마]
{SCHEMA_DESCRIPTION}

[팀 이름 매핑]
{TEAM_NAME_MAP}

[선수 이름 매핑]
{PLAYER_NAME_MAP}

[예시]
{FEW_SHOT_EXAMPLES}

[반드시 지켜야 할 규칙]
1. 오직 하나의 SELECT SQL만 출력하세요.
2. INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, REPLACE, PRAGMA, ATTACH 등은 절대 사용하지 마세요.
3. 설명, 자연어, 마크다운 코드블록(```)은 출력하지 마세요.
4. 조회 대상 테이블은 matches와 match_events만 사용하세요.
5. 팀 검색은 가능한 경우 LIKE '%팀명%' 형태의 부분 일치를 사용하세요.
6. 선수 검색은 가능한 한 First Name + Last Name을 포함하여 구체적으로 검색하세요.
7. 흔한 성씨만 단독으로 검색하지 마세요. 예: player LIKE '%Son%' 금지.
8. 득점자 수/득점 수를 계산할 때는 match_events의 event_type='goal'을 사용하세요.
9. "득점 시간"을 물으면 match_events.minute을 사용하세요.
10. "득점 순위", "골을 많이 넣은 선수" 등의 질문은 GROUP BY + COUNT(*) + ORDER BY goal_count DESC를 사용하세요.
10-1. "어시스트 순위", "어시스트가 가장 많은 선수", "도움왕" 질문은 어시스트한 선수 기준이므로
    SELECT assist_player, COUNT(*) ... WHERE event_type='goal' AND assist_player IS NOT NULL
    GROUP BY assist_player ORDER BY assist_count DESC 로 작성하세요. (GROUP BY player는 득점자 기준이라 틀립니다.)
10-2. "팀이 넣은 총 골 수"는 matches에서 계산하세요 (상대 팀 골이 섞이지 않도록).
    예: SELECT SUM(CASE WHEN home_team='Chelsea' THEN home_score ELSE away_score END) AS goal_count
        FROM matches WHERE season='2122' AND (home_team='Chelsea' OR away_team='Chelsea')
10-2-1. "가장 많은 골을 넣은 팀" 같은 팀 득점 순위는 match_events의 team 컬럼으로 계산하세요.
    예: SELECT team, COUNT(*) AS goal_count FROM match_events WHERE event_type='goal' AND match_id IN (SELECT match_id FROM matches WHERE season='1516') GROUP BY team ORDER BY goal_count DESC LIMIT 1
    (홈/원정을 UNION ALL로 나눠 세면 한쪽만 집계되는 오류가 생깁니다.)
10-3. 두 선수·두 팀을 비교하는 질문은 LIMIT 1을 쓰지 말고 비교 대상 모두의 값을 함께 반환하세요.
10-4. 질문에 "(DB season: '2021')"처럼 시즌 코드가 붙어 있으면 그 코드를 그대로 season 조건에 사용하세요.
11. 경기 목록을 보여줄 때 match_id를 그대로 출력하지 말고,
    date || ' ' || home_team || ' vs ' || away_team AS match_label 형태를 우선 사용하세요.
12. 결과가 많을 수 있는 일반 목록/상세 조회는 LIMIT 20을 사용하세요.
    이때 경기 결과·경기 목록은 항상 최신 경기부터 보이도록 ORDER BY date DESC를 사용하세요
    (오래된 경기만 잘려서 보이는 일을 막기 위함).
13. 단순 COUNT/SUM/AVG/MIN/MAX 집계에는 불필요한 LIMIT을 붙이지 마세요.
13-1. "이번 시즌", "올 시즌", "최근 시즌" 같은 상대적 표현은 별도 시스템 메시지로 알려 주는
    데이터베이스의 최신 시즌 코드를 기준으로 해석하세요. ("지난 시즌"은 그 바로 이전 시즌입니다.)
13-2. 질문에 시즌·연도·"이번 시즌" 같은 기간 표현이 전혀 없으면 season 조건을 넣지 마세요.
    이 경우 DB에 담긴 전체 기간(2014-15 시즌 이후)을 기준으로 집계합니다. (예: "손흥민 득점수" → 전 시즌 합계)
14. 사용자가 질문한 시즌/팀/선수/경기 조건을 임의로 생략하지 마세요.
    질문에 팀이 나오면 home_team/away_team 조건을, 선수가 나오면 player/assist_player 조건을 반드시 넣으세요.
14-1. 질문에 "(DB 선수명: Bukayo Saka)"처럼 DB 저장명이 붙어 있으면 그 이름을 정확히 그대로 사용하세요.
    선수는 player = 'Bukayo Saka' 또는 assist_player = 'Bukayo Saka'처럼 = 비교를 쓰고,
    성만 따로 LIKE '%Saka%'로 검색하지 마세요 (다른 선수가 섞입니다).
    팀은 "(DB 팀명: Manchester City)"의 이름으로 비교하세요.
14-2. WHERE 절에서 OR와 AND를 함께 쓸 때는 OR 조건을 반드시 괄호로 묶으세요.
    예: WHERE ((home_team='A' AND away_team='B') OR (home_team='B' AND away_team='A')) AND season='1819'
15. DB에 없는 사실을 추측해서 SQL 조건으로 만들지 마세요.
16. 이전 대화가 제공된 경우 "그럼", "거기서", "그 경기", "그 선수" 등의 후속 표현을
    이전 대화의 대상과 연결하여 해석하세요.
17. 단, 이전 대화만으로 대상을 명확히 알 수 없다면 무리하게 추측하지 마세요.
18. 사용자가 "2024-25 시즌", "24-25시즌", "2024/2025", "2024년부터 2025년" 등
    다양한 형태로 시즌을 표현해도, season 값은 항상 위에 명시된 4자리 형식
    ("2425" 등)으로 변환해서 조건에 사용하세요.
19. [임베딩 기반 이름 후보] 힌트가 별도 시스템 메시지로 제공된 경우, 이는 참고용
    제안일 뿐입니다. PLAYER_NAME_MAP/TEAM_NAME_MAP에 이미 있는 이름은 그것을
    우선하고, 힌트가 질문 의도와 맞지 않아 보이면 무시하세요.
"""


# ============================================================
# 3. 공통 유틸
# ============================================================

MAX_HISTORY_TURNS = 3
MAX_SQL_LENGTH = 8000
DEFAULT_RESULT_LIMIT = 20

ALLOWED_TABLES = {"matches", "match_events"}

DANGEROUS_SQL_KEYWORDS = {
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "create",
    "replace",
    "truncate",
    "attach",
    "detach",
    "pragma",
    "vacuum",
    "reindex",
    "grant",
    "revoke",
}


def _clean_sql(sql: str) -> str:
    """GPT가 반환한 SQL에서 코드블록/불필요한 공백을 제거합니다."""
    if not sql:
        raise ValueError("GPT가 SQL을 생성하지 않았습니다.")

    sql = sql.strip()

    # ```sql ... ``` 또는 ``` ... ``` 제거
    sql = re.sub(r"^```(?:sql)?\s*", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\s*```$", "", sql)

    # SQL 뒤의 세미콜론 하나는 허용하되 제거합니다.
    sql = sql.strip()
    if sql.endswith(";"):
        sql = sql[:-1].rstrip()

    return sql


def _validate_sql(sql: str) -> str:
    """
    GPT가 생성한 SQL이 조회 전용인지 검사합니다.

    단순히 startswith('select')만 검사하지 않고:
    - 여러 문장 실행
    - 주석을 이용한 우회
    - 위험한 SQL 키워드
    - 허용되지 않은 테이블
    을 추가로 검사합니다.
    """
    sql = _clean_sql(sql)

    if len(sql) > MAX_SQL_LENGTH:
        raise ValueError("생성된 SQL이 너무 깁니다.")

    if not re.match(r"^\s*SELECT\b", sql, flags=re.IGNORECASE):
        raise ValueError("안전을 위해 SELECT 쿼리만 실행할 수 있습니다.")

    # 여러 SQL 문장 실행 방지
    if ";" in sql:
        raise ValueError("하나의 SELECT 쿼리만 실행할 수 있습니다.")

    # SQL 주석을 통한 우회 방지
    if "--" in sql or "/*" in sql or "*/" in sql:
        raise ValueError("SQL 주석은 사용할 수 없습니다.")

    lowered = sql.lower()

    for keyword in DANGEROUS_SQL_KEYWORDS:
        if re.search(rf"\b{re.escape(keyword)}\b", lowered):
            raise ValueError(f"허용되지 않는 SQL 명령이 포함되어 있습니다: {keyword}")

    # FROM / JOIN 뒤에 사용된 테이블 이름을 검사합니다.
    referenced_tables = re.findall(
        r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)",
        sql,
        flags=re.IGNORECASE,
    )

    unknown_tables = {
        table.lower()
        for table in referenced_tables
        if table.lower() not in ALLOWED_TABLES
    }

    if unknown_tables:
        raise ValueError(
            "허용되지 않은 테이블이 사용되었습니다: "
            + ", ".join(sorted(unknown_tables))
        )

    return sql


def _add_default_limit(sql: str) -> str:
    """
    결과가 지나치게 많아지는 일반 SELECT에 LIMIT 20을 추가합니다.

    집계 함수/ GROUP BY 결과는 그대로 둡니다.
    이미 LIMIT이 있으면 수정하지 않습니다.
    """
    lowered = sql.lower()

    if re.search(r"\blimit\s+\d+\b", lowered):
        return sql

    is_aggregate = bool(
        re.search(r"\b(count|sum|avg|min|max)\s*\(", lowered)
        or re.search(r"\bgroup\s+by\b", lowered)
    )

    if is_aggregate:
        return sql

    return f"{sql}\nLIMIT {DEFAULT_RESULT_LIMIT}"


def _require_client() -> OpenAI:
    """API 키가 없을 때 명확한 오류를 반환합니다."""
    if client is None:
        raise RuntimeError(
            "OPENAI_API_KEY가 설정되지 않았습니다. "
            ".env 파일의 OPENAI_API_KEY를 확인해주세요."
        )
    return client


def _openai_error_message(exc: Exception) -> str:
    """OpenAI 오류를 사용자에게 이해하기 쉬운 메시지로 변환합니다."""
    if isinstance(exc, RateLimitError):
        return (
            "OpenAI API 사용 한도를 초과했거나 크레딧이 부족합니다. "
            "OpenAI API Billing에서 잔액을 확인해주세요."
        )

    if isinstance(exc, APITimeoutError):
        return (
            "OpenAI API 응답 시간이 초과되었습니다. "
            "잠시 후 다시 질문해주세요."
        )

    if isinstance(exc, APIConnectionError):
        return (
            "OpenAI API 서버에 연결하지 못했습니다. "
            "인터넷 연결을 확인한 뒤 다시 시도해주세요."
        )

    return f"OpenAI API 오류가 발생했습니다: {exc}"


# ============================================================
# 4. 자연어 → SQL
# ============================================================

def validate_question(question: str) -> str | None:
    """
    [① 입력 검증] 문제가 있으면 오류 코드 E01을 반환하고, 정상이면 None.
    - 빈 값 / 공백만 있는 질문
    - 200자 초과
    - 제어 문자 포함
    - 글자·숫자가 하나도 없는 질문 (기호만 입력)
    """
    text = (question or "").strip()

    if not text:
        return "E01"

    if len(text) > MAX_QUESTION_LENGTH:
        return "E01"

    if any(ord(ch) < 32 and ch not in "\n\t" for ch in text):
        return "E01"

    if not any(ch.isalnum() for ch in text):
        return "E01"

    # 한글 자음·모음(ㅋㅋ, ㅏㅏ 등)만 길게 이어진 입력은 의미 없는 입력으로 본다.
    compact = [ch for ch in text if not ch.isspace()]
    jamo = sum(1 for ch in compact if "\u3131" <= ch <= "\u318e")
    if compact and jamo / len(compact) >= 0.3:
        return "E01"

    return None


def question_to_sql(
    question: str,
    history: list[dict] | None = None,
    force_sql: bool = False,
) -> str:
    """사용자의 자연어 질문을 SQLite SELECT SQL로 변환합니다."""
    question = (question or "").strip()

    if not question:
        raise ValueError("질문을 입력해주세요.")

    # 길이 제한은 validate_question()이 처리한다.
    # (SQL 재생성용 프롬프트는 질문보다 길 수 있어 여기서는 검사하지 않는다.)
    try:
        api_client = _require_client()
    except RuntimeError as exc:
        raise LLMError(str(exc), "E05") from exc

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # --------------------------------------------------------
    # [NEW] 임베딩 기반 이름 매칭 힌트 추가
    # PLAYER_NAME_MAP/TEAM_NAME_MAP에 없는 이름도 대응할 수 있도록
    # DB에 실제 존재하는 이름 중 의미적으로 가까운 후보를 찾아 힌트로 제공합니다.
    # 캐시가 없거나 API 호출이 실패해도 여기서 예외가 나지 않도록
    # resolve_entities/format_hint 내부에서 이미 안전하게 처리하지만,
    # 혹시 모를 상황에 대비해 한 번 더 감싸줍니다.
    # --------------------------------------------------------
    try:
        candidates = resolve_entities(question)
        hint = format_hint(candidates)
        if hint:
            messages.append({"role": "system", "content": hint})
    except Exception:
        pass

    if history:
        # app.py에서 전달되는 대화 기록이 너무 길어지지 않도록 제한
        messages.extend(history[-MAX_HISTORY_TURNS * 2:])

    latest = latest_season_code()
    if latest:
        messages.append(
            {
                "role": "system",
                "content": f"데이터베이스의 최신 시즌 코드는 '{latest}'입니다. "
                           "'이번 시즌'은 이 코드로 해석하세요.",
            }
        )

    if force_sql:
        # 기록·순위 질문은 DB 집계로 답할 수 있으므로 "DB에 없음"으로 빠지지 못하게 막는다
        messages.append(
            {
                "role": "system",
                "content": (
                    "다음 질문은 matches/match_events 집계로 답할 수 있는 기록·순위 질문입니다. "
                    "NOT_IN_DB를 출력하지 말고, 데이터베이스에 담긴 기간 안에서 집계하는 "
                    "SELECT SQL 하나만 출력하세요."
                ),
            }
        )

    messages.append(
        {
            "role": "user",
            # 별명(덕베, 쏘니, 맨유 ...)을 DB 저장명과 함께 적어 AI가 정확히 검색하게 한다
            "content": expand_for_sql(question),
        }
    )

    try:
        response = api_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            temperature=0,
        )
    except Exception as exc:
        code = "E08" if isinstance(exc, RateLimitError) else "E05"
        raise LLMError(_openai_error_message(exc), code) from exc

    content = response.choices[0].message.content

    if not content:
        raise ValueError("GPT가 SQL을 반환하지 않았습니다.")

    # [② 범위 확인] 범위 밖이거나 의미 없는 질문이면 SQL을 만들지 않는다 (E02)
    head = content.strip().strip("`").strip().upper()
    if head.startswith("OUT_OF_SCOPE"):
        raise ScopeError("OUT_OF_SCOPE")
    if head.startswith("NOT_IN_DB"):
        if force_sql:
            raise ValueError("기록·순위 질문인데 SQL 대신 NOT_IN_DB가 반환되었습니다. SQL을 작성하세요.")
        raise NotInDBError("NOT_IN_DB")

    sql = _validate_sql(content)
    sql = _add_default_limit(sql)

    # LIMIT 추가 후에도 다시 검증
    return _validate_sql(sql)


# ============================================================
# 5. SQL 실행
# ============================================================

class QueryTimeout(Exception):
    """조회가 제한 시간을 넘겼을 때 (E06)."""


QUERY_TIMEOUT_SECONDS = 5


def _open_readonly_connection():
    """챗봇 전용 읽기 전용 연결. 실수로라도 DB를 바꿀 수 없다."""
    from database.db_utils import DB_PATH

    uri = DB_PATH.resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def run_sql(sql: str) -> tuple[list, list]:
    """검증된 SELECT SQL을 읽기 전용으로, 제한 시간(5초) 안에서 실행합니다."""
    sql = _validate_sql(sql)

    conn = _open_readonly_connection()
    deadline = time.monotonic() + QUERY_TIMEOUT_SECONDS
    # 약 1만 VM 명령마다 시간 확인 -> 초과하면 0이 아닌 값을 돌려 쿼리를 중단
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10000)

    try:
        cur = conn.cursor()
        cur.execute(sql)

        if cur.description is None:
            raise ValueError("조회 결과를 반환하지 않는 SQL입니다.")

        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()

        return columns, rows

    except sqlite3.OperationalError as exc:
        if "interrupted" in str(exc).lower():
            raise QueryTimeout("조회 시간 초과") from exc
        raise

    finally:
        conn.close()


# ============================================================
# 6. 단순 결과는 GPT 없이 답변
# ============================================================

def _format_simple_result(
    question: str,
    columns: list,
    rows: list,
) -> str | None:
    """
    GPT를 다시 호출할 필요가 없는 간단한 1행/1열 집계 결과를 처리합니다.

    예:
    SELECT COUNT(*) AS goal_count ...
    → "손흥민이 넣은 골은 127골입니다."
    """
    if len(rows) != 1 or len(columns) != 1:
        return None

    column = str(columns[0]).lower()
    value = rows[0][0]

    if value is None:
        return "조회 결과가 없습니다."

    if "goal_count" in column:
        kinds = mentioned_kinds(question)
        if kinds["team"] and not kinds["player"]:
            return f"해당 팀의 득점은 {value}골입니다."
        return f"질문하신 선수의 득점은 {value}골입니다."

    if "assist_count" in column:
        return f"어시스트 기록은 {value}회입니다."

    if "match_count" in column:
        return f"조건에 해당하는 경기는 {value}경기입니다."

    if "yellow_card_count" in column:
        return f"옐로카드는 {value}회입니다."

    if "red_card_count" in column:
        return f"레드카드는 {value}회입니다."

    if "avg" in column or "average" in column:
        return f"평균값은 {value}입니다."

    if "sum" in column or "total" in column:
        return f"합계는 {value}입니다."

    if "max" in column:
        return f"최댓값은 {value}입니다."

    if "min" in column:
        return f"최솟값은 {value}입니다."

    return f"{columns[0]}: {value}"


# ============================================================
# 7. 조회 결과 → 자연어
# ============================================================

def summarize_result(
    question: str,
    columns: list,
    rows: list,
) -> str:
    """조회 결과를 자연스러운 한글 답변으로 변환합니다."""
    if not rows:
        return "조회 결과가 없습니다. 질문의 선수명, 팀명, 시즌 등을 확인해보세요."

    # 단순 집계는 API를 한 번 더 사용하지 않습니다.
    simple_answer = _format_simple_result(question, columns, rows)

    if simple_answer:
        return simple_answer

    # GPT에 너무 많은 데이터를 전달하지 않도록 최대 20행만 전달
    data_preview = "\n".join(
        ", ".join(
            f"{col}: {val}"
            for col, val in zip(columns, row)
        )
        for row in rows[:20]
    )

    api_client = _require_client()

    summary_system_prompt = """
당신은 EPL 축구 데이터 분석가입니다.

사용자의 질문과 SQLite 조회 결과를 바탕으로 자연스러운 한글 답변을 작성하세요.

반드시 지켜야 할 규칙:
1. 조회 결과에 실제로 존재하는 데이터만 사용하세요.
2. 데이터에 없는 사실이나 선수/경기 정보를 추측해서 추가하지 마세요.
3. SQL 문장을 답변에 노출하지 마세요.
4. 너무 장황하게 설명하지 말고 핵심 결과를 먼저 말하세요.
5. 여러 경기/선수가 있으면 이해하기 쉬운 목록 형태로 정리하세요.
6. 숫자와 날짜는 조회 결과를 그대로 사용하세요.
   조회 결과에 없는 '최근', '가장 마지막', '처음' 같은 시점 판단이나 총 전적 요약은 만들지 마세요.
   목록의 맨 앞/맨 뒤 행이 최신·최초라고 단정하지 말고, 결과에 보이는 날짜만 그대로 말하세요.
7. "데이터에 따르면", "조회 결과" 같은 표현을 필요 이상으로 반복하지 마세요.
8. 조회 결과에 등장하는 선수 이름(player, assist_player 등 사람 이름 컬럼)은
   영문 원어(Harry Kane, Mohamed Salah 등)를 그대로 노출하지 말고, 한국
   축구 팬들에게 통용되는 한글 표기로 바꿔서 답변하세요.
   예: Harry Kane -> 해리 케인, Mohamed Salah -> 모하메드 살라,
       Jamie Vardy -> 제이미 바디, Sergio Agüero -> 세르히오 아구에로,
       Son Heung-min -> 손흥민, Raheem Sterling -> 라힘 스털링,
       Erling Haaland -> 엘링 홀란, Sadio Mané -> 사디오 마네,
       Callum Wilson -> 캘럼 윌슨, Chris Wood -> 크리스 우드.
   위 목록에 없는 선수도 일반적으로 통용되는 한글 표기(외래어 표기법 기준)로
   바꾸세요. 확실한 한글 표기를 알 수 없는 아주 생소한 이름이라면 원문
   영문 이름을 괄호로 함께 표기해도 됩니다 (예: 존 도(John Doe)).
9. 조회 결과에 등장하는 팀 이름(home_team, away_team, team, match_label 등)도
   영문 원어를 그대로 노출하지 말고, 한국 축구 팬들에게 통용되는 한글 표기로
   바꿔서 답변하세요.
   예: Manchester City -> 맨체스터 시티, Manchester United -> 맨체스터 유나이티드,
       Arsenal -> 아스널, Chelsea -> 첼시, Liverpool -> 리버풀,
       Tottenham -> 토트넘, Newcastle -> 뉴캐슬, Brighton -> 브라이턴,
       West Ham -> 웨스트햄, Everton -> 에버튼, Wolverhampton -> 울버햄튼,
       Crystal Palace -> 크리스탈 팰리스, Fulham -> 풀럼, Brentford -> 브렌트포드,
       Nottingham Forest -> 노팅엄 포레스트, Aston Villa -> 애스턴 빌라,
       Bournemouth -> 본머스, Leicester -> 레스터, Southampton -> 사우샘프턴,
       Burnley -> 번리, Watford -> 왓퍼드, Norwich -> 노리치, Sunderland -> 선덜랜드.
   위 목록에 없는 팀(과거 시즌의 승격/강등 팀 포함)도 일반적으로 통용되는
   한글 표기로 바꾸세요. 확신이 안 서는 낯선 팀명이면 영문을 괄호로 함께
   표기해도 됩니다 (예: 입스위치(Ipswich)).
   "date || ' ' || home_team || ' vs ' || away_team" 형태로 합쳐진
   match_label 컬럼 안의 팀 이름도 동일하게 한글로 바꿔서 답변하세요.
"""

    try:
        response = api_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": summary_system_prompt,
                },
                {
                    "role": "user",
                    "content": (
                        f"질문: {question}\n\n"
                        f"조회 결과:\n{data_preview}"
                    ),
                },
            ],
            temperature=0.2,
        )

        content = response.choices[0].message.content

        if not content:
            raise ValueError("GPT가 답변을 생성하지 않았습니다.")

        return content.strip()

    except Exception:
        # 두 번째 GPT 호출이 실패하더라도 DB 조회 자체는 성공했으므로
        # 기본 답변으로 결과를 보여줍니다.
        return _fallback_answer(columns, rows)


def _fallback_answer(columns: list, rows: list) -> str:
    """GPT 요약 실패 시 사용할 안전한 기본 답변."""
    preview_rows = rows[:10]

    if len(rows) > 10:
        suffix = f"\n총 {len(rows)}개의 결과 중 10개를 표시합니다."
    else:
        suffix = ""

    lines = []

    for row in preview_rows:
        parts = [
            f"{col}: {value}"
            for col, value in zip(columns, row)
        ]
        lines.append(" · ".join(parts))

    return "조회 결과입니다.\n\n" + "\n".join(lines) + suffix


# ============================================================
# 7-1. [NEW] 답변 뒤에 붙는 "추가 인사이트" 생성
# ============================================================

# GPT에게 "추가로 조회할 SQL"과 "그 결과를 담을 문장 템플릿"을
# 한 번에 요청합니다. 문장 템플릿의 {0}, {1} ... 자리에는
# 추가 SQL 결과의 컬럼 값이 순서대로 들어갑니다.
INSIGHT_SYSTEM_PROMPT = f"""
당신은 EPL 데이터베이스 인사이트 도우미입니다.

사용자의 질문과 이미 조회되어 사용자에게 보여준 답변을 참고하여,
답변 뒤에 한 줄 덧붙이면 사용자가 "오, 이것도 아네?"라고 느낄 만한
"추가 통계 하나"를 제안하세요.

[데이터베이스 스키마]
{SCHEMA_DESCRIPTION}

출력 형식은 반드시 아래 두 줄이어야 합니다. 그 외의 설명, 인사말,
마크다운은 절대 출력하지 마세요.

SQL: <하나의 SQLite SELECT 쿼리>
TEMPLATE: <조회 결과를 자연스럽게 담을 한 문장. 결과 컬럼은 등장 순서대로
{{0}}, {{1}}, {{2}} ... 로 표시>

반드시 지켜야 할 규칙:
1. SQL은 matches, match_events 테이블만 사용하고 SELECT만 허용됩니다.
2. INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/PRAGMA/ATTACH 등은 절대 사용하지 마세요.
3. 쿼리 결과는 반드시 1행만 나오도록 설계하세요 (필요시 LIMIT 1 사용).
4. 이미 사용자에게 보여준 것과 완전히 동일한 정보를 반복하지 마세요.
5. 조회 SQL의 결과 숫자로만 만들 수 있는 사실(예: 시즌별 골 수, 최근 시즌 기록)을 우선하세요.
   순위·최다·팀 내 비교처럼 SQL 결과만으로 확인되지 않는 표현은 TEMPLATE에 쓰지 마세요.
5-1. 평균·시즌당·경기당·비율 같은 파생 수치는 만들지 마세요. (분모가 되는 시즌·경기 수가 DB 범위에 따라 달라집니다)
6. 마땅히 덧붙일 인사이트가 떠오르지 않으면, 다른 말 없이 정확히
   한 단어 "NONE" 만 출력하세요.
7. TEMPLATE 문장은 존댓말로, 한 문장으로 짧게 작성하세요.
"""


def generate_insight(
    question: str,
    columns: list,
    rows: list,
) -> str | None:
    """
    답변 뒤에 덧붙일 "추가 인사이트" 한 줄을 생성합니다.

    동작 방식:
    1. GPT에게 추가로 조회할 SELECT SQL과 문장 템플릿을 요청합니다.
    2. GPT가 "NONE"을 반환하면 조용히 None을 반환합니다.
    3. 반환된 SQL을 기존 _validate_sql()로 검증한 뒤 실행합니다.
    4. 실행 결과를 문장 템플릿의 {0}, {1} ... 자리에 채워 넣습니다.

    이 함수는 실패하더라도(형식 오류, SQL 오류, API 오류 등) 예외를
    던지지 않고 None을 반환하여, 메인 답변 흐름에 절대 영향을 주지 않습니다.
    """
    if not rows or not columns:
        return None

    if client is None:
        return None

    # GPT에 너무 많은 데이터를 보내지 않도록 1행만 미리보기로 전달
    data_preview = ", ".join(
        f"{col}: {val}" for col, val in zip(columns, rows[0])
    )

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": INSIGHT_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"사용자 질문: {question}\n"
                        f"이미 조회되어 보여준 결과: {data_preview}"
                    ),
                },
            ],
            temperature=0.3,
        )
        content = response.choices[0].message.content
    except Exception:
        return None

    if not content:
        return None

    content = content.strip()

    if content.upper() == "NONE":
        return None

    sql_match = re.search(
        r"SQL:\s*(.+?)\nTEMPLATE:", content, re.DOTALL | re.IGNORECASE
    )
    template_match = re.search(
        r"TEMPLATE:\s*(.+)", content, re.DOTALL | re.IGNORECASE
    )

    if not sql_match or not template_match:
        return None

    insight_sql = sql_match.group(1).strip()
    template = template_match.group(1).strip()

    if not insight_sql or not template:
        return None

    try:
        insight_sql = _validate_sql(insight_sql)
        insight_columns, insight_rows = run_sql(insight_sql)
    except Exception:
        return None

    if not insight_rows:
        return None

    # 근거 없는 순위·최상급 표현이 템플릿에 섞이면 사용하지 않는다 (예: "팀 내 두 번째")
    if re.search(r"번째|가장|최고|최다|최초|최소|팀 ?내|리그 ?내|역대|\d위|랭킹|순위", template):
        return None
    # 평균·비율처럼 분모(시즌 수·경기 수)에 따라 달라지는 파생 수치도 쓰지 않는다 (예: "시즌당 약 15.9골")
    if re.search(r"평균|시즌당|경기당|매 ?시즌|비율|확률|퍼센트|%|당 약", template):
        return None

    insight_text = template
    for i, value in enumerate(insight_rows[0]):
        insight_text = insight_text.replace(f"{{{i}}}", str(value))

    # 치환이 안 된 자리표시자가 남아있거나 문장이 비정상적으로 길면
    # (오작동 가능성) 안전하게 생략합니다.
    if "{" in insight_text or "}" in insight_text:
        return None

    if len(insight_text) > 200:
        return None

    return insight_text


# ============================================================
# 7-2. [NEW] 대화 맥락 기반 후속 질문 추천
# ============================================================

# 왼쪽 사이드바의 "추천 질문"을 고정된 예시 대신, 방금 나눈 대화를
# 기반으로 GPT가 실시간으로 만들어주는 후속 질문으로 교체하기 위한 함수입니다.
FOLLOWUP_SYSTEM_PROMPT = f"""
당신은 EPL 데이터 챗봇의 "다음 질문 추천" 도우미입니다.

[데이터베이스 스키마]
{SCHEMA_DESCRIPTION}

사용자가 방금 아래와 같이 질문하고 답변을 받았습니다. 이 대화 흐름에
자연스럽게 이어서 물어볼 만한 후속 질문을 정확히 4개 만드세요.

반드시 지켜야 할 규칙:
1. matches, match_events 테이블에 있는 정보만으로 답할 수 있는 질문만 만드세요
   (예: 득점, 어시스트, 카드, 경기 결과, 시즌별 비교 등).
2. 방금 받은 답변과 완전히 같은 내용을 다시 묻는 질문은 만들지 마세요.
3. 방금 대화에 등장한 선수/팀/시즌이 있다면 최대한 활용해 구체적인 질문을
   만드세요 (예: "그럼 손흥민의 어시스트는 몇 개야?").
4. 짧고 자연스러운 한국어 구어체 질문으로 작성하세요.
5. 출력은 질문 하나당 한 줄, 번호·설명·마크다운·따옴표 없이 질문 텍스트만
   출력하세요. 정확히 4줄만 출력하세요.
6. 자연스러운 후속 질문이 4개 이하로만 떠오르면, 대신 EPL 전반의 흥미로운
   질문으로 나머지 줄을 채우세요 (빈 줄을 남기지 마세요).
"""


def generate_followup_questions(
    question: str,
    answer: str,
    max_questions: int = 4,
) -> list[str]:
    """
    방금 오간 질문/답변을 바탕으로 자연스러운 후속 질문 목록을 생성합니다.

    이 함수는 실패하더라도(형식 오류, API 오류 등) 예외를 던지지 않고
    빈 리스트를 반환하여, 메인 답변 흐름이나 UI 렌더링에 영향을 주지
    않습니다 (generate_insight()와 동일한 안전 패턴).
    """
    if client is None:
        return []

    if not question or not answer:
        return []

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": FOLLOWUP_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"방금 질문: {question}\n방금 답변: {answer}",
                },
            ],
            temperature=0.5,
        )
        content = response.choices[0].message.content
    except Exception:
        return []

    if not content:
        return []

    questions = []
    for line in content.strip().split("\n"):
        line = line.strip().strip("-•* ").strip('"').strip()
        if line:
            questions.append(line)

    return questions[:max_questions]


# ============================================================
# 7-3. [NEW] DB 조회 자체가 실패했을 때의 GPT 지식 기반 폴백
# ============================================================

# SQL 생성/실행이 재시도까지 모두 실패했을 때, 사용자에게 "조회 실패"만
# 보여주는 대신 GPT의 일반 지식으로 답을 시도합니다.
# 이 답변은 DB로 검증된 값이 아니므로, answer_source="gpt_fallback"으로
# 표시해 UI(app.py)가 반드시 출처를 구분해서 보여주도록 합니다.
FALLBACK_SYSTEM_PROMPT = """
당신은 EPL(잉글랜드 프리미어리그) 전문가입니다.
사용자의 질문을 데이터베이스로는 확인할 수 없었습니다. 당신이 알고 있는
일반 지식을 바탕으로 최대한 정확하게 답변해주세요.

반드시 지켜야 할 규칙:
1. 확신이 없는 구체적인 수치(정확한 골 개수, 경기 스코어, 날짜 등)는
   단정적으로 말하지 말고 "제가 알기로는", "정확하지 않을 수 있지만" 같은
   표현으로 불확실성을 표시하세요.
2. 전혀 모르는 내용은 지어내지 말고 솔직하게 모른다고 답하세요.
3. 너무 길게 설명하지 말고 핵심만 간결하게 답하세요.
4. 선수/팀 이름은 손흥민, 토트넘처럼 한국에서 통용되는 한글 표기를
   사용하세요.
5. 아래 [알려진 이름·별명] 목록에 있는 이름이나 별명은 반드시 그 선수/팀으로
   해석하세요. 목록에도 없고 확실히 아는 이름이 아니면, 추측해서 설명하지 말고
   "정확히 알지 못합니다"라고 답하세요.
6. 현재 소속팀처럼 시간이 지나면 바뀌는 정보는 "제가 아는 시점 기준"이라고
   밝히거나, 확실하지 않으면 말하지 마세요.

[알려진 이름·별명] (오른쪽은 DB 저장명 검색어이므로 답변에는 한글 이름을 쓰세요)
""" + TEAM_NAME_MAP + PLAYER_NAME_MAP + "\n"


# 한글 별명/표기 -> 정식 한글 이름. GPT 지식 답변에서 "덕베"처럼 낯선 별명을
# GPT가 못 알아보는 문제를 막기 위해, 코드가 질문 속 별명을 정식 이름으로 풀어 준다.
PLAYER_ALIAS_TO_FULL = {
    "쏘니": "손흥민",
    "홀란드": "엘링 홀란드",
    "홀란": "엘링 홀란드",
    "모하메드 살라": "모하메드 살라",
    "살라": "모하메드 살라",
    "덕배": "케빈 데브라위너",
    "덕베": "케빈 데브라위너",
    "데브라위너": "케빈 데브라위너",
    "더브라위너": "케빈 데브라위너",
    "부카요 사카": "부카요 사카",
    "사카": "부카요 사카",
    "필 포든": "필 포든",
    "포든": "필 포든",
    "마르틴 외데고르": "마르틴 외데고르",
    "외데고르": "마르틴 외데고르",
}


def _expand_aliases(text: str) -> str:
    """질문 속 별명을 '정식이름(별명)' 형태로 풀어 줍니다. 예: 덕베 -> 케빈 데브라위너(덕베)"""
    for alias in sorted(PLAYER_ALIAS_TO_FULL, key=len, reverse=True):
        full = PLAYER_ALIAS_TO_FULL[alias]
        if alias in text and full not in text:
            text = text.replace(alias, f"{full}({alias})", 1)
    return text


def generate_gpt_fallback_answer(
    question: str,
    history: list[dict] | None = None,
) -> str | None:
    """
    DB 조회가 재시도 끝에 실패했을 때, GPT의 일반 지식으로 답변을
    시도합니다. 이 함수가 반환하는 값은 DB로 검증되지 않았으므로,
    호출하는 쪽(answer_question)에서 반드시 answer_source로 출처를
    구분해 표시해야 합니다.

    API 오류 등으로 실패하면 조용히 None을 반환합니다.
    """
    if client is None:
        return None

    if not question:
        return None

    messages = [{"role": "system", "content": FALLBACK_SYSTEM_PROMPT}]

    if history:
        messages.extend(history[-MAX_HISTORY_TURNS * 2:])

    messages.append({"role": "user", "content": expand_for_answer(question)})

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            temperature=0.3,
        )
        content = response.choices[0].message.content
    except Exception:
        return None

    if not content:
        return None

    return content.strip()


# ============================================================
# 8. 전체 질문 처리
# ============================================================

RECORD_RANK_RE = re.compile(r"통산|역대|가장 많|최다|최고|1위|순위|랭킹|상위|득점왕|도움왕|몇 ?(골|개|번|경기|회)")
RECORD_TOPIC_RE = re.compile(r"골|득점|어시스트|도움|경기|무승부|이긴|승리|카드")

MAX_REGENERATIONS = 2  # 설계: SQL 검증·실행 실패 시 재생성 최대 2회


RECENT_RE = re.compile(r"이번 ?시즌|올 ?시즌|올해|현재|지금|최근|어제|오늘|이번 ?주|방금")


def latest_season_code() -> str | None:
    """경기가 실제로 치러진 가장 최근 시즌 코드. 예: '2627'."""
    try:
        conn = _open_readonly_connection()
        try:
            row = conn.execute(
                "SELECT season FROM matches WHERE home_score IS NOT NULL "
                "ORDER BY date DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        return row[0] if row else None
    except Exception:
        return None


def latest_match_date() -> str | None:
    """DB에 담긴 가장 최근 경기 날짜 (YYYY-MM-DD)."""
    try:
        conn = _open_readonly_connection()
        try:
            row = conn.execute("SELECT MAX(date) FROM matches WHERE home_score IS NOT NULL").fetchone()
        finally:
            conn.close()
        return (row[0] or "")[:10] or None
    except Exception:
        return None


def _fix_season_literal(question: str, sql: str) -> str:
    """질문에 시즌이 하나만 있고 SQL의 시즌 값이 그와 다르면 올바른 코드로 바로잡는다.
    (GPT가 2020-21을 '2121'처럼 잘못 바꾸는 경우를 막는다)"""
    codes = season_codes(question)
    if len(set(codes)) != 1:
        return sql
    code = codes[0]
    found = set(re.findall(r"season\s*=\s*'(\d{4})'", sql, flags=re.IGNORECASE))
    if len(found) == 1 and code not in found:
        return re.sub(r"(season\s*=\s*)'\d{4}'", rf"\1'{code}'", sql, flags=re.IGNORECASE)
    return sql


def check_sql_semantics(question: str, sql: str) -> str | None:
    """문법은 맞지만 뜻이 틀린 SQL의 대표 유형을 잡아낸다. 문제가 있으면 설명 문장을 돌려준다."""
    q = question or ""
    low = (sql or "").lower()
    if re.search(r"어시스트|도움", q) and re.search(r"group\s+by\s+player\b", low):
        has_assist_filter = re.search(r"assist_player\s*(=|like)", low)
        if "assist_player" in low and "group by assist_player" not in low and not has_assist_filter:
            return "어시스트 순위는 득점자(player)가 아니라 어시스트한 선수(assist_player) 기준으로 GROUP BY 해야 합니다."

    # 질문에 나온 시즌이 SQL의 season 조건에 정확히 들어 있어야 한다 (예: 2020-21 -> '2021')
    for code in season_codes(q):
        if f"'{code}'" not in low:
            return f"질문의 시즌은 season = '{code}' 입니다. SQL의 시즌 조건을 확인하세요."

    # 질문에 기간 표현이 없는데 SQL이 임의로 시즌을 한정하면 엉뚱한 값(예: 최신 시즌 0골)이 나온다
    if re.search(r"season\s*(=|in)", low) and not season_codes(q) and not RECENT_RE.search(q) \
            and not re.search(r"시즌|작년|지난|재작년|\d{4}|\d{2}[-/]\d{2}", q):
        return "질문에 시즌·기간 표현이 없으므로 season 조건을 빼고 전체 기간으로 집계하세요."

    # WHERE 최상위 수준에서 AND와 OR가 괄호 없이 섞이면 조건이 엉뚱하게 묶인다
    where = re.search(r"\bwhere\b(.*)", low, re.DOTALL)
    if where:
        depth, ops = 0, set()
        for tok in re.finditer(r"\(|\)|\band\b|\bor\b", where.group(1)):
            t = tok.group(0)
            if t == "(":
                depth += 1
            elif t == ")":
                depth -= 1
            elif depth == 0:
                ops.add(t)
        if {"and", "or"} <= ops:
            return "WHERE 절에서 AND와 OR가 괄호 없이 섞여 있습니다. OR 조건은 괄호로 묶으세요."

    kinds = mentioned_kinds(q)

    # 홈/원정을 UNION ALL로 나눠 놓고 바깥에서 다시 합치지 않은 채 순위만 매기면 한쪽만 집계된다
    if "union all" in low and re.search(r"limit\s+1\b", low) and not re.search(r"from\s*\(\s*select", low):
        return "UNION ALL로 나눈 결과를 바깥 쿼리에서 팀별로 다시 SUM하지 않았습니다. match_events.team 기준으로 계산하세요."

    # 팀 총 득점은 상대 팀 골이 섞이지 않게 matches(스코어)나 team 컬럼으로 계산해야 한다
    if (
        kinds["team"]
        and not kinds["player"]
        and re.search(r"총 ?(골|득점)|넣은 ?골|골 ?수|득점 ?수", q)
        and not re.search(r"득점자|누가|누구|어시스트", q)
        and "from match_events" in low
        and not re.search(r"\bteam\s*(=|like)", low)
    ):
        return "팀의 총 골 수는 matches의 home_score/away_score 또는 match_events.team 조건으로 계산해야 합니다."

    # 두 선수를 비교하는 질문인데 한 명만 반환하는 SQL
    if len(kinds["player"]) >= 2 and re.search(r"limit\s+1\b", low):
        return "두 선수를 비교하는 질문입니다. LIMIT 1을 쓰지 말고 모두의 값을 반환하세요."
    return None


def _build_repair_prompt(question: str, sql: str, exc: Exception | None) -> str:
    """실패한 SQL과 오류를 GPT에게 알려 주고 다시 생성하게 하는 프롬프트."""
    return f"""
다음 사용자의 질문에 대해 생성한 SQL이 검증 또는 실행에 실패했습니다.

사용자 질문:
{question}

생성된 SQL:
{sql}

오류:
{exc}

위 오류를 수정하여 다시 실행 가능한 하나의 SELECT SQL만 출력하세요.

반드시:
- matches 또는 match_events만 사용
- SELECT만 사용
- INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/PRAGMA/ATTACH 금지
- 설명이나 마크다운 금지
"""



# ============================================================
# 답변 검증 (E07)
# ============================================================

_NUM_RE = re.compile(r"\d[\d,]*\.?\d*")


def _numbers_in(text: str) -> set[float]:
    out = set()
    for m in _NUM_RE.findall(text or ""):
        try:
            out.add(float(m.replace(",", "").rstrip(".")))
        except ValueError:
            pass
    return out


def verify_answer(question: str, columns: list, rows: list, answer: str) -> bool:
    """답변 속 숫자가 조회 결과(또는 질문, 행 개수·순번)에 근거하는지 확인한다."""
    allowed: set[float] = set()
    for row in rows:
        for v in row:
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                allowed.add(float(v))
            elif isinstance(v, str):
                allowed |= _numbers_in(v)
    allowed |= _numbers_in(question)
    allowed |= set(float(i) for i in range(0, len(rows) + 2))  # 순위·건수
    allowed |= {float(len(rows))}

    # 합계·평균 같은 파생값은 허용: 숫자 열의 합계
    for ci in range(len(columns)):
        vals = [r[ci] for r in rows if isinstance(r[ci], (int, float)) and not isinstance(r[ci], bool)]
        if vals:
            allowed.add(float(sum(vals)))

    for n in _numbers_in(answer):
        if n in allowed:
            continue
        # 소수 반올림 허용 (예: 12.345 -> 12.3)
        if any(abs(n - a) <= 0.06 + abs(a) * 0.005 for a in allowed):
            continue
        # 연도·시즌 표기 (예: 2024) 는 질문/결과에 있으면 위에서 통과, 없으면 의심
        return False
    return True


def answer_question(
    question: str,
    history: list[dict] | None = None,
    max_retries: int = 1,
) -> dict:
    """
    질문 하나를 처리하여 Streamlit에서 바로 사용할 수 있는 dict를 반환합니다.

    반환 형식:
    {
        "sql": 생성된 SQL,
        "columns": 컬럼 목록,
        "rows": 조회 결과,
        "answer": 자연어 답변,
        "insight": 추가 인사이트 한 줄 (없으면 None),
        "error": 오류 메시지 또는 None
    }
    """

    result = {
        "sql": "",
        "columns": [],
        "rows": [],
        "answer": None,
        "answer_source": None,
        "insight": None,
        "followups": [],
        "error": None,
        "error_code": None,
    }

    question = (question or "").strip()

    # [① 입력 검증] 실패 시 E01
    code = validate_question(question)
    if code:
        result["error"] = error_message(code)
        result["error_code"] = code
        return result

    # --------------------------------------------------------
    # 1~2) SQL 생성 → 검증 → 실행
    #      실패하면 오류 내용을 알려 주며 다시 생성한다 (최초 1회 + 재생성 최대 2회).
    #      모두 실패하면 E03.
    # --------------------------------------------------------
    sql = ""
    last_exc = None
    columns, rows = [], []
    succeeded = False
    next_prompt = None
    # 기록·순위 질문은 처음부터 SQL을 만들도록 강제 (GPT가 "DB에 없음"으로 빠지는 것을 막는다)
    force_sql = bool(RECORD_RANK_RE.search(question) and RECORD_TOPIC_RE.search(question))

    for attempt in range(MAX_REGENERATIONS + 1):
        try:
            if next_prompt:
                sql = question_to_sql(next_prompt, history, force_sql)
                next_prompt = None
            elif attempt == 0:
                sql = question_to_sql(question, history, force_sql)
            else:
                sql = question_to_sql(
                    _build_repair_prompt(question, sql, last_exc),
                    history,
                    force_sql,
                )

            result["sql"] = sql
            missing = missing_entities(question, sql)
            if missing:
                # 질문에 나온 선수·팀 조건이 SQL에서 빠졌으면 다시 만들게 한다
                raise ValueError(
                    "질문에 나온 다음 이름이 SQL 조건에 없습니다: " + ", ".join(missing)
                )
            sql = _fix_season_literal(question, sql)
            result["sql"] = sql
            semantic_issue = check_sql_semantics(question, sql)
            if semantic_issue:
                raise ValueError(semantic_issue)
            columns, rows = run_sql(sql)
            succeeded = True
            break

        except ScopeError:
            result["sql"] = ""
            result["error"] = error_message("E02")
            result["error_code"] = "E02"
            return result

        except NotInDBError:
            # "통산 득점 1위"처럼 DB 집계로 답할 수 있는 기록·순위 질문이면 SQL로 한 번 더 시도
            if (
                attempt == 0
                and RECORD_RANK_RE.search(question)
                and RECORD_TOPIC_RE.search(question)
            ):
                next_prompt = (
                    question
                    + "\n(참고: 이 질문은 match_events/matches 집계로 답할 수 있습니다. "
                    "NOT_IN_DB 대신 SELECT SQL을 작성하세요.)"
                )
                continue

            # 축구 관련이지만 DB로 답할 수 없는 질문 → GPT 지식 답변 (배지로 구분)
            result["sql"] = ""
            fallback_answer = None
            try:
                fallback_answer = generate_gpt_fallback_answer(question, history)
            except Exception:
                fallback_answer = None

            if fallback_answer:
                result["answer"] = fallback_answer
                result["answer_source"] = "gpt_fallback"
            else:
                result["error"] = error_message("E03", "DB에 없는 정보이고 AI 답변도 받지 못했습니다.")
                result["error_code"] = "E03"
            return result

        except QueryTimeout:
            # 오래 걸리는 쿼리는 다시 만들어도 같은 결과일 가능성이 높아 재시도하지 않는다.
            result["error"] = error_message("E06")
            result["error_code"] = "E06"
            return result

        except LLMError as exc:
            # AI 서비스 자체 문제는 같은 요청을 반복해도 소용이 없다.
            result["error"] = error_message(exc.code, str(exc))
            result["error_code"] = exc.code
            return result

        except Exception as exc:
            last_exc = exc

    if not succeeded:
        # [E03] 재생성 한도를 넘김 → 마지막 수단으로 GPT 지식 기반 답변 시도
        result["error_code"] = "E03"

        fallback_answer = None
        try:
            fallback_answer = generate_gpt_fallback_answer(question, history)
        except Exception:
            fallback_answer = None

        if fallback_answer:
            result["answer"] = fallback_answer
            result["answer_source"] = "gpt_fallback"
        else:
            result["error"] = error_message("E03", f"마지막 오류: {last_exc}")

        return result

    # --------------------------------------------------------
    # 3) 결과 자연어 요약
    # --------------------------------------------------------
    result["columns"] = columns
    result["rows"] = rows

    if not rows:
        # [E04] 0건: 오류가 아니라 안내만 한다.
        result["error_code"] = "E04"
        result["answer"] = error_message("E04")
        result["answer_source"] = "db"
    else:
        try:
            answer_text = summarize_result(question, columns, rows)
            if not verify_answer(question, columns, rows, answer_text):
                # 근거 없는 숫자가 섞였으면 한 번 더 요약 -> 그래도 틀리면 결과를 그대로 보여준다.
                answer_text = summarize_result(question, columns, rows)
                if not verify_answer(question, columns, rows, answer_text):
                    answer_text = _fallback_answer(columns, rows)
                    result["error_code"] = "E07"
                    result["answer"] = answer_text + "\n\n" + error_message("E07")
                    result["answer_source"] = "db"
                    answer_text = None
            if answer_text is not None:
                result["answer"] = answer_text
                result["answer_source"] = "db"
        except Exception as exc:
            # 이 단계가 실패해도 SQL 결과는 이미 정상적으로 조회됨
            result["answer"] = _fallback_answer(columns, rows)
            result["answer_source"] = "db"
            result["error"] = (
                "데이터 조회는 성공했지만 답변 요약 중 문제가 발생했습니다: "
                f"{exc}"
            )
            result["error_code"] = "E05"

    # --------------------------------------------------------
    # 4) 추가 인사이트 한 줄 (실패해도 메인 답변에 영향 없음)
    # --------------------------------------------------------
    # "이번 시즌·최근·오늘" 같은 표현은 DB가 어디까지 최신인지 알려 준다
    if RECENT_RE.search(question) and result.get("answer") and result.get("answer_source") == "db":
        latest = latest_match_date()
        if latest:
            result["answer"] += (
                f"\n\n※ 데이터베이스의 가장 최근 경기는 {latest}입니다. "
                "그 이후 경기는 자동 수집이 반영된 뒤에 조회할 수 있습니다."
            )

    # 목록이 기본 상한(LIMIT 20)에서 잘렸다면 전체가 아님을 알린다
    if (
        rows
        and len(rows) >= DEFAULT_RESULT_LIMIT
        and re.search(rf"\blimit\s+{DEFAULT_RESULT_LIMIT}\s*;?\s*$", result["sql"], re.IGNORECASE)
        and not re.search(r"\bgroup\s+by\b", result["sql"], re.IGNORECASE)
        and result.get("answer")
    ):
        result["answer"] += (
            f"\n\n※ 결과가 많아 {DEFAULT_RESULT_LIMIT}건만 표시했습니다. "
            "전체가 아닐 수 있으니 시즌이나 기간을 지정해 다시 물어보세요."
        )

    # 통산·역대 질문은 DB에 담긴 기간 기준임을 알린다
    if (
        result.get("answer_source") == "db"
        and rows
        and re.search(r"통산|역대|전체 기간|모든 시즌", question)
        and result.get("answer")
    ):
        result["answer"] += "\n\n※ 데이터베이스에 수록된 2014-15 시즌 이후 기록 기준입니다."

    if rows and len(rows) <= 5:
        try:
            result["insight"] = generate_insight(question, columns, rows)
        except Exception:
            result["insight"] = None

    # --------------------------------------------------------
    # 5) 후속 질문 추천 (실패해도 메인 답변에 영향 없음)
    # --------------------------------------------------------
    try:
        result["followups"] = generate_followup_questions(
            question,
            result.get("answer") or "",
        )
    except Exception:
        result["followups"] = []

    return result

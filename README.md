# ⚽ EPL 데이터 챗봇

프리미어리그 경기 결과·득점자·어시스트를 한글 자연어로 물으면, GPT가 SQL로 바꿔 SQLite DB에서 조회하고
**조회 결과로만** 답해 주는 챗봇입니다. 근거가 되는 SQL을 화면에서 확인할 수 있습니다.

## 폴더 구조
```
epl-chatbot/
├── app.py                    # Streamlit 챗봇 화면 (진입점)
├── text_to_sql.py            # 질문 → SQL → 조회 → 답변, 검증·재생성·오류 처리
├── fast_path.py              # 빠른 경로: 자주 묻는 질문을 GPT 없이 고정 SQL로 조회
├── cards.py                  # 빠른 경로 결과 카드(프로필·비교·상대전적) HTML
├── theme.py                  # 화면 디자인(다크 스코어보드 테마) CSS
├── .streamlit/config.toml    # 다크 테마 색상 설정
├── error_codes.py            # 오류 코드 E01~E09 문구
├── start_auto_collect.bat    # 자동 수집 실행 (Windows, 더블클릭)
├── rate_limiter.py           # 호출 제한 (E08): 세션당 분당 5회, 하루 200회
├── query_logger.py           # 처리 기록 저장 (app_log.db)
├── pages/admin.py            # 관리자 화면 (/admin, 비밀번호 필요)
├── tests/accuracy_test.py    # 30문항 정확도 테스트 (OpenAI 키 필요)
├── tests/fast_path_test.py   # 빠른 경로 정답 대조 테스트 (키 없이 실행)
├── tests/functional_test.py  # 기능·예외·통합 테스트 (키 없이 실행)
├── tests/trace_question.py   # 질문 하나의 처리 과정(SQL·거부 이유) 추적 (OpenAI 키 필요)
├── live_scores.py            # 진행 중인 EPL 경기 실시간 스코어 (API-Football 무료)
├── ai_commentary.py          # AI 해설: DB 기록만으로 GPT가 쓴 해설 + 숫자 검증
├── rag.py                    # 문서 근거 답변(RAG): knowledge/ 문서 검색 → 근거 답변 + 출처
├── knowledge/                # RAG 문서 (경기 규칙·리그 제도·구단 정보·데이터 안내, 직접 작성)
├── tests/ai_features_check.py # AI 해설·RAG 실제 GPT 확인 (OpenAI 키 필요)
├── requirements.txt
├── .env                      # API 키·관리자 비밀번호 (직접 만들기, 공유 금지)
├── database/
│   ├── schema.sql            # matches / match_events 테이블 정의
│   ├── db_utils.py           # DB 연결/초기화
│   ├── aliases.py            # 한글 별명 사전 (선수 117명, 팀 35개)
│   ├── entity_resolver.py    # 임베딩 기반 이름 매칭
│   └── match_dedupe.py       # 두 소스의 같은 경기 찾기
└── data_collection/
    ├── collect_understat.py        # 득점자/시간/xG 수집
    ├── collect_api_football.py     # 어시스트/카드 보완 수집
    ├── dedupe_sources.py           # 중복 골 병합 (--apply로 실제 반영)
    ├── update_current_season.py    # 진행 중인 시즌 갱신 (Understat, 무료, 반복 실행 가능)
    ├── collect_history_results.py  # 2000-01~2013-14 경기 결과 (football-data.co.uk)
    ├── fill_scores_football_data.py # Understat 장애 시 이번 시즌 스코어만 보완 (football-data.co.uk)
    ├── daily_update.bat            # 매일 자동 갱신 (작업 스케줄러용)
    └── auto_collect.py             # 경기 종료 자동 수집 (30분 간격)
```

## 시작하기

### 1. 설치
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt            # 챗봇 실행용
pip install -r requirements-collect.txt    # 데이터 수집까지 할 때 (soccerdata 포함)
```

### 2. `.env` 만들기
```
OPENAI_API_KEY=sk-...
API_FOOTBALL_KEY=...            # 자동 수집·보완 수집에 사용 (api-sports.io)
ADMIN_PASSWORD=원하는비밀번호     # 관리자 화면용
# 선택: API_FOOTBALL_SEASON=2025  OPENAI_MODEL=gpt-4o-mini
```

### 3. 데이터 수집 (처음 한 번)
```bash
python data_collection/collect_understat.py
python data_collection/collect_api_football.py     # 하루 100회 제한, 나눠서 실행 가능
python data_collection/dedupe_sources.py           # 미리보기
python data_collection/dedupe_sources.py --apply   # 중복 골 병합 반영
```

### 4. 실행
```bash
streamlit run app.py                    # 챗봇: http://localhost:8501
                                        # 관리자: http://localhost:8501/admin
python data_collection/update_current_season.py  # 진행 중인 시즌 데이터 갱신 (경기가 끝날 때마다)
python data_collection/auto_collect.py  # 카드 등 API-Football 보완 수집 (별도 터미널, 유료 플랜 권장)
python tests/accuracy_test.py           # 정확도 테스트 (OpenAI 호출 발생)
```

## 빠른 경로 (FAST PATH)
질문이 아래 유형에 **정확히** 맞으면 GPT를 거치지 않고 검증된 고정 SQL로 DB를 바로 조회합니다.
애매하거나 시즌·홈/원정·상대팀 같은 추가 조건이 있으면 기존 GPT 경로로 넘어갑니다.

| 유형 | 예시 질문 | 화면 |
|---|---|---|
| 골·어시스트 수 | 쏘니 골 몇 개야? | 큰 숫자 |
| 선수 프로필 | 손흥민 알려줘 | 프로필 카드 + 시즌별 막대 |
| 시즌별 골 | 케인 시즌별 골 수 | 막대 카드 |
| 선수 비교 | 손흥민이랑 케인 비교해줘 | 비교 카드 |
| 팀 상대전적 | 아스날과 맨시티 상대전적 | 상대전적 카드 |

테스트: `python tests/fast_path_test.py` (모든 선수·팀 조합을 다른 SQL로 다시 계산해 대조)

## 동작 방식
1. **입력 검증**(E01) → 2. **범위 확인**(E02): EPL 기록과 무관하면 안내
3. 별명을 DB 이름으로 변환("덕베" → Kevin De Bruyne) → GPT가 SELECT SQL 생성
4. **SQL 검증**: SELECT 한 문장, 허용 테이블만. 실패 시 오류를 알려 최대 2회 재생성(E03)
5. DB는 **읽기 전용**으로 열고 5초 초과 시 중단(E06)
6. 결과를 문장으로 요약하고 **숫자가 조회 결과에 있는지 검증**(E07)
7. DB에 없는 축구 지식은 GPT 지식으로 답하되 "DB로 확인되지 않음" 경고를 표시
8. 인사이트 줄은 JOIN·평균·비율 표현을 막고, `ENABLE_INSIGHT=0`으로 끌 수 있음
9. 모든 처리는 `app_log.db`에 기록, 관리자 화면에서 오류 코드별로 확인

## AI 해설과 문서 근거 답변 (RAG)
- **AI 해설**: 선수 프로필·시즌별 골·선수 비교·팀 상대전적 카드 아래 [AI 해설 보기]를 누르면,
  코드가 DB에서 모은 기록만 가지고 GPT가 3~4문장 해설을 씁니다. 해설 속 숫자가 기록에 없으면 다시 쓰게 하고,
  그래도 틀리면 표시하지 않습니다. 해설에 쓴 기록은 화면에서 펼쳐 볼 수 있습니다.
- **문서 근거 답변**: DB 기록으로 답할 수 없는 질문(경기 규칙, 리그 제도, 구단 정보, 데이터 출처)은
  `knowledge/` 문서에서 가까운 문단 3개를 찾아(임베딩 + 키워드) 그 내용으로만 답하고 출처를 보여 줍니다.
  문서에 없으면 기존처럼 GPT 일반 지식 답변(경고 표시)으로 넘어갑니다. 문서를 고치면 다음 질문부터 바로 반영됩니다.

## 오류 코드
| 코드 | 의미 |
|---|---|
| E01 | 입력이 비었거나 200자 초과, 의미 없는 입력 |
| E02 | EPL 기록과 무관한 질문 |
| E03 | SQL 생성·검증을 재생성 한도까지 실패 |
| E04 | 조건에 맞는 데이터 없음 |
| E05 | AI 서비스 호출 오류 |
| E06 | 조회 시간 5초 초과 |
| E07 | 답변 속 숫자가 조회 결과와 불일치 → 결과를 그대로 표시 |
| E08 | 호출 제한 초과 |
| E09 | 예상하지 못한 오류 |

## 데이터 범위와 갱신
| 데이터 | 기간 | 출처 |
|---|---|---|
| 경기 결과(날짜·팀·스코어) | 2000-01 시즌 ~ 현재 | 2000-01~2013-14: football-data.co.uk / 2014-15~: Understat |
| 골·어시스트·득점 시간 | 2014-15 시즌 ~ 현재 | Understat |
| 진행 중 경기 스코어 | 실시간 (화면에만 표시) | API-Football 무료 플랜 |

- 과거 시즌 경기 결과 다시 받기: `python data_collection/collect_history_results.py`
- 2014-15 이전 시즌의 선수 기록을 물으면 GPT를 부르지 않고 "기록 없음"을 안내합니다.

### 매일 자동 갱신 (윈도우 작업 스케줄러)
`data_collection/daily_update.bat`이 이번 시즌 끝난 경기를 수집해 GitHub에 올리면 배포 앱이 자동으로 반영합니다.
PowerShell에서 한 번만 등록하면 됩니다 (PC가 꺼져 있던 날은 켜진 뒤 실행).
```powershell
$bat = "C:\경로\epl-chatbot\data_collection\daily_update.bat"
$a = New-ScheduledTaskAction -Execute $bat
$t = New-ScheduledTaskTrigger -Daily -At 10:00
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable
Register-ScheduledTask -TaskName "EPL챗봇 데이터 갱신" -Action $a -Trigger $t -Settings $s
```
기록은 `data_collection/daily_update.log`에 남습니다(보기: `Get-Content data_collection\daily_update.log -Encoding UTF8 -Tail 20`).

Understat가 점검 중이면(2026-11 초부터 "We will come back soon" 안내만 보냄) 끝난 경기 **스코어만** football-data.co.uk에서 채웁니다.
득점자·어시스트는 Understat가 돌아온 뒤 첫 실행 때 같은 경기를 덮어쓰며 들어갑니다. soccerdata가 저장해 둔 안내 페이지는 실행할 때마다 지우므로 Understat가 돌아오면 자동으로 정상 수집됩니다.
football-data.co.uk는 주말 경기를 보통 하루 이틀 뒤에 올립니다. 지우려면 `Unregister-ScheduledTask -TaskName "EPL챗봇 데이터 갱신"`.

### 실시간 경기 카드
배포 환경의 Secrets에 `API_FOOTBALL_KEY`를 넣으면, EPL 경기가 진행 중일 때 첫 화면 위에 LIVE 카드가 보입니다.
무료 한도(하루 100회)를 넘지 않게 경기 중 3분, 평소 30분 간격으로만 요청하고 하루 90회에서 멈춥니다.

## 알려진 제약사항
- 같은 골이 두 소스에서 중복 저장되는 문제는 `dedupe_sources.py`로 병합했지만,
  소스마다 집계 기준이 달라 공식 기록과 1~3건 차이가 날 수 있습니다.
- 카드 데이터는 2024-25 시즌만 있습니다.
- API-Football 무료 플랜은 하루 100회이고, 시즌 경기 목록은 2022~2024 시즌만 받을 수 있습니다
  (2026-11 확인). 그래서 이번 시즌 DB 갱신은 Understat + PC 예약 작업으로 하고, API-Football은 진행 중 경기 스코어에만 씁니다.
- 답변 검증은 숫자만 확인합니다. 이름은 "생성된 SQL"과 결과 표로 확인하세요.
- GPT가 만든 SQL이 문법은 맞아도 의미가 틀릴 수 있어, 정확도 테스트로 계속 점검합니다.

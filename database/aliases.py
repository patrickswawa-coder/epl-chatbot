"""
한글 선수·팀 이름/별명 -> DB 저장명(영문) 사전.

질문 속 별명("덕베", "쏘니", "맨유" 등)을 AI가 알아보지 못해 틀리는 일을 막기 위해,
AI에게 질문을 보내기 전에 코드가 별명을 정확한 이름으로 풀어 줍니다.

- expand_for_sql(text)   : "덕베 골" -> "덕베(DB 선수명: Kevin De Bruyne) 골"   (SQL 생성용)
- expand_for_answer(text): "덕베 누구야" -> "케빈 데브라위너(덕베) 누구야"       (GPT 지식 답변용)

새 선수를 추가하려면 PLAYERS 목록에 (한글 정식이름, [별명들], DB 영문이름) 한 줄만 넣으면 됩니다.
DB 영문이름은 football_history.db의 match_events.player 값과 같아야 합니다.
"""
import re
import unicodedata

# (한글 정식 이름, [별명/표기들], DB 저장명)
PLAYERS = [
    ("해리 케인", ["케인", "해리케인"], "Harry Kane"),
    ("모하메드 살라", ["살라", "모 살라", "이집션 킹", "이집트 왕"], "Mohamed Salah"),
    ("제이미 바디", ["바디", "제이미바디"], "Jamie Vardy"),
    ("세르히오 아게로", ["아게로", "쿤 아게로", "쿤"], "Sergio Agüero"),
    ("손흥민", ["쏘니", "소니", "흥민", "손흥민"], "Son Heung-Min"),
    ("엘링 홀란드", ["홀란드", "홀란", "홀란트", "엘링 홀란"], "Erling Haaland"),
    ("라힘 스털링", ["스털링", "스털링"], "Raheem Sterling"),
    ("사디오 마네", ["마네", "사디오마네"], "Sadio Mané"),
    ("칼럼 윌슨", ["칼럼 윌슨"], "Callum Wilson"),
    ("크리스 우드", ["크리스 우드"], "Chris Wood"),
    ("올리 왓킨스", ["왓킨스", "올리 왓킨스"], "Ollie Watkins"),
    ("마커스 래시포드", ["래시포드", "래쉬포드"], "Marcus Rashford"),
    ("로멜루 루카쿠", ["루카쿠"], "Romelu Lukaku"),
    ("리야드 마레즈", ["마레즈"], "Riyad Mahrez"),
    ("호베르투 피르미누", ["피르미누", "피르미뇨"], "Roberto Firmino"),
    ("가브리엘 제주스", ["제주스", "제수스", "헤수스"], "Gabriel Jesus"),
    ("히샬리송", ["히샬리송", "리샬리송"], "Richarlison"),
    ("케빈 데브라위너", ["덕배", "덕베", "데브라위너", "더브라위너", "케빈 더브라위너", "케빈 데 브라위너"], "Kevin De Bruyne"),
    ("대니 잉스", ["잉스"], "Danny Ings"),
    ("브루누 페르난드스", ["브루노 페르난데스", "브루노 페르난드스", "브루누 페르난데스", "페르난데스", "브페", "브루노"], "Bruno Fernandes"),
    ("도미닉 칼버트르윈", ["칼버트르윈", "칼버트 르윈"], "Dominic Calvert-Lewin"),
    ("피에르에메릭 오바메양", ["오바메양", "오바메양"], "Pierre-Emerick Aubameyang"),
    ("마이클 안토니오", ["안토니오", "미칼 안토니오"], "Michail Antonio"),
    ("필 포든", ["포든"], "Phil Foden"),
    ("라울 히메네스", ["히메네스", "하우 히메네스"], "Raúl Jiménez"),
    ("윌프리드 자하", ["자하"], "Wilfried Zaha"),
    ("재로드 보웬", ["보웬", "자로드 보웬"], "Jarrod Bowen"),
    ("대니 웰벡", ["웰백", "웰벡"], "Danny Welbeck"),
    ("알렉시스 산체스", ["산체스", "알렉시스 산체스"], "Alexis Sánchez"),
    ("앙토니 마르시알", ["마르시알"], "Anthony Martial"),
    ("디오구 조타", ["조타"], "Diogo Jota"),
    ("올리비에 지루", ["지루"], "Olivier Giroud"),
    ("에당 아자르", ["아자르"], "Eden Hazard"),
    ("부카요 사카", ["사카"], "Bukayo Saka"),
    ("알렉산데르 이사크", ["이사크", "이삭", "아이작"], "Alexander Isak"),
    ("크리스티안 벤테케", ["벤테케"], "Christian Benteke"),
    ("제임스 워드프라우즈", ["워드프라우즈", "워드프라우스"], "James Ward-Prowse"),
    ("하비 반스", ["하비 반스"], "Harvey Barnes"),
    ("제임스 매디슨", ["매디슨"], "James Maddison"),
    ("알렉상드르 라카제트", ["라카제트"], "Alexandre Lacazette"),
    ("브라이언 음뵈모", ["음뵈모", "음베우모", "음뷔모"], "Bryan Mbeumo"),
    ("디에구 코스타", ["디에고 코스타", "디에구 코스타"], "Diego Costa"),
    ("귀르피 시구르드손", ["시구르드손", "시구르손"], "Gylfi Sigurdsson"),
    ("레안드로 트로사르", ["트로사르"], "Leandro Trossard"),
    ("델레 알리", ["델리 알리", "델레알리"], "Dele Alli"),
    ("크리스티안 에릭센", ["에릭센"], "Christian Eriksen"),
    ("콜 파머", ["파머", "팔머", "콜 팔머"], "Cole Palmer"),
    ("베르나르두 실바", ["베르나르두 실바", "베르나르두"], "Bernardo Silva"),
    ("일카이 귄도안", ["귄도안", "권도안", "귄도간"], "Ilkay Gündogan"),
    ("카이 하베르츠", ["하베르츠", "하베르츠"], "Kai Havertz"),
    ("윌리안", ["윌리안"], "Willian"),
    ("도미닉 솔랑케", ["솔랑케", "솔란케"], "Dominic Solanke"),
    ("에베레치 에제", ["에제"], "Eberechi Eze"),
    ("가브리엘 마르티넬리", ["마르티넬리"], "Gabriel Martinelli"),
    ("마르코 아르나우토비치", ["아르나우토비치"], "Marko Arnautovic"),
    ("마테우스 쿠냐", ["쿠냐"], "Matheus Cunha"),
    ("필리페 쿠티뉴", ["쿠티뉴"], "Philippe Coutinho"),
    ("알렉산다르 미트로비치", ["미트로비치"], "Aleksandar Mitrovic"),
    ("다비드 실바", ["다비드 실바"], "David Silva"),
    ("저메인 데포", ["데포"], "Jermain Defoe"),
    ("앙투안 세메뇨", ["세메뇨"], "Antoine Semenyo"),
    ("이반 토니", ["이반 토니", "아이반 토니"], "Ivan Toney"),
    ("알렉스 이워비", ["이워비"], "Alex Iwobi"),
    ("마르틴 외데고르", ["외데고르", "외데가르드", "외데가드"], "Martin Odegaard"),
    ("테오 월콧", ["월콧"], "Theo Walcott"),
    ("웨인 루니", ["루니"], "Wayne Rooney"),
    ("모건 깁스화이트", ["깁스화이트", "깁스 화이트"], "Morgan Gibbs-White"),
    ("코디 학포", ["학포", "각포", "곽포"], "Cody Gakpo"),
    ("메이슨 마운트", ["마운트"], "Mason Mount"),
    ("앤서니 고든", ["앤서니 고든"], "Anthony Gordon"),
    ("버질 판다이크", ["판다이크", "반다이크", "판 다이크", "반 다이크", "버질 반 다이크"], "Virgil van Dijk"),
    ("브루누 기마랑이스", ["기마랑이스", "브루노 기마랑이스", "기마랑이스"], "Bruno Guimarães"),
    ("잭 그릴리시", ["그릴리시"], "Jack Grealish"),
    ("제시 린가드", ["린가드"], "Jesse Lingard"),
    ("루이스 디아스", ["루이스 디아스", "디아스"], "Luis Díaz"),
    ("폴 포그바", ["포그바"], "Paul Pogba"),
    ("알렉시스 맥알리스터", ["맥알리스터", "맥 알리스터"], "Alexis Mac Allister"),
    ("후안 마타", ["마타"], "Juan Mata"),
    ("메수트 외질", ["외질", "오질"], "Mesut Özil"),
    ("타미 에이브러햄", ["에이브러햄", "타미 아브라함"], "Tammy Abraham"),
    ("조르지뉴 바이날둠", ["바이날둠", "와이날둠", "비날둠"], "Georginio Wijnaldum"),
    ("브레넌 존슨", ["브레넌 존슨", "브렌넌 존슨"], "Brennan Johnson"),
    ("다르윈 누녜스", ["누녜스", "누네스", "다윈 누녜스"], "Darwin Núñez"),
    ("데클란 라이스", ["라이스", "데클란 라이스"], "Declan Rice"),
    ("제임스 밀너", ["밀너"], "James Milner"),
    ("르로이 사네", ["사네", "르로이 사네"], "Leroy Sané"),
    ("마르코스 알론소", ["마르코스 알론소"], "Marcos Alonso"),
    ("에디 은케티아", ["은케티아", "엔케티아"], "Eddie Nketiah"),
    ("황희찬", ["희찬", "황희찬"], "Hee-Chan Hwang"),
    ("조엘링톤", ["조엘링톤", "조엘링턴"], "Joelinton"),
    ("니콜라스 잭슨", ["니콜라스 잭슨", "잭슨"], "Nicolas Jackson"),
    ("아론 램지", ["램지"], "Aaron Ramsey"),
    ("미토마 가오루", ["미토마"], "Kaoru Mitoma"),
    ("로드리", ["로드리"], "Rodri"),
    ("데얀 쿨루세프스키", ["쿨루세프스키", "쿨루셉스키"], "Dejan Kulusevski"),
    ("디보크 오리기", ["오리기"], "Divock Origi"),
    ("메이슨 그린우드", ["그린우드"], "Mason Greenwood"),
    ("티아고 알칸타라", ["티아고", "티아구"], "Thiago"),
    ("제르단 샤키리", ["샤키리"], "Xherdan Shaqiri"),
    ("조르지뉴", ["조르지뉴", "조르징유"], "Jorginho"),
    ("야야 투레", ["야야 투레", "야야투레"], "Yaya Touré"),
    ("크리스천 풀리식", ["풀리식", "풀리시치"], "Christian Pulisic"),
    ("훌리안 알바레스", ["알바레스", "훌리안 알바레스"], "Julián Álvarez"),
    ("페드로 네투", ["페드로 네투", "네투"], "Pedro Neto"),
    ("크리스티아누 호날두", ["호날두", "크리스티아누 호날두", "CR7", "씨알칠"], "Cristiano Ronaldo"),
    ("대니얼 스터리지", ["스터리지"], "Daniel Sturridge"),
    ("코너 갤러거", ["갤러거", "콘로 갤러거"], "Conor Gallagher"),
    ("트렌트 알렉산더아널드", ["알렉산더아널드", "알렉산더 아놀드", "트렌트", "TAA"], "Trent Alexander-Arnold"),
    ("앤드루 로버트슨", ["로버트슨"], "Andrew Robertson"),
    ("세스크 파브레가스", ["파브레가스", "세스크"], "Cesc Fàbregas"),
    ("키어런 트리피어", ["트리피어"], "Kieran Trippier"),
    ("조던 헨더슨", ["헨더슨"], "Jordan Henderson"),
    ("루카 디뉴", ["디뉴"], "Lucas Digne"),
    ("그라니트 자카", ["자카"], "Granit Xhaka"),
    ("카일 워커", ["워커", "카일 워커"], "Kyle Walker"),
    ("세사르 아스필리쿠에타", ["아스필리쿠에타", "아스필"], "César Azpilicueta"),
    ("아다마 트라오레", ["트라오레", "아다마"], "Adama Traoré"),
]

# (한글 정식 이름, [별명/표기들], DB 저장명)
TEAMS = [
    ("맨체스터 시티", ["맨시티", "맨체스터시티", "맨체스터 시티", "시티즌"], "Manchester City"),
    ("맨체스터 유나이티드", ["맨유", "맨체스터유나이티드", "맨체스터 유나이티드", "레드 데블스"], "Manchester United"),
    ("아스널", ["아스날", "아스널", "거너스", "건너스"], "Arsenal"),
    ("첼시", ["첼시", "블루스"], "Chelsea"),
    ("리버풀", ["리버풀", "레즈"], "Liverpool"),
    ("토트넘", ["토트넘", "토트넘 홋스퍼", "스퍼스", "토트넘홋스퍼"], "Tottenham"),
    ("뉴캐슬", ["뉴캐슬", "뉴캐슬 유나이티드", "까치"], "Newcastle United"),
    ("브라이턴", ["브라이튼", "브라이턴", "브라이턴 앤 호브 알비온"], "Brighton"),
    ("웨스트햄", ["웨스트햄", "웨스트햄 유나이티드", "해머스"], "West Ham"),
    ("에버턴", ["에버튼", "에버턴", "토피스"], "Everton"),
    ("울버햄프턴", ["울버햄튼", "울버햄프턴", "울브스", "울버햄튼 원더러스"], "Wolverhampton Wanderers"),
    ("크리스털 팰리스", ["크리스탈팰리스", "크리스탈 팰리스", "크리스털 팰리스", "팰리스"], "Crystal Palace"),
    ("풀럼", ["풀럼", "풀햄"], "Fulham"),
    ("브렌트퍼드", ["브렌트포드", "브렌트퍼드"], "Brentford"),
    ("노팅엄 포레스트", ["노팅엄포레스트", "노팅엄 포레스트", "노팅엄", "포레스트"], "Nottingham Forest"),
    ("애스턴 빌라", ["애스턴빌라", "애스턴 빌라", "아스톤 빌라", "아스톤빌라", "빌라"], "Aston Villa"),
    ("본머스", ["본머스", "본마우스"], "Bournemouth"),
    ("레스터 시티", ["레스터", "레스터 시티", "레스터시티"], "Leicester"),
    ("리즈 유나이티드", ["리즈", "리즈 유나이티드"], "Leeds"),
    ("번리", ["번리"], "Burnley"),
    ("사우샘프턴", ["사우샘프턴", "사우스햄튼", "사우샘프튼", "세인츠"], "Southampton"),
    ("입스위치", ["입스위치", "입스위치 타운"], "Ipswich"),
    ("노리치", ["노리치", "노리치 시티"], "Norwich"),
    ("왓퍼드", ["왓포드", "왓퍼드"], "Watford"),
    ("셰필드 유나이티드", ["셰필드", "쉐필드", "셰필드 유나이티드"], "Sheffield United"),
    ("루턴 타운", ["루턴", "루튼", "루턴 타운"], "Luton"),
    ("스토크 시티", ["스토크", "스토크 시티"], "Stoke"),
    ("스완지 시티", ["스완지", "스완지 시티"], "Swansea"),
    ("선덜랜드", ["선덜랜드"], "Sunderland"),
    ("헐 시티", ["헐 시티", "헐시티"], "Hull"),
    ("웨스트 브로미치", ["웨스트브롬", "웨스트 브롬", "웨스트브로미치", "웨스트 브로미치", "웨브"], "West Bromwich Albion"),
    ("퀸스 파크 레인저스", ["QPR", "퀸즈 파크 레인저스", "퀸스 파크 레인저스"], "Queens Park Rangers"),
    ("카디프 시티", ["카디프", "카디프 시티"], "Cardiff"),
    ("허더즈필드", ["허더즈필드", "허더스필드"], "Huddersfield"),
    ("미들즈브러", ["미들즈브러", "미들스브러"], "Middlesbrough"),
]

# alias -> (종류, 한글 정식 이름, DB 저장명)
ALIAS = {}
for kind, rows in (("team", TEAMS), ("player", PLAYERS)):
    for ko, aliases, db in rows:
        for a in set(aliases) | {ko}:
            ALIAS.setdefault(a, (kind, ko, db))

# 가장 긴 별명부터 한 번에 찾는다 ("브루노 기마랑이스"가 "브루노"보다 먼저 잡히도록).
# 두 글자 이하 별명은 "지루한 경기"의 '지루'처럼 다른 단어 속에서 잘못 잡히지 않도록,
# 뒤에 한글이 이어지면 조사(은/는/이/가/을/를/의/도/와/과/에/랑/로)일 때만 인정한다.
_PARTICLES = "은는이가을를의도와과에랑로"


def _alt(a: str) -> str:
    e = re.escape(a)
    if len(a) <= 2:
        return rf"{e}(?:(?![가-힣])|(?=[{_PARTICLES}]))"
    return e


_ALTS = "|".join(_alt(a) for a in sorted(ALIAS, key=len, reverse=True))
_FIND = re.compile(rf"(?:{_ALTS})")
_SQL_PATTERN = re.compile(rf"(?:{_ALTS})(?!\(DB )")
_ANSWER_PATTERN = re.compile(rf"(?:{_ALTS})(?![A-Za-z가-힣]*\()")


# "2020-21 시즌", "2020-2021", "20/21시즌" 같은 시즌 표기 -> DB의 4자리 시즌 코드('2021')
_SEASON_LONG = re.compile(r"(?<!\d)(20\d{2})\s*[-/~–]\s*(\d{4}|\d{2})(?!\d)")
_SEASON_SHORT = re.compile(r"(?<!\d)(\d{2})\s*[-/~–]\s*(\d{2})\s*시즌")


def _season_code(start: int, end: int) -> str | None:
    if end % 100 != (start + 1) % 100:
        return None
    return f"{start % 100:02d}{(start + 1) % 100:02d}"


def season_codes(text: str) -> list[str]:
    """질문 속 시즌 표기를 DB 시즌 코드로 바꾼 목록."""
    out = []
    for m in _SEASON_LONG.finditer(text or ""):
        c = _season_code(int(m.group(1)), int(m.group(2)))
        if c:
            out.append(c)
    for m in _SEASON_SHORT.finditer(text or ""):
        c = _season_code(2000 + int(m.group(1)), 2000 + int(m.group(2)))
        if c:
            out.append(c)
    return out


def _expand_seasons(text: str) -> str:
    def long_repl(m):
        c = _season_code(int(m.group(1)), int(m.group(2)))
        return m.group(0) + (f"(DB season: '{c}')" if c else "")

    def short_repl(m):
        c = _season_code(2000 + int(m.group(1)), 2000 + int(m.group(2)))
        return m.group(0) + (f"(DB season: '{c}')" if c else "")

    text = _SEASON_LONG.sub(long_repl, text)
    return _SEASON_SHORT.sub(short_repl, text)


def mentioned_kinds(text: str) -> dict[str, set]:
    """질문에 나온 선수·팀의 DB 이름 집합 {'player': {...}, 'team': {...}}."""
    out = {"player": set(), "team": set()}
    for m in _FIND.finditer(text or ""):
        kind, _, db = ALIAS[m.group(0)]
        out[kind].add(db)
    return out


def expand_for_sql(text: str) -> str:
    """별명·시즌 뒤에 DB 저장명을 붙여 SQL 생성 AI가 정확한 값으로 검색하게 한다."""
    def repl(m):
        kind, _, db = ALIAS[m.group(0)]
        label = "선수명" if kind == "player" else "팀명"
        return f"{m.group(0)}(DB {label}: {db})"

    return _expand_seasons(_SQL_PATTERN.sub(repl, text or ""))


def expand_for_answer(text: str) -> str:
    """별명을 '정식이름(별명)'으로 풀어 GPT 지식 답변이 이름을 알아보게 한다."""
    def repl(m):
        _, ko, _ = ALIAS[m.group(0)]
        alias = m.group(0)
        return alias if alias == ko else f"{ko}({alias})"

    return _ANSWER_PATTERN.sub(repl, text or "")


def _plain(t: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn"
    )


_GENERIC = {"united", "city", "town", "wanderers", "albion", "hotspur", "forest", "palace", "rangers"}


def missing_entities(question: str, sql: str) -> list[str]:
    """질문에 나온 선수·팀 중 SQL 조건에 전혀 반영되지 않은 DB 이름을 돌려준다."""
    seen, missing = set(), []
    sql_p = _plain(sql or "")
    for m in _FIND.finditer(question or ""):
        kind, _, db = ALIAS[m.group(0)]
        if db in seen:
            continue
        seen.add(db)
        full = _plain(db)
        tokens = [t for t in re.split(r"[\s]+", full) if t]
        if kind == "player":
            keys = {full} | {t for t in tokens if len(t) >= 4 and t not in _GENERIC}
        else:
            keys = {full, tokens[0]} if tokens else {full}
        if not any(k in sql_p for k in keys):
            missing.append(db)
    return missing

"""호출 제한 (E08). 세션당 분당 5회, 하루 전체 200회."""
import threading
import time
from datetime import date

PER_MINUTE = 5
PER_DAY = 200

_lock = threading.Lock()
_recent: dict[str, list[float]] = {}
_day = {"date": date.today(), "count": 0}


def check_and_count(session_id: str) -> bool:
    """호출이 허용되면 True(횟수 1 증가), 한도 초과면 False."""
    now = time.time()
    with _lock:
        if _day["date"] != date.today():
            _day["date"], _day["count"] = date.today(), 0
        if _day["count"] >= PER_DAY:
            return False
        hits = [t for t in _recent.get(session_id, []) if now - t < 60]
        if len(hits) >= PER_MINUTE:
            _recent[session_id] = hits
            return False
        hits.append(now)
        _recent[session_id] = hits
        _day["count"] += 1
        return True

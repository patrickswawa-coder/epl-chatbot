"""
지금 진행 중인 EPL 경기의 실시간 스코어 (API-Football 무료 플랜).

- 무료 플랜은 하루 100회 요청이 한도다. 그래서 진행 중인 EPL 경기가 있을 때는 3분마다,
  없을 때는 30분마다 한 번만 실제로 요청하고, 하루 90회를 넘으면 더 요청하지 않는다.
  (앱을 보는 사람이 몇 명이든 서버 전체에서 한 번만 요청하고 결과를 함께 쓴다)
- 무료 플랜은 이번 시즌 경기 목록은 막혀 있지만 진행 중 경기(live=all)는 받을 수 있다.
- 결과는 화면에만 보여주고 DB에는 저장하지 않는다. 끝난 경기는 매일 수집 작업으로 DB에 들어간다.
- 키(API_FOOTBALL_KEY)가 없거나 요청이 실패하면 조용히 빈 목록을 돌려줘 앱은 그대로 동작한다.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import date
from html import escape

import requests

URL = "https://v3.football.api-sports.io/fixtures"
EPL_LEAGUE_ID = 39
INTERVAL_LIVE = 3 * 60       # EPL 경기가 진행 중일 때 다시 묻는 간격(초)
INTERVAL_IDLE = 30 * 60      # 진행 중 경기가 없을 때
DAILY_BUDGET = 90            # 무료 한도 100회 중 사용할 최대치

# API-Football 표기 -> 우리 DB 표기 (나머지는 같다)
API_TEAM_FIX = {
    "Newcastle": "Newcastle United",
    "Wolves": "Wolverhampton Wanderers",
    "Sheffield Utd": "Sheffield United",
    "Nottingham": "Nottingham Forest",
}

# 시간 칸은 숫자 글꼴로 짧게 보여준다 (하프타임 HT, 연장 휴식 BT, 승부차기 PEN)
STATUS_SHORT = {"HT": "HT", "BT": "BT", "P": "PEN", "LIVE": "LIVE"}

_lock = threading.Lock()
_state = {"matches": [], "fetched": 0.0, "day": date.today(), "calls": 0, "error": None}


def _api_key() -> str | None:
    key = os.getenv("API_FOOTBALL_KEY")
    if key:
        return key
    try:  # Streamlit Cloud Secrets
        import streamlit as st

        return st.secrets.get("API_FOOTBALL_KEY")
    except Exception:
        return None


def check_key(fetch=None) -> dict:
    """키가 맞는지 /status로 확인한다 (이 요청은 하루 한도에 포함되지 않는다). 키 값은 돌려주지 않는다."""
    key = _api_key()
    out = {"has_key": bool(key), "ok": False, "message": "", "used": None, "limit": None,
           "calls_today": _state["calls"], "last_error": _state["error"]}
    if not key:
        out["message"] = "API_FOOTBALL_KEY가 설정되어 있지 않습니다 (Secrets 또는 .env 확인)."
        return out
    try:
        if fetch is None:
            resp = requests.get(URL.replace("/fixtures", "/status"), headers={"x-apisports-key": key}, timeout=8)
            resp.raise_for_status()
            payload = resp.json()
        else:
            payload = fetch()
    except Exception as exc:
        out["message"] = f"API 서버 연결 실패: {type(exc).__name__}"
        return out
    errors = payload.get("errors")
    if errors:
        out["message"] = f"키 오류: {errors}"
        return out
    resp_ = payload.get("response") or {}
    req = resp_.get("requests") or {}
    out.update(ok=True, used=req.get("current"), limit=req.get("limit_day"),
               message=f"키 정상 · 플랜 {((resp_.get('subscription') or {}).get('plan')) or '-'}")
    return out


def parse_live(payload: dict) -> list[dict]:
    """API 응답에서 EPL 경기만 골라 화면에 필요한 값으로 정리한다."""
    out = []
    for item in payload.get("response") or []:
        if (item.get("league") or {}).get("id") != EPL_LEAGUE_ID:
            continue
        fx = item.get("fixture") or {}
        status = fx.get("status") or {}
        teams = item.get("teams") or {}
        goals = item.get("goals") or {}
        home = (teams.get("home") or {}).get("name") or "홈팀"
        away = (teams.get("away") or {}).get("name") or "원정팀"
        out.append({
            "home": API_TEAM_FIX.get(home, home),
            "away": API_TEAM_FIX.get(away, away),
            "hs": goals.get("home"),
            "as": goals.get("away"),
            "minute": status.get("elapsed"),
            "status": status.get("short") or "",
        })
    return out


def get_live_matches(now: float | None = None, fetch=None) -> list[dict]:
    """진행 중인 EPL 경기 목록. 정해진 간격이 지나지 않았으면 지난 결과를 그대로 돌려준다."""
    key = _api_key()
    if not key:
        return []
    now = now or time.time()
    with _lock:
        if _state["day"] != date.today():
            _state.update(day=date.today(), calls=0)
        interval = INTERVAL_LIVE if _state["matches"] else INTERVAL_IDLE
        if _state["fetched"] and now - _state["fetched"] < interval:
            return list(_state["matches"])
        if _state["calls"] >= DAILY_BUDGET:
            return list(_state["matches"])
        _state["calls"] += 1
        _state["fetched"] = now
        try:
            if fetch is None:
                resp = requests.get(URL, params={"live": "all"}, headers={"x-apisports-key": key}, timeout=8)
                resp.raise_for_status()
                payload = resp.json()
            else:
                payload = fetch()
            if payload.get("errors"):
                raise RuntimeError(str(payload["errors"]))
            _state["matches"] = parse_live(payload)
            _state["error"] = None
        except Exception as exc:  # 실패해도 앱은 계속 동작
            _state["error"] = str(exc)[:200]
        return list(_state["matches"])


def live_html(matches: list[dict], ko_name=lambda x: x) -> str:
    """진행 중 경기 카드 HTML (한 줄로 이어 붙인다)."""
    if not matches:
        return ""
    rows = []
    for m in matches:
        minute = f"{m['minute']}'" if m.get("minute") and m.get("status") not in ("HT", "BT") else STATUS_SHORT.get(m["status"], "")
        hs = "-" if m["hs"] is None else m["hs"]
        as_ = "-" if m["as"] is None else m["as"]
        rows.append(
            f'<div class="live-row"><span class="live-min">{escape(str(minute), quote=False)}</span>'
            f'<span class="rh">{escape(ko_name(m["home"]))}</span>'
            f'<span class="rs hi">{hs} - {as_}</span>'
            f'<span class="ra">{escape(ko_name(m["away"]))}</span></div>'
        )
    return (
        '<div class="live-box"><div class="live-head"><span class="live-dot"></span>'
        f'<span class="t">LIVE<b>지금 진행 중인 EPL 경기 {len(matches)}개</b></span>'
        '<span class="s">몇 분 간격으로 갱신 · 끝난 경기는 다음 날 DB에 반영</span></div>'
        f'{"".join(rows)}</div>'
    )

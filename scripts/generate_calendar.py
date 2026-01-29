#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Generate an Apple-compatible ICS calendar for major US macro releases (Taipei time).

Included (2026):
- CPI (BLS schedule) - assumed 08:30 ET
- Employment Situation / NFP (BLS schedule) - assumed 08:30 ET
- FOMC statement day (hardcoded 2026 decision days) - assumed 14:00 ET
- GDP (BEA release_dates.json)
- Personal Income and Outlays / PCE (BEA release_dates.json)

Output:
- us-macro-2026-taipei.ics
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup


# -----------------------
# Config
# -----------------------

YEAR = 2026
OUT_FILE = "us-macro-2026-taipei.ics"

TZ_TAIPEI = ZoneInfo("Asia/Taipei")
TZ_NY = ZoneInfo("America/New_York")
TZ_UTC = ZoneInfo("UTC")

ALARMS_MINUTES = (30, 60)
DEFAULT_DURATION_MIN = 15
FOMC_DURATION_MIN = 30

# FOMC decision (statement) days for 2026 (hardcoded for stability)
# Assume statement at 14:00 ET on these days.
FOMC_STATEMENT_DATES_2026 = [
    "2026-01-28",
    "2026-03-18",
    "2026-04-29",
    "2026-06-17",
    "2026-07-29",
    "2026-09-16",
    "2026-10-28",
    "2026-12-09",
]

# Common headers to avoid 403 blocks in GitHub Actions
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}


# -----------------------
# ICS helpers
# -----------------------

def _fold_ics_line(line: str, limit: int = 75) -> str:
    """RFC5545 line folding: CRLF + space."""
    if len(line) <= limit:
        return line
    out: list[str] = []
    while len(line) > limit:
        out.append(line[:limit])
        line = " " + line[limit:]
    out.append(line)
    return "\r\n".join(out)


def _fmt_local(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%S")


def _stable_uid(summary: str, dtstart: datetime) -> str:
    base = f"{summary}|{dtstart.isoformat()}"
    h = hashlib.sha1(base.encode("utf-8")).hexdigest()[:20]
    return f"fin-{h}@zeuscheng.github.io"


def _escape_ics_text(text: str) -> str:
    """Basic escaping for ICS text fields (newlines -> \\n)."""
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")


@dataclass(frozen=True)
class Event:
    summary: str
    start_tp: datetime
    duration_min: int
    description: str
    categories: tuple[str, ...]


def _event_to_ics_lines(ev: Event) -> list[str]:
    dt_end = ev.start_tp + timedelta(minutes=ev.duration_min)
    lines = [
        "BEGIN:VEVENT",
        f"UID:{_stable_uid(ev.summary, ev.start_tp)}",
        f"DTSTAMP:{datetime.now(tz=TZ_UTC).strftime('%Y%m%dT%H%M%SZ')}",
        f"SUMMARY:{ev.summary}",
        f"DTSTART;TZID=Asia/Taipei:{_fmt_local(ev.start_tp)}",
        f"DTEND;TZID=Asia/Taipei:{_fmt_local(dt_end)}",
    ]

    if ev.categories:
        lines.append("CATEGORIES:" + ",".join(ev.categories))

    if ev.description:
        lines.append("DESCRIPTION:" + _escape_ics_text(ev.description))

    for m in ALARMS_MINUTES:
        lines.extend([
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"DESCRIPTION:提醒：{ev.summary}",
            f"TRIGGER:-PT{m}M",
            "END:VALARM",
        ])

    lines.append("END:VEVENT")
    return lines


# -----------------------
# HTTP helpers
# -----------------------

def _get_with_retries(
    url: str,
    headers: dict[str, str],
    timeout: int = 30,
    retries: int = 3,
    backoff_sec: float = 1.2,
) -> requests.Response:
    last_err: Exception | None = None
    for i in range(retries):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as e:
            last_err = e
            time.sleep(backoff_sec * (i + 1))
    raise RuntimeError(f"HTTP request failed after {retries} retries: {url} ; last_err={last_err}")


# -----------------------
# Data sources
# -----------------------

def fetch_bls_cpi_and_nfp(year: int) -> tuple[list[datetime], list[datetime]]:
    """
    BLS schedule page includes dates for CPI & Employment Situation (NFP).
    Assumption:
      - CPI: 08:30 ET
      - Employment Situation: 08:30 ET
    Robust matching because BLS title strings vary.
    """
    url = f"https://www.bls.gov/schedule/{year}/home.htm"
    headers = dict(BROWSER_HEADERS)
    headers["Referer"] = "https://www.bls.gov/"

    resp = _get_with_retries(url, headers=headers, retries=4)
    soup = BeautifulSoup(resp.text, "html.parser")

    rows = soup.select("table tbody tr")
    if not rows:
        raise RuntimeError("BLS schedule table not found; page structure may have changed or blocked.")

    cpi_tp: list[datetime] = []
    nfp_tp: list[datetime] = []

    date_pat = re.compile(r"([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})")

    def norm(s: str) -> str:
        return re.sub(r"\s+", " ", s.strip()).lower()

    def is_cpi(title: str) -> bool:
        t = norm(title)
        # CPI 常見各種寫法：Consumer Price Index / CPI / CPI-U / CPI Summary...
        return ("consumer price index" in t) or (re.search(r"\bcpi\b", t) is not None) or ("cpi-u" in t)

    def is_nfp(title: str) -> bool:
        t = norm(title)
        # 非農常見：Employment Situation / The Employment Situation / Employment Situation Summary...
        return ("employment situation" in t) or ("the employment situation" in t)

    for tr in rows:
        cols = [td.get_text(" ", strip=True) for td in tr.find_all(["th", "td"])]
        if len(cols) < 2:
            continue

        release = cols[0]
        date_str = " ".join(cols[1:])  # 日期欄後面可能還有其他資訊，合併找日期

        m = date_pat.search(date_str)
        if not m:
            continue

        # 08:30 ET
        dt_ny = datetime.strptime(m.group(0), "%B %d, %Y").replace(
            hour=8, minute=30, second=0, tzinfo=TZ_NY
        )
        dt_tp = dt_ny.astimezone(TZ_TAIPEI)

        if is_cpi(release):
            cpi_tp.append(dt_tp)
        if is_nfp(release):
            nfp_tp.append(dt_tp)

    cpi_tp = sorted(set(cpi_tp))
    nfp_tp = sorted(set(nfp_tp))

    if not cpi_tp:
        sample = []
        for tr in rows[:12]:
            tds = tr.find_all(["th", "td"])
            if tds:
                sample.append(norm(tds[0].get_text(" ", strip=True)))
        raise RuntimeError(f"BLS parse failed: CPI list empty. Sample titles: {sample}")

    if not nfp_tp:
        sample = []
        for tr in rows[:12]:
            tds = tr.find_all(["th", "td"])
            if tds:
                sample.append(norm(tds[0].get_text(" ", strip=True)))
        raise RuntimeError(f"BLS parse failed: NFP list empty. Sample titles: {sample}")

    return cpi_tp, nfp_tp


def fetch_bea_gdp_and_pio(year: int) -> tuple[list[datetime], list[datetime]]:
    """
    BEA release_dates.json structure:
    {
      "Gross Domestic Product": {"release_dates": [...]},
      "Personal Income and Outlays": {"release_dates": [...]},
      ...
    }
    """
    url = "https://apps.bea.gov/API/signup/release_dates.json"
    headers = dict(BROWSER_HEADERS)
    headers["Accept"] = "application/json,text/plain,*/*"
    headers["Referer"] = "https://www.bea.gov/"

    resp = _get_with_retries(url, headers=headers, retries=4)
    data = resp.json()

    if not isinstance(data, dict) or not data:
        raise RuntimeError("BEA release_dates.json unexpected empty or non-dict response.")

    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", s.strip()).lower()

    def _find_key(target: str) -> str | None:
        if target in data:
            return target
        t = _norm(target)
        for k in data.keys():
            if _norm(str(k)) == t:
                return str(k)
        for k in data.keys():
            if t in _norm(str(k)):
                return str(k)
        return None

    def _parse_dates(key: str) -> list[datetime]:
        obj = data.get(key, {})
        if not isinstance(obj, dict):
            return []
        raw_dates = obj.get("release_dates", [])
        if not isinstance(raw_dates, list):
            return []
        out: list[datetime] = []
        for s in raw_dates:
            if not isinstance(s, str):
                continue
            try:
                dt = datetime.fromisoformat(s)  # includes offset
            except Exception:
                continue
            if dt.year == year:
                out.append(dt.astimezone(TZ_TAIPEI))
        return sorted(set(out))

    gdp_key = _find_key("Gross Domestic Product")
    pio_key = _find_key("Personal Income and Outlays")

    if not gdp_key or not pio_key:
        raise RuntimeError(f"BEA keys not found. GDP={gdp_key}, PIO={pio_key}")

    gdp_tp = _parse_dates(gdp_key)
    pio_tp = _parse_dates(pio_key)

    if not gdp_tp:
        raise RuntimeError("BEA parse failed: GDP list empty after filtering by year.")
    if not pio_tp:
        raise RuntimeError("BEA parse failed: PIO/PCE list empty after filtering by year.")

    return gdp_tp, pio_tp


def fomc_statement_times_tp(year: int) -> list[datetime]:
    if year != 2026:
        raise RuntimeError("FOMC dates are hard-coded for 2026 only in this script.")
    out: list[datetime] = []
    for d in FOMC_STATEMENT_DATES_2026:
        dt_ny = datetime.fromisoformat(d + "T14:00:00").replace(tzinfo=TZ_NY)
        out.append(dt_ny.astimezone(TZ_TAIPEI))
    return out


# -----------------------
# Build events / calendar
# -----------------------

def build_events() -> list[Event]:
    events: list[Event] = []

    # CPI / NFP from BLS
    cpi_tp, nfp_tp = fetch_bls_cpi_and_nfp(YEAR)

    for dt_tp in cpi_tp:
        events.append(Event(
            summary="美國 CPI 公佈（BLS）",
            start_tp=dt_tp,
            duration_min=DEFAULT_DURATION_MIN,
            description=f"來源：BLS schedule（{YEAR}；08:30 ET，已換算台北時間）",
            categories=("US", "CPI", "BLS"),
        ))

    for dt_tp in nfp_tp:
        events.append(Event(
            summary="美國 非農/就業報告 NFP（BLS Employment Situation）",
            start_tp=dt_tp,
            duration_min=DEFAULT_DURATION_MIN,
            description=f"來源：BLS schedule（{YEAR}；08:30 ET，已換算台北時間）",
            categories=("US", "NFP", "BLS"),
        ))

    # FOMC hardcoded
    for dt_tp in fomc_statement_times_tp(YEAR):
        events.append(Event(
            summary="FOMC 利率決議聲明（Fed）",
            start_tp=dt_tp,
            duration_min=FOMC_DURATION_MIN,
            description=f"來源：Fed FOMC calendar（{YEAR}；假設 14:00 ET 發布，已換算台北時間）",
            categories=("US", "FOMC", "Fed"),
        ))

    # BEA GDP / PCE (PIO)
    gdp_tp, pio_tp = fetch_bea_gdp_and_pio(YEAR)

    for dt_tp in gdp_tp:
        events.append(Event(
            summary="美國 GDP 發布（BEA）",
            start_tp=dt_tp,
            duration_min=DEFAULT_DURATION_MIN,
            description=f"來源：BEA release_dates.json（{YEAR}；原始時間含時區，已換算台北時間）",
            categories=("US", "GDP", "BEA"),
        ))

    for dt_tp in pio_tp:
        events.append(Event(
            summary="美國 PCE/個人所得與支出（BEA）",
            start_tp=dt_tp,
            duration_min=DEFAULT_DURATION_MIN,
            description=f"來源：BEA release_dates.json（{YEAR}；含 PCE；已換算台北時間）",
            categories=("US", "PCE", "BEA"),
        ))

    events.sort(key=lambda e: e.start_tp)
    return events


def build_ics(events: list[Event]) -> str:
    header = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ZeusCheng//US Macro Calendar 2026//ZH-TW",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{YEAR} 重大美國金融數據（Taipei）",
        "X-WR-TIMEZONE:Asia/Taipei",
    ]

    lines = list(header)
    for ev in events:
        lines.extend(_event_to_ics_lines(ev))

    lines.append("END:VCALENDAR")

    return "\r\n".join(_fold_ics_line(l) for l in lines) + "\r\n"


def main():
    events = build_events()
    ics = build_ics(events)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(ics)
    print(f"✅ Generated: {OUT_FILE} ({len(events)} events)")


if __name__ == "__main__":
    main()

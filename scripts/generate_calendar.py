#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Generate US major macro calendar (.ics) for 2026 in Asia/Taipei timezone.

Sources:
- BLS release schedule (CPI, Employment Situation): https://www.bls.gov/schedule/2026/home.htm
- BEA release dates JSON (GDP, Personal Income and Outlays): https://apps.bea.gov/API/signup/release_dates.json
- FOMC dates: hardcoded 2026 decision days (safer than parsing the webpage)

Output:
- us-macro-2026-taipei.ics
"""

import hashlib
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

YEAR = 2026
OUT_FILE = "us-macro-2026-taipei.ics"

TZ_TAIPEI = ZoneInfo("Asia/Taipei")
TZ_NY = ZoneInfo("America/New_York")
TZ_UTC = ZoneInfo("UTC")


# ---------- iCalendar helpers ----------

def _fold_ics_line(line: str, limit: int = 75) -> str:
    """
    RFC5545 line folding: lines longer than 75 octets should be folded with CRLF + single space.
    We approximate by character count (works well for our content).
    """
    if len(line) <= limit:
        return line
    out = []
    while len(line) > limit:
        out.append(line[:limit])
        line = " " + line[limit:]
    out.append(line)
    return "\r\n".join(out)

def _dt_local(dt: datetime) -> str:
    # local time with seconds, no 'Z'
    return dt.strftime("%Y%m%dT%H%M%S")

def _dtstamp_utc() -> str:
    return datetime.now(tz=TZ_UTC).strftime("%Y%m%dT%H%M%SZ")

def _stable_uid(summary: str, dtstart: datetime) -> str:
    """
    Stable UID so updates don't create duplicates.
    UID must be globally unique; use hash of summary+datetime.
    """
    base = f"{summary}|{dtstart.isoformat()}"
    h = hashlib.sha1(base.encode("utf-8")).hexdigest()[:20]
    return f"fin-{h}@zeuscheng.github.io"

def _escape_desc(text: str) -> str:
    """
    iCalendar escaping:
    - Newlines as \n
    """
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")

def add_event(
    lines: list[str],
    summary: str,
    start_tp: datetime,
    duration_minutes: int = 15,
    description: str = "",
    categories: list[str] | None = None,
    alarms: tuple[int, ...] = (30, 60),
):
    end_tp = start_tp + timedelta(minutes=duration_minutes)

    lines.extend([
        "BEGIN:VEVENT",
        f"UID:{_stable_uid(summary, start_tp)}",
        f"DTSTAMP:{_dtstamp_utc()}",
        f"SUMMARY:{summary}",
        f"DTSTART;TZID=Asia/Taipei:{_dt_local(start_tp)}",
        f"DTEND;TZID=Asia/Taipei:{_dt_local(end_tp)}",
    ])

    if categories:
        lines.append("CATEGORIES:" + ",".join(categories))

    if description:
        lines.append(f"DESCRIPTION:{_escape_desc(description)}")

    for m in alarms:
        lines.extend([
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"DESCRIPTION:提醒：{summary}",
            f"TRIGGER:-PT{m}M",
            "END:VALARM",
        ])

    lines.append("END:VEVENT")


# ---------- Data fetchers ----------

def fetch_bls_cpi_and_nfp(year: int) -> tuple[list[datetime], list[datetime]]:
    """
    Parse BLS schedule page for a given year.
    - CPI (Consumer Price Index)
    - Employment Situation (NFP)
    Default release time assumed 08:30 ET; convert to Taipei.
    """
def fetch_bls_cpi_and_nfp(year: int) -> tuple[list[datetime], list[datetime]]:
    """
    Parse BLS schedule page for a given year.
    - CPI (Consumer Price Index)
    - Employment Situation (NFP)
    Default release time assumed 08:30 ET; convert to Taipei.
    """
    urls = [
        f"https://www.bls.gov/schedule/{year}/home.htm",
        f"https://www.bls.gov/schedule/{year}/home.htm",  # 備援可留同一個（或你想改成 http 也行）
    ]

    headers = {
        # BLS 會擋 GitHub Actions 的預設 UA，偽裝成一般瀏覽器就會放行
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.bls.gov/",
        "Connection": "keep-alive",
    }

    last_err = None
    for url in urls:
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            html = resp.text
            break
        except Exception as e:
            last_err = e
            html = None

    if html is None:
        raise RuntimeError(f"BLS schedule fetch failed (likely blocked). Last error: {last_err}")

    soup = BeautifulSoup(html, "html.parser")

    cpi_tp: list[datetime] = []
    nfp_tp: list[datetime] = []

    rows = soup.select("table tbody tr")
    if not rows:
        raise RuntimeError("BLS schedule table not found; page structure may have changed.")

    date_pat = re.compile(r"([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})")

    for tr in rows:
        cols = [td.get_text(" ", strip=True) for td in tr.find_all(["th", "td"])]
        if len(cols) < 2:
            continue
        release, date_str = cols[0], cols[1]

        m = date_pat.search(date_str)
        if not m:
            continue

        dt_ny = datetime.strptime(m.group(0), "%B %d, %Y").replace(
            hour=8, minute=30, second=0, tzinfo=TZ_NY
        )
        dt_tp = dt_ny.astimezone(TZ_TAIPEI)

        if "Consumer Price Index" in release:
            cpi_tp.append(dt_tp)

        if "Employment Situation" in release:
            nfp_tp.append(dt_tp)

    return sorted(set(cpi_tp)), sorted(set(nfp_tp))

    soup = BeautifulSoup(resp.text, "html.parser")

    cpi_tp: list[datetime] = []
    nfp_tp: list[datetime] = []

    # Typical structure: table with Release / Date columns
    rows = soup.select("table tbody tr")
    if not rows:
        # fallback: sometimes schedule uses different markup; fail loudly for visibility in Actions logs
        raise RuntimeError("BLS schedule table not found; page structure may have changed.")

    date_pat = re.compile(r"([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})")

    for tr in rows:
        cols = [td.get_text(" ", strip=True) for td in tr.find_all(["th", "td"])]
        if len(cols) < 2:
            continue
        release, date_str = cols[0], cols[1]

        m = date_pat.search(date_str)
        if not m:
            continue

        # Build NY time 08:30 ET
        dt_ny = datetime.strptime(m.group(0), "%B %d, %Y").replace(
            hour=8, minute=30, second=0, tzinfo=TZ_NY
        )
        dt_tp = dt_ny.astimezone(TZ_TAIPEI)

        if "Consumer Price Index" in release:
            cpi_tp.append(dt_tp)

        if "Employment Situation" in release:
            nfp_tp.append(dt_tp)

    return sorted(set(cpi_tp)), sorted(set(nfp_tp))

def fetch_bea_gdp_and_pio(year: int) -> tuple[list[datetime], list[datetime]]:
    """
    Parse BEA release dates JSON for:
    - Gross Domestic Product
    - Personal Income and Outlays (includes PCE)
    BEA JSON timestamps are ISO w/ UTC offset; convert to Taipei.
    """
    url = "https://apps.bea.gov/API/signup/release_dates.json"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()

    data = resp.json()
    items = data.get("release_dates", [])
    if not items:
        raise RuntimeError("BEA release_dates.json returned no items.")

    gdp_tp: list[datetime] = []
    pio_tp: list[datetime] = []

    for item in items:
        name = item.get("releaseName", "") or item.get("name", "")
        dt_str = item.get("date")
        if not dt_str:
            continue

        try:
            dt_utc = datetime.fromisoformat(dt_str)
        except Exception:
            continue

        if dt_utc.year != year:
            continue

        dt_tp = dt_utc.astimezone(TZ_TAIPEI)

        if "Gross Domestic Product" in name:
            gdp_tp.append(dt_tp)

        if "Personal Income and Outlays" in name:
            pio_tp.append(dt_tp)

    return sorted(set(gdp_tp)), sorted(set(pio_tp))

def fomc_decision_days_2026() -> list[datetime]:
    """
    Hardcode FOMC decision (statement) dates for 2026 to avoid parsing issues.
    Assume statement time 14:00 ET, convert to Taipei.
    """
    dates = [
        "2026-01-28",
        "2026-03-18",
        "2026-04-29",
        "2026-06-17",
        "2026-07-29",
        "2026-09-16",
        "2026-10-28",
        "2026-12-09",
    ]
    out = []
    for d in dates:
        dt_ny = datetime.fromisoformat(d + "T14:00:00").replace(tzinfo=TZ_NY)
        out.append(dt_ny.astimezone(TZ_TAIPEI))
    return out


# ---------- Build calendar ----------

def build_ics_2026() -> str:
    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ZeusCheng//US Macro Calendar 2026//ZH-TW",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:2026 重大美國金融數據（Taipei）",
        "X-WR-TIMEZONE:Asia/Taipei",
    ]

    # BLS
    cpi_tp, nfp_tp = fetch_bls_cpi_and_nfp(YEAR)
    for dt_tp in cpi_tp:
        add_event(
            lines,
            "美國 CPI 公佈（BLS）",
            dt_tp,
            duration_minutes=15,
            description=f"來源：BLS schedule（{YEAR}；08:30 ET 已換算台北時間）",
            categories=["US", "CPI", "BLS"],
        )

    for dt_tp in nfp_tp:
        add_event(
            lines,
            "美國 非農/就業報告 NFP（BLS Employment Situation）",
            dt_tp,
            duration_minutes=15,
            description=f"來源：BLS schedule（{YEAR}；08:30 ET 已換算台北時間）",
            categories=["US", "NFP", "BLS"],
        )

    # FOMC
    for dt_tp in fomc_decision_days_2026():
        add_event(
            lines,
            "FOMC 利率決議聲明（Fed）",
            dt_tp,
            duration_minutes=30,
            description=f"來源：Fed FOMC calendar（{YEAR}；假設 14:00 ET 發布，已換算台北時間）",
            categories=["US", "FOMC", "Fed"],
        )

    # BEA
    gdp_tp, pio_tp = fetch_bea_gdp_and_pio(YEAR)
    for dt_tp in gdp_tp:
        add_event(
            lines,
            "美國 GDP 發布（BEA）",
            dt_tp,
            duration_minutes=15,
            description=f"來源：BEA release_dates.json（{YEAR}；UTC 時間已換算台北時間）",
            categories=["US", "GDP", "BEA"],
        )

    for dt_tp in pio_tp:
        add_event(
            lines,
            "美國 PCE/個人所得與支出（BEA）",
            dt_tp,
            duration_minutes=15,
            description=f"來源：BEA release_dates.json（{YEAR}；含 PCE；UTC 時間已換算台北時間）",
            categories=["US", "PCE", "BEA"],
        )

    lines.append("END:VCALENDAR")

    # Fold lines and ensure CRLF
    return "\r\n".join(_fold_ics_line(l) for l in lines) + "\r\n"


def main():
    ics_text = build_ics_2026()
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(ics_text)
    print(f"✅ Generated {OUT_FILE}")


if __name__ == "__main__":
    main()

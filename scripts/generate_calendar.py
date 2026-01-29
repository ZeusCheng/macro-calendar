#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import hashlib
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

TZ_TAIPEI = ZoneInfo("Asia/Taipei")
TZ_NY = ZoneInfo("America/New_York")

YEAR = 2026
OUT_FILE = "us-macro-2026-taipei.ics.ics"  # 這個要跟你 repo 目前訂閱的檔名一致

def fold_ics_line(line: str, limit: int = 75) -> str:
    # RFC5545 line folding: CRLF + space
    if len(line) <= limit:
        return line
    out = []
    while len(line) > limit:
        out.append(line[:limit])
        line = " " + line[limit:]
    out.append(line)
    return "\r\n".join(out)

def dt_local(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%S")

def stable_uid(summary: str, dtstart: datetime) -> str:
    # 固定 UID，避免每次更新變成「新增一批重複事件」
    base = f"{summary}|{dtstart.isoformat()}"
    h = hashlib.sha1(base.encode("utf-8")).hexdigest()[:20]
    return f"fin-{h}@zeuscheng.github.io"

def add_event(lines, summary, start_tp, minutes, description, categories=None, alarms=(30, 60)):
    end_tp = start_tp + timedelta(minutes=minutes)
    lines.extend([
        "BEGIN:VEVENT",
        f"UID:{stable_uid(summary, start_tp)}",
        f"DTSTAMP:{datetime.now(tz=ZoneInfo('UTC')).strftime('%Y%m%dT%H%M%SZ')}",
        f"SUMMARY:{summary}",
        f"DTSTART;TZID=Asia/Taipei:{dt_local(start_tp)}",
        f"DTEND;TZID=Asia/Taipei:{dt_local(end_tp)}",
    ])
    if categories:
        lines.append("CATEGORIES:" + ",".join(categories))

    if description:
        desc = description.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")
        lines.append(f"DESCRIPTION:{desc}")

    for m in alarms:
        lines.extend([
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"DESCRIPTION:提醒：{summary}",
            f"TRIGGER:-PT{m}M",
            "END:VALARM",
        ])

    lines.append("END:VEVENT")

def parse_bls_schedule(year: int):
    """
    BLS schedule：抓 CPI / Employment Situation 日期（通常 08:30 ET）
    https://www.bls.gov/schedule/{year}/home.htm
    """
    url = f"https://www.bls.gov/schedule/{year}/home.htm"
    html = requests.get(url, timeout=30).text
    soup = BeautifulSoup(html, "html.parser")

    cpi = []
    nfp = []

    rows = soup.select("table tbody tr")
    for tr in rows:
        tds = [td.get_text(" ", strip=True) for td in tr.find_all(["th", "td"])]
        if len(tds) < 2:
            continue
        release = tds[0]
        date_str = tds[1]

        m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})", date_str)
        if not m:
            continue

        dt_ny = datetime.strptime(m.group(0), "%B %d, %Y").replace(
            hour=8, minute=30, second=0, tzinfo=TZ_NY
        )
        dt_tp = dt_ny.astimezone(TZ_TAIPEI)

        if "Consumer Price Index" in release:
            cpi.append(dt_tp)
        if "Employment Situation" in release:
            nfp.append(dt_tp)

    return sorted(set(cpi)), sorted(set(nfp))

def parse_fomc_2026():
    """
    2026 會議日（決議日）固定寫死，避免抓網頁解析失敗。
    預設 14:00 ET 發布（已換算台北時間）
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

def parse_bea_release_dates(year: int):
    """
    BEA release dates JSON
    https://apps.bea.gov/API/signup/release_dates.json
    抓 GDP + Personal Income and Outlays（含 PCE）
    """
    url = "https://apps.bea.gov/API/signup/release_dates.json"
    data = requests.get(url, timeout=30).json()

    gdp = []
    pio = []

    for item in data.get("release_dates", []):
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
            gdp.append(dt_tp)
        if "Personal Income and Outlays" in name:
            pio.append(dt_tp)

    return sorted(set(gdp)), sorted(set(pio))

def build_ics():
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ZeusCheng//US Macro Calendar 2026//ZH-TW",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:2026 重大美國金融數據（Taipei）",
        "X-WR-TIMEZONE:Asia/Taipei",
    ]

    # BLS CPI / NFP
    cpi, nfp = parse_bls_schedule(YEAR)
    for dt_tp in cpi:
        add_event(
            lines,
            "美國 CPI 公佈（BLS）",
            dt_tp, 15,
            f"來源：BLS schedule（{YEAR}；08:30 ET，已換算台北時間）",
            categories=["US","CPI","BLS"],
        )
    for dt_tp in nfp:
        add_event(
            lines,
            "美國 非農/就業報告 NFP（BLS Employment Situation）",
            dt_tp, 15,
            f"來源：BLS schedule（{YEAR}；08:30 ET，已換算台北時間）",
            categories=["US","NFP","BLS"],
        )

    # FOMC
    for dt_tp in parse_fomc_2026():
        add_event(
            lines,
            "FOMC 利率決議聲明（Fed）",
            dt_tp, 30,
            f"來源：Fed FOMC calendar（{YEAR}；假設 14:00 ET 發布，已換算台北時間）",
            categories=["US","FOMC","Fed"],
        )

    # BEA GDP / PCE
    gdp, pio = parse_bea_release_dates(YEAR)
    for dt_tp in gdp:
        add_event(
            lines,
            "美國 GDP 發布（BEA）",
            dt_tp, 15,
            f"來源：BEA release_dates.json（{YEAR}；UTC 時間已換算台北時間）",
            categories=["US","GDP","BEA"],
        )
    for dt_tp in pio:
        add_event(
            lines,
            "美國 PCE/個人所得與支出（BEA）",
            dt_tp, 15,
            f"來源：BEA release_dates.json（{YEAR}；UTC 時間已換算台北時間）",
            categories=["US","PCE","BEA"],
        )

    lines.append("END:VCALENDAR")
    return "\r\n".join(fold_ics_line(l) for l in lines) + "\r\n"

def main():
    ics = build_ics()
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(ics)
    print(f"✅ Generated {OUT_FILE}")

if __name__ == "__main__":
    main()

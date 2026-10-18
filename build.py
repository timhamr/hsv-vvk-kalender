#!/usr/bin/env python3
"""HSV-Kalender: Spiele und Mitglieder-Vorverkaufsstarts von hsv.de/tickets/ticketinfos als iCalendar.

Liest die Termintabelle („Termine Männer“) und schreibt docs/hsv.ics:
  - jedes Heim- und Auswärtsspiel (Anstoß, bzw. ganztägig über den Zeitraum,
    solange der Spieltag noch nicht terminiert ist)
  - jeden angekündigten Mitglieder-Vorverkauf mit Erinnerung 30 Minuten vorher
    (dann öffnet der HSV den Pre-Warteraum im Ticketshop)

Nur Standardbibliothek, damit GitHub Actions ohne Installation auskommt.
"""
import html
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

URL = "https://www.hsv.de/tickets/ticketinfos"
BASE = "https://www.hsv.de"
BERLIN = ZoneInfo("Europe/Berlin")
OUT = Path(__file__).parent / "docs" / "hsv.ics"
MATCH_DURATION = timedelta(hours=2)
VVK_DURATION = timedelta(minutes=30)


class TableParser(HTMLParser):
    """Sammelt alle Tabellenzeilen als Liste von Zellen (Text, Bild-alt, Links)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr":
            self.row = []
        elif tag == "td" and self.row is not None:
            self.cell = {"text": [], "alts": [], "links": []}
        elif self.cell is not None:
            if tag == "img" and a.get("alt"):
                self.cell["alts"].append(a["alt"])
            elif tag == "a" and a.get("href"):
                self.cell["links"].append(a["href"])
            elif tag in ("br", "p"):
                self.cell["text"].append("\n")

    def handle_endtag(self, tag):
        if tag == "td" and self.cell is not None:
            text = re.sub(r"[ \t\xa0]+", " ", "".join(self.cell["text"]))
            self.cell["text"] = "\n".join(l.strip() for l in text.splitlines() if l.strip())
            self.row.append(self.cell)
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell["text"].append(data)


def parse_kickoff(text):
    """'So., 22.11.26, 17.30 Uhr' → datetime; '04.12. - 06.12.26' → (date, date)."""
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4}),?\s*(\d{1,2})[.:](\d{2})\s*Uhr", text)
    if m:
        d, mo, y, h, mi = map(int, m.groups())
        return datetime(2000 + y if y < 100 else y, mo, d, h, mi, tzinfo=BERLIN)
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})?\s*-\s*(\d{1,2})\.(\d{1,2})\.(\d{2,4})", text.replace("\n", " "))
    if m:
        d1, mo1, y1, d2, mo2, y2 = m.groups()
        y2 = int(y2) + (2000 if int(y2) < 100 else 0)
        end = date(y2, int(mo2), int(d2))
        y1 = int(y1) + (2000 if int(y1) < 100 else 0) if y1 else (y2 if int(mo1) <= int(mo2) else y2 - 1)
        return (date(y1, int(mo1), int(d1)), end)
    return None


def parse_presale(text, label, match_day):
    """Startzeit eines Vorverkaufs, z. B. 'Mitgl.-VVK: 20.10. ab 10 Uhr' → datetime.

    Das Jahr fehlt auf der Seite; der Vorverkauf liegt vor dem Spiel, also das
    letzte passende Datum bis zum Spieltag."""
    m = re.search(label + r"\s*:?\s*\n?\s*(\d{1,2})\.(\d{1,2})\.(\d{2,4})?\s*ab\s*(\d{1,2})(?:[.:](\d{2}))?\s*Uhr", text)
    if not m:
        return None
    d, mo, y, h, mi = m.groups()
    year = int(y) + (2000 if int(y) < 100 else 0) if y else match_day.year
    start = datetime(year, int(mo), int(d), int(h), int(mi or 0), tzinfo=BERLIN)
    if not y and start.date() > match_day:
        start = start.replace(year=year - 1)
    return start


def presale_status(text, label):
    """Kurzer Status eines Vorverkaufs für die Beschreibung, z. B. 'läuft' oder '20.10. ab 10 Uhr'."""
    m = re.search(label + r"\s*:?\s*\n?\s*([^\n]+)", text)
    if not m:
        return None
    value = m.group(1).strip()
    return "läuft (Hier buchen)" if value.lower().startswith("hier buchen") else value


def season(day):
    return f"{day.year}{day.year + 1}" if day.month >= 7 else f"{day.year - 1}{day.year}"


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def competition(alts):
    for alt in alts:
        name = re.sub(r"\s*(Logo|\d+x\d+)\b", "", alt, flags=re.I).strip()
        if name:
            return name
    return None


def esc(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line):
    """RFC 5545: Zeilen nach 75 Oktetten umbrechen."""
    out, raw = [], line.encode()
    while len(raw) > 75:
        cut = 75 if not out else 74
        while (raw[cut] & 0xC0) == 0x80:  # nicht mitten in einem UTF-8-Zeichen trennen
            cut -= 1
        out.append(raw[:cut].decode())
        raw = raw[cut:]
    out.append(raw.decode())
    return "\r\n ".join(out)


def utc(dt):
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build(page):
    p = TableParser()
    p.feed(page)
    events = []
    for row in p.rows:
        if len(row) < 6:
            continue
        kickoff = parse_kickoff(row[1]["text"])
        home, guest = row[2]["text"].replace("\n", " "), row[4]["text"].replace("\n", " ")
        if kickoff is None or "HSV" not in (home, guest):
            continue
        vvk = row[5]["text"]
        link = next((l for c in row[6:] for l in c["links"]), None)
        link = BASE + link if link and link.startswith("/") else (link or URL)
        comp = competition(row[0]["alts"])
        is_home = home == "HSV"
        title = f"{home} – {guest}"
        day = kickoff.date() if isinstance(kickoff, datetime) else kickoff[1]
        uid = f"{slug(home)}-{slug(guest)}-{season(day)}"

        info = [f"Wettbewerb: {comp}"] if comp else []
        for label, name in (("Mitgl.-VVK", "Mitglieder-VVK"), ("Freier[- ]VVK", "Freier VVK")):
            status = presale_status(vvk, label)
            if status:
                info.append(f"{name}: {status}")
        for flag in ("Kein freier VVK", "Ausverkauft", "Infos folgen"):
            if flag in vvk:
                info.append(flag)
        info.append(f"Ticketinfos: {link}")

        ev = {"uid": f"spiel-{uid}@hsv-vvk-kalender", "summary": f"⚽ {title}",
              "location": "Volksparkstadion, Hamburg" if is_home else f"Auswärts bei {home}",
              "description": "\n".join(info), "url": link}
        if isinstance(kickoff, datetime):
            ev.update(start=kickoff, end=kickoff + MATCH_DURATION)
        else:
            ev.update(allday=(kickoff[0], kickoff[1] + timedelta(days=1)),
                      summary=f"⚽ {title} (Termin offen)")
        events.append(ev)

        start = parse_presale(vvk, r"Mitgl\.-VVK", day)
        if start:
            events.append({
                "uid": f"vvk-mitglieder-{uid}@hsv-vvk-kalender",
                "summary": f"🎟️ Mitglieder-VVK: {title}",
                "start": start, "end": start + VVK_DURATION,
                "description": f"Mitglieder-Vorverkauf startet um {start:%H:%M} Uhr.\n"
                               f"30 Minuten vorher öffnet der Pre-Warteraum im Ticketshop.\n"
                               f"Spiel: {title}\nTicketinfos: {link}",
                "url": link, "alarm": timedelta(minutes=30)})
    return events


def ics(events):
    stamp = utc(datetime.now(timezone.utc))
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//timhamr//hsv-vvk-kalender//DE",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-CALNAME:HSV Spiele & Vorverkauf",
             "X-WR-TIMEZONE:Europe/Berlin", "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
             "X-PUBLISHED-TTL:PT6H"]
    for ev in events:
        lines += ["BEGIN:VEVENT", f"UID:{ev['uid']}", f"DTSTAMP:{stamp}"]
        if "allday" in ev:
            lines += [f"DTSTART;VALUE=DATE:{ev['allday'][0]:%Y%m%d}",
                      f"DTEND;VALUE=DATE:{ev['allday'][1]:%Y%m%d}", "TRANSP:TRANSPARENT"]
        else:
            lines += [f"DTSTART:{utc(ev['start'])}", f"DTEND:{utc(ev['end'])}"]
        lines += [f"SUMMARY:{esc(ev['summary'])}", f"DESCRIPTION:{esc(ev['description'])}",
                  f"URL:{ev['url']}"]
        if ev.get("location"):
            lines.append(f"LOCATION:{esc(ev['location'])}")
        if ev.get("alarm"):
            mins = int(ev["alarm"].total_seconds() // 60)
            lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{esc(ev['summary'])}",
                      f"TRIGGER:-PT{mins}M", "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in lines) + "\r\n"


def main():
    if len(sys.argv) > 1:
        page = Path(sys.argv[1]).read_text(encoding="utf-8")
    else:
        req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 (hsv-vvk-kalender; +https://github.com/timhamr/hsv-vvk-kalender)"})
        page = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
    events = build(page)
    if not any(e["uid"].startswith("spiel-") for e in events):
        sys.exit("Keine Spiele gefunden – hat sich die HSV-Seite geändert? Kalender bleibt unverändert.")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(ics(events), encoding="utf-8", newline="")
    games = sum(e["uid"].startswith("spiel-") for e in events)
    print(f"{games} Spiele, {len(events) - games} Mitglieder-VVK-Termine → {OUT}")
    for e in events:
        when = e.get("start") or e["allday"][0]
        print(f"  {when:%d.%m.%Y %H:%M}  {e['summary']}" if isinstance(when, datetime)
              else f"  {when:%d.%m.%Y}        {e['summary']}")


if __name__ == "__main__":
    main()

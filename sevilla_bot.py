import os
import json
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# ===================== POSTAVKE =====================
TEAMS = [
    {
        "competition": "PD",        # LaLiga
        "match_name": "Sevilla",    # kako se klub zove u podacima
        "display": "Seville",       # kako se zove u poruci
        "stream": "https://www.youtube.com/@SevillaFC/streams",
    },
    {
        "competition": "FL1",       # Ligue 1
        "match_name": "Marseille",
        "display": "Marseille",
        "stream": "https://www.youtube.com/@om_officiel/streams",
    },
]
TIMEZONE = "Europe/Zagreb"   # u kojoj se zoni ispisuje hh:mm
MINUTES_BEFORE = 60
# ====================================================

API_KEY = os.environ["FOOTBALL_API_KEY"]
WEBHOOK = os.environ["SLACK_WEBHOOK_URL"]
SENT_FILE = "sent.json"


def send_slack(text):
    data = json.dumps({"text": text}).encode()
    req = urllib.request.Request(WEBHOOK, data=data, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req)


def build_message(team, opponent, start, is_home):
    hhmm = start.astimezone(ZoneInfo(TIMEZONE)).strftime("%H:%M")
    link = f"<{team['stream']}|live show stream>"
    if is_home:
        return (f"{team['display']} vs {opponent} match starts today at {hhmm}! - "
                f"Please post {link} - since it's a home game, post it as a KEY HL")
    return (f"{opponent} vs {team['display']} match starts today at {hhmm}! - "
            f"Please post {link} - since it's an away game, post it as a REGULAR HL")


def team_name(t):
    return t.get("shortName") or t.get("name") or "?"


# --- Test način: pošalje primjer obje poruke ---
if os.environ.get("TEST") == "true":
    fake_start = datetime.now(timezone.utc) + timedelta(hours=1)
    send_slack("✅ Test (domaća): " + build_message(TEAMS[0], "Test FC", fake_start, True))
    send_slack("✅ Test (gostujuća): " + build_message(TEAMS[1], "Test FC", fake_start, False))
    raise SystemExit

# --- Već poslane obavijesti (da nikad ne stigne duplo) ---
try:
    with open(SENT_FILE) as f:
        sent = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    sent = []

now = datetime.now(timezone.utc)
date_from = now.date().isoformat()
date_to = (now + timedelta(days=1)).date().isoformat()

due = []
for team in TEAMS:
    url = (f"https://api.football-data.org/v4/competitions/{team['competition']}/matches"
           f"?dateFrom={date_from}&dateTo={date_to}")
    req = urllib.request.Request(url, headers={"X-Auth-Token": API_KEY})
    with urllib.request.urlopen(req) as r:
        matches = json.load(r)["matches"]

    for m in matches:
        if m["id"] in sent or m["status"] not in ("SCHEDULED", "TIMED"):
            continue
        home, away = m["homeTeam"], m["awayTeam"]
        is_home = team["match_name"] in (home.get("name") or "")
        is_away = team["match_name"] in (away.get("name") or "")
        if not (is_home or is_away):
            continue

        start = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))
        minutes = (start - now).total_seconds() / 60
        # Skripta se pokreće svakih 15 min: uhvati utakmice za 60-75 min,
        # pa pričeka da bude točno 60 min do početka.
        if MINUTES_BEFORE < minutes <= MINUTES_BEFORE + 15:
            opponent = team_name(away if is_home else home)
            due.append((start, m["id"], build_message(team, opponent, start, is_home)))

for start, match_id, text in sorted(due):
    wait = (start - timedelta(minutes=MINUTES_BEFORE) - datetime.now(timezone.utc)).total_seconds()
    if wait > 0:
        time.sleep(wait)
    send_slack(text)
    sent.append(match_id)

with open(SENT_FILE, "w") as f:
    json.dump(sent[-100:], f)

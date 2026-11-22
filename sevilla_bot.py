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
MINUTES_BEFORE = 60          # obavijest stiže 60 min prije početka
LATEST_MINUTES_BEFORE = 30   # ako kasni, najkasnije 30 min prije, nikad poslije
RUN_MINUTES = 340            # koliko jedna "smjena" bota traje prije nego preda sljedećoj
CHECK_EVERY_SECONDS = 300    # koliko često provjerava raspored
# ====================================================

API_KEY = os.environ["FOOTBALL_API_KEY"]
WEBHOOK = os.environ["SLACK_WEBHOOK_URL"]
SENT_FILE = "sent.json"


def now_utc():
    return datetime.now(timezone.utc)


def send_slack(text):
    data = json.dumps({"text": text}).encode()
    req = urllib.request.Request(WEBHOOK, data=data, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=30)


def build_message(team, opponent, start, is_home):
    hhmm = start.astimezone(ZoneInfo(TIMEZONE)).strftime("%H:%M %Z")
    link = f"<{team['stream']}|live show stream>"
    if is_home:
        return (f"{team['display']} vs {opponent} match starts today at {hhmm}! - "
                f"Please post {link} - since it's a home game, post it as a KEY HL")
    return (f"{opponent} vs {team['display']} match starts today at {hhmm}! - "
            f"Please post {link} - since it's an away game, post it as a REGULAR HL")


def team_name(t):
    return t.get("shortName") or t.get("name") or "?"


def fetch_matches():
    """Vrati listu (match_id, start, poruka) za Sevillu i Marseille u sljedeća 2 dana."""
    found = []
    now = now_utc()
    date_from = now.date().isoformat()
    date_to = (now + timedelta(days=2)).date().isoformat()
    for team in TEAMS:
        url = (f"https://api.football-data.org/v4/competitions/{team['competition']}/matches"
               f"?dateFrom={date_from}&dateTo={date_to}")
        req = urllib.request.Request(url, headers={"X-Auth-Token": API_KEY})
        with urllib.request.urlopen(req, timeout=30) as r:
            matches = json.load(r)["matches"]
        for m in matches:
            if m["status"] not in ("SCHEDULED", "TIMED"):
                continue
            home, away = m["homeTeam"], m["awayTeam"]
            is_home = team["match_name"] in (home.get("name") or "")
            is_away = team["match_name"] in (away.get("name") or "")
            if not (is_home or is_away):
                continue
            start = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))
            opponent = team_name(away if is_home else home)
            found.append((m["id"], start, build_message(team, opponent, start, is_home)))
    return found


def save_sent(sent):
    with open(SENT_FILE, "w") as f:
        json.dump(sent[-200:], f)


# --- Test način: pošalje primjer obje poruke ---
if os.environ.get("TEST") == "true":
    fake_start = now_utc() + timedelta(hours=1)
    send_slack("✅ Test (domaća): " + build_message(TEAMS[0], "Test FC", fake_start, True))
    send_slack("✅ Test (gostujuća): " + build_message(TEAMS[1], "Test FC", fake_start, False))
    raise SystemExit

try:
    with open(SENT_FILE) as f:
        sent = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    sent = []
save_sent(sent)

# Bot radi neprekidno ~5,5 sati, svakih 5 minuta provjeri raspored i pošalje
# obavijest točno 60 min prije početka. Na kraju preda posao sljedećoj "smjeni".
end_time = now_utc() + timedelta(minutes=RUN_MINUTES)
matches = []
while now_utc() < end_time:
    try:
        matches = fetch_matches()
        for match_id, start, text in matches:
            if match_id not in sent:
                print(f"Vidim: {text.split(' - ')[0]} (početak {start.isoformat()})")
    except Exception as e:
        print("Greška pri dohvaćanju rasporeda, pokušat ću ponovno:", e)

    next_wake = now_utc() + timedelta(seconds=CHECK_EVERY_SECONDS)
    for match_id, start, text in sorted(matches, key=lambda x: x[1]):
        if match_id in sent:
            continue
        send_at = start - timedelta(minutes=MINUTES_BEFORE)
        latest = start - timedelta(minutes=LATEST_MINUTES_BEFORE)
        n = now_utc()
        if send_at <= n <= latest:
            try:
                send_slack(text)
                sent.append(match_id)
                save_sent(sent)
                print("Poslano:", text)
            except Exception as e:
                print("Greška pri slanju u Slack:", e)
        elif n < send_at < next_wake:
            next_wake = send_at  # probudi se točno kad treba poslati

    sleep_for = (min(next_wake, end_time) - now_utc()).total_seconds()
    if sleep_for > 0:
        time.sleep(sleep_for)

print("Smjena gotova, predajem sljedećoj.")

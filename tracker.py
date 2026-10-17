"""Fare tracker SYD<->SGN, nonstop Vietjet and Jetstar, 12 and 15 day trips.
Every run (hourly):
  1. SCAN  - free fast-flights scan of every date pair, to see which dates have nonstop Vietjet/Jetstar flights on sale.
  2. CHECK - once a day, SerpApi (Google, Australian prices) confirms the real price of up to 7 of those date pairs.
Saves data/latest.json (the dashboard reads it), data/prices.csv (price history) and emails you through GitHub issues."""
import csv, json, os, random, re, threading, time, urllib.parse, urllib.request
from datetime import date, datetime, timedelta, timezone

ORIGIN, DEST = "SYD", "SGN"
FIRST, LAST = date(2027, 8, 1), date(2027, 11, 15)
TRIP_DAYS = [12, 15]
AIRLINES = ("vietjet", "jetstar")
ALERT = 400        # A$ - a confirmed trip newly at or under this gets its own urgent email
CAP = 500          # A$ - confirmed trips at or under this count as deals
DAILY_CHECKS = 7   # SerpApi searches per day (about 215 a month, inside the free 250)
HIST = "data/prices.csv"
LATEST = "data/latest.json"
FIELDS = ["checked", "depart", "return", "days", "price", "airline"]
USER = "danny1389-wq"


class HardError(Exception):
    pass


def run_with_timeout(fn, *args, seconds=60):
    box = {}

    def work():
        try:
            box["value"] = fn(*args)
        except Exception as e:
            box["error"] = e

    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        raise TimeoutError(f"took longer than {seconds} seconds")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def post_issue(title, body):
    token, repo = os.environ.get("GH_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print("No GitHub token here, so no email was sent.", flush=True)
        return
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues",
        data=json.dumps({"title": title, "body": body}).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json", "User-Agent": "fare-tracker"})
    try:
        urllib.request.urlopen(req, timeout=30).read()
        print(f"Email sent: {title}", flush=True)
    except Exception as e:
        print(f"Could not send email ({e})", flush=True)


def all_pairs():
    pairs, d = [], FIRST
    while d <= LAST:
        for n in TRIP_DAYS:
            pairs.append((d, d + timedelta(days=n), n))
        d += timedelta(days=1)
    return pairs


# ---------- step 1: free scan (existence of flights, rough Jetstar price) ----------
def scan(depart, ret):
    """Returns {'vj': bool, 'js': rough Jetstar price or None}, or None if no nonstop Vietjet/Jetstar flight."""
    from fast_flights import FlightData, Passengers, create_filter, get_flights_from_filter
    filt = create_filter(
        flight_data=[FlightData(date=depart.isoformat(), from_airport=ORIGIN, to_airport=DEST),
                     FlightData(date=ret.isoformat(), from_airport=DEST, to_airport=ORIGIN)],
        trip="round-trip", seat="economy", passengers=Passengers(adults=1))
    res = get_flights_from_filter(filt, currency="AUD", mode="fallback")
    vj, js = False, None
    for f in res.flights:
        if f.stops != 0:
            continue
        name = f.name.lower()
        if "vietjet" in name:
            vj = True
        if "jetstar" in name:
            digits = re.sub(r"[^\d.]", "", f.price.replace(",", ""))
            if digits and (js is None or float(digits) < js):
                js = round(float(digits))
    if not vj and js is None:
        return None
    return {"vj": vj, "js": js}


# ---------- step 2: SerpApi check (the real Google price) ----------
def serp_search(depart, ret):
    """Cheapest nonstop Vietjet/Jetstar round trip as (price, airline), or None."""
    q = urllib.parse.urlencode({
        "engine": "google_flights", "departure_id": ORIGIN, "arrival_id": DEST,
        "outbound_date": depart.isoformat(), "return_date": ret.isoformat(),
        "type": 1, "stops": 2, "currency": "AUD", "hl": "en", "gl": "au",
        "api_key": os.environ["SERPAPI_KEY"]})
    with urllib.request.urlopen("https://serpapi.com/search.json?" + q, timeout=90) as r:
        data = json.load(r)
    if "error" in data:
        msg = str(data["error"])
        if any(w in msg.lower() for w in ("api key", "run out", "limit", "plan", "account")):
            raise HardError(msg)
        return None
    best = None
    for f in data.get("best_flights", []) + data.get("other_flights", []):
        price = f.get("price")
        if price is None or f.get("layovers"):
            continue
        legs = f.get("flights") or [{}]
        airline = (legs[0].get("airline") or "").replace(",", " ")
        if not any(a in airline.lower() for a in AIRLINES):
            continue
        if best is None or price < best[0]:
            best = (round(float(price)), airline)
    return best


# ---------- text helpers ----------
def pretty(iso):
    d = date.fromisoformat(iso[:10])
    return f"{d.day} {d.strftime('%b')}"


def link(d, ret):
    q = f"Flights from {ORIGIN} to {DEST} on {d} through {ret}"
    return "https://www.google.com/travel/flights?hl=en&curr=AUD&q=" + urllib.parse.quote(q)


def table(rows):
    out = ["| Trip | Price | Airline | Checked | Link |", "|---|---|---|---|---|"]
    for t in rows:
        out.append(f"| {pretty(t['depart'])} to {pretty(t['return'])} | A${t['price']} | {t['airline']} | "
                   f"{pretty(t['confirmed'])} | [Check on Google]({link(t['depart'], t['return'])}) |")
    return out


def main():
    os.makedirs("data", exist_ok=True)
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    prev = {}
    if os.path.exists(LATEST):
        try:
            prev = json.load(open(LATEST, encoding="utf-8"))
        except Exception:
            prev = {}
    if prev.get("source") != "hybrid":
        prev = {}
        with open(HIST, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow(FIELDS)
    trips = dict(prev.get("trips", {}))

    # ----- step 1: scan every pair -----
    ok = fail = 0
    for d, ret, n in all_pairs():
        key = f"{d}|{ret}"
        try:
            res = run_with_timeout(scan, d, ret, seconds=60)
        except Exception as e:
            fail += 1
            print(f"{d} +{n}d scan failed: {e}", flush=True)
            continue   # keep whatever we knew
        ok += 1
        if res is None:
            trips.pop(key, None)
        else:
            t = trips.get(key) or {"depart": str(d), "return": str(ret), "days": n,
                                    "price": None, "airline": None, "confirmed": None}
            t.update({"vj": res["vj"], "js": res["js"], "scanned": now.isoformat()})
            trips[key] = t
        time.sleep(random.uniform(1, 2.5))
    print(f"scan: {ok} read, {fail} failed, {len(trips)} date pairs have nonstop Vietjet/Jetstar", flush=True)
    if ok == 0:
        raise SystemExit("The scan read nothing; check the log above.")

    # ----- step 2: daily SerpApi check of the real price -----
    serp_day, serp_used = prev.get("serp_day"), prev.get("serp_used", 0)
    if serp_day != today:
        serp_day, serp_used = today, 0
    checked, new_alerts, hard, ran = [], [], False, 0
    todo = max(0, DAILY_CHECKS - serp_used)
    if todo and os.environ.get("SERPAPI_KEY"):
        cands = sorted(trips.values(), key=lambda t: (t["confirmed"] is not None,
                                                      t["js"] if t["js"] is not None else 99999,
                                                      t["confirmed"] or ""))[:todo]
        with open(HIST, "a", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            for t in cands:
                d, ret = date.fromisoformat(t["depart"]), date.fromisoformat(t["return"])
                try:
                    best = run_with_timeout(serp_search, d, ret, seconds=90)
                except HardError as e:
                    hard = True
                    print(f"SerpApi stopped: {e}", flush=True)
                    break
                except Exception as e:
                    print(f"{d} check failed: {e}", flush=True)
                    continue
                serp_used += 1
                ran += 1
                old = t["price"]
                t["confirmed"] = now.isoformat()
                if best:
                    t["price"], t["airline"] = best
                    if old != best[0]:
                        w.writerow([now.isoformat(), d, ret, t["days"], best[0], best[1]])
                    if best[0] <= ALERT and (old is None or old > ALERT):
                        new_alerts.append(t)
                    checked.append(t)
                    print(f"{d} to {ret}: {best[1]} A${best[0]}", flush=True)
                else:
                    t["price"], t["airline"] = None, None
                    print(f"{d} to {ret}: no nonstop Vietjet/Jetstar fare on Google", flush=True)
                time.sleep(random.uniform(1, 3))
    elif todo:
        print("No SERPAPI_KEY secret, so real prices were not checked.", flush=True)
    else:
        print(f"Already used today's {DAILY_CHECKS} SerpApi checks.", flush=True)

    # ----- email: one report a day, right after the check -----
    did_check = ran > 0
    confirmed = [t for t in trips.values() if t["price"] is not None]
    deals = sorted((t for t in confirmed if t["price"] <= CAP), key=lambda t: t["price"])
    if did_check:
        out = [f"@{USER} Daily fare report: Sydney to Ho Chi Minh City, nonstop Vietjet and Jetstar, 12 and 15 day trips.", ""]
        if deals:
            out += [f"**Trips at or under A${CAP} ({len(deals)})**", ""] + table(deals[:15]) + [""]
        else:
            out += [f"**Nothing confirmed at or under A${CAP} yet.**", ""]
            if confirmed:
                t = min(confirmed, key=lambda t: t["price"])
                out += [f"Cheapest confirmed: A${t['price']} with {t['airline']}, {pretty(t['depart'])} to {pretty(t['return'])}.", ""]
        if checked:
            out += ["**Checked today**", ""] + table(sorted(checked, key=lambda t: t["price"])) + [""]
        out.append(f"{len(trips)} date pairs have nonstop Vietjet or Jetstar flights on sale; {len(confirmed)} have a confirmed price. "
                   f"The rest are checked in turn, {DAILY_CHECKS} a day, cheapest-looking first.")
        out += ["", "Prices are Australian dollars from Google Flights. Click the link and confirm before buying; checked baggage may not be included."]
        post_issue(f"Fare report {today}", "\n".join(out) + "\n")
    if new_alerts:
        a = ([f"@{USER} **A trip has dropped to A${ALERT} or under.** Sydney to Ho Chi Minh City, nonstop.", ""]
             + table(sorted(new_alerts, key=lambda t: t["price"]))
             + ["", "Click the link and confirm on Google Flights before buying."])
        post_issue(f"ALERT - trip at or under A${ALERT} ({today})", "\n".join(a) + "\n")

    json.dump({"source": "hybrid", "updated": now.isoformat(), "cap": CAP, "serp_day": serp_day,
               "serp_used": serp_used, "trips": trips}, open(LATEST, "w", encoding="utf-8"))
    if hard and not checked and serp_used == 0:
        print("SerpApi stopped on its first search; check the key and monthly allowance.", flush=True)


if __name__ == "__main__":
    main()

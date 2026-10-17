"""Daily check SYD<->SGN with SerpApi (Google Flights, Australian prices).
Looks at nonstop Vietjet and Jetstar flights for 12 and 15 day trips. Each run checks a few date pairs,
so every pair is re-checked about once a month and the free SerpApi plan (250 searches a month) is enough.
Saves everything to data/latest.json (the dashboard reads it) and emails you a daily report."""
import csv, json, math, os, random, threading, time, urllib.error, urllib.parse, urllib.request
from datetime import date, datetime, timedelta, timezone

ORIGIN, DEST = "SYD", "SGN"
FIRST, LAST = date(2027, 8, 1), date(2027, 11, 15)
TRIP_DAYS = [12, 15]
AIRLINES = ("vietjet", "jetstar")   # only these airlines are tracked
ALERT = 400      # A$ a trip newly at or under this triggers its own urgent email
CAP = 500        # A$ at or under this counts as a deal
PER_RUN = 7      # searches per run: about 215 a month, inside the free 250
KEEP_DAYS = 45   # a trip is dropped if it has not been re-checked for this long
HIST = "data/prices.csv"
LATEST = "data/latest.json"
FIELDS = ["checked", "depart", "return", "days", "price", "airline", "stops"]
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
        raise TimeoutError(f"search took longer than {seconds} seconds")
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


def spread_order(pairs):
    """Visit the pairs in a scattered order so every week of the window is sampled early."""
    stride = 31
    while math.gcd(stride, len(pairs)) != 1:
        stride += 1
    return [pairs[(i * stride) % len(pairs)] for i in range(len(pairs))]


def search(depart, ret):
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
        return None   # no flights for these dates (usually not on sale yet)
    best = None
    for f in data.get("best_flights", []) + data.get("other_flights", []):
        price = f.get("price")
        if price is None or f.get("layovers"):
            continue   # nonstop only
        legs = f.get("flights") or [{}]
        airline = (legs[0].get("airline") or "").replace(",", " ")
        if not any(a in airline.lower() for a in AIRLINES):
            continue
        if best is None or price < best[0]:
            best = (round(float(price)), airline)
    return best


def pretty(iso):
    d = date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%b')}"


def link(d, ret):
    q = f"Flights from {ORIGIN} to {DEST} on {d} through {ret}"
    return "https://www.google.com/travel/flights?hl=en&curr=AUD&q=" + urllib.parse.quote(q)


def table(rows):
    out = ["| Trip | Price | Airline | Checked | Link |", "|---|---|---|---|---|"]
    for t in rows:
        out.append(f"| {pretty(t['depart'])} to {pretty(t['return'])} | A${t['price']} | {t['airline']} | "
                   f"{pretty(t['seen'][:10])} | [Check on Google]({link(t['depart'], t['return'])}) |")
    return out


def main():
    os.makedirs("data", exist_ok=True)
    if not os.environ.get("SERPAPI_KEY"):
        raise SystemExit("SERPAPI_KEY is missing. Add it under Settings > Secrets and variables > Actions.")
    now = datetime.now(timezone.utc)
    prev = {}
    if os.path.exists(LATEST):
        try:
            prev = json.load(open(LATEST, encoding="utf-8"))
        except Exception:
            prev = {}
    if prev.get("source") != "serpapi":
        prev = {}   # older data came from a different method, so start fresh
        with open(HIST, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow(FIELDS)
    trips = dict(prev.get("trips", {}))
    pairs = all_pairs()
    order = spread_order(pairs)
    cursor = prev.get("cursor", 0) % len(order)
    batch = [order[(cursor + i) % len(order)] for i in range(PER_RUN)]
    checked, new_alerts, ok, none, hard = [], [], 0, 0, 0
    with open(HIST, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        for d, ret, n in batch:
            key = f"{d}|{ret}"
            old = trips.get(key)
            try:
                best = run_with_timeout(search, d, ret, seconds=60)
            except HardError as e:
                hard += 1
                print(f"{d} +{n}d stopped: {e}", flush=True)
                break
            except Exception as e:
                none += 1
                print(f"{d} +{n}d failed: {e}", flush=True)
                continue
            if best:
                price, airline = best
                trips[key] = {"depart": str(d), "return": str(ret), "days": n,
                              "price": price, "airline": airline, "seen": now.isoformat()}
                if not old or old["price"] != price:
                    w.writerow([now.isoformat(), d, ret, n, price, airline, 0])
                if price <= ALERT and (not old or old["price"] > ALERT):
                    new_alerts.append(trips[key])
                checked.append(trips[key])
                ok += 1
                print(f"{d} to {ret}: {airline} A${price}", flush=True)
            else:
                trips.pop(key, None)
                none += 1
                print(f"{d} to {ret}: no nonstop Vietjet/Jetstar fare", flush=True)
            fh.flush()
            time.sleep(random.uniform(1, 3))
    print(f"found {ok}, nothing found {none}, stopped {hard}")
    if hard and ok == 0 and none == 0:
        raise SystemExit("Search stopped; check the SerpApi key and monthly allowance.")
    cutoff = now - timedelta(days=KEEP_DAYS)
    trips = {k: t for k, t in trips.items() if datetime.fromisoformat(t["seen"]) >= cutoff}
    done = len(batch) if not hard else ok + none
    cursor = (cursor + done) % len(order)
    deals = sorted((t for t in trips.values() if t["price"] <= CAP), key=lambda t: t["price"])
    out = [f"@{USER} Daily fare report: Sydney to Ho Chi Minh City, nonstop Vietjet and Jetstar, 12 and 15 day trips.", ""]
    if deals:
        out += [f"**Trips at or under A${CAP} (latest readings, {len(deals)})**", ""] + table(deals[:15]) + [""]
    else:
        out += [f"**Nothing at or under A${CAP} in the readings so far.**", ""]
        if trips:
            t = min(trips.values(), key=lambda t: t["price"])
            out += [f"Cheapest so far: A${t['price']} with {t['airline']}, {pretty(t['depart'])} to {pretty(t['return'])}.", ""]
    if checked:
        out += ["**Checked today**", ""] + table(sorted(checked, key=lambda t: t["price"])) + [""]
    out.append(f"Checked {ok + none} date pairs today; {none} had no nonstop Vietjet or Jetstar fare. "
               f"Tracking {len(trips)} trips. Every pair is re-checked about every {math.ceil(len(pairs) / PER_RUN)} days.")
    out += ["", "Prices are Australian dollars from Google Flights. Click the link and confirm before buying; checked baggage may not be included."]
    post_issue(f"Fare report {now.strftime('%Y-%m-%d')}", "\n".join(out) + "\n")
    if new_alerts:
        a = ([f"@{USER} **A trip has dropped to A${ALERT} or under.** Sydney to Ho Chi Minh City, nonstop.", ""]
             + table(sorted(new_alerts, key=lambda t: t["price"]))
             + ["", "Click the link and confirm on Google Flights before buying."])
        post_issue(f"ALERT - trip at or under A${ALERT} ({now.strftime('%Y-%m-%d')})", "\n".join(a) + "\n")
    json.dump({"source": "serpapi", "updated": now.isoformat(), "cap": CAP, "cursor": cursor, "trips": trips},
              open(LATEST, "w", encoding="utf-8"))


if __name__ == "__main__":
    main()

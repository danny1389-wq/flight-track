"""DRAFT - Kiwi Vietjet tracker SYD<->SGN, nonstop, one-way legs, 12 and 15 day trips.
Separate from the Jetstar tracker: its own files in data/kiwi_vj/, no shared code, nothing imported from tracker.py.
Does nothing unless KIWI_VJ_ENABLED=yes. Alerts are off unless KIWI_VJ_ALERTS=yes.
Uses Kiwi's public MCP endpoint (search-flight) with date ranges. Missing dates are UNKNOWN, never 'not available'.
Stops at once if Kiwi answers 403/429 (no retries, no workarounds)."""
import csv, json, os, sys, time, urllib.request, urllib.error
from datetime import date, datetime, timedelta, timezone

URL = "https://mcp.kiwi.com"
HDR = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
ORIGIN, DEST = "SYD", "SGN"
FIRST, LAST = date(2027, 8, 1), date(2027, 11, 15)
TRIP_DAYS = [12, 15]
ALERT, CAP = 400, 500       # A$ per trip (outbound + return, Kiwi all-in prices)
WINDOW_DAYS = 7             # dates per request
RESULT_CAP = 15             # Kiwi returns at most 15 itineraries per range search; a full page = maybe truncated -> split
MAX_REQUESTS = 70           # hard budget per run
PAUSE = 15                  # seconds between requests
EMPTY_STOP = 2              # stop a direction after this many consecutive empty windows (later dates stay UNKNOWN)
D = "data/kiwi_vj"
USER = "danny1389-wq"


class Blocked(Exception):
    pass


class Kiwi:
    def __init__(self):
        self.sid, self.n, self.requests = None, 0, 0

    def _rpc(self, body, timeout=90):
        h = dict(HDR)
        if self.sid:
            h["mcp-session-id"] = self.sid
        req = urllib.request.Request(URL, json.dumps(body).encode(), h)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                txt = r.read().decode()
                self.sid = r.headers.get("mcp-session-id") or self.sid
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 429):
                raise Blocked(f"HTTP {e.code}")
            raise
        line = next((l for l in txt.split("\n") if l.startswith("data:")), None)
        return json.loads(line[5:] if line else txt)

    def start(self):
        self._rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "fare-tracker", "version": "1"}}})
        try:
            self._rpc({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except Blocked:
            raise
        except Exception:
            pass

    def search(self, frm, to, d1, d2):
        """Vietjet-only, nonstop, AUD, one-way, cheapest first. Returns the list of itineraries (may be empty)."""
        self.n += 1
        self.requests += 1
        args = {"flyFrom": frm, "flyTo": to, "departureDate": d1.strftime("%d/%m/%Y"), "adults": 1, "cabinClass": "M",
                "currency": "AUD", "sort": "price", "select_airlines": "VJ", "max_sector_stopovers": 0}
        if d2 > d1:
            args["departureDateTo"] = d2.strftime("%d/%m/%Y")
        r = self._rpc({"jsonrpc": "2.0", "id": self.n + 1, "method": "tools/call",
                       "params": {"name": "search-flight", "arguments": args}})
        res = r.get("result", {})
        txt = (res.get("content") or [{}])[0].get("text", "")
        if res.get("isError") or not txt:
            raise RuntimeError("Kiwi error: " + (txt or json.dumps(r))[:200])
        return json.loads(txt).get("itineraries", [])


def vietjet_leg(it):
    """Return (date_str, leg dict) for a Vietjet nonstop itinerary, else None."""
    ob = it.get("outbound") or {}
    segs = ob.get("segments") or []
    if ob.get("stops") != 0 or len(segs) != 1 or "viet" not in (segs[0].get("carrierName") or "").lower():
        return None
    s = segs[0]
    flight = f"{s.get('carrierCode') or 'VJ'}{s.get('flightNumber') or ''}".replace("VJVJ", "VJ")
    bag = it.get("baggage") or {}
    return ob["departureTime"][:10], {"p": float(it["price"]), "a": "Vietjet", "flight": flight, "id": it.get("id"),
                                       "url": it.get("bookingUrl"), "dep": ob["departureTime"],
                                       "checked_bag": bag.get("checkedBag"), "cabin_bag": bag.get("cabinBag")}


def scan(kiwi, frm, to, first, last, now_iso, state, log):
    """Scan first..last in WINDOW_DAYS windows. A window that fills Kiwi's result cap is split, so the cap never hides a fare.
    Returns (legs {date: leg}, coverage dict)."""
    legs, cov = {}, {"windows": [], "stopped_early": False, "possibly_truncated_days": []}
    empty_run = [0]

    def window(d1, d2):
        if state["stop"]:
            return
        if kiwi.requests >= MAX_REQUESTS:
            state["stop"], state["why"] = True, "request budget reached"
            return
        if empty_run[0] >= EMPTY_STOP:
            cov["stopped_early"] = True
            return
        if kiwi.requests:
            time.sleep(PAUSE)
        try:
            its = kiwi.search(frm, to, d1, d2)
        except Blocked as e:
            state["stop"], state["why"] = True, f"Kiwi refused the request ({e}); stopped, no workaround attempted"
            return
        except Exception as e:
            cov["windows"].append({"from": str(d1), "to": str(d2), "error": str(e)[:160]})
            log(f"{frm}->{to} {d1}..{d2}: ERROR {e}")
            return
        full = len(its) >= RESULT_CAP
        cov["windows"].append({"from": str(d1), "to": str(d2), "n": len(its), "full_page": full})
        log(f"{frm}->{to} {d1}..{d2}: {len(its)} itineraries{' (full page)' if full else ''}")
        if full and d2 > d1:
            mid = d1 + (d2 - d1) // 2
            window(d1, mid)
            window(mid + timedelta(days=1), d2)
            return
        if full:
            cov["possibly_truncated_days"].append(str(d1))
        mine = [x for x in map(vietjet_leg, its) if x]
        empty_run[0] = 0 if mine else empty_run[0] + 1
        per_day = {}
        for day, leg in mine:
            per_day.setdefault(day, []).append(leg)
        for day, ls in per_day.items():
            best = min(ls, key=lambda l: l["p"])
            best["n_itineraries"] = len(ls)
            best["seen"] = now_iso
            legs[day] = best

    d = first
    while d <= last and not state["stop"] and empty_run[0] < EMPTY_STOP:
        window(d, min(d + timedelta(days=WINDOW_DAYS - 1), last))
        d += timedelta(days=WINDOW_DAYS)
    if empty_run[0] >= EMPTY_STOP:
        cov["stopped_early"] = True
    cov["dates_with_result"] = sorted(legs)
    cov["dates_unknown"] = [str(first + timedelta(days=i)) for i in range((last - first).days + 1)
                            if str(first + timedelta(days=i)) not in legs]
    return legs, cov


def build_trips(out_legs, back_legs, now_iso):
    """Every outbound date FIRST..LAST paired with a return exactly 12 or 15 days later, when both legs have a price."""
    trips, d = {}, FIRST
    while d <= LAST:
        for n in TRIP_DAYS:
            r = d + timedelta(days=n)
            o, b = out_legs.get(d.isoformat()), back_legs.get(r.isoformat())
            if o and b:
                trips[f"{d}|{r}"] = {"depart": str(d), "return": str(r), "days": n, "price": round(o["p"] + b["p"]),
                                     "out": o["p"], "out_flight": o["flight"], "out_id": o["id"], "out_url": o["url"],
                                     "back": b["p"], "back_flight": b["flight"], "back_id": b["id"], "back_url": b["url"],
                                     "fresh": o["seen"] == now_iso and b["seen"] == now_iso,
                                     "seen": min(o["seen"], b["seen"])}
        d += timedelta(days=1)
    return trips


def post_issue(title, body):
    token, repo = os.environ.get("GH_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print("No GitHub token, no email sent.", flush=True)
        return
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/issues",
                                 data=json.dumps({"title": title, "body": body}).encode(),
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                          "Content-Type": "application/json", "User-Agent": "fare-tracker"})
    try:
        urllib.request.urlopen(req, timeout=30).read()
    except Exception as e:
        print(f"Could not send email ({e})", flush=True)


def load(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def main():
    if os.environ.get("KIWI_VJ_ENABLED") != "yes":
        print("Kiwi Vietjet tracker is DISABLED (set KIWI_VJ_ENABLED=yes to run). Nothing requested.")
        return
    os.makedirs(D, exist_ok=True)
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    prev = load(f"{D}/legs.json", {"out": {}, "back": {}})
    lines = []
    log = lambda s: (print(s, flush=True), lines.append(s))
    kiwi, state = Kiwi(), {"stop": False, "why": ""}
    try:
        kiwi.start()
    except Exception as e:
        log(f"Could not start Kiwi session: {e}")
        state["stop"], state["why"] = True, str(e)
    out_new, back_new, cov = {}, {}, {}
    if not state["stop"]:
        out_new, cov["out"] = scan(kiwi, ORIGIN, DEST, FIRST, LAST, now_iso, state, log)
    if not state["stop"]:
        back_new, cov["back"] = scan(kiwi, DEST, ORIGIN, FIRST + timedelta(days=min(TRIP_DAYS)),
                                     LAST + timedelta(days=max(TRIP_DAYS)), now_iso, state, log)
    # Keep older readings (marked by their own 'seen' time); this run's readings replace them. Nothing is deleted because a date was missing.
    legs = {"out": {**prev.get("out", {}), **out_new}, "back": {**prev.get("back", {}), **back_new}}
    trips = build_trips(legs["out"], legs["back"], now_iso)
    json.dump({"source": "kiwi", "updated": now_iso, "requests": kiwi.requests, "stopped": state["why"], "legs": legs},
              open(f"{D}/legs.json", "w", encoding="utf-8"))
    json.dump({"updated": now_iso, "cap": CAP, "alert": ALERT, "trips": trips}, open(f"{D}/trips.json", "w", encoding="utf-8"))
    json.dump({"updated": now_iso, "requests": kiwi.requests, "stopped": state["why"], **cov},
              open(f"{D}/coverage.json", "w", encoding="utf-8"))
    new_file = not os.path.exists(f"{D}/history.csv")
    with open(f"{D}/history.csv", "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new_file:
            w.writerow(["checked", "direction", "date", "price", "flight", "itinerary_id", "checked_bag"])
        for dirn, ls in (("out", out_new), ("back", back_new)):
            for day, l in sorted(ls.items()):
                w.writerow([now_iso, dirn, day, l["p"], l["flight"], l["id"], l["checked_bag"]])
    deals = sorted((t for t in trips.values() if t["fresh"] and t["price"] <= CAP), key=lambda t: t["price"])
    log(f"{kiwi.requests} requests. {len(out_new)} outbound and {len(back_new)} return dates with a price this run. "
        f"{len(trips)} trips priced, {len(deals)} at or under A${CAP}.")
    if state["why"]:
        log("STOPPED EARLY: " + state["why"])
    if os.environ.get("KIWI_VJ_ALERTS") == "yes" and deals:
        sent = load(f"{D}/alerted.json", {})
        fresh_deals = [t for t in deals if t["price"] < sent.get(f"{t['depart']}|{t['return']}", 10 ** 9)]
        great = [t for t in fresh_deals if t["price"] <= ALERT]
        row = lambda t: (f"| {t['depart']} to {t['return']} | {t['days']} days | A${t['price']} | "
                         f"{t['out_flight']} A${t['out']:.0f} + {t['back_flight']} A${t['back']:.0f} | "
                         f"[out]({t['out_url']}) [back]({t['back_url']}) |")
        head = ["| Dates | Length | Total | Legs | Kiwi links |", "|---|---|---|---|---|"]
        note = ("Kiwi.com Vietjet fares, two separate one-way tickets. Each price is Kiwi's all-in price for one adult "
                "(includes taxes and Kiwi's service fee) and **excludes a checked bag**. Not confirmed bookable until you check the links.")
        if fresh_deals:
            post_issue(f"Kiwi Vietjet update {now:%Y-%m-%d %H:%M} UTC",
                       "\n".join([f"@{USER} Vietjet trips at or under A${CAP}:", ""] + head + [row(t) for t in fresh_deals[:15]] + ["", note]))
        if great:
            post_issue(f"ALERT - Kiwi Vietjet trip at or under A${ALERT}",
                       "\n".join([f"@{USER} **Vietjet trip at or under A${ALERT}.**", ""] + head + [row(t) for t in great] + ["", note]))
        for t in fresh_deals:
            sent[f"{t['depart']}|{t['return']}"] = t["price"]
        json.dump(sent, open(f"{D}/alerted.json", "w"))
    open(f"{D}/last_run.txt", "w").write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

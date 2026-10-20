
"""Kiwi repeat test (5 requests per run, 15s apart). Vietjet-only, nonstop, AUD, one-way.
Appends to data/kiwi_repeat.txt so several runs at different times build up a record."""
import json, time, datetime, os, urllib.request

URL = "https://mcp.kiwi.com"
H = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
out = []
def log(s=""):
    print(s); out.append(str(s))

def rpc(body, sid=None, t=90):
    h = dict(H)
    if sid: h["mcp-session-id"] = sid
    req = urllib.request.Request(URL, json.dumps(body).encode(), h)
    with urllib.request.urlopen(req, timeout=t) as r:
        txt = r.read().decode()
        new = r.headers.get("mcp-session-id") or sid
    line = next((l for l in txt.split("\n") if l.startswith("data:")), None)
    return json.loads(line[5:] if line else txt), new

now = datetime.datetime.utcnow()
log("\n##### RUN " + now.isoformat() + "Z (UTC) = " + (now + datetime.timedelta(hours=11)).strftime("%H:%M Sydney (AEDT)"))
sid = None
try:
    r, sid = rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "fare-test", "version": "1"}}})
    try: rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    except Exception: pass
except Exception as e:
    log("INIT ERROR: %r" % e)

# (from, to, date, date_to or None)
SEARCHES = [("SYD","SGN","16/08/2027",None), ("SGN","SYD","29/08/2027",None),
            ("SGN","SYD","31/08/2027",None), ("SYD","SGN","29/08/2027",None),
            ("SYD","SGN","01/08/2027","29/08/2027")]
n = 2
for a, b, d, d2 in SEARCHES:
    args = {"flyFrom": a, "flyTo": b, "departureDate": d, "adults": 1, "cabinClass": "M",
            "currency": "AUD", "sort": "price", "select_airlines": "VJ", "max_sector_stopovers": 0}
    if d2: args["departureDateTo"] = d2
    log(f"\n=== {a}->{b} {d}" + (f" to {d2}" if d2 else "") + " VJ nonstop")
    try:
        n += 1
        r, _ = rpc({"jsonrpc": "2.0", "id": n, "method": "tools/call",
                    "params": {"name": "search-flight", "arguments": args}}, sid)
        txt = (r.get("result", {}).get("content") or [{}])[0].get("text", "")
        if not txt or r.get("result", {}).get("isError"):
            log("ERROR/EMPTY: " + (txt or json.dumps(r))[:400]); continue
        its = json.loads(txt).get("itineraries", [])
        log(f"{len(its)} itineraries")
        for it in its[:30]:
            o = it.get("outbound") or {}
            segs = o.get("segments", [])
            fn = ",".join(str(s.get("flightNumber") or s.get("carrierCode", "")) for s in segs)
            car = "/".join(dict.fromkeys(s.get("carrierName", "?") for s in segs))
            log(f"  A${it.get('price')}  {car}  {fn}  stops={o.get('stops')}  {o.get('departureTime')}  checkedBag={(it.get('baggage') or {}).get('checkedBag')}  {it.get('bookingUrl')}")
        if its: log("FULL cheapest: " + json.dumps(its[0])[:2500])
    except Exception as e:
        log("ERROR: %r" % e)
    time.sleep(15)

os.makedirs("data", exist_ok=True)
with open("data/kiwi_repeat.txt", "a") as f:
    f.write("\n".join(out) + "\n")

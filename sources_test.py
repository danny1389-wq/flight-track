"""One-off diagnostic: can GitHub's servers read flight prices from several booking sites?
It only LOOKS (plain headless Chromium, no stealth tricks, no CAPTCHA solving). If a site blocks it, that is reported as blocked.
For each site it records: robots.txt rules, whether the page loaded, whether a bot check appeared, whether Vietjet nonstop shows,
the price near Vietjet, and any member-only / baggage wording. Output: data/sources_test.txt (+ screenshots data/src_*.png)."""
import os, re, traceback, urllib.request
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

OUT = []
def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True); OUT.append(s)

D = "2027-08-29"
SITES = {
 "edreams": {"host": "https://www.edreams.com.au",
    "urls": {"SYD-SGN": f"https://www.edreams.com.au/travel/#results/infants=0;children=0;adults=1;type=O;class=TOURIST;from.iata=SYD;to.iata=SGN;dep={D}",
             "SGN-SYD": f"https://www.edreams.com.au/travel/#results/infants=0;children=0;adults=1;type=O;class=TOURIST;from.iata=SGN;to.iata=SYD;dep={D}"}},
 "trip.com": {"host": "https://au.trip.com",
    "urls": {"SYD-SGN": f"https://au.trip.com/flights/sydney-to-ho-chi-minh-city/tickets-syd-sgn/?dcity=syd&acity=sgn&ddate={D}&triptype=ow&class=y&quantity=1&searchboxarg=t",
             "SGN-SYD": f"https://au.trip.com/flights/ho-chi-minh-city-to-sydney/tickets-sgn-syd/?dcity=sgn&acity=syd&ddate={D}&triptype=ow&class=y&quantity=1&searchboxarg=t"}},
 "kiwi.com": {"host": "https://www.kiwi.com",
    "urls": {"SYD-SGN": f"https://www.kiwi.com/en/search/results/SYD/SGN/{D}/no-return/?currency=AUD",
             "SGN-SYD": f"https://www.kiwi.com/en/search/results/SGN/SYD/{D}/no-return/?currency=AUD"}},
 "mytrip": {"host": "https://www.mytrip.com",
    "urls": {"home": "https://www.mytrip.com/"}},
 "gotogate": {"host": "https://www.gotogate.com.au",
    "urls": {"home": "https://www.gotogate.com.au/"}},
 "skyscanner": {"host": "https://www.skyscanner.com.au",
    "urls": {"SYD-SGN": "https://www.skyscanner.com.au/transport/flights/syd/sgn/270829/?adultsv2=1&cabinclass=economy&rtn=0&currency=AUD",
             "SGN-SYD": "https://www.skyscanner.com.au/transport/flights/sgn/syd/270829/?adultsv2=1&cabinclass=economy&rtn=0&currency=AUD"}},
}
BLOCK = re.compile(r"captcha|access denied|verify you are human|unusual traffic|pardon our interruption|are you a robot|robot or human|press (&|and) hold|px-captcha|datadome|request blocked|forbidden", re.I)
PRICE = re.compile(r"(?:A\$|AU\$|AUD|\$)\s?\d[\d,]*(?:\.\d{1,2})?")

def robots(host):
    try:
        req = urllib.request.Request(host + "/robots.txt", headers={"User-Agent": "Mozilla/5.0"})
        t = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "ignore")
    except Exception as e:
        return f"robots.txt not readable ({str(e)[:60]})"
    lines, on, out = t.splitlines(), False, []
    for ln in lines:
        l = ln.strip()
        if l.lower().startswith("user-agent:"):
            on = l.split(":", 1)[1].strip() == "*"
        elif on and l.lower().startswith(("disallow:", "allow:")):
            out.append(l)
    rel = [x for x in out if re.search(r"flight|search|result|travel|air|booking|/$|\*", x, re.I)]
    return f"{len(out)} rules for all robots; relevant: {rel[:8] if rel else 'none that mention flights/search/results'}"

def main():
    os.makedirs("data", exist_ok=True)
    log("Checked (UTC):", datetime.now(timezone.utc).isoformat(timespec="seconds"), "| date tested:", D)
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(locale="en-AU", timezone_id="Australia/Sydney", viewport={"width": 1366, "height": 900})
        for name, cfg in SITES.items():
            log(f"\n===== {name} =====")
            log("robots.txt:", robots(cfg["host"]))
            for leg, url in cfg["urls"].items():
                page = ctx.new_page()
                try:
                    r = page.goto(url, timeout=45000, wait_until="domcontentloaded")
                    page.wait_for_timeout(15000)
                    body = page.inner_text("body")
                    status = r.status if r else None
                    blocked = bool(BLOCK.search(body[:3000])) or (status in (403, 429))
                    low = body.lower()
                    vj = [m.start() for m in re.finditer("vietjet", low)]
                    near = []
                    for i in vj[:3]:
                        seg = body[max(0, i - 250): i + 250]
                        near.append(sorted(set(PRICE.findall(seg)))[:4])
                    allp = PRICE.findall(body)
                    log(f"[{leg}] status={status} blocked={blocked} title={page.title()[:70]!r} text_len={len(body)} price_tokens={len(allp)}")
                    log(f"   Vietjet mentioned: {len(vj)}x | prices near Vietjet: {near if near else 'n/a'}")
                    log(f"   nonstop/direct words: {len(re.findall(r'nonstop|direct', low))} | baggage mentions: {sorted(set(re.findall(r'(?:checked|cabin|hand|carry-on)[ a-z\-]{0,20}bag(?:gage)?[ a-z]{0,15}', low)))[:4]}")
                    log(f"   member/Prime/sign-in wording: {sorted(set(re.findall(r'prime|member|sign in|log in', low)))[:5]}")
                    log("   first text:", body[:160].replace("\n", " "))
                    page.screenshot(path=f"data/src_{name.replace('.', '')}_{leg}.png")
                except Exception as e:
                    log(f"[{leg}] FAILED: {str(e)[:160]}")
                finally:
                    page.close()
        b.close()

try:
    main()
except Exception:
    log("CRASH", traceback.format_exc())
open("data/sources_test.txt", "w", encoding="utf-8").write("\n".join(OUT) + "\n")

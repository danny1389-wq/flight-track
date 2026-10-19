"""One-off test: can a headless browser on GitHub read Vietjet's own fares (Australian site, AUD)?
Writes data/vietjet_test.txt (plus screenshots in data/). Nothing else is changed."""
import json, os, re, sys, traceback
from playwright.sync_api import sync_playwright

OUT = []
def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True); OUT.append(s)

CASES = [("SYD", "SGN", "2027-08-16", "Chrome showed A$303"),
         ("SGN", "SYD", "2027-08-29", "Chrome showed A$251")]

def candidates(frm, to, d):
    return [
        f"https://www.vietjetair.com/en/booking/select-flight?tripType=oneway&departure={frm}&destination={to}&departureDate={d}&adults=1&children=0&infants=0&currency=AUD",
        f"https://www.vietjetair.com/en/booking?tripType=oneway&from={frm}&to={to}&departureDate={d}&adult=1",
        f"https://booking.vietjetair.com/Index.aspx?lang=en&st=sl&flo=0&cur=AUD&dep={frm}&des={to}&dd={d}&ad=1",
    ]

def main():
    os.makedirs("data", exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = b.new_context(locale="en-AU", timezone_id="Australia/Sydney",
                            viewport={"width": 1366, "height": 900},
                            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
        # 1. home page
        page = ctx.new_page()
        hits = []
        def on_resp(r):
            try:
                ct = r.headers.get("content-type", "")
                if "json" in ct and r.status == 200:
                    t = r.text()
                    if re.search(r"fare|price|amount|AUD", t, re.I):
                        hits.append((r.url, t[:600]))
            except Exception:
                pass
        page.on("response", on_resp)
        try:
            resp = page.goto("https://www.vietjetair.com/en", timeout=45000, wait_until="domcontentloaded")
            page.wait_for_timeout(6000)
            log("HOME status:", resp.status if resp else None, "| title:", page.title())
            txt = page.inner_text("body")[:400].replace("\n", " ")
            log("HOME text:", txt)
            page.screenshot(path="data/vj_home.png")
        except Exception as e:
            log("HOME failed:", e)
        # 2. each case, each candidate url
        for i, (frm, to, d, note) in enumerate(CASES):
            log(f"\n=== {frm}->{to} {d} ({note}) ===")
            for j, url in enumerate(candidates(frm, to, d)):
                hits.clear()
                try:
                    r = page.goto(url, timeout=45000, wait_until="domcontentloaded")
                    page.wait_for_timeout(10000)
                    body = page.inner_text("body")
                    prices = sorted(set(re.findall(r"(?:A\$|AUD)\s?[\d,]+(?:\.\d+)?|[\d,]{3,}(?:\.\d+)?\s?AUD", body)))[:15]
                    log(f"[{j}] status={r.status if r else None} url={page.url[:110]}")
                    log(f"    title={page.title()[:80]} | prices on page: {prices}")
                    log(f"    text: {body[:250].replace(chr(10), ' ')}")
                    if re.search(r"captcha|access denied|blocked|verify you are human|unusual traffic", body, re.I):
                        log("    BLOCKED by bot check")
                    for u, t in hits[:4]:
                        log(f"    JSON {u[:100]} -> {t[:300]}")
                    page.screenshot(path=f"data/vj_{i}_{j}.png")
                except Exception as e:
                    log(f"[{j}] failed: {str(e)[:150]}")
        b.close()

try:
    main()
except Exception:
    log("CRASH", traceback.format_exc())
open("data/vietjet_test.txt", "w", encoding="utf-8").write("\n".join(OUT) + "\n")

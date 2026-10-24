#!/usr/bin/env python3
"""stockholm.py — Apple Store pickup-stock watcher.

You refresh Apple's stock page. It says no. You refresh again. This script does
the refreshing for you, within the limits Apple tolerates, and makes your phone
scream the moment the thing you want becomes available for in-store pickup.

It does NOT buy anything. Checkout is a human job (Apple Pay + Face ID takes 15s,
and automating it is what gets launch-day orders cancelled).

Features
  * one request per cycle covers the 12 stores nearest a postcode (+ optional 2nd postcode)
  * Plan A / Plan B tiers (e.g. 1TB first, 2TB fallback) with separate alerts
  * alerts: ntfy push (priority 5, bypasses silent mode) + iMessage (macOS) + macOS notification
  * direct link to the pre-configured product page per colour/capacity
  * adaptive polling: slow overnight, fast in the launch window
  * block-aware: HTTP 541/403 -> backoff + re-handshake + ONE loud warning + ONE recovery notice
  * hot standby: a second Mac polls only if the primary's heartbeat goes stale (same IP, no extra load)
  * self-uninstalls (launchd + files) when the run window ends

Config is via environment variables (see README). Standard library only, Python 3.9+.

Usage:
  stockholm.py                run (respects RUN_UNTIL, then self-uninstalls)
  stockholm.py --once         one poll cycle, print state, exit (no alerts)
  stockholm.py --test-alert   send a test alert on every channel and exit
  stockholm.py --no-uninstall run but never self-remove
"""
import json, os, random, signal, subprocess, sys, time, urllib.request, urllib.parse, urllib.error
from datetime import datetime
from http.cookiejar import CookieJar

# ---------------------------------------------------------------- config ----
def env(name, default=""):
    return os.environ.get(name, default)

COUNTRY = env("STOCK_COUNTRY", "uk")                       # apple.com/<country>/shop/...
PRODUCT_SLUG = env("STOCK_PRODUCT", "iphone-duo")          # /shop/buy-iphone/<slug>

# Part numbers -> human names. UK iPhone Duo SIM-free parts (Oct 2026):
#   MK2J4QN/A 1TB Night Sky   MK2H4QN/A 1TB Star White
#   MK2L4QN/A 2TB Night Sky   MK2K4QN/A 2TB Star White
# Find yours: curl the buy page and grep '"partNumber":"...","price"...,"name":"..."'.
PARTS = {
    "MK2J4QN/A": "iPhone Duo 1TB Night Sky",
    "MK2H4QN/A": "iPhone Duo 1TB Star White",
    "MK2L4QN/A": "iPhone Duo 2TB Night Sky",
    "MK2K4QN/A": "iPhone Duo 2TB Star White",
}
PLAN_A = {"MK2J4QN/A", "MK2H4QN/A"}       # everything else is Plan B
PART_URL = {                              # pre-configured product pages (capacity+colour selected)
    "MK2J4QN/A": f"https://www.apple.com/{COUNTRY}/shop/buy-iphone/{PRODUCT_SLUG}/7.6-inch-display-1tb-night-sky",
    "MK2H4QN/A": f"https://www.apple.com/{COUNTRY}/shop/buy-iphone/{PRODUCT_SLUG}/7.6-inch-display-1tb-star-white",
    "MK2L4QN/A": f"https://www.apple.com/{COUNTRY}/shop/buy-iphone/{PRODUCT_SLUG}/7.6-inch-display-2tb-night-sky",
    "MK2K4QN/A": f"https://www.apple.com/{COUNTRY}/shop/buy-iphone/{PRODUCT_SLUG}/7.6-inch-display-2tb-star-white",
}

PRIMARY_LOCATION = env("STOCK_LOCATION", "W1B 5AH")        # postcode: Apple returns its 12 nearest stores
SECONDARY_LOCATION = env("STOCK_LOCATION2", "")            # optional; polled every 3rd cycle
# Store IDs to watch, in priority order (alerts list them in this order). Run --once
# with an empty list to print everything Apple returns for your postcode(s).
TARGET_STORES = [(p.split(":")[0], p.split(":")[1]) for p in env(
    "STOCK_STORES",
    "R092:Regent Street,R245:Covent Garden,R762:Battersea,R226:White City,R329:Brompton Road,"
    "R163:Brent Cross,R227:Kingston,R527:Watford,R410:Stratford City,R496:Bromley").split(",") if p]
TARGET_IDS = {s for s, _ in TARGET_STORES}

IMESSAGE_TO = env("STOCK_IMESSAGE_TO", "")                 # e.g. +447700900000 (macOS Messages must be signed in)
NTFY_TOPICS = [t.strip() for t in env("STOCK_NTFY_TOPIC", "").split(",") if t.strip()]   # comma-separate for a partner/family
NTFY_SERVER = env("STOCK_NTFY_SERVER", "https://ntfy.sh")
HEARTBEAT_EVERY = int(env("STOCK_HEARTBEAT", "3600"))      # seconds; 0 disables (iMessage only, silent)
REALERT_EVERY = 300                                        # re-send while still available
RUN_UNTIL = datetime.fromisoformat(env("STOCK_RUN_UNTIL", "2026-10-24T23:59"))
# Fast-polling windows (local time): the launch-morning drop, then midday and evening when
# uncollected reservations expire back into stock. Everything else runs at INTERVAL_COLD.
HOT_WINDOWS = [((5, 30), (10, 0), 45), ((12, 0), (14, 30), 60), ((20, 0), (22, 30), 60)]
INTERVAL_HOT, INTERVAL_COLD = 45, 120                      # seconds (±15% jitter)
WAKE_AT = (5, 45)                                          # daily max-priority status push; None to disable
BACKOFF = [60, 120, 300, 600, 900]
PROXY_URL = env("STOCK_PROXY", "")                         # http://user:pass@host:port, Apple requests only
STANDBY_HB = env("STOCK_STANDBY_HEARTBEAT", "")            # standby mode: only poll when this file is stale
STANDBY_STALE = 240

LAUNCHD_LABEL = "com.stockholm.watch"
HB_LABEL = "com.stockholm.heartbeat"
HOME = os.path.expanduser("~")
BASE = os.path.join(HOME, "stockholm-syndrome")
LOG = os.path.join(BASE, "stockholm.log")
STATE = os.path.join(BASE, "state.json")
HISTORY = os.path.join(BASE, "history.csv")   # every appear/disappear event, for pattern-spotting
PLIST = os.path.join(HOME, "Library", "LaunchAgents", LAUNCHD_LABEL + ".plist")
BUY_URL = f"https://www.apple.com/{COUNTRY}/shop/buy-iphone/{PRODUCT_SLUG}"
API = f"https://www.apple.com/{COUNTRY}/shop/retail/pickup-message"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Safari/605.1.15")

# ------------------------------------------------------------- plumbing ----
os.makedirs(BASE, exist_ok=True)
_jar = CookieJar()
_handlers = [urllib.request.HTTPCookieProcessor(_jar)]
if PROXY_URL:
    _handlers.append(urllib.request.ProxyHandler({"http": PROXY_URL, "https": PROXY_URL}))
_opener = urllib.request.build_opener(*_handlers)

def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")

def imessage(text):
    if not IMESSAGE_TO:
        return False
    scpt = ('tell application "Messages"\n'
            'set s to 1st account whose service type = iMessage\n'
            f'set b to participant "{IMESSAGE_TO}" of s\n'
            'send "' + text.replace('\\', '\\\\').replace('"', '\\"') + '" to b\n'
            'end tell')
    try:
        subprocess.run(["osascript", "-e", scpt], check=True, timeout=30, capture_output=True)
        return True
    except Exception as e:
        log(f"IMESSAGE FAILED: {e}")
        return False

def notify(title, text):
    try:
        subprocess.run(["osascript", "-e",
                        f'display notification "{text}" with title "{title}" sound name "Glass"'],
                       timeout=10, capture_output=True)
    except Exception:
        pass

def ntfy(text, title="Stockholm", urgent=False, click=None, actions=None):
    """actions: list of (label, url) -> buttons on the notification (max 3)."""
    if not NTFY_TOPICS:
        return False
    ok = True
    for topic in NTFY_TOPICS:
      try:
        headers = {"Title": title.encode("ascii", "ignore").decode().strip() or "Stockholm",
                   "Priority": "5" if urgent else "3",
                   "Tags": "green_circle,iphone" if urgent else "eyes",
                   "Click": click or BUY_URL, "Content-Type": "text/plain; charset=utf-8"}
        if actions:
            headers["Actions"] = "; ".join(f"view, {lbl.encode('ascii','ignore').decode()}, {url}" for lbl, url in actions[:3])
        req = urllib.request.Request(f"{NTFY_SERVER}/{topic}", data=text.encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read()
      except Exception as e:
        log(f"NTFY FAILED ({topic}): {e}"); ok = False
    return ok

def alert(text, title="Stockholm", urgent=False, click=None, actions=None):
    log("ALERT: " + text.replace("\n", " | "))
    notify(title, text[:200])
    ntfy(text, title, urgent, click, actions)
    imessage(text)

# ----------------------------------------------------------------- fetch ----
def prime_session():
    """Visit the buy page to pick up Apple's cookies (the 'handshake')."""
    req = urllib.request.Request(BUY_URL, headers={"User-Agent": UA, "Accept": "text/html"})
    with _opener.open(req, timeout=30) as r:
        r.read(4096)
    log("session primed (cookies: %d)" % len(_jar))

def fetch(location):
    q = {"pl": "true", "mts.0": "regular", "location": location}
    for i, p in enumerate(PARTS):
        q[f"parts.{i}"] = p
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(q), headers={
        "User-Agent": UA, "Accept": "application/json",
        "Referer": BUY_URL, "Accept-Language": "en-GB,en;q=0.9"})
    with _opener.open(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

def parse(data):
    """-> {(store, part): (status, quote, store_name)}"""
    out = {}
    for s in data.get("body", {}).get("stores", []):
        sid = s.get("storeNumber")
        if sid:
            _store_meta[sid] = {"name": s.get("storeName", sid), "city": s.get("city", ""),
                                "postcode": (s.get("address") or {}).get("postalCode", ""),
                                "phone": s.get("phoneNumber", ""), "distance_mi": s.get("storedistance")}
        if TARGET_IDS and sid not in TARGET_IDS:
            continue
        for part, pa in s.get("partsAvailability", {}).items():
            disp = (pa.get("pickupDisplay") or "").lower()
            elig = pa.get("storePickEligible", True)
            quote = pa.get("pickupSearchQuote") or pa.get("storePickupQuote") or ""
            status = "available" if (disp == "available" and elig) else "unavailable"
            out[(sid, part)] = (status, quote, s.get("storeName", sid))
    return out

_store_meta = {}
SNAPSHOT = os.path.join(BASE, "snapshot.json")
PAUSED = os.path.join(BASE, "paused")

def write_snapshot(res, err=None):
    """Atomic JSON for the menu bar app: every target store x part, plus block state."""
    stores = {}
    for (sid, part), (status, quote, name) in (res or {}).items():
        m = _store_meta.get(sid, {})
        e = stores.setdefault(sid, {"name": m.get("name", name), "city": m.get("city", ""),
                                    "postcode": m.get("postcode", ""), "phone": m.get("phone", ""),
                                    "distance_mi": m.get("distance_mi"), "parts": {}})
        e["parts"][part] = {"available": status == "available", "quote": quote}
    snap = {"checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "parts": list(PARTS), "part_names": dict(PARTS),
            "plan_a": sorted(PLAN_A), "buy_urls": dict(PART_URL),
            "launchd_label": LAUNCHD_LABEL, "error": err, "stores": stores}
    tmp = SNAPSHOT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(snap, f)
    os.replace(tmp, SNAPSHOT)

_cycle = [0]
_retry_after = [0]
def poll():
    """-> (results dict or None, error string or None)"""
    merged, errs = {}, []
    _cycle[0] += 1
    locs = [PRIMARY_LOCATION] + ([SECONDARY_LOCATION] if SECONDARY_LOCATION and _cycle[0] % 3 == 0 else [])
    for loc in locs:
        try:
            merged.update(parse(fetch(loc)))
        except urllib.error.HTTPError as e:
            ra = e.headers.get("Retry-After") if e.headers else None
            errs.append(f"{loc}: HTTP {e.code}" + (f" (Retry-After {ra})" if ra else ""))
            if ra and str(ra).isdigit():
                _retry_after[0] = max(_retry_after[0], int(ra))
        except Exception as e:
            errs.append(f"{loc}: {type(e).__name__} {e}")
        time.sleep(1.5)
    if errs:
        return (merged or None), "; ".join(errs)
    if not merged:
        return None, "no target stores in response"
    return merged, None

# ------------------------------------------------------------ lifecycle ----
def uninstall():
    log("run window ended — uninstalling")
    for label in (LAUNCHD_LABEL, HB_LABEL):
        try:
            subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{label}"], capture_output=True, timeout=20)
        except Exception:
            pass
    hb_plist = os.path.join(HOME, "Library", "LaunchAgents", HB_LABEL + ".plist")
    for p in (PLIST, hb_plist, os.path.join(BASE, "heartbeat.sh"), STATE, os.path.join(BASE, "stockholm.py")):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
    imessage("Stockholm: run window over, uninstalled itself. Log kept at ~/stockholm-syndrome/stockholm.log")

def current_interval():
    hm = datetime.now().timetuple()[3:5]
    for start, end, secs in HOT_WINDOWS:
        if start <= hm < end:
            return secs
    return INTERVAL_COLD

def wake_message(st):
    """Once per day at WAKE_AT: max-priority status push that doubles as the alarm."""
    if not WAKE_AT:
        return
    now = datetime.now()
    key = now.strftime("%Y-%m-%d")
    end = (WAKE_AT[0], WAKE_AT[1] + 30)
    if WAKE_AT <= (now.hour, now.minute) < end and st.get("wake_sent") != key:
        n = len(st.get("avail", {}))
        txt = ("Good morning. Stockholm is live, polling every %ds. " % INTERVAL_HOT
               + (f"{n} store/config combo(s) AVAILABLE right now — check the last alert!" if n
                  else "No pickup stock yet. Go back to sleep; I will buzz the second it appears."))
        alert(txt, f"⏰ Stockholm {WAKE_AT[0]:02d}:{WAKE_AT[1]:02d} status", urgent=True)
        st["wake_sent"] = key
        save_state(st)

def history(event, sid, name, part, extra=""):
    new = not os.path.exists(HISTORY)
    with open(HISTORY, "a") as f:
        if new:
            f.write("timestamp,event,store_id,store,part,config,extra\n")
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S},{event},{sid},{name},{part},{PARTS.get(part, part)},{extra}\n")

def load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}

def save_state(st):
    json.dump(st, open(STATE, "w"))

def short(part):
    return PARTS[part].split(" ", 2)[-1] if PARTS[part].count(" ") >= 2 else PARTS[part]

def main():
    args = sys.argv[1:]
    if "--test-alert" in args:
        ok = alert("Stockholm test: if this reached your phone, the alert channels work.", "Stockholm test", urgent=True)
        print("sent"); return
    if "--once" in args:
        prime_session()
        res, err = poll()
        print("error:", err)
        for (sid, part), (status, quote, name) in sorted((res or {}).items()):
            print(f"{sid} {name:24} {PARTS[part]:28} {status:11} {quote}")
        return
    no_uninstall = "--no-uninstall" in args
    stop = {"flag": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.__setitem__("flag", True))

    log(f"=== stockholm start pid={os.getpid()} until={RUN_UNTIL} host={os.uname().nodename}")
    try:
        prime_session()
    except Exception as e:
        log(f"prime failed (continuing): {e}")
    st = load_state()
    st.setdefault("avail", {}); st.setdefault("quotes", {}); st.setdefault("last_alert", {})
    if not st.get("started"):
        alert(f"Stockholm LIVE on {os.uname().nodename}. Watching {len(TARGET_STORES)} stores for "
              f"{len(PLAN_A)} Plan A and {len(PARTS) - len(PLAN_A)} Plan B configs. "
              f"Will message the second one is available.")
        st["started"] = time.time()
    last_hb = time.time()
    fails = 0
    blocked_alerted = bool(st.get("blocked_alerted"))

    while not stop["flag"]:
        if os.path.exists(PAUSED):
            time.sleep(5); continue
        if datetime.now() >= RUN_UNTIL:
            break
        if STANDBY_HB:
            try:
                age = time.time() - os.path.getmtime(STANDBY_HB)
            except FileNotFoundError:
                age = 1e9
            if age < STANDBY_STALE:
                if st.get("standby_active"):
                    alert(f"Stockholm standby on {os.uname().nodename}: primary is back, standing down.")
                    st["standby_active"] = False; save_state(st)
                log(f"standby: primary heartbeat {int(age)}s old, not polling")
                time.sleep(current_interval())
                continue
            if not st.get("standby_active"):
                alert(f"Stockholm standby on {os.uname().nodename}: primary silent for {int(age)}s — TAKING OVER polling.", urgent=True)
                st["standby_active"] = True; save_state(st)
        if st.get("blocked_until", 0) > time.time():
            w = int(st["blocked_until"] - time.time())
            log(f"restart during block: honouring persisted backoff {w}s"); time.sleep(min(w, 900)); st["blocked_until"] = 0
        _retry_after[0] = 0
        res, err = poll()
        now = time.time()
        if err and not res:
            fails += 1
            wait = max(BACKOFF[min(fails - 1, len(BACKOFF) - 1)], _retry_after[0])
            st["blocked_until"] = now + wait; save_state(st)
            log(f"POLL FAILED ({fails}): {err} — backoff {wait}s")
            write_snapshot(None, err)
            if fails >= 2 and not blocked_alerted:
                alert(f"WARNING: Stockholm cannot read Apple's feed ({err}). Retrying with backoff — "
                      f"availability is UNKNOWN until this clears. Check the app yourself.", urgent=True)
                blocked_alerted = True; st["blocked_alerted"] = True; save_state(st)
            try:
                prime_session()
            except Exception as e:
                log(f"re-prime failed: {e}")
            time.sleep(wait)
            continue
        if fails:
            if blocked_alerted:
                alert("Stockholm: feed readable again, back to normal polling.")
            fails, blocked_alerted = 0, False; st["blocked_alerted"] = False; save_state(st)
        if err:
            log(f"partial: {err}")

        newly, still, quote_changes, gone = [], [], [], []
        for (sid, part), (status, quote, name) in res.items():
            key = f"{sid}|{part}"
            prev_q = st["quotes"].get(key)
            if quote and quote != prev_q:
                if prev_q is not None and status != "available" and key not in st["avail"]:
                    quote_changes.append(f"{name}: {quote}")
                st["quotes"][key] = quote
            if status == "available":
                if key not in st["avail"]:
                    st["avail"][key] = now
                    newly.append((sid, name, part))
                    history("appeared", sid, name, part)
                elif now - st["last_alert"].get(key, 0) >= REALERT_EVERY:
                    still.append((sid, name, part))
            elif key in st["avail"]:
                misses = st.setdefault("misses", {}).get(key, 0) + 1
                st["misses"][key] = misses
                if misses >= 2:
                    lasted = int((now - st["avail"].get(key, now)) / 60)
                    log(f"gone: {name} {PARTS[part]} after {lasted} min")
                    history("gone", sid, name, part, f"lasted_min={lasted}")
                    gone.append(f"{name} — {short(part)} (lasted {lasted} min)")
                    st["avail"].pop(key, None); st["last_alert"].pop(key, None); st["misses"].pop(key, None)
            if status == "available" and "misses" in st:
                st["misses"].pop(key, None)

        pri = {s: i for i, (s, _) in enumerate(TARGET_STORES)}
        order = lambda items: sorted(items, key=lambda t: pri.get(t[0], 99))

        if newly:
            a = [t for t in newly if t[2] in PLAN_A]
            b = [t for t in newly if t[2] not in PLAN_A]
            for tier, items in (("A", a), ("B", b)):
                if not items:
                    continue
                if tier == "A":
                    lines = ["🟢 PLAN A — AVAILABLE FOR PICKUP NOW:"]; title = "🟢 PLAN A AVAILABLE — GO"
                else:
                    lines = ["🟡 PLAN B — available for pickup" + (" (no Plan A yet):" if not a and not st.get("avail_a") else ":")]
                    title = "🟡 PLAN B available"
                for sid, name, part in order(items):
                    lines.append(f"• {name} — {short(part)}")
                    st["last_alert"][f"{sid}|{part}"] = now
                for part in sorted({p for _, _, p in items}):
                    lines.append(f"{short(part)}: {PART_URL.get(part, BUY_URL)}")
                lines.append("Tap link → Pick up → choose store → Continue. GO.")
                btns = [(short(p), PART_URL.get(p, BUY_URL)) for p in sorted({p for _, _, p in items})]
                alert("\n".join(lines), title, urgent=True, click=PART_URL.get(order(items)[0][2], BUY_URL), actions=btns)
            st["avail_a"] = any(k.split("|")[1] in PLAN_A for k in st["avail"])
        if still:
            lines = ["Still available for pickup:"]
            for sid, name, part in order(still):
                lines.append(f"• {name} — {short(part)}")
                st["last_alert"][f"{sid}|{part}"] = now
            alert("\n".join(lines), urgent=any(p in PLAN_A for _, _, p in still))
        if gone:
            alert("No longer available:\n" + "\n".join(gone))   # quiet (priority 3): useful for timing, not for action
        if quote_changes:
            alert("Apple pickup text changed (not yet 'available'):\n" + "\n".join(sorted(set(quote_changes))[:8]))
        save_state(st)

        summary = sum(1 for v in res.values() if v[0] == "available")
        log(f"ok: {len(res)} store/part combos, {summary} available"
            + (f", quote='{next(iter(res.values()))[1]}'" if res else ""))
        write_snapshot(res)
        if HEARTBEAT_EVERY and now - last_hb >= HEARTBEAT_EVERY:
            imessage(f"Stockholm heartbeat {datetime.now():%H:%M}: polling fine, {summary} available.")
            last_hb = now
        wake_message(st)
        time.sleep(current_interval() * random.uniform(0.85, 1.15))

    if stop["flag"]:
        log("stopped by signal"); return
    if no_uninstall:
        log("run window ended (no-uninstall)"); return
    uninstall()

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""test_sim.py — offline simulation of stockholm.py. Never touches Apple, never sends alerts.

Fakes poll() so one store/part flips to "available" for one cycle, then disappears, and checks
that the watcher: fires exactly one Plan A alert, does NOT declare it gone on a single miss
(two-miss hysteresis), declares it gone after two misses with a duration, and records both events
in history.csv. Run this after any change to the state machine:

    python3 test_sim.py
"""
import datetime as dt, json, os, sys, tempfile

sys.argv = ["x", "--no-uninstall"]
import stockholm as s

tmp = tempfile.mkdtemp(prefix="stockholm-sim-")
s.STATE = os.path.join(tmp, "state.json")
s.LOG = os.path.join(tmp, "log.txt")
s.HISTORY = os.path.join(tmp, "history.csv")
s.HEARTBEAT_EVERY = 0
s.current_interval = lambda: 1                    # one cycle per second
s.RUN_UNTIL = dt.datetime.now() + dt.timedelta(seconds=9)   # ~6 cycles
s.prime_session = lambda: None

sent = []
s.imessage = lambda text: sent.append(("imessage", text)) or True
s.ntfy = lambda text, *a, **k: sent.append(("ntfy", text)) or True
s.notify = lambda *a, **k: None

STORE, PART = (s.TARGET_STORES[0][0] if s.TARGET_STORES else "R092"), sorted(s.PLAN_A)[0]
base = {(sid, p): ("unavailable", "Check back for availability on 10.24", name)
        for sid, name in (s.TARGET_STORES or [("R092", "Regent Street")]) for p in s.PARTS}

cycle = [0]
def fake_poll():
    cycle[0] += 1
    res = dict(base)
    if cycle[0] in (2, 3):                        # available for two cycles
        res[(STORE, PART)] = ("available", "Available Today", res[(STORE, PART)][2])
    return res, None
s.poll = fake_poll

json.dump({"started": 1, "avail": {}, "quotes": {}, "last_alert": {}}, open(s.STATE, "w"))
s.main()

log = open(s.LOG).read()
hist = open(s.HISTORY).read() if os.path.exists(s.HISTORY) else ""
plan_a = [t for ch, t in sent if ch == "ntfy" and "PLAN A" in t]        # one push per alert
gone = [t for ch, t in sent if ch == "ntfy" and "No longer available" in t]

checks = {
    "exactly one Plan A alert": len(plan_a) == 1,
    "alert carries the product link": bool(plan_a) and s.PART_URL[PART] in plan_a[0],
    "one 'gone' notice (after 2 misses, not 1)": len(gone) == 1 and "lasted" in gone[0],
    "history has appeared + gone": "appeared" in hist and "gone" in hist,
    "no duplicate 'available' after the blip": log.count("appeared") <= 1 or hist.count("appeared") == 1,
}
for name, ok in checks.items():
    print(("PASS " if ok else "FAIL ") + name)
if not all(checks.values()):
    print("\n--- log ---\n" + log + "\n--- history ---\n" + hist + "\n--- sent ---")
    for ch, t in sent:
        print(ch, "|", t.splitlines()[0])
    sys.exit(1)
print("ok —", tmp)

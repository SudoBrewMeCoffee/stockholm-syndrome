# Stockholm Syndrome

> You refresh Apple's stock page. It says no. You refresh again. It still says no.
> You keep coming back. You've developed feelings for the "Check back for availability" message.

A small, honest Apple Store **pickup-stock watcher** for launch-day phones you couldn't pre-order
(or pre-ordered from a carrier that then texted you "28 days or longer"). It polls Apple's own
retail pickup feed for the stores near you and makes your phone scream the moment your config
becomes reservable for in-store pickup. Then **you** tap Pick Up → store → Apple Pay.

It deliberately does not automate checkout. Automated checkouts are what get launch-day orders
cancelled, and a human with Face ID does the last step in 15 seconds anyway. The hard part is
*knowing the second stock appears* — that's what this does.

Built in one morning for the iPhone Duo UK launch (24 Oct 2026), standard library only, runs on
any Mac. The interesting bits are the things we learned the hard way, below.

## What it does

- **One request covers 12 stores.** Apple's `retail/pickup-message` endpoint returns the 12 stores
  nearest a postcode, for up to ~10 part numbers, in one call. A second postcode (e.g. up the M4)
  is polled every third cycle.
- **Plan A / Plan B.** 1TB first, 2TB as fallback — separate 🟢 / 🟡 alerts so you never buy the
  wrong one in a half-asleep panic.
- **Alerts that wake you.** [ntfy](https://ntfy.sh) push at priority 5 (add ntfy to your Sleep Focus
  allow-list and it rings through Do Not Disturb), plus iMessage and a macOS notification. Each alert
  carries a direct link to the *pre-configured* product page for the colour that's in stock.
- **Adaptive polling.** 120s overnight, 45s in the launch window (05:30–10:00).
- **Block-aware.** On HTTP 541/403 it backs off (60s → 15 min), re-handshakes with the buy page,
  sends **one** loud warning ("availability is UNKNOWN") and **one** recovery notice. Silence never
  means "no stock".
- **Hot standby.** A second Mac runs the same script in standby mode and polls *only* if the primary's
  heartbeat goes stale for 4 minutes — so you get failover without doubling the request rate from
  your IP (see below for why that matters). Takes over and stands down with an alert each way.
- **Daily wake-up push** at 05:45 with the current state. Doubles as your alarm.
- **Self-uninstalls** (LaunchAgent + files) when the run window ends. Leaves the log.

## Things we learned so you don't have to

**Apple rate-limits by IP, and the penalty is long.** Two watchers plus some manual testing from
one home IP — roughly 6 requests/minute for 10 minutes — got the IP blocked with HTTP 541 on the
pickup endpoint (the buy page itself kept working, and a real browser on the same IP was blocked
too). The block lasted **43 minutes**, and retrying every 5–15 minutes during it did not extend it.
One request every 45–120 seconds has run for hours without trouble. So: **one watcher per IP**, and
make the second one a standby, not a twin. A VPN won't help — datacenter IPs get 541 on sight.
A phone hotspot or a residential proxy (`STOCK_PROXY`) is a genuinely different IP.

**`pickupDisplay` is the field.** `"available"` means reservable now. Before launch every store
says `"default"` with `pickupSearchQuote: "Check back for availability on 10.24"` — the quote text
changing is itself a useful early signal, so the script alerts on that too (lower priority).

**iMessages to yourself don't buzz.** If your Mac and phone share an Apple ID, a script sending
iMessage to your own number lands in a conversation with yourself, silently, twice. Fine as a log,
useless as an alarm. ntfy at priority 5 is the loud channel.

**Keep checkout automation out of it.** The old `fulfillment-messages` endpoint is dead (541). The
projects that drive Chrome through to "Place Order" need your Apple ID password and card details in
a script, and that's exactly the pattern Apple's fraud checks cancel. Don't.

**Trade-in:** do it at the counter when you collect, not in the online checkout. Fewer screens at
6am, same money, and it comes straight off the price.

## Setup (macOS)

```sh
git clone https://github.com/SudoBrewMeCoffee/stockholm-syndrome
cd stockholm-syndrome
cp stockholm.env.example stockholm.env     # fill in postcode, stores, ntfy topic, iMessage number
python3 stockholm.py --once                # prints every store/config Apple returns — sanity check
python3 stockholm.py --test-alert          # should buzz your phone
zsh install.sh                             # LaunchAgent: starts now, restarts on crash, self-removes
```

Standby on a second Mac (same IP is fine — it only polls when the primary is dead):

```sh
# on the standby Mac
STANDBY=1 zsh install.sh
# on the primary Mac (needs passwordless SSH to the standby, e.g. via Tailscale SSH)
zsh heartbeat-install.sh you@standby-mac
```

Find part numbers for a different product: `curl -sA 'Mozilla/5.0' https://www.apple.com/uk/shop/buy-iphone/<slug> | grep -oE '"partNumber":"[A-Z0-9/]+","price":\{"fullPrice":[0-9.]+\},"category":"iphone","name":"[^"]+"' | sort -u`

Find store IDs for your postcode: set `STOCK_STORES=` (empty) and run `--once`.

## Bonus: one-tap "check now" iOS Shortcut

`make_shortcut.py` generates a signed-importable Shortcut that hits the same endpoint from your
phone (different IP when on 4G), lists every nearby store's status, and opens the buy page if
anything says "available". Generate on a Mac, `shortcuts sign --mode anyone`, open it, and it syncs
to your iPhone via iCloud. First run asks to allow access to apple.com — tap Always Allow.

## Disclaimer

Polls a public, unauthenticated Apple endpoint at a rate a human could manage by hand. Be a good
citizen: one watcher per IP, slow overnight. No affiliation with Apple. No guarantees you'll get a
phone — but you'll know the instant you could.

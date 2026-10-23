#!/usr/bin/env python3
"""find_parts.py — print the part numbers (SKUs) Apple's buy page lists for a product.

  python3 find_parts.py iphone-duo            # UK by default
  python3 find_parts.py iphone-18-pro --country us

Paste the ones you want into PARTS / PLAN_A in stockholm.py. Part numbers differ per
country (UK ends QN/A, US LL/A). Run it on launch day too — new configs appear then.
Also prints the pre-configured product URL slug for each, for PART_URL.
"""
import re, sys, urllib.request

slug = next((a for a in sys.argv[1:] if not a.startswith("-")), "iphone-duo")
country = sys.argv[sys.argv.index("--country") + 1] if "--country" in sys.argv else "uk"
url = f"https://www.apple.com/{country}/shop/buy-iphone/{slug}"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                           "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"})
html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")

parts = {}
for m in re.finditer(r'"partNumber":"([A-Z0-9]+/A)","price":\{"fullPrice":([0-9.]+)\},"category":"[a-z]+","name":"([^"]+)"', html):
    parts.setdefault(m.group(1), (m.group(3), m.group(2)))
slugs = sorted(set(re.findall(rf'/{country}/shop/buy-iphone/{re.escape(slug)}/[a-z0-9.-]+', html)))

if not parts:
    sys.exit(f"no part numbers found at {url} — is the slug right?")
print(f"{'part':12} {'price':>9}  name")
for pn, (name, price) in sorted(parts.items(), key=lambda kv: (float(kv[1][1]), kv[1][0])):
    print(f"{pn:12} {price:>9}  {name}")
if slugs:
    print("\nproduct page URLs (for PART_URL):")
    for s in slugs:
        print("  https://www.apple.com" + s)

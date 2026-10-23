"""One-shot diagnostic for picks screener failures (not for merge)."""
import json, sys, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from probe_picks import _build_url, SCREENER_BASE
from playwright.sync_api import sync_playwright

cfg = json.loads(Path("data/picks/screener_config.json").read_text())
full = _build_url(cfg, "semiconductors")
cols = re.search(r"&c=([^&]+)", full).group(1)
V = {
 "full": full,
 "no_sort": full.replace("&o=-marketcap", ""),
 "no_52wh": full.replace("ta_highlow52w_a20h,", ""),
 "ind_only": f"{SCREENER_BASE}?v=151&f=ind_semiconductors&ft=4&c={cols}",
 "ind_only_v111": f"{SCREENER_BASE}?v=111&f=ind_semiconductors",
 "52wh_only_v111": f"{SCREENER_BASE}?v=111&f=ta_highlow52w_a20h",
 "cap_only_v111": f"{SCREENER_BASE}?v=111&f=cap_midover",
 "vol_only_v111": f"{SCREENER_BASE}?v=111&f=sh_avgvol_o100",
 "ticker_ctrl": f"{SCREENER_BASE}?v=151&t=NVDA,AMD&ft=4&c={cols}",
 "sort_only_v111": f"{SCREENER_BASE}?v=111&t=NVDA,AMD&o=-marketcap",
}
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36", ignore_https_errors=True)
    pg = ctx.new_page()
    for k, u in V.items():
        r = pg.goto(u, wait_until="domcontentloaded", timeout=30000)
        pg.wait_for_timeout(5000)
        h = pg.content()
        tables = sorted(set(re.findall(r'<table[^>]*class="([^"]+)"', h)))[:15]
        print(f"=== {k} status={r.status if r else None} final={pg.url[:200]}")
        print(f"  title={pg.title()!r} len={len(h)} has_screener_table={'screener_table' in h} rows={h.count('screener-body-table')}")
        print(f"  table classes: {tables}")
        txt = pg.inner_text("body")[:600].replace("\n", " | ")
        print(f"  body: {txt}")
        Path(f"data/picks/debug_html").mkdir(parents=True, exist_ok=True)
        Path(f"data/picks/debug_html/{k}.html").write_text(h)
    b.close()

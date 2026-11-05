"""Slim day tapes to what the replay needs, and print 1-min ATR% stats from the live scan rows."""
import json, statistics, sys
from pathlib import Path

INVERSE = {"SQQQ", "SPXU", "SDS", "SH", "PSQ", "TZA", "SOXS", "LABD", "QID", "DOG", "SPDN", "TECS", "FAZ", "SRTY"}
KEEP = {"top_volume_snapshot", "market_bar", "daily_universe_pick", "daily_universe_recheck"}
SCAN_KEYS = ("config", "top_volume_rows", "top_volume_source", "top_volume_symbols", "top_volume_updated_at", "symbol_source")
src, dst = Path(sys.argv[1]), Path(sys.argv[2])
atr_all, atr_inv, atr_by_sym = [], [], {}
with src.open() as fin, dst.open("w") as fout:
    for line in fin:
        e = json.loads(line)
        kind = e.get("kind")
        if kind == "strategy_scan":
            p = e["payload"]
            for row in p.get("strategy") or []:
                a = row.get("atr_raw")
                if a:
                    atr_all.append(a)
                    atr_by_sym.setdefault(row["symbol"], []).append(a)
                    if row["symbol"] in INVERSE:
                        atr_inv.append(a)
            e["payload"] = {k: p.get(k) for k in SCAN_KEYS}
        elif kind not in KEEP:
            continue
        fout.write(json.dumps(e, separators=(",", ":")) + "\n")
q = lambda xs: [round(x, 3) for x in statistics.quantiles(xs, n=10)] if len(xs) > 10 else xs
print(src.name, "ATR% deciles all:", q(atr_all))
print(src.name, "ATR% deciles inverse:", q(atr_inv))
med = {s: round(statistics.median(v), 3) for s, v in atr_by_sym.items() if s in INVERSE}
print(src.name, "inverse medians:", med)
print(src.name, "median of all symbols:", round(statistics.median(atr_all), 3))

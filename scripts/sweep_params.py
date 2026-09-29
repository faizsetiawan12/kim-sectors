"""Parameter sweep over cached LQ45 history (zero API credits).

Explores lookback / min-samples / top-k / rebalance-sessions across the cached
window and reports the full distribution, not just the winner. A best config
selected from many candidates on a short window is overfitted by construction,
so this reports how many combinations were profitable and how far the top
result sits from the median. Use scripts/sweep_holdout.py to check a chosen
config on data it was not tuned on.

Run from the repository root:
    python scripts/sweep_params.py
"""

from __future__ import annotations

import io
import itertools
import json
import statistics
import sys
from datetime import date, timezone as _tz
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kim_sectors.backtest import run_backtest
from kim_sectors.market_data.errors import CacheError
from kim_sectors.observability import configure_logging
from kim_sectors.paths import ensure_dirs

CACHE = Path("data/cache")
OUT = Path("output/sweep")
START = date(2026, 5, 1)
END = date(2026, 8, 7)

# Costs stay at realistic defaults: they describe the world, not the model.
# Tuning them would fit friction assumptions rather than the signal.
COST_BPS = 10
SLIPPAGE_BPS = 5

LOOKBACKS = [5, 10, 15, 21, 30, 40]
MIN_SAMPLES = [3, 5, 8]
TOP_K = [1, 2, 3, 5, 8, 10]
REBALANCE = [1, 2, 3, 5]

_SILENT = configure_logging(io.StringIO(), _tz.utc, event="sweep", name="sweep")


def run(lookback: int, samples: int, top_k: int, rebal: int) -> dict | None:
    """Replay one parameter combination; None when it cannot be evaluated."""
    try:
        report = run_backtest(
            index="lq45",
            start=START,
            end=END,
            lookback=lookback,
            min_samples=samples,
            top_k=top_k,
            rebalance_sessions=rebal,
            cost_bps=COST_BPS,
            slippage_bps=SLIPPAGE_BPS,
            cache_dir=CACHE,
            logger=_SILENT,
            today=END,
            timezone=_tz.utc,
        )
    except (ValueError, CacheError):
        return None
    if report.status != "ok":
        return None
    return {
        "lookback": lookback,
        "min_samples": samples,
        "top_k": top_k,
        "rebalance": rebal,
        "total_return": report.total_return,
        "benchmark": report.benchmark.total_return if report.benchmark else None,
        "trades": report.trades,
        "win_rate": report.win_rate,
        "max_drawdown": report.max_drawdown,
        "rebalances": report.rebalances,
    }


def main() -> int:
    ensure_dirs(cache_dir=CACHE, output_dir=OUT)
    rows = [
        row
        for row in (
            run(lb, ms, k, rb)
            for lb, ms, k, rb in itertools.product(
                LOOKBACKS, MIN_SAMPLES, TOP_K, REBALANCE
            )
        )
        if row is not None
    ]
    if not rows:
        print("no combination could be evaluated; check cache coverage")
        return 1

    rows.sort(key=lambda r: r["total_return"], reverse=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(rows, indent=2))

    rets = [r["total_return"] for r in rows]
    wins = [r for r in rows if r["total_return"] > 0]
    beats = [
        r
        for r in rows
        if r["benchmark"] is not None and r["total_return"] > r["benchmark"]
    ]
    print(f"combinations evaluated : {len(rows)}")
    print(f"profitable             : {len(wins)} ({100*len(wins)/len(rows):.1f}%)")
    print(f"beat the benchmark     : {len(beats)} ({100*len(beats)/len(rows):.1f}%)")
    print(f"median return          : {statistics.median(rets):.4f}")
    print(f"best / worst           : {max(rets):.4f} / {min(rets):.4f}")
    print(f"rebalances in best run : {rows[0]['rebalances']}")
    print("\ntop 15 by total return:")
    print(f"{'lb':>3} {'ms':>3} {'k':>3} {'reb':>4} {'return':>9} {'bench':>8} {'trades':>7} {'win':>6}")
    for r in rows[:15]:
        bench = f"{r['benchmark']:.4f}" if r["benchmark"] is not None else "   n/a"
        print(
            f"{r['lookback']:>3} {r['min_samples']:>3} {r['top_k']:>3} {r['rebalance']:>4} "
            f"{r['total_return']:>9.4f} {bench:>8} {r['trades']:>7} {r['win_rate']:>6.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

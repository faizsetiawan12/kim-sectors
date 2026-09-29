"""Out-of-sample check for a configuration chosen by scripts/sweep_params.py.

Selecting the best of many combinations on one window rewards luck. This
replays a chosen configuration on a later window it was not tuned on, which is
the only way to tell a real edge from an overfitted winner.

Usage from the repository root:
    python scripts/sweep_holdout.py --lookback 15 --top-k 3 --rebalance 2 \
        --min-samples 5 --tune-end 2026-07-15

The tuning window ends at --tune-end; the holdout window is everything after
it. Both windows read the same cache and cost zero API credits.
"""

from __future__ import annotations

import io
import json
from datetime import date, timezone as _tz
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kim_sectors.backtest import run_backtest
from kim_sectors.observability import configure_logging
from kim_sectors.paths import ensure_dirs

CACHE = Path("data/cache")
START = date(2026, 5, 1)
COST_BPS = 10
SLIPPAGE_BPS = 5
_SILENT = configure_logging(io.StringIO(), _tz.utc, event="holdout", name="holdout")


def replay(start: date, end: date, *, lookback: int, samples: int, top_k: int, rebal: int) -> dict | None:
    """Replay one window; None when the window cannot be evaluated."""
    try:
        report = run_backtest(
            index="lq45",
            start=start,
            end=end,
            lookback=lookback,
            min_samples=samples,
            top_k=top_k,
            rebalance_sessions=rebal,
            cost_bps=COST_BPS,
            slippage_bps=SLIPPAGE_BPS,
            cache_dir=CACHE,
            logger=_SILENT,
            today=date(2026, 8, 7),
            timezone=_tz.utc,
        )
    except Exception as error:  # coverage gaps are informative, not fatal
        return {"error": str(error)}
    if report.status != "ok":
        return {"error": f"status={report.status}"}
    return {
        "total_return": report.total_return,
        "benchmark": report.benchmark.total_return if report.benchmark else None,
        "rebalances": report.rebalances,
        "trades": report.trades,
        "win_rate": report.win_rate,
        "max_drawdown": report.max_drawdown,
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lookback", type=int, required=True)
    parser.add_argument("--min-samples", type=int, default=5)
    parser.add_argument("--top-k", type=int, required=True)
    parser.add_argument("--rebalance", type=int, required=True)
    parser.add_argument("--tune-end", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 8, 7))
    args = parser.parse_args()

    ensure_dirs(cache_dir=CACHE, output_dir=Path("output/sweep"))

    params = {
        "lookback": args.lookback,
        "samples": args.min_samples,
        "top_k": args.top_k,
        "rebal": args.rebalance,
    }
    tune = replay(START, args.tune_end, **params)
    holdout = replay(
        date.fromordinal(args.tune_end.toordinal() + 1), args.end, **params
    )

    print(f"config: lookback={args.lookback} min_samples={args.min_samples} "
          f"top_k={args.top_k} rebalance={args.rebalance}")
    print(f"tuning   {START} -> {args.tune_end}: {json.dumps(tune)}")
    print(f"holdout  {args.tune_end} +1d -> {args.end}: {json.dumps(holdout)}")

    if tune and holdout and "error" not in tune and "error" not in holdout:
        survived = holdout["total_return"] > 0
        beat = (
            holdout["benchmark"] is not None
            and holdout["total_return"] > holdout["benchmark"]
        )
        print(f"\nholdout profitable: {survived}   beat benchmark: {beat}")
        if survived:
            print("Result is consistent with a real edge over this holdout.")
        else:
            print("Result did not survive. Treat the tuning-window winner as noise.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

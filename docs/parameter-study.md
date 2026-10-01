# Parameter Study — LQ45 Momentum × Broker EV

## Purpose

Answer one question: *does this strategy have a validated edge, or did parameter
search merely find a configuration that fit this particular window?*

Everything here runs from the Data Cache and costs **zero API credits**, so the
study is reproducible by anyone with the cache.

## Method

1. **Sweep** — replay 80 configurations over 2026-05-04 → 2026-08-07 (64 IDX
   trading days). Knobs: `lookback` ∈ {5,10,21,30,40}, `top_k` ∈ {1,3,5,10},
   `rebalance_sessions` ∈ {1,2,5,10}. `min_samples` fixed at 5.
2. **Rank** — select the highest total-return configuration.
3. **Hold out** — replay *that* configuration on 2026-07-11 → 2026-08-07, which
   it was never tuned on.

Trading costs are pinned at 10 bps commission + 5 bps slippage in both scripts.
They describe the world rather than the model, so tuning them would fit friction
assumptions instead of the signal.

Reproduce with:

```bash
python scripts/sweep_params.py
python scripts/sweep_holdout.py --lookback 10 --top-k 1 --rebalance 10 \
    --min-samples 5 --tune-end 2026-07-10
```

## Sweep result

| Metric | Value |
|---|---|
| Combinations evaluated | 80 |
| Profitable | 70 (87.5%) |
| Beat the benchmark | 77 (96.2%) |
| Median return | +13.9% |
| Best / worst | +78.0% / −17.3% |
| Benchmark (LQ45 buy-and-hold) | **−10.1%** |

Best configuration: `lookback=10, top_k=1, rebalance_sessions=10` → **+78.0%**,
11 trades.

## Holdout result — the winner fails

| Window | Strategy | Benchmark |
|---|---|---|
| Tuning (05-04 → 07-10) | **+60.6%** | −18.5% |
| **Holdout (07-11 → 08-07)** | **−0.24%** | **+9.1%** |

The configuration that returned +78% across the full window lost 0.24% on data
it had never seen, while the index rose 9.1% over the same holdout.

**Verdict: the apparent edge is overfitting.** 80 configurations were selected
against the same window the winner was then measured on, so the top result
measures selection as much as signal.

Two structural signals in the sweep confirm it:

- `top_k=1` accounts for 6 of the top 10 results. Concentrating on one ticker
  makes luck the dominant term.
- The benchmark is negative, so **holding cash (0%) would have beaten 79 of the
  80 configurations.** "Beat the benchmark" is a weak claim in a falling market.

## What this does and does not establish

**Not established:** any claim that the strategy is profitable. The best
configuration available to us does not survive out-of-sample.

**Established:** the pipeline is reproducible and the ranking is point-in-time —
end-of-day signals enter at the *next* session close, and broker-EV observations
only use outcomes observable by the signal date. A +60% in-sample number that
fails on holdout is the expected signature of a correctly-implemented replay
with no real edge, not of broken mechanics.

This result is the reason the study exists. A reported +78% would have been the
more attractive number and the less honest one.

## Note on universe membership

LQ45 membership is resolved from Sectors as a *current* snapshot and dated from
the start of the fetched window. Real LQ45 membership changes quarterly, so
replays spanning several months approximate historical membership with the
current list. This does not introduce look-ahead into prices or broker outcomes,
but membership reconstitution is approximate over long windows.
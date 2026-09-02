# KIM Sectors Domain Context

KIM Sectors is KIM's automated IDX market-intelligence workflow for the Sectors Hackathon 2026 Automation & Workflows track.

## Core terms

- **Universe**: The selected set of IDX securities analyzed by the workflow; LQ45 is the default.
- **Momentum**: The percentage return over a configurable trailing number of trading days, monthly by default.
- **Broker EV**: Raw next-day expected value estimated from historical Sectors broker-summary observations.
- **Signal score**: The product of momentum and broker EV; candidates are ranked by this value.
- **Daily market brief**: The post-market Markdown/JSON report sent to Telegram.
- **Backtest run**: A point-in-time replay of the signal and portfolio rules over historical data.
- **Pipeline**: The automated process that fetches, validates, scores, reports, and notifies.
- **Sectors tracer**: A small live-data check that authenticates through a representative fetch, validates the response schema, and records structured stages.
- **Data cache**: Local persisted Sectors responses reused by backtests and later runs to avoid repeated API calls.

## Boundaries

KIM Sectors provides research and decision support only. It does not authenticate with brokers, place orders, execute trades, or automate buy/sell decisions on live accounts.

## Data integrity

- Sectors API is the core market-data source.
- Signal inputs available at time T must not use data after T.
- End-of-day signals are entered at the next eligible market session in backtests.
- Market timestamps use `Asia/Jakarta` (WIB).
- API and validation failures must be visible; no silent repair or dropped rows.

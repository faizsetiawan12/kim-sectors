# ADR-0001: Single-Repository Modular Architecture

- **Status:** Accepted
- **Date:** 2026-09-02

## Context

KIM Sectors is one Python application for the Sectors Hackathon 2026 Automation & Workflows track. It has one primary workflow, one Backtest Run, one Sectors data source, and one Telegram output. The project needs clear seams for testing and future growth, but it does not yet contain multiple independently deployed applications or separately released packages.

## Decision

KIM Sectors will use one Git repository containing one modular Python application. It will not use a monorepo structure with multiple applications or packages at this stage.

The application will organize behavior around deep modules with small interfaces:

- **Market data** hides Sectors HTTP, authentication, pagination, validation, normalization, cache coverage, provenance, and credit estimation.
- **Strategy** calculates Momentum, raw Broker EV, eligibility, and the composite Signal Score.
- **Backtest** performs point-in-time historical replay, next-session entry, rebalancing, costs, and metrics.
- **Workflow** orchestrates the daily sequence from data synchronization through reporting.
- **Outputs** generates Markdown/JSON artifacts and adapts results to Telegram.

The primary external seams are:

1. A market-data seam with a live Sectors adapter and controlled test adapter.
2. A notification seam with a Telegram adapter and controlled test recorder.

`main.py` remains a thin command interface. It parses commands, loads configuration, invokes the appropriate module, and reports success or failure. It does not contain market-data, scoring, caching, reporting, or Backtest Run implementation details.

## Consequences

### Positive

- One repository, runtime, dependency set, and release path keep the competition MVP easy to operate.
- Shared interfaces allow the Daily Pipeline and Backtest Run to use the same scoring behavior.
- Deep modules provide leverage for callers and locality for maintainers.
- External adapters make command-level tests possible without network calls, API credits, or Telegram delivery.
- Future factors and Universes can be added without changing the portfolio simulation interface.

### Negative

- The initial strategy module may contain more than one factor implementation until the factor family becomes large enough to justify further separation.
- A future split into independently deployed applications would require an intentional architecture change.
- Local cache files and generated reports remain operational concerns of this application rather than independently managed packages.

## Alternatives considered

### Monorepo

Rejected for the initial release. A monorepo is useful when one repository contains multiple independently managed applications or packages. KIM Sectors currently has one application, so the additional workspace, dependency, test, and release complexity would not provide meaningful leverage.

### Multiple repositories

Rejected because the Daily Pipeline, Backtest Run, strategy, and reporting capabilities need coordinated changes and share one release. Splitting them now would create versioning and integration overhead.

### Flat script collection

Rejected because it would spread Sectors authentication, cache behavior, scoring rules, and timing assumptions across commands, reducing locality and making point-in-time testing harder.

## Revisit conditions

Reconsider this decision when KIM has multiple independently deployed applications, independently released reusable packages, separate ownership boundaries, or a demonstrated need for coordinated multi-application tooling.

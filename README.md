# Sports Betting Research Bot

An evidence-first sports research platform for analyzing player props and market context. It does not guarantee outcomes or replace official injury/lineup verification.

## What is included

- RSS news, Reddit, and optional X API v2 ingestion; source data is persisted and deduplicated.
- Explainable evidence extraction for injuries, lineups, weather, and market chatter with source reliability and contradiction tracking.
- A multi-agent-style research orchestration workflow: collection, classification, skeptical evidence review, and synthesis.
- Monte Carlo prop distributions, no-vig market probabilities, expected value, line-movement summaries, confidence/edge scores, and correlation-aware parlay math.
- Database audit tables for evidence, model runs, pick settlement, and parlay candidates; daily scheduler jobs and a new Streamlit research/learning tab.
- Post-game settlement, ROI, hit-rate, and Brier-score calibration helpers.

## Setup

1. Copy `.env.example` to `.env`; never commit the latter.
2. Configure PostgreSQL and run `python database/migrate.py`.
3. Run `python scheduler/scheduler.py` and `streamlit run dashboard/app.py`.

X is optional: without `TWITTER_BEARER_TOKEN`, ingestion returns no X records without failing the job. AI defaults to `heuristic`, which is deterministic and auditable. Keep `MIN_EDGE_PROBABILITY` conservative and evaluate models using settled outcomes before acting on any signal.

## Validation

Run `pytest -q` to validate the core research math and rules.

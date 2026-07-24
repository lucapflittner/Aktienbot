# Idea backlog (SOTA-informed)

Grounded in a literature scan done when this skill was set up (HRP,
volatility targeting, LSTM+risk-budgeting, CVaR risk parity — see sources at
the bottom). Treat this as a prioritized menu for Phase 2 (Ideate), not a
script — check `results.tsv` before picking one so you don't repeat a
discarded change. Update this file when a tier is exhausted.

## Tier 1 — position sizing (biggest lever; the baseline equal-weights picks
that differ hugely in volatility and correlation)

- [ ] `weighting="inverse_vol"` — cheap first step, should reduce vol on the
      more-volatile picks without needing a covariance matrix.
- [ ] `weighting="hrp"` — Hierarchical Risk Parity (already implemented in
      `quant_bot/weighting.hrp_weight`); literature reports ~18% Sharpe
      uplift over equal-weight on similar universes. Try varying the
      lookback window used to build `hist_returns` in `backtest.py` (currently
      126 trading days) — shorter may adapt faster to regime shifts, longer
      may reduce estimation noise.
- [ ] Combine: HRP for intra-basket weights + `vol_target` overlay for
      basket-level leverage (both can be on at once).

## Tier 2 — volatility targeting overlay

- [ ] `vol_target=0.15` (or sweep 0.10-0.20) with the existing
      `volatility_target_scale` — literature shows Sharpe gains concentrated
      in momentum-style strategies specifically (this bot picks
      momentum-heavy features), but real-time performance sometimes lags
      in-sample results — verify out-of-sample on the 2018-2026 window, don't
      trust an in-sample-only read.
  - [ ] sweep `vol_target_lookback` (63 vs 21 vs 126 days) — shorter reacts
        faster to vol spikes (e.g. 2020, 2022) but noisier.
  - [ ] `max_leverage` in `volatility_target_scale` is hardcoded to 1.5 —
        try 1.0 (never lever up, only delever) as a lower-variance variant.

## Tier 3 — model / label

- [ ] `rank_objective=True` — switches to `XGBRanker` with cross-sectional
      rank labels instead of point regression. Ranking who's relatively
      better this month is arguably an easier, lower-variance learning
      problem than predicting the exact forward return.
- [ ] Sweep `label_horizon_days` (10, 21, 42, 63) — current 21-day (~1
      month) forward return may not match the model's actual holding period
      well if rebalancing logic changes.
- [ ] Sweep `train_window_years` (2, 3, 5) — shorter adapts faster to regime
      change, longer gives the model more rows per fit.
- [ ] Ensemble: average predictions from 2-3 XGBoost seeds/hyperparameter
      variants before ranking — reduces variance in the picks, may reduce
      turnover too.

## Tier 4 — universe / selection

- [ ] Sweep `top_n` (5, 10, 15, 20) — smaller is more concentrated
      (potentially higher return, higher vol); larger is more diversified
      but dilutes the model's edge.
- [ ] Add a low-volatility or quality tilt as an additional feature in
      `features.py` (e.g. earnings-quality proxy, debt/equity if a
      fundamentals source is added later) — momentum-only cross-sections can
      crowd into the same crash-prone names.
- [ ] Regime filter: compute a broad-market trend signal (e.g. S&P 500
      itself vs its 200-day SMA) and reduce `top_n` / move partially to cash
      when the market is below its long-term trend — a simple, well-studied
      way to cut drawdowns without touching the stock-picking model at all.

## Tier 5 — costs / turnover

- [ ] Sweep `transaction_cost_bps` sensitivity (5, 10, 20) — confirms
      whether reported gains survive realistic cost assumptions; don't chase
      a Sharpe win that only exists at 0 bps.
- [ ] Add a turnover penalty/hysteresis: only replace a held name if a new
      candidate's predicted rank beats it by a margin, instead of always
      taking the literal top-N — should lower `avg_turnover` at little
      Sharpe cost.

## Tier 6 — radical (use when stuck after 5+ discards)

- [ ] Replace point-in-time top-N selection with a continuous rank-weighted
      long-only book (weight proportional to predicted rank across the
      *entire* investable universe, not just top-N) — changes the problem
      from "pick 10 winners" to "tilt the whole index."
- [ ] Try a completely different model family for the ranking step (e.g.
      LightGBM, or a simple linear factor model) as a sanity check that
      XGBoost itself isn't the bottleneck.
- [ ] Bootstrap/purged walk-forward CV within each training window (instead
      of a single train/val split in `train_model`) to get a more robust
      hyperparameter choice before the monthly refit.

## Sources consulted (2026 literature scan)

- Hierarchical Risk Parity — QuantPedia: https://quantpedia.com/hierarchical-risk-parity/
- ML-based risk asset allocation — Scientific Reports: https://www.nature.com/articles/s41598-025-26337-x
- RL-embedded Bayesian HRP: https://arxiv.org/pdf/2508.11856
- Mean-Variance vs HRP vs RL comparison (Indian market): https://arxiv.org/pdf/2305.17523
- Volatility targeting impact — Man Group: https://www.man.com/insights/the-impact-of-volatility-targeting
- Volatility-managed portfolios — Alpha Architect: https://alphaarchitect.com/the-performance-of-volatility-managed-portfolios/
- Volatility targeting on equities/bonds/commodities/FX — QuantPedia: https://quantpedia.com/the-impact-of-volatility-targeting-on-equities-bonds-commodities-and-currencies/

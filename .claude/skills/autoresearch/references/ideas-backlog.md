# Idea backlog (SOTA-informed)

Grounded in a literature scan done when this skill was set up (HRP,
volatility targeting, LSTM+risk-budgeting, CVaR risk parity — see sources at
the bottom). Treat this as a prioritized menu for Phase 2 (Ideate), not a
script — check `results.tsv` before picking one so you don't repeat a
discarded change. Update this file when a tier is exhausted.

## Tier 1 — position sizing (biggest lever; the baseline equal-weights picks
that differ hugely in volatility and correlation)

- [x] `weighting="inverse_vol"` — **kept** (iteration 1, Sharpe 0.6515→0.6578).
- [x] `weighting="hrp"` — **discarded** (iteration 2, Sharpe 0.5536): underperforms
      on this small N=10 basket, likely overfits noisy correlation clustering.
- [ ] Combine: HRP for intra-basket weights + `vol_target` overlay for
      basket-level leverage (both can be on at once). Still untried — note HRP
      alone already lost, so this is a lower-priority combo now.

## Tier 2 — volatility targeting overlay

- [x] `vol_target=0.15` @ lookback=63/max_leverage=1.5 — **discarded** (iteration 3,
      Sharpe 0.2722): reactive vol-scaling levers up right before crashes.
- [x] `vol_target=0.15` @ lookback=21 (faster reaction) + `max_leverage=1.0`
      (delever-only, never lever up) — **discarded** (iteration 8, Sharpe 0.2817):
      still crushes CAGR; cutting exposure during profitable-but-volatile periods
      hurts more than crash-avoidance helps, in this universe/period. Both obvious
      variants of vol-targeting have now failed — deprioritize this whole tier
      unless a fundamentally different implementation is proposed (e.g. targeting
      *downside* vol only, not full vol).

## Tier 3 — model / label

- [x] `rank_objective=True` (XGBRanker) — **discarded twice**: iteration 4
      (Sharpe 0.6016 vs kept baseline 0.6578) and again re-tested against the
      current best baseline — worse both times, deeper drawdown too. Stop
      retrying this without a structurally different ranking approach.
- [x] Sweep `label_horizon_days` — **42 days is a big keep** (iteration 5,
      Sharpe 0.6578→1.1126, CAGR 15.7%→35.0%, MaxDD also improved to -24.0%).
      This is now the baseline. Still untried: 10, 63 days — worth sweeping
      further around 42 (e.g. 35, 50) since the jump from 21→42 was large.
- [x] Sweep `train_window_years` — 5 alone (vs old baseline) looked good in
      isolation (Sharpe 0.87) but **discarded in combination with the new
      label_horizon=42 baseline** (iteration 6, Sharpe 0.8341 < 1.1126) — doesn't
      stack. 2 years still untried against the label_horizon=42 baseline.
- [x] Ensemble of XGBoost seeds — **discarded** (iteration 10): identical to
      single-model baseline because `subsample`/`colsample_bytree` aren't
      configured, so `random_state` has zero effect — tree construction is fully
      deterministic. If retried, must first add row/column subsampling to create
      actual variance across seeds, otherwise it's a no-op by construction.
- [ ] LightGBM swap — **blocked, not actually tested**: this conda env's
      lightgbm 4.7.0 install crashes with a native access-violation even on a
      minimal standalone fit() outside project code (iteration 11/crash). Needs
      `pip install --force-reinstall lightgbm` or a conda-forge reinstall before
      this idea can be evaluated at all.
- [ ] sklearn MLPRegressor swap — **not actually tested**: fails regression_check
      (7/10) because MLPRegressor can't handle the NaNs XGBoost tolerates
      natively (iteration 12/discard-regression). Would need a NaN imputer added
      to the pipeline first (e.g. `SimpleImputer` before `StandardScaler`).

## Tier 4 — universe / selection

- [x] Sweep `top_n` — 15 alone (vs old baseline) looked good in isolation
      (Sharpe 0.83) but **discarded in combination with label_horizon=42**
      (iteration 7, Sharpe 0.9835 < 1.1126) — same non-stacking pattern as
      train_window. 5 and 20 still untried against the label_horizon=42 baseline.
- [ ] Add a low-volatility or quality tilt as an additional feature in
      `features.py` (e.g. earnings-quality proxy, debt/equity if a
      fundamentals source is added later) — momentum-only cross-sections can
      crowd into the same crash-prone names.
- [x] Regime filter (equal-weighted universe proxy vs its 200d SMA,
      halve exposure below trend) — **discarded** (iteration 9, Sharpe 0.4826):
      the proxy is noisy/whipsaw-prone, hurt both Sharpe and max drawdown. A
      real S&P 500 index series (not a same-universe proxy) might behave
      differently but isn't in the local dataset.

## Tier 5 — costs / turnover

- [ ] Sweep `transaction_cost_bps` sensitivity (5, 10, 20) — confirms
      whether reported gains survive realistic cost assumptions; don't chase
      a Sharpe win that only exists at 0 bps.
- [x] Turnover hysteresis (keep a held name unless its rank falls outside
      top_n+5) — **discarded** (iteration 13, Sharpe 0.6348 vs old baseline
      0.6578): also didn't meaningfully reduce avg_turnover as hoped. Untried
      against the current label_horizon=42 baseline, and untried with a smaller
      buffer (e.g. +2/+3) which might behave differently.

## Tier 6 — radical (use when stuck after 5+ discards)

- [ ] Replace point-in-time top-N selection with a continuous rank-weighted
      long-only book (weight proportional to predicted rank across the
      *entire* investable universe, not just top-N) — changes the problem
      from "pick 10 winners" to "tilt the whole index." Still untried.
- [ ] Try a completely different model family for the ranking step —
      LightGBM is blocked by a broken env install (see Tier 3); CatBoost isn't
      installed either. A simple linear/ElasticNet factor model as a sanity
      check that XGBoost itself isn't the bottleneck is still untried and needs
      no new dependency.
- [ ] Bootstrap/purged walk-forward CV within each training window (instead
      of a single train/val split in `train_model`) to get a more robust
      hyperparameter choice before the monthly refit. Still untried.

## Tier 7 — new price-only factors (2026 literature scan, close-price-only
constraint — this dataset has no volume/fundamentals/sector data)

- [x] `pth_52wk` (52-week-high proximity, George & Hwang 2004) — **discarded**
      (iteration 14, Sharpe 0.4725): hurt performance in this universe/period
      despite solid academic backing elsewhere — a reminder that a real citation
      doesn't guarantee it transfers to this specific small-basket, cost-aware
      setup. Don't re-add this exact feature without a different angle (e.g.
      interacting it with momentum rather than adding it as a standalone column).
- [ ] MAX effect (max daily return in trailing ~21 days; Bali, Cakici & Whitelaw
      2011) — untried. Cross-sectionally *negative* predictor (lottery-demand
      anomaly) — implement as a new feature in `engineer_features`, e.g.
      `daily.rolling(21).max()`, and let the model learn the sign itself (it's
      cross-sectionally z-scored anyway).
- [ ] Idiosyncratic volatility vs. an equal-weighted universe proxy (Ang, Hodrick,
      Xing & Zhang 2006) — untried, more implementation effort (needs a rolling
      regression per ticker against the same-universe proxy) and per Bali et al.
      2011 is highly correlated with/subsumed by the MAX effect above — try MAX
      first since it's simpler and may capture most of the same signal.

## Sources consulted (2026 literature scan)

- Hierarchical Risk Parity — QuantPedia: https://quantpedia.com/hierarchical-risk-parity/
- ML-based risk asset allocation — Scientific Reports: https://www.nature.com/articles/s41598-025-26337-x
- RL-embedded Bayesian HRP: https://arxiv.org/pdf/2508.11856
- Mean-Variance vs HRP vs RL comparison (Indian market): https://arxiv.org/pdf/2305.17523
- Volatility targeting impact — Man Group: https://www.man.com/insights/the-impact-of-volatility-targeting
- Volatility-managed portfolios — Alpha Architect: https://alphaarchitect.com/the-performance-of-volatility-managed-portfolios/
- Volatility targeting on equities/bonds/commodities/FX — QuantPedia: https://quantpedia.com/the-impact-of-volatility-targeting-on-equities-bonds-commodities-and-currencies/
- 52-week high anomaly — George & Hwang (2004), Journal of Finance: https://www.bauer.uh.edu/tgeorge/papers/GHL-52WHQ.pdf
- MAX effect — Bali, Cakici & Whitelaw (2011), NBER WP 14804: https://www.nber.org/system/files/working_papers/w14804/w14804.pdf
- Idiosyncratic volatility puzzle — Ang, Hodrick, Xing & Zhang (2006), NBER WP 10852: https://www.nber.org/papers/w10852

## Sources consulted (2026 literature scan)

- Hierarchical Risk Parity — QuantPedia: https://quantpedia.com/hierarchical-risk-parity/
- ML-based risk asset allocation — Scientific Reports: https://www.nature.com/articles/s41598-025-26337-x
- RL-embedded Bayesian HRP: https://arxiv.org/pdf/2508.11856
- Mean-Variance vs HRP vs RL comparison (Indian market): https://arxiv.org/pdf/2305.17523
- Volatility targeting impact — Man Group: https://www.man.com/insights/the-impact-of-volatility-targeting
- Volatility-managed portfolios — Alpha Architect: https://alphaarchitect.com/the-performance-of-volatility-managed-portfolios/
- Volatility targeting on equities/bonds/commodities/FX — QuantPedia: https://quantpedia.com/the-impact-of-volatility-targeting-on-equities-bonds-commodities-and-currencies/

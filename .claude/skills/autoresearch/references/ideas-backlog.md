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
- [x] Combine: HRP + `vol_target=0.15` (both original defaults) — **discard**:
      Sharpe 0.5168, now underperforms even buy&hold. The two individually-failed
      ideas stack rather than cancel — don't retry this combo in any variant.

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
      Confirmed as a local optimum: 35 (iteration 16, Sharpe 0.9665) and 50
      (iteration 17, Sharpe 0.9802) both underperform 42 against the
      cost-realistic baseline. Still untried: 10, 63 (further out); a finer
      grid around 38-45 could still exist but returns are likely diminishing.
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

- [x] Sweep `top_n` fully resolved: 15 and 20 both **discarded** against the
      label_horizon=42 baseline (dilutes conviction). **top_n=5 is a big keep**
      (iteration 18, Sharpe 1.0904→1.2129, CAGR 34%→48%) — but MaxDD deepened
      substantially (-24.3%→-32.6%) and annual_vol rose to 38.5%. This is now
      the baseline, with a real risk-tolerance tradeoff flagged to the user —
      not a free lunch. Turnover hysteresis (buffer=2) combined with top_n=5
      was tried and made Sharpe slightly worse (1.1986), though it did reduce
      MaxDD and turnover a bit — a secondary risk/return tradeoff worth
      revisiting if the user prioritizes drawdown over raw Sharpe.
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

- [x] Replaced the pure `transaction_cost_bps`-of-turnover assumption with a
      realistic composite (iteration 15, **keep** — this is a correctness fix,
      not an alpha experiment, adopted regardless of its Sharpe effect):
      `spread_bps=7.5` (proportional, same mechanism as before) **+** a flat
      `flat_fee_per_trade_eur=1.0` per buy/sell order, sized against a tracked,
      compounding `capital_eur=10_000` starting balance. Effect on the
      label_horizon=42 baseline was small (Sharpe 1.1126→1.0904) because
      capital compounds fast at this CAGR; the same fee model costs
      proportionally more on lower-return configs (e.g. the old label_horizon=21
      setup lost 0.6578→0.6150) since the fixed fee stays relatively larger for
      longer when capital grows slower. **Caveat:** `num_trades` currently
      counts every name with *any* nonzero weight change (threshold 1e-6) as a
      full trade, including tiny inverse-vol reweighting drift on continuing
      holdings — a real trader likely wouldn't re-trade a <1% drift, so this may
      still slightly overstate turnover-driven flat fees. A minimum-trade-size
      threshold (e.g. skip trades below some % of position value) would be a
      natural next refinement.
- [x] Swept `spread_bps` (5 vs 10) and `flat_fee_per_trade_eur` (0.5 vs 2) —
      **sensitivity checks only, not adopted as config changes** (the real fee
      is a broker fact, not a knob to tune for a better Sharpe). Result stays
      Sharpe >1.0 across the whole plausible range (1.05-1.11 around the
      then-current baseline), i.e. the strategy's edge is robust to reasonable
      cost-assumption uncertainty.
- [x] Minimum-trade-size threshold (skip re-trading <1pp weight drift) —
      **discard**: essentially a no-op/marginal regression. The flat EUR 1 fee
      is already small enough at this account size that snapping trivial drift
      doesn't meaningfully reduce costs, and occasionally holds a stale weight
      it would otherwise have updated.
- [x] Turnover hysteresis (keep a held name unless its rank falls outside
      top_n+5) — **discarded** (iteration 13, Sharpe 0.6348 vs old baseline
      0.6578): also didn't meaningfully reduce avg_turnover as hoped. Untried
      against the current label_horizon=42 baseline, and untried with a smaller
      buffer (e.g. +2/+3) which might behave differently.

## Tier 6 — radical (use when stuck after 5+ discards)

- [x] Continuous rank-weighted long-only book (tilt the whole universe,
      linear decay to zero at the halfway rank) — **catastrophic discard**:
      wiped out capital (Sharpe -0.86, CAGR -100%). Root cause isn't the
      weighting math, it's the flat per-trade fee: holding ~150-250 names/month
      instead of 5-10 means ~25x more flat-fee trades, which compounds
      destructively at a EUR 10k account. Would only be viable at a much larger
      capital_eur (where the flat fee is negligible) or with a pure bps cost
      model — don't retry at this account size.
- [x] Linear/ElasticNet factor model sanity check — **discard** (Sharpe 0.72
      vs kept baseline, notably worse): confirms XGBoost's nonlinear/interaction
      modeling is adding real value over a linear model on these features, i.e.
      the model family isn't the bottleneck holding back further gains.
- [ ] LightGBM is still blocked: the conda env's install crashes with a native
      access violation even after a full uninstall+reinstall (tried twice).
      CatBoost isn't installed. Neither has been fairly tested.
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
- [x] MAX effect (max daily return, trailing 21 days) — **discard** (Sharpe
      1.0004 vs kept baseline): hurt performance despite academic backing.
- [x] Idiosyncratic volatility vs. equal-weighted universe proxy (63d rolling
      beta) — **discard** (Sharpe 1.0255): also hurt, consistent with the MAX
      effect finding. Three literature factors tried now (pth_52wk, MAX, IVOL)
      and all three have hurt performance on this specific small-basket,
      cost-aware, S&P-500-only setup — worth pausing this whole factor-mining
      approach unless a genuinely different data source (fundamentals, sector,
      volume) becomes available; price-only anomalies from the literature
      don't seem to transfer here.

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

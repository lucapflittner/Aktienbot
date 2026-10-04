"""Single source of truth for strategy parameters.

This is the file the autoresearch loop mutates each iteration (one field at a
time). Keep it a flat, serializable dataclass so every experiment is fully
described by one object that can be logged verbatim to results.tsv.
"""
from dataclasses import dataclass, asdict


@dataclass
class StrategyConfig:
    start_year: int = 2018          # research window (autoresearch iterates against this only)
    end_year: int = 2023             # 2024-2026 is a locked holdout, see holdout_check.py -
                                      # never widen this to peek at holdout data mid-experiment
    train_window_years: float = 1.0  # rolling training window (fractional years allowed; converted to months internally)
    label_horizon_days: int = 10    # ~2 trading weeks forward return
    top_n: int = 5                  # basket size
    model_corr_cap: float = 0.5      # None disables the greedy correlation cap during top-N
                                      # selection; else a pairwise trailing-return correlation
                                      # threshold (e.g. 0.7) - a ranked candidate is skipped if
                                      # its correlation to any already-accepted name exceeds this,
                                      # to avoid the top-N basket crowding into one correlated
                                      # sector/factor bet (see ideas-backlog.md Tier 4)
    weighting: str = "inverse_vol"  # equal | inverse_vol | hrp
    vol_target: float = None        # None disables the vol-targeting overlay; else annualized target e.g. 0.15
    vol_target_lookback: int = 63
    spread_bps: float = 7.5          # bid-ask spread cost charged on turnover, in basis points
    capital_eur: float = 10_000.0   # assumed account size, for sizing the flat per-trade fee below
    flat_fee_per_trade_eur: float = 1.0  # fixed broker fee per buy or sell order (not per round-trip)
    model_n_estimators: int = 600
    model_max_depth: int = 7
    model_learning_rate: float = 0.05
    model_subsample: float = 0.8        # row subsampling per tree (1.0 = off, XGBoost default)
    model_colsample_bytree: float = 0.8  # feature subsampling per tree (1.0 = off, XGBoost default)
    rank_objective: bool = False     # False -> reg:squarederror, True -> rank:pairwise
    include_volume_features: bool = False  # adds illiq_amihud_63d + volume_spike (needs quant_bot/cache/volume.parquet)
    rebalance_freq: str = "W"        # pandas period alias: W (weekly) | M (monthly) | Q (quarterly) | Y (yearly)
    retrain_freq: str = None        # None -> retrain every rebalance period (old behavior, backward compatible).
                                      # Else a pandas period alias (e.g. "M") coarser than rebalance_freq: the
                                      # model is only refit when the rebalance period crosses into a new bucket
                                      # of this frequency; in between, the existing model re-scores fresh
                                      # features each rebalance so stock picks/weights can still update without
                                      # paying XGBoost's full retrain cost every period.

    def as_dict(self):
        return asdict(self)


DEFAULT_CONFIG = StrategyConfig()

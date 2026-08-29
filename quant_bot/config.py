"""Single source of truth for strategy parameters.

This is the file the autoresearch loop mutates each iteration (one field at a
time). Keep it a flat, serializable dataclass so every experiment is fully
described by one object that can be logged verbatim to results.tsv.
"""
from dataclasses import dataclass, asdict


@dataclass
class StrategyConfig:
    start_year: int = 2018          # backtest evaluation window (fast, real, out-of-sample)
    end_year: int = 2026
    train_window_years: float = 1.0  # rolling training window (fractional years allowed; converted to months internally)
    label_horizon_days: int = 10    # ~2 trading weeks forward return
    top_n: int = 5                  # basket size
    weighting: str = "inverse_vol"  # equal | inverse_vol | hrp
    vol_target: float = None        # None disables the vol-targeting overlay; else annualized target e.g. 0.15
    vol_target_lookback: int = 63
    spread_bps: float = 7.5          # bid-ask spread cost charged on turnover, in basis points
    capital_eur: float = 10_000.0   # assumed account size, for sizing the flat per-trade fee below
    flat_fee_per_trade_eur: float = 1.0  # fixed broker fee per buy or sell order (not per round-trip)
    model_n_estimators: int = 300
    model_max_depth: int = 5
    model_learning_rate: float = 0.1
    rank_objective: bool = False     # False -> reg:squarederror, True -> rank:pairwise
    include_volume_features: bool = False  # adds illiq_amihud_63d + volume_spike (needs quant_bot/cache/volume.parquet)
    rebalance_freq: str = "W"        # pandas period alias: W (weekly) | M (monthly) | Q (quarterly) | Y (yearly)

    def as_dict(self):
        return asdict(self)


DEFAULT_CONFIG = StrategyConfig()

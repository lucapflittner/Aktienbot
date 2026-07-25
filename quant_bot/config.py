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
    train_window_years: int = 3     # rolling training window
    label_horizon_days: int = 42    # ~2 trading month forward return
    top_n: int = 10                 # basket size
    weighting: str = "inverse_vol"  # equal | inverse_vol | hrp
    vol_target: float = None        # None disables the vol-targeting overlay; else annualized target e.g. 0.15
    vol_target_lookback: int = 63
    transaction_cost_bps: float = 10.0  # round-trip cost charged on turnover, in basis points
    model_n_estimators: int = 300
    model_max_depth: int = 5
    model_learning_rate: float = 0.1
    rank_objective: bool = False     # False -> reg:squarederror, True -> rank:pairwise

    def as_dict(self):
        return asdict(self)


DEFAULT_CONFIG = StrategyConfig()

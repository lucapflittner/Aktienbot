"""Leakage-free, monthly cross-sectional feature engineering.

Every feature at date t is a function of prices up to and including t only
(pct_change/rolling never look forward). regression_check.py asserts this by
perturbing future prices and checking past feature rows are untouched.
"""
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

CACHE_DIR = Path(__file__).resolve().parent / "cache"


def _winsorize(s: pd.Series, lower=0.01, upper=0.99) -> pd.Series:
    q_low, q_high = s.quantile(lower), s.quantile(upper)
    return s.clip(q_low, q_high)


def _zscore(s: pd.Series) -> pd.Series:
    std = s.std()
    if std == 0 or pd.isna(std):
        return s * 0
    return (s - s.mean()) / std


def engineer_features(price_df: pd.DataFrame, volume_df: pd.DataFrame = None,
                       include_volume_features: bool = False, resample_freq: str = "M") -> pd.DataFrame:
    """price_df: Date-indexed wide frame, one column per ticker (close prices).
    volume_df (optional): same shape, daily trading volume -- only used when
    include_volume_features is True, so passing it is harmless/inert by
    default (backward compatible with callers, incl. regression_check.py's
    synthetic-price-only tests, that never pass volume at all).
    resample_freq: pandas period alias controlling how often a "row" exists per
    ticker (W/M/Q/Y) -- must match quant_bot.config.StrategyConfig.rebalance_freq
    for the rebalance cadence and this feature snapshot cadence to agree."""
    df = price_df.sort_index()

    r2y = df.pct_change(500, fill_method=None)
    r1y = df.pct_change(252, fill_method=None)
    r6m = df.pct_change(126, fill_method=None)
    r3m = df.pct_change(63, fill_method=None)
    r1m = df.pct_change(21, fill_method=None)
    r10d = df.pct_change(10, fill_method=None)
    r5d = df.pct_change(5, fill_method=None)
    r12_1 = r1y - r1m  # 12-1 momentum, skip last month

    daily = df.pct_change(fill_method=None)
    vol1m = daily.rolling(21).std()
    vol3m = daily.rolling(63).std()
    vol6m = daily.rolling(126).std()
    downside_vol = daily.clip(upper=0).rolling(63).std()

    sma20 = df.rolling(20).mean() / df
    sma50 = df.rolling(50).mean() / df
    sma200 = df.rolling(200).mean() / df

    momo_sharpe = r3m / vol3m

    def tag(frame, name):
        frame = frame.copy()
        frame.columns = pd.MultiIndex.from_product([[name], frame.columns])
        return frame

    parts = [
        tag(r2y, "return_2y"), tag(r1y, "return_1y"), tag(r6m, "return_6m"),
        tag(r3m, "return_3m"), tag(r1m, "return_1m"), tag(r10d, "return_10d"),
        tag(r5d, "return_5d"), tag(r12_1, "momentum_12_1"),
        tag(vol1m, "vol_1m"), tag(vol3m, "vol_3m"), tag(vol6m, "vol_6m"),
        tag(downside_vol, "downside_vol"),
        tag(sma20, "sma20_rel"), tag(sma50, "sma50_rel"), tag(sma200, "sma200_rel"),
        tag(momo_sharpe, "momo_sharpe"),
    ]

    if include_volume_features and volume_df is not None:
        vol_aligned = volume_df.reindex(index=df.index, columns=df.columns)
        dollar_volume = df * vol_aligned
        # Amihud (2002) illiquidity: |return| per unit of dollar volume traded,
        # trailing-averaged -- higher means harder to trade without moving the
        # price. Cross-sectional z-score below makes the raw scale irrelevant.
        illiq_amihud = (daily.abs() / dollar_volume.replace(0, np.nan)).rolling(63).mean()
        # today's volume relative to its own trailing average -- an unusual
        # activity spike, often a precursor to news-driven moves.
        volume_spike = vol_aligned / vol_aligned.rolling(63).mean()
        parts.append(tag(illiq_amihud, "illiq_amihud_63d"))
        parts.append(tag(volume_spike, "volume_spike"))

    features = pd.concat(parts, axis=1)

    stacked = features.stack(level=1, future_stack=True).reset_index()
    stacked.columns = ["date", "ticker"] + list(features.columns.get_level_values(0).unique())
    features = stacked.set_index(["date", "ticker"])

    # first trading day of each period (week/month/quarter/year), per ticker
    stacked = features.reset_index().sort_values("date")
    stacked["period"] = stacked["date"].dt.to_period(resample_freq)
    monthly = stacked.groupby(["ticker", "period"], as_index=False).first()
    monthly = monthly.drop(columns=["period"]).set_index(["date", "ticker"]).sort_index()

    feature_cols = [c for c in monthly.columns]
    for col in feature_cols:
        monthly[col] = monthly.groupby("date")[col].transform(_winsorize)
    for col in feature_cols:
        monthly[col] = monthly.groupby("date")[col].transform(_zscore)

    return monthly


def create_labels(price_df: pd.DataFrame, interval: int) -> pd.Series:
    """Forward `interval`-trading-day return, indexed like engineer_features."""
    df = price_df.sort_index()
    future_returns = df.pct_change(interval, fill_method=None).shift(-interval)
    stacked = future_returns.stack().reset_index()
    stacked.columns = ["date", "ticker", "future_return"]
    return stacked.set_index(["date", "ticker"])["future_return"]


def get_features_and_labels(price_df: pd.DataFrame, label_horizon_days: int,
                             volume_df: pd.DataFrame = None, include_volume_features: bool = False,
                             resample_freq: str = "M"):
    """engineer_features/create_labels are expensive (~30-60s over 884 tickers);
    cache the result keyed on this file's own source + the label horizon, so an
    autoresearch iteration that only changes the model/weighting reuses it."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(
        (Path(__file__).read_text() + str(label_horizon_days) + str(price_df.shape)
         + str(include_volume_features) + str(volume_df.shape if volume_df is not None else "none")
         + str(resample_freq)).encode()
    ).hexdigest()[:16]
    feat_path = CACHE_DIR / f"features_{key}.parquet"
    label_path = CACHE_DIR / f"labels_{key}.parquet"

    if feat_path.exists() and label_path.exists():
        features = pd.read_parquet(feat_path)
        labels = pd.read_parquet(label_path)["future_return"]
        return features, labels

    features = engineer_features(price_df, volume_df, include_volume_features, resample_freq)
    labels = create_labels(price_df, label_horizon_days)
    common = features.index.intersection(labels.index)
    features, labels = features.loc[common], labels.loc[common]

    features.to_parquet(feat_path)
    labels.to_frame("future_return").to_parquet(label_path)
    return features, labels

"""Position-sizing schemes for a selected basket of tickers.

The XGBoost ranking step only decides *which* names to hold; these functions
decide *how much* of each — this is where most of the risk-adjusted-return
gains come from (equal-weight ignores that picks differ wildly in volatility
and correlation). All return a pd.Series of weights summing to 1, long-only.
"""
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage
from scipy.spatial.distance import squareform


def equal_weight(hist_returns: pd.DataFrame, tickers: list) -> pd.Series:
    return pd.Series(1.0 / len(tickers), index=tickers)


def inverse_vol_weight(hist_returns: pd.DataFrame, tickers: list) -> pd.Series:
    vol = hist_returns[tickers].std().replace(0, np.nan)
    inv = 1.0 / vol
    inv = inv.fillna(inv.mean())
    return inv / inv.sum()


def _quasi_diag(link: np.ndarray) -> list:
    link = link.astype(int)
    n = link.shape[0] + 1
    root = 2 * n - 2

    def recurse(node):
        if node < n:
            return [node]
        left, right = link[node - n, 0], link[node - n, 1]
        return recurse(left) + recurse(right)

    return recurse(root)


def _cluster_var(cov: np.ndarray, items: list) -> float:
    sub = cov[np.ix_(items, items)]
    ivp = 1.0 / np.diag(sub)
    ivp /= ivp.sum()
    return float(ivp @ sub @ ivp)


def _recursive_bisection(cov: np.ndarray, sorted_items: list) -> np.ndarray:
    w = np.ones(len(sorted_items))
    clusters = [sorted_items]
    while clusters:
        clusters = [c[start:end] for c in clusters
                    for start, end in ((0, len(c) // 2), (len(c) // 2, len(c)))
                    if len(c) > 0]
        clusters = [c for c in clusters if len(c) > 0]
        for i in range(0, len(clusters), 2):
            if i + 1 >= len(clusters):
                continue
            left, right = clusters[i], clusters[i + 1]
            var_l, var_r = _cluster_var(cov, left), _cluster_var(cov, right)
            alpha = 1 - var_l / (var_l + var_r)
            w[left] *= alpha
            w[right] *= 1 - alpha
        clusters = [c for c in clusters if len(c) > 1]
    return w


def hrp_weight(hist_returns: pd.DataFrame, tickers: list) -> pd.Series:
    """Hierarchical Risk Parity (Lopez de Prado, 2016): cluster by correlation,
    then recursively split inverse-variance weight top-down along the
    dendrogram instead of using the full (noisy) covariance matrix at once."""
    sub = hist_returns[tickers].dropna(axis=0, how="any")
    if len(tickers) < 3 or len(sub) < 20:
        return equal_weight(hist_returns, tickers)

    corr = sub.corr().values
    cov = sub.cov().values
    corr = np.nan_to_num(corr, nan=0.0)
    np.fill_diagonal(corr, 1.0)

    dist = np.sqrt(np.clip((1 - corr) / 2, 0, 1))
    condensed = squareform(dist, checks=False)
    link = linkage(condensed, method="single")

    order = _quasi_diag(link)
    w = _recursive_bisection(cov, order)

    weights = pd.Series(0.0, index=range(len(tickers)))
    weights.iloc[order] = w
    weights.index = tickers
    return weights / weights.sum()


SCHEMES = {
    "equal": equal_weight,
    "inverse_vol": inverse_vol_weight,
    "hrp": hrp_weight,
}


def volatility_target_scale(portfolio_daily_returns: pd.Series, target_annual_vol: float,
                             lookback: int = 63, max_leverage: float = 1.5) -> float:
    """Scalar applied to next-period exposure so realized vol tracks the target.
    Long-only book: scale is clipped to [0, max_leverage] (no shorting cash)."""
    if len(portfolio_daily_returns) < lookback:
        return 1.0
    realized = portfolio_daily_returns.tail(lookback).std() * np.sqrt(252)
    if realized == 0 or np.isnan(realized):
        return 1.0
    return float(np.clip(target_annual_vol / realized, 0.0, max_leverage))

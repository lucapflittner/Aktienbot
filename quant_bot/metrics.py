"""Risk-adjusted performance metrics computed from a series of period returns.

All inputs are *monthly* simple returns (net of any transaction costs already
applied by the caller). Annualization assumes 12 periods/year throughout.
"""
import numpy as np

PERIODS_PER_YEAR = 12


def cagr(returns: np.ndarray) -> float:
    returns = np.asarray(returns, dtype=float)
    if len(returns) == 0:
        return 0.0
    growth = np.prod(1 + returns)
    years = len(returns) / PERIODS_PER_YEAR
    if growth <= 0 or years <= 0:
        return -1.0
    return growth ** (1 / years) - 1


def sharpe_ratio(returns: np.ndarray, rf_annual: float = 0.0) -> float:
    returns = np.asarray(returns, dtype=float)
    if len(returns) < 2:
        return 0.0
    rf_period = rf_annual / PERIODS_PER_YEAR
    excess = returns - rf_period
    std = excess.std(ddof=1)
    if std == 0:
        return 0.0
    return float(excess.mean() / std * np.sqrt(PERIODS_PER_YEAR))


def sortino_ratio(returns: np.ndarray, rf_annual: float = 0.0) -> float:
    returns = np.asarray(returns, dtype=float)
    if len(returns) < 2:
        return 0.0
    rf_period = rf_annual / PERIODS_PER_YEAR
    excess = returns - rf_period
    downside = excess[excess < 0]
    dd = downside.std(ddof=1) if len(downside) > 1 else 0.0
    if dd == 0:
        return 0.0
    return float(excess.mean() / dd * np.sqrt(PERIODS_PER_YEAR))


def max_drawdown(returns: np.ndarray) -> float:
    returns = np.asarray(returns, dtype=float)
    if len(returns) == 0:
        return 0.0
    curve = np.cumprod(1 + returns)
    peak = np.maximum.accumulate(curve)
    dd = curve / peak - 1
    return float(dd.min())


def calmar_ratio(returns: np.ndarray) -> float:
    mdd = max_drawdown(returns)
    if mdd == 0:
        return 0.0
    return cagr(returns) / abs(mdd)


def annual_vol(returns: np.ndarray) -> float:
    returns = np.asarray(returns, dtype=float)
    if len(returns) < 2:
        return 0.0
    return float(returns.std(ddof=1) * np.sqrt(PERIODS_PER_YEAR))


def summarize(returns: np.ndarray) -> dict:
    return {
        "cagr": cagr(returns),
        "sharpe": sharpe_ratio(returns),
        "sortino": sortino_ratio(returns),
        "calmar": calmar_ratio(returns),
        "max_drawdown": max_drawdown(returns),
        "annual_vol": annual_vol(returns),
        "n_periods": len(returns),
    }

"""Risk-adjusted performance metrics computed from a series of period returns.

Annualization defaults to 12 periods/year (monthly rebalancing, this project's
original and still-default cadence) but every function accepts periods_per_year
explicitly so weekly/quarterly/yearly rebalancing (see
quant_bot.config.StrategyConfig.rebalance_freq) annualizes correctly instead of
silently assuming monthly.
"""
import numpy as np

PERIODS_PER_YEAR = 12  # kept for backward compatibility; prefer passing it explicitly


def cagr(returns: np.ndarray, periods_per_year: int = PERIODS_PER_YEAR) -> float:
    returns = np.asarray(returns, dtype=float)
    if len(returns) == 0:
        return 0.0
    growth = np.prod(1 + returns)
    years = len(returns) / periods_per_year
    if growth <= 0 or years <= 0:
        return -1.0
    return growth ** (1 / years) - 1


def sharpe_ratio(returns: np.ndarray, rf_annual: float = 0.0, periods_per_year: int = PERIODS_PER_YEAR) -> float:
    returns = np.asarray(returns, dtype=float)
    if len(returns) < 2:
        return 0.0
    rf_period = rf_annual / periods_per_year
    excess = returns - rf_period
    std = excess.std(ddof=1)
    if std == 0:
        return 0.0
    return float(excess.mean() / std * np.sqrt(periods_per_year))


def sortino_ratio(returns: np.ndarray, rf_annual: float = 0.0, periods_per_year: int = PERIODS_PER_YEAR) -> float:
    returns = np.asarray(returns, dtype=float)
    if len(returns) < 2:
        return 0.0
    rf_period = rf_annual / periods_per_year
    excess = returns - rf_period
    downside = excess[excess < 0]
    dd = downside.std(ddof=1) if len(downside) > 1 else 0.0
    if dd == 0:
        return 0.0
    return float(excess.mean() / dd * np.sqrt(periods_per_year))


def max_drawdown(returns: np.ndarray) -> float:
    returns = np.asarray(returns, dtype=float)
    if len(returns) == 0:
        return 0.0
    curve = np.cumprod(1 + returns)
    peak = np.maximum.accumulate(curve)
    dd = curve / peak - 1
    return float(dd.min())


def calmar_ratio(returns: np.ndarray, periods_per_year: int = PERIODS_PER_YEAR) -> float:
    mdd = max_drawdown(returns)
    if mdd == 0:
        return 0.0
    return cagr(returns, periods_per_year) / abs(mdd)


def annual_vol(returns: np.ndarray, periods_per_year: int = PERIODS_PER_YEAR) -> float:
    returns = np.asarray(returns, dtype=float)
    if len(returns) < 2:
        return 0.0
    return float(returns.std(ddof=1) * np.sqrt(periods_per_year))


def summarize(returns: np.ndarray, periods_per_year: int = PERIODS_PER_YEAR) -> dict:
    return {
        "cagr": cagr(returns, periods_per_year),
        "sharpe": sharpe_ratio(returns, periods_per_year=periods_per_year),
        "sortino": sortino_ratio(returns, periods_per_year=periods_per_year),
        "calmar": calmar_ratio(returns, periods_per_year),
        "max_drawdown": max_drawdown(returns),
        "annual_vol": annual_vol(returns, periods_per_year),
        "n_periods": len(returns),
    }

"""Does ANY cross-sectional signal survive honest measurement?

Independent of quant_bot.backtest on purpose: a small, auditable harness that
answers one question before any further portfolio-construction work - is there
predictive signal at all? (See results.tsv iteration 73.)

Setup, monthly, deliberately boring and untuned:
- Decision at the first trading day of month m, using features computed from
  closes up to and including that day (quant_bot.features.engineer_features).
- Execution one bar later (next close), exit one bar after the first trading
  day of month m+1 -> holding spans tile the calendar, no same-bar fills.
- Universe: S&P 500 membership as of month m-1, restricted to names with a
  price at entry. A name whose price disappears before exit is booked at its
  last available close (delisting proxy).
- Models are trained only on months whose label window had fully resolved at
  the decision date (months <= m-2), rolling 36-month window.

Reports per signal: mean rank IC, t-stat, hit rate, and the net return of a
top-quintile equal-weight long-only book vs the equal-weight universe, for the
research window 2018-2023 and the locked holdout 2024-2026 separately.

Usage: python scripts/signal_check.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from quant_bot import data  # noqa: E402
from quant_bot.features import engineer_features  # noqa: E402

SPREAD_BPS = 7.5
TRAIN_MONTHS = 36
QUANTILE = 0.2


def monthly_panel(prices: pd.DataFrame, universe: pd.DataFrame):
    feats = engineer_features(prices, resample_freq="M")
    idx = prices.index
    months = pd.period_range("2010-01", str(idx[-1].to_period("M") - 1), freq="M")
    rows = []
    for m in months:
        d0 = idx[idx.searchsorted(m.to_timestamp(how="start"))]
        nxt = idx.searchsorted((m + 1).to_timestamp(how="start"))
        i_entry = idx.get_loc(d0) + 1
        i_exit = nxt + 1
        if i_exit >= len(idx):
            break
        prev = universe[universe["date"] < m.to_timestamp(how="start")]
        if prev.empty:
            continue
        members = [t for t in prev["tickers"].iloc[-1] if t in prices.columns]
        entry = prices.iloc[i_entry][members]
        exit_ = prices.iloc[: i_exit + 1][members].ffill().iloc[-1]  # delisting proxy
        fwd = (exit_ / entry - 1).dropna()
        try:
            f = feats.xs(d0, level="date")
        except KeyError:
            continue
        f = f.reindex(fwd.index).dropna(how="all")
        if len(f) < 100:
            continue
        f = f.assign(fwd=fwd.reindex(f.index), month=m)
        rows.append(f)
    panel = pd.concat(rows).reset_index().rename(columns={"index": "ticker"})
    return panel


def rank_ic(score: pd.Series, fwd: pd.Series) -> float:
    ok = score.notna() & fwd.notna()
    if ok.sum() < 30:
        return np.nan
    return score[ok].rank().corr(fwd[ok].rank())


def walk_forward_models(panel: pd.DataFrame, feat_cols):
    from sklearn.linear_model import Ridge
    from xgboost import XGBRegressor

    months = sorted(panel["month"].unique())
    out = {"ridge": [], "xgb_small": []}
    panel = panel.copy()
    panel["target"] = panel.groupby("month")["fwd"].rank(pct=True) - 0.5
    for i, m in enumerate(months):
        if m.year < 2018:
            continue
        train_months = [x for x in months if m - TRAIN_MONTHS - 1 <= x <= m - 2]
        tr = panel[panel["month"].isin(train_months)]
        te = panel[panel["month"] == m]
        X, y = tr[feat_cols].fillna(0.0), tr["target"]
        Xt = te[feat_cols].fillna(0.0)
        ridge = Ridge(alpha=10.0).fit(X, y)
        xgb = XGBRegressor(n_estimators=200, max_depth=3, learning_rate=0.05,
                           subsample=0.8, colsample_bytree=0.8, random_state=0,
                           n_jobs=-1, verbosity=0).fit(X, y)
        out["ridge"].append(pd.Series(ridge.predict(Xt), index=te.index))
        out["xgb_small"].append(pd.Series(xgb.predict(Xt), index=te.index))
    res = {k: pd.concat(v) for k, v in out.items()}
    # ensemble = average of within-month ranks, so neither model's scale dominates
    r = pd.DataFrame(res).join(panel["month"])
    res["ensemble"] = (r.groupby("month")["ridge"].rank(pct=True)
                       + r.groupby("month")["xgb_small"].rank(pct=True)) / 2
    return res


def evaluate(panel: pd.DataFrame, score: pd.Series, name: str):
    df = panel.assign(score=score).dropna(subset=["score", "fwd"])
    rows, prev = [], set()
    for m, g in df.groupby("month"):
        ic = rank_ic(g["score"], g["fwd"])
        k = max(int(len(g) * QUANTILE), 1)
        top = g.nlargest(k, "score")
        names = set(top["ticker"])
        turnover = 1.0 if not prev else 2 * len(names - prev) / k
        prev = names
        long_ret = top["fwd"].mean() - turnover * SPREAD_BPS / 1e4
        rows.append({"month": m, "ic": ic, "long": long_ret, "univ": g["fwd"].mean(),
                     "turnover": turnover})
    r = pd.DataFrame(rows).set_index("month")
    out = {}
    for label, sl in [("2018-2023", r.loc["2018-01":"2023-12"]), ("2024-2026", r.loc["2024-01":])]:
        ex = sl["long"] - sl["univ"]
        out[label] = {
            "IC": sl["ic"].mean(),
            "IC_t": sl["ic"].mean() / sl["ic"].std() * np.sqrt(len(sl)),
            "IC>0": (sl["ic"] > 0).mean(),
            "excess_pa": ex.mean() * 12,
            "excess_t": ex.mean() / ex.std() * np.sqrt(len(sl)),
            "long_cagr": (1 + sl["long"]).prod() ** (12 / len(sl)) - 1,
            "univ_cagr": (1 + sl["univ"]).prod() ** (12 / len(sl)) - 1,
            "turnover": sl["turnover"].mean(),
            "n": len(sl),
        }
    return name, out


def main():
    prices = data.load_prices()
    universe = data.load_universe(10, 2018)
    panel = monthly_panel(prices, universe)
    feat_cols = [c for c in panel.columns if c not in ("ticker", "fwd", "month")]
    panel = panel[panel["month"] >= pd.Period("2014-01", "M")].reset_index(drop=True)

    results = []
    # single hand-signed signals, no fitting at all
    signs = {"momentum_12_1": 1, "return_6m": 1, "return_1m": -1, "vol_3m": -1,
             "sma200_rel": 1, "momo_sharpe": 1}
    for col, s in signs.items():
        results.append(evaluate(panel, s * panel[col], f"{'-' if s < 0 else ''}{col}"))
    for name, score in walk_forward_models(panel, feat_cols).items():
        results.append(evaluate(panel, score, name))

    lines = []
    hdr = f"{'signal':<16}{'window':<11}{'IC':>7}{'IC_t':>7}{'IC>0':>6}{'exc%pa':>8}{'exc_t':>7}{'top CAGR':>9}{'univ':>7}{'turn':>6}"
    lines.append(hdr)
    for name, out in results:
        for w, v in out.items():
            lines.append(f"{name:<16}{w:<11}{v['IC']:>7.3f}{v['IC_t']:>7.2f}{v['IC>0']:>6.2f}"
                         f"{v['excess_pa']*100:>8.2f}{v['excess_t']:>7.2f}{v['long_cagr']*100:>8.1f}%"
                         f"{v['univ_cagr']*100:>6.1f}%{v['turnover']:>6.2f}")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

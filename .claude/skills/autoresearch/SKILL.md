---
name: autoresearch
description: Autonomous, goal-directed iteration loop for this stock bot. Use when asked to improve the trading strategy's risk-adjusted return, run more experiments, keep optimizing the bot, or continue the autoresearch loop. Inspired by Andrej Karpathy's autoresearch (github.com/karpathy/autoresearch) pattern, adapted to quant portfolio research.
---

# Autoresearch — stock bot edition

Andrej Karpathy's `autoresearch` pattern: give an agent a real benchmark, a
baseline, and a regression gate, then let it modify → measure → keep/discard
→ repeat, unsupervised, for as long as it's allowed to run. This project
wires that pattern to a walk-forward equity portfolio backtest instead of
nanoGPT training.

**Goal on file:** maximize `metric` = annualized Sharpe ratio of
`quant_bot/config.py`'s `DEFAULT_CONFIG`, long-only, weekly rebalance, net
of transaction costs, backtested 2018-2023 on real S&P 500 data — without
the regression suite dropping below baseline. This is the default; if the
user gives a different goal (e.g. "minimize max drawdown", "maximize CAGR
subject to vol < 15%"), re-target `benchmark.py`'s printed `metric:` line
accordingly (it's a single `print` statement) and proceed with the same loop.

**2018-2023 is a research window, not the full corpus.** 2024-2026 is a
locked holdout (`holdout_check.py`) that iteration never touches — see
[[benchmark-harness]] "Locked holdout" section for why (iteration 47's
train_window_years=0.5 hit Sharpe 2.40 in-sample on the full 2018-2026
window and then lost money live in `paper_trading`, the textbook overfitting
failure this split exists to catch earlier next time). Never widen
`start_year`/`end_year` back toward 2026 to "get more data" for an
experiment — that reopens the exact hole this closed.

## The four project files that make this work

| File | Role |
|---|---|
| `benchmark.py` | **The harness.** Read-only during iteration. Runs the full walk-forward backtest, prints `metric: <sharpe>` + a bundle of other stats, writes `autoresearch/last_run.json`. Editing it requires a separate `harness:`-prefixed commit — see [[benchmark-harness]]. |
| `regression_check.py` | **The regression gate.** Mechanical, no pytest dependency, ~2s. Checks no look-ahead bias, valid portfolio weights, and that a tiny synthetic backtest runs end-to-end. Prints `passed: <n>`. |
| `quant_bot/config.py` | **What iteration actually edits.** `StrategyConfig` — one flat dataclass. Nearly every experiment is "change one field, rerun benchmark.py." |
| `quant_bot/*.py` | `features.py` (factor engineering), `weighting.py` (equal/inverse-vol/HRP position sizing), `backtest.py` (walk-forward loop + XGBoost training), `metrics.py` (Sharpe/Sortino/Calmar/MaxDD). New ideas that aren't just a config tweak land here. |

Run the harness with the project's conda env, not bare `python` (bare `python`
on this machine is a stub 3.8 with no pandas):

```
"/c/Users/lucap/anaconda3/envs/tf-gpu/python.exe" benchmark.py
"/c/Users/lucap/anaconda3/envs/tf-gpu/python.exe" regression_check.py
```

## Entry points

- **"keep improving the bot" / "run more autoresearch iterations" / `/autoresearch`** — run the Default Path below, unbounded (never stop, never ask permission to continue — only the user's Ctrl+C or a session end stops it).
- **`/loop N` chained with this skill** — run exactly N bounded iterations, then print a final summary (see [[loop-protocol]] Bounded Mode).
- **A specific hypothesis** ("try HRP weighting", "add a regime filter") — skip Ideate, apply that one change directly, then fall into Verify → Decide → Log → Repeat.

## Default Path (every iteration)

1. **Review** — read `autoresearch/results.tsv` (last ~15 rows), `git log --oneline -15`, and the current `quant_bot/config.py`. Never assume state; a prior iteration may have been rolled back.
2. **Ideate** — pick ONE change. Priority: fix a crash > exploit a recent win > try an untried idea from [[ideas-backlog]] > combine two near-misses > simplify > radical change if stuck. Never repeat an exact change already logged as `discard`.
3. **Modify** — one atomic change, describable in one sentence, in `quant_bot/config.py` and/or the relevant `quant_bot/*.py` module. `benchmark.py` and `regression_check.py` stay untouched unless the change IS to the harness itself (separate commit, prefixed `harness:`).
4. **Commit before verifying**: `git add -A -- quant_bot benchmark.py regression_check.py && git commit -m "experiment: <one sentence>"` — commit first so a bad result rolls back cleanly with `git reset --hard HEAD~1`.
5. **Regression gate (absolute, checked first):** run `regression_check.py`. If `passed` < the integer in `autoresearch/.regression-baseline`, discard immediately — do not even look at the Sharpe. `git reset --hard HEAD~1`, log status `discard-regression`, go to step 8.
6. **Verify**: run `benchmark.py`, parse the `metric:` line (Sharpe). Timeout rule: if it runs >3x the ~50s baseline runtime, kill it and treat as a crash.
7. **Decide**:
   - Sharpe improved AND regression passed → `keep` (commit stays).
   - Sharpe same/worse → `discard`, `git reset --hard HEAD~1`.
   - Crashed → attempt a fix (max 3 tries), else `discard`/`crash` + rollback.
   - Simplicity override: a >+0.02 Sharpe gain that adds real complexity → keep. A <0.005 gain with real complexity → treat as discard. Simpler code at equal Sharpe → keep.
8. **Log** — append one TSV row to `autoresearch/results.tsv`: `iteration, commit (or "-" if discarded), metric, cagr, max_drawdown, status, one-line description`. Commit this log update too (`log: iteration N <status>`).
9. **Repeat** from step 1. Full detail, crash recovery, and the "stuck after 5 discards" playbook: [[loop-protocol]].

## Non-negotiables

- Real data only. The corpus is already real (S&P 500 2007-2026 actual closes + actual historical index membership, see `autoresearch/README.md`) — never fabricate price data. `regression_check.py`'s synthetic prices are fine because they test mechanical properties, not the actual metric.
- One change per iteration. Two simultaneous changes make the Sharpe delta unattributable.
- The regression gate is absolute — a Sharpe win that breaks look-ahead safety or produces invalid weights is not a win, full stop.
- Don't ask "should I keep going?" mid-loop. Unbounded means unbounded.
- Print one status line every ~5 iterations (`Iteration 12: Sharpe 0.81 (baseline 0.65), 4 keeps / 7 discards / 1 crash`), not a play-by-play of every step.

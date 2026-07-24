# Loop protocol (full detail)

SKILL.md has the summary; this is the complete rule set, ported from
Karpathy's autoresearch loop to this project's git + TSV mechanics.

## Modes

- **Unbounded (default):** loop until interrupted. Never ask "should I
  continue?" — the answer in this mode is always yes.
- **Bounded (`/loop N` chained with this skill):** exactly N iterations, then
  stop and print the final summary below, even mid-streak.

## Phase 1 — Review (cheap, do it every time)

```
git log --oneline -15
tail -n 16 autoresearch/results.tsv
cat quant_bot/config.py   # current StrategyConfig values
```

State can differ from what you expect after a rollback — never assume,
always re-read.

## Phase 2 — Ideate

Priority order:
1. Fix the previous iteration's crash first.
2. If the last change was a `keep`, try a variant in the same direction
   before moving on (e.g. weighting=hrp helped → try lookback tweaks on HRP
   before abandoning it).
3. Pull an untried idea from [[ideas-backlog]].
4. Combine two changes that individually were near-misses (Sharpe delta
   between -0.02 and +0.02).
5. Simplify: if two config values produce equal Sharpe, prefer the simpler
   one (fewer knobs, shorter code).
6. If stuck (see below), go radical.

Anti-patterns: repeating an exact discarded change; bundling unrelated
changes; chasing a +0.005 Sharpe gain with a large code-complexity increase.

## Phase 3 — Modify

One atomic change. Write the one-sentence description before touching code —
if you can't state it in one sentence, it's not one change.

## Phase 4 — Commit before verifying

```
git add -A -- quant_bot benchmark.py regression_check.py
git commit -m "experiment: <one sentence>"
```
Committing before verification means a bad result rolls back cleanly:
`git reset --hard HEAD~1`.

## Phase 5 — Regression gate (absolute, checked BEFORE the metric)

```
"/c/Users/lucap/anaconda3/envs/tf-gpu/python.exe" regression_check.py
```
Parse `passed: <n>`. Compare against the integer in
`autoresearch/.regression-baseline` (currently 10). If lower:
```
git reset --hard HEAD~1
# log status=discard-regression, skip Phase 6/7
```
No exceptions — a Sharpe win that breaks a look-ahead-bias check or produces
negative portfolio weights is not a win.

## Phase 6 — Verify

```
"/c/Users/lucap/anaconda3/envs/tf-gpu/python.exe" benchmark.py
```
Parse the `metric:` line (Sharpe) plus `cagr:` and `max_drawdown:` for the
log row. Normal runtime is ~45-60s on the 2018-2026 window; if a run exceeds
~3 minutes, kill it and treat as a crash (usually an infinite loop in a new
weighting/model change, or an XGBoost config that blew up training time).

## Phase 7 — Decide

```
IF regression discarded already: skip (handled in Phase 5)
ELIF sharpe_new > sharpe_prev_kept + 0.02: keep (clear win)
ELIF sharpe_new > sharpe_prev_kept and simpler-or-equal code: keep
ELIF crashed: fix (max 3 attempts) -> re-verify, else discard + rollback
ELSE: discard, git reset --hard HEAD~1
```
`sharpe_prev_kept` = the metric value of the last `keep` row in
`results.tsv`, not the immediately preceding row (which may itself have been
a discard).

## Phase 8 — Log

Append to `autoresearch/results.tsv` (tab-separated):
```
iteration	commit	metric	cagr	max_drawdown	status	description
7	a1b2c3d	0.8123	0.2210	-0.1890	keep	switch top-N weighting from equal to HRP
8	-	0.7950	0.2100	-0.2050	discard	tried top_n=15 (too diluted)
```
Commit the log line itself: `git commit -am "log: iteration 8 discard"`.

## Phase 9 — Repeat

Unbounded: go to Phase 1, forever.

Bounded: if `current_iteration < N`, go to Phase 1. Otherwise stop and print:
```
=== Autoresearch Complete (N/N iterations) ===
Baseline Sharpe: 0.6515 -> Final: {value} ({delta})
Keeps: X | Discards: Y | Regression-discards: Z | Crashes: W
Best iteration: #{n} — {description}
```

## When stuck (5+ consecutive discards)

1. Re-read all of `quant_bot/*.py` from scratch, not just `config.py`.
2. Re-read the goal (top of SKILL.md).
3. Scan the full `results.tsv` for a pattern (e.g. every weighting change
   loses — maybe the model's ranking signal itself is the bottleneck, not
   position sizing).
4. Try combining 2-3 previously-successful (`keep`) changes together.
5. Try the opposite of what's been failing (e.g. if shrinking `top_n` kept
   losing, try growing it instead).
6. Try a structurally different idea from the "radical" tier of
   [[ideas-backlog]] (e.g. switch the label from point regression to
   cross-sectional rank, or add a regime filter that goes to cash).

## Crash recovery

- Syntax/import error → fix immediately, doesn't count as a separate
  iteration.
- XGBoost/pandas runtime error → attempt a fix (max 3 tries), then discard.
- Backtest producing 0 months (`metric: -999.0` from `benchmark.py`) → the
  change likely broke a filter (e.g. `train_mask.sum() < 100` never
  satisfied) — inspect before retrying blindly.
- Hang/very slow run → kill after ~3x normal runtime, revert, avoid whatever
  made training or feature engineering blow up (e.g. huge `n_estimators`,
  a per-row Python loop over the full universe).

## Communication

- No "should I keep going?" mid-loop.
- No step-by-step narration of Phases 1-8 every iteration — just log and
  move on.
- One status line every ~5 iterations.
- Do flag anything genuinely surprising (a change that 3x's the Sharpe, or
  one that reveals a data bug).

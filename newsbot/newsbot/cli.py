"""Command line entry point:  python -m newsbot <command>

  setup      load universe (tickers, SEC CIKs, sectors) - run once
  check      is the local LLM reachable? which models does it serve?
  ingest     pull new SEC filings, world news, RSS
  score      score unscored events (insider rules + local LLM)
  trade      update prices, run the paper broker up to the latest close
  evaluate   event study: did the scores predict anything?
  report     NAV, positions, latest signals, recent trades
  run        ingest + score + trade (what the scheduler calls)
"""
import argparse
import json
import sys

import pandas as pd

from . import broker, db, evaluate, notify, prices, scoring, universe
from .config import SECTOR_ETFS, SETTINGS
from .llm import LocalLLM
from .signals import compute_signals
from .sources import edgar, gdelt, rss


def _con():
    return db.connect(SETTINGS.db_path)


def cmd_setup(args):
    con = _con()
    if args.sectors:
        print("Fetching sectors from Yahoo (one-time, a few minutes)...")
        universe.build_sector_file(universe.load_tickers())
    n = universe.refresh_universe(con, SETTINGS)
    print(f"universe: {n} tickers")


def cmd_check(args):
    llm = LocalLLM(SETTINGS)
    try:
        models = llm.ping()
    except Exception as e:
        print(f"LLM server at {SETTINGS.llm_base_url} not reachable: {e}")
        return 1
    print(f"server OK, models: {models}")
    if SETTINGS.llm_model not in models:
        print(f"WARNING: LLM_MODEL={SETTINGS.llm_model!r} is not in that list - set it in .env")
        return 1
    reply = llm.chat_json(scoring.COMPANY_SYSTEM,
                          "Company ticker(s): TEST\nTitle: TEST 8-K: 2.02 Results\n\n"
                          "Quarterly revenue rose 25% year over year, well above the company's prior "
                          "guidance range; full-year outlook raised.")
    print("test score:", scoring.normalize_company(reply))
    return 0


def cmd_ingest(args):
    con = _con()
    now = scoring.utcnow()
    ciks = universe.cik_map(con)
    if not ciks:
        sys.exit("universe is empty - run `python -m newsbot setup` first")
    stats = {}
    for name, fn in (("edgar", lambda: edgar.ingest(con, SETTINGS, ciks, now)),
                     ("gdelt", lambda: gdelt.ingest(con, SETTINGS, now)),
                     ("rss", lambda: rss.ingest(con, SETTINGS, now))):
        try:
            stats.update(fn())
        except SystemExit:
            raise
        except Exception as e:  # one broken source must not stop the others
            print(f"  {name} failed: {e}")
    print("ingested:", stats)
    return stats


def cmd_score(args):
    con = _con()
    stats = scoring.score_pending(con, SETTINGS, LocalLLM(SETTINGS), scoring.utcnow())
    print("scored:", stats)
    return stats


def _price_universe(con):
    held = [r["ticker"] for r in con.execute("SELECT ticker FROM positions")]
    sig = compute_signals(con, SETTINGS, pd.Timestamp.now(tz="UTC").to_pydatetime())
    return sorted(set(held) | set(sig.index) | set(evaluate.scored_targets(con))
                  | set(SECTOR_ETFS.values()) | {SETTINGS.benchmark})


def cmd_trade(args):
    con = _con()
    prices.update_prices(con, _price_universe(con))
    closes = prices.close_matrix(con)
    results = broker.run(con, SETTINGS, closes)
    for r in results:
        print(f"{r['date']}: NAV {r['nav']:,.2f}  bench {r['bench_nav']:,.2f}  " + "; ".join(r["actions"]))
        if r["actions"]:
            notify.send(SETTINGS, f"Newsbot {r['date']}\n" + "\n".join(r["actions"])
                        + f"\nNAV {r['nav']:,.2f} (SPY {r['bench_nav']:,.2f})")
    return results


def cmd_evaluate(args):
    con = _con()
    prices.update_prices(con, evaluate.scored_targets(con) + list(SECTOR_ETFS.values()) + [SETTINGS.benchmark])
    df = evaluate.event_returns(con, SETTINGS, prices.close_matrix(con))
    if df.empty:
        print("no scored events with prices yet - let it run for a while")
        return
    pd.set_option("display.width", 160)
    print(evaluate.summarize(df).to_string(index=False))
    conf = evaluate.by_confidence(df)
    if not conf.empty:
        print("\nby confidence (5d) - higher confidence should mean better results:")
        print(conf.to_string())
    print(f"\n{len(df)} scored events. Rule of thumb: don't trust any row with n < 100.")


def cmd_report(args):
    con = _con()
    nav = pd.read_sql_query("SELECT * FROM nav ORDER BY date", con)
    if len(nav):
        last = nav.iloc[-1]
        print(f"{last['date']}: NAV {last['nav']:,.2f} ({last['nav']/SETTINGS.capital-1:+.2%})  "
              f"SPY {last['bench_nav']:,.2f} ({last['bench_nav']/SETTINGS.capital-1:+.2%})  "
              f"positions {int(last['n_positions'])}")
    for r in con.execute("SELECT * FROM positions"):
        print(f"  holding {r['ticker']}: {r['shares']:.2f} @ {r['entry_price']:.2f} since {r['entry_date']}")
    sig = compute_signals(con, SETTINGS, pd.Timestamp.now(tz="UTC").to_pydatetime())
    print("\ntop signals:", ", ".join(f"{t} {v:+.2f}" for t, v in sig.head(8).items()) or "-")
    print("bottom signals:", ", ".join(f"{t} {v:+.2f}" for t, v in sig.tail(5).items() if v < 0) or "-")
    print("\nlatest scored events:")
    for r in con.execute(
            "SELECT e.title, s.target, s.direction, s.confidence, s.rationale FROM scores s "
            "JOIN events e ON e.id=s.event_id WHERE s.direction != 0 ORDER BY s.scored_at DESC LIMIT 10"):
        print(f"  {r['direction']:+d} {r['target']:<5} conf {r['confidence']:.2f}  {r['title'][:70]}")
        print(f"        {r['rationale'][:140]}")
    counts = con.execute("SELECT source, COUNT(*) n FROM events GROUP BY source").fetchall()
    print("\nevents stored:", json.dumps({r["source"]: r["n"] for r in counts}))


def cmd_run(args):
    cmd_ingest(args)
    cmd_score(args)
    cmd_trade(args)


def main(argv=None):
    p = argparse.ArgumentParser(prog="newsbot", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup")
    s.add_argument("--sectors", action="store_true", help="(re)build data/sectors.csv from Yahoo")
    for name in ("check", "ingest", "score", "trade", "evaluate", "report", "run"):
        sub.add_parser(name)
    args = p.parse_args(argv)
    return globals()[f"cmd_{args.cmd}"](args)


if __name__ == "__main__":
    main()

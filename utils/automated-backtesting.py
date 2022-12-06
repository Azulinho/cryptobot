"""automated-backtesting.py"""
import argparse
import glob
import os
import re
import shutil
import subprocess
from collections import OrderedDict
from datetime import datetime
from multiprocessing import get_context
from string import Template
from typing import Optional

import yaml
from isal import igzip


def backup_backtesting_log(logs_dir="log"):
    """makes a backup of backtesting.log"""
    shutil.copyfile(
        f"{logs_dir}/backtesting.log", f"{logs_dir}/backtesting.log.backup"
    )


def compress_file(filename):
    """compresses coin price.log file"""
    with open(filename) as uncompressed:
        with igzip.open(f"{filename}.gz", mode="wt") as compressed:
            shutil.copyfileobj(uncompressed, compressed)
    os.remove(filename)


def split_logs_into_coins(filename, cfg, logs_dir="log"):
    """splits one price.log into individual coin price.log files"""
    coinfiles = set()
    coinfh = {}
    pairing = cfg["DEFAULTS"]["PAIRING"]
    with igzip.open(f"{filename}", "rt") as logfile:
        for line in logfile:

            # don't process all the lines, but only the ones related to our PAIR
            # 2021-01-01 00:00:01.0023 BTCUSDT 36000.00
            if not f"{pairing} " in line:
                continue

            parts = line.split(" ")
            symbol = parts[2]

            # don't process any BEAR/BULL/UP/DOWN lines
            if symbol in [
                f"DOWN{pairing}",
                f"UP{pairing}",
                f"BEAR{pairing}",
                f"BULL{pairing}",
            ]:
                continue

            coinfilename = f"{logs_dir}/coin.{symbol}.log"
            if symbol not in coinfh:
                coinfh[symbol] = open(  # pylint: disable=R1732
                    coinfilename, "wt"
                )  # pylint: disable=R1732
                coinfiles.add(coinfilename)

            coinfh[symbol].write(line)

    for symbol in coinfh:  # pylint: disable=C0206
        coinfh[symbol].close()

    log_msg("compressing logfiles....")
    tasks = []
    with get_context("spawn").Pool(processes=N_TASKS) as pool:
        for coin_filename in coinfiles:
            job = pool.apply_async(compress_file, (coin_filename,))
            tasks.append(job)
        for t in tasks:
            t.get()
    return coinfiles


def wrap_subprocessing(config, config_dir, results_dir, timeout=None):
    """wraps subprocess call"""
    subprocess.run(
        # TODO: tests/fake.yaml? really?
        "python app.py -m backtesting -s tests/fake.yaml "
        + f"-c {config_dir}/{config} >{results_dir}/backtesting.{config}.txt 2>&1",
        shell=True,
        timeout=timeout,
        check=False,
    )


def gather_best_results_from_backtesting_log(log, minimum, kind, word, sortby):
    """parses backtesting.log for the best result for a coin"""
    coins = {}
    results = {}
    if os.path.exists(log):
        with open(log, encoding="utf-8") as lines:
            for line in lines:
                _profit, _, _, wls, cfgname, _cfg = line[7:].split("|")
                if not word in cfgname:
                    continue
                profit = float(_profit)
                if profit < 0:
                    continue

                if profit < float(minimum):
                    continue

                coin = cfgname[9:].split(".")[0]
                w, l, s, h = [int(x[1:]) for x in wls.split(",")]

                # drop any results containing losses, stales, or holds
                if sortby == "wins":
                    if l != 0 or s != 0 or h != 0 or w == 0:
                        continue

                coincfg = eval(_cfg)["TICKERS"][coin]  # pylint: disable=W0123
                if coin not in coins:
                    coins[coin] = {
                        "profit": profit,
                        "wls": wls,
                        "w": w,
                        "l": l,
                        "s": s,
                        "h": h,
                        "cfgname": cfgname,
                        "coincfg": coincfg,
                    }

                if coin in coins:
                    if sortby == "profit":
                        if profit > coins[coin]["profit"]:
                            coins[coin] = {
                                "profit": profit,
                                "wls": wls,
                                "w": w,
                                "l": l,
                                "s": s,
                                "h": h,
                                "cfgname": cfgname,
                                "coincfg": coincfg,
                            }
                    else:
                        if w >= coins[coin]["w"]:
                            # if this run has the same amount of wins but higher
                            # profit, then keep the old one.
                            # we are aiming for the safest number of wins, not
                            # the highest profit.
                            if (
                                w == coins[coin]["w"]
                                and profit > coins[coin]["profit"]
                            ):
                                continue
                            coins[coin] = {
                                "profit": profit,
                                "wls": wls,
                                "w": w,
                                "l": l,
                                "s": s,
                                "h": h,
                                "cfgname": cfgname,
                                "coincfg": coincfg,
                            }

        _coins = coins
        coins = OrderedDict(sorted(_coins.items(), key=lambda x: x[1]["w"]))
        for coin in coins:
            if kind == "coincfg":
                results[coin] = coins[coin]["coincfg"]
    return results


def generate_coin_template_config_file(coin, strategy, cfg, config_dir):
    """generates a config.yaml for a coin"""

    tmpl = Template(
        """{
    "STRATEGY": "$STRATEGY",
    "PAUSE_FOR": $PAUSE_FOR,
    "INITIAL_INVESTMENT": $INITIAL_INVESTMENT,
    "MAX_COINS": $MAX_COINS,
    "PAIRING": "$PAIRING",
    "CLEAR_COIN_STATS_AT_BOOT": $CLEAR_COIN_STATS_AT_BOOT,
    "CLEAR_COIN_STATS_AT_SALE": $CLEAR_COIN_STATS_AT_SALE,
    "DEBUG": $DEBUG,
    "TRADING_FEE": $TRADING_FEE,
    "SELL_AS_SOON_IT_DROPS": $SELL_AS_SOON_IT_DROPS,
    "STOP_BOT_ON_LOSS": $STOP_BOT_ON_LOSS,
    "STOP_BOT_ON_STALE": $STOP_BOT_ON_STALE,
    "ENABLE_NEW_LISTING_CHECKS": False,
    "KLINES_CACHING_SERVICE_URL": $KLINES_CACHING_SERVICE_URL,
    "TICKERS": {
      "$COIN": {
          "BUY_AT_PERCENTAGE": $BUY_AT_PERCENTAGE,
          "SELL_AT_PERCENTAGE": $SELL_AT_PERCENTAGE,
          "STOP_LOSS_AT_PERCENTAGE": $STOP_LOSS_AT_PERCENTAGE,
          "TRAIL_TARGET_SELL_PERCENTAGE": $TRAIL_TARGET_SELL_PERCENTAGE,
          "TRAIL_RECOVERY_PERCENTAGE": $TRAIL_RECOVERY_PERCENTAGE,
          "SOFT_LIMIT_HOLDING_TIME": $SOFT_LIMIT_HOLDING_TIME,
          "HARD_LIMIT_HOLDING_TIME": $HARD_LIMIT_HOLDING_TIME,
          "NAUGHTY_TIMEOUT": $NAUGHTY_TIMEOUT,
          "KLINES_TREND_PERIOD": "$KLINES_TREND_PERIOD",
          "KLINES_SLICE_PERCENTAGE_CHANGE": $KLINES_SLICE_PERCENTAGE_CHANGE
      }
     },
    "PRICE_LOGS": ["log/coin.$COIN.log.gz"]
    }"""
    )

    with open(f"{config_dir}/coin.{coin}.yaml", "wt") as f:
        f.write(
            tmpl.substitute(
                {
                    "COIN": coin,
                    "PAUSE_FOR": cfg["PAUSE_FOR"],
                    "INITIAL_INVESTMENT": cfg["INITIAL_INVESTMENT"],
                    "MAX_COINS": cfg["MAX_COINS"],
                    "PAIRING": cfg["PAIRING"],
                    "CLEAR_COIN_STATS_AT_BOOT": cfg[
                        "CLEAR_COIN_STATS_AT_BOOT"
                    ],
                    "CLEAR_COIN_STATS_AT_SALE": cfg[
                        "CLEAR_COIN_STATS_AT_SALE"
                    ],
                    "DEBUG": cfg["DEBUG"],
                    "TRADING_FEE": cfg["TRADING_FEE"],
                    "SELL_AS_SOON_IT_DROPS": cfg["SELL_AS_SOON_IT_DROPS"],
                    "BUY_AT_PERCENTAGE": cfg["BUY_AT_PERCENTAGE"],
                    "SELL_AT_PERCENTAGE": cfg["SELL_AT_PERCENTAGE"],
                    "STOP_LOSS_AT_PERCENTAGE": cfg["STOP_LOSS_AT_PERCENTAGE"],
                    "TRAIL_TARGET_SELL_PERCENTAGE": cfg[
                        "TRAIL_TARGET_SELL_PERCENTAGE"
                    ],
                    "TRAIL_RECOVERY_PERCENTAGE": cfg[
                        "TRAIL_RECOVERY_PERCENTAGE"
                    ],
                    "SOFT_LIMIT_HOLDING_TIME": cfg["SOFT_LIMIT_HOLDING_TIME"],
                    "HARD_LIMIT_HOLDING_TIME": cfg["HARD_LIMIT_HOLDING_TIME"],
                    "NAUGHTY_TIMEOUT": cfg["NAUGHTY_TIMEOUT"],
                    "KLINES_TREND_PERIOD": cfg["KLINES_TREND_PERIOD"],
                    "KLINES_SLICE_PERCENTAGE_CHANGE": cfg[
                        "KLINES_SLICE_PERCENTAGE_CHANGE"
                    ],
                    "KLINES_CACHING_SERVICE_URL": cfg.get(
                        "KLINES_CACHING_SERVICE_URL", "http://klines:8999"
                    ),
                    "STRATEGY": strategy,
                    "STOP_BOT_ON_LOSS": cfg.get("STOP_BOT_ON_LOSS", False),
                    "STOP_BOT_ON_STALE": cfg.get("STOP_BOT_ON_STALE", False),
                }
            )
        )


def generate_config_for_tuned_strategy(strategy, cfg, results, logfile):
    """generates a config.yaml for a final strategy run"""
    tmpl = Template(
        """{
    "STRATEGY": "$STRATEGY",
    "PAUSE_FOR": $PAUSE_FOR,
    "INITIAL_INVESTMENT": $INITIAL_INVESTMENT,
    "RE_INVEST_PERCENTAGE": $RE_INVEST_PERCENTAGE,
    "MAX_COINS": $MAX_COINS,
    "PAIRING": "$PAIRING",
    "CLEAR_COIN_STATS_AT_BOOT": $CLEAR_COIN_STATS_AT_BOOT,
    "CLEAR_COIN_STATS_AT_SALE": $CLEAR_COIN_STATS_AT_SALE,
    "DEBUG": $DEBUG,
    "TRADING_FEE": $TRADING_FEE,
    "SELL_AS_SOON_IT_DROPS": $SELL_AS_SOON_IT_DROPS,
    "ENABLE_NEW_LISTING_CHECKS_AGE_IN_DAYS": $ENABLE_NEW_LISTING_CHECKS_AGE_IN_DAYS,
    "KLINES_CACHING_SERVICE_URL": $KLINES_CACHING_SERVICE_URL,
    "TICKERS": $RESULTS,
    "PRICE_LOGS": $LOGFILE
    }"""
    )

    with open(f"configs/{strategy}.yaml", "wt") as f:
        f.write(
            tmpl.substitute(
                {
                    "PAUSE_FOR": cfg["PAUSE_FOR"],
                    "INITIAL_INVESTMENT": cfg["INITIAL_INVESTMENT"],
                    "RE_INVEST_PERCENTAGE": cfg.get(
                        "RE_INVEST_PERCENTAGE", 100
                    ),
                    "MAX_COINS": cfg["MAX_COINS"],
                    "PAIRING": cfg["PAIRING"],
                    "CLEAR_COIN_STATS_AT_BOOT": cfg[
                        "CLEAR_COIN_STATS_AT_BOOT"
                    ],
                    "CLEAR_COIN_STATS_AT_SALE": cfg[
                        "CLEAR_COIN_STATS_AT_SALE"
                    ],
                    "DEBUG": cfg["DEBUG"],
                    "TRADING_FEE": cfg["TRADING_FEE"],
                    "SELL_AS_SOON_IT_DROPS": cfg["SELL_AS_SOON_IT_DROPS"],
                    "KLINES_CACHING_SERVICE_URL": cfg.get(
                        "KLINES_CACHING_SERVICE_URL", "http://klines:8999"
                    ),
                    "STRATEGY": strategy,
                    "RESULTS": results,
                    "LOGFILE": [logfile],
                    "ENABLE_NEW_LISTING_CHECKS": True,
                    "ENABLE_NEW_LISTING_CHECKS_AGE_IN_DAYS": cfg.get(
                        "ENABLE_NEW_LISTING_CHECKS_AGE_IN_DAYS", 31
                    ),
                }
            )
        )


def run_tuned_config(strategies, config_dir, results_dir):
    """run final tuned config"""
    # run_tuned_config
    with get_context("spawn").Pool(processes=N_TASKS) as pool:
        tasks = []
        for strategy in strategies:
            # first check if our config to test actually contain any tickers
            # if not we will skip this round
            with open(f"{config_dir}/{strategy}.yaml") as cf:
                tickers = yaml.safe_load(cf.read())["TICKERS"]
            if not tickers:
                log_msg(
                    f"automated-backtesting: no tickers in {strategy} yaml, skipping run"
                )
                continue

            job = pool.apply_async(
                wrap_subprocessing,
                (f"{strategy}.yaml", config_dir, results_dir),
            )
            tasks.append(job)
        for t in tasks:
            t.get()


def cleanup(config_dir="configs", results_dir="results", logs_dir="log"):
    """clean files"""
    for item in glob.glob(f"{config_dir}/coin.*.yaml"):
        os.remove(item)
    for item in glob.glob(f"{results_dir}/backtesting.coin.*.txt"):
        os.remove(item)
    for item in glob.glob(f"{logs_dir}/backtesting.coin.*.log.gz"):
        os.remove(item)


def generate_all_coin_config_files(
    coinfiles, config, sortby, strategy, config_dir="configs"
):
    """generate coin config backtesting files"""
    for coin in coinfiles:
        symbol = coin.split(".")[1]
        # on 'wins' we don't want to keep on processing our logfiles
        # when we hit a STOP_LOSS
        if sortby == "wins":
            config["STOP_BOT_ON_LOSS"] = True
            config["STOP_BOT_ON_STALE"] = True

        # and we generate a specific coin config file for that strategy
        generate_coin_template_config_file(
            symbol, strategy, config, config_dir
        )


def process_all_coin_files(
    coinfiles, config_dir="configs", results_dir="results"
):
    """process all coin files"""
    tasks = []
    with get_context("spawn").Pool(processes=N_TASKS) as pool:
        for coin in coinfiles:
            symbol = coin.split(".")[1]
            # then we backtesting this strategy run against each coin
            # ocasionally we get stuck runs, so we timeout a coin run
            # to a maximum of 15 minutes
            job = pool.apply_async(
                wrap_subprocessing,
                (f"coin.{symbol}.yaml", config_dir, results_dir, 900),
            )
            tasks.append(job)

        for t in tasks:
            try:
                t.get()
            except subprocess.TimeoutExpired as excp:
                log_msg(f"timeout while running: {excp}")


def process_strategy_run(
    run, strategy, min_profit, sortby, cfgs, coinfiles, config_dir
):
    """run strategy"""
    # in each strategy we will have multiple runs
    log_msg(
        " ".join(
            [
                f"backtesting {run} on {strategy} for {min_profit}",
                f"on {sortby} mode",
            ]
        )
    )

    # merge defaults with the strategy config
    config = {
        **cfgs["DEFAULTS"],
        **cfgs["STRATEGIES"][strategy][run],
    }
    generate_all_coin_config_files(
        coinfiles, config, sortby, strategy, config_dir
    )
    process_all_coin_files(coinfiles)


def log_msg(msg):
    """prefix message with timestamp"""
    now = datetime.now().strftime("%H:%M:%S")
    print(f"{now} AUTOMATED-BACKTESTING: {msg}")


def cli():
    """parse arguments"""
    parser = argparse.ArgumentParser()
    parser.add_argument("-l", "--log", help="logfile")
    parser.add_argument("-c", "--cfgs", help="backtesting cfg")
    parser.add_argument("-m", "--min", help="min coin profit")
    parser.add_argument("-f", "--filter", help="filter by")
    parser.add_argument("-s", "--sortby", help="sort by 'profit' or 'wins'")
    parser.add_argument(
        "-cd", "--config-dir", help="configs directory", default="configs"
    )
    parser.add_argument(
        "-rd", "--results-dir", help="results directory", default="results"
    )
    parser.add_argument(
        "-ld", "--logs-dir", help="logs directory", default="log"
    )
    parser.add_argument(
        "-rfbt",
        "--run-final-backtest",
        help="run final backtesting?",
        default="True",
    )
    args = parser.parse_args()

    with open(args.cfgs, "rt") as f:
        cfgs = yaml.safe_load(f.read())

    return [
        cfgs,
        args.log,
        args.min,
        args.filter,
        args.sortby,
        args.config_dir,
        args.results_dir,
        args.logs_dir,
        False if args.run_final_backtest != "True" else True,
    ]


def gather_best_results_from_run(coinfiles, sortby, results_dir):
    """finds the best results from run"""
    wins_re = r".*INFO.*\swins:([0-9]+)\slosses:([0-9]+)\sstales:([0-9]+)\sholds:([0-9]+)"
    balance_re = r".*INFO.*final\sbalance:\s(-?[0-9]+\.[0-9]+)"

    highest_profit = 0
    coin_with_highest_profit = ""

    run = {}
    run["total_wins"] = 0
    run["total_losses"] = 0
    run["total_stales"] = 0
    run["total_holds"] = 0
    run["total_profit"] = 0

    # TODO: parsing logfiles is not nice, rework this in app.py
    for coinfile in coinfiles:
        symbol = coinfile.split(".")[1]
        results_txt = f"{results_dir}/backtesting.coin.{symbol}.yaml.txt"
        with open(results_txt) as f:
            run_results = f.read()

        wins, losses, stales, holds = re.search(wins_re, run_results).groups()

        balance = float(re.search(balance_re, run_results).groups()[0])

        if sortby == "wins":
            if (int(losses) + int(stales) + int(holds)) == 0:
                run["total_wins"] += int(wins)
                run["total_losses"] += int(losses)
                run["total_stales"] += int(stales)
                run["total_holds"] += int(holds)
                run["total_profit"] += float(balance)
        else:
            run["total_wins"] += int(wins)
            run["total_losses"] += int(losses)
            run["total_stales"] += int(stales)
            run["total_holds"] += int(holds)
            run["total_profit"] += float(balance)

        if balance > highest_profit:
            if sortby == "wins":
                if (int(losses) + int(stales) + int(holds)) == 0:
                    coin_with_highest_profit = symbol
                    highest_profit = balance
            else:
                coin_with_highest_profit = symbol
                highest_profit = balance

    log_msg(
        f"sum of all coins profit:{run['total_profit']:.3f}|"
        + f"w:{run['total_wins']},l:{run['total_losses']},"
        + f"s:{run['total_stales']},h:{run['total_holds']}|"
        + "coin with highest profit:"
        + f"{coin_with_highest_profit}:{highest_profit:.3f}"
    )
    return run


def gather_best_results_per_strategy(strategy, this):
    """finds the best results in the strategy"""
    best_run = ""
    best_profit_in_runs = 0
    for run in this.keys():
        if this[run]["total_profit"] >= best_profit_in_runs:
            best_run = run
            best_profit_in_runs = this[run]["total_profit"]
    log_msg(
        f"{strategy} best run {best_run} profit: {best_profit_in_runs:.3f}"
    )


def gather_strategies_best_runs(this):
    """iterates over strategies and finds the best run in each"""
    log_msg("STRATEGIES BEST RUNS:")
    best = {}
    for strategy in this.keys():
        best[strategy] = {"best_run": "", "best_profit": 0}
        for run in this[strategy].keys():
            if (
                this[strategy][run]["total_profit"]
                >= best[strategy]["best_profit"]
            ):
                best[strategy]["best_profit"] = this[strategy][run][
                    "total_profit"
                ]
                best[strategy]["best_run"] = run
    for strategy in best.keys():  # pylint: disable=C0201,C0206
        log_msg(
            f"{strategy} best run {best[strategy]['best_run']} "
            + f"with profit: {best[strategy]['best_profit']:.3f}"
        )


def main():
    """main"""
    (
        cfgs,
        logfile,
        min_profit,
        filterby,
        sortby,
        config_dir,
        results_dir,
        logs_dir,
        run_final_backtest,
    ) = cli()

    coinfiles = split_logs_into_coins(logfile, cfgs, logs_dir="log")

    if os.path.exists("cache/binance.client"):
        os.remove("cache/binance.client")

    top_results_per_run = {}

    for strategy in cfgs["STRATEGIES"]:

        if os.path.exists(f"{logs_dir}/backtesting.log"):
            os.remove(f"{logs_dir}/backtesting.log")

        top_results_per_run[strategy] = {}

        for run in cfgs["STRATEGIES"][strategy]:
            process_strategy_run(
                run, strategy, min_profit, sortby, cfgs, coinfiles, config_dir
            )
            top_results_per_run[strategy][run] = gather_best_results_from_run(
                coinfiles, sortby, results_dir
            )

        gather_best_results_per_strategy(
            strategy, top_results_per_run[strategy]
        )

        # finally we soak up the backtesting.log and generate the best
        # config from all the runs in this strategy
        results = gather_best_results_from_backtesting_log(
            f"{logs_dir}/backtesting.log",
            min_profit,
            "coincfg",
            filterby,
            sortby,
        )
        generate_config_for_tuned_strategy(
            strategy, cfgs["DEFAULTS"], results, logfile
        )
    # cleanup backtesting.log
    if os.path.exists(f"{logs_dir}/backtesting.log"):
        os.remove(f"{logs_dir}/backtesting.log")

    gather_strategies_best_runs(top_results_per_run)
    if run_final_backtest:
        run_tuned_config(cfgs["STRATEGIES"], config_dir, results_dir)
    cleanup(config_dir, results_dir, logs_dir)


if __name__ == "__main__":
    # max number of parallel tasks we will run
    n_cpus: Optional[int] = os.cpu_count()
    smp_multiplier = float(os.getenv("SMP_MULTIPLIER", str(1)))
    N_TASKS = int(n_cpus if n_cpus is not None else 1 * smp_multiplier)

    main()

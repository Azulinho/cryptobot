"""automated-backtesting.py"""
import argparse
import concurrent.futures
import glob
import os
import shutil
import subprocess
from collections import OrderedDict
from string import Template

import yaml
from xopen import xopen


def backup_backtesting_log():
    """makes a backup of backtesting.log"""
    shutil.copyfile("log/backtesting.log", "log/backtesting.log.backup")


def compress_file(filename):
    """compresses coin price.log file"""
    with open(filename) as uncompressed:
        print(f"\ncompressing file {filename}\n")
        with xopen(f"{filename}.gz", mode="wt") as compressed:
            shutil.copyfileobj(uncompressed, compressed)
    os.remove(filename)


def split_logs_into_coins(filename, cfg):
    """splits one price.log into individual coin price.log files"""
    coinfiles = set()
    coinfh = {}
    print(f"\nprocessing file {str(filename)}\n")
    pairing = cfg["DEFAULTS"]["PAIRING"]
    with xopen(f"{filename}", "rt") as logfile:
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

            coinfilename = f"log/coin.{symbol}.log"
            if symbol not in coinfh:
                coinfh[symbol] = open(coinfilename, "wt")
                coinfiles.add(coinfilename)

            coinfh[symbol].write(line)

    for symbol in coinfh:
        coinfh[symbol].close()

    tasks = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=N_TASKS) as pool:
        for coin_filename in coinfiles:
            job = pool.submit(compress_file, coin_filename)
            tasks.append(job)
        for t in tasks:
            t.result()
    return coinfiles


def wrap_subprocessing(config, timeout=None):
    """wraps subprocess call"""
    subprocess.run(
        "python app.py -m backtesting -s tests/fake.yaml "
        + f"-c configs/{config} >results/{config}.txt 2>&1",
        shell=True,
        timeout=timeout,
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

                coincfg = eval(_cfg)["TICKERS"][coin]
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
                            # if this run has the same amount of wins but lower
                            # profit, then keep the old one
                            if (
                                w == coins[coin]["w"]
                                and profit < coins[coin]["profit"]
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


def generate_coin_template_config_file(coin, strategy, cfg):
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
    "ENABLE_NEW_LISTING_CHECKS": False,
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

    print(f"\ncreating {coin} config for {strategy}\n")
    with open(f"configs/coin.{coin}.yaml", "wt") as f:
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
                    "STRATEGY": strategy,
                    "STOP_BOT_ON_LOSS": cfg.get("STOP_BOT_ON_LOSS", False),
                }
            )
        )


def generate_config_for_tuned_strategy_run(strategy, cfg, results, logfile):
    """generates a config.yaml for a final strategy run"""
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
    "ENABLE_NEW_LISTING_CHECKS_AGE_IN_DAYS": $ENABLE_NEW_LISTING_CHECKS_AGE_IN_DAYS,
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
                    "STRATEGY": strategy,
                    "RESULTS": results,
                    "LOGFILE": [logfile],
                    "ENABLE_NEW_LISTING_CHECKS_AGE_IN_DAYS": cfg.get(
                        "ENABLE_NEW_LISTING_CHECKS_AGE_IN_DAYS", 31
                    ),
                }
            )
        )


def main():
    """main"""
    parser = argparse.ArgumentParser()
    parser.add_argument("-l", "--log", help="logfile")
    parser.add_argument("-c", "--cfgs", help="backtesting cfg")
    parser.add_argument("-m", "--min", help="min coin profit")
    parser.add_argument("-f", "--filter", help="filter by")
    parser.add_argument("-s", "--sortby", help="sort by 'profit' or 'wins'")
    args = parser.parse_args()

    with open(args.cfgs, "rt") as f:
        cfgs = yaml.safe_load(f.read())

    logfile = args.log
    coinfiles = split_logs_into_coins(logfile, cfgs)

    # clean up old binance client cache file
    if os.path.exists("cache/binance.client"):
        os.remove("cache/binance.client")

    with concurrent.futures.ProcessPoolExecutor(max_workers=N_TASKS) as pool:
        # process one strategy at a time
        for strategy in cfgs["STRATEGIES"]:
            # cleanup backtesting.log
            if os.path.exists("log/backtesting.log"):
                os.remove("log/backtesting.log")

            for run in cfgs["STRATEGIES"][strategy]:
                # in each strategy we will have multiple runs
                for coin in coinfiles:
                    symbol = coin.split(".")[1]
                    config = {
                        **cfgs["DEFAULTS"],
                        **cfgs["STRATEGIES"][strategy][run],
                    }
                    # on 'wins' we don't want to keep on processing our logfiles
                    # when we hit a STOP_LOSS
                    if args.sortby == "wins":
                        config["STOP_BOT_ON_LOSS"] = True

                    # and we generate a specific coin config file for that strategy
                    generate_coin_template_config_file(
                        symbol, strategy, config
                    )

                tasks = []
                for coin in coinfiles:
                    symbol = coin.split(".")[1]
                    print(
                        f"\nbacktesting {symbol} for {run} on {strategy} for"
                        + f"{args.min} on {args.sortby}\n"
                    )
                    # then we backtesting this strategy run against each coin
                    # ocasionally we get stuck runs, so we timeout a coin run
                    # to a maximum of 15 minutes
                    job = pool.submit(
                        wrap_subprocessing, f"coin.{symbol}.yaml", 900
                    )
                    tasks.append(job)

                for t in tasks:
                    try:
                        t.result()
                    except subprocess.TimeoutExpired as excp:
                        print(f"timeout while running: {excp}")

            # finally we soak up the backtesting.log and generate the best
            # config from all the runs in this strategy
            results = gather_best_results_from_backtesting_log(
                "log/backtesting.log",
                args.min,
                "coincfg",
                args.filter,
                args.sortby,
            )
            generate_config_for_tuned_strategy_run(
                strategy, cfgs["DEFAULTS"], results, logfile
            )
        # cleanup backtesting.log
        if os.path.exists("log/backtesting.log"):
            os.remove("log/backtesting.log")

    with concurrent.futures.ProcessPoolExecutor(max_workers=N_TASKS) as pool:
        tasks = []
        for strategy in cfgs["STRATEGIES"]:
            job = pool.submit(wrap_subprocessing, f"{strategy}.yaml")
            tasks.append(job)
        for t in tasks:
            t.result()
    for item in glob.glob("configs/coin.*.yaml"):
        os.remove(item)
    for item in glob.glob("results/coin.*.txt"):
        os.remove(item)
    for item in glob.glob("log/coin.*.log.gz"):
        os.remove(item)


if __name__ == "__main__":
    # max number of parallel tasks we will run
    N_TASKS = int(os.cpu_count() * float(os.getenv("SMP_MULTIPLIER", "1")))

    main()

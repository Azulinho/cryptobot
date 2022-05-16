import argparse
import logging
import os
import re
import sys
import traceback
import glob
import shutil
import subprocess
import yaml
import json
import multiprocessing as mp

from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from functools import partial
from string import Template
from pathlib import Path
from xopen import xopen


def backup_backtesting_log():
    shutil.copyfile("log/backtesting.log", "log/backtesting.log.backup")


def compress_file(filename):
    with open(filename) as uncompressed:
        print(f"\ncompressing file {filename}\n")
        with xopen(f"{filename}.gz", mode="wt") as compressed:
            shutil.copyfileobj(uncompressed, compressed)
    os.remove(filename)


def split_logs_into_coins(filename):
    coinfiles = set()
    coinfh = {}
    print(f"\nprocessing file {str(filename)}\n")
    with xopen(f"{filename}", "rt") as logfile:
        for line in logfile:
            parts = line.split(" ")
            symbol = parts[2]

            coinfilename = f"log/coin.{symbol}.log"
            if symbol not in coinfh:
                coinfh[symbol] = open(coinfilename, "wt")
                coinfiles.add(coinfilename)

            coinfh[symbol].write(line)

    for symbol in coinfh:
        coinfh[symbol].close()

    tasks = []
    with mp.Pool(processes=os.cpu_count()) as pool:
        for filename in coinfiles:
            job = pool.apply_async(compress_file, (filename,))
            tasks.append(job)
        for t in tasks:
            t.get()
    return coinfiles


def wrap_subprocessing(config):
    subprocess.run(
        f"python app.py -m backtesting -s tests/fake.yaml -c configs/{config} >results/{config}.txt 2>&1",
        shell=True,
    )


def gather_best_results_from_backtesting_log(log, min, kind, word, strategy, sortby):
    coins = {}
    results = dict()
    if os.path.exists(log):
        with open(log, encoding="utf-8") as lines:
            for line in lines:
                _profit, investment, days, wls, cfgname, _cfg = line[7:].split(
                    "|"
                )
                if not word in cfgname:
                    continue
                profit = float(_profit)
                if profit < 0:
                    continue

                if profit < float(min):
                    continue

                coin = cfgname[9:].split(".")[0]
                w, l, s, h = [ int(x[1:]) for x in wls.split(",")]

                # drop any results containing losses, stales, or holds
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
                        if w > coins[coin]["w"]:
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
                    "STOP_BOT_ON_LOSS": cfg["STOP_BOT_ON_LOSS"]
                }
            )
        )


def generate_config_for_tuned_strategy_run(strategy, cfg, results, logfile):
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
                }
            )
        )



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-l", "--log", help="logfile")
    parser.add_argument("-c", "--cfgs", help="backtesting cfg")
    parser.add_argument("-m", "--min", help="min coin profit")
    parser.add_argument("-f", "--filter", help="filter by")
    parser.add_argument("-s", "--sortby", help="sort by 'profit' or 'wins'")
    args = parser.parse_args()

    logfile = args.log
    coinfiles = split_logs_into_coins(logfile)
    with open(args.cfgs, "rt") as f:
        cfgs = yaml.safe_load(f.read())

    # clean up old binance client cache file
    if os.path.exists("cache/binance.client"):
        os.remove("cache/binance.client")

    with mp.Pool(processes=os.cpu_count()) as pool:
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
                    print(f"\nbacktesting {symbol} for {run} on {strategy} for {args.min} on {args.sortby}\n")
                    # then we backtesting this strategy run against each coin
                    job = pool.apply_async(
                        wrap_subprocessing, (f"coin.{symbol}.yaml",)
                    )
                    tasks.append(job)

                for t in tasks:
                    t.get()

            # finally we soak up the backtesting.log and generate the best
            # config from all the runs in this strategy
            results = gather_best_results_from_backtesting_log(
                "log/backtesting.log",
                args.min,
                "coincfg",
                args.filter,
                strategy,
                args.sortby
            )
            generate_config_for_tuned_strategy_run(
                strategy, cfgs["DEFAULTS"], results, logfile
            )
        # cleanup backtesting.log
        if os.path.exists("log/backtesting.log"):
            os.remove("log/backtesting.log")

    with mp.Pool(processes=os.cpu_count()) as pool:
        for strategy in cfgs["STRATEGIES"]:
            tasks = []
            job = pool.apply_async(wrap_subprocessing, (f"{strategy}.yaml",))
            tasks.append(job)
        for t in tasks:
            t.get()
    for item in glob.glob('configs/coin.*.yaml'):
        os.remove(item)
    for item in glob.glob('results/coin.*.txt'):
        os.remove(item)
    for item in glob.glob('log/coin.*.log.gz'):
        os.remove(item)


if __name__ == "__main__":
    main()

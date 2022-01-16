import argparse
import logging
import os
import re
import sys
import traceback
import gzip
import shutil
import multiprocessing as mp
import random
import string
import yaml
import subprocess
import time
import json

from collections import OrderedDict
from pathlib import Path

import random, string

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-l", "--log", help="backtesting.log file", default="log/backtesting.log")
    parser.add_argument("-m", "--min", help="min profit")
    parser.add_argument("-o", "--output", help="output [cfgname|coincfg]", default="cfgname")
    parser.add_argument("-f", "--filter", help="filter cfgname", default="")
    args = parser.parse_args()

    coins = {}
    with open(args.log, encoding="utf-8") as lines:
        for line in lines:
            _profit, investment, days, wls, cfgname, _cfg = line[7:].split('|')
            if not args.filter in cfgname:
                continue
            profit = float(_profit)
            if profit < 0:
                continue

            if profit < float(args.min):
                continue

            coin = cfgname[9:].split(".")[0]
            coincfg=eval(_cfg)['TICKERS'][coin]
            if coin not in coins:
                coins[coin] = {
                    "profit": profit,
                    "wls": wls,
                    "cfgname": cfgname,
                    "coincfg": coincfg
                }

            if coin in coins:
                if profit > coins[coin]['profit']:
                    coins[coin] = {
                        "profit": profit,
                        "wls": wls,
                        "cfgname": cfgname,
                        "coincfg": coincfg
                    }

    _coins = coins
    coins = OrderedDict(sorted(_coins.items(), key=lambda x: x[1]['profit']))
    for coin in coins:
        if args.output == "cfgname":
            print(f"{coin}: {coins[coin]['profit']} {coins[coin]['wls']} {coins[coin]['cfgname']}")
        if args.output == "coincfg":
            print(f"{coin}: {coins[coin]['wls']} {coins[coin]['coincfg']}")

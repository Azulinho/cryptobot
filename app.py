""" CryptoBot for Binance """

import argparse
import importlib
import json
import logging
import sys
import threading
from os import getpid, unlink
from os.path import exists
from typing import Any

import colorlog
import epdb
import yaml
from binance.client import Client

# allow migration from old pickle format to new format
# old pickle cointains app.Bot, app.Coin
from lib.bot import Bot  # pylint: disable=unused-import
from lib.coin import Coin  # pylint: disable=unused-import
from lib.helpers import cached_binance_client


def control_center() -> None:
    """pdb remote endpoint"""
    while True:
        try:
            epdb.serve(port=5555)
        except Exception:  # pylint: disable=broad-except
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", help="config.yaml file")
    parser.add_argument("-s", "--secrets", help="secrets.yaml file")
    parser.add_argument(
        "-m", "--mode", help='bot mode ["live", "backtesting", "testnet"]'
    )
    parser.add_argument(
        "-ld", "--logs-dir", help="logs directory", default="log"
    )
    args = parser.parse_args()

    with open(args.config, encoding="utf-8") as _f:
        cfg = yaml.safe_load(_f.read())
    with open(args.secrets, encoding="utf-8") as _f:
        secrets = yaml.safe_load(_f.read())
    cfg["MODE"] = args.mode

    PID = getpid()
    c_handler = colorlog.StreamHandler(sys.stdout)
    c_handler.setFormatter(
        colorlog.ColoredFormatter(
            "%(log_color)s[%(levelname)s] %(message)s",
            log_colors={
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "red,bg_white",
            },
        )
    )
    c_handler.setLevel(logging.INFO)

    if cfg["DEBUG"]:
        f_handler = logging.FileHandler(f"{args.logs_dir}/debug.log")
        f_handler.setLevel(logging.DEBUG)

        logging.basicConfig(
            level=logging.DEBUG,
            format=" ".join(
                [
                    "(%(asctime)s)",
                    f"({PID})",
                    "(%(lineno)d)",
                    "(%(funcName)s)",
                    "[%(levelname)s]",
                    "%(message)s",
                ]
            ),
            handlers=[f_handler, c_handler],
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    else:
        logging.basicConfig(
            level=logging.INFO,
            handlers=[c_handler],
        )

    if args.mode == "backtesting":
        client = cached_binance_client(
            secrets["ACCESS_KEY"], secrets["SECRET_KEY"]
        )
    else:
        client = Client(secrets["ACCESS_KEY"], secrets["SECRET_KEY"])

    module = importlib.import_module(f"strategies.{cfg['STRATEGY']}")
    Strategy = getattr(module, "Strategy")

    bot: Any = Strategy(client, args.config, cfg)

    logging.info(
        f"running in {bot.mode} mode with "
        + f"{json.dumps(args.config, indent=4)}"
    )

    # clean up any stale control/STOP files
    if exists("control/STOP"):
        unlink("control/STOP")

    if bot.mode in ["testnet", "live"]:
        # start command-control-center (ipdb on port 5555)
        t = threading.Thread(target=control_center)
        t.daemon = True
        t.start()

    if bot.mode == "backtesting":
        bot.backtesting()

    if bot.mode == "logmode":
        bot.logmode()

    if bot.mode == "testnet":
        bot.client.API_URL = "https://testnet.binance.vision/api"
        bot.run()

    if bot.mode == "live":
        bot.run()

    bot.print_final_balance_report()

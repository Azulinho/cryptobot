""" config-endpoint-service """
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timedelta
from typing import Dict

import pandas  # pylint: disable=E0401
import yaml
from flask import Flask, jsonify
from isal import igzip

g: Dict = {}
app = Flask(__name__)


def log_msg(msg):
    """logs out message prefixed with timestamp"""
    now = datetime.now().strftime("%H:%M:%S")
    print(f"{now} {msg}")


def backtesting_dates(days):
    """returns a list of dates, up to 'days' before today"""
    start_date = datetime.now()
    dates = (
        pandas.date_range(
            start_date - timedelta(days=int(days) - 1), start_date, freq="d"
        )
        .strftime("%Y%m%d")
        .tolist()
    )
    return dates


def create_zipped_logfile(
    dates, pair, logs_dir="log", work_dir=None, symbols=None
):
    """
    generates lastfewdays.log.gz from the provided list of price.log files
    excluding any symbol in the excluded list, and not matching pairing
    also if symbols[] is provided, then only symbols in that list is used
    to generate the lastfewdays.log.gz
    """
    if symbols is None:
        symbols = []

    if work_dir is None:
        work_dir = logs_dir

    log_msg("creating gzip lastfewdays.log.gz")

    with open(f"{work_dir}/lastfewdays.log", "wt") as w:
        for day in dates:
            log = f"{logs_dir}/{day}.log.gz"

            if not os.path.exists(log):
                log_msg(f"WARNING: {log} does not exist")
                continue
            with igzip.open(log, "rt") as r:
                for line in r:
                    if pair not in line:
                        continue
                    # don't process any BEAR/BULL/UP/DOWN lines
                    excluded = [
                        f"DOWN{pair}",
                        f"UP{pair}",
                        f"BEAR{pair}",
                        f"BULL{pair}",
                    ]
                    if any(symbol in str(line) for symbol in excluded):
                        continue

                    if symbols:
                        if not any(symbol in line for symbol in symbols):
                            continue
                    w.write(str(line))
    with igzip.open(f"{work_dir}/lastfewdays.log.gz", "wt") as compressed:
        with open(f"{work_dir}/lastfewdays.log", "rt") as uncompressed:
            shutil.copyfileobj(uncompressed, compressed)


def run_automated_backtesting(
    config_file, minimum_profit, sort_by, logs_dir="log"
):
    """calls automated-backtesting"""
    subprocess.run(
        "python -u utils/automated-backtesting.py "
        + f"-l {logs_dir}/lastfewdays.log.gz "
        + f"-c configs/{config_file} "
        + f"-m {minimum_profit} "
        + "-f '' "
        + f"-s {sort_by} "
        + "--run-final-backtest=False",
        shell=True,
        check=False,
    )


def run(backtrack_days, pair, minimum_profit, config_file, sort_by):
    """main block"""
    dates = backtesting_dates(backtrack_days)
    create_zipped_logfile(dates, pair, logs_dir="log", symbols=[])
    run_automated_backtesting(
        config_file, minimum_profit, sort_by, logs_dir="log"
    )


@app.route("/")
def root():
    """Flask / handler"""
    _tuned_config = g["tuned_config"]

    with open(f"configs/{_tuned_config}") as f:
        cfg = yaml.safe_load(f.read())
        hashstr = hashlib.md5(
            (json.dumps(config["TICKERS"], sort_keys=True)).encode("utf-8")
        ).hexdigest()
        config["md5"] = hashstr
    return jsonify(cfg)


def api_endpoint():
    """runs Flask"""
    app.run(debug=True, use_reloader=False, host="0.0.0.0", port=5883)


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", help="config.yaml file")
    parser.add_argument(
        "-b", "--backtrack", help="number of days to backtrack"
    )
    parser.add_argument(
        "-s",
        "--sortby",
        help="greed|number_of_clean_wins|max_profit_on_clean_wins",
    )
    parser.add_argument(
        "-t",
        "--tuned-config",
        help="BuyOnRecoveryAfterDropFromAverageStrategy.yaml",
    )
    parser.add_argument("-p", "--pairing", help="Pair to use")
    parser.add_argument("-m", "--min", help="minimum")

    args = parser.parse_args()

    config = args.config
    backtrack = args.backtrack
    sortby = args.sortby
    tuned_config = args.tuned_config
    pairing = args.pairing
    min_profit = args.min

    g["tuned_config"] = tuned_config

    t = threading.Thread(target=api_endpoint)
    t.daemon = True
    t.start()

    while True:
        time.sleep(1)
        if os.path.exists("control/RUN"):
            log_msg("control/RUN flag found")
            os.unlink("control/RUN")
            run(backtrack, pairing, min_profit, config, sortby)

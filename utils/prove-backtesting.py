""" prove-backtesting """
import argparse
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta
from itertools import islice

import pandas  # pylint: disable=E0401
import yaml  # pylint: disable=E0401
from isal import igzip  # pylint: disable=E0401


def cli():
    """parse arguments"""
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--date", help="test from this date forward")
    parser.add_argument(
        "-c", "--config", help="automated-backtesting yaml config file"
    )
    parser.add_argument(
        "-b", "--backtrack", help="backtrack days for automated-backtesting"
    )
    parser.add_argument(
        "-f", "--forward", help="number of days to forward test "
    )
    parser.add_argument("-m", "--min", help="min coin profit")
    parser.add_argument("-e", "--enddate", help="test until this date")
    parser.add_argument(
        "-s", "--sortby", help="sortby results by profit/wins", default="wins"
    )

    # TODO: the args below are not currently consumed
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
        "-x", "--concurrency", help="SMP_MULTIPLIER value", default="1.0"
    )
    args = parser.parse_args()

    return [
        args.config,
        int(args.date),
        int(args.backtrack),
        int(args.forward),
        int(args.min),
        int(args.enddate),
        args.sortby,
        args.config_dir,
        args.results_dir,
        args.logs_dir,
        args.concurrency,
    ]


def generate_start_dates(start_date, end_date, jump=7):
    """returns a list of dates, with a gap in 'jump' days"""
    start_date = datetime.strptime(str(start_date), "%Y%m%d")
    end_date = datetime.strptime(str(end_date), "%Y%m%d")
    dates = pandas.date_range(start_date, end_date, freq="d").strftime(
        "%Y%m%d"
    )
    start_dates = list(islice(dates, 0, None, jump))
    log_msg(f"using start dates: {start_dates}")
    return start_dates


def backtesting_dates(end_date, days=31):
    """returns a list of dates, up to 'days' before the 'end_date'"""
    start_date = datetime.strptime(str(end_date), "%Y%m%d")
    dates = (
        pandas.date_range(
            start_date - timedelta(days=days - 1), start_date, freq="d"
        )
        .strftime("%Y%m%d")
        .tolist()
    )
    return dates


def prove_backtesting_dates(end_date, days=7):
    """returns a list of dates, up to 'days' past the 'end_date'"""
    start_date = datetime.strptime(str(end_date), "%Y%m%d") + timedelta(days=1)
    end_date = datetime.strptime(str(end_date), "%Y%m%d") + timedelta(
        days=days
    )
    dates = (
        pandas.date_range(start_date, end_date, freq="d")
        .strftime("%Y%m%d")
        .tolist()
    )
    return dates


def run_prove_backtesting(config, results_dir):
    """calls backtesting"""
    subprocess.run(
        "python -u app.py -s secrets/binance.prod.yaml "
        + f"-c configs/{config}  -m  backtesting"
        + f"> {results_dir}/{config}.txt 2>&1",
        shell=True,
        check=False,
    )
    subprocess.run(
        f"grep -E '\[HOLD\]|\[SOLD_BY_' {results_dir}/{config}.txt ",  # pylint: disable=W1401
        shell=True,
        check=False,
    )


def run_automated_backtesting(
    config, min_profit, sortby, logs_dir="log", env={}
):
    """calls automated-backtesting"""
    subprocess.run(
        f"python -u utils/automated-backtesting.py -l {logs_dir}/lastfewdays.log.gz "
        + f"-c configs/{config} -m {min_profit} -f '' -s {sortby} --run-final-backtest=False",
        shell=True,
        check=False,
        env=env,
    )


def create_zipped_logfile(dates, pairing, logs_dir="log", symbols=[]):
    """
    generates lastfewdays.log.gz from the provided list of price.log files
    excluding any symbol in the excluded list, and not matching pairing
    also if symbols[] is provided, then only symbols in that list is used
    to generate the lastfewdays.log.gz
    """
    log_msg("creating gzip lastfewdays.log.gz")

    with open(f"{logs_dir}/lastfewdays.log", "wt") as w:
        for day in dates:
            log = f"{logs_dir}/{day}.log.gz"
            if not os.path.exists(log):
                log_msg(f"WARNING: {log} does not exist")
                continue
            with igzip.open(log, "rt") as r:
                for line in r:
                    if pairing not in line:
                        continue
                    # don't process any BEAR/BULL/UP/DOWN lines
                    excluded = [
                        f"DOWN{pairing}",
                        f"UP{pairing}",
                        f"BEAR{pairing}",
                        f"BULL{pairing}",
                    ]
                    if any(symbol in line for symbol in excluded):
                        continue

                    if symbols:
                        if not any(symbol in line for symbol in symbols):
                            continue
                    w.write(line)
    with igzip.open(f"{logs_dir}/lastfewdays.log.gz", "wt") as compressed:
        with open(f"{logs_dir}/lastfewdays.log", "rt") as uncompressed:
            shutil.copyfileobj(uncompressed, compressed)


def main():
    """main"""

    (
        config_file,
        from_date,
        backtrack_days,
        forward_days,
        min_profit,
        end_date,
        sortby,
        config_dir,
        results_dir,
        logs_dir,
        concurrency,
    ) = cli()

    log_msg(
        f"running from {from_date} to {end_date} "
        + f"backtesting previous {backtrack_days} days every {forward_days} days"
    )
    # we step every 'n' days, in our backtesting and 'forwardtesting'.
    # essentialy we find the start date for every 'forward' days
    # which we will use as an end date for our backtesting, back to the
    # backtrack days to generate a tuned config.
    # this config we then consume from our start_date up to days 'forward'
    # Then we repeat of the following start_date, which is the date after the 'forward_date'

    start_dates = generate_start_dates(from_date, end_date, forward_days)

    with open(f"{config_dir}/{config_file}") as f:
        cfg = yaml.safe_load(f)

    pairing = cfg["DEFAULTS"]["PAIRING"]
    balances = {}
    percent_results = {}
    strategies = cfg["STRATEGIES"].keys()
    for strategy in strategies:
        balances[strategy] = float(cfg["DEFAULTS"]["INITIAL_INVESTMENT"])

    final_balance = 0
    for start_date in start_dates:
        log_msg(
            f"now backtesting previous {backtrack_days}"
            + f" days from end of {start_date}"
        )
        dates = backtesting_dates(end_date=start_date, days=backtrack_days)
        log_msg(dates)
        create_zipped_logfile(dates, pairing, logs_dir)
        log_msg(
            f"starting automated_backtesting using {config_file} for {min_profit}"
        )
        # check for new values for SMP_MULTIPLIER and adjust as needed
        # use this setting in cron jobs to increase/decrease the number of
        # parallel backtesting processes based on the time of the day.
        if os.path.exists("control/SMP_MULTIPLIER"):
            with open("control/SMP_MULTIPLIER") as f:
                concurrency = f.read().strip()
                log_msg(f"control/SMP_MULTIPLIER contains {concurrency}")
            os.unlink("control/SMP_MULTIPLIER")

        # runs automated_backtesting on all strategies
        run_automated_backtesting(
            config=config_file,
            min_profit=min_profit,
            sortby=sortby,
            env={**os.environ, "SMP_MULTIPLIER": concurrency},
        )

        dates = prove_backtesting_dates(
            end_date=start_date, days=int(forward_days)
        )

        with open(f"{config_dir}/{config_file}") as f:
            cfg = yaml.safe_load(f)
            strategies = cfg["STRATEGIES"].keys()

        # TODO: modify this so that we can run all strategies against a set
        # of dates (a logfile),
        # create a log zipped file with only the coins we will be testing
        symbols = set()
        for strategy in strategies:
            with open(f"{config_dir}/{strategy}.yaml") as f:
                cfg = yaml.safe_load(f)
                tickers = cfg["TICKERS"].keys()
            symbols = symbols | tickers

        # if our backtesting gave us no tickers,
        # we'll skip this forward testing run
        if not symbols:
            log_msg("forwardtesting config contains no tickers, skipping run")
            continue

        log_msg(
            f"forwardtesting next {forward_days} days from end of {start_date}"
        )
        log_msg(dates)

        create_zipped_logfile(dates, pairing, logs_dir, symbols)

        for strategy in strategies:
            with open(f"{config_dir}/{strategy}.yaml") as f:
                cfg = yaml.safe_load(f)
            cfg["INITIAL_INVESTMENT"] = balances[strategy]

            _config = "".join(
                [
                    f"{strategy}.{start_date}.f{forward_days}d.",
                    f"b{backtrack_days}d.m{min_profit}.yaml",
                ]
            )
            with open(f"{config_dir}/{_config}", "wt") as c:
                c.write(json.dumps(cfg))

            log_msg(f"calling backtesting with {_config}")
            start_bal = float(balances[strategy])
            log_msg(f"starting balance for {strategy}: {balances[strategy]}")
            run_prove_backtesting(f"{_config}", results_dir)
            with open(f"{results_dir}/{_config}.txt") as results_txt:
                final_balance = float(
                    re.findall(
                        r"final balance: (-?\d+\.\d+)", results_txt.read()
                    )[0]
                )
                balances[strategy] = balances[strategy] + final_balance
                end_bal = float(balances[strategy])
                diff = str(int(100 - ((start_bal / end_bal) * 100)))
                percent_results[strategy] = diff
                if int(diff) > 0:
                    diff = f"+{diff}"
                log_msg(
                    f"final balance for {strategy}: {str(end_bal)} {diff}%"
                )
        log_msg("COMPLETED WITH RESULTS:")
        for strategy in strategies:
            diff = percent_results[strategy]
            if int(diff) > 0:
                diff = f"+{diff}"
            log_msg(f"{strategy}: {balances[strategy]} {diff}%")
    log_msg("PROVE-BACKTESTING: FINISHED")


def log_msg(msg):
    """logs out message prefixed with timestamp"""
    now = datetime.now().strftime("%H:%M:%S")
    print(f"{now} PROVE-BACKTESTING: {msg}")


if __name__ == "__main__":
    main()

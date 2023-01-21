""" retrieves klines for binance suitable for cryptoBot """

import argparse
import gzip
import os
import json
import time
from datetime import datetime, timedelta

from binance.client import Client  # pylint: disable=E0401

client = Client("FAKE", "FAKE")


def get_all_tickers():
    """returns the current list of tickers from binance"""
    _tickers = []
    for item in client.get_all_tickers():
        _tickers.append(item["symbol"])
    return sorted(_tickers)


def pull_klines(k_symbol, k_start, k_end, limit=720):
    """returns klines for a particular day and ticker"""
    k_results = []
    print(f"start: {k_start} end: {k_end}")
    while k_start <= k_end:
        print(f"fetching chunk {k_start} <-> {k_start + (limit * 60000)}")
        klines = client.get_klines(
            symbol=k_symbol,
            interval="1m",
            limit=limit,
            startTime=int(k_start),
            endTime=int(k_start + (limit * 60000)),
        )
        for entry in klines:
            k_results.append(tuple(entry))
        k_start = k_start + (limit * 60000)
    # klines is an expensive API call, so only pull one klines set per second
    time.sleep(0.3)
    return k_results


def daterange(date1, date2):
    """returns a list of dates between 2 dates"""
    dates = []
    for item in range(int((date2 - date1).days) + 1):
        dates.append(date1 + timedelta(item))
    return dates


def generate_index(log_dir="log"):
    """generates index.json with dates <- [coins]"""
    date_list = set()
    symbols_list = set()
    index = {}

    # gather all date.log.gz logs and
    # all symbol dirs
    for item in sorted(os.listdir(log_dir)):
        if (
            os.path.isfile(f"{log_dir}/{item}")
            and item.startswith("20")
            and ".log." in item
        ):
            date = item.split(".")[0]
            date_list.add(date)
        if os.path.isdir(f"{log_dir}/{item}"):
            symbols_list.add(item)

    # we'll store all symbol logs in each date
    for date in sorted(date_list):
        index[date] = set()

    # iterate over all the symbols and gather all the
    # logfiles in in each one of those symbol dirs
    for _symbol in sorted(symbols_list):
        logs = os.listdir(f"{log_dir}/{_symbol}")
        for _log in sorted(logs):
            if not os.path.isfile(f"{log_dir}/{_symbol}/{_log}"):
                continue
            date = _log.split(".")[0]
            index[date].add(_symbol)

    tmp = index
    index = {}
    for date in tmp.keys():  # pylint: disable=C0206,C0201
        index[date] = list(tmp[date])

    with open(f"{log_dir}/index.json", "w", encoding="utf-8") as index_json:
        index_json.write(json.dumps(index, indent=4))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--start", help="start day to fetch klines for")
    parser.add_argument(
        "-e", "--end", help="end day to fetch klines for", required=False
    )

    args = parser.parse_args()
    s = args.start
    # if we don't define an end date, lets assume we only want one day
    if args.end:
        e = args.end
    else:
        e = s

    start_dt = datetime.strptime(s, "%Y%m%d")
    end_dt = datetime.strptime(e, "%Y%m%d")

    print("getting list of all binance tickers")
    tickers = get_all_tickers()
    ignore_list = []

    # iterate over the date range, so that we generate one price.log.gz file
    # per day.
    # we run the dates in reverse, as we want to discard tickers as soon we
    # reach a date where they have no klines data available.
    for dt in reversed(daterange(start_dt, end_dt)):
        day = dt.strftime("%Y%m%d")
        if os.path.exists(f"log/{day}.log.gz"):
            print(f"log/{day}.log.gz already exists, skipping day")
            continue

        print(f"processing day {day}")
        # pull klines from 00:00:00 to 23:59:59 on each day, every 1 min
        start = float(
            datetime.strptime(f"{day} 00:00:00", "%Y%m%d %H:%M:%S").timestamp()
            * 1000
        )
        end = float(
            datetime.strptime(f"{day} 23:59:59", "%Y%m%d %H:%M:%S").timestamp()
            * 1000
        )

        log = []

        # iterate over the current (as of from today) list of available
        # tickers on binance, and retrieve the klines for each one for this
        # particular day.
        for ticker in tickers:
            if ticker in ignore_list:
                continue
            print(f"getting klines for {ticker} on {day}")
            results = []
            for line in pull_klines(ticker, start, end):
                results.append(line)
            if not results:
                # this ticker doesn't exist at this date and dates before this
                # let's add it to the ignore list
                print(f"no data found for {ticker}, ignoring coin from now on")
                ignore_list.append(ticker)
                continue

            # build our price.log file based on the klines info
            for (
                _,
                _,
                high,
                low,
                _,
                _,
                closetime,
                _,
                _,
                _,
                _,
                _,
            ) in results:
                klines_date = str(  # pylint: disable=invalid-name
                    datetime.fromtimestamp(float(closetime) / 1000)
                )  # pylint: disable=C0103
                log.append(
                    f"{klines_date} {ticker} {(float(high) + float(low))/2}\n"
                )
            # create a directory for each symbol to keep its logfiles
            if not os.path.exists(f"log/{ticker}"):
                os.mkdir(f"log/{ticker}")
            # write down log/ ticker / day.log
            with open(f"log/{ticker}/{day}.log", "w", encoding="utf-8") as f:
                oldprice = 0  # pylint: disable=invalid-name
                for line in log:
                    parts = line.split(" ")
                    symbol = parts[2]
                    price = parts[3]

                    # dedup identical price log lines
                    if price != oldprice:
                        oldprice = price
                        f.write(line)
            # and compress to log/ ticker / day.log.gz
            with gzip.open(f"log/{ticker}/{day}.log.gz", "wt") as z:
                with open(f"log/{ticker}/{day}.log", encoding="utf-8") as f:
                    z.write(f.read())
            if os.path.exists(f"log/{ticker}/{day}.log"):
                os.remove(f"log/{ticker}/{day}.log")

        # now that we have all klines for all tickers for this day,
        # we're going to dedup the results and discard any lines that haven't
        # moved in price.
        print(f"saving and sorting all klines for {day}")
        coin = {}
        oldcoin = {}
        with open(f"log/{day}.log", "w", encoding="utf-8") as f:
            for line in sorted(log):
                parts = line.split(" ")
                symbol = parts[2]
                # price_date = " ".join(parts[0:1])
                price = parts[3]

                if symbol not in coin:
                    coin[symbol] = price
                    oldcoin[symbol] = 0

                if price != oldcoin[symbol]:
                    f.write(line)
                    oldcoin[symbol] = price

        # and finally we compression our price.log for this day and discard
        # and temporary work files.
        with gzip.open(f"log/{day}.log.gz", "wt") as z:
            with open(f"log/{day}.log", encoding="utf-8") as f:
                z.write(f.read())
        if os.path.exists(f"log/{day}.log"):
            os.remove(f"log/{day}.log")

    # and generate and index.json for all the dates and which coin files
    # are available for those dates
    generate_index("log")

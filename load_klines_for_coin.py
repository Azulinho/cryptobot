import logging
import json
from datetime import datetime
from hashlib import md5
from flask import Flask, request
from os.path import basename, exists
import threading

import sys
from os import fsync, getpid
from lib.helpers import c_from_timestamp, requests_with_backoff
import colorlog

DEBUG = False
PID = getpid()

LOCK = threading.Lock()

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

if DEBUG:
    f_handler = logging.FileHandler("log/debug.log")
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


app = Flask(__name__)


def process_klines_line(kline):
    (
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
        _
    ) = kline

    date = float(
        datetime.fromtimestamp(
            closetime / 1000
        ).timestamp()
    )
    low = float(low)
    high = float(high)
    avg = (low + high) / 2

    return date, low, avg, high


def read_from_local_cache(f_path ):

    logging.info(f"using path {f_path}")
    # wrap results in a try call, in case our cached files are corrupt
    # and attempt to pull the required fields from our data.

    if not exists(f_path):
        logging.info(f"(no cache file {f_path}")
        return (False, [])

    logging.info(f"(trying to read klines from {f_path}")
    try:
        with open(f_path, "r") as f:
            results = json.load(f)
    except Exception as err:
        logging.critical(err)
        return (False, [])

    # new listed coins will return an empty array
    # so we bail out early here
    if not results:
        logging.info(f"(empty klines from {f_path}")
        return (True, [])

    # check for valid values by reading one line
    try:
        _, _, high, low, _, _, closetime, _, _, _, _, _ = results[0]
    except Exception as err:
        logging.critical(err)
        return (False, [])

    return (True, results)


def populate_values(klines, unit):
    _lowest = []
    _averages = []
    _highest = []

    # retrieve and calculate the lowest, highest, averages
    # from the klines data.
    # we need to transform the dates into consumable timestamps
    # that work for our bot.
    for line in klines:
        date, low, avg, high = process_klines_line(line)
        _lowest.append((date, low))
        _averages.append((date, avg))
        _highest.append((date, high))

    # finally, populate all the data coin buckets
    values = {}
    for metric in ['lowest', 'averages', 'highest']:
        values[metric] = []

    unit_values = {
        "m": 60,
        "h": 24,
        # for 'Days' we retrieve 1000 days, binance API default
        "d": 1000
    }

    timeslice = unit_values[unit]
    # we gather all the data we collected and only populate
    # the required number of records we require.
    # this could possibly be optimized, but at the same time
    # this only runs the once when we initialise a coin
    for d, v in _lowest[-timeslice:]:
        values['lowest'].append((d, v))

    for d, v in _averages[-timeslice:]:
        values['averages'].append((d, v))

    for d, v in _highest[-timeslice:]:
        values['highest'].append((d, v))

    return (True, values)


def call_binance_for_klines(query):
    logging.info(f"calling binance on {query}")
    with LOCK:
        response = requests_with_backoff(query)
    if response.status_code == 400:
        # 400 typically means binance has no klines for this coin
        logging.warning(f"got a 400 from binance for {query}")
        return (True, [])
    return (True, response.json())

def save_binance_klines(query, f_path, klines, mode):
    logging.info(f"caching binance {query} on {f_path}")
    if mode == "backtesting":
        with open(f_path, "w") as f:
            f.write(json.dumps(klines))


@app.route('/')
def load_klines_for_coin():
    """fetches from binance or a local cache klines for a coin"""

    symbol = request.args.get('symbol')
    date = int(float(request.args.get('date')))
    mode = request.args.get('mode')
    debug = bool(request.args.get('debug'))

    # when we initialise a coin, we pull a bunch of klines from binance
    # for that coin and save it to disk, so that if we need to fetch the
    # exact same data, we can pull it from disk instead.
    # we pull klines for the last 60min, the last 24h, and the last 1000days

    api_url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&"

    unit_values = {
        "m": (60, 1),
        "h": (24, 60),
        # for 'Days' we retrieve 1000 days, binance API default
        "d": (1000, 60 * 24),
    }
    unit_url_fpath = []
    for unit in ["m", "h", "d"]:

        # lets find out the from what date we need to pull klines from while in
        # backtesting mode.
        timeslice, minutes_before_now = unit_values[unit]

        backtest_end_time = date
        end_unix_time = int(
            (backtest_end_time - (60 * minutes_before_now)) * 1000
        )

        query = f"{api_url}endTime={end_unix_time}&interval=1{unit}"
        md5_query = md5(query.encode()).hexdigest()  # nosec
        f_path = f"cache/{symbol}.{md5_query}"
        unit_url_fpath.append((unit, query, f_path))

    values = {}
    for metric in ['lowest', 'averages', 'highest']:
        values[metric] = {}
        for unit in ["m", "h", "d", "s"]:
            values[metric][unit] = []

    for unit, query, f_path in unit_url_fpath:
        klines = []
        ok, klines = read_from_local_cache(f_path)
        if not ok:
            ok, klines = call_binance_for_klines(query)
            if ok:
                save_binance_klines(query, f_path, klines, mode)

        if ok:
            ok, low_avg_high = populate_values(klines, unit)

        if ok:
            for metric in low_avg_high.keys():
                values[metric][unit] = low_avg_high[metric]
                # make sure we don't keep more values that we should
                timeslice, _ = unit_values[unit]
                while len(values[metric][unit]) > timeslice:
                    values[metric][unit].pop()
    return values


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8999, threaded=True)
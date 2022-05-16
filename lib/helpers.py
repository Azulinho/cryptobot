""" helpers module """
import logging
import pickle
import sys
from datetime import datetime
from functools import lru_cache
from os import getpid
from os.path import exists, getctime
import colorlog
import requests
import udatetime
from binance.client import Client
from tenacity import retry, wait_exponential


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

f_handler = logging.FileHandler("log/debug.log")
f_handler.setLevel(logging.DEBUG)

logging.basicConfig(
    level=logging.DEBUG,
    format=f"[%(levelname)s] {PID} %(lineno)d %(funcName)s %(message)s",
    handlers=[f_handler, c_handler],
)

def mean(values: list) -> float:
    """returns the mean value of an array of integers"""
    return sum(values) / len(values)

@lru_cache(1024)
def percent(part: float, whole: float) -> float:
    """returns the percentage value of a number"""
    result = whole / 100 * part
    return result


@lru_cache(1024)
def add_100(number: float) -> float:
    """adds 100 to a number"""
    return 100 + number


@lru_cache(1)
def c_date_from(day: str) -> float:
    """ returns a cached datetime.fromisoformat()"""
    return datetime.fromisoformat(day).timestamp()


@lru_cache(8)
def c_from_timestamp(date: float) -> datetime:
    """ returns a cached datetime.fromtimestamp()"""
    return datetime.fromtimestamp(date)


@lru_cache(512)
@retry(wait=wait_exponential(multiplier=1, max=10))
def requests_with_backoff(query: str):
    """ retry wrapper for requests calls """
    return requests.get(query)


@retry(wait=wait_exponential(multiplier=15, max=10))
def cached_binance_client(access_key: str, secret_key: str) -> Client:
    """ retry wrapper for binance client first call """

    # when running automated-testing with multiple threads, we will hit
    # api requests limits, this happens during the client initialization
    # which mostly issues a ping. To avoid this when running multiple processes
    # we cache the client in a pickled state on disk and load it if it already
    # exists.
    cachefile = "cache/binance.client"
    if exists(cachefile) and (
            udatetime.now().timestamp() - getctime(cachefile) < (30 * 60)
    ):
        with open(cachefile, "rb") as f:
            _client = pickle.load(f)
    else:
        _client = Client(access_key, secret_key)
        with open(cachefile, "wb") as f:
            pickle.dump(_client, f)

    return _client

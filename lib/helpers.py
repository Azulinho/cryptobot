""" helpers module """
import logging
import math
import pickle  # nosec
from datetime import datetime
from functools import lru_cache
from os.path import exists, getctime
from time import sleep

import requests
import udatetime
from binance.client import Client
from filelock import SoftFileLock
from pyrate_limiter import Duration, Limiter, RequestRate
from tenacity import retry, wait_exponential

rate = RequestRate(600, Duration.MINUTE)  # 600 requests per minute
limiter = Limiter(rate)


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


@lru_cache(64)
def c_date_from(day: str) -> float:
    """returns a cached datetime.fromisoformat()"""
    return datetime.fromisoformat(day).timestamp()


@lru_cache(64)
def c_from_timestamp(date: float) -> datetime:
    """returns a cached datetime.fromtimestamp()"""
    return datetime.fromtimestamp(date)


@retry(wait=wait_exponential(multiplier=1, max=3))
@limiter.ratelimit("binance", delay=True)
def requests_with_backoff(query: str):
    """retry wrapper for requests calls"""
    response = requests.get(query, timeout=5)

    # 418 is a binance api limits response
    # don't raise a HTTPError Exception straight away but block until we are
    # free from the ban.
    status = response.status_code
    if status in [418, 429]:
        backoff = int(response.headers["Retry-After"])
        logging.warning(f"HTTP {status} from binance, sleeping for {backoff}s")
        sleep(backoff)
        response.raise_for_status()

    with open("log/binance.response.log", "at") as f:
        f.write(f"{query} {status} {response}\n")
    return response


def cached_binance_client(access_key: str, secret_key: str) -> Client:
    """retry wrapper for binance client first call"""

    lock = SoftFileLock("state/binance.client.lockfile", timeout=10)
    # when running automated-testing with multiple threads, we will hit
    # api requests limits, this happens during the client initialization
    # which mostly issues a ping. To avoid this when running multiple processes
    # we cache the client in a pickled state on disk and load it if it already
    # exists.
    cachefile = "cache/binance.client"
    with lock:
        if exists(cachefile) and (
            udatetime.now().timestamp() - getctime(cachefile) < (30 * 60)
        ):
            logging.debug("re-using local cached binance.client file")
            with open(cachefile, "rb") as f:
                _client = pickle.load(f)  # nosec
        else:
            try:
                logging.debug("refreshing cached binance.client")
                _client = Client(access_key, secret_key)
            except Exception as err:
                logging.warning(f"API client exception: {err}")
                raise Exception from err
            with open(cachefile, "wb") as f:
                pickle.dump(_client, f)

        return _client


def step_size_to_precision(step_size: str) -> int:
    """returns step size"""
    precision: int = step_size.find("1") - 1
    with open("log/binance.step_size_to_precision.log", "at") as f:
        f.write(f"{step_size} {precision}\n")
    return precision


def floor_value(val: float, step_size: str) -> str:
    """floors quantity depending on precision"""
    value: str = ""
    precision: int = step_size_to_precision(step_size)
    if precision > 0:
        value = "{:0.0{}f}".format(  # pylint: disable=consider-using-f-string
            val, precision
        )
    else:
        value = str(math.floor(int(val)))
    with open("log/binance.floor_value.log", "at") as f:
        f.write(f"{val} {step_size} {precision} {value}\n")
    return value

""" helpers module """
import logging
import pickle
from datetime import datetime
from functools import lru_cache
from os.path import exists, getctime
from time import sleep

import requests
import udatetime
from binance.client import Client
from tenacity import retry, wait_exponential


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
    """returns a cached datetime.fromisoformat()"""
    return datetime.fromisoformat(day).timestamp()


@lru_cache(8)
def c_from_timestamp(date: float) -> datetime:
    """returns a cached datetime.fromtimestamp()"""
    return datetime.fromtimestamp(date)


@lru_cache(512)
@retry(wait=wait_exponential(multiplier=1, max=10))
def requests_with_backoff(query: str):
    """retry wrapper for requests calls"""
    response = requests.get(query)

    # 418 is a binance api limits response
    # don't raise a HTTPError Exception straight away but block until we are
    # free from the ban.
    status = response.status_code
    if status in [418, 429]:
        backoff = int(response.headers["Retry-After"])
        logging.warning(f"HTTP {status} from binance, sleeping for {backoff}s")
        sleep(backoff)
        response.raise_for_status()
    response.raise_for_status()
    return response


@retry(wait=wait_exponential(multiplier=15, max=10))
def cached_binance_client(access_key: str, secret_key: str) -> Client:
    """retry wrapper for binance client first call"""

    # when running automated-testing with multiple threads, we will hit
    # api requests limits, this happens during the client initialization
    # which mostly issues a ping. To avoid this when running multiple processes
    # we cache the client in a pickled state on disk and load it if it already
    # exists.
    cachefile = "cache/binance.client"
    if exists(cachefile) and (
        udatetime.now().timestamp() - getctime(cachefile) < (30 * 60)
    ):
        logging.debug("re-using local cached binance.client file")
        with open(cachefile, "rb") as f:
            _client = pickle.load(f)
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

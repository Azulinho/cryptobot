""" cryptobot/databank/views.py """

import json
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from sortedcontainers import SortedKeyList

from .helpers import CACHE, Helpers

KLINES_MAX_BATCH_SIZE: dict = settings.DATABANK_KLINES_MAX_BATCH_SIZE
AGGREGATE_MAX_BATCH_SIZE: dict = settings.DATABANK_AGGREGATE_MAX_BATCH_SIZE
KLINES_DIRECTORY: str = settings.DATABANK_KLINES_DIRECTORY
CACHE_DIRECTORY: str = settings.DATABANK_CACHE_DIRECTORY
PAIRS: list = settings.DATABANK_PAIRS


@csrf_exempt
def handler_klines(request):
    """/klines endpoint"""
    req = json.loads(request.body)

    timeframe: str = req["timeframe"]
    symbol: str = req["symbol"]
    pair: str = req["pair"]
    from_timestamp: int = int(req["from_timestamp"])
    if "batch_size" in req:
        batch_size: int = int(req["batch_size"])
        if batch_size > int(KLINES_MAX_BATCH_SIZE[timeframe]):
            batch_size = int(KLINES_MAX_BATCH_SIZE[timeframe])
    else:
        batch_size = int(KLINES_MAX_BATCH_SIZE[timeframe])

    to_timestamp = from_timestamp + batch_size

    cache_key: str = (
        f"{timeframe}_{symbol}_{pair}_{from_timestamp}_{to_timestamp}"
    )
    avail, contents = CACHE["klines"].get(cache_key, raw=True)
    if avail:
        return HttpResponse(contents)

    lines = Helpers.get_klines(
        timeframe,
        symbol,
        from_timestamp,
        to_timestamp,
        pair=pair,
    )
    CACHE["klines"].update(cache_key, lines)
    avail, resp = CACHE["klines"].get(cache_key, raw=True)
    return HttpResponse(resp)


@csrf_exempt
def handler_symbols(request):
    """/symbols endpoint"""
    req = json.loads(request.body)

    timeframe: str = req["timeframe"]
    pair: str = req["pair"]
    from_timestamp: int = int(req["from_timestamp"])
    to_timestamp: int = int(req["to_timestamp"])

    cache_key: str = f"{timeframe}_{pair}_{from_timestamp}_{to_timestamp}"
    avail, contents = CACHE["symbols"].get(cache_key, raw=True)
    if avail:
        return HttpResponse(contents)

    symbols: list = list(
        Helpers.symbols(timeframe, from_timestamp, to_timestamp, pair)
    )
    CACHE["symbols"].update(cache_key, symbols)
    avail, resp = CACHE["symbols"].get(cache_key, raw=True)

    return HttpResponse(resp)


@csrf_exempt
def handler_aggregate(request):
    """/aggregate endpoint"""
    req = json.loads(request.body)

    timeframe: str = req["timeframe"]

    pair = None
    if "pair" in req:
        pair: str = req["pair"]

    from_timestamp: int = int(req["from_timestamp"])
    if "batch_size" in req:
        batch_size: int = int(req["batch_size"])
        if batch_size > int(AGGREGATE_MAX_BATCH_SIZE[timeframe]):
            batch_size = int(AGGREGATE_MAX_BATCH_SIZE[timeframe])
    else:
        batch_size = int(AGGREGATE_MAX_BATCH_SIZE[timeframe])

    # override to_timestamp, so that we don't go over batch size
    to_timestamp = from_timestamp + batch_size

    cache_key: str = f"{timeframe}_{pair}_{from_timestamp}_{to_timestamp}"
    avail, contents = CACHE["aggregate"].get(cache_key, raw=True)
    if avail:
        return HttpResponse(contents)

    symbols = Helpers.symbols(
        timeframe=timeframe,
        from_timestamp=from_timestamp,
        to_timestamp=to_timestamp,
        pair=pair,
    )
    lines: SortedKeyList = SortedKeyList([], key=lambda x: x[2])
    for symbol in symbols:
        klines = Helpers.get_klines(
            timeframe, symbol, from_timestamp, to_timestamp, pair=pair
        )
        lines.update(klines)

    CACHE["aggregate"].update(cache_key, list(lines))
    avail, resp = CACHE["aggregate"].get(cache_key, raw=True)
    return HttpResponse(resp)


@csrf_exempt
def handler_hourly_filenames(request):
    """/hourly_filenames endpoint"""
    req = json.loads(request.body)

    timeframe: str = req["timeframe"]

    symbol = None
    if "symbol" in req:
        symbol: str = req["symbol"]

    pair = None
    if "pair" in req:
        pair: str = req["pair"]

    from_timestamp: int = int(req["from_timestamp"])
    to_timestamp: int = int(req["to_timestamp"])

    contents = Helpers.get_list_of_hourly_filenames(
        timeframe=timeframe,
        symbol=symbol,
        pair=pair,
        from_timestamp=from_timestamp,
        to_timestamp=to_timestamp,
    )
    return JsonResponse(contents, safe=False)

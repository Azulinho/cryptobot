""" cryptobot/databank/views.py """

import json
from glob import glob
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
import pyzstd
from sortedcontainers import SortedKeyList

from .models import Mappings
from .helpers import CACHE, Helpers

KLINES_MAX_BATCH_SIZE: int = settings.DATABANK_KLINES_MAX_BATCH_SIZE
AGGREGATE_MAX_BATCH_SIZE: int = settings.DATABANK_AGGREGATE_MAX_BATCH_SIZE
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
    to_timestamp: int = int(req["to_timestamp"])
    if "batch_size" in req:
        batch_size: int = int(req["batch_size"])
        if batch_size > int(KLINES_MAX_BATCH_SIZE):
            batch_size = int(KLINES_MAX_BATCH_SIZE)
    else:
        batch_size = int(KLINES_MAX_BATCH_SIZE)

    cache_key: str = f"{timeframe}_{symbol}_{pair}_{from_timestamp}_{to_timestamp}_{batch_size}"
    avail, contents = CACHE["klines"].get(cache_key, raw=True)
    if avail:
        return HttpResponse(contents)

    lines = Helpers.get_klines(
        timeframe,
        symbol,
        from_timestamp,
        to_timestamp,
        pair=pair,
        batch_size=batch_size,
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
    """/combined endpoint"""
    req = json.loads(request.body)

    timeframe: str = req["timeframe"]
    pair: str = req["pair"]
    from_timestamp: int = int(req["from_timestamp"])
    to_timestamp: int = int(req["to_timestamp"])
    if "batch_size" in req:
        batch_size: int = int(req["batch_size"])
        if batch_size > int(AGGREGATE_MAX_BATCH_SIZE):
            batch_size = int(AGGREGATE_MAX_BATCH_SIZE)
    else:
        batch_size = int(AGGREGATE_MAX_BATCH_SIZE)

    cache_key: str = (
        f"{timeframe}_{pair}_{from_timestamp}_{to_timestamp}_{batch_size}"
    )
    avail, contents = CACHE["aggregate"].get(cache_key, raw=True)
    if avail:
        return HttpResponse(contents)

    symbols = Helpers.symbols(timeframe, from_timestamp, to_timestamp, pair)

    lines: SortedKeyList = SortedKeyList([], key=lambda x: x[2])
    for symbol in symbols:
        for file in Helpers.filenames(
            timeframe,
            symbol,
            pair,
            from_timestamp,
            to_timestamp,
        ):
            lines_in_file = []
            with pyzstd.open(
                f"{KLINES_DIRECTORY}/{file.filename}", "rt", encoding="utf-8"
            ) as f:
                for line in f:
                    entry = line.replace("\n", "").split(",")
                    if entry:
                        if int(entry[6]) > (from_timestamp + batch_size):
                            break

                        if (
                            int(entry[0]) >= from_timestamp
                            and int(entry[6]) <= to_timestamp
                        ):
                            lines_in_file.append([symbol] + [pair] + entry)
            lines.update(lines_in_file)

    CACHE["aggregate"].update(cache_key, list(lines))
    avail, resp = CACHE["aggregate"].get(cache_key, raw=True)
    return HttpResponse(resp)


@csrf_exempt
def handler_mappings(request):
    """updates mappings of filenames in DB"""
    try:
        req = json.loads(request.body)
    except:  # pylint: disable=bare-except
        req = {}

    filename = req["filename"]
    timeframe = req["timeframe"]
    symbol = req["symbol"]
    pair = req["pair"]
    open_timestamp = req["open_timestamp"]
    close_timestamp = req["close_timestamp"]

    res = Mappings.objects.filter(filename=filename).exists()

    if res:
        rec = Mappings.objects.get(filename=filename)
        rec.filename = str(filename)
        rec.timeframe = str(timeframe)
        rec.symbol = str(symbol)
        rec.pair = str(pair)
        rec.open_timestamp = int(open_timestamp)
        rec.close_timestamp = int(close_timestamp)
    else:
        rec = Mappings(
            filename=str(filename),
            timeframe=str(timeframe),
            symbol=str(symbol),
            pair=str(pair),
            open_timestamp=int(open_timestamp),
            close_timestamp=int(close_timestamp),
        )
    rec.save()
    return HttpResponse("OK: Mapping updated\n")


@csrf_exempt
def handler_hourly_filenames(request):
    """/klines endpoint"""
    req = json.loads(request.body)

    timeframe: str = req["timeframe"]
    symbol: str = req["symbol"]
    pair: str = req["pair"]
    from_timestamp: int = int(req["from_timestamp"])
    to_timestamp: int = int(req["to_timestamp"])

    contents = Helpers.get_list_of_hourly_filenames(
        timeframe, symbol, pair, from_timestamp, to_timestamp
    )

    return JsonResponse(contents, safe=False)

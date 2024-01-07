import os
import json
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
import pyzstd
import msgpack
from sortedcontainers import SortedKeyList

from .models import Mappings
from .helpers import CACHE, Helpers

KLINES_MAX_BATCH_SIZE: int = int(os.getenv("KLINES_MAX_BATCH_SIZE", "86400"))
AGGREGATE_MAX_BATCH_SIZE: int = int(
    os.getenv("AGGREGATE_MAX_BATCH_SIZE", "3600")
)
KLINES_DIRECTORY: str = os.getenv("KLINES_DIRECTORY", "./klines")
CACHE_DIRECTORY: str = os.getenv("CACHE_DIRECTORY", "./cache")
PAIRS: list = os.getenv("PAIRS", "BTC USDT ETH BNB").split(" ")
PORT = int(os.getenv("PORT", "9000"))


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

    lines: list = []
    batch = 0
    for file in Helpers.filenames(
        timeframe,
        symbol,
        pair,
        from_timestamp,
        to_timestamp,
    ):
        if batch >= batch_size:
            break
        with pyzstd.open(
            f"{KLINES_DIRECTORY}/{file.filename}", "rt", encoding="utf-8"
        ) as f:
            for line in f:
                if batch >= batch_size:
                    break
                entry = line.replace("\n", "").split(",")
                if (
                    int(entry[0]) >= from_timestamp
                    and int(entry[6]) <= to_timestamp
                ):
                    lines.append([symbol] + [pair] + entry)
                    batch = batch + 1

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
        rec = Mappings.filter(filename=filename).update(
            filename=str(filename),
            timeframe=str(timeframe),
            symbol=str(symbol),
            pair=str(pair),
            open_timestamp=int(open_timestamp),
            close_timestamp=int(close_timestamp),
        )
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

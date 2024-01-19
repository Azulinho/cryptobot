""" cryptobot/databank/helpers.py """
import json
import os
import re
import zipfile
import io
from glob import glob
import hashlib
from datetime import datetime, timedelta
from functools import lru_cache

import pandas
import requests
import pyzstd
import msgpack
from django.conf import settings

CACHE_DIRECTORY: str = settings.DATABANK_CACHE_DIRECTORY
CACHE_CONFIG: dict = settings.DATABANK_CACHE_CONFIG
KLINES_DIRECTORY: str = settings.DATABANK_KLINES_DIRECTORY

VISION = "https://data.binance.vision/data/spot/monthly/klines/AAVEBKRW/1m/AAVEBKRW-1m-2021-01.zip"
VISION = "https://data.binance.vision/data/spot"
KLINES = "/home/azul/tmp/binance-bulk-downloader/REORDERED"


class DiskCache:
    """Disk Cache"""

    def __init__(self, namespace: str, ttl=0) -> None:
        """DiskCache instance"""
        self.cache_path: str = f"{CACHE_DIRECTORY}/{namespace}"
        self.namespace: str = namespace
        self.ttl: int = ttl
        if not os.path.exists(self.cache_path):
            os.makedirs(self.cache_path)

        for key_path in glob(self.cache_path + "/*"):
            modified_last: float = os.path.getmtime(key_path)
            if self.ttl != 0:
                if datetime.now().timestamp() > modified_last + self.ttl:
                    try:
                        os.remove(key_path)
                    except:  # pylint: disable=bare-except
                        pass

    def cache_key(self, key: str) -> str:
        """returns unique cache key"""

        key_path: str = f"{self.cache_path}/{key}"
        digest: str = hashlib.sha256(key_path.encode()).hexdigest()
        full_path: str = f"{self.cache_path}/{digest}.{key}"
        return full_path

    def update(self, key: str, contents) -> None:
        """update cache key"""
        key_path: str = self.cache_key(key)

        with pyzstd.open(key_path, "wb") as f:
            f.write(msgpack.packb(contents))

    def get(self, key: str, raw=False) -> tuple:
        """retrieves key from cache"""

        key_path: str = self.cache_key(key)

        if os.path.exists(key_path):
            modified_last: float = os.path.getmtime(key_path)
            if self.ttl != 0:
                if datetime.now().timestamp() > modified_last + self.ttl:
                    try:
                        os.remove(key_path)
                    except:  # pylint: disable=bare-except
                        pass
                    return (False, None)
            try:
                if raw:
                    with open(key_path, "rb") as f:
                        return (True, f.read())
                else:
                    with pyzstd.open(key_path, "rb") as f:
                        return (True, msgpack.unpackb(f.read()))
            except:  # pylint: disable=bare-except
                pass
        return (False, None)


CACHE = {}
for k, v in CACHE_CONFIG.items():
    CACHE[k] = DiskCache(namespace=k, ttl=int(v))


class Helpers:
    """Helper methods"""

    @staticmethod
    def get_hourly_filename_strings(start_timestamp, end_timestamp):
        result = []
        current_timestamp = start_timestamp

        while current_timestamp <= end_timestamp:
            current_datetime = datetime.fromtimestamp(current_timestamp)

            current_string = current_datetime.strftime("%Y/%m/%d/%H")
            result.append(current_string)

            current_timestamp += 3600

        return result

    @staticmethod
    def get_lowest_highest_hourly_timestamps(filenames):
        # wrap all filenames into a dictionary index
        idx = {}
        for f in filenames:
            columns = f.split("/")
            idx[f] = {
                "EXCHANGE": columns[-9],
                "TIMEFRAME": columns[-8],
                "SYMBOL": columns[-7],
                "PAIR": columns[-6],
                "YEAR": int(columns[-5]),
                "MONTH": int(columns[-4]),
                "DAY": int(columns[-3]),
                "HOUR": int(columns[-2]),
            }
        if filenames:
            ly = min([idx[x]["YEAR"] for x in idx.keys()])
            hy = max([idx[x]["YEAR"] for x in idx.keys()])
            lm = min([idx[x]["MONTH"] for x in idx.keys()])
            hm = max([idx[x]["MONTH"] for x in idx.keys()])
            ld = min([idx[x]["DAY"] for x in idx.keys()])
            hd = max([idx[x]["DAY"] for x in idx.keys()])
            lh = min([idx[x]["HOUR"] for x in idx.keys()])
            hh = max([idx[x]["HOUR"] for x in idx.keys()])

            # from all the files founds, find out the oldest and newest dates available
            lowest_timestamp = datetime.strptime(
                f"{ly}/{lm}/{ld} {lh}:00",
                "%Y/%m/%d %H:00",
            ).timestamp()
            highest_timestamp = datetime.strptime(
                f"{hy}/{hm}/{hd} {hh}:00",
                "%Y/%m/%d %H:00",
            ).timestamp()
            return (True, lowest_timestamp, highest_timestamp)
        return (False, None, None)

    @staticmethod
    def get_list_of_hourly_filenames(
        timeframe, from_timestamp, to_timestamp, symbol=None, pair=None
    ):
        _symbol = symbol
        _pair = pair
        if not symbol:
            symbol = "*"
        if not pair:
            pair = "*"

        files_found: list[str] = glob(
            KLINES_DIRECTORY + f"*/{timeframe}/{symbol}/{pair}/**/klines.zstd",
            recursive=True,
        )

        symbol = _symbol
        pair = _pair

        (
            ok,
            lowest_timestamp,
            highest_timestamp,
        ) = Helpers.get_lowest_highest_hourly_timestamps(files_found)

        contents = []
        if ok:
            # override the timestamps with the most recent, oldest timestamp available
            # we won't find any finds older or more recent than those.
            from_timestamp = max(from_timestamp, lowest_timestamp)
            to_timestamp = min(to_timestamp, highest_timestamp)

            # finally with the timestamps aligned to the file contents we have
            # generate a list of all possible partial filenames with an hour interval
            # between the from and the to timestamps
            hourly_filenames = Helpers.get_hourly_filename_strings(
                from_timestamp, to_timestamp
            )

            # now find any matches, that contain the hourly partial strings
            # against the full list of filenames available for these timestamps
            path_name = f"/{timeframe}/"
            if not symbol:
                path_name = path_name + ".*/"
            else:
                path_name = path_name + f"{symbol}/"

            if not pair:
                path_name = path_name + ".*/"
            else:
                path_name = path_name + f"{pair}/"

            for filename in files_found:
                if re.search(path_name, filename):
                    for hourly_filename in hourly_filenames:
                        if hourly_filename in filename:
                            contents.append(filename)

        return sorted(contents)

    @staticmethod
    def get_klines(
        timeframe, symbol, from_timestamp, to_timestamp, pair=""
    ) -> list:
        lines: list = []

        all_files = Helpers.get_list_of_hourly_filenames(
            timeframe=timeframe,
            symbol=symbol,
            pair=pair,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )
        for file in all_files:
            with pyzstd.open(file, "rt", encoding="utf-8") as f:
                for line in f:
                    entry = line.replace("\n", "").split(",")
                    if int(entry[0]) >= to_timestamp:
                        break
                    if (
                        int(entry[0]) >= from_timestamp
                        and int(entry[6]) <= to_timestamp
                    ):
                        lines.append([symbol] + [pair] + entry)
        return lines

    @staticmethod
    def symbols(timeframe, from_timestamp, to_timestamp, pair="") -> list:
        """returns list of symbols available from a time window"""

        all_files = Helpers.get_list_of_hourly_filenames(
            timeframe=timeframe,
            pair=pair,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )
        symbols = list(set([file.split("/")[-7] for file in all_files]))

        return symbols


class Token:
    def __init__(self, fullsymbol, symbol, pair):
        self.fullsymbol = fullsymbol
        self.symbol = symbol
        self.pair = pair

    @staticmethod
    def get_date_fields_from(date):
        year = date.split("/")[0]
        month = date.split("/")[1]
        day = date.split("/")[2]
        hour = date.split("/")[3]
        return (year, month, day, hour)

    @staticmethod
    def get_all_tokens(url):
        blob = json.loads(requests.get(url).content)["symbols"]
        tokens = []
        for s in blob:
            fullsymbol = s["symbol"]
            status = s["status"]
            symbol = s["baseAsset"]
            pair = s["quoteAsset"]
            if status != "TRADING":
                continue
            tokens.append([fullsymbol, pair, symbol])
        return tokens

    @staticmethod
    def get_list_of_dates(sdate, edate):
        date_list = sorted(
            pandas.date_range(sdate, edate - timedelta(hours=1), freq="h")
            .strftime("%Y/%m/%d/%H")
            .tolist(),
            reverse=True,
        )
        return date_list

    def process_symbol(self, date_list, period="1s"):
        print(f"{datetime.now()} process_symbol: {self.fullsymbol}")
        not_available = 0
        for date in date_list:
            if not_available > 2:
                print(
                    f"{datetime.now()} process_symbol: giving up on {self.fullsymbol}"
                )
                break
            filename = f"{KLINES}/BINANCE/{period}/{self.symbol}/{self.pair}/{date}/klines.zstd"
            if not os.path.exists(filename):
                print(
                    f"{datetime.now()} process_symbol: missing file {filename}"
                )
                year, month, day, hour = Token.get_date_fields_from(date)
                ok = self.download_file(year=year, month=month, period=period)
                if not ok:
                    ok = self.download_file(
                        year=year, month=month, day=day, period=period
                    )
                    if not ok:
                        not_available = not_available + 1
                        # TODO: we need to call binance client
                        # and split_downloaded_file() for it
                        # and return True

    @lru_cache(maxsize=65535)
    def download_file(self, year, month, day=None, period="1s"):
        print(
            f"{datetime.now()} download_file: {self.fullsymbol} {year} {month} {day} {period}"
        )

        if day:
            url = f"{VISION}/daily/klines/{self.fullsymbol}/{period}/{self.fullsymbol}-{period}-{year}-{month}-{day}.zip"
        else:
            url = f"{VISION}/monthly/klines/{self.fullsymbol}/{period}/{self.fullsymbol}-{period}-{year}-{month}.zip"
        print(f"{datetime.now()} pulling file {url}")
        req = requests.get(url)
        if req.status_code == 200:
            print(f"{datetime.now()} download_file: downloaded {url}")
            self.split_downloaded_file(
                klines=req.content,
                year=year,
                month=month,
                day=day,
                timeframe=period,
            )
            return True

        print(f"{datetime.now()} download_file: failed to download {url}")
        return False

    # TODO: need to cache this function call, but for that I need to
    # move 'klines' out of the parameters.
    # use a GLOBAL var?, how? this needs to work across gunicorn workers
    # or celery workers
    def split_downloaded_file(self, klines, year, month, day, timeframe):
        print(
            f"{datetime.now()} split_download_file: {self.fullsymbol} {self.pair} {self.symbol} {year} {month} {day}"
        )

        newfiles = {}
        hourly_fh = {}

        if day:
            zipfilename = (
                f"{self.fullsymbol}-{timeframe}-{year}-{month}-{day}.csv"
            )
        else:
            zipfilename = f"{self.fullsymbol}-{timeframe}-{year}-{month}.csv"

        zippo = zipfile.ZipFile(io.BytesIO(klines)).open(zipfilename, mode="r")
        for line in zippo.readlines():
            line = line.decode()
            timestamp = int(int(line.split(",", maxsplit=1)[0]) / 1000)
            str_timestamp = str(datetime.utcfromtimestamp(timestamp))

            year = str_timestamp[0:4]
            month = str_timestamp[5:7]
            day = str_timestamp[8:10]
            hour = str_timestamp[11:13]

            NEW_DIRECTORY = f"BINANCE/{timeframe}/{self.symbol}/{self.pair}/{year}/{month}/{day}/{hour}"
            newfile = f"{NEW_DIRECTORY}/klines.zstd"
            os.makedirs(f"{KLINES}/{NEW_DIRECTORY}", exist_ok=True)

            if newfile not in hourly_fh:
                hourly_fh[newfile] = []
            if newfile in hourly_fh:
                # TODO: fix timestamps, as they are x1000
                fields = line.split(",")
                fields[0] = str(int(int(fields[0]) / 1000))
                fields[6] = str(int(int(fields[6]) / 1000))
                line = ",".join(fields)
                hourly_fh[newfile].append(line.encode("utf-8"))

                newfiles[newfile] = {
                    "symbol": self.symbol,
                    "pair": self.pair,
                    "timeframe": timeframe,
                }
        for fh in hourly_fh:
            if not os.path.exists(fh):
                print(f"{datetime.now()} split downloaded_file writing {fh}")
                with pyzstd.open(f"{KLINES}/{fh}", "w") as f:
                    f.writelines(hourly_fh[fh])

                timeframe = newfiles[fh]["timeframe"]
                symbol = newfiles[fh]["symbol"]
                pair = newfiles[fh]["pair"]

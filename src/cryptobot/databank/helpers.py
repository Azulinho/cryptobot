""" cryptobot/databank/helpers.py """
import os
from glob import glob
import hashlib
from datetime import datetime

import pyzstd
import msgpack
from django.db.models import Q
from django.conf import settings
from .models import Mappings

CACHE_DIRECTORY: str = settings.DATABANK_CACHE_DIRECTORY
CACHE_CONFIG: dict = settings.DATABANK_CACHE_CONFIG
KLINES_DIRECTORY: str = settings.DATABANK_KLINES_DIRECTORY


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
                "EXCHANGE": columns[-8],
                "TIMEFRAME": columns[-7],
                "SYMBOL": columns[-6],
                "PAIR": columns[-5],
                "YEAR": int(columns[-4]),
                "MONTH": int(columns[-3]),
                "DAY": int(columns[-2]),
                "HOUR": int(columns[-1].split(".")[0]),
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
        timeframe, symbol, pair, from_timestamp, to_timestamp
    ):
        files_found: list[str] = glob(
            KLINES_DIRECTORY + f"*/{timeframe}/{symbol}/{pair}/**/*.zstd",
            recursive=True,
        )

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
            path_name = f"{timeframe}/{symbol}/{pair}/"
            for filename in files_found:
                if path_name in filename:
                    for hourly_filename in hourly_filenames:
                        if hourly_filename in filename:
                            contents.append(filename)

        return sorted(contents)

    @staticmethod
    def get_klines(
        timeframe,
        symbol,
        from_timestamp,
        to_timestamp,
        pair="",
        batch_size=None,
    ) -> list:
        lines: list = []
        batch = 0

        all_files = Helpers.get_list_of_hourly_filenames(
            timeframe, symbol, pair, from_timestamp, to_timestamp
        )
        for file in all_files:
            if batch >= batch_size:
                break
            with pyzstd.open(file, "rt", encoding="utf-8") as f:
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
        return lines

    @staticmethod
    def symbols(timeframe, from_timestamp, to_timestamp, pair="") -> list:
        """returns list of symbols available from a time window"""

        symbol_queryset = (
            Mappings.objects.filter(
                Q(
                    open_timestamp__lte=int(from_timestamp),
                    close_timestamp__gte=int(from_timestamp),
                )
                | Q(
                    open_timestamp__lte=int(to_timestamp),
                    close_timestamp__gte=int(to_timestamp),
                )
                | Q(
                    open_timestamp__gte=int(from_timestamp),
                    open_timestamp__lte=int(to_timestamp),
                ),
                timeframe=str(timeframe),
                pair=str(pair),
            )
            .order_by("open_timestamp")
            .distinct()
        )

        symbols = list(set(symbol_queryset.values_list("symbol", flat=True)))
        return symbols

    @staticmethod
    def filenames(
        timeframe, symbol, pair, from_timestamp, to_timestamp
    ) -> list:
        """returns list of filenames available from a time window"""
        return list(
            Mappings.objects.raw(
                f"""
                SELECT filename FROM databank_mappings
                WHERE timeframe='{timeframe}'
                AND pair='{pair}'
                AND symbol='{symbol}'
                AND (
                    (
                        open_timestamp <= {from_timestamp}
                        AND {from_timestamp} <= close_timestamp
                    ) OR
                    (
                        open_timestamp <= {to_timestamp}
                        AND {to_timestamp} <= close_timestamp
                    ) OR
                    (
                        {from_timestamp} <= open_timestamp
                        AND open_timestamp <= {to_timestamp}
                    )
                ) ORDER BY open_timestamp;
            """
            )
        )

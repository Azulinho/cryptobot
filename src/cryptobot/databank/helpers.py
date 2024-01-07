""" cryptobot/databank/helpers.py """
import os
import glob
import hashlib
import re
from datetime import datetime, timedelta
from itertools import chain

import pyzstd
import msgpack
from .models import Mappings
from django.db.models import Q

CACHE_DIRECTORY: str = os.getenv("CACHE_DIRECTORY", "./cache")
CACHE_CONFIG: dict = {
    "filelist": 3600,
    "klines": 3600,
    "aggregate": 0,
    "symbols": 3600,
}


class DiskCache:
    """Disk Cache"""

    def __init__(self, namespace: str, ttl=0) -> None:
        """DiskCache instance"""
        self.cache_path: str = f"{CACHE_DIRECTORY}/{namespace}"
        self.namespace: str = namespace
        self.ttl: int = ttl
        if not os.path.exists(self.cache_path):
            os.makedirs(self.cache_path)

        for key_path in glob.glob(self.cache_path + "/*"):
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
    def init_db() -> None:
        """init database"""
        with app.app_context():
            db.create_all()
            db.session.commit()

    @staticmethod
    def symbols(timeframe, from_timestamp, to_timestamp, pair="") -> list:
        """returns list of symbols available from a time window"""

        symbol_queryset = Mappings.objects.filter(
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
        ).order_by("open_timestamp")

        symbols = symbol_queryset.values_list("symbol", flat=True)
        return list(symbols)

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

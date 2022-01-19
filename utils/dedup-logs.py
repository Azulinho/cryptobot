import argparse
import logging
import os
import re
import sys
import traceback
import gzip
import shutil
import multiprocessing as mp

from pathlib import Path



if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("-l", "--log", help="log")
        args = parser.parse_args()

        p = Path('.')
        logfile = list(sorted(p.glob(args.log)))

        coin = {}
        oldcoin = {}
        with gzip.open(str(args.log), "rt") as logfile:
            line = logfile.readline()
            date = (line.split(" ")[0]).replace("-", "")
            fh = open(f"{date}.log.dedup", "wt")

        with gzip.open(str(args.log), "rt") as logfile:
            for line in logfile:
                parts = line.split(" ")
                symbol = parts[2]
                date = ' '.join(parts[0:1])
                price = parts[3]

                if symbol not in coin:
                    coin[symbol] = price
                    oldcoin[symbol] = 0

                if price != oldcoin[symbol]:
                    fh.write(line)
                    oldcoin[symbol] = price

        fh.close()
    except Exception:  # pylint: disable=broad-except
        logging.error(traceback.format_exc())
        sys.exit(1)

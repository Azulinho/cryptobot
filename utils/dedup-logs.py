""" dedup entries in price.logs where the price of a coin hasn't moved """
import argparse
import gzip
import logging
import sys
import traceback
from pathlib import Path

if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("-l", "--log", help="log")
        args = parser.parse_args()

        p = Path(".")

        coin = {}
        oldcoin = {}
        with gzip.open(str(args.log), "rt") as logfile:
            line = logfile.readline()
            date = (line.split(" ")[0]).replace("-", "")
            fh = open(f"{date}.log.dedup", "wt")  # pylint: disable=R1732

        with gzip.open(str(args.log), "rt") as logfile:
            for line in logfile:
                parts = line.split(" ")
                symbol = parts[2]
                date = " ".join(parts[0:1])
                price = parts[3]

                if symbol not in coin:
                    coin[symbol] = price
                    oldcoin[symbol] = str(0)

                if price != oldcoin[symbol]:
                    fh.write(line)
                    oldcoin[symbol] = str(price)

        fh.close()
    except Exception:  # pylint: disable=broad-except
        logging.error(traceback.format_exc())
        sys.exit(1)

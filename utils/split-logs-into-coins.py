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



def compress_file(filename):
    with open(filename) as uncompressed:
        print(f"compressing file {filename}")
        with gzip.open(f"{filename}.gz", mode='wt') as compressed:
            shutil.copyfileobj(uncompressed, compressed)
    os.remove(filename)


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("-g", "--glob", help="glob for logs")
        args = parser.parse_args()

        p = Path('.')
        logfiles = list(sorted(p.glob(args.glob)))

        coinfiles = set()

        usdtfile = open("pair.USDT.log", "wt")
        btcfile = open("pair.BTC.log", "wt")
        bnbfile = open("pair.BNB.log", "wt")
        ethfile = open("pair.ETH.log", "wt")

        coinfh = {}
        for filename in logfiles:
            print(f"processing file {str(filename)}")
            with gzip.open(str(filename), "rt") as logfile:
                for line in logfile:
                    parts = line.split(" ")
                    symbol = parts[2]

                    if symbol.endswith("USDT"):
                        usdtfile.write(line)

                    if symbol.endswith("BTC"):
                        btcfile.write(line)

                    if symbol.endswith("BNB"):
                        bnbfile.write(line)

                    if symbol.endswith("ETH"):
                        ethfile.write(line)


                    coinfilename = f"coin.{symbol}.log"
                    if symbol not in coinfh:
                        coinfh[symbol] = open(coinfilename, "wt")
                        coinfiles.add(coinfilename)

                    coinfh[symbol].write(line)

        for symbol in coinfh:
            coinfh[symbol].close()

        usdtfile.close()
        btcfile.close()
        bnbfile.close()
        ethfile.close()

        coinfiles.add("pair.USDT.log")
        coinfiles.add("pair.BTC.log")
        coinfiles.add("pair.BNB.log")
        coinfiles.add("pair.ETH.log")

        tasks = []
        with mp.Pool(processes=os.cpu_count()) as pool:
            for filename in coinfiles:
                job = pool.apply_async(
                   compress_file,(filename,)
                )
                tasks.append(job)
            for t in tasks:
                t.get()


    except Exception:  # pylint: disable=broad-except
        logging.error(traceback.format_exc())
        sys.exit(1)

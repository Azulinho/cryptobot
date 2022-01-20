import argparse
import logging
import os
import re
import sys
import traceback
import gzip
import shutil
import multiprocessing as mp
import random
import string
import yaml
import subprocess
import time

from pathlib import Path

import random, string

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", help="config.yaml template")
    args = parser.parse_args()

    with open(f"configs/{args.config}", encoding="utf-8") as cfgtmpl:
        body = cfgtmpl.read()
        tickers = yaml.safe_load(body)['TICKERS'].keys()

        jobs = []
        with mp.Pool(processes=os.cpu_count() * 2) as pool:
            for symbol in tickers:
                with open(f"configs/coin.{symbol}.{args.config}", "wt") as tc:
                    newbody = body.replace("COINTEMPLATE", symbol)
                    tc.write(newbody)

                job = pool.apply_async(
                   os.system, (f"make backtesting CONFIG=coin.{symbol}.{args.config} >/dev/null 2>&1", )
                )
                time.sleep(0.1)
                jobs.append(job)

            for j in jobs:
                j.get()


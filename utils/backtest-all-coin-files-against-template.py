import argparse
import logging
import os
import re
import sys
import traceback
import gzip
import shutil
import random
import string
import yaml
import subprocess
import time

from concurrent.futures import ThreadPoolExecutor

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
        with ThreadPoolExecutor(os.cpu_count() * 2) as pool:
            for symbol in tickers:
                with open(f"configs/coin.{symbol}.{args.config}", "wt") as tc:
                    newbody = body.replace("COINTEMPLATE", symbol)
                    tc.write(newbody)

                job = pool.submit(
                   subprocess.run, f"make backtesting CONFIG=coin.{symbol}.{args.config} >/dev/null 2>&1", shell=True
                )
                #time.sleep(0.01)
                jobs.append(job)

            for j in jobs:
                j.done()

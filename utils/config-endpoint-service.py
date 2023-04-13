""" config-endpoint-service """
import argparse
import hashlib
import json
import os
import subprocess
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict

import yaml
from flask import Flask, jsonify, Response

g: Dict[str, Any] = {}
app: Flask = Flask(__name__)


def log_msg(msg: str) -> None:
    """logs out message prefixed with timestamp"""
    now: str = datetime.now().strftime("%H:%M:%S")
    print(f"{now} {msg}")


def run_prove_backtesting() -> None:
    """calls prove-backtesting"""

    yesterday: datetime = datetime.now() - timedelta(days=1)
    end_date: str = yesterday.strftime("%Y%m%d")

    with open("configs/CONFIG_ENDPOINT_SERVICE.yaml", "w") as c:
        endpoint_config: dict[str, Any] = g["CONFIG"]
        endpoint_config["FROM_DATE"] = end_date
        endpoint_config["END_DATE"] = end_date
        # prove-backtestin won't take 0 but it doesn't matter as
        # we're giving yesterday's date as the start/end date and the logs
        # for today (ROLL_FORWARD=1) don't exist yet.
        endpoint_config["ROLL_FORWARD"] = int(1)
        c.write(json.dumps(endpoint_config))

    subprocess.run(
        "python -u utils/prove-backtesting.py "
        + "-c configs/CONFIG_ENDPOINT_SERVICE.yaml",
        shell=True,
        check=False,
    )


@app.route("/")
def root() -> Response:
    """Flask / handler"""
    strategy: str = g["CONFIG"]["STRATEGY"]

    with open(f"configs/optimized.{strategy}.yaml") as c:
        cfg: Dict[str, Any] = yaml.safe_load(c.read())
        hashstr: str = hashlib.md5(
            (json.dumps(cfg["TICKERS"], sort_keys=True)).encode("utf-8")
        ).hexdigest()
        cfg["md5"] = hashstr
    return jsonify(cfg)


def api_endpoint() -> None:
    """runs Flask"""
    app.run(debug=True, use_reloader=False, host="0.0.0.0", port=5883)


if __name__ == "__main__":
    parser: argparse.ArgumentParser = argparse.ArgumentParser()
    parser.add_argument(
        "-c", "--config", help="prove-backtesting config.yaml file"
    )

    args: argparse.Namespace = parser.parse_args()

    with open(args.config, "rt") as f:
        config: Any = yaml.safe_load(f.read())

    g["CONFIG"] = config

    t: threading.Thread = threading.Thread(target=api_endpoint)
    t.daemon = True
    t.start()

    while True:
        time.sleep(1)
        if os.path.exists("control/RUN"):
            log_msg("control/RUN flag found")
            os.unlink("control/RUN")
            run_prove_backtesting()

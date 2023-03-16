#!/bin/bash
ulimit -n 65535
source /cryptobot/.venv/bin/activate
python -u /cryptobot/utils/prove-backtesting.py -c configs/${CONFIG_FILE}

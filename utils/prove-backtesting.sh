#!/bin/bash
ulimit -n 65535
source /cryptobot/.venv/bin/activate
python -u /cryptobot/utils/prove-backtesting.py -d ${FROM} -b ${BACKTRACK} -c ${CONFIG} -m ${MIN} -f ${FORWARD} -e ${TO} -s ${SORTBY}

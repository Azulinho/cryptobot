#!/bin/bash
set -x
ulimit -n 65535
source /cryptobot/.venv/bin/activate
python -u /cryptobot/utils/prove-backtesting.py \
	-d ${FROM} -b ${BACKTRACK} -c ${CONFIG_FILE} -m ${MIN} \
	-f ${FORWARD} -e ${TO} -s ${SORTBY}

#!/usr/bin/env bash
ulimit -n 65535
source /cryptobot/.venv/bin/activate
python -u utils/automated-backtesting.py \
	-l ${LOGFILE} -c ${CONFIG_FILE} -m ${MIN} -f "${FILTER}" -s "${SORTBY}"

#!/bin/bash
ulimit -n 65535
source /cryptobot/.venv/bin/activate
python -u utils/config-endpoint-service.py -c ${CONFIG_FILE} -b ${BACKTRACK} -s ${SORTBY} -t ${TUNED_CONFIG} -p ${PAIRING} -m ${MIN}

#!/bin/bash
ulimit -n 65535
source /cryptobot/.venv/bin/activate
python -u utils/config-endpoint-service.py -c ${CONFIG} -b ${BACKTRACK} -s ${SORTBY} -r ${RUN_AT} -t ${TUNED_CONFIG} -p ${PAIRING} -m ${MIN}

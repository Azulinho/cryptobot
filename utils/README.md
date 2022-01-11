split-logs-into-coins.py
========================

splits a set of daily price logs into separate coin.log.gz files, one for each
coin.

this script consume a lot of file handles, before running it, execute:

```
ulimit -n 8192
cd cryptobot/logs
python ../utils/split-logs-into-coins.py -g "2021*"
```

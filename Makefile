.PHONY: default
default: help ;

logmode:
	U="$$(id -u)" G="$$(id -g)" docker-compose run --name cryptobot.logmode.$(CONFIG) --rm --service-ports cryptobot -s /secrets/binance.prod.yaml -c /configs/$(CONFIG)  -m  logmode > log/logmode.$(CONFIG).txt 2>&1

testnet:
	U="$$(id -u)" G="$$(id -g)" docker-compose run --rm --name cryptobot.testnet.$(CONFIG) --service-ports cryptobot -s /secrets/binance.testnet.yaml -c /configs/$(CONFIG)  -m  testnet  > log/testnet.$(CONFIG).txt 2>&1

live:
	U="$$(id -u)" G="$$(id -g)" docker-compose run --rm --name cryptobot.live.$(CONFIG) --service-ports cryptobot -s /secrets/binance.prod.yaml -c /configs/$(CONFIG)  -m  live  >> log/live.$(CONFIG).txt 2>&1

backtesting:
	U="$$(id -u)" G="$$(id -g)" docker-compose run --name cryptobot.backtesting.$(CONFIG) --rm --service-ports cryptobot -s /secrets/binance.prod.yaml -c /configs/$(CONFIG)  -m  backtesting  > results/$(CONFIG).txt 2>&1

split-logs-into-coins:
	ulimit -n 8192; cd log; python3 ../utils/split-logs-into-coins.py -g "$(LOGS)"

backtest-all-coin-files:
	python3 utils/backtest-all-coin-files-against-template.py -c "$(TEMPLATE)"

slice-of-log:
	cut -c1- log/backtesting.log | grep cfg: |  cut -d "|" -f 1,3,4,5,6 | cut -d " " -f 1,22-40 | tr -d " " |cut -c8- | sort -n | cut -d "|" -f 1-4

generate-coincfg-for-coins:
	python3 utils/generate-configs-from-backtestinglog.py -l $(LOG) -m $(MIN) -o coincfg

generate-cfgname-for-coins:
	python3 utils/generate-configs-from-backtestinglog.py -l $(LOG) -m $(MIN) -o cfgname

help:
	@echo "USAGE:"
	@echo "make logmode CONFIG=< config.yaml >"
	@echo "make backtesting CONFIG=< config.yaml >"
	@echo "make testnet CONFIG=< config.yaml >"
	@echo "make live CONFIG=< config.yaml >"
	@echo "make split-logs-into-coins LOGS=< 2021*.log.gz >"
	@echo "make backtest-all-coin-files TEMPLATE=< template.yaml >"
	@echo "make slice-of-log"
	@echo "make generate-cfgname-for-coins LOG=log/backtesting.log MIN=30"
	@echo "make generate-coincfg-for-coins LOG=log/backtesting.log MIN=30"

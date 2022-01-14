.PHONY: default
default: help ;

backtesting:
	U="$$(id -u)" G="$$(id -g)" docker-compose run --name cryptobot.backtesting.${CONFIG} --rm --service-ports cryptobot -s /secrets/binance.prod.yaml -c /configs/$(CONFIG)  -m  backtesting  > results/$(CONFIG).txt

testnet:
	U="$$(id -u)" G="$$(id -g)" docker-compose run --rm --name cryptobot.testnet.${CONFIG} --service-ports cryptobot -s /secrets/binance.testnet.yaml -c /configs/$(CONFIG)  -m  testnet  > results/$(CONFIG).txt

live:
	U="$$(id -u)" G="$$(id -g)" docker-compose run --rm --name cryptobot.live.${CONFIG} --service-ports cryptobot -s /secrets/binance.prod.yaml -c /configs/$(CONFIG)  -m  live  > results/$(CONFIG).txt

split-logs-into-coins:
	ulimit -n 8192; cd log; python3 ../utils/split-logs-into-coins.py -g "$(LOGS)"

backtest-all-coin-files:
	python3 utils/backtest-all-coin-files-against-template.py -c "$(TEMPLATE)"

slice-of-log:
	cut -c1- log/backtesting.log | grep cfg: |  cut -d "|" -f 1,3,4,5,6 | cut -d " " -f 1,22-41 | tr -d " " |cut -c8- | sort -n

help:
	@echo "USAGE:"
	@echo "make backtesting CONFIG=< config.yaml >"
	@echo "make testnet CONFIG=< config.yaml >"
	@echo "make live CONFIG=< config.yaml >"
	@echo "make split-logs-into-coins LOGS=< 2021*.log.gz >"
	@echo "make backtest-all-coin-files TEMPLATE=< template.yaml >"
	@echo "make slice-of-log"

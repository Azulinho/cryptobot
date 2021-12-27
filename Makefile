
backtesting:
	U="$$(id -u)" G="$$(id -g)" docker-compose run --service-ports cryptobot -s /secrets/binance.prod.yaml -c /configs/$(CONFIG).yaml  -m  backtesting  > results/$(CONFIG).txt

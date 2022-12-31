""" bot buy strategy file """
from lib.bot import Bot
from lib.coin import Coin
from lib.helpers import c_from_timestamp, logging, percent


class Strategy(Bot):
    """BuyDropSellRecoveryStrategyWhenBTCisUp"""

    def buy_strategy(self, coin: Coin) -> bool:
        """BuyDropSellRecoveryStrategyWhenBTCisUp buy_strategy

        this strategy only buys coins when the price of bitcoin is heading up.
        it waits until BTC has gone up by KLINES_SLICE_PERCENTAGE_CHANGE in
        the KLINES_TREND_PERIOD before looking at coin prices.
        Then as the price of a coin has gone down by the BUY_AT_PERCENTAGE
        it marks the coin as TARGET_DIP.
        wait for the coin to go up in price by TRAIL_RECOVERY_PERCENTAGE
        before buying the coin

        """

        BTC = f"BTC{self.pairing}"
        # with this strategy we never buy BTC
        if coin.symbol == BTC:
            return False

        if BTC not in self.coins:
            return False

        unit = str(self.coins[BTC].klines_trend_period[-1:]).lower()
        klines_trend_period = int(self.coins[BTC].klines_trend_period[:-1])

        last_period = list(self.coins[BTC].averages[unit])[
            -klines_trend_period:
        ]

        if len(last_period) < klines_trend_period:
            return False

        last_period_slice = last_period[0][1]
        for _, n in last_period[1:]:
            if (
                percent(
                    100
                    + float(self.coins[BTC].klines_slice_percentage_change),
                    last_period_slice,
                )
                > n
            ):
                return False
            last_period_slice = n

        # has the price gone down by x% on a coin we don't own?
        if (
            coin.price < percent(coin.buy_at_percentage, coin.max)
            and coin.status == ""
            and not coin.naughty
        ):
            coin.dip = coin.price
            logging.info(
                f"{c_from_timestamp(coin.date)}: {coin.symbol} [{coin.status}] "
                + f"-> [TARGET_DIP] ({coin.price})"
            )
            coin.status = "TARGET_DIP"

        if coin.status != "TARGET_DIP":
            return False

        # do some gimmicks, and don't buy the coin straight away
        # but only buy it when the price is now higher than the last
        # price recorded. This way we ensure that we got the dip
        self.log_debug_coin(coin)
        if coin.price < coin.last:
            if coin.price > percent(coin.trail_recovery_percentage, coin.dip):
                self.buy_coin(coin)
                return True
        return False

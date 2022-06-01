""" bot buy strategy file """
from app import Bot, Coin
from lib.helpers import percent


class Strategy(Bot):
    """BuyMoonSellRecoveryStrategy"""

    def buy_strategy(self, coin: Coin) -> bool:
        """BuyMoonSellRecoveryStrategy buy_strategy

        this strategy looks for a price change between the last price recorded
        the current price, and if it was gone up by BUY_AT_PERCENTAGE
        it buys the coin.

        """
        if coin.price > percent(coin.buy_at_percentage, coin.last):
            self.buy_coin(coin)
            self.log_debug_coin(coin)
            return True
        return False

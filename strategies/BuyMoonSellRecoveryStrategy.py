from app import Bot, Coin
from lib.helpers import percent


class Strategy(Bot):
    """Base Strategy Class"""

    def buy_strategy(self, coin: Coin) -> bool:
        """bot buy strategy"""
        if float(coin.price) > percent(coin.buy_at_percentage, coin.last):
            self.buy_coin(coin)
            self.log_debug_coin(coin)
            return True
        return False

import sys
sys.path.insert(0, '')

import app
import pytest
import socket
import requests
from unittest import mock

from binance.client import Client

app.MODE = "backtesting"
app.PAUSE_FOR = 1
app.INITIAL_INVESTMENT = 100
app.MAX_COINS = 2
app.PAIRING="USDT"
app.SOFT_LIMIT_HOLDING_TIME = 3600
app.HARD_LIMIT_HOLDING_TIME = 7200
app.BUY_AT_PERCENTAGE = -5.0
app.SELL_AT_PERCENTAGE = +1.0
app.STOP_LOSS_AT_PERCENTAGE = -9
app.CLEAR_COIN_STATS_AT_BOOT = True
app.TRAIL_TARGET_SELL_PERCENTAGE = -0.1
app.TRAIL_RECOVERY_PERCENTAGE = +0.5
app.NAUGHTY_TIMEOUT = 28800
app.CLEAR_COIN_STATS_AT_SALE = True
app.DEBUG = False
app.STRATEGY="buy_drop_sell_recovery_strategy"
app.TICKERS_FILE = "tickers/all.txt"
app.TICKERS = ["BTCUSDT"]
app.TRADING_FEE = 0.1
app.PRICE_LOGS = ["prices.log"]
app.EXCLUDED_COINS = [
    'DOWNUSDT',
    'UPUSDT',
]



def test_percent():
    assert app.percent(0.1, 100.0) == 0.1

@pytest.fixture()
def bot():
    with mock.patch('binance.client.Client', new_callable=mock.PropertyMock
    ) as mock1:
        mock1.return_value = None
        client = Client("FAKE", "FAKE")

        with mock.patch('requests.get', return_value={}
        ) as mock2:

            bot = app.Bot(client)
            bot.client.API_URL = "https://www.google.com"
            bot.tickers = ["BTCUSDT"]
            yield bot
            del(bot)

@pytest.fixture()
def coin():
    client = "fake"
    coin = app.Coin(
        client=client,
        symbol="BTCUSDT",
        date="2021",
        market_price=100.00,
        buy_at=(100 + app.BUY_AT_PERCENTAGE),
        sell_at=(100 + app.SELL_AT_PERCENTAGE),
        stop_loss=(100 + app.STOP_LOSS_AT_PERCENTAGE),
        trail_target_sell_percentage=(100 + app.TRAIL_TARGET_SELL_PERCENTAGE),
        trail_recovery_percentage=(100 + app.TRAIL_RECOVERY_PERCENTAGE)
    )
    yield coin
    del(coin)

#  class TestCoin:
#      def test_update(self):
#          assert False
#

class TestBot:

    def test_update_investment(self, bot):
        bot.profit = 10

        result = bot.update_investment()
        assert result is None
        assert bot.investment == 110

    def test_update_bot_profit_returns_None(self, bot, coin):
        result = bot.update_bot_profit(coin)
        assert result == None

    def test_update_bot_profit_on_profit(self, bot, coin):
        coin.cost = 100
        coin.value = 200
        coin.profit = 100

        result = bot.update_bot_profit(coin)
        # bought 100 of coin and paid 0.1% of fees which is 0.10
        # sold 200 of coin and paid 0.1% of fees which is 0.20
        assert float(round(bot.fees, 1)) == float(0.3)
        assert float(bot.profit) == float(99.7)

    def test_update_bot_profit_on_loss(self, bot, coin):
        coin.cost = 110
        coin.value = 100
        coin.profit = -10

        result = bot.update_bot_profit(coin)
        # bought 110 of coin and paid 0.1% of fees which is 0.11
        # sold 100 of coin and paid 0.1% of fees which is 0.10
        assert bot.profit == -10.21
        assert bot.fees == 0.21000000000000002


    def test_buy_coin_when_coin_already_on_wallet(self, bot, coin):
        bot.wallet = ["BTCUSDT"]
        bot.buy_coin(coin)
        assert bot.wallet == ["BTCUSDT"]

    def test_buy_coin_when_wallet_is_full(self, bot, coin):
        bot.wallet = ["BTCUSDT", "ETHUSDT"]
        bot.buy_coin(coin)
        assert bot.wallet == ["BTCUSDT", "ETHUSDT"]

    def test_buy_coin_when_coin_is_naughty(self, bot, coin):
        coin.naughty_timeout = 1
        bot.buy_coin(coin)
        assert bot.wallet == []

    @mock.patch('app.Bot.get_symbol_precision', return_value=1)
    def test_buy_coin_in_backtesting(self, mocked, bot, coin):
        bot.mode = "backtesting"
        coin.price = 100

        bot.buy_coin(coin)
        assert bot.wallet == ["BTCUSDT"]
        assert coin.bought_at == 100
        assert coin.volume == 0.5

    def test_buy_coin_in_testnet(self, bot, coin):
        bot.mode = "testnet"
        coin.price = 100

        with mock.patch.object(
            bot.client, 'create_order', return_value={
                "symbol": "BTCUSDT",
                "orderId": "1",
                "transactTime": 1507725176595,
                "fills": [
                    {
                        "price": "100",
                        "qty": "1",
                        "commission": "1",
                    }
                ]
            }
        ) as m1:
            with mock.patch.object(
                bot.client, 'get_all_orders', return_value=[
                    {
                        "symbol": "BTCUSDT",
                        "orderId": 1
                    }
                ]
            ) as m2:
                with mock.patch.object(
                    bot, 'get_symbol_precision', return_value=1
                ) as m3:

                    bot.buy_coin(coin)
                    assert bot.wallet == ["BTCUSDT"]
                    assert coin.bought_at == 100
                    assert coin.volume == 0.5
                    # TODO: assert that clear_all_coins_stats


    def test_sell_coin_in_testnet(self, bot, coin):
        bot.mode = "testnet"
        coin.price = 100
        bot.wallet = [ "BTCUSDT" ]
        bot.coins["BTCUSDT"] = coin

        with mock.patch.object(
            bot.client, 'create_order', return_value={
                "symbol": "BTCUSDT",
                "orderId": "1",
                "transactTime": 1507725176595,
                "fills": [
                    {
                        "price": "100",
                        "qty": "1",
                        "commission": "1",
                    }
                ]
            }
        ) as m1:
            with mock.patch.object(
                bot.client, 'get_all_orders', return_value=[
                    {
                        "symbol": "BTCUSDT",
                        "orderId": 1
                    }
                ]
            ) as m2:
                with mock.patch.object(
                    bot, 'get_symbol_precision', return_value=1
                ) as m3:
                    bot.sell_coin(coin)
                    assert bot.wallet == []
                    assert float(coin.price) == float(100)
                    assert float(coin.bought_at) == float(0)
                    assert float(coin.value) == float(0.0)


    def test_get_symbol_precision(self, bot, coin):
        with mock.patch.object(
            bot.client, 'get_symbol_info', return_value={
                "symbol": "BTCUSDT",
                "filters": [
                    {},
                    {},
                    { "stepSize": "0.1" }
                ]
            }
        ) as m1:
            result = bot.get_symbol_precision('BTCUSDT')
            assert result == 1

    def test_extract_order_data(self):
        pass

    def test_calculate_volume_size(self, bot, coin):
        with mock.patch.object(
            bot, 'get_symbol_precision', return_value=1
        ) as m1:
            volume = bot.calculate_volume_size(coin)
            assert volume == 0.5

    def test_get_binance_prices(self, bot, coin):
        pass

    def test_init_or_update_coin(self, bot, coin):
        binance_data = {"symbol":"BTCUSDT","price":"101.000"}

        result = bot.init_or_update_coin(binance_data)
        assert result == None

        assert float(bot.coins['BTCUSDT'].price) == float(101.0)
        assert bot.coins['BTCUSDT'].buy_at_percentage == float(
            100 + app.BUY_AT_PERCENTAGE
        )
        assert bot.coins['BTCUSDT'].stop_loss_at_percentage == float(
            100 + app.STOP_LOSS_AT_PERCENTAGE
        )
        assert bot.coins['BTCUSDT'].sell_at_percentage == float(
            100 + app.SELL_AT_PERCENTAGE
        )
        assert bot.coins['BTCUSDT'].trail_target_sell_percentage == float(
            100 + app.TRAIL_TARGET_SELL_PERCENTAGE
        )
        assert bot.coins['BTCUSDT'].trail_recovery_percentage == float(
            100 + app.TRAIL_RECOVERY_PERCENTAGE
        )


    def test_process_coins(self, bot, coin):
        # TODO: this should only assert that the strategy is called
        # and not verify the strategy
        with mock.patch.object(
            bot.client, 'create_order', return_value={
                "symbol": "BTCUSDT",
                "orderId": "1",
                "transactTime": 1507725176595,
                "fills": [
                    {
                        "price": "100",
                        "qty": "1",
                        "commission": "1",
                    }
                ]
            }
        ) as m1:
            with mock.patch.object(
                bot.client, 'get_all_orders', return_value=[
                    {
                        "symbol": "BTCUSDT",
                        "orderId": 1
                    }
                ]
            ) as m2:
                with mock.patch.object(
                    bot, 'get_symbol_precision', return_value=1
                ) as m3:
                    binance_data = [
                        {"symbol":"BTCUSDT","price":"101.000"},
                        {"symbol":"BTCUSDT","price":"70.000"},
                        {"symbol":"BTCUSDT","price":"75.000"},
                    ]
                    with mock.patch.object(
                        bot, 'get_binance_prices', return_value=binance_data
                    ) as m4:
                        bot.process_coins()
                        assert bot.wallet == ["BTCUSDT"]

                    binance_data = [
                        {"symbol":"BTCUSDT","price":"101.000"},
                        {"symbol":"BTCUSDT","price":"98.000"},
                    ]

                    with mock.patch.object(
                        bot, 'get_binance_prices', return_value=binance_data
                    ) as m4:
                        bot.process_coins()
                        assert bot.wallet == []


    def test_stop_loss(self, bot, coin):
        bot.wallet = ["BTCUSDT"]
        coin.bought_at = 100
        coin.cost = 100
        coin.price = 20
        coin.value = 20
        coin.volume = 1

        with mock.patch.object(
            bot.client, 'create_order', return_value={
                "symbol": "BTCUSDT",
                "orderId": "1",
                "transactTime": 1507725176595,
                "fills": [
                    {
                        "price": "100",
                        "qty": "1",
                        "commission": "1",
                    }
                ]
            }
        ) as m1:
            with mock.patch.object(
                bot.client, 'get_all_orders', return_value=[
                    {
                        "symbol": "BTCUSDT",
                        "orderId": 1
                    }
                ]
            ) as m2:
                bot.stop_loss(coin)
                assert bot.wallet == []
                assert bot.profit == -80.12
                assert round(bot.investment, 2) == float(19.88)
                assert bot.losses == 1


    def test_coin_gone_up_and_dropped(self, bot, coin):
        bot.wallet = ["BTCUSDT"]
        coin.bought_at = 100
        coin.cost = 100
        coin.price = 1
        coin.profit = -99
        coin.status = "TARGET_SELL"
        coin.value = 1
        coin.volume = 1
        with mock.patch.object(
            bot.client, 'create_order', return_value={
                "symbol": "BTCUSDT",
                "orderId": "1",
                "transactTime": 1507725176595,
                "fills": [
                    {
                        "price": "100",
                        "qty": "1",
                        "commission": "1",
                    }
                ]
            }
        ) as m1:
            with mock.patch.object(
                bot.client, 'get_all_orders', return_value=[
                    {
                        "symbol": "BTCUSDT",
                        "orderId": 1
                    }
                ]
            ) as m2:

                result = bot.coin_gone_up_and_dropped(coin)
                assert result == True
                assert bot.wins == 1
                assert bot.profit == -99.101
                assert round(bot.investment, 1) == round(0.89, 1)


    def test_possible_sale(self, bot, coin):
        bot.wallet = ["BTCUSDT"]
        coin.bought_at = 100
        coin.cost = 100
        coin.tip = 300
        coin.last = 290
        coin.price = 200
        coin.profit = 100
        coin.status = "TARGET_SELL"
        coin.value = 200
        coin.volume = 1
        with mock.patch.object(
            bot.client, 'create_order', return_value={
                "symbol": "BTCUSDT",
                "orderId": "1",
                "transactTime": 1507725176595,
                "fills": [
                    {
                        "price": "100",
                        "qty": "1",
                        "commission": "1",
                    }
                ]
            }
        ) as m1:
            with mock.patch.object(
                bot.client, 'get_all_orders', return_value=[
                    {
                        "symbol": "BTCUSDT",
                        "orderId": 1
                    }
                ]
            ) as m2:

                result = bot.possible_sale(coin)
                assert result == True
                assert bot.wins == 1
                assert bot.profit == 99.7
                assert round(bot.investment, 1) == round(199.7, 1)

    def test_past_hard_limit(self, bot, coin):
        bot.wallet = ["BTCUSDT"]
        coin.bought_at = 100
        coin.cost = 100
        coin.tip = 300
        coin.last = 290
        coin.price = 200
        coin.profit = 100
        coin.value = 200
        coin.volume = 1
        coin.holding_time = 9999999
        with mock.patch.object(
            bot.client, 'create_order', return_value={
                "symbol": "BTCUSDT",
                "orderId": "1",
                "transactTime": 1507725176595,
                "fills": [
                    {
                        "price": "100",
                        "qty": "1",
                        "commission": "1",
                    }
                ]
            }
        ) as m1:
            with mock.patch.object(
                bot.client, 'get_all_orders', return_value=[
                    {
                        "symbol": "BTCUSDT",
                        "orderId": 1
                    }
                ]
            ) as m2:

                result = bot.past_hard_limit(coin)
                assert result == True
                assert bot.stales == 1
                assert bot.profit == 99.7
                assert coin.naughty_timeout == app.NAUGHTY_TIMEOUT
                assert round(bot.investment, 1) == round(199.7, 1)

    def test_past_soft_limit(self, bot, coin):
        coin.bought_at = 100
        coin.cost = 100
        coin.tip = 300
        coin.last = 290
        coin.price = 200
        coin.profit = 100
        coin.value = 200
        coin.volume = 1
        coin.holding_time = 9999999
        with mock.patch.object(
            bot.client, 'create_order', return_value={
                "symbol": "BTCUSDT",
                "orderId": "1",
                "transactTime": 1507725176595,
                "fills": [
                    {
                        "price": "100",
                        "qty": "1",
                        "commission": "1",
                    }
                ]
            }
        ) as m1:
            with mock.patch.object(
                bot.client, 'get_all_orders', return_value=[
                    {
                        "symbol": "BTCUSDT",
                        "orderId": 1
                    }
                ]
            ) as m2:

                result = bot.past_soft_limit(coin)
                assert result == True
                assert coin.naughty_timeout == 0

    def test_clear_all_coins_stats(self, bot, coin):
        coin1 = coin
        coin2 = coin
        coin1.symbol = "BTCUSDT"
        coin1.status = "DIRTY"
        coin2.symbol = "ETHUSDT"
        coin2.status = "DIRTY"
        bot.coins['BTCUSDT'] = coin1
        bot.coins['ETHUSDT'] = coin2

        result = bot.clear_all_coins_stats()
        assert result is None
        assert bot.coins['BTCUSDT'].status == ""
        assert bot.coins['ETHUSDT'].status == ""

    def test_clear_coin_stats(self, bot, coin):
        coin.status = "DIRTY"
        coin.holding_time = 999
        coin.buy_at_percentage = 999
        coin.sell_at_percentage = 999
        coin.stop_loss_at_percentage = 999
        coin.trail_target_sell_percentage = 999
        coin.trail_recovery_percentage = 999
        coin.bought_at = float(9999)
        coin.dip = float(9999)
        coin.tip = float(9999)
        coin.max = float(9999)
        coin.min = float(9999)

        bot.clean_coin_stats_at_sale = False
        result = bot.clear_coin_stats(coin)
        assert result == None
        assert coin.status == ""
        assert coin.holding_time == 0
        assert coin.buy_at_percentage == bot.buy_at_percentage
        assert coin.sell_at_percentage == bot.sell_at_percentage
        assert coin.stop_loss_at_percentage == bot.stop_loss_at_percentage
        assert coin.trail_target_sell_percentage == bot.trail_target_sell_percentage
        assert coin.trail_recovery_percentage == bot.trail_recovery_percentage
        assert coin.bought_at == float(0)
        assert coin.dip == float(0)
        assert coin.tip == float(0)
        assert coin.max == float(9999)
        assert coin.min == float(9999)

        bot.clean_coin_stats_at_sale = True
        result = bot.clear_coin_stats(coin)
        assert result == None
        assert coin.min == coin.price
        assert coin.max == coin.price

    def test_buy_drop_sell_recovery_strategy(self, bot, coin):
        pass

    def test_buy_moon_sell_recovery_strategy(self, bot, coin):
        pass


class TestBotCheckForSaleConditions:
    def test_returns_early_on_empty_wallet(self, bot, coin):
        bot.wallet = []
        result = bot.check_for_sale_conditions(coin)
        assert result == (False, 'EMPTY_WALLET')

    def test_returns_early_on_stop_loss(self, bot, coin):
        bot.wallet = ["BTCUSDT"]
        coin.price = 1
        coin.bought_at = 100
        result = bot.check_for_sale_conditions(coin)
        assert result == (True, 'STOP_LOSS')

    def test_returns_early_on_stale_coin(self, bot, coin):
        bot.wallet = ["BTCUSDT"]
        coin.price = 1000
        coin.holding_time = 99999
        coin.status = "DIRTY"
        bot.hard_limit_holding_time = 1
        result = bot.check_for_sale_conditions(coin)
        assert result == (True, 'STALE')

    def test_returns_early_on_coing_gone_up_and_dropped(self, bot, coin):
        bot.wallet = ["BTCUSDT"]
        coin.status = "TARGET_SELL"
        coin.price = 100.5
        coin.last = 120
        coin.bought_at = 100
        result = bot.check_for_sale_conditions(coin)
        print(coin.stop_loss_at_percentage)
        assert result == (True, 'GONE_UP_AND_DROPPED')

    def test_returns_early_on_possible_sale(self, bot, coin):
        bot.wallet = ["BTCUSDT"]
        coin.status = "TARGET_SELL"
        coin.bought_at = 1
        coin.price = 50
        coin.last = 100
        coin.tip = 200
        result = bot.check_for_sale_conditions(coin)
        assert result == (True, 'TARGET_SELL')

    def test_returns_final_on_past_soft_limit(self, bot, coin):
        bot.wallet = ["BTCUSDT"]
        coin.bought_at = 100
        coin.price = 100
        coin.last = 100
        coin.tip = 100
        result = bot.check_for_sale_conditions(coin)
        assert result == (False, 'HOLD')

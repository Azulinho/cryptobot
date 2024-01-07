""" cryptobot/databank/models.py """
from django.db import models


class Mappings(models.Model):  # pylint: disable=too-few-public-methods
    """SQLAlchemy DB Model"""

    __tablename__ = "mappings"

    filename = models.CharField(max_length=256, primary_key=True)
    timeframe = models.CharField(max_length=3)
    symbol = models.CharField(max_length=32)
    pair = models.CharField(max_length=32)
    open_timestamp = models.BigIntegerField()
    close_timestamp = models.BigIntegerField()

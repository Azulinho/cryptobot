""" cryptobot/databank/urls.py """
from django.urls import path
from . import views

urlpatterns = [
    path("v1/klines", views.handler_klines, name="klines"),
    path("v1/symbols", views.handler_symbols, name="symbols"),
    path("v1/aggregate", views.handler_aggregate, name="aggregate"),
    path(
        "v1/filenames",
        views.handler_hourly_filenames,
        name="handler_hourly_filenames",
    ),
]

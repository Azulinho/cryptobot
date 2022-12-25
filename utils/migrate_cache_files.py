""" migrates the cache files to the new symbol/file layout """
from glob import glob
from os import listdir, mkdir
from os.path import exists
from shutil import move

cache_files = listdir("cache")
for file in cache_files:
    if "precision" in file:
        continue
    symbol = file.split(".")[0]
    if not exists(f"cache/{symbol}"):
        print(f"creating cache/{symbol}")
        mkdir(f"cache/{symbol}")
    if file == symbol:
        continue

    print(f"moving cache/{file}")
    move(f"cache/{file}", f"cache/{symbol}/{file}")

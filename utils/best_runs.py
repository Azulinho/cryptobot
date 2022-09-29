import re
from os import listdir
from os.path import isfile, join

mypath = "./results/"
results_txt = [f for f in listdir(mypath) if isfile(join(mypath, f))]

filename_regex_str = "^prove-backtesting\.(.*\.*\.yaml)\.min(\d+)\.([wins|profit]+)\.(\d+)_(\d+)\.f(\d+)d\.b(\d+)d\.txt"

final_balance_regex = ".* PROVE-BACKTESTING: final balance for (.*): (\d+)"

proves_backtesting_files = {}

for result_txt in results_txt:
    matches = re.search(filename_regex_str, result_txt)
    if matches:
        proves_backtesting_files[result_txt] = {}
        proves_backtesting_files[result_txt]["strats"] = {}
        proves_backtesting_files[result_txt]["config"] = matches.group(1)
        proves_backtesting_files[result_txt]["min"] = matches.group(2)
        proves_backtesting_files[result_txt]["wins_profit"] = matches.group(3)
        proves_backtesting_files[result_txt]["start_date"] = matches.group(4)
        proves_backtesting_files[result_txt]["end_date"] = matches.group(5)
        proves_backtesting_files[result_txt]["forward"] = matches.group(6)
        proves_backtesting_files[result_txt]["backward"] = matches.group(7)

        with open(f"./results/{result_txt}") as f:
            lines = f.readlines()

            if len(lines[-1:]):
                if "PROVE-BACKTESTING: FINISHED" not in lines[-1:][0]:
                    continue
            else:
                continue


        with open(f"./results/{result_txt}") as f:
            for line in f:
                matches = re.search(final_balance_regex, line)
                if matches:
                    strategy = matches.group(1)
                    balance = matches.group(2)
                    proves_backtesting_files[result_txt]["strats"][
                        strategy
                    ] = balance

        top_balance = float(0)
        best_strat = ""
        for strat in proves_backtesting_files[result_txt]["strats"].keys():
            if (
                float(proves_backtesting_files[result_txt]["strats"][strat])
                > top_balance
            ):
                best_strat = strat
                top_balance = float(
                    proves_backtesting_files[result_txt]["strats"][strat]
                )

        proves_backtesting_files[result_txt]["best"] = best_strat
        if proves_backtesting_files[result_txt]["best"] != "":
            run = proves_backtesting_files[result_txt]
            print(
                f"{run['strats'][best_strat]} {run['best']} {run['config']} min:{run['min']} {run['wins_profit']} {run['start_date']} {run['end_date']} f:{run['forward']} b:{run['backward']}"
            )

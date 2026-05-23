import os
import sys

# Reconfigure stdout to use UTF-8
sys.stdout.reconfigure(encoding='utf-8')

backtest_dir = r"C:\Users\manir\Desktop\Backtest"
files = os.listdir(backtest_dir)
for f in files:
    print(repr(f))

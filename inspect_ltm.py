import os
import sys
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')

filepath = r"C:\Users\manir\Desktop\Backtest\✔✔LTM 2h.csv"
try:
    df = pd.read_csv(filepath)
    print("✔✔LTM 2h.csv:")
    print(f"  Shape: {df.shape}")
    print(f"  Columns: {list(df.columns)}")
    if not df.empty:
        print("  First row:")
        print(df.iloc[0])
        if 'Net P&L INR' in df.columns:
            pnl = df['Net P&L INR'].dropna()
            print(f"  Total Trades: {len(pnl)}")
            print(f"  Sum of P&L: {pnl.sum():,.2f}")
        elif 'Net P&L NONE' in df.columns:
            pnl = df['Net P&L NONE'].dropna()
            print(f"  Total Trades: {len(pnl)}")
            print(f"  Sum of P&L: {pnl.sum():,.2f}")
except Exception as e:
    print(f"Error reading ✔✔LTM 2h.csv: {e}")

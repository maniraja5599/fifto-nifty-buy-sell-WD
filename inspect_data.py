import os
import pandas as pd

backtest_dir = r"C:\Users\manir\Desktop\Backtest"
files = [f for f in os.listdir(backtest_dir) if f.endswith('.csv')]

print(f"Found {len(files)} backtest CSV files in {backtest_dir}:\n")

for file in sorted(files):
    filepath = os.path.join(backtest_dir, file)
    try:
        df = pd.read_csv(filepath)
        print(f"File: {file}")
        print(f"  Shape: {df.shape}")
        print(f"  Columns: {list(df.columns)}")
        if not df.empty:
            # Let's inspect some date info and P&L info
            # The dates might be in 'Date and time' column
            if 'Date and time' in df.columns:
                dates = pd.to_datetime(df['Date and time'])
                print(f"  Date Range: {dates.min()} to {dates.max()}")
            if 'Net P&L INR' in df.columns:
                # The exit rows have Net P&L INR. Entry rows usually have NaN or 0 or are empty for P&L.
                # Let's see
                pnl = df['Net P&L INR'].dropna()
                print(f"  Total Trades: {len(pnl)}")
                print(f"  Net P&L INR Sum: {pnl.sum():,.2f}")
                print(f"  Net P&L INR Mean: {pnl.mean():,.2f}")
        print("-" * 50)
    except Exception as e:
        print(f"Error reading {file}: {e}")

import os
import pandas as pd
import numpy as np

DATA_DIR = r"C:\Users\manir\.gemini\antigravity\scratch\fifto-nifty-pivot-gap\data"

def load_spot_data(date_str, instrument_name):
    """
    Loads tick data for a given date and instrument from the CSV file.
    """
    # Build standard CSV file name
    file_name = f"{date_str}_{instrument_name}.csv"
    file_path = os.path.join(DATA_DIR, file_name)
    
    if not os.path.exists(file_path):
        # Fallback to check if it has the options naming convention
        # (which might be e.g. <date>_<instrument>.csv)
        return None
        
    try:
        df = pd.read_csv(file_path)
        df['date_time'] = pd.to_datetime(df['date_time'])
        df['time'] = df['date_time'].dt.strftime('%H:%M:%S')
        return df
    except Exception as e:
        print(f"Error loading {file_path}: {e}")
        return None

def create_spot_ohlc(spot_ticks, timeframe="1T"):
    """
    Converts tick-level spot data into 1-minute OHLC candles.
    """
    df = spot_ticks.copy()
    df['date_time'] = pd.to_datetime(df['date_time'])
    df = df.set_index('date_time')
    
    # Resample to 1-minute OHLC using the 'price' column
    ohlc = df['price'].resample(timeframe).ohlc()
    ohlc = ohlc.reset_index()
    ohlc = ohlc.dropna().reset_index(drop=True)
    return ohlc

def list_trading_dates():
    """
    Lists unique sorted trading dates from the data directory.
    """
    if not os.path.exists(DATA_DIR):
        return []
        
    files = os.listdir(DATA_DIR)
    dates = set()
    for f in files:
        if f.endswith('.csv'):
            parts = f.split('_')
            if len(parts) >= 2 and len(parts[0]) == 8 and parts[0].isdigit():
                dates.add(parts[0])
                
    return sorted(list(dates))

def calculate_strike(spot_ref, opt_type, index_name="NIFTY", strike_type="atm"):
    """
    Calculates strike price (rounds NIFTY spot to nearest 50 for ATM).
    """
    if strike_type.lower() == "atm":
        return int(round(spot_ref / 50.0) * 50)
    # Default fallback
    return int(round(spot_ref / 50.0) * 50)

def build_instrument_name(index_name, strike, date_str, is_current_expiry, opt_type):
    """
    Builds the simulated option instrument name.
    Format: NIFTY_<strike>_<date_str>_<is_current_expiry>_<opt_type>
    """
    return f"{index_name}_{strike}_{date_str}_{is_current_expiry}_{opt_type}"

def price_at(spot_ticks, time_str):
    """
    Gets the first spot price available at or after the given time_str.
    """
    try:
        t = pd.Timestamp(f"2000-01-01 {time_str}").time()
        rows = spot_ticks[spot_ticks['date_time'].dt.time >= t]
        if not rows.empty:
            return round(rows.iloc[0]['price'], 2)
    except Exception as e:
        print(f"Error in price_at: {e}")
    return None

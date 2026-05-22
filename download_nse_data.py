import os
import urllib.request
import json
import pandas as pd
from datetime import datetime, timezone, timedelta

def download_nifty_spot():
    print("Fetching historical NIFTY 50 spot data from Yahoo Finance...")
    
    url = "https://query1.finance.yahoo.com/v8/finance/chart/^NSEI?interval=1m&range=7d"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            
        chart_data = data.get('chart', {}).get('result', [])
        if not chart_data:
            print("ERROR: No chart data found in Yahoo response.")
            return False
            
        result = chart_data[0]
        timestamps = result.get('timestamp', [])
        quote = result.get('indicators', {}).get('quote', [{}])[0]
        closes = quote.get('close', [])
        
        if not timestamps or not closes:
            print("ERROR: Timestamps or closes missing in Yahoo response.")
            return False
            
        print(f"Downloaded {len(timestamps)} data points. Processing dates...")
        
        # Convert to DataFrame
        records = []
        # IST is UTC + 5:30
        ist_offset = timedelta(hours=5, minutes=30)
        
        for ts, close in zip(timestamps, closes):
            if ts is None or close is None:
                continue
            # Convert timestamp to IST
            dt_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
            dt_ist = dt_utc + ist_offset
            
            # We only want standard market hours (09:15:00 to 15:30:00)
            time_str = dt_ist.strftime('%H:%M:%S')
            if '09:15:00' <= time_str <= '15:30:00':
                records.append({
                    'date_str': dt_ist.strftime('%Y%m%d'),
                    'date_time': dt_ist.strftime('%Y-%m-%d %H:%M:%S'),
                    'price': round(float(close), 2)
                })
                
        df = pd.DataFrame(records)
        if df.empty:
            print("ERROR: No data points fell within NIFTY market hours.")
            return False
            
        # Group by date and save to individual files
        base_dir = r"C:\Users\manir\.gemini\antigravity\scratch\nifty-pivot-gap-strategy\data"
        os.makedirs(base_dir, exist_ok=True)
        
        unique_dates = df['date_str'].unique()
        print(f"Unique dates found in downloaded data: {list(unique_dates)}")
        
        for date_str in unique_dates:
            day_df = df[df['date_str'] == date_str].copy()
            # Drop the helper column
            day_df = day_df.drop(columns=['date_str'])
            # Sort chronologically
            day_df = day_df.sort_values('date_time')
            
            file_name = f"{date_str}_NIFTY.csv"
            file_path = os.path.join(base_dir, file_name)
            day_df.to_csv(file_path, index=False)
            print(f"Saved real 1-min spot data to: {file_path} ({len(day_df)} rows)")
            
        print("Data download and formatting completed successfully!")
        return True
        
    except Exception as e:
        print(f"ERROR downloading data: {e}")
        return False

if __name__ == "__main__":
    download_nifty_spot()

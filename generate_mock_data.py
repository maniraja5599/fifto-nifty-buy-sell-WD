import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def calc_day_pivots(prices_prev):
    """
    Calculates Pivot (P), R1, and S1 from the previous day's spot prices.
    This exactly mirrors the backtester's calculation.
    """
    if not prices_prev:
        return None
    H = max(prices_prev)
    L = min(prices_prev)
    C = prices_prev[-1]
    P = round((H + L + C) / 3, 2)
    R1 = round(2 * P - L, 2)
    S1 = round(2 * P - H, 2)
    return {"P": P, "R1": R1, "S1": S1}

def generate_data():
    base_dir = r"C:\Users\manir\.gemini\antigravity\scratch\nifty-pivot-gap-strategy\data"
    os.makedirs(base_dir, exist_ok=True)
    
    # Generate 1 year of trading dates (from 2025-05-12 to 2026-05-21)
    # Skipping weekends
    start_date = datetime(2025, 5, 12)
    end_date = datetime(2026, 5, 21)
    
    trading_dates = []
    curr = start_date
    while curr <= end_date:
        if curr.weekday() < 5:  # Monday to Friday
            trading_dates.append(curr.strftime('%Y%m%d'))
        curr += timedelta(days=1)
        
    print(f"Generating high-fidelity data for {len(trading_dates)} days...")
    
    # Initial NIFTY spot price
    spot_price = 22000.0
    
    # Pre-calculate previous closes and daily prices
    prev_closes = {}
    daily_prices = {}
    
    # Set seed for reproducibility
    np.random.seed(100)
    
    # We will track our non-Thursday indices to distribute trade days deterministically
    non_thurs_idx = 0
    
    for i, date_str in enumerate(trading_dates):
        dt = datetime.strptime(date_str, '%Y%m%d')
        is_thursday = (dt.weekday() == 3)
        
        # Determine previous close and yesterday's price path
        if i == 0:
            prev_close = spot_price
            # Seed a high-quality previous day price path to make the first real day's pivots realistic
            prices_prev = [round(prev_close + x, 2) for x in np.linspace(-40, 45, 2251)]
        else:
            prev_date = trading_dates[i-1]
            prev_close = prev_closes[prev_date]
            prices_prev = daily_prices[prev_date]
            
        # Calculate mathematical pivots for today based on yesterday's actual spot prices
        pivots = calc_day_pivots(prices_prev)
        P = pivots["P"]
        R1 = pivots["R1"]
        S1 = pivots["S1"]
        
        # Total ticks in a day: 09:15:00 to 15:30:00 every 10 seconds = 2,251 ticks
        time_range = pd.date_range(
            start=f"{dt.strftime('%Y-%m-%d')} 09:15:00",
            end=f"{dt.strftime('%Y-%m-%d')} 15:30:00",
            freq='10s'
        )
        n_ticks = len(time_range)
        
        prices = []
        
        # Decide if today is a Thursday (skipped anyway) or a non-Thursday trade/no-trade day
        if is_thursday:
            # thursday is skipped. We just simulate a standard trend day.
            today_open = round(prev_close + np.random.uniform(-15, 15), 2)
            current = today_open
            for _ in range(n_ticks):
                current += np.random.normal(0, 1.5)
                prices.append(round(current, 2))
        else:
            # Distribute trade outcomes among non-Thursday days
            # We want exactly 50 trade days in total:
            # - 25 Wins (12 CE Wins, 13 PE Wins)
            # - 25 Losses (13 CE Losses, 12 PE Losses)
            is_trade_day = (non_thurs_idx % 4 == 0) and (non_thurs_idx < 200)
            
            if is_trade_day:
                # We have exactly 50 trade days at indices 0, 4, 8, ..., 196
                trade_num = non_thurs_idx // 4  # 0 to 49
                
                # Determine outcome and type
                # 25 wins, 25 losses
                if trade_num < 25:
                    outcome = 'win'
                    # 12 CE Wins, 13 PE Wins
                    opt_type = 'CE' if trade_num < 12 else 'PE'
                else:
                    outcome = 'loss'
                    # 13 CE Losses, 12 PE Losses
                    opt_type = 'CE' if (trade_num - 25) < 13 else 'PE'
                    
                # Generate matching gap and open price
                if opt_type == 'CE':
                    # Gap Up: Open > Pivot, Gap > 30
                    gap = np.random.uniform(35, 65)
                    today_open = round(max(prev_close + gap, P + 15.0), 2)
                    direction = 'LONG'
                else:
                    # Gap Down: Open < Pivot, Gap < -30
                    gap = np.random.uniform(-65, -35)
                    today_open = round(min(prev_close + gap, P - 15.0), 2)
                    direction = 'SHORT'
                    
                # Setup price path to touch P and then go to target or stop loss
                current = today_open
                touch_index = int(n_ticks * np.random.uniform(0.18, 0.32)) # Touch P around 10:30 AM
                
                # Phase 1: Drift from open to P
                for k in range(touch_index):
                    fraction = k / touch_index
                    target_temp = today_open - fraction * (today_open - P)
                    current = target_temp + np.random.normal(0, 1.2)
                    prices.append(round(current, 2))
                    
                # Ensure exact P touch at touch_index
                prices[touch_index - 1] = P
                
                # Phase 2: Hover near P for 60 ticks (10 minutes)
                hover_ticks = 60
                for k in range(hover_ticks):
                    current = P + np.random.normal(0, 0.8)
                    prices.append(round(current, 2))
                    
                # Phase 3: Trend strongly to Target (Win) or Stop Loss (Loss)
                elapsed_so_far = touch_index + hover_ticks
                remaining_ticks = n_ticks - elapsed_so_far
                
                # We want winning trends to hit targets quickly to preserve premium value (high-momentum wins)
                # We want losing trends to hit SL quickly to prevent premium recovery
                trend_ticks = 140 if outcome == 'win' else 110
                
                for k in range(remaining_ticks):
                    if k < trend_ticks:
                        fraction = k / trend_ticks
                        if outcome == 'win':
                            if direction == 'LONG':
                                # Rise to R1
                                target_val = R1
                            else:
                                # Fall to S1
                                target_val = S1
                            current = P + fraction * (target_val - P) + np.random.normal(0, 1.2)
                        else:
                            # Loss: Cross P - 20 (LONG) or P + 20 (SHORT) by 24 points
                            sl_offset = -24.0 if direction == 'LONG' else 24.0
                            current = P + fraction * sl_offset + np.random.normal(0, 1.2)
                    else:
                        # Hold after hitting target/SL
                        if outcome == 'win':
                            target_val = R1 if direction == 'LONG' else S1
                            current = target_val + np.random.normal(0, 1.5)
                        else:
                            sl_offset = -24.0 if direction == 'LONG' else 24.0
                            current = P + sl_offset + np.random.normal(0, 1.5)
                            
                    prices.append(round(current, 2))
                    
            else:
                # No trade day: either flat open or gap that never touches Pivot
                # 70% flat days, 30% gap days that trend away from Pivot
                no_trade_type = np.random.choice(['flat', 'no_touch_gap'], p=[0.70, 0.30])
                
                if no_trade_type == 'flat':
                    # Flat day: open is close to yesterday's close, oscilates around it
                    today_open = round(prev_close + np.random.uniform(-15, 15), 2)
                    current = today_open
                    for _ in range(n_ticks):
                        current = 0.98 * current + 0.02 * today_open + np.random.normal(0, 1.2)
                        prices.append(round(current, 2))
                else:
                    # No touch gap day: gap is large, but trends away from P
                    is_gap_up = np.random.choice([True, False])
                    if is_gap_up:
                        gap = np.random.uniform(35, 60)
                        today_open = round(max(prev_close + gap, P + 15.0), 2)
                        current = today_open
                        for k in range(n_ticks):
                            # Trend further up, staying far away from P
                            current = today_open + (k / n_ticks) * 40.0 + np.random.normal(0, 1.5)
                            prices.append(round(current, 2))
                    else:
                        gap = np.random.uniform(-60, -35)
                        today_open = round(min(prev_close + gap, P - 15.0), 2)
                        current = today_open
                        for k in range(n_ticks):
                            # Trend further down, staying far away from P
                            current = today_open - (k / n_ticks) * 40.0 + np.random.normal(0, 1.5)
                            prices.append(round(current, 2))
                            
            # Increment non-Thursday index
            non_thurs_idx += 1
            
        # Save Spot Ticks to CSV
        spot_df = pd.DataFrame({
            'date_time': time_range,
            'price': prices
        })
        spot_df['time'] = spot_df['date_time'].dt.strftime('%H:%M:%S')
        spot_df.to_csv(os.path.join(base_dir, f"{date_str}_NIFTY.csv"), index=False)
        
        # Save daily prices and close for next day pivots
        prev_closes[date_str] = prices[-1]
        daily_prices[date_str] = prices
        
        # Generate Option Ticks for 5 strikes around the open ATM strike to ensure availability
        atm_strike_open = int(round(today_open / 50.0) * 50)
        strikes = [atm_strike_open - 100, atm_strike_open - 50, atm_strike_open, atm_strike_open + 50, atm_strike_open + 100]
        
        for strike in strikes:
            for opt_type in ['CE', 'PE']:
                opt_prices = []
                for idx, row in spot_df.iterrows():
                    spot = row['price']
                    t_frac = idx / n_ticks  # 0 to 1
                    time_decay = 1.0 - t_frac * 0.28  # Moderate theta decay
                    
                    if opt_type == 'CE':
                        dist = spot - strike
                    else:
                        dist = strike - spot
                        
                    # Standard high-fidelity Delta curve matching realistic option pricing
                    x = dist / 90.0
                    delta = 0.53 + 0.35 * np.tanh(x)
                    
                    # Premium = base value * decay + intrinsic/delta-based value + noise
                    opt_price = (88.0 * time_decay) + (dist * delta) + np.random.normal(0, 0.3)
                    opt_price = round(max(2.0, opt_price), 2)
                    opt_prices.append(opt_price)
                    
                opt_df = pd.DataFrame({
                    'date_time': time_range,
                    'price': opt_prices
                })
                opt_df['time'] = opt_df['date_time'].dt.strftime('%H:%M:%S')
                
                inst_name = f"NIFTY_{strike}_{date_str}_True_{opt_type}"
                opt_df.to_csv(os.path.join(base_dir, f"{date_str}_{inst_name}.csv"), index=False)
                
    print("Mock data generated successfully with mathematical pivot alignment!")

if __name__ == "__main__":
    generate_data()

import os
import sys
import pandas as pd
from datetime import datetime
from my_util import (load_spot_data, create_spot_ohlc, list_trading_dates,
                     calculate_strike, build_instrument_name, price_at)

LOT_SIZE     = 65
GAP_THRESH   = 30
P_TOL        = 10
SL_PTS       = 20
ENTRY_CUTOFF = pd.Timestamp("13:00:00").time()
EOD_EXIT     = pd.Timestamp("15:20:00").time()

def calc_pivots(prev_date):
    df = load_spot_data(prev_date, "NIFTY")
    if df is None or df.empty: return None
    tr = df[(df['time'] >= '09:15:00') & (df['time'] <= '15:30:00')]
    if tr.empty: return None
    H = tr['price'].max(); L = tr['price'].min(); C = tr['price'].iloc[-1]
    R = H - L
    P  = round((H+L+C)/3, 2)
    R1 = round(2*P-L, 2);  S1 = round(2*P-H, 2)
    R2 = round(P+R, 2);    S2 = round(P-R, 2)
    return {"P":P, "R1":R1, "R2":R2, "S1":S1, "S2":S2}

def get_opt_pnl(date_str, opt_type, spot_ref, entry_time, exit_time):
    try:
        strike = calculate_strike(spot_ref, opt_type, "NIFTY", "atm")
        inst   = build_instrument_name("NIFTY", strike, date_str, True, opt_type)
        oticks = load_spot_data(date_str, inst)
        if oticks is None or oticks.empty: return None, None, None
        t_entry = pd.Timestamp(f"2000-01-01 {entry_time}").time()
        t_exit  = pd.Timestamp(f"2000-01-01 {exit_time}").time()
        
        entry_rows = oticks[oticks['date_time'].dt.time >= t_entry]
        exit_rows = oticks[oticks['date_time'].dt.time >= t_exit]
        
        if entry_rows.empty or exit_rows.empty:
            return None, None, None
            
        ep = round(entry_rows.iloc[0]['price'], 2)
        xp = round(exit_rows.iloc[0]['price'],  2)
        return ep, xp, round(xp - ep, 2)
    except Exception as e:
        return None, None, None

def check_live_signal(target_date=None):
    all_dates = list_trading_dates()
    if not all_dates:
        print("No trading data available in the data/ directory. Please run generate_mock_data.py first.")
        return
        
    if target_date is None:
        target_date = all_dates[-1]
        print(f"No date provided. Defaulting to the latest available trading date: {target_date}")
    elif target_date not in all_dates:
        print(f"Date {target_date} not found in available trading dates. Available: {all_dates[:5]} ... {all_dates[-5:]}")
        return
        
    idx = all_dates.index(target_date)
    if idx == 0:
        print(f"Cannot run check for the very first date {target_date} because previous day's data is needed for pivots.")
        return
        
    prev_date = all_dates[idx - 1]
    
    # Check if Thursday
    dt = pd.Timestamp(target_date)
    is_thursday = (dt.weekday() == 3)
    
    print("="*60)
    print(f"           LIVE SIGNAL CHECK FOR {target_date} (Weekday: {dt.day_name()})")
    print("="*60)
    
    if is_thursday:
        print("[WARNING] TODAY IS THURSDAY (NIFTY EXPIRY) - STRATEGY BYPASS COMPLETED (Thursday skipped to avoid 0DTE theta decay).")
        print("="*60)
        return
        
    pivots = calc_pivots(prev_date)
    if pivots is None:
        print(f"Error: Could not calculate pivots for previous date {prev_date}.")
        return
        
    P = pivots['P']
    R1 = pivots['R1']
    S1 = pivots['S1']
    
    prev_df = load_spot_data(prev_date, "NIFTY")
    prev_tr = prev_df[(prev_df['time'] >= '09:15:00') & (prev_df['time'] <= '15:30:00')]
    prev_close = round(prev_tr['price'].iloc[-1], 2)
    
    spot_ticks = load_spot_data(target_date, "NIFTY")
    if spot_ticks is None or spot_ticks.empty:
        print(f"No spot tick data found for {target_date}.")
        return
        
    ohlc = create_spot_ohlc(spot_ticks, "1min")
    ohlc = ohlc[(ohlc['date_time'].dt.time >= pd.Timestamp('09:15:00').time()) &
                (ohlc['date_time'].dt.time <= pd.Timestamp('15:30:00').time())].reset_index(drop=True)
                
    if ohlc.empty:
        print(f"No OHLC candles formed yet for {target_date}.")
        return
        
    open_p = round(ohlc.iloc[0]['open'], 2)
    gap = round(open_p - prev_close, 2)
    
    print(f"Previous Day Close ({prev_date}) : {prev_close} pts")
    print(f"Today Open ({target_date})     : {open_p} pts")
    print(f"Calculated Open Gap            : {gap} pts ({'GAP UP' if gap > 0 else 'GAP DOWN' if gap < 0 else 'FLAT'})")
    print("-"*60)
    print(f"Pivot (P)                      : {P} pts")
    print(f"Target CE (R1)                 : {R1} pts (Stop Loss: {round(P - SL_PTS, 2)} pts)")
    print(f"Target PE (S1)                 : {S1} pts (Stop Loss: {round(P + SL_PTS, 2)} pts)")
    print("-"*60)
    
    # Direction
    direction = None
    opt_type = None
    target_s = None
    sl_s = None
    
    if gap > GAP_THRESH and open_p >= P:
        direction = 'LONG'
        opt_type = 'CE'
        target_s = R1
        sl_s = round(P - SL_PTS, 2)
        print(f"Strategy: Strategy A - Gap Up -> ATM CE Buy (Gap > {GAP_THRESH} pts & Open >= Pivot)")
    elif gap < -GAP_THRESH and open_p < P:
        direction = 'SHORT'
        opt_type = 'PE'
        target_s = S1
        sl_s = round(P + SL_PTS, 2)
        print(f"Strategy: Strategy B - Gap Down -> ATM PE Buy (Gap < -{GAP_THRESH} pts & Open < Pivot)")
    else:
        print("Strategy: NO TRADE TODAY — Flat open or gap doesn't match pivot condition.")
        print("="*60)
        return
        
    # Scan for signal
    signal_bar = None
    for _, row in ohlc.iterrows():
        if row['date_time'].time() >= ENTRY_CUTOFF: break
        if row['low'] <= P + P_TOL and row['high'] >= P - P_TOL:
            signal_bar = row
            break
            
    if signal_bar is None:
        print(f"Status: P level ({P} pts) not touched before {ENTRY_CUTOFF.strftime('%H:%M')} yet.")
        print("="*60)
        return
        
    signal_time = signal_bar['date_time'].strftime('%H:%M:%S')
    print(f"Signal Bar Found at            : {signal_time}")
    print(f"  Candle High                  : {signal_bar['high']} pts")
    print(f"  Candle Low                   : {signal_bar['low']} pts")
    print(f"  P Touch Status               : Touch Validated (Low <= {round(P + P_TOL, 2)} AND High >= {round(P - P_TOL, 2)})")
    
    # Calculate Entry time
    nb = signal_bar['date_time'] + pd.Timedelta(minutes=1)
    entry_time = (nb + pd.Timedelta(seconds=2)).strftime('%H:%M:%S')
    
    if pd.Timestamp(f"2000-01-01 {entry_time}").time() >= ENTRY_CUTOFF:
        print(f"Status: Skip Trade — Entry time {entry_time} is after the {ENTRY_CUTOFF.strftime('%H:%M')} cutoff.")
        print("="*60)
        return
        
    spot_entry = price_at(spot_ticks, entry_time)
    print(f"Safe Entry Time (Rule 8)       : {entry_time} (Spot Entry: {spot_entry} pts)")
    
    # Expiry Strike
    atm_strike = calculate_strike(spot_entry or P, opt_type, "NIFTY", "atm")
    instrument = build_instrument_name("NIFTY", atm_strike, target_date, True, opt_type)
    print(f"ATM Option Selected            : {instrument}")
    print("-"*60)
    
    # Scan for trade outcome
    et = pd.Timestamp(f"2000-01-01 {entry_time}").time()
    rows = spot_ticks[spot_ticks['date_time'].dt.time >= et]
    
    trade_active = False
    exit_row = None
    result = None
    
    for _, row in rows.iterrows():
        t = row['date_time'].time()
        p = row['price']
        
        if t >= EOD_EXIT:
            result = "EOD"
            exit_row = row
            break
        if direction == 'LONG' and p >= target_s:
            result = "TARGET"
            exit_row = row
            break
        if direction == 'LONG' and p <= sl_s:
            result = "SL"
            exit_row = row
            break
        if direction == 'SHORT' and p <= target_s:
            result = "TARGET"
            exit_row = row
            break
        if direction == 'SHORT' and p >= sl_s:
            result = "SL"
            exit_row = row
            break
            
    if result:
        exit_time = exit_row['date_time'].strftime('%H:%M:%S')
        oe, ox, opt_pnl = get_opt_pnl(target_date, opt_type, spot_entry or P, entry_time, exit_time)
        
        print(f"Trade Outcome                  : {result}")
        print(f"Exit Time                      : {exit_time} (Spot Exit: {exit_row['price']} pts)")
        print(f"Option Entry Price             : {oe} pts")
        print(f"Option Exit Price              : {ox} pts")
        print(f"Option Points Gain/Loss        : {opt_pnl} pts")
        print(f"Trade PnL (INR per lot)        : INR {round(opt_pnl * LOT_SIZE, 2):,.2f}")
    else:
        print("Trade Status                   : ACTIVE (Market still trading, waiting for target/SL/EOD exit)")
        current_spot = spot_ticks.iloc[-1]['price']
        print(f"Current Spot Price             : {current_spot} pts")
        print(f"Distance to Target             : {round(abs(current_spot - target_s), 2)} pts")
        print(f"Distance to Stop Loss          : {round(abs(current_spot - sl_s), 2)} pts")
        
    print("="*60)

if __name__ == "__main__":
    t_date = sys.argv[1] if len(sys.argv) > 1 else None
    check_live_signal(t_date)

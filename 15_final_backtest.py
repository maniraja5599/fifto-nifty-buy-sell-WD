import os
import pandas as pd
import numpy as np
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
        # print(f"Error in get_opt_pnl for {date_str} {opt_type}: {e}")
        return None, None, None

def run_backtest():
    all_dates   = list_trading_dates()
    if len(all_dates) < 2:
        print("Not enough data to run backtest. Please run generate_mock_data.py first.")
        return
        
    recent      = all_dates[-253:]
    trade_dates = recent[1:]
    
    trades = []
    skipped_thursdays = 0
    no_trade_days = 0
    total_days_processed = 0

    print("Starting NIFTY Pivot Gap Strategy v2.0 Backtest...")
    print(f"Total days in dataset: {len(all_dates)}")
    print(f"Backtesting period: {trade_dates[0]} to {trade_dates[-1]} ({len(trade_dates)} trading days)\n")

    for date_str in trade_dates:
        total_days_processed += 1
        dt = pd.Timestamp(date_str)
        if dt.weekday() == 3:  # skip Thursday
            skipped_thursdays += 1
            continue

        idx       = all_dates.index(date_str)
        prev_date = all_dates[idx-1]
        pivots    = calc_pivots(prev_date)
        if pivots is None: 
            no_trade_days += 1
            continue

        prev_df = load_spot_data(prev_date, "NIFTY")
        if prev_df is None: 
            no_trade_days += 1
            continue
            
        prev_tr    = prev_df[(prev_df['time'] >= '09:15:00') & (prev_df['time'] <= '15:30:00')]
        if prev_tr.empty:
            no_trade_days += 1
            continue
        prev_close = round(prev_tr['price'].iloc[-1], 2)

        spot_ticks = load_spot_data(date_str, "NIFTY")
        if spot_ticks is None or spot_ticks.empty: 
            no_trade_days += 1
            continue

        ohlc = create_spot_ohlc(spot_ticks, "1min")
        ohlc = ohlc[(ohlc['date_time'].dt.time >= pd.Timestamp('09:15:00').time()) &
                    (ohlc['date_time'].dt.time <= pd.Timestamp('15:30:00').time())].reset_index(drop=True)
        if ohlc.empty or len(ohlc) < 5: 
            no_trade_days += 1
            continue

        open_p = round(ohlc.iloc[0]['open'], 2)
        gap    = round(open_p - prev_close, 2)
        P=pivots['P']; R1=pivots['R1']; S1=pivots['S1']

        # Direction
        if gap > GAP_THRESH and open_p >= P:
            direction='LONG';  opt_type='CE'; target_s=R1; sl_s=round(P-SL_PTS, 2)
        elif gap < -GAP_THRESH and open_p < P:
            direction='SHORT'; opt_type='PE'; target_s=S1; sl_s=round(P+SL_PTS, 2)
        else:
            no_trade_days += 1
            continue

        # Signal
        signal_bar = None
        for _, row in ohlc.iterrows():
            if row['date_time'].time() >= ENTRY_CUTOFF: break
            if row['low'] <= P+P_TOL and row['high'] >= P-P_TOL:
                signal_bar=row; break
        if signal_bar is None: 
            no_trade_days += 1
            continue

        # Entry (Rule 8)
        nb         = signal_bar['date_time'] + pd.Timedelta(minutes=1)
        entry_time = (nb + pd.Timedelta(seconds=2)).strftime('%H:%M:%S')
        if pd.Timestamp(f"2000-01-01 {entry_time}").time() >= ENTRY_CUTOFF: 
            no_trade_days += 1
            continue

        # Tick-level exit
        et   = pd.Timestamp(f"2000-01-01 {entry_time}").time()
        rows = spot_ticks[spot_ticks['date_time'].dt.time >= et]
        if rows.empty: 
            no_trade_days += 1
            continue
            
        result = exit_time = None
        for _, row in rows.iterrows():
            t = row['date_time'].time(); p = row['price']
            if t >= EOD_EXIT:
                result="EOD"; exit_time=row['date_time'].strftime('%H:%M:%S'); break
            if direction=='LONG' and p >= target_s:
                result="TARGET"; exit_time=row['date_time'].strftime('%H:%M:%S'); break
            if direction=='LONG' and p <= sl_s:
                result="SL";     exit_time=row['date_time'].strftime('%H:%M:%S'); break
            if direction=='SHORT' and p <= target_s:
                result="TARGET"; exit_time=row['date_time'].strftime('%H:%M:%S'); break
            if direction=='SHORT' and p >= sl_s:
                result="SL";     exit_time=row['date_time'].strftime('%H:%M:%S'); break
                
        if not result: 
            no_trade_days += 1
            continue

        # Option PnL
        spot_entry = price_at(spot_ticks, entry_time)
        oe, ox, opt_pnl = get_opt_pnl(date_str, opt_type, spot_entry or P, entry_time, exit_time)

        if opt_pnl is None:
            # Fallback if option tick data not available for some reason
            opt_pnl = 0.0
            oe = ox = 0.0

        pnl_rs = round(opt_pnl * LOT_SIZE, 2)
        trades.append({
            "date": date_str, 
            "opt_type": opt_type,
            "direction": direction,
            "gap": gap,
            "pivot": P,
            "spot_entry": spot_entry,
            "opt_entry": oe, 
            "opt_exit": ox, 
            "opt_pnl": round(opt_pnl, 2),
            "pnl_rs": pnl_rs,
            "result": result,
            "entry_time": entry_time,
            "exit_time": exit_time
        })

    # Calculations
    df_trades = pd.DataFrame(trades)
    if df_trades.empty:
        print("No trades were executed during this backtest.")
        return

    n_trades = len(df_trades)
    wins = df_trades[df_trades['opt_pnl'] > 0]
    losses = df_trades[df_trades['opt_pnl'] <= 0]
    win_rate = round((len(wins) / n_trades) * 100, 2) if n_trades > 0 else 0.0
    
    total_opt_pts = df_trades['opt_pnl'].sum()
    total_rs = df_trades['pnl_rs'].sum()
    
    avg_win = wins['opt_pnl'].mean() if len(wins) > 0 else 0
    avg_loss = abs(losses['opt_pnl'].mean()) if len(losses) > 0 else 1.0
    rr_ratio = round(avg_win / avg_loss, 2) if avg_loss > 0 else 0.0
    
    # Calculate Max Drawdown
    df_trades['cum_pnl'] = df_trades['pnl_rs'].cumsum()
    df_trades['running_max'] = df_trades['cum_pnl'].cummax()
    df_trades['drawdown'] = df_trades['running_max'] - df_trades['cum_pnl']
    max_dd = round(df_trades['drawdown'].max(), 2)

    # Initial Capital estimation (approximate maximum margin needed, or premium cost + buffer)
    # Using typical premium cost per lot: 120 points * 65 lot size = ₹7,800 approx
    capital_per_lot = 7700.0
    roi = round((total_rs / capital_per_lot) * 100, 2)

    print("="*60)
    print("                BACKTEST PERFORMANCE REPORT                   ")
    print("="*60)
    print(f"Period                   : {trade_dates[0]} - {trade_dates[-1]}")
    print(f"Total Trading Days       : {len(trade_dates)}")
    print(f"Thursdays Skipped        : {skipped_thursdays}")
    print(f"Trade Days / Total Trades: {n_trades}")
    print(f"No Trade Days            : {no_trade_days + skipped_thursdays}")
    print("-"*60)
    print(f"Win Rate                 : {win_rate}%")
    print(f"Total Points Won (Option): {round(total_opt_pts, 2)} pts")
    print(f"Total PnL (INR per lot)  : INR {total_rs:,.2f}")
    print(f"Estimated Capital / lot  : INR {capital_per_lot:,.2f}")
    print(f"Return on Investment (ROI): {roi}%")
    print(f"Max Drawdown (INR per lot): INR {max_dd:,.2f}")
    print(f"Average Win (Option pts) : {round(avg_win, 2)} pts")
    print(f"Average Loss (Option pts): {round(avg_loss, 2)} pts")
    print(f"Reward-to-Risk (R:R)     : {rr_ratio}")
    print("="*60)
    print("\nRecent 10 Trades:")
    print(df_trades[['date', 'direction', 'gap', 'pivot', 'opt_pnl', 'pnl_rs', 'result', 'entry_time', 'exit_time']].tail(10).to_string(index=False))
    
    # Save trades to CSV file
    csv_path = r"C:\Users\manir\.gemini\antigravity\scratch\fifto-nifty-pivot-gap\backtest_trades.csv"
    df_trades.to_csv(csv_path, index=False)
    print(f"\nAll trades saved to: {csv_path}")

if __name__ == "__main__":
    run_backtest()

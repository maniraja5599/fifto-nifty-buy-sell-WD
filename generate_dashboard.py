import os
import sys
import json
import numpy as np
import pandas as pd
from datetime import datetime, date

# Reconfigure stdout to use UTF-8
sys.stdout.reconfigure(encoding='utf-8')

# Paths
backtest_dir = r"C:\Users\manir\Desktop\Backtest"
output_html = r"e:\Projects\FiFTO Backtest Engine MANI\portfolio_dashboard.html"

# ----------------------------------------------------
# 1. Market Regimes Definition
# ----------------------------------------------------
def get_market_regime(dt):
    if isinstance(dt, pd.Timestamp):
        d = dt.date()
    elif isinstance(dt, datetime):
        d = dt.date()
    else:
        d = dt
    
    # High VIX ranges
    high_vix_ranges = [
        (date(2016, 11, 8), date(2016, 12, 31)),
        (date(2018, 2, 1), date(2018, 3, 31)),
        (date(2020, 2, 15), date(2020, 9, 30)),
        (date(2022, 2, 1), date(2022, 6, 30)),
        (date(2024, 4, 15), date(2024, 6, 15))
    ]
    is_high_vix = False
    for start, end in high_vix_ranges:
        if start <= d <= end:
            is_high_vix = True
            break
            
    vix_regime = "High VIX" if is_high_vix else "Low VIX"
    
    # Trend ranges
    trending_bull = [
        (date(2017, 1, 1), date(2017, 12, 31)),
        (date(2020, 6, 1), date(2021, 10, 31)),
        (date(2023, 4, 1), date(2024, 3, 31)),
        (date(2024, 6, 1), date(2026, 5, 31))
    ]
    trending_bear = [
        (date(2020, 2, 1), date(2020, 5, 31))
    ]
    
    is_trending = False
    for start, end in trending_bull:
        if start <= d <= end:
            is_trending = True
            break
    for start, end in trending_bear:
        if start <= d <= end:
            is_trending = True
            break
            
    trend_regime = "Trending" if is_trending else "Sideways"
    
    return trend_regime, vix_regime

# ----------------------------------------------------
# 2. Main Analysis Loop
# ----------------------------------------------------
csv_files = [f for f in os.listdir(backtest_dir) if f.endswith('.csv')]
strategies_data = {}
all_monthly_pnl_data = {}
all_dates = set()
overall_min_date = None
overall_max_date = None

for file in sorted(csv_files):
    filepath = os.path.join(backtest_dir, file)
    strategy_name = file.replace('.csv', '').replace('✔✔', '')
    
    try:
        df = pd.read_csv(filepath)
        if df.empty:
            continue
            
        df.columns = [c.strip() for c in df.columns]
        
        pnl_col = [c for c in df.columns if 'Net P&L' in c or 'Net P' in c or 'P&L' in c][0]
        cum_pnl_col = [c for c in df.columns if 'Cumulative P&L' in c or 'Cumulative P' in c][0]
        val_col = [c for c in df.columns if 'Size (value)' in c or 'value' in c][0]
        
        df['Datetime'] = pd.to_datetime(df['Date and time'], format='mixed')
        df = df.sort_values('Datetime')
        
        # Track overall min and max dates across all strategies
        if not df.empty:
            file_min = df['Datetime'].min()
            file_max = df['Datetime'].max()
            if overall_min_date is None or file_min < overall_min_date:
                overall_min_date = file_min
            if overall_max_date is None or file_max > overall_max_date:
                overall_max_date = file_max
        
        df_exits = df[df['Type'].str.contains('Exit', case=False, na=False)].copy()
        if df_exits.empty:
            df_exits = df.copy()
            
        df_exits[pnl_col] = pd.to_numeric(df_exits[pnl_col].astype(str).str.replace(',', '').str.strip(), errors='coerce')
        df_exits[cum_pnl_col] = pd.to_numeric(df_exits[cum_pnl_col].astype(str).str.replace(',', '').str.strip(), errors='coerce')
        df_exits[val_col] = pd.to_numeric(df_exits[val_col].astype(str).str.replace(',', '').str.strip(), errors='coerce')
        
        df_exits = df_exits.dropna(subset=[pnl_col])
        if df_exits.empty:
            continue
            
        trades_count = len(df_exits)
        net_profit = df_exits[pnl_col].sum()
        
        wins = df_exits[df_exits[pnl_col] > 0]
        losses = df_exits[df_exits[pnl_col] < 0]
        
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = (win_count / trades_count) * 100 if trades_count > 0 else 0
        
        avg_win = wins[pnl_col].mean() if win_count > 0 else 0
        avg_loss = abs(losses[pnl_col].mean()) if loss_count > 0 else 0
        risk_reward = avg_win / avg_loss if avg_loss > 0 else 0
        
        total_wins_sum = wins[pnl_col].sum()
        total_losses_sum = abs(losses[pnl_col].sum())
        profit_factor = total_wins_sum / total_losses_sum if total_losses_sum > 0 else 999.0
        
        # Streak
        pnl_series = df_exits[pnl_col].values
        max_streak = 0
        current_streak = 0
        for val in pnl_series:
            if val <= 0:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0
                
        max_capital_used = df_exits[val_col].max()
        if pd.isna(max_capital_used) or max_capital_used == 0:
            max_capital_used = 500000.0
            
        # Drawdown calculation
        equity = max_capital_used + df_exits[pnl_col].cumsum().values
        peak = np.maximum.accumulate(equity)
        drawdown_inr = peak - equity
        max_dd_inr = drawdown_inr.max()
        max_dd_pct = (drawdown_inr / peak).max() * 100
        
        # Annualized Return
        duration_days = (df_exits['Datetime'].max() - df_exits['Datetime'].min()).days
        duration_years = max(duration_days / 365.25, 0.1)
        raw_return = net_profit / max_capital_used
        annualized_return = (raw_return / duration_years) * 100
        
        # Consistency
        df_exits['YearMonth'] = df_exits['Datetime'].dt.to_period('M')
        monthly_pnl = df_exits.groupby('YearMonth')[pnl_col].sum()
        profitable_months = (monthly_pnl > 0).sum()
        total_months = len(monthly_pnl)
        consistency_score = (profitable_months / total_months) * 100 if total_months > 0 else 0
        
        # Market Regime Performance
        df_exits['Regime'] = df_exits['Datetime'].apply(get_market_regime)
        df_exits['TrendRegime'] = df_exits['Regime'].apply(lambda x: x[0])
        df_exits['VixRegime'] = df_exits['Regime'].apply(lambda x: x[1])
        
        regime_performance = {}
        for r_type in ['Trending', 'Sideways', 'High VIX', 'Low VIX']:
            col_filter = 'TrendRegime' if 'Trend' in r_type or r_type in ['Trending', 'Sideways'] else 'VixRegime'
            r_df = df_exits[df_exits[col_filter] == r_type]
            r_trades = len(r_df)
            if r_trades > 0:
                r_win_rate = (len(r_df[r_df[pnl_col] > 0]) / r_trades) * 100
                r_pf = r_df[r_df[pnl_col] > 0][pnl_col].sum() / abs(r_df[r_df[pnl_col] < 0][pnl_col].sum()) if len(r_df[r_df[pnl_col] < 0]) > 0 else 999.0
            else:
                r_win_rate, r_pf = 0.0, 0.0
            regime_performance[r_type] = {'WinRate': r_win_rate, 'PF': r_pf, 'Count': r_trades}
            
        # Scoring Model
        score_win_rate = np.clip((win_rate - 30) / (70 - 30) * 20, 0, 20)
        score_pf = np.clip((profit_factor - 1.0) / (2.5 - 1.0) * 25, 0, 25)
        score_ret = np.clip(annualized_return / 50.0 * 20, 0, 20)
        score_dd = np.clip((30.0 - max_dd_pct) / (30.0 - 5.0) * 20, 0, 20)
        score_const = consistency_score / 100 * 15
        final_score = score_win_rate + score_pf + score_ret + score_dd + score_const
        
        # Parse individual trade ledger
        trades_ledger = []
        df_clean = df.copy()
        df_clean.columns = [c.strip() for c in df_clean.columns]
        
        # Check column existence safely
        pnl_col_ledger = [c for c in df_clean.columns if 'Net P&L' in c or 'Net P' in c or 'P&L' in c][0]
        pnl_pct_col_ledger = [c for c in df_clean.columns if 'Net P&L %' in c or 'Net P %' in c or 'P&L %' in c]
        pnl_pct_col_ledger = pnl_pct_col_ledger[0] if pnl_pct_col_ledger else None
        
        qty_col = [c for c in df_clean.columns if 'Size (qty)' in c or 'qty' in c or 'Size' in c]
        qty_col = qty_col[0] if qty_col else None
        
        price_col = [c for c in df_clean.columns if 'Price' in c or 'Price INR' in c]
        price_col = price_col[0] if price_col else None
        
        # Safely convert to numeric where needed
        for col in [price_col, qty_col, pnl_col_ledger]:
            if col and col in df_clean.columns:
                df_clean[col] = pd.to_numeric(df_clean[col].astype(str).str.replace(',', '').str.strip(), errors='coerce')
        if pnl_pct_col_ledger and pnl_pct_col_ledger in df_clean.columns:
            df_clean[pnl_pct_col_ledger] = pd.to_numeric(df_clean[pnl_pct_col_ledger].astype(str).str.replace(',', '').str.replace('%', '').str.strip(), errors='coerce')
            
        grouped = df_clean.groupby('Trade #')
        for trade_no, group in grouped:
            entry_row = group[group['Type'].str.contains('Entry|Enter', case=False, na=False)]
            exit_row = group[group['Type'].str.contains('Exit', case=False, na=False)]
            
            if not entry_row.empty and not exit_row.empty:
                e_row = entry_row.iloc[0]
                x_row = exit_row.iloc[0]
                
                e_time = str(e_row['Date and time'])
                x_time = str(x_row['Date and time'])
                
                e_price = float(e_row[price_col]) if price_col and not pd.isna(e_row[price_col]) else 0.0
                x_price = float(x_row[price_col]) if price_col and not pd.isna(x_row[price_col]) else 0.0
                qty = float(e_row[qty_col]) if qty_col and not pd.isna(e_row[qty_col]) else 0.0
                
                pnl_inr = float(x_row[pnl_col_ledger]) if not pd.isna(x_row[pnl_col_ledger]) else 0.0
                
                pnl_pct = 0.0
                if pnl_pct_col_ledger and not pd.isna(x_row[pnl_pct_col_ledger]):
                    pnl_pct = float(x_row[pnl_pct_col_ledger])
                elif e_price > 0:
                    # Calculate as fallback
                    direction = 1 if 'long' in str(e_row['Type']).lower() else -1
                    pnl_pct = direction * ((x_price - e_price) / e_price) * 100
                
                trades_ledger.append({
                    'trade_no': int(trade_no),
                    'type': 'Long' if 'long' in str(e_row['Type']).lower() else 'Short',
                    'entry_time': e_time,
                    'entry_price': e_price,
                    'exit_time': x_time,
                    'exit_price': x_price,
                    'qty': int(qty),
                    'pnl_inr': pnl_inr,
                    'pnl_pct': pnl_pct
                })
                
        # Sort trades by trade_no descending (show latest trades first)
        trades_ledger = sorted(trades_ledger, key=lambda x: x['trade_no'], reverse=True)
        
        strategies_data[strategy_name] = {
            'name': strategy_name,
            'NetProfit': float(net_profit),
            'DrawdownINR': float(max_dd_inr),
            'DrawdownPct': float(max_dd_pct),
            'ProfitFactor': float(profit_factor),
            'WinRate': float(win_rate),
            'RiskReward': float(risk_reward),
            'TradeCount': int(trades_count),
            'ConsistencyScore': float(consistency_score),
            'MaxCapitalUsed': float(max_capital_used),
            'AnnualizedReturn': float(annualized_return),
            'LosingStreak': int(max_streak),
            'Regimes': regime_performance,
            'FinalScore': float(final_score),
            'pnl_col': pnl_col,
            'trades': trades_ledger
        }
        
        # Monthly realized returns series
        for ym, val in monthly_pnl.items():
            ym_str = str(ym)
            all_dates.add(ym_str)
            if strategy_name not in all_monthly_pnl_data:
                all_monthly_pnl_data[strategy_name] = {}
            all_monthly_pnl_data[strategy_name][ym_str] = float(val)
            
    except Exception as e:
        print(f"Error processing {strategy_name}: {e}")

# Align all monthly series to a complete common dates index
sorted_dates = sorted(list(all_dates))
aligned_monthly_series = {}

for name in strategies_data.keys():
    aligned_monthly_series[name] = []
    for ym in sorted_dates:
        pnl_val = all_monthly_pnl_data.get(name, {}).get(ym, 0.0)
        aligned_monthly_series[name].append(pnl_val)

# Compute Monthly Correlation Matrix (Pearson)
# Build a pandas DataFrame to compute it easily
df_monthly = pd.DataFrame(index=sorted_dates)
for name, series in aligned_monthly_series.items():
    df_monthly[name] = series
corr_df = df_monthly.corr().fillna(0.0)

# Build correlation scores (average with others)
correlation_scores = {}
for name in strategies_data.keys():
    others = [c for c in corr_df.index if c != name]
    correlation_scores[name] = float(corr_df.loc[name, others].mean()) if others else 0.0
    strategies_data[name]['CorrelationScore'] = correlation_scores[name]

# Filter kept vs removed (re-apply threshold of 20 trades)
kept_strategies = []
removed_strategies = []

for name, s in strategies_data.items():
    reasons = []
    if s['ProfitFactor'] < 1.3:
        reasons.append(f"Profit Factor {s['ProfitFactor']:.2f} < 1.3")
    if s['DrawdownPct'] > 25.0:
        reasons.append(f"High Drawdown {s['DrawdownPct']:.1f}% > 25%")
    if s['TradeCount'] < 20:
        reasons.append(f"Low Trade Count {s['TradeCount']} < 20")
    if s['ConsistencyScore'] < 50.0:
        reasons.append(f"Inconsistent Monthly Returns ({s['ConsistencyScore']:.1f}%)")
        
    if reasons:
        s['status'] = 'Rejected'
        s['rejection_reason'] = ", ".join(reasons)
        removed_strategies.append(s)
    else:
        s['status'] = 'Kept'
        s['rejection_reason'] = ''
        kept_strategies.append(s)

# Prepare lot margin configuration
lot_margins = {}
for name in strategies_data.keys():
    margin = 120000.0
    if 'GOLD' in name:
        margin = 250000.0
    elif 'SILVER' in name:
        margin = 200000.0
    elif 'NATURALGAS' in name:
        margin = 150000.0
    elif 'NIFTY' in name or 'MIDCAP' in name:
        margin = 110000.0
    lot_margins[name] = margin

# Format overall date range and duration
overall_min_str = overall_min_date.strftime('%d-%b-%Y') if overall_min_date else '--'
overall_max_str = overall_max_date.strftime('%d-%b-%Y') if overall_max_date else '--'

duration_days_total = (overall_max_date - overall_min_date).days if overall_min_date and overall_max_date else 0
duration_years_total = duration_days_total / 365.25
duration_months_total = round(duration_days_total / 30.4375)

overall_range_str = f"{overall_min_str} to {overall_max_str}"
overall_duration_str = f"Duration: {duration_years_total:.2f} Years ({duration_months_total} Months)"

# Package all data for embedding in HTML
dashboard_dataset = {
    'dates': sorted_dates,
    'strategies': list(strategies_data.values()),
    'aligned_monthly_pnl': aligned_monthly_series,
    'lot_margins': lot_margins,
    'correlation_matrix': corr_df.to_dict(orient='index'),
    'overall_date_range': overall_range_str,
    'overall_duration': overall_duration_str
}

# ----------------------------------------------------
# 3. Render Web Application HTML
# ----------------------------------------------------
html_code = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FiFTO Quant Desk — Portfolio construction Terminal</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@300;400;500;700&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --bg: #090b0f;
            --bg-card: rgba(16, 20, 30, 0.7);
            --bg-card-hover: rgba(22, 28, 42, 0.85);
            --border: rgba(255, 255, 255, 0.08);
            --border-glow: rgba(0, 255, 204, 0.25);
            --cyan: #00ffcc;
            --emerald: #00e676;
            --rose: #ff2d55;
            --amber: #ff9f0a;
            --text: #eef2f7;
            --muted: #8a96a8;
            --mono: 'JetBrains Mono', monospace;
            --sans: 'Outfit', sans-serif;
            --card-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            background-color: var(--bg);
            background-image: 
                radial-gradient(at 10% 10%, rgba(0, 255, 204, 0.03) 0px, transparent 50%),
                radial-gradient(at 90% 80%, rgba(0, 230, 118, 0.03) 0px, transparent 50%);
            color: var(--text);
            font-family: var(--sans);
            min-height: 100vh;
            overflow-x: hidden;
            padding-bottom: 50px;
        }

        /* HEADER */
        header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 15px 30px;
            border-bottom: 1px solid var(--border);
            backdrop-filter: blur(10px);
            background: rgba(9, 11, 15, 0.8);
            position: sticky;
            top: 0;
            z-index: 1000;
        }

        .header-logo {
            font-weight: 800;
            font-size: 20px;
            letter-spacing: -0.03em;
            display: flex;
            align-items: center;
            gap: 10px;
            background: linear-gradient(135deg, var(--cyan), var(--emerald));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .logo-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: var(--cyan);
            box-shadow: 0 0 12px var(--cyan);
            animation: glowPulse 2s infinite alternate;
        }

        @keyframes glowPulse {
            0% { transform: scale(0.9); box-shadow: 0 0 6px var(--cyan); }
            100% { transform: scale(1.1); box-shadow: 0 0 15px var(--cyan); }
        }

        .header-meta {
            display: flex;
            align-items: center;
            gap: 25px;
            font-size: 13px;
        }

        .meta-item {
            color: var(--muted);
            font-family: var(--mono);
        }

        .meta-item strong {
            color: var(--text);
        }

        .status-pill {
            background: rgba(0, 255, 204, 0.1);
            color: var(--cyan);
            border: 1px solid rgba(0, 255, 204, 0.2);
            padding: 4px 12px;
            border-radius: 99px;
            font-weight: 600;
            font-size: 11px;
            letter-spacing: 0.05em;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .status-dot {
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: var(--cyan);
            box-shadow: 0 0 8px var(--cyan);
        }

        /* GRID SYSTEM */
        .container {
            max-width: 1440px;
            margin: 0 auto;
            padding: 20px 30px;
            display: flex;
            flex-direction: column;
            gap: 20px;
        }

        /* HERO STATS OVERVIEW */
        .stats-overview {
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 20px;
        }

        .stat-card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            box-shadow: var(--card-shadow);
            backdrop-filter: blur(10px);
            transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            position: relative;
            overflow: hidden;
        }

        .stat-card::after {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 4px;
            height: 100%;
            background: var(--border-color, var(--cyan));
        }

        .stat-card:hover {
            transform: translateY(-4px);
            border-color: var(--border-glow);
            background: var(--bg-card-hover);
        }

        .stat-label {
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--muted);
            font-weight: 600;
            margin-bottom: 8px;
        }

        .stat-value {
            font-size: 32px;
            font-weight: 800;
            letter-spacing: -0.02em;
            font-family: var(--sans);
            display: flex;
            align-items: baseline;
            gap: 5px;
        }

        .stat-desc {
            font-size: 12px;
            color: var(--muted);
            margin-top: 6px;
        }

        /* SIMULATOR & CONTROL GRID */
        .dashboard-body {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 20px;
        }

        /* CARDS */
        .card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 24px;
            box-shadow: var(--card-shadow);
            backdrop-filter: blur(10px);
            display: flex;
            flex-direction: column;
            gap: 20px;
        }

        .card-header-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .card-title {
            font-size: 16px;
            font-weight: 700;
            letter-spacing: -0.01em;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .card-subtitle {
            font-size: 12px;
            color: var(--muted);
            margin-top: -15px;
        }

        /* INPUTS & SLIDERS */
        .control-group {
            display: flex;
            flex-direction: column;
            gap: 10px;
            background: rgba(0, 0, 0, 0.2);
            padding: 16px;
            border-radius: 8px;
            border: 1px solid var(--border);
        }

        .control-label {
            font-size: 13px;
            font-weight: 600;
            color: var(--muted);
            display: flex;
            justify-content: space-between;
        }

        .control-value {
            font-family: var(--mono);
            color: var(--cyan);
            font-weight: 700;
        }

        input[type="range"] {
            -webkit-appearance: none;
            width: 100%;
            height: 6px;
            background: rgba(255, 255, 255, 0.1);
            border-radius: 99px;
            outline: none;
        }

        input[type="range"]::-webkit-slider-thumb {
            -webkit-appearance: none;
            width: 18px;
            height: 18px;
            border-radius: 50%;
            background: var(--cyan);
            cursor: pointer;
            box-shadow: 0 0 10px var(--cyan);
            transition: all 0.1s;
        }

        input[type="range"]::-webkit-slider-thumb:hover {
            transform: scale(1.2);
        }

        /* STRATEGY GRID */
        .strategy-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 12px;
            max-height: 480px;
            overflow-y: auto;
            padding-right: 5px;
        }

        .strategy-item-card {
            border: 1px solid var(--border);
            background: rgba(0,0,0,0.15);
            border-radius: 8px;
            padding: 12px 14px;
            display: flex;
            flex-direction: column;
            gap: 8px;
            cursor: pointer;
            transition: all 0.2s ease;
            position: relative;
        }

        .strategy-item-card.active {
            border-color: var(--cyan);
            background: rgba(0, 255, 204, 0.03);
            box-shadow: 0 0 15px rgba(0, 255, 204, 0.05);
        }

        .strategy-item-card.rejected {
            opacity: 0.6;
        }

        .strategy-item-card.rejected:hover {
            opacity: 0.85;
        }

        .strategy-card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .strategy-card-name {
            font-weight: 700;
            font-size: 14px;
        }

        .strategy-card-score {
            font-family: var(--mono);
            font-size: 11px;
            padding: 2px 6px;
            border-radius: 4px;
            background: rgba(255, 255, 255, 0.05);
            color: var(--muted);
        }

        .strategy-item-card.active .strategy-card-score {
            background: rgba(0, 255, 204, 0.15);
            color: var(--cyan);
            font-weight: 700;
        }

        .strategy-card-metrics {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 4px 10px;
            font-size: 11px;
            color: var(--muted);
        }

        .strategy-card-metrics span strong {
            color: var(--text);
        }

        .strategy-toggle-indicator {
            position: absolute;
            top: 10px;
            right: 10px;
            width: 14px;
            height: 14px;
            border-radius: 50%;
            border: 1px solid var(--border);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 8px;
            color: transparent;
        }

        .strategy-item-card.active .strategy-toggle-indicator {
            border-color: var(--cyan);
            background: var(--cyan);
            color: var(--bg);
        }

        /* CHART BOX */
        .chart-box {
            position: relative;
            height: 300px;
            width: 100%;
        }

        /* CORRELATION MATRIX GRID */
        .corr-grid-container {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        .corr-matrix-wrapper {
            overflow-x: auto;
            width: 100%;
        }

        .corr-matrix {
            border-collapse: collapse;
            font-size: 10px;
            font-family: var(--mono);
            width: 100%;
        }

        .corr-matrix th {
            font-weight: 600;
            color: var(--muted);
            padding: 6px;
            text-align: center;
            border: 1px solid var(--border);
        }

        .corr-matrix td {
            text-align: center;
            padding: 6px;
            border: 1px solid var(--border);
            font-weight: 700;
        }

        /* INTERACTIVE SCORE TABLE */
        .table-card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 24px;
            box-shadow: var(--card-shadow);
        }

        .table-controls {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
            gap: 15px;
        }

        .search-input {
            background: rgba(0, 0, 0, 0.3);
            border: 1px solid var(--border);
            padding: 8px 16px;
            border-radius: 6px;
            color: var(--text);
            font-family: var(--sans);
            outline: none;
            width: 250px;
            font-size: 13px;
        }

        .search-input:focus {
            border-color: var(--cyan);
        }

        .table-wrapper {
            overflow-x: auto;
            width: 100%;
            border-radius: 8px;
            border: 1px solid var(--border);
        }

        .score-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
            text-align: left;
        }

        .score-table th {
            background: rgba(0,0,0,0.3);
            color: var(--muted);
            font-weight: 600;
            padding: 12px 14px;
            border-bottom: 1px solid var(--border);
            cursor: pointer;
            user-select: none;
        }

        .score-table th:hover {
            color: var(--text);
            background: rgba(255, 255, 255, 0.03);
        }

        .score-table td {
            padding: 12px 14px;
            border-bottom: 1px solid var(--border);
            font-family: var(--mono);
        }

        .score-table tr:hover {
            background: rgba(255, 255, 255, 0.02);
        }

        .score-table tr.active-ledger-row {
            background: rgba(0, 255, 204, 0.08) !important;
            box-shadow: inset 3px 0 0 0 var(--cyan);
        }

        .score-table tr.rejected-row {
            opacity: 0.5;
        }

        .status-badge {
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: 600;
            letter-spacing: 0.05em;
        }

        .status-badge.kept {
            background: rgba(0, 230, 118, 0.1);
            color: var(--emerald);
            border: 1px solid rgba(0, 230, 118, 0.2);
        }

        .status-badge.rejected {
            background: rgba(255, 45, 85, 0.1);
            color: var(--rose);
            border: 1px solid rgba(255, 45, 85, 0.2);
        }

        /* LOTS CALCULATOR TABLE */
        .lots-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
        }

        .lots-table th {
            color: var(--muted);
            font-weight: 600;
            padding: 8px 10px;
            border-bottom: 1px solid var(--border);
            text-align: left;
        }

        .lots-table td {
            padding: 8px 10px;
            border-bottom: 1px solid var(--border);
            font-family: var(--mono);
        }

        .lots-table tr:last-child td {
            border-bottom: none;
        }

        /* RECOMMENDATIONS ACCORDION */
        .accordion {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        .accordion-item {
            border: 1px solid var(--border);
            border-radius: 8px;
            overflow: hidden;
            background: rgba(0, 0, 0, 0.2);
        }

        .accordion-header {
            padding: 14px 16px;
            font-weight: 600;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
            user-select: none;
            background: rgba(255, 255, 255, 0.02);
            font-size: 13px;
        }

        .accordion-header:hover {
            background: rgba(255, 255, 255, 0.04);
        }

        .accordion-content {
            padding: 14px 16px;
            font-size: 12px;
            line-height: 1.6;
            color: var(--muted);
            border-top: 1px solid var(--border);
            display: none;
        }

        .accordion-item.active .accordion-content {
            display: block;
        }

        .accordion-item.active .accordion-header {
            background: rgba(0, 255, 204, 0.03);
            color: var(--cyan);
        }

        /* ALERTS */
        .alert-box {
            border-radius: 8px;
            padding: 12px 16px;
            font-size: 12px;
            line-height: 1.6;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .alert-box.tip {
            background: rgba(0, 230, 118, 0.05);
            border: 1px solid rgba(0, 230, 118, 0.15);
            color: var(--emerald);
        }

        .alert-box.important {
            background: rgba(0, 255, 204, 0.05);
            border: 1px solid rgba(0, 255, 204, 0.15);
            color: var(--cyan);
        }

        /* SCROLLBAR */
        ::-webkit-scrollbar {
            width: 5px;
            height: 5px;
        }

        ::-webkit-scrollbar-track {
            background: transparent;
        }

        ::-webkit-scrollbar-thumb {
            background: var(--border);
            border-radius: 2px;
        }

        ::-webkit-scrollbar-thumb:hover {
            background: rgba(255, 255, 255, 0.15);
        }
    </style>
</head>
<body>

    <!-- HEADER -->
    <header>
        <div class="header-logo">
            <div class="logo-dot"></div>
            FiFTO Quant Desk
            <span style="color:var(--muted);font-weight:400;font-size:14px">/ Strategy Portfolio Construction</span>
        </div>
        <div class="header-meta">
            <span class="meta-item">Status: <span class="status-pill"><span class="status-dot"></span>PRO TERMINAL</span></span>
            <span class="meta-item">Date: <strong id="clock-date">--:--:--</strong></span>
        </div>
    </header>

    <!-- CONTENT CONTAINER -->
    <div class="container">

        <!-- 1. HERO METRIC CARDS -->
        <section class="stats-overview">
            <div class="stat-card" style="--border-color: var(--cyan);">
                <div class="stat-label">Starting Capital</div>
                <div class="stat-value" id="capital-val">₹1.5M</div>
                <div class="stat-desc">Customizable starting pool</div>
            </div>
            <div class="stat-card" id="port-return-card" style="--border-color: var(--emerald);">
                <div class="stat-label">Portfolio Net Profit</div>
                <div class="stat-value" id="port-return-val" style="color: var(--emerald);">₹0</div>
                <div class="stat-desc" id="port-return-desc">0.00% Total Return (0.00% Ann.)</div>
            </div>
            <div class="stat-card" style="--border-color: var(--rose);">
                <div class="stat-label">Portfolio Max Drawdown</div>
                <div class="stat-value" id="port-dd-val" style="color: var(--rose);">1.40%</div>
                <div class="stat-desc" id="port-dd-inr-val">₹22,551 max historical drop</div>
            </div>
            <div class="stat-card" style="--border-color: var(--emerald);">
                <div class="stat-label">Annualized Sharpe Ratio</div>
                <div class="stat-value" id="port-sharpe-val" style="color: var(--emerald);">3.53</div>
                <div class="stat-desc" id="port-div-val">Diversification Score: 2.44</div>
            </div>
            <div class="stat-card" style="--border-color: var(--cyan);">
                <div class="stat-label">Overall Backtest Period</div>
                <div class="stat-value" id="overall-date-val" style="font-size:14px; font-weight:700; color:var(--cyan); height: 38px; display:flex; align-items:center;">-- to --</div>
                <div class="stat-desc" id="overall-duration-val">--</div>
            </div>
        </section>

        <!-- 2. MAIN SIMULATOR GRID -->
        <section class="dashboard-body">

            <!-- LEFT COLUMN: CONTROLS & STRATEGIES -->
            <div style="display:flex;flex-direction:column;gap:20px;">

                <!-- CONTROLS CARD -->
                <div class="card">
                    <div class="card-header-row">
                        <div class="card-title">Portfolio Allocator Controls</div>
                    </div>
                    <!-- Allocation Mode Switch -->
                    <div class="control-group" style="display:flex; flex-direction:row; justify-content:space-between; align-items:center; padding:10px 16px; margin-bottom: 5px;">
                        <span style="font-size:13px; font-weight:600; color:var(--muted)">Allocation Mode:</span>
                        <div style="display:flex; gap:15px;">
                            <label style="display:flex; align-items:center; gap:5px; font-size:12px; cursor:pointer; color:var(--cyan); font-weight:600;" id="auto-label">
                                <input type="radio" name="alloc-mode" value="auto" checked onchange="toggleAllocMode('auto')"> Auto (Risk-Adjusted ERC)
                            </label>
                            <label style="display:flex; align-items:center; gap:5px; font-size:12px; cursor:pointer; color:var(--muted); font-weight:600;" id="manual-label">
                                <input type="radio" name="alloc-mode" value="manual" onchange="toggleAllocMode('manual')"> Manual Custom
                            </label>
                        </div>
                    </div>

                    <!-- Backtest Date Range Filter -->
                    <div class="control-group" style="padding:10px 16px; margin-bottom: 10px; border-top: 1px solid var(--border); padding-top: 12px; display:flex; flex-direction:column; gap:8px;">
                        <div style="font-size:13px; font-weight:600; color:var(--muted)">Simulation Period Filter:</div>
                        <div style="display:flex; gap:15px; align-items:center;">
                            <div style="flex:1; display:flex; flex-direction:column; gap:4px;">
                                <span style="font-size:10px; color:var(--muted)">Start Month</span>
                                <select id="filter-start-month" class="search-input" style="width:100%; padding:6px 12px; background:rgba(0,0,0,0.5); border:1px solid var(--border); color:var(--text); cursor:pointer; font-family:var(--mono);" onchange="updateDateFilter()">
                                    <!-- Populated dynamically -->
                                </select>
                            </div>
                            <div style="display:flex; align-items:center; justify-content:center; color:var(--muted); font-weight:700; margin-top:14px; font-size:11px;">to</div>
                            <div style="flex:1; display:flex; flex-direction:column; gap:4px;">
                                <span style="font-size:10px; color:var(--muted)">End Month</span>
                                <select id="filter-end-month" class="search-input" style="width:100%; padding:6px 12px; background:rgba(0,0,0,0.5); border:1px solid var(--border); color:var(--text); cursor:pointer; font-family:var(--mono);" onchange="updateDateFilter()">
                                    <!-- Populated dynamically -->
                                </select>
                            </div>
                        </div>
                    </div>

                    <div class="dashboard-body" style="grid-template-columns: 1fr 1fr; gap: 15px;">
                        <div class="control-group">
                            <div class="control-label">
                                <span>Adjust Total Capital</span>
                                <span class="control-value" id="capital-control-display">₹1,500,000</span>
                            </div>
                            <input type="range" id="capital-slider" min="100000" max="10000000" step="50000" value="1500000" oninput="updateCapital(this.value)">
                        </div>
                        <div class="control-group" style="justify-content: center; gap: 8px;">
                            <div style="display:flex;justify-content:space-between;font-size:13px;font-weight:600;color:var(--muted)">
                                <span>Selected Strategy Count</span>
                                <span style="color:var(--cyan);font-family:var(--mono);" id="selected-count">12 / 14</span>
                            </div>
                            <div style="display:flex;gap:10px;margin-top:5px;">
                                <button onclick="toggleAllStrategies(true)" style="flex:1;background:rgba(0,255,204,0.1);color:var(--cyan);border:1px solid rgba(0,255,204,0.2);padding:6px;border-radius:4px;font-size:11px;font-weight:600;cursor:pointer;">Select Kept</button>
                                <button onclick="toggleAllStrategies(false)" style="flex:1;background:rgba(255,45,85,0.1);color:var(--rose);border:1px solid rgba(255,45,85,0.2);padding:6px;border-radius:4px;font-size:11px;font-weight:600;cursor:pointer;">Select None</button>
                            </div>
                        </div>
                    </div>

                    <!-- STRATEGY SELECTOR GRID -->
                    <div style="display:flex;flex-direction:column;gap:10px;">
                        <div class="card-title" style="font-size:13px;color:var(--muted);">Toggle Strategies to Include in Simulation</div>
                        <div class="strategy-grid" id="strategy-selector-grid">
                            <!-- Injected dynamically -->
                        </div>
                    </div>
                </div>

                <!-- LOT ALLOCATION CALCULATOR -->
                <div class="card">
                    <div class="card-title">Dynamic Lot & Capital Allocation</div>
                    <div class="card-subtitle">Calculated dynamically in real-time based on allocation weights and asset-class margin margins.</div>
                    <table class="lots-table">
                        <thead>
                            <tr>
                                <th>Strategy Name</th>
                                <th>Allocation Weight</th>
                                <th>Allocated Capital</th>
                                <th>Margin/Lot</th>
                                <th>Allocated Lots</th>
                            </tr>
                        </thead>
                        <tbody id="lots-table-body">
                            <!-- Injected dynamically -->
                        </tbody>
                    </table>
                </div>

            </div>

            <!-- RIGHT COLUMN: INTERACTIVE CHARTS & MATRIX -->
            <div style="display:flex;flex-direction:column;gap:20px;">

                <!-- EQUITY CURVE CARD -->
                <div class="card">
                    <div class="card-title">Simulated Portfolio Equity Curve</div>
                    <div class="chart-box">
                        <canvas id="portfolioChart"></canvas>
                    </div>
                </div>

                <!-- CORRELATION MATRIX -->
                <div class="card">
                    <div class="card-title">Strategy Monthly Returns Correlation</div>
                    <div class="corr-grid-container">
                        <div class="corr-matrix-wrapper">
                            <table class="corr-matrix" id="correlation-matrix-table">
                                <!-- Injected dynamically -->
                            </table>
                        </div>
                        <div class="alert-box tip">
                            <strong>Diversification Insight:</strong> Low-correlation strategies (CDSL, Commodities) help to smooth out drawdowns. The negative correlation between Silver/Gold and equity indices serves as an excellent natural hedge.
                        </div>
                    </div>
                </div>

            </div>

        </section>

        <!-- 3. STRATEGY SCORE TABLE CARD -->
        <section class="table-card">
            <div class="table-controls">
                <div>
                    <div class="card-title">Comprehensive Strategy Scorecard</div>
                    <div class="card-subtitle" style="font-size:12px; color:var(--muted); margin-top:2px;">Click on any row to view its complete trade-by-trade ledger below.</div>
                </div>
                <input type="text" class="search-input" id="table-search" placeholder="Search strategy name..." oninput="filterTable(this.value)">
            </div>
            <div class="table-wrapper">
                <table class="score-table" id="strategy-score-table">
                    <thead>
                        <tr>
                            <th onclick="sortTable('name')">Name ⇅</th>
                            <th onclick="sortTable('status')">Status ⇅</th>
                            <th onclick="sortTable('NetProfit')">Net Profit (INR) ⇅</th>
                            <th onclick="sortTable('DrawdownPct')">Max Drawdown ⇅</th>
                            <th onclick="sortTable('ProfitFactor')">Profit Factor ⇅</th>
                            <th onclick="sortTable('WinRate')">Win Rate ⇅</th>
                            <th onclick="sortTable('RiskReward')">Risk:Reward ⇅</th>
                            <th onclick="sortTable('TradeCount')">Trades ⇅</th>
                            <th onclick="sortTable('ConsistencyScore')">Consistency ⇅</th>
                            <th onclick="sortTable('CorrelationScore')">Avg Correlation ⇅</th>
                            <th onclick="sortTable('FinalScore')">Final Score ⇅</th>
                        </tr>
                    </thead>
                    <tbody id="score-table-body">
                        <!-- Injected dynamically -->
                    </tbody>
                </table>
            </div>
        </section>

        <!-- 3B. INDIVIDUAL STRATEGY TRADE LEDGER -->
        <section class="table-card" style="margin-top: 20px;" id="trade-ledger-section">
            <div class="table-controls">
                <div>
                    <div class="card-title">Detailed Trade Ledger</div>
                    <div class="card-subtitle" style="font-size:12px; color:var(--muted); margin-top:2px;">
                        Showing trade logs for strategy: <strong id="ledger-strategy-name" style="color:var(--cyan); font-size:14px;">--</strong>
                    </div>
                </div>
                <div style="display:flex; gap:10px; align-items:center;">
                    <select id="ledger-type-filter" class="search-input" style="width:130px; background:rgba(0,0,0,0.5); border:1px solid var(--border); color:var(--text); padding:6px 12px; cursor:pointer;" onchange="filterLedger()">
                        <option value="all">All Types</option>
                        <option value="Long">Long Only</option>
                        <option value="Short">Short Only</option>
                    </select>
                    <select id="ledger-pnl-filter" class="search-input" style="width:130px; background:rgba(0,0,0,0.5); border:1px solid var(--border); color:var(--text); padding:6px 12px; cursor:pointer;" onchange="filterLedger()">
                        <option value="all">All Trades</option>
                        <option value="win">Profitable (Wins)</option>
                        <option value="loss">Unprofitable (Losses)</option>
                    </select>
                    <input type="text" class="search-input" id="ledger-search" placeholder="Search trade # or date..." oninput="filterLedger()" style="width:200px;">
                </div>
            </div>
            
            <div style="display:grid; grid-template-columns: repeat(4, 1fr); gap:15px; padding:15px; margin-bottom:15px; background:rgba(255,255,255,0.02); border:1px solid var(--border); border-radius:8px;">
                <div style="border-left:2px solid var(--cyan); padding-left:10px;">
                    <span style="font-size:10px; color:var(--muted); text-transform:uppercase;">Net Profit</span>
                    <div id="ledger-net-profit" style="font-size:16px; font-weight:700; font-family:var(--mono);">₹0</div>
                </div>
                <div style="border-left:2px solid var(--emerald); padding-left:10px;">
                    <span style="font-size:10px; color:var(--muted); text-transform:uppercase;">Win Rate %</span>
                    <div id="ledger-win-rate" style="font-size:16px; font-weight:700; font-family:var(--mono);">0.0%</div>
                </div>
                <div style="border-left:2px solid var(--cyan); padding-left:10px;">
                    <span style="font-size:10px; color:var(--muted); text-transform:uppercase;">Profit Factor</span>
                    <div id="ledger-profit-factor" style="font-size:16px; font-weight:700; font-family:var(--mono);">0.00</div>
                </div>
                <div style="border-left:2px solid var(--border); padding-left:10px;">
                    <span style="font-size:10px; color:var(--muted); text-transform:uppercase;">Total Trades</span>
                    <div id="ledger-trade-count" style="font-size:16px; font-weight:700; font-family:var(--mono);">0</div>
                </div>
            </div>
            
            <div class="table-wrapper" style="max-height: 400px; overflow-y: auto;">
                <table class="score-table">
                    <thead>
                        <tr>
                            <th>Trade #</th>
                            <th>Type</th>
                            <th>Entry Price</th>
                            <th>Entry Time</th>
                            <th>Exit Price</th>
                            <th>Exit Time</th>
                            <th>Quantity</th>
                            <th>Net P&L (INR)</th>
                            <th>Net P&L (%)</th>
                        </tr>
                    </thead>
                    <tbody id="trade-ledger-body">
                        <!-- Injected dynamically -->
                    </tbody>
                </table>
            </div>
        </section>

        <!-- 4. QUANT SUGGESTIONS AND REJECTION EXPLANATION PANEL -->
        <section class="dashboard-body" style="grid-template-columns: 1fr 1fr; gap: 20px;">
            
            <div class="card">
                <div class="card-title" style="color: var(--rose);">Removed / Reconditioned Strategies</div>
                <div class="alert-boxTip alert-box" style="background: rgba(255, 45, 85, 0.04); border: 1px solid rgba(255, 45, 85, 0.15); color: var(--rose);">
                    <strong>Strict Risk Rules Applied:</strong> Strategies with Profit Factor &lt; 1.3, Max Drawdown &gt; 25%, or Trade Count &lt; 20 were excluded from the baseline portfolio.
                </div>
                <div class="accordion" id="removed-strategies-accordion">
                    <!-- Injected dynamically -->
                </div>
            </div>

            <div class="card">
                <div class="card-title" style="color: var(--cyan);">Institutional Quant PM Guidelines</div>
                <div class="accordion" id="guidelines-accordion">
                    <div class="accordion-item active">
                        <div class="accordion-header" onclick="toggleAccordion(this)">1. VIX-Based Dynamic Scaling <span>▼</span></div>
                        <div class="accordion-content">
                            Automate lot sizing changes based on market volatility. When the VIX index exceeds 20, reduce equity index strangle allocations by 30-50% and allocate the surplus capital to MCX Gold and Silver, which thrive in high VIX environments.
                        </div>
                    </div>
                    <div class="accordion-item">
                        <div class="accordion-header" onclick="toggleAccordion(this)">2. Daily Portfolio circuit Breaker <span>▼</span></div>
                        <div class="accordion-content">
                            Implement a hard stop on your live broker execution. If the portfolio-level combined P&L drops below 2.5% of total capital (₹37,500 on a ₹1.5M capital pool) on any single day, trigger emergency strangling exits to prevent catastrophic drawdowns.
                        </div>
                    </div>
                    <div class="accordion-item">
                        <div class="accordion-header" onclick="toggleAccordion(this)">3. Slippage and Execution Drag <span>▼</span></div>
                        <div class="accordion-content">
                            Remember that these backtests do not model trade slippage. When execution triggers swing trades, a slippage penalty of 0.1% to 0.2% per round-trip trade is standard. Always model a 0.15% frictional drag when evaluating live capital efficiency.
                        </div>
                    </div>
                </div>
            </div>

        </section>

    </div>

    <!-- DATASET EMBEDDING -->
    <script>
        const DATASET = __DATASET_JSON__;
    </script>

    <!-- JS LOGIC -->
    <script>
        let selectedCapital = 1500000;
        let activeStrategies = [];
        let sortColumn = 'FinalScore';
        let sortDirection = 'desc';
        let chartInstance = null;
        let currentLedgerStrategy = '';
        
        // Manual Custom allocations
        let allocationMode = 'auto';
        const strategyWeights = {};
        const strategyMargins = {};
        const strategyLotSizes = {};

        // Initialize App
        function initApp() {
            // Select first kept strategy by default for ledger
            const firstKept = DATASET.strategies.find(s => s.status === 'Kept');
            if (firstKept) {
                currentLedgerStrategy = firstKept.name;
            } else if (DATASET.strategies.length > 0) {
                currentLedgerStrategy = DATASET.strategies[0].name;
            }
            // Set clock
            setInterval(() => {
                const n = new Date();
                document.getElementById('clock-date').textContent = n.toLocaleTimeString("en-IN", {hour12: false});
            }, 1000);

            // Populate overall backtest dates
            document.getElementById('overall-date-val').textContent = DATASET.overall_date_range;
            document.getElementById('overall-duration-val').textContent = DATASET.overall_duration;

            // Populate Start and End Month filters
            const startDropdown = document.getElementById('filter-start-month');
            const endDropdown = document.getElementById('filter-end-month');
            
            let dropdownHtml = '';
            DATASET.dates.forEach(d => {
                dropdownHtml += `<option value="${d}">${d}</option>`;
            });
            
            startDropdown.innerHTML = dropdownHtml;
            endDropdown.innerHTML = dropdownHtml;
            
            // Set defaults: first date and last date
            startDropdown.value = DATASET.dates[0];
            endDropdown.value = DATASET.dates[DATASET.dates.length - 1];

            // Initialize custom weights, margins & lot sizes
            DATASET.strategies.forEach(s => {
                strategyWeights[s.name] = s.status === 'Kept' ? 5 : 0;
                strategyMargins[s.name] = DATASET.lot_margins[s.name] || 120000;
                
                // Set default lot sizes: Stocks default to 1 Qty, Commodities/Indices use standards
                let defaultLotSize = 1;
                if (s.name.includes('NIFTY') || s.name.includes('MIDCAP')) defaultLotSize = 75;
                else if (s.name.includes('GOLD')) defaultLotSize = 100;
                else if (s.name.includes('NATURALGAS')) defaultLotSize = 1250;
                else if (s.name.includes('SILVER')) defaultLotSize = 30;
                
                strategyLotSizes[s.name] = defaultLotSize;
            });

            // Select all 'Kept' strategies by default
            activeStrategies = DATASET.strategies
                .filter(s => s.status === 'Kept')
                .map(s => s.name);

            renderStrategySelector();
            renderCorrelationMatrix();
            renderScoreTable();
            renderRemovedAccordion();
            runSimulation();
            selectLedgerStrategy(currentLedgerStrategy);
        }

        // Toggle Alloc Mode
        function toggleAllocMode(mode) {
            allocationMode = mode;
            document.getElementById('auto-label').style.color = mode === 'auto' ? 'var(--cyan)' : 'var(--muted)';
            document.getElementById('manual-label').style.color = mode === 'manual' ? 'var(--cyan)' : 'var(--muted)';
            renderStrategySelector();
            runSimulation();
        }

        // Update Strategy Custom Weight
        function updateStrategyWeight(name, val) {
            strategyWeights[name] = parseFloat(val);
            document.querySelector(`.weight-val-${name}`).textContent = val;
            
            // Auto include if weight > 0, exclude if weight == 0
            if (parseFloat(val) > 0 && !activeStrategies.includes(name)) {
                activeStrategies.push(name);
            } else if (parseFloat(val) === 0 && activeStrategies.includes(name)) {
                activeStrategies = activeStrategies.filter(n => n !== name);
            }
            document.getElementById('selected-count').textContent = `${activeStrategies.length} / ${DATASET.strategies.length}`;
            
            // Find card and toggle active class
            const cards = document.querySelectorAll('.strategy-item-card');
            cards.forEach(card => {
                const cardName = card.querySelector('.strategy-card-name').textContent.split(' ')[0];
                if (cardName === name) {
                    if (parseFloat(val) > 0) {
                        card.classList.add('active');
                    } else {
                        card.classList.remove('active');
                    }
                }
            });
            
            runSimulation();
        }

        // Update Strategy Margin
        function updateStrategyMargin(name, val) {
            strategyMargins[name] = parseFloat(val) || 120000;
            runSimulation();
        }

        // Update Strategy Lot Size Qty
        function updateStrategyLotSize(name, val) {
            strategyLotSizes[name] = parseInt(val) || 1;
            runSimulation();
        }

        // Render Strategy Toggles
        function renderStrategySelector() {
            const grid = document.getElementById('strategy-selector-grid');
            grid.innerHTML = DATASET.strategies.map(s => {
                const isActive = activeStrategies.includes(s.name);
                const isKept = s.status === 'Kept';
                const weight = strategyWeights[s.name] !== undefined ? strategyWeights[s.name] : (isKept ? 5 : 0);
                const margin = strategyMargins[s.name] !== undefined ? strategyMargins[s.name] : (DATASET.lot_margins[s.name] || 120000);
                const lotsize = strategyLotSizes[s.name] !== undefined ? strategyLotSizes[s.name] : 250;
                
                return `
                    <div class="strategy-item-card ${isActive ? 'active' : ''} ${!isKept ? 'rejected' : ''}" onclick="toggleStrategy('${s.name}', event)" style="padding-bottom: 8px;">
                        <div class="strategy-card-header">
                            <span class="strategy-card-name">${s.name} ${!isKept ? '⚠️' : ''}</span>
                            <span class="strategy-card-score">${s.FinalScore.toFixed(1)} Pts</span>
                        </div>
                        <div class="strategy-card-metrics">
                            <span>PF: <strong>${s.ProfitFactor.toFixed(2)}</strong></span>
                            <span>DD: <strong>${s.DrawdownPct.toFixed(1)}%</strong></span>
                            <span>WR: <strong>${s.WinRate.toFixed(1)}%</strong></span>
                            <span>Trd: <strong>${s.TradeCount}</strong></span>
                        </div>
                        
                        <div class="manual-strategy-controls" onclick="event.stopPropagation()" style="margin-top: 8px; display: flex; flex-direction: column; gap: 4px; border-top: 1px solid var(--border); padding-top: 6px;">
                            <div style="display:flex; justify-content:space-between; font-size:10px; color:var(--muted);">
                                <span>Rel. Weight:</span>
                                <span class="weight-val-${s.name}" style="color:var(--cyan); font-weight:700;">${weight}</span>
                            </div>
                            <input type="range" class="weight-slider-${s.name}" min="0" max="10" step="1" value="${weight}" oninput="updateStrategyWeight('${s.name}', this.value)" style="height:3px; margin:2px 0;" ${allocationMode === 'auto' ? 'disabled style="opacity:0.4; cursor:not-allowed;"' : ''}>
                            
                            <div style="display:flex; align-items:center; justify-content:space-between; font-size:10px; color:var(--muted); margin-top:2px;">
                                <span>Margin/Lot:</span>
                                <input type="number" class="margin-input-${s.name}" value="${margin}" onchange="updateStrategyMargin('${s.name}', this.value)" style="width:75px; background:rgba(0,0,0,0.5); border:1px solid var(--border); color:var(--text); font-family:var(--mono); font-size:9px; text-align:right; border-radius:3px; padding:1px 4px; outline:none;">
                            </div>
                            <div style="display:flex; align-items:center; justify-content:space-between; font-size:10px; color:var(--muted); margin-top:2px;">
                                <span>Qty per Lot:</span>
                                <input type="number" class="lotsize-input-${s.name}" value="${lotsize}" onchange="updateStrategyLotSize('${s.name}', this.value)" style="width:75px; background:rgba(0,0,0,0.5); border:1px solid var(--border); color:var(--text); font-family:var(--mono); font-size:9px; text-align:right; border-radius:3px; padding:1px 4px; outline:none;">
                            </div>
                            <button onclick="selectLedgerStrategy('${s.name}')" style="margin-top:6px; background:rgba(0,255,204,0.1); border:1px solid rgba(0,255,204,0.25); color:var(--cyan); padding:4px 8px; border-radius:4px; font-size:10px; cursor:pointer; font-weight:600; width:100%; text-align:center; transition:all 0.2s;" onmouseover="this.style.background='rgba(0,255,204,0.2)'" onmouseout="this.style.background='rgba(0,255,204,0.1)'">View Trade Ledger 📊</button>
                        </div>
                        
                        <div class="strategy-toggle-indicator">✓</div>
                    </div>
                `;
            }).join('');
            document.getElementById('selected-count').textContent = `${activeStrategies.length} / ${DATASET.strategies.length}`;
        }

        // Toggle Single Strategy
        function toggleStrategy(name, event) {
            if (event && event.target.closest('.manual-strategy-controls')) {
                return;
            }
            if (activeStrategies.includes(name)) {
                activeStrategies = activeStrategies.filter(n => n !== name);
                if (allocationMode === 'manual') {
                    strategyWeights[name] = 0;
                }
            } else {
                activeStrategies.push(name);
                if (allocationMode === 'manual' && strategyWeights[name] === 0) {
                    strategyWeights[name] = 5;
                }
            }
            renderStrategySelector();
            runSimulation();
        }

        // Select All / Select Kept / Select None
        function toggleAllStrategies(keptOnly) {
            if (keptOnly) {
                activeStrategies = DATASET.strategies.filter(s => s.status === 'Kept').map(s => s.name);
                if (allocationMode === 'manual') {
                    DATASET.strategies.forEach(s => {
                        strategyWeights[s.name] = s.status === 'Kept' ? 5 : 0;
                    });
                }
            } else {
                activeStrategies = [];
                if (allocationMode === 'manual') {
                    DATASET.strategies.forEach(s => {
                        strategyWeights[s.name] = 0;
                    });
                }
            }
            renderStrategySelector();
            runSimulation();
        }

        // Render Correlation Table (Filtered dynamically by active selection)
        function renderCorrelationMatrix() {
            const table = document.getElementById('correlation-matrix-table');
            const stratNames = activeStrategies;
            
            if (stratNames.length === 0) {
                table.innerHTML = '<tr><td style="color:var(--muted); text-align:center; padding:30px; font-family:var(--sans); font-size:12px;">No active strategies selected for correlation matrix.</td></tr>';
                return;
            }
            
            let html = '<thead><tr><th>Symbol</th>';
            stratNames.forEach(n => {
                html += `<th>${n.substring(0, 7)}</th>`;
            });
            html += '</tr></thead><tbody>';
            
            stratNames.forEach(rowName => {
                html += `<tr><th>${rowName}</th>`;
                stratNames.forEach(colName => {
                    const corr = DATASET.correlation_matrix[rowName][colName] || 0.0;
                    let cellColor = 'transparent';
                    let textColor = 'var(--text)';
                    
                    if (rowName === colName) {
                        cellColor = 'rgba(0, 255, 204, 0.15)';
                    } else if (corr > 0.4) {
                        cellColor = `rgba(255, 45, 85, ${corr * 0.4})`;
                    } else if (corr < -0.1) {
                        cellColor = `rgba(0, 230, 118, ${Math.abs(corr) * 0.4})`;
                    }
                    
                    html += `<td style="background:${cellColor}; color:${textColor};">${corr.toFixed(2)}</td>`;
                });
                html += '</tr>';
            });
            html += '</tbody>';
            table.innerHTML = html;
        }

        // Render Removed accordion
        function renderRemovedAccordion() {
            const container = document.getElementById('removed-strategies-accordion');
            const rejected = DATASET.strategies.filter(s => s.status === 'Rejected');
            
            if (rejected.length === 0) {
                container.innerHTML = '<div style="color:var(--muted); font-size:12px; padding:10px;">No strategies rejected.</div>';
                return;
            }
            
            container.innerHTML = rejected.map((s, idx) => `
                <div class="accordion-item">
                    <div class="accordion-header" onclick="toggleAccordion(this)">
                        <span>${s.name} (Score: ${s.FinalScore.toFixed(1)})</span>
                        <span style="color: var(--rose);">PF: ${s.ProfitFactor.toFixed(2)} | DD: ${s.DrawdownPct.toFixed(1)}% ▼</span>
                    </div>
                    <div class="accordion-content">
                        <strong>Rejection Reasons:</strong> <span style="color:var(--rose);">${s.rejection_reason}</span><br><br>
                        <strong>Strategy Metrics Profile:</strong><br>
                        - Total Net Profit: ₹${s.NetProfit.toLocaleString("en-IN")}<br>
                        - Win Rate: ${s.WinRate.toFixed(1)}%<br>
                        - Risk:Reward Ratio: ${s.RiskReward.toFixed(2)}<br>
                        - Trade Count: ${s.TradeCount}<br>
                        - Monthly Consistency: ${s.ConsistencyScore.toFixed(1)}%
                    </div>
                </div>
            `).join('');
        }

        // Accordion Toggler
        function toggleAccordion(element) {
            const item = element.parentElement;
            item.classList.toggle('active');
        }

        // Render Score Table
        function renderScoreTable() {
            const body = document.getElementById('score-table-body');
            const searchVal = document.getElementById('table-search').value.toLowerCase();
            
            let list = [...DATASET.strategies];
            
            // Search filter
            if (searchVal) {
                list = list.filter(s => s.name.toLowerCase().includes(searchVal));
            }
            
            // Sort
            list.sort((a, b) => {
                let valA = a[sortColumn];
                let valB = b[sortColumn];
                
                if (typeof valA === 'string') {
                    valA = valA.toLowerCase();
                    valB = valB.toLowerCase();
                }
                
                if (valA < valB) return sortDirection === 'asc' ? -1 : 1;
                if (valA > valB) return sortDirection === 'asc' ? 1 : -1;
                return 0;
            });
            
            body.innerHTML = list.map(s => `
                <tr class="${s.status === 'Rejected' ? 'rejected-row' : ''} ${s.name === currentLedgerStrategy ? 'active-ledger-row' : ''}" onclick="selectLedgerStrategy('${s.name}')" style="cursor:pointer;" title="Click to view detailed trade ledger">
                    <td><strong>${s.name}</strong></td>
                    <td><span class="status-badge ${s.status.toLowerCase()}">${s.status}</span></td>
                    <td style="color:${s.NetProfit >= 0 ? 'var(--emerald)' : 'var(--rose)'}">₹${s.NetProfit.toLocaleString("en-IN")}</td>
                    <td>${s.DrawdownPct.toFixed(1)}%</td>
                    <td>${s.ProfitFactor.toFixed(2)}</td>
                    <td>${s.WinRate.toFixed(1)}%</td>
                    <td>${s.RiskReward.toFixed(2)}</td>
                    <td>${s.TradeCount}</td>
                    <td>${s.ConsistencyScore.toFixed(1)}%</td>
                    <td>${s.CorrelationScore.toFixed(2)}</td>
                    <td style="color:var(--cyan); font-weight:700;">${s.FinalScore.toFixed(1)}</td>
                </tr>
            `).join('');
        }

        function sortTable(column) {
            if (sortColumn === column) {
                sortDirection = sortDirection === 'asc' ? 'desc' : 'asc';
            } else {
                sortColumn = column;
                sortDirection = 'desc';
            }
            renderScoreTable();
        }

        function filterTable(val) {
            renderScoreTable();
        }

        // Update Capital from Slider
        function updateCapital(val) {
            selectedCapital = parseInt(val);
            document.getElementById('capital-val').textContent = `₹${(selectedCapital / 100000).toFixed(1)}L`;
            document.getElementById('capital-control-display').textContent = `₹${selectedCapital.toLocaleString("en-IN")}`;
            runSimulation();
        }

        // ----------------------------------------------------
        // 4. Portfolio Simulator Core Math (JS)
        // ----------------------------------------------------
        function runSimulation() {
            if (activeStrategies.length === 0) {
                // Empty state
                document.getElementById('port-return-val').textContent = '₹0';
                document.getElementById('port-return-val').style.color = 'var(--muted)';
                document.getElementById('port-return-desc').textContent = '0.00% Total Return (0.00% Ann.)';
                document.getElementById('port-dd-val').textContent = '0.00%';
                document.getElementById('port-dd-inr-val').textContent = '₹0';
                document.getElementById('port-sharpe-val').textContent = '0.00';
                document.getElementById('port-div-val').textContent = 'Diversification Score: 1.00';
                document.getElementById('lots-table-body').innerHTML = '<tr><td colspan="5" style="color:var(--muted); text-align:center;">No active strategies selected</td></tr>';
                if (chartInstance) chartInstance.destroy();
                return;
            }

            // Calculate active strategy weights based on mode
            const weights = {};
            let totalWeightMetric = 0;
            
            activeStrategies.forEach(name => {
                if (allocationMode === 'auto') {
                    const s = DATASET.strategies.find(st => st.name === name);
                    const ddCap = Math.max(s.DrawdownPct, 1.0);
                    let metric = s.AnnualizedReturn / ddCap;
                    
                    // correlation penalty
                    const corrPenalty = Math.max(0.2, 1.0 - s.CorrelationScore);
                    metric = metric * corrPenalty;
                    
                    weights[name] = metric;
                } else {
                    weights[name] = strategyWeights[name] || 0;
                }
                totalWeightMetric += weights[name];
            });

            // Normalize weights & build allocation table
            const normWeights = {};
            const allocatedCap = {};
            const allocatedLots = {};
            
            let lotsTableHtml = '';
            
            activeStrategies.forEach(name => {
                const s = DATASET.strategies.find(st => st.name === name);
                const weight = totalWeightMetric > 0 ? weights[name] / totalWeightMetric : 0;
                normWeights[name] = weight;
                
                const cap = weight * selectedCapital;
                allocatedCap[name] = cap;
                
                const margin = strategyMargins[name] || 120000;
                const lotsize = strategyLotSizes[name] || 250;
                const lots = Math.floor(cap / margin);
                allocatedLots[name] = lots;
                const totalQty = lots * lotsize;
                
                lotsTableHtml += `
                    <tr>
                        <td><strong>${name}</strong></td>
                        <td>${(weight * 100).toFixed(1)}%</td>
                        <td>₹${Math.round(cap).toLocaleString("en-IN")}</td>
                        <td>₹${margin.toLocaleString("en-IN")}</td>
                        <td style="color:${lots > 0 ? 'var(--cyan)' : 'var(--muted)'}; font-weight:700;">${lots} lots (${totalQty.toLocaleString("en-IN")} Qty)</td>
                    </tr>
                `;
            });
            document.getElementById('lots-table-body').innerHTML = lotsTableHtml;

            // Simulate monthly P&L within filtered date range
            const startMonthVal = document.getElementById('filter-start-month') ? document.getElementById('filter-start-month').value : DATASET.dates[0];
            const endMonthVal = document.getElementById('filter-end-month') ? document.getElementById('filter-end-month').value : DATASET.dates[DATASET.dates.length - 1];
            
            const startIndex = DATASET.dates.indexOf(startMonthVal);
            const endIndex = DATASET.dates.indexOf(endMonthVal);
            const filteredDates = DATASET.dates.slice(startIndex, endIndex + 1);
            const numMonthsFiltered = filteredDates.length;
            
            const portfolioMonthlyPnl = new Array(numMonthsFiltered).fill(0.0);
            
            activeStrategies.forEach(name => {
                const weight = normWeights[name];
                const pnlSeries = DATASET.aligned_monthly_pnl[name];
                for (let i = startIndex; i <= endIndex; i++) {
                    portfolioMonthlyPnl[i - startIndex] += pnlSeries[i] * weight;
                }
            });

            // Compute portfolio statistics
            const portfolioCumPnl = [];
            let currentCum = 0.0;
            portfolioMonthlyPnl.forEach(val => {
                currentCum += val;
                portfolioCumPnl.push(currentCum);
            });

            const portfolioEquity = portfolioCumPnl.map(pnl => selectedCapital + pnl);
            
            // Drawdown calculation
            let runningMax = selectedCapital;
            let maxDdPct = 0.0;
            let maxDdInr = 0.0;
            
            portfolioEquity.forEach(eq => {
                if (eq > runningMax) {
                    runningMax = eq;
                }
                const ddInr = runningMax - eq;
                const ddPct = (ddInr / runningMax) * 100;
                if (ddPct > maxDdPct) maxDdPct = ddPct;
                if (ddInr > maxDdInr) maxDdInr = ddInr;
            });

            // Expected return
            const totalProfit = portfolioMonthlyPnl.reduce((a, b) => a + b, 0);
            const durationYears = numMonthsFiltered / 12;
            const portAnnReturn = (totalProfit / selectedCapital) / durationYears * 100;

            // Sharpe
            const monthlyReturns = portfolioMonthlyPnl.map(pnl => pnl / selectedCapital);
            const meanReturn = monthlyReturns.reduce((a, b) => a + b, 0) / numMonthsFiltered;
            const variance = monthlyReturns.reduce((a, b) => a + Math.pow(b - meanReturn, 2), 0) / (numMonthsFiltered - 1);
            const stdReturn = Math.sqrt(variance);
            const portfolioSharpe = stdReturn > 0 ? (meanReturn / stdReturn) * Math.sqrt(12) : 0.0;

            // Diversification score (Weighted Vol / Port Vol)
            let weightedVol = 0.0;
            activeStrategies.forEach(name => {
                const weight = normWeights[name];
                const pnlSeries = DATASET.aligned_monthly_pnl[name];
                const slicedPnl = pnlSeries.slice(startIndex, endIndex + 1);
                const stratReturns = slicedPnl.map(val => val / selectedCapital);
                const stratMean = stratReturns.reduce((a, b) => a + b, 0) / numMonthsFiltered;
                const stratVar = stratReturns.reduce((a, b) => a + Math.pow(b - stratMean, 2), 0) / (numMonthsFiltered - 1);
                const stratVol = Math.sqrt(stratVar);
                weightedVol += weight * stratVol;
            });
            const portfolioVol = stdReturn;
            const divScore = portfolioVol > 0 ? weightedVol / portfolioVol : 1.0;

            // Update UI Metrics
            const portTotalReturnPct = (totalProfit / selectedCapital) * 100;
            const isPositive = totalProfit >= 0;
            const amountPrefix = isPositive ? '+' : '-';
            const pctPrefix = isPositive ? '+' : '';
            
            const totalProfitFormatted = amountPrefix + '₹' + Math.abs(Math.round(totalProfit)).toLocaleString("en-IN");
            const descFormatted = `${pctPrefix}${portTotalReturnPct.toFixed(2)}% Total Return (${pctPrefix}${portAnnReturn.toFixed(2)}% Ann.)`;
            
            const returnValEl = document.getElementById('port-return-val');
            const returnCardEl = document.getElementById('port-return-card');
            
            returnValEl.textContent = totalProfitFormatted;
            returnValEl.style.color = isPositive ? 'var(--emerald)' : 'var(--rose)';
            if (returnCardEl) {
                returnCardEl.style.setProperty('--border-color', isPositive ? 'var(--emerald)' : 'var(--rose)');
            }
            document.getElementById('port-return-desc').textContent = descFormatted;
            
            document.getElementById('port-dd-val').textContent = `${maxDdPct.toFixed(2)}%`;
            document.getElementById('port-dd-inr-val').textContent = `₹${Math.round(maxDdInr).toLocaleString("en-IN")} max historical drop`;
            document.getElementById('port-sharpe-val').textContent = portfolioSharpe.toFixed(2);
            document.getElementById('port-div-val').textContent = `Diversification Score: ${divScore.toFixed(2)}`;

            // Render Chart
            renderChart(filteredDates, portfolioEquity);

            // Dynamically recalculate and display correlation matrix for selected strategies only
            renderCorrelationMatrix();
        }

        // Render Chart using Chart.js
        function renderChart(dates, equitySeries) {
            const ctx = document.getElementById('portfolioChart').getContext('2d');
            
            if (chartInstance) {
                chartInstance.destroy();
            }

            chartInstance = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: dates,
                    datasets: [{
                        label: 'Simulated Portfolio Value (INR)',
                        data: equitySeries,
                        borderColor: '#00ffcc',
                        borderWidth: 2.5,
                        backgroundColor: 'rgba(0, 255, 204, 0.05)',
                        fill: true,
                        tension: 0.15,
                        pointRadius: 0,
                        pointHoverRadius: 5
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: function(context) {
                                    let label = context.dataset.label || '';
                                    if (label) {
                                        label += ': ';
                                    }
                                    if (context.parsed.y !== null) {
                                        label += new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(context.parsed.y);
                                    }
                                    return label;
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            grid: { color: 'rgba(255, 255, 255, 0.03)' },
                            ticks: { color: '#8a96a8', font: { size: 9, family: 'JetBrains Mono' } }
                        },
                        y: {
                            grid: { color: 'rgba(255, 255, 255, 0.03)' },
                            ticks: { 
                                color: '#8a96a8', 
                                font: { size: 9, family: 'JetBrains Mono' },
                                callback: function(value, index, values) {
                                    return '₹' + (value / 100000).toFixed(1) + 'L';
                                }
                            }
                        }
                    }
                }
            });
        }

        // ----------------------------------------------------
        // 5. Individual Strategy Trade Ledger Engine (JS)
        // ----------------------------------------------------
        function selectLedgerStrategy(name) {
            currentLedgerStrategy = name;
            
            // Highlight the active row in scorecard table
            const rows = document.querySelectorAll('#score-table-body tr');
            rows.forEach(row => {
                const rowNameCell = row.querySelector('td strong');
                if (rowNameCell && rowNameCell.textContent === name) {
                    row.classList.add('active-ledger-row');
                } else {
                    row.classList.remove('active-ledger-row');
                }
            });

            // Update Ledger UI Header & Metrics
            const s = DATASET.strategies.find(st => st.name === name);
            if (!s) return;

            document.getElementById('ledger-strategy-name').textContent = name;
            document.getElementById('ledger-net-profit').textContent = `₹${Math.round(s.NetProfit).toLocaleString("en-IN")}`;
            document.getElementById('ledger-net-profit').style.color = s.NetProfit >= 0 ? 'var(--emerald)' : 'var(--rose)';
            document.getElementById('ledger-win-rate').textContent = `${s.WinRate.toFixed(1)}%`;
            document.getElementById('ledger-profit-factor').textContent = s.ProfitFactor.toFixed(2);
            document.getElementById('ledger-trade-count').textContent = s.trades ? s.trades.length : 0;
            
            // Reset filters & input
            document.getElementById('ledger-type-filter').value = 'all';
            document.getElementById('ledger-pnl-filter').value = 'all';
            document.getElementById('ledger-search').value = '';
            
            renderLedgerTable();
        }

        function renderLedgerTable() {
            const body = document.getElementById('trade-ledger-body');
            const typeFilter = document.getElementById('ledger-type-filter').value;
            const pnlFilter = document.getElementById('ledger-pnl-filter').value;
            const searchVal = document.getElementById('ledger-search').value.toLowerCase();
            
            const s = DATASET.strategies.find(st => st.name === currentLedgerStrategy);
            if (!s || !s.trades || s.trades.length === 0) {
                body.innerHTML = '<tr><td colspan="9" style="text-align:center; color:var(--muted); padding:20px;">No trade ledger data available for this strategy.</td></tr>';
                return;
            }
            
            let list = [...s.trades];
            
            // Filter by selected date range
            const startMonthVal = document.getElementById('filter-start-month') ? document.getElementById('filter-start-month').value : DATASET.dates[0];
            const endMonthVal = document.getElementById('filter-end-month') ? document.getElementById('filter-end-month').value : DATASET.dates[DATASET.dates.length - 1];
            
            list = list.filter(t => {
                const ym = getTradeYearMonth(t.exit_time);
                return ym >= startMonthVal && ym <= endMonthVal;
            });
            
            // Filter Long vs Short
            if (typeFilter !== 'all') {
                list = list.filter(t => t.type === typeFilter);
            }
            
            // Filter Wins vs Losses
            if (pnlFilter === 'win') {
                list = list.filter(t => t.pnl_inr > 0);
            } else if (pnlFilter === 'loss') {
                list = list.filter(t => t.pnl_inr < 0);
            }
            
            // Filter Search Query
            if (searchVal) {
                list = list.filter(t => 
                    t.trade_no.toString().includes(searchVal) || 
                    t.entry_time.toLowerCase().includes(searchVal) || 
                    t.exit_time.toLowerCase().includes(searchVal)
                );
            }
            
            if (list.length === 0) {
                body.innerHTML = '<tr><td colspan="9" style="text-align:center; color:var(--muted); padding:20px;">No trades matched the selected filters.</td></tr>';
                return;
            }
            
            body.innerHTML = list.map(t => {
                const pnlInr = t.pnl_inr;
                const pnlPct = t.pnl_pct;
                const typeClass = t.type === 'Long' ? 'status-badge kept' : 'status-badge rejected';
                const pnlStyle = pnlInr >= 0 ? 'color:var(--emerald); font-weight:600;' : 'color:var(--rose); font-weight:600;';
                
                return `
                    <tr>
                        <td><strong>#${t.trade_no}</strong></td>
                        <td><span class="${typeClass}" style="padding:2px 6px; font-size:10px;">${t.type}</span></td>
                        <td>₹${t.entry_price.toLocaleString("en-IN", {minimumFractionDigits:2})}</td>
                        <td style="color:var(--muted); font-size:11px;">${t.entry_time}</td>
                        <td>₹${t.exit_price.toLocaleString("en-IN", {minimumFractionDigits:2})}</td>
                        <td style="color:var(--muted); font-size:11px;">${t.exit_time}</td>
                        <td>${t.qty.toLocaleString("en-IN")}</td>
                        <td style="${pnlStyle}">₹${Math.round(pnlInr).toLocaleString("en-IN")}</td>
                        <td style="${pnlStyle}">${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%</td>
                    </tr>
                `;
            }).join('');
        }

        function filterLedger() {
            renderLedgerTable();
        }

        // Helper to extract YYYY-MM from exit date string
        function getTradeYearMonth(dateStr) {
            if (!dateStr) return '';
            const datePart = dateStr.split(' ')[0];
            const parts = datePart.split('-');
            if (parts.length === 3) {
                const year = parts[2];
                const month = parts[1]; // "01", "02", etc.
                return `${year}-${month}`;
            }
            return '';
        }

        // Handle dropdown month selection changes
        function updateDateFilter() {
            const startVal = document.getElementById('filter-start-month').value;
            const endVal = document.getElementById('filter-end-month').value;
            
            const startIndex = DATASET.dates.indexOf(startVal);
            const endIndex = DATASET.dates.indexOf(endVal);
            
            // If end month is before start month, auto-adjust end month to start month
            if (endIndex < startIndex) {
                document.getElementById('filter-end-month').value = startVal;
            }
            
            // Re-run simulation and ledger tables
            runSimulation();
            if (currentLedgerStrategy) {
                renderLedgerTable();
            }
        }

        // Start App on page load
        window.onload = initApp;
    </script>
</body>
</html>
"""

html_code = html_code.replace('__DATASET_JSON__', json.dumps(dashboard_dataset))

with open(output_html, 'w', encoding='utf-8') as f:
    f.write(html_code)

print("Dashboard compiled successfully and saved as portfolio_dashboard.html!")

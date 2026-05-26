import sys, os, time, csv, json, traceback
from datetime import datetime, date
import pandas as pd

# Override built-in print for Windows terminal CP1252 / ASCII character map safety
_original_print = print
def print(*args, **kwargs):
    try:
        _original_print(*args, **kwargs)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or 'ascii'
        new_args = []
        for arg in args:
            if isinstance(arg, str):
                new_args.append(arg.encode(enc, errors='replace').decode(enc))
            else:
                new_args.append(arg)
        _original_print(*new_args, **kwargs)

sys.path.insert(0, os.path.dirname(__file__))
from my_util import (load_spot_data, create_spot_ohlc, list_trading_dates,
                     calculate_strike)

# Initialize globals for live status reporting
prev_close     = None
gap            = None
direction      = None
open_price     = None

# Strategy 1: Buying (BASE) Globals
base_active        = False
base_symbol        = None
base_strike        = None
base_opt_type      = None
base_target_spot   = None
base_sl_spot       = None
base_entry_time    = None
base_entry_price   = None
base_exit_time     = None
base_exit_price    = None
base_pnl_pts       = None
base_pnl_rs        = None
base_result        = None
base_spot_at_entry = None
base_signal_time   = None
base_ltp           = None
base_status_desc   = "Scanning for P-touch..."

# Strategy 2: Selling (Strangle) Globals
strangle_active         = False
strangle_ce_symbol      = None
strangle_pe_symbol      = None
strangle_ce_strike      = None
strangle_pe_strike      = None
strangle_ce_entry_price = None
strangle_pe_entry_price = None
strangle_ce_exit_price  = None
strangle_pe_exit_price  = None
strangle_ce_ltp         = None
strangle_pe_ltp         = None
strangle_entry_time     = None
strangle_exit_time      = None
strangle_pnl_pts        = None
strangle_pnl_rs         = None
strangle_result         = None
strangle_status_desc    = "Waiting for 09:16 strangle entry..."
strangle_combined_sl    = 7000.0
spot_at_0916            = None

# ════════════════════════════════════════════════════════
#  CONFIGURATION — default settings (overridden by data/config.json if exists)
# ════════════════════════════════════════════════════════
OPENALGO_HOST   = "http://127.0.0.1:5000"
OPENALGO_API_KEY = "YOUR_OPENALGO_API_KEY"   # from OpenAlgo dashboard

LOT_SIZE        = 65       # NIFTY lot size
GAP_THRESH      = 30       # minimum gap in pts
P_TOL           = 10       # pivot touch tolerance pts
SL_PTS          = 20       # SL distance from P in pts
ENTRY_CUTOFF    = "13:00"  # no new entries after this
EOD_EXIT        = "15:20"  # force exit time (NRML - no broker auto-squareoff restriction)

PAPER_TRADE     = True     # True = paper trade only (no real orders)
POLL_SIGNAL_SEC = 30       # how often to check for signal (seconds)
POLL_EXIT_SEC   = 15       # how often to monitor exit conditions (seconds)

TELEGRAM_BOT_TOKEN = None
TELEGRAM_CHAT_ID   = None

LOG_FILE        = os.path.join(os.path.dirname(__file__),
                               "data", "paper_trade_log.csv")
CONFIG_FILE     = os.path.join(os.path.dirname(__file__),
                               "data", "config.json")

# Load dynamic config
if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, 'r') as f:
            cfg = json.load(f)
            OPENALGO_HOST = cfg.get("OPENALGO_HOST", OPENALGO_HOST)
            OPENALGO_API_KEY = cfg.get("OPENALGO_API_KEY", OPENALGO_API_KEY)
            LOT_SIZE = int(cfg.get("LOT_SIZE", LOT_SIZE))
            GAP_THRESH = float(cfg.get("GAP_THRESH", GAP_THRESH))
            P_TOL = float(cfg.get("P_TOL", P_TOL))
            SL_PTS = float(cfg.get("SL_PTS", SL_PTS))
            ENTRY_CUTOFF = cfg.get("ENTRY_CUTOFF", ENTRY_CUTOFF)
            EOD_EXIT = cfg.get("EOD_EXIT", EOD_EXIT)
            PAPER_TRADE = bool(cfg.get("PAPER_TRADE", PAPER_TRADE))
            TELEGRAM_BOT_TOKEN = cfg.get("TELEGRAM_BOT_TOKEN", None)
            TELEGRAM_CHAT_ID = cfg.get("TELEGRAM_CHAT_ID", None)
            print(f"Loaded config from {CONFIG_FILE}")
    except Exception as e:
        print(f"WARN: Failed to load config from {CONFIG_FILE}, using defaults: {e}")

STATUS_FILE = os.path.join(os.path.dirname(__file__), "data", "live_status.json")

def load_live_status():
    """Load active trades from live_status.json on startup to recover state."""
    global strangle_active, strangle_entered, strangle_ce_symbol, strangle_pe_symbol
    global strangle_ce_strike, strangle_pe_strike, strangle_ce_entry_price, strangle_pe_entry_price
    global strangle_entry_time, spot_at_0916
    global base_active, base_entered, base_symbol, base_strike, base_opt_type
    global base_entry_time, base_entry_price, base_target_spot, base_sl_spot, base_spot_at_entry, base_signal_time

    if not os.path.exists(STATUS_FILE):
        return
        
    try:
        with open(STATUS_FILE, 'r') as f:
            data = json.load(f)
            
        # Verify if the status belongs to today's date
        status_date = data.get('date')
        if status_date != today_str:
            print(f"Status file belongs to another date ({status_date}), skipping recovery.")
            return
            
        # Recover Strangle
        sell_data = data.get('selling', {})
        if sell_data.get('in_trade'):
            strangle_active = True
            strangle_entered = True
            strangle_ce_symbol = sell_data.get('ce_symbol')
            strangle_pe_symbol = sell_data.get('pe_symbol')
            strangle_ce_strike = sell_data.get('ce_strike')
            strangle_pe_strike = sell_data.get('pe_strike')
            strangle_ce_entry_price = sell_data.get('ce_entry_price')
            strangle_pe_entry_price = sell_data.get('pe_entry_price')
            strangle_entry_time = sell_data.get('entry_time')
            # Fallback for spot_at_0916
            spot_at_0916 = data.get('live_data', {}).get('spot')
            print(f"SUCCESSFULLY RECOVERED RUNNING STRANGLE: CE={strangle_ce_symbol} @ {strangle_ce_entry_price} | PE={strangle_pe_symbol} @ {strangle_pe_entry_price}")
            
        # Recover BASE Buying
        buy_data = data.get('buying', {})
        if buy_data.get('in_trade'):
            base_active = True
            base_entered = True
            base_symbol = buy_data.get('symbol')
            base_strike = buy_data.get('strike')
            base_opt_type = buy_data.get('opt_type')
            base_entry_time = buy_data.get('entry_time')
            base_entry_price = buy_data.get('entry_price')
            base_target_spot = buy_data.get('target_spot')
            base_sl_spot = buy_data.get('sl_spot')
            base_signal_time = buy_data.get('entry_time') # estimate
            base_spot_at_entry = data.get('live_data', {}).get('spot')
            print(f"SUCCESSFULLY RECOVERED RUNNING BASE BUY: {base_symbol} @ {base_entry_price}")
            
    except Exception as e:
        print(f"WARN: Failed to load live status for recovery: {e}")

def update_live_status(status, status_desc, live_spot=None):
    """Save current state to JSON for the web UI."""
    try:
        os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
        
        # Estimate live BASE Buying P&L
        cur_buy_pnl_pts = 0.0
        cur_buy_pnl_rs = 0.0
        if base_active and base_entry_price:
            ltp_to_use = base_ltp if base_ltp else (base_entry_price + (live_spot - base_spot_at_entry) * (0.5 if base_opt_type == 'CE' else -0.5) if (live_spot and base_spot_at_entry) else base_entry_price)
            cur_buy_pnl_pts = round(ltp_to_use - base_entry_price, 2)
            cur_buy_pnl_rs = round(cur_buy_pnl_pts * (LOT_SIZE * 3), 2)  # 3 lots = 195
        elif base_exit_price is not None and base_entry_price is not None:
            cur_buy_pnl_pts = base_pnl_pts
            cur_buy_pnl_rs = base_pnl_rs

        # Estimate live Strangle Selling P&L
        cur_sell_pnl_pts = 0.0
        cur_sell_pnl_rs = 0.0
        if strangle_active and strangle_ce_entry_price and strangle_pe_entry_price:
            ce_ltp_to_use = strangle_ce_ltp if strangle_ce_ltp else (strangle_ce_entry_price + (live_spot - spot_at_0916) * 0.4 if (live_spot and spot_at_0916) else strangle_ce_entry_price)
            pe_ltp_to_use = strangle_pe_ltp if strangle_pe_ltp else (strangle_pe_entry_price - (live_spot - spot_at_0916) * 0.4 if (live_spot and spot_at_0916) else strangle_pe_entry_price)
            cur_sell_pnl_pts = round(strangle_ce_entry_price - ce_ltp_to_use + strangle_pe_entry_price - pe_ltp_to_use, 2)
            cur_sell_pnl_rs = round(cur_sell_pnl_pts * LOT_SIZE, 2)
        elif strangle_ce_exit_price is not None and strangle_pe_exit_price is not None:
            cur_sell_pnl_pts = strangle_pnl_pts
            cur_sell_pnl_rs = strangle_pnl_rs
            
        data = {
            'last_update': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'date': today_str if 'today_str' in globals() else datetime.now().strftime("%Y%m%d"),
            'status': status,
            'status_desc': status_desc,
            'mode': 'PAPER' if PAPER_TRADE else 'LIVE',
            'lot_size': LOT_SIZE,
            'pivots': {
                'P': P if 'P' in globals() and P is not None else None,
                'R1': R1 if 'R1' in globals() and R1 is not None else None,
                'S1': S1 if 'S1' in globals() and S1 is not None else None,
                'R2': R2 if 'R2' in globals() and R2 is not None else None,
                'S2': S2 if 'S2' in globals() and S2 is not None else None,
                'prev_close': prev_close if 'prev_close' in globals() and prev_close is not None else None
            },
            'gap': {
                'open_price': open_price,
                'prev_close': prev_close,
                'gap_pts': gap
            },
            'live_data': {
                'spot': live_spot,
            },
            'buying': {
                'status': 'IN_TRADE' if base_active else ('NO_TRADE' if status == 'NO_TRADE' or base_result in ['SKIP', 'ERROR'] else ('CLOSED' if base_exit_price else 'SCANNING')),
                'status_desc': base_status_desc,
                'in_trade': base_active,
                'symbol': base_symbol,
                'strike': base_strike,
                'opt_type': base_opt_type,
                'entry_time': base_entry_time,
                'entry_price': base_entry_price,
                'exit_time': base_exit_time,
                'exit_price': base_exit_price,
                'pnl_pts': cur_buy_pnl_pts,
                'pnl_rs': cur_buy_pnl_rs,
                'result': base_result,
                'target_spot': base_target_spot,
                'sl_spot': base_sl_spot,
                'to_target': round(live_spot - base_target_spot if base_opt_type == 'CE' else base_target_spot - live_spot, 2) if (live_spot and base_target_spot) else None,
                'to_sl': round(live_spot - base_sl_spot if base_opt_type == 'CE' else base_sl_spot - live_spot, 2) if (live_spot and base_sl_spot) else None
            },
            'selling': {
                'status': 'IN_TRADE' if strangle_active else ('NO_TRADE' if status == 'NO_TRADE' or strangle_result in ['ERROR'] else ('CLOSED' if strangle_ce_exit_price else 'WAIT_ENTRY')),
                'status_desc': strangle_status_desc,
                'in_trade': strangle_active,
                'ce_symbol': strangle_ce_symbol,
                'pe_symbol': strangle_pe_symbol,
                'ce_strike': strangle_ce_strike,
                'pe_strike': strangle_pe_strike,
                'ce_entry_price': strangle_ce_entry_price,
                'pe_entry_price': strangle_pe_entry_price,
                'ce_exit_price': strangle_ce_exit_price,
                'pe_exit_price': strangle_pe_exit_price,
                'ce_ltp': strangle_ce_ltp,
                'pe_ltp': strangle_pe_ltp,
                'entry_time': strangle_entry_time,
                'exit_time': strangle_exit_time,
                'pnl_pts': cur_sell_pnl_pts,
                'pnl_rs': cur_sell_pnl_rs,
                'result': strangle_result,
                'combined_sl': strangle_combined_sl
            }
        }
        with open(STATUS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"WARN: update_live_status failed: {e}")
# ════════════════════════════════════════════════════════

# ── OpenAlgo client ────────────────────────────────────────────────────────
try:
    from openalgo import api as OpenAlgoAPI
    client = OpenAlgoAPI(api_key=OPENALGO_API_KEY, host=OPENALGO_HOST)
    print(f"OpenAlgo connected: {OPENALGO_HOST}")
except ImportError:
    print("ERROR: openalgo not installed. Run: pip install openalgo")
    sys.exit(1)
except Exception as e:
    print(f"ERROR connecting to OpenAlgo: {e}")
    print("Make sure OpenAlgo server is running at", OPENALGO_HOST)
    sys.exit(1)


# ── Helpers ────────────────────────────────────────────────────────────────
def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}]  {msg}")

def send_telegram_message(message):
    """Send HTML-formatted message to Telegram channel safely in the background."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    import threading
    def _send():
        try:
            import requests
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML"
            }
            resp = requests.post(url, json=payload, timeout=5)
            if resp.status_code != 200:
                print(f"Telegram send failed: {resp.text}")
        except Exception as e:
            print(f"Telegram error: {e}")
            
    threading.Thread(target=_send, daemon=True).start()

def now_time():
    return datetime.now().strftime("%H:%M:%S")

def now_hm():
    return datetime.now().strftime("%H:%M")

def time_ge(a, b):
    """True if time string a >= b (HH:MM or HH:MM:SS)"""
    return a[:5] >= b[:5]

def get_live_nifty():
    """Fetch live NIFTY spot LTP from OpenAlgo."""
    try:
        resp = client.quotes(symbol="NIFTY", exchange="NSE")
        # OpenAlgo returns {'status': 'success', 'data': {'ltp': ...}}
        if isinstance(resp, dict) and resp.get('status') == 'success':
            return round(float(resp['data']['ltp']), 2)
        # fallback: some versions return list or direct value
        if isinstance(resp, (int, float)):
            return round(float(resp), 2)
    except Exception as e:
        log(f"WARN: quote fetch failed: {e}")
    return None

def build_angel_symbol(strike, expiry_date_str, opt_type):
    """
    Convert to Angel One option symbol format.
    expiry_date_str: YYYYMMDD  e.g. "20260529"
    Angel One format: NIFTY29MAY2523500CE
      = NIFTY + DD + MMM + YY + STRIKE + CE/PE
    """
    dt   = pd.Timestamp(expiry_date_str)
    yy   = dt.strftime("%y")       # 25
    mmm  = dt.strftime("%b").upper()  # MAY
    dd   = dt.strftime("%d")       # 29
    return f"NIFTY{dd}{mmm}{yy}{strike}{opt_type}"

def get_active_expiry_date_from_openalgo():
    """
    Dynamically fetch the closest active NIFTY option expiry date from OpenAlgo.
    This automatically handles trading holidays (like Bakri Id on 28-May-2026).
    """
    try:
        url = f"{OPENALGO_HOST}/api/v1/instruments?apikey={OPENALGO_API_KEY}&exchange=NFO"
        import requests
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            instruments = data.get("data", []) if isinstance(data, dict) else data
            
            # Extract unique NIFTY expiry dates
            expiries = set()
            for inst in instruments:
                if not isinstance(inst, dict):
                    continue
                if inst.get("name") == "NIFTY" and inst.get("instrumenttype") in ["CE", "PE"]:
                    exp_str = inst.get("expiry") # e.g. "26-MAY-26"
                    if exp_str:
                        expiries.add(exp_str)
            
            if not expiries:
                return None
                
            # Convert to pandas Timestamps or datetime to find the closest one
            today = pd.Timestamp(date.today().strftime("%Y-%m-%d"))
            valid_expiries = []
            for exp in expiries:
                try:
                    dt = pd.Timestamp(exp)
                    if dt >= today:
                        valid_expiries.append((dt, exp))
                except:
                    continue
            
            if not valid_expiries:
                return None
                
            # Sort by date and get the closest one
            valid_expiries.sort(key=lambda x: x[0])
            closest_dt, closest_exp_str = valid_expiries[0]
            
            # Format as YYYYMMDD
            return closest_dt.strftime("%Y%m%d")
    except Exception as e:
        print(f"WARN: Failed to fetch expiry dynamically from OpenAlgo: {e}")
    return None

def get_expiry_date(date_str):
    """
    Get current weekly expiry date (next Thursday from today).
    For Angel One: NIFTY weekly expires every Thursday.
    But now enhanced to dynamically resolve from OpenAlgo if available to handle holidays!
    """
    # 1. Try to get it dynamically from OpenAlgo
    dynamic_expiry = get_active_expiry_date_from_openalgo()
    if dynamic_expiry:
        return dynamic_expiry
        
    # 2. Fallback to next Thursday calculation
    today = pd.Timestamp(date_str)
    days_ahead = (3 - today.weekday()) % 7   # 3 = Thursday
    if days_ahead == 0:
        days_ahead = 0
    expiry = today + pd.Timedelta(days=days_ahead)
    return expiry.strftime("%Y%m%d")

def place_order(symbol, action, qty):
    """Place order via OpenAlgo. Returns order_id or None."""
    if PAPER_TRADE:
        log(f"[PAPER] {action} {qty} x {symbol}  @ MARKET")
        return f"PAPER_{datetime.now().strftime('%H%M%S')}"
    try:
        resp = client.placeorder(
            symbol=symbol,
            exchange="NFO",
            action=action,         # "BUY" or "SELL"
            quantity=qty,
            price_type="MARKET",
            product="NRML",        # NRML = no broker auto-squareoff at 15:15
        )
        log(f"ORDER placed: {action} {qty}x{symbol}  -> {resp}")
        if isinstance(resp, dict):
            return resp.get('orderid') or resp.get('data', {}).get('orderid')
        return str(resp)
    except Exception as e:
        log(f"ERROR placing order: {e}")
        return None

def git_sync_log():
    """Sync the trade log CSV file to GitHub in the background."""
    def _sync():
        try:
            import subprocess
            log("Syncing trade log to GitHub...")
            subprocess.run(["git", "add", "data/paper_trade_log.csv"], check=True, capture_output=True)
            msg = f"chore: auto update trade log at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            subprocess.run(["git", "commit", "-m", msg], check=True, capture_output=True)
            subprocess.run(["git", "push", "origin", "main"], check=True, capture_output=True)
            log("GitHub sync completed successfully! 🐙")
        except Exception as e:
            log(f"Git sync failed: {e}")
            
    import threading
    threading.Thread(target=_sync, daemon=True).start()

def write_log(row):
    """Append trade row to CSV log."""
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    fieldnames = ['date','signal_time','entry_time','symbol','strike','opt_type',
                  'entry_price','exit_time','exit_price','result','pnl_pts',
                  'pnl_rs','lot_size','paper_trade','gap','P','R1','S1','SL','remark']
    write_header = not os.path.exists(LOG_FILE)
    with open(LOG_FILE, 'a', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            w.writeheader()
        w.writerow(row)
    log(f"Trade logged → {LOG_FILE}")
    git_sync_log()


# ── Pivot calculation from yesterday ──────────────────────────────────────
today_str   = date.today().strftime("%Y%m%d")
today_dt    = pd.Timestamp(today_str)

# Self-healing auto-downloader on startup to prevent missing data gaps
try:
    print("\n[STARTUP] Running self-healing NIFTY spot database sync...")
    from download_nse_data import download_nifty_spot
    sync_success = download_nifty_spot()
    if sync_success:
        print("[STARTUP] NIFTY spot data synced successfully!\n")
    else:
        print("[STARTUP] WARN: NIFTY spot data sync returned False. Running with local data.\n")
except Exception as e:
    print(f"[STARTUP] WARN: Failed to run auto-downloader on startup: {e}. Running with local data.\n")

all_dates   = list_trading_dates()
load_live_status()

print()
print("=" * 60)
print("  NIFTY Pivot Gap - Paper Trade (OpenAlgo + Angel One)")
print(f"  Date  : {today_str}  ({today_dt.day_name()})")
print(f"  Mode  : {'PAPER (no real orders)' if PAPER_TRADE else '*** LIVE TRADING ***'}")
print("=" * 60)

mode_str = "PAPER (Simulated)" if PAPER_TRADE else "LIVE TRADING ⚠️"
send_telegram_message(
    f"🚀 <b>NIFTY Pivot Gap Strategy Started</b>\n"
    f"📅 Date: {today_str} ({today_dt.day_name()})\n"
    f"⚙️ Mode: <b>{mode_str}</b>\n"
    f"💼 Lot Size: {LOT_SIZE} (Buy: {LOT_SIZE*3} = 3 lots | Sell: {LOT_SIZE} = 1 lot)"
)

# Skip Thursday
if today_dt.weekday() == 3:
    log("NO TRADE — Thursday is expiry day (0DTE skip rule)")
    update_live_status("NO_TRADE", "NO TRADE - Thursday expiry day (0DTE skip rule)")
    sys.exit(0)

# Skip weekends
if today_dt.weekday() >= 5:
    log("NO TRADE — Today is a weekend.")
    update_live_status("NO_TRADE", "NO TRADE - Weekend.")
    sys.exit(0)

# Find the latest trading date in our database that is before today_str
past_dates = [d for d in all_dates if d < today_str]
if not past_dates:
    log("ERROR: No historical trading dates found in the database to calculate pivots.")
    sys.exit(1)

prev_date = past_dates[-1]
prev_dt = pd.Timestamp(prev_date)
gap_days = (today_dt - prev_dt).days
if gap_days > 4:
    warn_msg = f"⚠️ <b>WARNING: Pivot Source Date is {gap_days} days old!</b>\n• Pivot calculated from: <code>{prev_date}</code>\n• Today's Date: <code>{today_str}</code>\n\nPlease double check if yesterday was a holiday or if data is missing!"
    log(f"WARN: Pivot source date {prev_date} is {gap_days} days old!")
    send_telegram_message(warn_msg)

log(f"Loading pivots from {prev_date}...")

prev_df = load_spot_data(prev_date, "NIFTY")
if prev_df is None or prev_df.empty:
    log(f"ERROR: No historical data for {prev_date}")
    update_live_status("ERROR", f"ERROR: No historical data for {prev_date}")
    sys.exit(1)

prev_tr    = prev_df[(prev_df['time'] >= '09:15:00') & (prev_df['time'] <= '15:30:00')]
H = prev_tr['price'].max(); L = prev_tr['price'].min(); C = prev_tr['price'].iloc[-1]
P  = round((H+L+C)/3, 2)
R1 = round(2*P-L, 2);  S1 = round(2*P-H, 2)
R2 = round(P+(H-L), 2); S2 = round(P-(H-L), 2)
prev_close = round(C, 2)

print(f"\n  Pivot Levels (from {prev_date}):")
print(f"    R2 = {R2}")
print(f"    R1 = {R1}  <- CE Target")
print(f"    P  = {P}   <- Signal level")
print(f"    S1 = {S1}  <- PE Target")
print(f"    S2 = {S2}")
print(f"    Prev close = {prev_close}")

update_live_status("WAIT_MARKET", f"Pivots loaded from {prev_date}. Waiting for market open...")
send_telegram_message(
    f"📊 <b>Pivot Levels Calculated (from {prev_date})</b>\n"
    f"• <b>R2:</b> {R2}\n"
    f"• <b>R1:</b> {R1} (CE Target 🎯)\n"
    f"• <b>P:</b> {P} (Signal Trigger ⚡)\n"
    f"• <b>S1:</b> {S1} (PE Target 🎯)\n"
    f"• <b>S2:</b> {S2}\n"
    f"• <b>Prev Close:</b> {prev_close}\n\n"
    f"⏳ Waiting for Market Open at 09:15..."
)

# ── Wait for market open ───────────────────────────────────────────────────
MARKET_OPEN = "09:15"
log("Waiting for market open (09:15)...")
while now_hm() < MARKET_OPEN:
    update_live_status("WAIT_MARKET", f"Waiting for market open (09:15)... Local time: {now_time()}")
    time.sleep(10)

# ── Get today's open and check gap ────────────────────────────────────────
open_price = None

# First, try to fetch the actual 09:15:00 open price from today's CSV file if we started late or if it is already available
today_csv = os.path.join(os.path.dirname(__file__), "data", f"{today_str}_NIFTY.csv")
if os.path.exists(today_csv):
    try:
        today_df = pd.read_csv(today_csv)
        if not today_df.empty:
            open_price = round(float(today_df.iloc[0]['price']), 2)
            log(f"Loaded actual 09:15 open price from today's CSV: {open_price}")
    except Exception as e:
        print(f"WARN: Failed to read open price from today's CSV: {e}")

if not open_price:
    time.sleep(5)  # wait a few seconds for first tick
    for attempt in range(10):
        open_price = get_live_nifty()
        if open_price:
            break
        update_live_status("WAIT_MARKET", f"Waiting for first tick... Attempt {attempt+1}/10")
        time.sleep(3)

if not open_price:
    log("ERROR: Could not fetch opening price. Check OpenAlgo connection.")
    update_live_status("ERROR", "ERROR: Could not fetch opening price. Check OpenAlgo connection.")
    sys.exit(1)

gap = round(open_price - prev_close, 2)
log(f"Today open={open_price}  Prev close={prev_close}  Gap={'+' if gap>=0 else ''}{gap} pts")

# -- Determine direction ----------------------------------------------------
thresh = abs(GAP_THRESH)
if gap > thresh and open_price >= P:
    direction='LONG';  opt_type='CE'; strat='A - Gap Up -> ATM CE Buy'
    target_spot=R1;    sl_spot=round(P-SL_PTS, 2)
elif gap < -thresh and open_price < P:
    direction='SHORT'; opt_type='PE'; strat='B - Gap Down -> ATM PE Buy'
    target_spot=S1;    sl_spot=round(P+SL_PTS, 2)
else:
    reason = f"Gap only {abs(gap):.0f}pts (<{thresh})" if abs(gap)<=thresh \
             else f"Gap {'up' if gap>0 else 'down'} but open {'below' if gap>0 else 'above'} P"
    log(f"NO TRADE - {reason}")
    update_live_status("NO_TRADE", f"NO TRADE - {reason}")
    send_telegram_message(
        f"⚠️ <b>No Trading Today! (BASE Strategy Skip)</b>\n"
        f"• <b>NIFTY Open:</b> {open_price}\n"
        f"• <b>Gap:</b> {gap:+.2f} pts\n"
        f"• <b>Reason:</b> {reason}\n\n"
        f"💤 <i>Trading engine will now shut down cleanly for the day.</i>"
    )
    sys.exit(0)

log(f"Strategy : {strat}")
log(f"Watching : P={P} +/- {P_TOL}  ->  range [{P-P_TOL}, {P+P_TOL}]")
log(f"Target   : {target_spot}  |  SL: {sl_spot}  |  Cutoff: {ENTRY_CUTOFF}")

send_telegram_message(
    f"📈 <b>Market Opened & Gap Identified!</b>\n"
    f"• <b>NIFTY Open:</b> {open_price}\n"
    f"• <b>Prev Close:</b> {prev_close}\n"
    f"• <b>Gap:</b> {gap:+.2f} pts ({'Gap Up 🟢' if gap > 0 else 'Gap Down 🔴'})\n\n"
    f"🎯 <b>Strategy Selected: Option Buying (BASE)</b>\n"
    f"• <b>Direction:</b> {direction} ({opt_type})\n"
    f"• <b>Trigger Level (P):</b> {P} (tolerance ±{P_TOL})\n"
    f"• <b>Target Spot:</b> {target_spot}\n"
    f"• <b>Stop Loss Spot:</b> {sl_spot}\n\n"
    f"⚡ <i>Monitoring spot price for Pivot test...</i>"
)

update_live_status("SCANNING", f"Strategy: {strat}. Scanning for P-touch signal...")

# ── Exit Handlers ─────────────────────────────────────────────────────────
def exit_base(res):
    global base_active, base_exit_time, base_exit_price, base_pnl_pts, base_pnl_rs, base_result, base_status_desc, base_ltp
    base_exit_time = now_time()
    base_result = res
    base_status_desc = f"Exiting BASE Buy position ({res})..."
    update_live_status("IN_TRADE", base_status_desc, get_live_nifty())
    
    log(f"PLACING BASE EXIT ORDER FOR {base_symbol} (res: {res})...")
    place_order(base_symbol, "SELL", LOT_SIZE * 3)  # 3 lots = 195 shares
    
    # Get option exit price
    try:
        base_q = client.quotes(symbol=base_symbol, exchange="NFO")
        if isinstance(base_q, dict) and base_q.get('status') == 'success':
            base_exit_price = round(float(base_q['data']['ltp']), 2)
    except:
        pass
        
    if base_exit_price is None:
        if res == "TARGET":
            base_exit_price = base_entry_price + abs(base_target_spot - base_spot_at_entry) * 0.5 if (base_entry_price and base_target_spot and base_spot_at_entry) else 100.0
        elif res == "SL":
            base_exit_price = base_entry_price - abs(base_sl_spot - base_spot_at_entry) * 0.5 if (base_entry_price and base_sl_spot and base_spot_at_entry) else 50.0
        else:
            base_exit_price = base_entry_price if base_entry_price else 100.0
        log(f"WARN: BASE exit quote fetch failed, using estimate {base_exit_price:.2f}")
        
    base_pnl_pts = round(base_exit_price - base_entry_price, 2) if (base_exit_price and base_entry_price) else 0.0
    base_pnl_rs = round(base_pnl_pts * (LOT_SIZE * 3), 2)  # 3 lots = 195
    
    log(f"BASE CLOSED | Entry: {base_entry_price} | Exit: {base_exit_price} | P&L: Rs. {base_pnl_rs:+.2f}")
    pnl_sign = "🟢" if base_pnl_rs >= 0 else "🔴"
    send_telegram_message(
        f"🏁 <b>Strategy 1: BASE Option BUY Exit Executed!</b> {pnl_sign}\n"
        f"• <b>Reason:</b> {base_result} 🚀\n"
        f"• <b>Symbol:</b> <code>{base_symbol}</code>\n"
        f"• <b>Entry Option Price:</b> ₹{base_entry_price}\n"
        f"• <b>Exit Option Price:</b> ₹{base_exit_price}\n"
        f"• <b>Net P&L Points:</b> {base_pnl_pts:+.2f} pts\n"
        f"• <b>Net P&L Rupees:</b> <b>₹{base_pnl_rs:+.2f}</b>\n"
        f"• <b>Time:</b> {base_exit_time}"
    )
    
    # Write to CSV Log
    write_log({
        'date':        today_str,
        'signal_time': base_signal_time,
        'entry_time':  base_entry_time,
        'symbol':      base_symbol,
        'strike':      base_strike,
        'opt_type':    base_opt_type,
        'entry_price': base_entry_price,
        'exit_time':   base_exit_time,
        'exit_price':  base_exit_price,
        'result':      base_result,
        'pnl_pts':     base_pnl_pts,
        'pnl_rs':      base_pnl_rs,
        'lot_size':    LOT_SIZE * 3,  # 3 lots = 195 shares
        'paper_trade': PAPER_TRADE,
        'gap':         gap,
        'P':           P,
        'R1':          R1,
        'S1':          S1,
        'SL':          base_sl_spot,
        'remark':      f"BASE Option Buying ({base_opt_type}) - {base_result} Exit"
    })
    
    base_active = False

def exit_strangle(res):
    global strangle_active, strangle_exit_time, strangle_ce_exit_price, strangle_pe_exit_price, strangle_pnl_pts, strangle_pnl_rs, strangle_result, strangle_status_desc, strangle_ce_ltp, strangle_pe_ltp
    strangle_exit_time = now_time()
    strangle_result = res
    strangle_status_desc = f"Exiting Strangle sold positions ({res})..."
    update_live_status("IN_TRADE", strangle_status_desc, get_live_nifty())
    
    log(f"PLACING STRANGLE BUY EXIT ORDERS FOR {strangle_ce_symbol} AND {strangle_pe_symbol}...")
    place_order(strangle_ce_symbol, "BUY", LOT_SIZE)
    place_order(strangle_pe_symbol, "BUY", LOT_SIZE)
    
    # Get option exit prices
    try:
        ce_q = client.quotes(symbol=strangle_ce_symbol, exchange="NFO")
        if isinstance(ce_q, dict) and ce_q.get('status') == 'success':
            strangle_ce_exit_price = round(float(ce_q['data']['ltp']), 2)
    except:
        pass
        
    try:
        pe_q = client.quotes(symbol=strangle_pe_symbol, exchange="NFO")
        if isinstance(pe_q, dict) and pe_q.get('status') == 'success':
            strangle_pe_exit_price = round(float(pe_q['data']['ltp']), 2)
    except:
        pass
        
    if strangle_ce_exit_price is None:
        strangle_ce_exit_price = strangle_ce_ltp if strangle_ce_ltp else strangle_ce_entry_price
    if strangle_pe_exit_price is None:
        strangle_pe_exit_price = strangle_pe_ltp if strangle_pe_ltp else strangle_pe_entry_price
        
    strangle_pnl_pts = round(strangle_ce_entry_price - strangle_ce_exit_price + strangle_pe_entry_price - strangle_pe_exit_price, 2)
    strangle_pnl_rs = round(strangle_pnl_pts * LOT_SIZE, 2)
    
    log(f"STRANGLE CLOSED | CE Entry: {strangle_ce_entry_price} Exit: {strangle_ce_exit_price} | PE Entry: {strangle_pe_entry_price} Exit: {strangle_pe_exit_price} | P&L: Rs. {strangle_pnl_rs:+.2f}")
    pnl_sign = "🟢" if strangle_pnl_rs >= 0 else "🔴"
    send_telegram_message(
        f"🏁 <b>Strategy 2: Strangle SELL Exit Executed!</b> {pnl_sign}\n"
        f"• <b>Reason:</b> {strangle_result} 🚀\n"
        f"• <b>CE Symbol:</b> <code>{strangle_ce_symbol}</code>\n"
        f"• <b>PE Symbol:</b> <code>{strangle_pe_symbol}</code>\n"
        f"• <b>CE Entry/Exit:</b> ₹{strangle_ce_entry_price} / ₹{strangle_ce_exit_price}\n"
        f"• <b>PE Entry/Exit:</b> ₹{strangle_pe_entry_price} / ₹{strangle_pe_exit_price}\n"
        f"• <b>Combined P&L Points:</b> {strangle_pnl_pts:+.2f} pts\n"
        f"• <b>Net P&L Rupees:</b> <b>₹{strangle_pnl_rs:+.2f}</b>\n"
        f"• <b>Time:</b> {strangle_exit_time}"
    )
    
    # Log Strangle to CSV Log
    write_log({
        'date':        today_str,
        'signal_time': strangle_entry_time,
        'entry_time':  strangle_entry_time,
        'symbol':      f"STRANGLE_{strangle_pe_strike}PE_{strangle_ce_strike}CE",
        'strike':      f"{strangle_pe_strike}/{strangle_ce_strike}",
        'opt_type':    "STRANGLE",
        'entry_price': strangle_ce_entry_price + strangle_pe_entry_price,
        'exit_time':   strangle_exit_time,
        'exit_price':  strangle_ce_exit_price + strangle_pe_exit_price,
        'result':      strangle_result,
        'pnl_pts':     strangle_pnl_pts,
        'pnl_rs':      strangle_pnl_rs,
        'lot_size':    LOT_SIZE,
        'paper_trade': PAPER_TRADE,
        'gap':         gap,
        'P':           P,
        'R1':          R1,
        'S1':          S1,
        'SL':          f"-{strangle_combined_sl}",
        'remark':      f"Strangle Short Selling (ATM±100) - {strangle_result} Exit"
    })
    
    strangle_active = False

# ── Main Concurrent Loop ──────────────────────────────────────────────────
log("Entering Main Concurrent Execution Loop...")

strangle_entered = False
base_entered = False
base_signal_bar = None

# Initialize BASE targets/SLs
base_opt_type = opt_type
base_target_spot = target_spot
base_sl_spot = sl_spot
live_spot = open_price

# Track 1-min bar high/low for BASE touch detection
bar_minute = None
bar_open = None
bar_high = None
bar_low = None

while True:
    current_time_str = now_time()
    current_hm = current_time_str[:5]
    
    # EOD Exit Check
    if time_ge(current_time_str, EOD_EXIT + ":00"):
        log(f"EOD EXIT TRIGGERED AT {current_time_str}")
        send_telegram_message(
            f"🕒 <b>EOD Exit Triggered!</b> ({current_time_str})\n"
            f"Closing any remaining active positions cleanly..."
        )
        if strangle_active:
            exit_strangle("EOD")
        if base_active:
            exit_base("EOD")
        break
        
    # Fetch live Nifty spot price
    live_spot = get_live_nifty()
    if live_spot is None:
        log("WARN: Spot price fetch failed. Retrying in loop...")
        time.sleep(2)
        continue
        
    # ── 1. STRANGLE ENTRY EXECUTION (09:16:02) ──
    if not strangle_entered and not strangle_active:
        if time_ge(current_time_str, "09:16:02"):
            log("Executing Strategy 2: Short Strangle...")
            spot_at_0916 = live_spot
            strangle_ce_strike = int(round(spot_at_0916 / 50) * 50) + 100
            strangle_pe_strike = int(round(spot_at_0916 / 50) * 50) - 100
            
            expiry_str = get_expiry_date(today_str)
            strangle_ce_symbol = build_angel_symbol(strangle_ce_strike, expiry_str, "CE")
            strangle_pe_symbol = build_angel_symbol(strangle_pe_strike, expiry_str, "PE")
            
            log(f"Strangle Entry Spot: {spot_at_0916}")
            log(f"Strangle CE: Strike {strangle_ce_strike} Symbol {strangle_ce_symbol}")
            log(f"Strangle PE: Strike {strangle_pe_strike} Symbol {strangle_pe_symbol}")
            
            strangle_status_desc = "Placing Strangle SELL orders..."
            update_live_status("SCANNING", strangle_status_desc, live_spot)
            
            # Place Sell Orders (1 lot each, LOT_SIZE=65)
            ce_order_id = place_order(strangle_ce_symbol, "SELL", LOT_SIZE)
            pe_order_id = place_order(strangle_pe_symbol, "SELL", LOT_SIZE)
            
            if ce_order_id and pe_order_id:
                strangle_entry_time = now_time()
                strangle_active = True
                strangle_entered = True
                
                # Fetch entry premium prices
                try:
                    ce_resp = client.quotes(symbol=strangle_ce_symbol, exchange="NFO")
                    if isinstance(ce_resp, dict) and ce_resp.get('status') == 'success':
                        strangle_ce_entry_price = round(float(ce_resp['data']['ltp']), 2)
                except:
                    pass
                
                try:
                    pe_resp = client.quotes(symbol=strangle_pe_symbol, exchange="NFO")
                    if isinstance(pe_resp, dict) and pe_resp.get('status') == 'success':
                        strangle_pe_entry_price = round(float(pe_resp['data']['ltp']), 2)
                except:
                    pass
                    
                # fallback if quotes fail
                if strangle_ce_entry_price is None:
                    strangle_ce_entry_price = 100.0 # fallback
                if strangle_pe_entry_price is None:
                    strangle_pe_entry_price = 100.0 # fallback
                    
                strangle_status_desc = f"Strangle active: Sold CE={strangle_ce_entry_price} PE={strangle_pe_entry_price} at {strangle_entry_time}"
                log(f"STRANGLE OPENED ce_entry={strangle_ce_entry_price} pe_entry={strangle_pe_entry_price}")
                send_telegram_message(
                    f"🛒 <b>Strategy 2: Strangle SELL Entry Executed!</b> 🟢\n"
                    f"• <b>CE Symbol:</b> <code>{strangle_ce_symbol}</code> (Strike: {strangle_ce_strike})\n"
                    f"• <b>PE Symbol:</b> <code>{strangle_pe_symbol}</code> (Strike: {strangle_pe_strike})\n"
                    f"• <b>Quantity:</b> {LOT_SIZE} (1 Lot each)\n"
                    f"• <b>CE Entry Price:</b> ₹{strangle_ce_entry_price}\n"
                    f"• <b>PE Entry Price:</b> ₹{strangle_pe_entry_price}\n"
                    f"• <b>Combined Premium:</b> ₹{round(strangle_ce_entry_price + strangle_pe_entry_price, 2)}\n"
                    f"• <b>Max Strangle SL:</b> ₹7,000 Loss\n"
                    f"• <b>Time:</b> {strangle_entry_time}"
                )
            else:
                strangle_status_desc = "ERROR: Strangle order placement failed!"
                log("ERROR: Strangle order placement failed. Strangle skipped.")
                send_telegram_message(
                    f"⚠️ <b>Strategy 2: Strangle Entry FAILED!</b> 🚨\n"
                    f"• <b>CE:</b> {strangle_ce_symbol}\n"
                    f"• <b>PE:</b> {strangle_pe_symbol}\n"
                    f"• <b>Status:</b> Order placement via OpenAlgo returned error or empty response. Strangle skipped."
                )
                strangle_entered = True # mark as processed to prevent infinite attempts

    # ── 2. BASE SIGNAL SCANNING & delayed entry (before 13:00) ──
    if not base_entered and not base_active:
        if current_hm < ENTRY_CUTOFF:
            # Update 1-min candle highs and lows
            if bar_minute != current_hm:
                bar_minute = current_hm
                bar_open = live_spot
                bar_high = live_spot
                bar_low = live_spot
            else:
                if live_spot > bar_high: bar_high = live_spot
                if live_spot < bar_low:  bar_low  = live_spot
                
            touches_p = (bar_low <= P + P_TOL) and (bar_high >= P - P_TOL)
            base_status_desc = f"Scanning for P-touch. Spot: {live_spot} | P: {P} (Bar H: {bar_high} L: {bar_low})"
            
            if touches_p and base_signal_bar is None:
                base_signal_bar = {
                    'time': now_time(),
                    'minute': current_hm,
                    'high': bar_high,
                    'low': bar_low
                }
                base_signal_time = base_signal_bar['time']
                
                # Entry time = next minute + 2 seconds (Rule 8)
                sig_dt = datetime.now().replace(second=0, microsecond=0)
                entry_dt = sig_dt + pd.Timedelta(minutes=1, seconds=2)
                base_planned_entry_time = entry_dt.strftime("%H:%M:%S")
                
                log(f"BASE SIGNAL DETECTED at {base_signal_time}! P={P} touched (Bar H={bar_high} L={bar_low}). Waiting for entry at {base_planned_entry_time}...")
                
                # Wait loop for delayed entry
                while now_time() < base_planned_entry_time:
                    live_spot = get_live_nifty() or live_spot
                    base_status_desc = f"Signal at {base_signal_time}. Waiting for entry at {base_planned_entry_time}..."
                    update_live_status("SCANNING", base_status_desc, live_spot)
                    time.sleep(1)
                    
                # Perform entry
                live_spot = get_live_nifty() or live_spot
                if time_ge(now_time(), ENTRY_CUTOFF + ":00"):
                    log(f"BASE Entry time {now_time()} >= Cutoff {ENTRY_CUTOFF}. Skip BASE trade.")
                    base_result = "SKIP"
                    base_entered = True
                    base_status_desc = "BASE skipped: Entry would be after cutoff."
                else:
                    base_spot_at_entry = live_spot
                    base_strike = calculate_strike(base_spot_at_entry, base_opt_type, "NIFTY", "atm")
                    expiry_str = get_expiry_date(today_str)
                    base_symbol = build_angel_symbol(base_strike, expiry_str, base_opt_type)
                    
                    log(f"BASE Entry: spot={base_spot_at_entry} strike={base_strike} symbol={base_symbol}")
                    base_status_desc = f"Placing BASE BUY order for {base_symbol}..."
                    update_live_status("SCANNING", base_status_desc, live_spot)
                    
                    # Place Buy Order (3 lots, 195 shares) — LOCKED v4.0
                    base_order_id = place_order(base_symbol, "BUY", LOT_SIZE * 3)
                    
                    if base_order_id:
                        base_entry_time = now_time()
                        base_active = True
                        base_entered = True
                        
                        # Get entry option price
                        try:
                            base_q = client.quotes(symbol=base_symbol, exchange="NFO")
                            if isinstance(base_q, dict) and base_q.get('status') == 'success':
                                base_entry_price = round(float(base_q['data']['ltp']), 2)
                        except:
                            pass
                            
                        if base_entry_price is None:
                            base_entry_price = 100.0 # fallback
                            
                        base_status_desc = f"BASE active: Bought {base_symbol} at Rs. {base_entry_price} at {base_entry_time}"
                        log(f"BASE OPTION BUY OPENED entry_price={base_entry_price}")
                        send_telegram_message(
                            f"🛒 <b>Strategy 1: BASE Option BUY Entry Executed!</b> 🟢\n"
                            f"• <b>Symbol:</b> <code>{base_symbol}</code> (Strike: {base_strike} {base_opt_type})\n"
                            f"• <b>Quantity:</b> {LOT_SIZE * 3} (3 Lots — LOCKED v4.0)\n"
                            f"• <b>NIFTY Entry Spot:</b> {base_spot_at_entry}\n"
                            f"• <b>Option Entry Price:</b> ₹{base_entry_price}\n"
                            f"• <b>Target Spot Level:</b> {base_target_spot}\n"
                            f"• <b>SL Spot Level:</b> {base_sl_spot}\n"
                            f"• <b>Time:</b> {base_entry_time}"
                        )
                    else:
                        base_status_desc = "ERROR: BASE Buy order placement failed!"
                        log("ERROR: BASE Buy order placement failed. BASE skipped.")
                        send_telegram_message(
                            f"⚠️ <b>Strategy 1: BASE Entry FAILED!</b> 🚨\n"
                            f"• <b>Symbol:</b> {base_symbol}\n"
                            f"• <b>Status:</b> Order placement via OpenAlgo returned error or empty response. BASE skipped."
                        )
                        base_entered = True
                        base_result = "ERROR"
        else:
            # Cutoff reached, no P-touch happened
            base_result = "SKIP"
            base_entered = True
            base_status_desc = "BASE skipped: Pivot not touched before 13:00 cutoff."
            log("No P-touch signal before 13:00. Strategy 1 (Option Buy) skipped for today.")
            send_telegram_message(
                f"⚠️ <b>Strategy 1: BASE Option Buy Skipped Today</b>\n"
                f"• <b>Reason:</b> NIFTY Spot did not touch the pivot level {P} before the 13:00 cutoff time."
            )

    # ── 3. MONITOR ACTIVE POSITIONS (Exits & live P&Ls) ──
    
    # Monitor BASE Position
    if base_active:
        try:
            base_q = client.quotes(symbol=base_symbol, exchange="NFO")
            if isinstance(base_q, dict) and base_q.get('status') == 'success':
                base_ltp = round(float(base_q['data']['ltp']), 2)
        except:
            pass
            
        hit = False
        if base_opt_type == 'CE':
            if live_spot >= base_target_spot:
                base_result = "TARGET"; hit = True; log(f"BASE Target Hit! Spot={live_spot} >= {base_target_spot}")
            elif live_spot <= base_sl_spot:
                base_result = "SL";     hit = True; log(f"BASE Stop Loss Hit! Spot={live_spot} <= {base_sl_spot}")
        else:
            if live_spot <= base_target_spot:
                base_result = "TARGET"; hit = True; log(f"BASE Target Hit! Spot={live_spot} <= {base_target_spot}")
            elif live_spot >= base_sl_spot:
                base_result = "SL";     hit = True; log(f"BASE Stop Loss Hit! Spot={live_spot} >= {base_sl_spot}")
                
        if hit:
            exit_base(base_result)
            
    # Monitor Strangle Position
    if strangle_active:
        try:
            ce_q = client.quotes(symbol=strangle_ce_symbol, exchange="NFO")
            if isinstance(ce_q, dict) and ce_q.get('status') == 'success':
                strangle_ce_ltp = round(float(ce_q['data']['ltp']), 2)
        except:
            pass
            
        try:
            pe_q = client.quotes(symbol=strangle_pe_symbol, exchange="NFO")
            if isinstance(pe_q, dict) and pe_q.get('status') == 'success':
                strangle_pe_ltp = round(float(pe_q['data']['ltp']), 2)
        except:
            pass
            
        ce_price = strangle_ce_ltp if strangle_ce_ltp else strangle_ce_entry_price
        pe_price = strangle_pe_ltp if strangle_pe_ltp else strangle_pe_entry_price
        
        current_strangle_pnl = (strangle_ce_entry_price - ce_price + strangle_pe_entry_price - pe_price) * LOT_SIZE
        
        # Check combined SL
        if current_strangle_pnl <= -strangle_combined_sl:
            log(f"STRANGLE COMBINED SL HIT! P&L: Rs. {current_strangle_pnl:.2f} <= -Rs. {strangle_combined_sl}")
            exit_strangle("SL")

    # ── 4. GLOBAL STATUS UPDATE & LOOP SLEEP ──
    global_status = "SCANNING"
    global_desc = ""
    if base_active or strangle_active:
        global_status = "IN_TRADE"
        active_strats = []
        if base_active: active_strats.append("BASE")
        if strangle_active: active_strats.append("Strangle")
        global_desc = f"Active trades: {', '.join(active_strats)}. Spot: {live_spot}"
    else:
        if strangle_entered and base_entered:
            global_status = "CLOSED"
            global_desc = "All trades completed for today."
        else:
            global_status = "SCANNING"
            global_desc = f"Scanning. Spot: {live_spot} | P: {P}"
            
    update_live_status(global_status, global_desc, live_spot)
    
    # Check if all completed and closed
    if strangle_entered and base_entered and not strangle_active and not base_active:
        log("All strategies executed and closed for the day. Exiting loop.")
        break
        
    # Dynamic loop sleep:
    # 1. Near Strategy 2 entry time (09:16:02), run loop every 0.5s to ensure execution within 1-2s.
    # 2. When positions are active, monitor every 2s for precise high-frequency stop loss exits.
    # 3. Idle monitoring runs at the configured POLL_EXIT_SEC (15s) to conserve API limits.
    current_time_str = now_time()
    sleep_time = POLL_EXIT_SEC
    if not strangle_entered and "09:15:30" <= current_time_str <= "09:16:05":
        sleep_time = 0.5
    elif base_active or strangle_active:
        sleep_time = 2.0
        
    time.sleep(sleep_time)

update_live_status("CLOSED", "Closed. Strategy run finished.", live_spot)

# Send Final Daily Summary
summary = "🏁 <b>Trading Day Summary</b>\n"
if base_entered:
    if base_result in ["TARGET", "SL", "EOD"]:
        pnl_sign = "🟢" if base_pnl_rs >= 0 else "🔴"
        summary += f"• <b>Strategy 1 (BASE):</b> P&L = <b>₹{base_pnl_rs:+.2f}</b> ({base_result} {pnl_sign})\n"
    else:
        summary += f"• <b>Strategy 1 (BASE):</b> {base_result} ⚠️\n"
else:
    summary += "• <b>Strategy 1 (BASE):</b> No trade triggered today.\n"

if strangle_entered:
    if strangle_result in ["SL", "EOD"]:
        pnl_sign = "🟢" if strangle_pnl_rs >= 0 else "🔴"
        summary += f"• <b>Strategy 2 (Strangle):</b> P&L = <b>₹{strangle_pnl_rs:+.2f}</b> ({strangle_result} {pnl_sign})\n"
    else:
        summary += f"• <b>Strategy 2 (Strangle):</b> {strangle_result} ⚠️\n"
else:
    summary += "• <b>Strategy 2 (Strangle):</b> No trade triggered today.\n"

send_telegram_message(summary)

log("Done.")

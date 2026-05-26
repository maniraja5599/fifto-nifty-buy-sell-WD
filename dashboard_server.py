import http.server
import socketserver
import json
import os
import sys
import subprocess
import signal
import csv
from datetime import datetime

PORT = 8080
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
STATUS_FILE = os.path.join(DATA_DIR, "live_status.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
LOG_FILE = os.path.join(DATA_DIR, "paper_trade_log.csv")
TERMINAL_LOG = os.path.join(DATA_DIR, "terminal.log")

# Create data directory if it doesn't exist
os.makedirs(DATA_DIR, exist_ok=True)

# Default Config values
DEFAULT_CONFIG = {
    "OPENALGO_HOST": "http://127.0.0.1:5000",
    "OPENALGO_API_KEY": "YOUR_OPENALGO_API_KEY",
    "LOT_SIZE": 65,
    "GAP_THRESH": 30.0,
    "P_TOL": 10.0,
    "SL_PTS": 20.0,
    "ENTRY_CUTOFF": "13:00",
    "EOD_EXIT": "15:20",
    "PAPER_TRADE": True
}

# Ensure config.json exists
if not os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        print(f"Created default config at {CONFIG_FILE}")
    except Exception as e:
        print(f"Error creating default config: {e}")

# Global pointer to the active subprocess
active_process = None
log_file_handle = None

def get_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error reading config: {e}")
    return DEFAULT_CONFIG

def save_config(config_data):
    try:
        # Validate types
        config_data["LOT_SIZE"] = int(config_data.get("LOT_SIZE", 65))
        config_data["GAP_THRESH"] = float(config_data.get("GAP_THRESH", 30.0))
        config_data["P_TOL"] = float(config_data.get("P_TOL", 10.0))
        config_data["SL_PTS"] = float(config_data.get("SL_PTS", 20.0))
        config_data["PAPER_TRADE"] = bool(config_data.get("PAPER_TRADE", True))
        
        with open(CONFIG_FILE, "w") as f:
            json.dump(config_data, f, indent=2)
        return True, "Config saved successfully"
    except Exception as e:
        return False, f"Failed to save config: {e}"

def start_scanner():
    global active_process, log_file_handle
    if active_process is not None and active_process.poll() is None:
        return False, "Scanner is already running"
    
    try:
        # Clear terminal log
        with open(TERMINAL_LOG, "w") as f:
            f.write(f"--- Scanner started by Dashboard at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            
        log_file_handle = open(TERMINAL_LOG, "a", buffering=1) # line buffered
        
        # Spawn subprocess unbuffered
        cmd = [sys.executable, "-u", "18_paper_trade_openalgo.py"]
        active_process = subprocess.Popen(
            cmd,
            cwd=BASE_DIR,
            stdout=log_file_handle,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
        )
        return True, f"Scanner started successfully with PID {active_process.pid}"
    except Exception as e:
        if log_file_handle:
            log_file_handle.close()
            log_file_handle = None
        return False, f"Error starting scanner: {e}"

def stop_scanner():
    global active_process, log_file_handle
    if active_process is None or active_process.poll() is not None:
        # Scanner not running under server, let's try to write stopped status to live_status.json
        write_offline_status()
        return True, "Scanner was not running"
    
    try:
        if os.name == 'nt':
            # On Windows, kill process group or use taskkill
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(active_process.pid)], capture_output=True)
        else:
            active_process.terminate()
            active_process.wait(timeout=5)
            
        if active_process.poll() is None:
            active_process.kill()
            
        active_process = None
        if log_file_handle:
            log_file_handle.write(f"\n--- Scanner stopped by Dashboard at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            log_file_handle.close()
            log_file_handle = None
            
        write_offline_status()
        return True, "Scanner stopped successfully"
    except Exception as e:
        write_offline_status()
        return False, f"Error stopping scanner: {e}"

def write_offline_status():
    try:
        # Update live_status.json to offline state
        status_data = {}
        if os.path.exists(STATUS_FILE):
            try:
                with open(STATUS_FILE, "r") as f:
                    status_data = json.load(f)
            except:
                pass
        
        status_data["status"] = "OFFLINE"
        status_data["status_desc"] = "Scanner is stopped."
        status_data["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # ensure pivots and trade are not null if they were loaded before, but just set state
        with open(STATUS_FILE, "w") as f:
            json.dump(status_data, f, indent=2)
    except Exception as e:
        print(f"Error writing offline status: {e}")

class DashboardRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Disable caching for API responses
        if hasattr(self, 'path') and self.path.startswith("/api/"):
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
        super().end_headers()

    def do_GET(self):
        # Serve root page
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            try:
                with open(os.path.join(BASE_DIR, "dashboard.html"), "rb") as f:
                    self.wfile.write(f.read())
            except Exception as e:
                self.wfile.write(f"Error loading dashboard.html: {e}".encode())
            return
            
        # GET /api/status
        elif self.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            
            # Read status JSON
            status_data = None
            if os.path.exists(STATUS_FILE):
                try:
                    with open(STATUS_FILE, "r") as f:
                        status_data = json.load(f)
                except Exception as e:
                    print(f"Error reading status file: {e}")
            
            # Determine if backend process is actually running
            is_running = False
            global active_process
            if active_process is not None and active_process.poll() is None:
                is_running = True
            
            if not status_data:
                status_data = {
                    "status": "OFFLINE",
                    "status_desc": "Scanner is not running",
                    "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
            
            # 1. Ping OpenAlgo Server Host
            openalgo_online = False
            config = get_config()
            host = config.get("OPENALGO_HOST", "http://127.0.0.1:5000")
            try:
                import urllib.request
                import urllib.error
                req = urllib.request.Request(host)
                with urllib.request.urlopen(req, timeout=0.8) as conn:
                    openalgo_online = True
            except urllib.error.HTTPError:
                openalgo_online = True
            except Exception as e:
                openalgo_online = False
                
            # 2. Determine Data Feed Status
            feed_status = "INACTIVE"
            if is_running:
                if status_data:
                    status_name = status_data.get("status", "")
                    status_desc = status_data.get("status_desc", "")
                    
                    if status_name == "WAIT_MARKET":
                        feed_status = "STANDBY"
                    elif "[Quote Fetch Fail]" in status_desc or "ERROR:" in status_desc:
                        feed_status = "ERROR"
                    else:
                        last_update_str = status_data.get("last_update")
                        if last_update_str:
                            try:
                                last_update_dt = datetime.strptime(last_update_str, "%Y-%m-%d %H:%M:%S")
                                delta = (datetime.now() - last_update_dt).total_seconds()
                                if delta < 45:
                                    feed_status = "ACTIVE"
                                else:
                                    feed_status = "STALE"
                            except:
                                feed_status = "ACTIVE"
                        else:
                            feed_status = "ACTIVE"
                else:
                    feed_status = "STANDBY"
            
            status_data["scanner_running"] = is_running
            status_data["openalgo_online"] = openalgo_online
            status_data["feed_status"] = feed_status
            
            self.wfile.write(json.dumps(status_data).encode())
            return
            
        # GET /api/config
        elif self.path == "/api/config":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(get_config()).encode())
            return
            
        # GET /api/logs
        elif self.path == "/api/logs":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            
            logs = []
            if os.path.exists(LOG_FILE):
                try:
                    with open(LOG_FILE, mode='r', newline='') as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            logs.append(row)
                except Exception as e:
                    print(f"Error reading log file: {e}")
            
            # Reverse to show newest trades first
            logs.reverse()
            
            # Prepend active trades from live_status.json
            if os.path.exists(STATUS_FILE):
                try:
                    with open(STATUS_FILE, "r") as sf:
                        status_data = json.load(sf)
                    
                    active_trades = []
                    
                    # 1. Option Buying (BASE) Active Trade
                    if status_data.get("buying", {}).get("in_trade"):
                        buy_data = status_data["buying"]
                        b_date = status_data.get("date", datetime.now().strftime("%Y%m%d"))
                        b_symbol = buy_data.get("symbol", "BASE")
                        b_entry_time = buy_data.get("entry_time", "-")
                        
                        # Avoid duplicate if already written to CSV
                        already_logged = any(
                            l.get("date") == b_date and 
                            l.get("symbol") == b_symbol and 
                            l.get("entry_time") == b_entry_time 
                            for l in logs
                        )
                        if not already_logged:
                            active_trades.append({
                                "date": b_date,
                                "signal_time": buy_data.get("entry_time", "-"),
                                "entry_time": b_entry_time,
                                "symbol": b_symbol,
                                "strike": str(buy_data.get("strike", "-")),
                                "opt_type": buy_data.get("opt_type", "CE"),
                                "entry_price": str(buy_data.get("entry_price", "0.0")),
                                "exit_time": "ACTIVE",
                                "exit_price": str(round((buy_data.get("entry_price") or 0.0) + (buy_data.get("pnl_pts") or 0.0), 2)),
                                "result": "ACTIVE 🟢" if (buy_data.get("pnl_rs") or 0.0) >= 0 else "ACTIVE 🔴",
                                "pnl_pts": str(buy_data.get("pnl_pts", "0.0")),
                                "pnl_rs": str(buy_data.get("pnl_rs", "0.0")),
                                "lot_size": str(status_data.get("lot_size", 65) * 3), # Locked v4.0 is 3 lots (195 shares)
                                "paper_trade": str(status_data.get("mode") == "PAPER"),
                                "gap": str(status_data.get("gap", {}).get("gap_pts", "0.0")),
                                "P": str(status_data.get("pivots", {}).get("P", "0.0")),
                                "R1": str(status_data.get("pivots", {}).get("R1", "0.0")),
                                "S1": str(status_data.get("pivots", {}).get("S1", "0.0")),
                                "SL": str(buy_data.get("sl_spot", "0.0")),
                                "remark": f"BASE Option Buying ({buy_data.get('opt_type')}) - Active Trade"
                            })
                        
                    # 2. Option Selling (Strangle) Active Trade
                    if status_data.get("selling", {}).get("in_trade"):
                        sell_data = status_data["selling"]
                        s_date = status_data.get("date", datetime.now().strftime("%Y%m%d"))
                        s_symbol = f"STRANGLE_{sell_data.get('pe_strike')}PE_{sell_data.get('ce_strike')}CE"
                        s_entry_time = sell_data.get("entry_time", "-")
                        
                        # Avoid duplicate if already written to CSV
                        already_logged = any(
                            l.get("date") == s_date and 
                            l.get("symbol") == s_symbol and 
                            l.get("entry_time") == s_entry_time 
                            for l in logs
                        )
                        if not already_logged:
                            ce_ltp = sell_data.get("ce_ltp") or sell_data.get("ce_entry_price") or 0.0
                            pe_ltp = sell_data.get("pe_ltp") or sell_data.get("pe_entry_price") or 0.0
                            active_trades.append({
                                "date": s_date,
                                "signal_time": s_entry_time,
                                "entry_time": s_entry_time,
                                "symbol": s_symbol,
                                "strike": f"{sell_data.get('pe_strike')}/{sell_data.get('ce_strike')}",
                                "opt_type": "STRANGLE",
                                "entry_price": str((sell_data.get("ce_entry_price") or 0.0) + (sell_data.get("pe_entry_price") or 0.0)),
                                "exit_time": "ACTIVE",
                                "exit_price": str(round(ce_ltp + pe_ltp, 2)),
                                "result": "ACTIVE 🟢" if (sell_data.get("pnl_rs") or 0.0) >= 0 else "ACTIVE 🔴",
                                "pnl_pts": str(sell_data.get("pnl_pts", "0.0")),
                                "pnl_rs": str(sell_data.get("pnl_rs", "0.0")),
                                "lot_size": str(status_data.get("lot_size", 65)),
                                "paper_trade": str(status_data.get("mode") == "PAPER"),
                                "gap": str(status_data.get("gap", {}).get("gap_pts", "0.0")),
                                "P": str(status_data.get("pivots", {}).get("P", "0.0")),
                                "R1": str(status_data.get("pivots", {}).get("R1", "0.0")),
                                "S1": str(status_data.get("pivots", {}).get("S1", "0.0")),
                                "SL": f"-{sell_data.get('combined_sl', 7000.0)}",
                                "remark": "Strangle Short Selling (ATM±100) - Active Trade"
                            })
                    
                    logs = active_trades + logs
                except Exception as ex:
                    print(f"Error appending active trade to logs: {ex}")
            
            self.wfile.write(json.dumps(logs).encode())
            return
            
        # GET /api/terminal
        elif self.path == "/api/terminal":
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            
            terminal_output = ""
            if os.path.exists(TERMINAL_LOG):
                try:
                    with open(TERMINAL_LOG, "r") as f:
                        # Return last 100 lines
                        lines = f.readlines()
                        terminal_output = "".join(lines[-100:])
                except Exception as e:
                    terminal_output = f"Error reading terminal log: {e}"
            else:
                terminal_output = "No terminal logs available. Start the scanner to see live terminal outputs."
                
            self.wfile.write(terminal_output.encode())
            return

        # Fallback to SimpleHTTPRequestHandler for static files
        super().do_GET()

    def do_POST(self):
        # POST /api/config
        if self.path == "/api/config":
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            try:
                config_data = json.loads(post_data.decode())
                success, msg = save_config(config_data)
                
                self.send_response(200 if success else 400)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": success, "message": msg}).encode())
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "message": str(e)}).encode())
            return
            
        # POST /api/control
        elif self.path == "/api/control":
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            try:
                control_data = json.loads(post_data.decode())
                action = control_data.get("action")
                
                if action == "start":
                    success, msg = start_scanner()
                elif action == "stop":
                    success, msg = stop_scanner()
                else:
                    success, msg = False, f"Invalid action: {action}"
                    
                self.send_response(200 if success else 400)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": success, "message": msg}).encode())
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "message": str(e)}).encode())
            return

        self.send_response(404)
        self.end_headers()

class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

def run():
    # Make sure to handle clean shutdown of subprocess on server exit
    def signal_handler(sig, frame):
        print("\nShutting down server, terminating scanner...")
        stop_scanner()
        sys.exit(0)
        
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Auto-start scanner by default on server boot
    success, msg = start_scanner()
    
    server = ThreadingHTTPServer(('0.0.0.0', PORT), DashboardRequestHandler)
    print(f"\n========================================================")
    print(f"  NIFTY PIVOT GAP WEB DASHBOARD")
    print(f"  Url: http://localhost:{PORT}")
    if success:
        print(f"  Status: SCANNER ENGINE AUTO-STARTED SUCCESSFULLY")
    else:
        print(f"  Status: SCANNER AUTO-START FAILED ({msg})")
    print(f"========================================================\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_scanner()

if __name__ == "__main__":
    run()

"""
NiftyAgent — Autonomous Trading System
Combines: Selling bot (AngelOne API) + Buying bot (GoCharting Vision + Claude API)
Author: Generated for prop-desk level automated trading
"""

import schedule, time, threading, json, logging
from datetime import datetime, date
from config import CONFIG
from auth.angel_auth import AngelSession
from data.market_data import MarketData
from data.scrip_master import ScripMaster
from analysis.regime import RegimeDetector
from analysis.setup_engine import SetupEngine
from analysis.strike_selector import StrikeSelector
from orders.order_manager import OrderManager
from orders.position_monitor import PositionMonitor
from risk.circuit_breaker import CircuitBreaker
from vision.gocharting_vision import GochartingVision
from alerts.telegram_alerts import TelegramAlert
from dashboard.server import DashboardServer

logging.basicConfig(
    filename='logs/agent.log',
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
log = logging.getLogger("NiftyAgent")


class NiftyAgent:
    def __init__(self):
        log.info("=== NiftyAgent Initializing ===")
        self.angel     = AngelSession()
        self.scrip     = ScripMaster()
        self.market    = MarketData(self.angel)
        self.regime    = RegimeDetector(self.market)
        self.setup     = SetupEngine(self.market, self.angel)
        self.strikes   = StrikeSelector(self.angel, self.scrip)
        self.orders    = OrderManager(self.angel)
        self.monitor   = PositionMonitor(self.angel, self.orders)
        self.risk      = CircuitBreaker(CONFIG)
        self.vision    = GochartingVision()           # GoCharting screen reader
        self.telegram  = TelegramAlert(CONFIG["TELEGRAM_TOKEN"], CONFIG["TELEGRAM_CHAT_ID"])
        self.dashboard = DashboardServer(self)

        self.state = {
            "regime": None,
            "trades_today": 0,
            "daily_pnl": 0.0,
            "active_position": None,
            "bot_running": False,
            "last_signal": None,
        }

    # ──────────────────────────────────────────────
    # STARTUP
    # ──────────────────────────────────────────────
    def start(self):
        log.info("Agent starting...")
        self.angel.login()
        self.scrip.refresh()          # load today's instrument list + expiries
        self.dashboard.run_async()    # start Flask dashboard in background thread
        self.state["bot_running"] = True
        self.telegram.send("🤖 NiftyAgent started. Watching markets.")

        # ── schedule jobs ──
        schedule.every().day.at("09:15").do(self._morning_scan)
        schedule.every().minute.do(self._position_monitor_loop)
        schedule.every(60).seconds.do(self._vision_loop)      # buying signal scanner
        schedule.every().day.at("15:30").do(self._eod_report)

        log.info("Scheduler armed. Running main loop.")
        while self.state["bot_running"]:
            schedule.run_pending()
            time.sleep(1)

    # ──────────────────────────────────────────────
    # MORNING SCAN — 9:15 AM
    # ──────────────────────────────────────────────
    def _morning_scan(self):
        log.info("Morning scan started")
        vix   = self.market.get_vix()
        atr   = self.market.get_atr(interval="FIFTEEN_MINUTE", period=10)
        regime_label = self.regime.classify(vix, atr)
        self.state["regime"] = regime_label
        self.state["trades_today"] = 0

        if regime_label == "C":
            self.telegram.send(f"⛔ Regime C — VIX {vix:.1f}. NO TRADE today.")
            log.info("Regime C — skipping all trades today")
            return

        self.telegram.send(f"📊 Regime {regime_label} — VIX {vix:.1f}. System armed.")

        # Try selling entry at 9:30
        schedule.every().day.at("09:30").do(self._try_selling_entry).tag("entry")

    # ──────────────────────────────────────────────
    # SELLING BOT ENTRY
    # ──────────────────────────────────────────────
    def _try_selling_entry(self):
        schedule.clear("entry")   # run once
        if not self._can_enter_new_trade():
            return

        checks = self.setup.run_all_checks()
        if not checks["all_pass"]:
            failed = [k for k, v in checks.items() if not v]
            log.info(f"Setup failed: {failed}")
            self.telegram.send(f"⚠️ Setup checks failed: {', '.join(failed)}. No trade.")
            return

        # strike selection
        spot      = self.market.get_nifty_spot()
        expiry    = self.scrip.get_next_expiry("NIFTY")
        ce_strike, pe_strike = self.strikes.select(spot, expiry, target_delta=CONFIG["DELTA_TARGET"])

        # pre-trade margin check
        margin_needed = self.orders.calculate_margin(ce_strike, pe_strike, expiry)
        available     = self.angel.get_available_margin()
        if available < margin_needed * 1.2:
            self.telegram.send(f"❌ Insufficient margin. Need ₹{margin_needed:,.0f}, have ₹{available:,.0f}")
            return

        # place orders
        ce_order = self.orders.sell_option(ce_strike, "CE", expiry, lots=CONFIG["lots"])
        pe_order = self.orders.sell_option(pe_strike, "PE", expiry, lots=CONFIG["lots"])

        premium_received = ce_order["avg_price"] + pe_order["avg_price"]
        self.state["active_position"] = {
            "ce": ce_order, "pe": pe_order,
            "premium_received": premium_received,
            "target": premium_received * 0.50,
            "sl": premium_received * 2.0,
            "entry_time": datetime.now().isoformat(),
            "expiry": expiry,
        }
        self.state["trades_today"] += 1
        self.telegram.send(
            f"✅ ENTRY\nCE {ce_strike} @ ₹{ce_order['avg_price']:.1f}\n"
            f"PE {pe_strike} @ ₹{pe_order['avg_price']:.1f}\n"
            f"Premium: ₹{premium_received:.1f} | Target: ₹{premium_received*0.5:.1f} | SL: ₹{premium_received*2:.1f}"
        )
        log.info(f"Strangle entered: CE {ce_strike}, PE {pe_strike}, prem={premium_received}")

    # ──────────────────────────────────────────────
    # POSITION MONITOR LOOP — every 60 sec
    # ──────────────────────────────────────────────
    def _position_monitor_loop(self):
        if not self.state["active_position"]:
            return
        pos   = self.state["active_position"]
        pnl   = self.monitor.get_combined_pnl(pos)
        self.state["daily_pnl"] = pnl

        # circuit breaker check
        if self.risk.daily_limit_hit(pnl):
            log.warning("Daily loss limit hit — emergency exit")
            self._exit_position("CIRCUIT_BREAKER")
            return

        # target hit
        if pnl >= pos["target"]:
            log.info(f"Target hit — PnL {pnl:.0f}")
            self._exit_position("TARGET")
            return

        # SL hit
        if pnl <= -pos["sl"]:
            log.info(f"SL hit — PnL {pnl:.0f}")
            self._exit_position("STOP_LOSS")
            return

        # trailing: lock breakeven after 30% profit
        if pnl >= pos["premium_received"] * 0.30:
            self.monitor.lock_breakeven(pos)

        # delta check
        net_delta = self.monitor.get_net_delta(pos)
        if abs(net_delta) > 0.40:
            self.telegram.send(f"⚠️ Delta breach {net_delta:.2f}. Reviewing position...")
            self._exit_position("DELTA_BREACH")

        # time exit: 1 PM on expiry Tuesday
        now = datetime.now()
        if self._is_expiry_day() and now.hour >= 13:
            self._exit_position("TIME_EXIT_EXPIRY")

    # ──────────────────────────────────────────────
    # VISION LOOP — GoCharting buying signals
    # ──────────────────────────────────────────────
    def _vision_loop(self):
        now = datetime.now()
        # only run during trading hours, not near expiry
        if not (9 <= now.hour < 14):
            return
        if self._is_expiry_day() and now.hour >= 11:
            return

        signal = self.vision.analyze_chart()
        self.state["last_signal"] = signal

        if signal["signal"] != "WAIT" and signal["confidence"] > 75:
            log.info(f"Vision signal: {signal}")
            # Send to Telegram with chart image for manual approval
            self.telegram.send_trade_approval_request(signal)
            # In full-auto mode, uncomment below:
            # self._execute_buying_trade(signal)

    # ──────────────────────────────────────────────
    # EXIT POSITION
    # ──────────────────────────────────────────────
    def _exit_position(self, reason: str):
        pos = self.state["active_position"]
        if not pos:
            return
        pnl = self.monitor.get_combined_pnl(pos)
        self.orders.exit_strangle(pos)
        self.state["active_position"] = None
        self.risk.record_trade(pnl)

        emoji = "💰" if pnl > 0 else "🚨"
        self.telegram.send(
            f"{emoji} EXIT [{reason}]\nP&L: ₹{pnl:+,.0f}\nTrades today: {self.state['trades_today']}"
        )
        log.info(f"Position exited. Reason={reason}, PnL={pnl:.0f}")

        # re-entry check after cooldown
        cooldown = 30 if reason == "STOP_LOSS" else 20
        schedule.every(cooldown).minutes.do(self._check_reentry).tag("reentry")

    def _check_reentry(self):
        schedule.clear("reentry")
        if not self._can_enter_new_trade():
            return
        size_mult = 0.5 if self.risk.had_sl_today() else 0.75
        CONFIG["lots"] = max(1, int(CONFIG["lots"] * size_mult))
        self._try_selling_entry()
        CONFIG["lots"] = CONFIG["BASE_LOTS"]  # reset after

    def _can_enter_new_trade(self):
        if self.state["trades_today"] >= CONFIG["MAX_TRADES_PER_DAY"]:
            return False
        if self.risk.daily_limit_hit(self.state["daily_pnl"]):
            return False
        if self.state["active_position"]:
            return False
        if self.state["regime"] == "C":
            return False
        now = datetime.now()
        if now.hour >= 14 or (now.hour == 13 and now.minute >= 30):
            return False
        return True

    def _is_expiry_day(self):
        today = date.today()
        return today.weekday() == 1 and not self.scrip.is_holiday(today)  # Tuesday

    def _eod_report(self):
        report = self.risk.daily_summary()
        self.telegram.send(f"📈 EOD Report\n{report}")

    def stop(self):
        self.state["bot_running"] = False
        if self.state["active_position"]:
            self._exit_position("MANUAL_STOP")
        self.angel.logout()
        self.telegram.send("🔴 NiftyAgent stopped.")
        log.info("Agent stopped cleanly")


if __name__ == "__main__":
    agent = NiftyAgent()
    try:
        agent.start()
    except KeyboardInterrupt:
        agent.stop()

# NIFTY Pivot Gap Strategy — Complete Specification
Version: 3.0 (LOCKED — validated & optimized)
Instrument: NIFTY (Index)
Style: Intraday Option Buying (ATM CE or PE, 2-lot) + Short Strangle Option Selling (ATM±100, 1-lot)
Validated: 1-year backtest (20250513–20260521, 252 days)

---

## 📊 Strategy Quick Reference

| Component | Trigger | Entry | P&L / year | ROI |
| :--- | :--- | :--- | :--- | :--- |
| **BASE Option Buy (Strategy 1)** | Gap > 30, Pivot touched | ATM CE/PE at next candle + 2s (2-lot) | **+₹1,11,787** | **721%** on premium |
| **Short Strangle Sell (Strategy 2)** | Gap > 30, any gap day | ATM±100 at 09:16:02 (1-lot each leg) | **+₹1,16,100** | **~145–193%** on margin |
| **COMBINED SYSTEM** | **—** | **—** | **+₹2,27,887** | **Acceptable DD** |

---

## ⚡ Strategy 1: BASE (Gap + Pivot Touch — Option Buy)

### Summary
* **Buy ATM CE** when NIFTY gaps up (>30 pts), the opening price is above Pivot (P), and price subsequently tests P level.
* **Buy ATM PE** when NIFTY gaps down (<-30 pts), the opening price is below Pivot (P), and price subsequently tests P level.
* **No Trade** on flat opens or wrong side of P.
* **No Trade** if P is never tested before 13:00.
* **Skip Thursday** (weekly expiry 0DTE day) due to negative contribution.

### 📐 Pivot Formula
Calculated from the previous trading day's OHLC (09:15–15:30 ticks only):
* `H` = previous day high
* `L` = previous day low
* `C` = previous day last traded price (15:30 tick)

$$P = \text{round}\left(\frac{H + L + C}{3}, 2\right)$$
$$R1 = \text{round}(2 \times P - L, 2) \quad \leftarrow \text{CE Target}$$
$$R2 = \text{round}(P + (H - L), 2)$$
$$S1 = \text{round}(2 \times P - H, 2) \quad \leftarrow \text{PE Target}$$
$$S2 = \text{round}(P - (H - L), 2)$$

*All values are rounded to 2 decimal places.*

### 🔍 Gap Calculation
* `prev_close` = last tick price of previous trading day (15:30 close tick)
* `today_open` = first 1-min candle open price of today
* `gap` = $\text{round}(\text{today\_open} - \text{prev\_close}, 2)$

### 🚦 Signal Rules (FINAL LOCKED PARAMS)

#### Strategy A — Gap Up → ATM CE Buy
* **Conditions (both must be true):**
  1. `gap > 30` (NIFTY points)
  2. `today_open >= P`
* **Signal Trigger:**
  * Scan 1-min candles from 09:15 onwards.
  * Signal fires on first candle where: `candle.low <= P + 10` AND `candle.high >= P - 10`.
  * Take only the first such candle before 13:00.
  * If no candle touches P before 13:00 $\rightarrow$ **NO BUY TRADE** (only Strangle strategy runs).
* **Entry (Rule 8 — forward bias prevention):**
  * `entry_time = signal_candle.time + 1 min + 2 seconds`
  * If `entry_time >= 13:00:00` $\rightarrow$ **NO TRADE**.
  * Instrument: ATM CE using `calculate_strike(spot_at_entry, "CE", "NIFTY", "atm")`
  * Symbol format: `NIFTY[DD][MMM][YY][Strike][CE]` (e.g. `NIFTY26MAY2623700CE`)
  * Enter at first available tick at or after `entry_time`.
* **Exit (tick-level on spot, Rule 12):**
  * **Target**: spot price `>= R1` $\rightarrow$ exit CE option at market.
  * **Stop Loss**: spot price `<= P - 20` $\rightarrow$ exit CE option at market.
  * **EOD Exit**: if neither hit by 15:20:00 $\rightarrow$ exit at 15:20 option price.

#### Strategy B — Gap Down → ATM PE Buy
* **Conditions (both must be true):**
  1. `gap < -30` (NIFTY points)
  2. `today_open < P`
* **Signal Trigger:**
  * Scan 1-min candles from 09:15 onwards.
  * Signal fires on first candle where: `candle.high >= P - 10` AND `candle.low <= P + 10`.
  * Take only the first such candle before 13:00.
  * If no candle touches P before 13:00 $\rightarrow$ **NO BUY TRADE** (only Strangle strategy runs).
* **Entry (Rule 8):**
  * `entry_time = signal_candle.time + 1 min + 2 seconds`
  * If `entry_time >= 13:00:00` $\rightarrow$ **NO TRADE**.
  * Instrument: ATM PE using `calculate_strike(spot_at_entry, "PE", "NIFTY", "atm")`
  * Symbol format: `NIFTY[DD][MMM][YY][Strike][PE]` (e.g. `NIFTY26MAY2623700PE`)
  * Enter at first available tick at or after `entry_time`.
* **Exit (tick-level on spot, Rule 12):**
  * **Target**: spot price `<= S1` $\rightarrow$ exit PE option at market.
  * **Stop Loss**: spot price `>= P + 20` $\rightarrow$ exit PE option at market.
  * **EOD Exit**: if neither hit by 15:20:00 $\rightarrow$ exit at 15:20 option price.

---

## 🛡️ Strategy 2: Short Strangle on ALL Gap Days (LOCKED v3)

### Core Logic & Synergies
The BASE strategy and the short strangle are naturally aligned:
1. **On gap days where P is touched**: The market tests the P level and bounces away towards R1/S1 after the BASE entry. The "threatened" strangle leg decays with the rebound, resulting in high profitability.
2. **On gap days where P is NOT touched**: The market never retraces to test P and trends strongly or trades in a range. Both strangle legs decay due to theta, resulting in an exceptionally high EOD win rate.
3. **Early Close Rule**: NEVER close the strangle early when P is touched. Hold it to EOD to harvest full theta decay.

### 🚦 Strangle Rules (LOCKED)
* **When to Trade**: Every gap day ($\text{abs}(\text{gap}) > 30$ pts, correct side of P), except Thursday.
* **Entry Time**: Sell strangle at **09:16:02** sharp.
* **Strike Selection**: ATM ± 100 points
  * **CE strike** = $\text{atm\_strike}(\text{spot\_at\_09:16}) + 100$
  * **PE strike** = $\text{atm\_strike}(\text{spot\_at\_09:16}) - 100$
  * *Since Nifty strike spacing is 50 pts, this represents exactly 2 strikes OTM on each side.*
* **Position Sizing**: 1 lot per leg (65 shares each).
* **Stop Loss**: Combined loss limit of **-₹7,000.00**. Exit both legs immediately if the joint P&L hits this limit.
* **Exit Time**: Hold to EOD and exit both legs at **15:20:00** at market.

---

## 🚫 No Trade Conditions (Combined System)
1. $\text{abs}(\text{gap}) \le 30$ pts $\rightarrow$ Flat open, skip entirely.
2. **Wrong side opens** $\rightarrow$ Skip entirely:
   * Gap up but `today_open < P` $\rightarrow$ skip.
   * Gap down but `today_open >= P` $\rightarrow$ skip.
3. **Thursday Expiry** $\rightarrow$ Skip entirely (NIFTY weekly expiry 0DTE option buying has -58% ROI).
4. **Lot Sizing**:
   * Strangle Sell: 1 lot per leg (65 shares each).
   * BASE Buy: 2 lots (130 shares).

---

## 📈 Backtest Performance (1-Year LOCKED Results)

### Strangle Component (120 Gap Days)
* **Win Rate**: 70.0%
* **Total P&L**: **+₹1,16,100**
* **SPAN Margin Required**: ~₹60,000–₹80,000 per strangle
* **ROI on Margin**: **~145%–193%**
* **Max Drawdown**: ₹13,257
* **Combined SL Hits**: ~4% of days

### BASE Option Buy Component (50 P-Touch Days, 2-Lot)
* **Win Rate**: 54.0%
* **Reward:Risk**: 3.27
* **Total P&L**: **+₹1,11,787**
* **Max Drawdown**: ₹6,754
* **ROI on Premium**: **721.4%**

### Combined System Performance (Approach C)
* **Total P&L**: **+₹2,27,887**
* **Max Combined Drawdown**: ₹17,192 (extremely acceptable)
* **Day-of-Week Win Rates**: 
  * Monday: 33.3% (Good)
  * Tuesday: 41.7% (Keep)
  * Wednesday: 57.9% (Best day)
  * Thursday: SKIPPED
  * Friday: 71.4% (Highest Win Rate)

---

## 📝 Daily Execution Checklist

> [!NOTE]
> **Daily Routine**
> Follow this checklist every trading morning to ensure flawless automated execution.

### Morning Standby (09:00 - 09:14)
1. Ensure the Windows PC is booted. Startup automation will automatically boot the **OpenAlgo Server** and **Dashboard Server**.
2. Open `http://localhost:8080` in the browser. Verify the green **OpenAlgo Server: ONLINE** indicator.
3. Verify that the **Pivots** have successfully calculated using yesterday's OHLC.
4. Verify the **Data Feed Status** shows **STANDBY**.

### Market Open (09:15 - 09:17)
1. At **09:15:05**, check the Opening Gap on the dashboard.
2. If $\text{abs}(\text{gap}) > 30$ pts AND not Thursday AND open is on the correct side of P:
   * Strategy triggers! Data feed status shifts to **ACTIVE**.
   * At **09:16:02**, Strategy 2 (Short Strangle) automatically sells ATM+100 CE and ATM-100 PE (1 lot each).
   * Strangle telemetry populates on the Option Selling card.
3. If flat open ($\le 30$ pts) or Thursday expiry:
   * Strategy prints "NO TRADE" in the console. Status updates to **NO_TRADE**. No orders are placed.

### Intra-day Execution (09:17 - 13:00)
1. If the strategy is active, the engine monitors Nifty spot quotes.
2. If spot tests P (within $\pm10$ pts tolerance) before **13:00**:
   * Strategy 1 (BASE Buy) signal fires.
   * Entry time is calculated as $\text{signal\_time} + 1\text{m }2\text{s}$.
   * At entry time, the engine buys ATM CE (Gap Up) or PE (Gap Down) with 2 lots (130 shares).
   * BASE buying telemetry populates on the Option Buying card.
3. If no P-touch occurs by **13:00**:
   * Option Buying card switches to **NO_TRADE** ("P not touched before cutoff").
   * Strangle Selling card continues running.

### Monitoring & Exits (13:00 - 15:20)
1. **BASE Position**: Monitors spot price tick-by-tick. Exits CE/PE option if spot price hits target ($R1/S1$) or SL ($P \pm 20$).
2. **Strangle Position**: Monitors combined option P&L. Exits CE and PE legs immediately if joint loss reaches **-₹7,000**.
3. **EOD Exit**: If positions are still active at **15:20:00**, the engine automatically cancels or offsets all open orders.

---

> [!WARNING]
> **Margin Requirements**
> Short Strangles require broker margin to execute. When live trading is enabled, ensure a minimum margin balance of **₹1,50,000.00** is available in your Angel One account to accommodate the dual short strangle legs and Option buying margin simultaneously.

#!/usr/bin/env python3
"""
setup_agent.py — Run this ONCE to set up the full NiftyAgent system
Usage: python setup_agent.py
"""

import os, sys, subprocess

BANNER = """
╔══════════════════════════════════════════╗
║   NiftyAgent — Prop Desk Setup Script   ║
║   Nifty Options Trading System v1.0     ║
╚══════════════════════════════════════════╝
"""

PACKAGES = [
    "smartapi-python",
    "pyotp",
    "flask",
    "schedule",
    "anthropic",
    "mss",
    "Pillow",
    "python-telegram-bot",
    "pandas",
    "numpy",
    "requests",
    "python-dotenv",
]

ENV_TEMPLATE = """# NiftyAgent Environment Variables
# Fill these in before running main_agent.py

ANGEL_API_KEY=your_api_key_here
ANGEL_CLIENT_ID=your_client_id_here
ANGEL_PASSWORD=your_password_here
ANGEL_TOTP_SECRET=your_totp_secret_here

TELEGRAM_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here

ANTHROPIC_API_KEY=your_anthropic_api_key_here
"""

def install_packages():
    print("\n[1/3] Installing Python packages...")
    for pkg in PACKAGES:
        print(f"  → {pkg}")
        subprocess.run([sys.executable, "-m", "pip", "install", pkg, "-q"], check=True)
    print("  ✓ All packages installed")

def create_env_file():
    print("\n[2/3] Creating .env template...")
    if not os.path.exists(".env"):
        with open(".env", "w") as f:
            f.write(ENV_TEMPLATE)
        print("  ✓ .env created — FILL IN YOUR CREDENTIALS before running")
    else:
        print("  ✓ .env already exists — skipping")

def create_placeholder_modules():
    """Create __init__.py files so Python treats folders as packages"""
    print("\n[3/3] Creating package __init__ files...")
    dirs = ["auth", "data", "analysis", "orders", "risk", "vision", "alerts", "dashboard", "logs"]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        init = os.path.join(d, "__init__.py")
        if not os.path.exists(init):
            open(init, "w").close()
    print("  ✓ Package structure ready")

def print_next_steps():
    print("""
════════════════════════════════════════════
  Setup complete. Next steps:
════════════════════════════════════════════

  1. Fill in your credentials in .env file:
     → ANGEL_API_KEY, CLIENT_ID, PASSWORD, TOTP_SECRET
     → TELEGRAM_TOKEN, CHAT_ID
     → ANTHROPIC_API_KEY

  2. Keep config.py PAPER_TRADE = True for first 4 weeks

  3. Open GoCharting in Chrome — position the window
     at the CHART_REGION defined in config.py

  4. Run the agent:
     python main_agent.py

  5. Open dashboard in browser:
     http://localhost:8080

  6. Watch Telegram for:
     → Morning regime scan
     → Entry/exit signals
     → Vision signals for approval

════════════════════════════════════════════
""")

if __name__ == "__main__":
    print(BANNER)
    install_packages()
    create_env_file()
    create_placeholder_modules()
    print_next_steps()

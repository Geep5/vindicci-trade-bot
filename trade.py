#!/usr/bin/env python3
"""Vindicci trade bot — follows top prediction agents and trades BTC on Hyperliquid."""

import json
import os
import sys
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError

try:
    from hyperliquid.exchange import Exchange
    from hyperliquid.info import Info
    import eth_account
except ImportError:
    print("Missing dependencies. Run: pip install hyperliquid-python-sdk eth-account", file=sys.stderr)
    sys.exit(1)

# === Configuration (all from env) ===
VINDICCI = os.environ.get("VINDICCI_SERVER", "https://vindicci.xyz")
PRIVATE_KEY = os.environ.get("HL_PRIVATE_KEY", "")
SIZE_BTC = float(os.environ.get("SIZE_BTC", "0.001"))
MODE = os.environ.get("MODE", "single")  # "single" or "multi"
TOP_N = int(os.environ.get("TOP_N", "3"))
MIN_CONFIDENCE = float(os.environ.get("MIN_CONFIDENCE", "60"))
MIN_ACCURACY_24H = float(os.environ.get("MIN_ACCURACY_24H", "50"))
MIN_PREDICTIONS = int(os.environ.get("MIN_PREDICTIONS", "5"))
CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL", "120"))


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def api_get(path):
    with urlopen(Request(f"{VINDICCI}{path}"), timeout=15) as r:
        return json.loads(r.read())


def get_top_agents():
    """Select agents from leaderboard by 24h accuracy."""
    board = api_get("/api/leaderboard")
    qualified = [
        a for a in board
        if a["total"] >= MIN_PREDICTIONS
        and a["accuracy_24h"] > MIN_ACCURACY_24H
    ]
    qualified.sort(key=lambda a: a["accuracy_24h"], reverse=True)
    if MODE == "single":
        return qualified[:1]
    return qualified[:TOP_N]


def get_agent_weight(agent):
    """Weight = accuracy_24h/100 + streak * 0.1."""
    base = agent["accuracy_24h"] / 100.0
    streak_bonus = agent["streak"] * 0.1
    return base + streak_bonus


def compute_signal(agents):
    """Weighted bull/bear signal from agents' latest predictions."""
    above_w, below_w = 0.0, 0.0

    for agent in agents:
        try:
            preds = api_get(f"/api/agents/{agent['agent_id']}/predictions")
        except Exception as e:
            log(f"  Failed to fetch predictions for {agent['agent_name']}: {e}")
            continue
        if not preds:
            continue
        latest = preds[0]
        weight = get_agent_weight(agent)
        direction = latest["direction"]
        log(f"  {agent['agent_name']}: {direction} (weight {weight:.2f}, acc_24h {agent['accuracy_24h']:.0f}%, streak {agent['streak']})")

        if direction == "above":
            above_w += weight
        elif direction == "below":
            below_w += weight

    total = above_w + below_w
    if total == 0:
        return None, 0
    if above_w > below_w:
        return "above", (above_w / total) * 100
    elif below_w > above_w:
        return "below", (below_w / total) * 100
    return None, 0


def get_btc_position(info, wallet_address):
    """Get current BTC position. Returns (size, entry_px)."""
    state = info.user_state(wallet_address)
    for pos in state.get("assetPositions", []):
        p = pos.get("position", {})
        if p.get("coin") == "BTC":
            size = float(p.get("szi", "0"))
            if size != 0:
                return size, float(p.get("entryPx", "0"))
    return 0.0, 0.0


def place_order(exchange, info, is_buy, size, reduce_only=False):
    """Place IOC order on Hyperliquid."""
    mids = info.all_mids()
    btc_mid = float(mids["BTC"])
    slippage = 1.003 if is_buy else 0.997
    limit_px = round(btc_mid * slippage, 1)
    log(f"  Order: {'BUY' if is_buy else 'SELL'} {size:.4f} BTC @ ${limit_px:,.1f} (IOC, reduce_only={reduce_only})")
    return exchange.order(
        "BTC", is_buy, size, limit_px,
        {"limit": {"tif": "Ioc"}},
        reduce_only=reduce_only,
    )


def execute_trade(exchange, info, wallet_address, direction):
    """Check position and execute trade based on signal direction."""
    pos_size, entry_px = get_btc_position(info, wallet_address)
    is_long = pos_size > 0
    is_short = pos_size < 0

    if direction == "above":
        if is_long:
            log(f"Already long {pos_size:.4f} BTC from ${entry_px:,.1f} — holding.")
            return
        if is_short:
            log(f"Closing short {abs(pos_size):.4f} BTC...")
            place_order(exchange, info, is_buy=True, size=abs(pos_size), reduce_only=True)
        log(f"Opening long {SIZE_BTC} BTC...")
        result = place_order(exchange, info, is_buy=True, size=SIZE_BTC)
        log(f"Result: {result}")

    elif direction == "below":
        if is_short:
            log(f"Already short {abs(pos_size):.4f} BTC from ${entry_px:,.1f} — holding.")
            return
        if is_long:
            log(f"Closing long {pos_size:.4f} BTC...")
            place_order(exchange, info, is_buy=False, size=pos_size, reduce_only=True)
        log(f"Opening short {SIZE_BTC} BTC...")
        result = place_order(exchange, info, is_buy=False, size=SIZE_BTC)
        log(f"Result: {result}")


def main():
    if not PRIVATE_KEY:
        print("Set HL_PRIVATE_KEY env var (Hyperliquid wallet private key)", file=sys.stderr)
        sys.exit(1)

    wallet = eth_account.Account.from_key(PRIVATE_KEY)
    exchange = Exchange(wallet, base_url="https://api.hyperliquid.xyz")
    info = Info(base_url="https://api.hyperliquid.xyz")

    log("Vindicci trade bot starting")
    log(f"Server:    {VINDICCI}")
    log(f"Wallet:    {wallet.address}")
    log(f"Mode:      {MODE} (top {TOP_N if MODE == 'multi' else 1})")
    log(f"Size:      {SIZE_BTC} BTC per trade")
    log(f"Interval:  {CHECK_INTERVAL}s")
    log("---")

    while True:
        try:
            agents = get_top_agents()
            if not agents:
                log("No qualified agents on leaderboard — skipping.")
                time.sleep(CHECK_INTERVAL)
                continue

            names = ", ".join(f"{a['agent_name']} ({a['accuracy_24h']:.0f}%)" for a in agents)
            log(f"Following: {names}")

            direction, confidence = compute_signal(agents)

            if not direction:
                log("No clear signal — skipping.")
                time.sleep(CHECK_INTERVAL)
                continue

            log(f"Signal: {direction.upper()} @ {confidence:.0f}% confidence")

            if MODE == "multi" and confidence < MIN_CONFIDENCE:
                log(f"Confidence {confidence:.0f}% below {MIN_CONFIDENCE}% threshold — skipping.")
                time.sleep(CHECK_INTERVAL)
                continue

            execute_trade(exchange, info, wallet.address, direction)

        except Exception as e:
            log(f"Error: {e}")

        log(f"Sleeping {CHECK_INTERVAL}s...")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()

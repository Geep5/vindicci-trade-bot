# vindicci-trade-bot

Follows the top-performing prediction agents on the [Vindicci leaderboard](https://vindicci-board.fly.dev) and mirrors their calls as real BTC perpetual trades on Hyperliquid.

No prediction logic. No LLM. Just follow the best and trade.

## Quick start

```bash
# 1. Clone
git clone https://github.com/Geep5/vindicci-trade-bot.git
cd vindicci-trade-bot

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set your Hyperliquid wallet key
cp .env.example .env
# Edit .env with your HL_PRIVATE_KEY

# 4. Run
python3 trade.py
```

That's it. The bot will:
- Fetch the Vindicci leaderboard, find the #1 agent by 24h accuracy
- Get their latest prediction (above/below)
- Open a BTC perpetual position on Hyperliquid in that direction
- Check every 2 minutes, flip if the signal changes

## How it works

```
Vindicci Leaderboard          This Bot              Hyperliquid
+-----------------+    +-------------------+    +----------------+
| #1 agent says   | -> | Read signal       | -> | Open long/short|
| "above"         |    | Check position    |    | BTC perpetual  |
|                 |    | Execute if needed |    |                |
+-----------------+    +-------------------+    +----------------+
```

**Single mode** (default): Follow the #1 agent. Their call is your trade. Zero config.

**Multi mode**: Follow the top N agents. Weight their signals by 24h accuracy + streak bonus. Trade only when consensus exceeds a confidence threshold.

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `HL_PRIVATE_KEY` | yes | | Hyperliquid wallet private key |
| `VINDICCI_SERVER` | no | `https://vindicci-board.fly.dev` | Vindicci server URL |
| `SIZE_BTC` | no | `0.001` | Position size per trade (~$68 at current prices) |
| `MODE` | no | `single` | `single` = follow #1, `multi` = follow top N |
| `TOP_N` | no | `3` | Agents to follow in multi mode |
| `MIN_CONFIDENCE` | no | `60` | Min weighted consensus to trade (multi mode) |
| `MIN_ACCURACY_24H` | no | `50` | Min 24h accuracy to trust an agent |
| `MIN_PREDICTIONS` | no | `5` | Min total predictions before trusting |
| `CHECK_INTERVAL` | no | `120` | Seconds between checks |

## Modes

### Single mode (default)

Follows the #1 agent by rolling 24h accuracy. If they say above, you go long. If they say below, you go short. Simplest strategy.

```bash
MODE=single python3 trade.py
```

### Multi mode

Follows the top N agents with weighted consensus. Each agent's weight = `accuracy_24h/100 + streak * 0.1`. Only trades when the weighted signal exceeds `MIN_CONFIDENCE`.

```bash
MODE=multi TOP_N=3 MIN_CONFIDENCE=60 python3 trade.py
```

Example with 3 agents:
```
Agent A: 72% accuracy, streak 4 -> weight 1.12, says "above"
Agent B: 65% accuracy, streak 1 -> weight 0.75, says "above"  
Agent C: 55% accuracy, streak 0 -> weight 0.55, says "below"

above_weight = 1.12 + 0.75 = 1.87
below_weight = 0.55
confidence = 1.87 / 2.42 * 100 = 77% -> TRADE ABOVE
```

## Position management

The bot checks your current Hyperliquid BTC position before every trade:

| Current Position | Signal | Action |
|-----------------|--------|--------|
| None | above | Open long |
| None | below | Open short |
| Long | above | Hold |
| Long | below | Close long, open short |
| Short | above | Close short, open long |
| Short | below | Hold |

## Run in background

```bash
# With nohup
nohup python3 trade.py > trade.log 2>&1 &

# With screen
screen -S vindicci-trade python3 trade.py
```

## Hyperliquid wallet setup

1. Go to [app.hyperliquid.xyz](https://app.hyperliquid.xyz)
2. Connect your wallet and deposit USDC
3. Export your private key (or use a dedicated trading wallet)
4. Set `HL_PRIVATE_KEY` in `.env`

Start with a small `SIZE_BTC` (0.001 = ~$68) while testing.

## Risk

- This is **perpetual futures**. Positions have funding rates and liquidation risk.
- IOC orders may not fill if the book is thin.
- The bot is only as good as the agents it follows. Check the [leaderboard](https://vindicci-board.fly.dev/leaderboard).
- Start small. Watch the logs. Increase size when you trust the signal.

## License

MIT

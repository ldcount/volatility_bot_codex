# Volatility Analysis Telegram Bot

A Telegram bot that validates Bybit tickers and returns a volatility/risk report using up to 1000 daily candles.

## Features
- Validates symbols in Bybit order: **Linear Perps → Inverse → Spot**.
- Pulls OHLCV candles directly from Bybit API (in-memory only, no CSV storage).
- Computes:
  - Daily and weekly volatility (std. dev. of log returns)
  - Max daily surge/crash
  - Intraday pump/dump stats (avg/std/max/min)
  - ATR(14), ATR(28) absolute and relative
  - Martingale/DCA percentile levels (P75..P99)
- Async Telegram handlers with non-blocking analysis (`asyncio.to_thread`).
- Retry + timeout + clear user-safe error messages.

## First Launch (Quick Start)
1. Create a bot with BotFather and get your Telegram token.
2. Install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Set environment variables:
   ```bash
   export TELEGRAM_BOT_TOKEN="<your-token>"
   # Optional (public funding endpoint is used; keep for private endpoint fallback)
   export BYBIT_API_KEY="<your-bybit-api-key>"
   export BYBIT_API_SECRET="<your-bybit-api-secret>"
   ```
4. Run:
   ```bash
   python bot.py
   ```

## Project Structure
- `bot.py`: Telegram handlers and bot lifecycle.
- `logic.py`: input validation, Bybit data access, analytics, report formatting.

## Suggested Future Improvements
1. `/chart` command to return volatility + ATR plot image for faster visual decisions.
2. `/alert` command for notifying users when price nears selected percentile DCA levels.


## Commands
- Send `BTC` style text for volatility analysis.
- Send `/dca <ticker> <first_cost_basis>` to generate a 6-session short DCA ladder.
- Send `/funding` to get the 10 most negative funding rates in Bybit Linear, sorted ascending (most negative first).
  - Example: `/dca BTC 1000`
  - Session 1 is a market entry at current price using the provided cost basis.
  - Sessions 2-6 are upward DCA entries derived from pump percentiles, each doubling total coin exposure.

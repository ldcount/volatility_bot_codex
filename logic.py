from __future__ import annotations

import logging
import math
import re
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
import requests

LOGGER = logging.getLogger(__name__)
BYBIT_BASE_URL = "https://api.bybit.com"


class BotError(Exception):
    """Base exception for user-facing errors."""


class ValidationError(BotError):
    """Raised when user input is invalid."""


class SymbolNotFoundError(BotError):
    """Raised when a symbol cannot be resolved on Bybit."""


class BybitAPIError(BotError):
    """Raised when Bybit API requests fail."""


@dataclass(frozen=True)
class SymbolResolution:
    category: str
    symbol: str


@dataclass(frozen=True)
class OHLCVCandle:
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class BybitClient:
    def __init__(self, base_url: str = BYBIT_BASE_URL, timeout: float = 10.0, retries: int = 3):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()

    def _request(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        delay = 0.5

        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                response.raise_for_status()
                payload = response.json()
                if payload.get("retCode") != 0:
                    raise BybitAPIError(f"Bybit error {payload.get('retCode')}: {payload.get('retMsg')}")
                return payload
            except (requests.RequestException, ValueError, BybitAPIError) as exc:
                LOGGER.warning("Bybit request failed (%s/%s): %s", attempt, self.retries, exc)
                if attempt == self.retries:
                    raise BybitAPIError("Could not reach Bybit API. Please try again shortly.") from exc
                time.sleep(delay)
                delay *= 2

        raise BybitAPIError("Unexpected API failure.")

    def resolve_symbol(self, ticker: str) -> SymbolResolution:
        normalized = normalize_ticker(ticker)

        candidates = [normalized]
        if not normalized.endswith(("USDT", "USDC", "USD")):
            candidates = [f"{normalized}USDT", f"{normalized}USD", normalized]

        category_order = ["linear", "inverse", "spot"]
        for category in category_order:
            for candidate in candidates:
                payload = self._request(
                    "/v5/market/instruments-info",
                    {"category": category, "symbol": candidate},
                )
                instruments = payload.get("result", {}).get("list", [])
                if instruments:
                    return SymbolResolution(category=category, symbol=instruments[0]["symbol"])

        raise SymbolNotFoundError(
            f"Ticker '{normalized}' was not found on Bybit (Linear, Inverse, or Spot)."
        )

    def fetch_daily_ohlcv(self, category: str, symbol: str, limit: int = 1000) -> list[OHLCVCandle]:
        payload = self._request(
            "/v5/market/kline",
            {
                "category": category,
                "symbol": symbol,
                "interval": "D",
                "limit": min(limit, 1000),
            },
        )
        raw_rows = payload.get("result", {}).get("list", [])
        if len(raw_rows) < 30:
            raise BybitAPIError("Not enough history available (need at least 30 daily candles).")

        candles: list[OHLCVCandle] = []
        for row in raw_rows:
            candles.append(
                OHLCVCandle(
                    ts=int(row[0]),
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
            )

        candles.sort(key=lambda c: c.ts)
        return candles


class VolatilityAnalyzer:
    PERCENTILES = [75, 80, 85, 90, 95, 99]

    def analyze(self, candles: list[OHLCVCandle]) -> dict[str, Any]:
        o = np.array([c.open for c in candles], dtype=np.float64)
        h = np.array([c.high for c in candles], dtype=np.float64)
        l = np.array([c.low for c in candles], dtype=np.float64)
        c = np.array([c.close for c in candles], dtype=np.float64)

        log_returns = np.diff(np.log(c))
        simple_returns = np.diff(c) / c[:-1]

        pump = (h - o) / o
        dump = (l - o) / o

        prev_close = np.roll(c, 1)
        prev_close[0] = c[0]

        true_range = np.maximum.reduce([
            h - l,
            np.abs(h - prev_close),
            np.abs(l - prev_close),
        ])

        atr_14 = float(np.mean(true_range[-14:]))
        atr_28 = float(np.mean(true_range[-28:]))

        return {
            "candle_count": len(candles),
            "daily_vol": float(np.std(log_returns, ddof=1)),
            "weekly_vol": float(np.std(log_returns, ddof=1) * math.sqrt(7)),
            "max_daily_surge": float(np.max(simple_returns)),
            "max_daily_crash": float(np.min(simple_returns)),
            "pump_avg": float(np.mean(pump)),
            "pump_std": float(np.std(pump, ddof=1)),
            "pump_best": float(np.max(pump)),
            "dump_avg": float(np.mean(dump)),
            "dump_std": float(np.std(dump, ddof=1)),
            "dump_worst": float(np.min(dump)),
            "atr_14": atr_14,
            "atr_28": atr_28,
            "atr_14_pct": float(atr_14 / c[-1]),
            "atr_28_pct": float(atr_28 / c[-1]),
            "dca_levels": {p: float(np.percentile(pump, p)) for p in self.PERCENTILES},
        }


class VolatilityReportService:
    def __init__(self, bybit: BybitClient, analyzer: VolatilityAnalyzer):
        self.bybit = bybit
        self.analyzer = analyzer

    def generate_report(self, user_text: str) -> str:
        resolution = self.bybit.resolve_symbol(user_text)
        candles = self.bybit.fetch_daily_ohlcv(resolution.category, resolution.symbol, limit=1000)
        stats = self.analyzer.analyze(candles)
        return format_report(resolution, stats)


def normalize_ticker(raw: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]", "", raw.upper().strip())
    if not cleaned:
        raise ValidationError("Please send a valid ticker (e.g., BTC, ETHUSDT, PEPE).")
    if len(cleaned) > 20:
        raise ValidationError("Ticker is too long. Please send a normal symbol like BTC or SOLUSDT.")
    return cleaned


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def format_report(resolution: SymbolResolution, stats: dict[str, Any]) -> str:
    lines = [
        f"*Volatility Analysis — {resolution.symbol}*",
        f"Market: `{resolution.category}` | Candles: `{stats['candle_count']}`",
        "",
        "*Daily Stats*",
        f"• Volatility (Daily): `{pct(stats['daily_vol'])}`",
        f"• Volatility (Weekly): `{pct(stats['weekly_vol'])}`",
        f"• Max Daily Surge: `{pct(stats['max_daily_surge'])}`",
        f"• Max Daily Crash: `{pct(stats['max_daily_crash'])}`",
        "",
        "*Intraday Pump / Dump*",
        f"• Pump Avg / Std: `{pct(stats['pump_avg'])}` / `{pct(stats['pump_std'])}`",
        f"• Best Pump: `{pct(stats['pump_best'])}`",
        f"• Dump Avg / Std: `{pct(stats['dump_avg'])}` / `{pct(stats['dump_std'])}`",
        f"• Worst Dump: `{pct(stats['dump_worst'])}`",
        "",
        "*Risk Metrics (ATR)*",
        f"• ATR(14): `{stats['atr_14']:.6f}` ({pct(stats['atr_14_pct'])})",
        f"• ATR(28): `{stats['atr_28']:.6f}` ({pct(stats['atr_28_pct'])})",
        "",
        "*Martingale / DCA Levels (Pump Percentiles)*",
    ]

    for percentile, move in stats["dca_levels"].items():
        lines.append(f"• P{percentile}: `{pct(move)}`")

    lines.extend(
        [
            "",
            "_Tip: Higher percentile levels represent rarer up-moves and can be used as more conservative DCA zones._",
        ]
    )
    return "\n".join(lines)

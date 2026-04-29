#!/usr/bin/env python3
"""
Bot #104 — Finance & Crypto Agent
Category: agent_workforce
Purpose: Autonomous finance intelligence agent. Monitors crypto prices, stock markets,
         DeFi yields, and trending financial opportunities. Generates signals, analysis,
         and affiliate-monetized content. Publishes to all platforms every 4 hours.
         Earns through Coinbase, Robinhood, and Binance affiliate links.
"""
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from core.base_bot import BaseBot  # noqa: E402

SYSTEM = """You are an elite crypto and financial markets analyst with 20 years of experience.
You analyze on-chain data, price action, macroeconomic signals, and market sentiment.
You write clear, engaging financial content for retail investors — not jargon, but
insight that actually helps people make money. You always include affiliate CTAs
for Coinbase and Robinhood. You are not a licensed advisor — you provide education
and information only. Your content is engaging, data-driven, and actionable."""


class FinanceAgentBot(BaseBot):

    def __init__(self):
        super().__init__("104_finance_agent", "agent_workforce")
        self.coinbase_url = os.getenv("AFFILIATE_COINBASE_URL", "https://coinbase.com/join")
        self.robinhood_url = os.getenv("AFFILIATE_WEBULL_URL", "https://robinhood.com/us/en/")
        self.binance_url = os.getenv("AFFILIATE_BINANCE_URL", "https://binance.com/en/register")

    def run(self, action: str = "signal", **kwargs):
        cfg = self.config
        action = action or cfg.get("action", "signal")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        actions = {
            "signal": self._crypto_signal,
            "stock": self._stock_analysis,
            "defi": self._defi_opportunities,
            "report": self._market_report,
            "content": self._finance_content,
            "alert": self._price_alert,
        }
        fn = actions.get(action, self._crypto_signal)
        return fn(ts, **kwargs)

    def _get_live_prices(self) -> dict:
        try:
            from bots.narai.narai.bot import NarAIInternet
            internet = NarAIInternet()
            prices = internet.crypto_price(["bitcoin", "ethereum", "solana", "cardano", "polkadot"])
            return prices
        except Exception:
            return {}

    def _get_trending_crypto(self) -> list:
        try:
            from bots.narai.narai.bot import NarAIInternet
            return NarAIInternet().trending()
        except Exception:
            return ["Bitcoin", "Ethereum", "Solana"]

    def _crypto_signal(self, ts: str, **kwargs) -> dict:
        prices = self._get_live_prices()
        trending = self._get_trending_crypto()

        btc = prices.get("bitcoin", {})
        eth = prices.get("ethereum", {})
        sol = prices.get("solana", {})

        price_context = f"""
Live Prices:
- BTC: ${btc.get('usd', 'N/A')} ({btc.get('usd_24h_change', 0):.1f}% 24h)
- ETH: ${eth.get('usd', 'N/A')} ({eth.get('usd_24h_change', 0):.1f}% 24h)
- SOL: ${sol.get('usd', 'N/A')} ({sol.get('usd_24h_change', 0):.1f}% 24h)
Trending: {', '.join(trending[:5])}"""

        prompt = f"""Generate a crypto signal post for WheellsVerse audience.

{price_context}

Create:
1. SIGNAL HEADER — Bullish/Bearish/Neutral market read with emoji
2. TOP COIN PICKS TODAY — 3 coins with entry context (not financial advice)
3. KEY LEVEL TO WATCH — one critical price level for BTC
4. RISK MANAGEMENT TIP — one actionable tip
5. AFFILIATE CTA — "Get $10 free Bitcoin → [Coinbase link]"

Format for Instagram + Facebook (spaced lines, emojis, engaging tone).
Include hashtags: #Bitcoin #Crypto #BTC #PassiveIncome #CryptoSignals #WheellsVerse

Coinbase affiliate: {self.coinbase_url}
Robinhood affiliate: {self.robinhood_url}"""

        result = self.claude(prompt, system=SYSTEM, max_tokens=1000)
        path = self.save_output(f"# Crypto Signal\n\n{result}", f"crypto_signal_{ts}.md", ext="md")

        # Auto-publish to Facebook + Instagram
        try:
            from core.facebook import get_facebook
            from core.instagram import get_instagram
            fb = get_facebook()
            ig = get_instagram()
            if fb.is_configured():
                fb.post(result)
            if ig.is_configured():
                ig.post(result)
            self.logger.info("Finance signal published to social media")
        except Exception as e:
            self.logger.warning("Could not publish signal: %s", e)

        try:
            from core.telegram import notify
            notify(f"📊 Finance Agent — Crypto Signal\n{price_context}\n✅ Published to FB + IG")
        except Exception:
            pass

        return {"file": str(path), "action": "signal", "prices": prices}

    def _stock_analysis(self, ts: str, **kwargs) -> dict:
        ticker = kwargs.get("ticker", "NVDA")

        price_data = {}
        try:
            from bots.narai.narai.bot import NarAIInternet
            price_data = NarAIInternet().market_price(ticker)
        except Exception:
            pass

        prompt = f"""Generate a stock analysis post for {ticker}.

Price data: {price_data}

Create engaging stock analysis content:
1. COMPANY SNAPSHOT — what they do + why it matters to AI/tech investors
2. PRICE ACTION — current trend reading (based on data above)
3. BULL CASE — top 2 reasons bulls are excited
4. BEAR CASE — top 1 risk to watch
5. VERDICT — buy, watch, or avoid (education, not advice)
6. CTA — "Start investing free → {self.robinhood_url}"

Tone: Bloomberg meets Reddit — smart but accessible.
Include hashtags: #Stocks #Investing #StockMarket #{ticker} #PassiveIncome"""

        result = self.claude(prompt, system=SYSTEM, max_tokens=1000)
        path = self.save_output(f"# Stock Analysis: {ticker}\n\n{result}",
                                f"stock_{ticker}_{ts}.md", ext="md")

        try:
            from core.facebook import get_facebook
            get_facebook().post(result)
        except Exception:
            pass

        return {"file": str(path), "action": "stock", "ticker": ticker}

    def _defi_opportunities(self, ts: str, **kwargs) -> dict:
        prompt = f"""Generate a DeFi yield opportunities report for this week.

Cover:
1. TOP 3 YIELD OPPORTUNITIES — protocol, APY, risk level, min investment
2. STABLECOIN YIELDS — safest options with 5%+ APY
3. NEW PROTOCOL SPOTLIGHT — one promising new DeFi project
4. RISK WARNING — one thing to absolutely avoid right now
5. HOW TO START — step-by-step for a beginner
6. CTA — "Get $10 free crypto → {self.coinbase_url}"

Keep it educational. Focus on legitimate, established protocols.
Hashtags: #DeFi #CryptoYield #PassiveIncome #Web3 #CryptoInvesting"""

        result = self.claude(prompt, system=SYSTEM, max_tokens=1200)
        path = self.save_output(f"# DeFi Opportunities\n\n{result}", f"defi_{ts}.md", ext="md")
        return {"file": str(path), "action": "defi"}

    def _market_report(self, ts: str, **kwargs) -> dict:
        prices = self._get_live_prices()
        trending = self._get_trending_crypto()

        news = []
        try:
            from bots.narai.narai.bot import NarAIInternet
            news_items = NarAIInternet().news("crypto bitcoin market 2026", num=5)
            news = [f"- {n.get('title', '')}" for n in news_items]
        except Exception:
            pass

        prompt = f"""Generate WheellsVerse Weekly Financial Market Report.

Live data:
{prices}

Trending coins: {', '.join(trending)}

Latest news:
{chr(10).join(news) if news else '- Market data unavailable'}

Report sections:
1. EXECUTIVE SUMMARY — market mood in 3 sentences
2. CRYPTO MARKET OVERVIEW — BTC/ETH/ALT summary
3. STOCK MARKET PULSE — tech stocks, AI sector
4. MACRO FACTORS — rates, inflation, dollar impact
5. THIS WEEK'S OPPORTUNITY — one specific trade/investment idea
6. OUTLOOK — next 7 days prediction
7. AFFILIATE LINKS — Coinbase + Robinhood CTAs

Professional newsletter format. 500-700 words."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2000)
        path = self.save_output(f"# Market Report — {datetime.now().strftime('%Y-%m-%d')}\n\n{result}",
                                f"market_report_{ts}.md", ext="md")

        # Send to email list via ConvertKit
        try:
            from core.convertkit import get_convertkit
            ck = get_convertkit()
            if ck.is_connected():
                ck.create_broadcast(
                    subject=f"📊 WheellsVerse Market Report — {datetime.now().strftime('%B %d')}",
                    content=result,
                )
                self.logger.info("Market report sent to email list")
        except Exception as e:
            self.logger.warning("ConvertKit send failed: %s", e)

        try:
            from core.telegram import notify
            notify("📈 Finance Agent — Weekly Market Report\n✅ Published + emailed to list")
        except Exception:
            pass

        return {"file": str(path), "action": "report"}

    def _finance_content(self, ts: str, **kwargs) -> dict:
        topic = kwargs.get("topic", "how to build passive income with crypto in 2026")
        prompt = f"""Write viral financial education content about: {topic}

For WheellsVerse brand. Make it:
- Hook that stops scrolling (first line is shocking or controversial)
- 5 key insights (numbered, digestible)
- Real numbers and examples
- CTA: Get started free → {self.coinbase_url}
- 15-20 hashtags for Instagram

Target: beginner investors who want passive income.
Tone: confident financial educator, not a bro."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=1000)
        path = self.save_output(f"# Finance Content\n\n{result}", f"finance_content_{ts}.md", ext="md")
        return {"file": str(path), "action": "content", "topic": topic}

    def _price_alert(self, ts: str, **kwargs) -> dict:
        prices = self._get_live_prices()
        btc_price = prices.get("bitcoin", {}).get("usd", 0)
        btc_change = prices.get("bitcoin", {}).get("usd_24h_change", 0)

        alert_type = "neutral"
        if btc_change and abs(btc_change) > 5:
            alert_type = "bull" if btc_change > 0 else "bear"

        msg = "🚨 CRYPTO ALERT\n"
        msg += f"BTC: ${btc_price:,} ({btc_change:+.1f}% 24h)\n"
        if alert_type == "bull":
            msg += "📈 Strong upward movement — market is heating up\n"
        elif alert_type == "bear":
            msg += "📉 Significant drop — watch key support levels\n"
        msg += f"\nGet $10 free Bitcoin: {self.coinbase_url}"

        if abs(btc_change) > 5:  # Only alert on significant moves
            try:
                from core.telegram import notify
                notify(msg)
            except Exception:
                pass

        path = self.save_output(f"# Price Alert\n\n{msg}", f"price_alert_{ts}.md", ext="md")
        return {"file": str(path), "action": "alert", "btc_price": btc_price, "change": btc_change}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Finance & Crypto Agent")
    parser.add_argument("--action", default="signal",
                        choices=["signal", "stock", "defi", "report", "content", "alert"])
    parser.add_argument("--ticker", type=str, default="NVDA")
    parser.add_argument("--topic", type=str, default=None)
    args = parser.parse_args()
    bot = FinanceAgentBot()
    result = bot.execute(action=args.action, ticker=args.ticker, topic=args.topic)
    print(f"\n✅ Finance Agent: {result['file']}")

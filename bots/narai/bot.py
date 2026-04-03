# Backward-compatibility shim — real code lives in bots/narai/narai/bot.py
from bots.narai.narai.bot import *  # noqa: F401, F403
from bots.narai.narai.bot import get_narai, NarAIBot  # noqa: F401

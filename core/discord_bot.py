#!/usr/bin/env python3
"""
core/discord_bot.py
─────────────────────────────────────────────────────────────────────────────
NarAI Discord bot integration.

Prefix commands: !ask, !bots, !startbot, !stopbot, !generate, !status
Slash commands: /ask, /bots, /generate
Any mention of the bot → NarAI response
Rich embeds for bot status

Launched as a background asyncio task if DISCORD_BOT_TOKEN is set.
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import os
import time
from collections import deque

logger = logging.getLogger("discord_bot")

_client = None
_started = False

# Per-user sliding-window rate limiter: max 5 messages per 60 seconds
_rate_limits: dict = {}

def _is_rate_limited(user_id: str, max_msgs: int = 5, window: int = 60) -> bool:
    now = time.time()
    q = _rate_limits.setdefault(user_id, deque())
    while q and q[0] < now - window:
        q.popleft()
    if len(q) >= max_msgs:
        return True
    q.append(now)
    return False


def is_enabled() -> bool:
    return bool(os.getenv("DISCORD_BOT_TOKEN"))


async def _get_narai_response(text: str, channel_id: str) -> str:
    """Get NarAI response for a Discord message."""
    try:
        import anthropic
        from core.chat_db import (
            add_message, create_conversation, get_claude_history,
            get_setting, _get_conn, _lock,
        )
        from core.memory_engine import format_memory_context

        conn = _get_conn()
        with _lock:
            row = conn.execute(
                "SELECT id FROM conversations WHERE title=? LIMIT 1",
                (f"Discord:{channel_id}",)
            ).fetchone()
        conv_id = row[0] if row else create_conversation(title=f"Discord:{channel_id}")

        sys_prompt = (
            get_setting("system_prompt") or
            "You are NarAI, a powerful AI assistant for the WheellsVerse Discord server. "
            "Be helpful, concise, and technically precise."
        )
        mem_ctx = format_memory_context()
        if mem_ctx:
            sys_prompt = mem_ctx + "\n" + sys_prompt

        history = get_claude_history(conv_id, max_messages=15)
        add_message(conv_id, "user", text)

        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        model = get_setting("default_model") or "claude-haiku-4-5-20251001"
        resp = client.messages.create(
            model=model, max_tokens=1024, system=sys_prompt,
            messages=history + [{"role": "user", "content": text}],
        )
        response_text = resp.content[0].text if resp.content else "I couldn't process that request."
        add_message(conv_id, "assistant", response_text)
        return response_text
    except Exception as e:
        logger.error(f"[discord] NarAI error: {e}")
        return f"Error: {e}"


async def start_bot():
    """Start the Discord bot."""
    global _client, _started

    if _started:
        return
    if not is_enabled():
        logger.info("[discord] DISCORD_BOT_TOKEN not set — skipping")
        return

    try:
        import discord
        from discord.ext import commands
    except ImportError:
        logger.warning("[discord] discord.py not installed. Run: pip install 'discord.py>=2.3.0'")
        return

    intents = discord.Intents.default()
    intents.message_content = True

    _client = commands.Bot(command_prefix="!", intents=intents)

    @_client.event
    async def on_ready():
        logger.info(f"[discord] Logged in as {_client.user} (ID: {_client.user.id})")
        try:
            guild_id = os.getenv("DISCORD_GUILD_ID")
            if guild_id:
                guild = discord.Object(id=int(guild_id))
                _client.tree.copy_global_to(guild=guild)
                await _client.tree.sync(guild=guild)
            else:
                await _client.tree.sync()
        except Exception as e:
            logger.warning(f"[discord] Slash sync error: {e}")

    @_client.event
    async def on_message(message):
        if message.author == _client.user:
            return
        # Respond if bot is mentioned
        if _client.user in message.mentions:
            text = message.content.replace(f"<@{_client.user.id}>", "").strip()
            if text:
                if _is_rate_limited(str(message.author.id)):
                    await message.channel.send("Slow down — max 5 messages per minute.")
                else:
                    async with message.channel.typing():
                        response = await _get_narai_response(text, str(message.channel.id))
                    await _chunked_reply(message, response)
        await _client.process_commands(message)

    async def _chunked_reply(message, text: str):
        """Send long text in chunks."""
        for i in range(0, len(text), 1900):
            await message.channel.send(text[i:i + 1900])

    @_client.command(name="ask")
    async def ask_cmd(ctx, *, question: str):
        """Ask NarAI a question."""
        if _is_rate_limited(str(ctx.author.id)):
            await ctx.send("Slow down — max 5 messages per minute.")
            return
        async with ctx.typing():
            response = await _get_narai_response(question, str(ctx.channel.id))
        await _chunked_reply(ctx.message, response)

    @_client.command(name="bots")
    async def bots_cmd(ctx):
        """List running bots."""
        try:
            from core.bot_manager import list_bots
            running = list_bots()
            if not running:
                await ctx.send("No bots currently running.")
                return
            embed = discord.Embed(title="🤖 Running Bots", color=0x7c6af7)
            for b in running[:25]:
                status_icon = "🟢" if b.get("status") == "running" else "🔴"
                embed.add_field(
                    name=f"{status_icon} {b['name']}",
                    value=f"Status: {b.get('status', 'unknown')} | PID: {b.get('pid', '?')}",
                    inline=True
                )
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"Error: {e}")

    @_client.command(name="startbot")
    async def startbot_cmd(ctx, bot_name: str, category: str = ""):
        """Start a bot."""
        try:
            from core.bot_manager import start_bot as _start
            result = _start(bot_name, category)
            await ctx.send(f"✅ Bot `{bot_name}` started (PID {result.get('pid', '?')})")
        except Exception as e:
            await ctx.send(f"❌ {e}")

    @_client.command(name="stopbot")
    async def stopbot_cmd(ctx, bot_name: str):
        """Stop a bot."""
        try:
            from core.bot_manager import stop_bot as _stop
            _stop(bot_name)
            await ctx.send(f"🛑 Bot `{bot_name}` stopped")
        except Exception as e:
            await ctx.send(f"❌ {e}")

    @_client.command(name="generate")
    async def generate_cmd(ctx, *, prompt: str):
        """Generate code with AI."""
        async with ctx.typing():
            try:
                from core.code_engine import generate_code, validate_code
                code = generate_code(prompt)
                valid, err = validate_code(code)
                preview = code[:1500] + ("..." if len(code) > 1500 else "")
                status = "✅ Valid Python" if valid else f"⚠️ {err}"
                await ctx.send(f"**Generated code** ({status}):\n```python\n{preview}\n```")
            except Exception as e:
                await ctx.send(f"Code gen error: {e}")

    @_client.command(name="status")
    async def status_cmd(ctx):
        """Platform status."""
        try:
            from core.bot_manager import list_bots
            running = list_bots()
            embed = discord.Embed(title="📊 WheellsVerse Status", color=0x00ff88)
            embed.add_field(name="🤖 Running Bots", value=str(len(running)), inline=True)
            embed.add_field(name="🌐 API", value="Online", inline=True)
            embed.add_field(name="🧠 NarAI", value="Active", inline=True)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"Status error: {e}")

    # ── Slash commands ────────────────────────────────────────────────────────

    @_client.tree.command(name="ask", description="Ask NarAI a question")
    async def slash_ask(interaction: discord.Interaction, question: str):
        await interaction.response.defer()
        response = await _get_narai_response(question, str(interaction.channel_id))
        await interaction.followup.send(response[:2000])

    @_client.tree.command(name="bots", description="List running bots")
    async def slash_bots(interaction: discord.Interaction):
        try:
            from core.bot_manager import list_bots
            running = list_bots()
            text = "\n".join(f"{'🟢' if b.get('status') == 'running' else '🔴'} {b['name']}" for b in running) or "No bots running"
            await interaction.response.send_message(text)
        except Exception as e:
            await interaction.response.send_message(f"Error: {e}")

    @_client.tree.command(name="generate", description="Generate Python code with AI")
    async def slash_generate(interaction: discord.Interaction, prompt: str):
        await interaction.response.defer()
        try:
            from core.code_engine import generate_code
            code = generate_code(prompt)
            preview = code[:1500]
            await interaction.followup.send(f"```python\n{preview}\n```")
        except Exception as e:
            await interaction.followup.send(f"Error: {e}")

    @_client.tree.command(name="help", description="What NarAI can do")
    async def slash_help(interaction: discord.Interaction):
        embed = discord.Embed(
            title="🧠 NarAI",
            description="Ask me anything, or use a slash command:",
            color=0x00d4ff,
        )
        embed.add_field(name="/ask <question>", value="Ask NarAI anything", inline=False)
        embed.add_field(name="/subscribe", value="Join Insider — $19/mo, AI signals + private channel", inline=False)
        embed.add_field(name="/bots", value="List running WheellsVerse bots", inline=False)
        embed.add_field(name="/generate <prompt>", value="Generate Python code", inline=False)
        embed.add_field(name="/help", value="This message", inline=False)
        embed.set_footer(text="You can also @mention NarAI in any channel.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @_client.tree.command(name="subscribe", description="Subscribe to Insider — daily AI signals + private channel ($19/mo)")
    async def slash_subscribe(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            from narai.integrations import discord_subscription as ds
            price_id = os.getenv("STRIPE_PRICE_TG_GROUP", "")
            stripe_key = os.getenv("STRIPE_SECRET_KEY", "")
            base_url = os.getenv("APP_BASE_URL", "https://app.wheellsverse.com").rstrip("/")
            if not price_id or not stripe_key:
                await interaction.followup.send(
                    "Subscription system isn't configured yet. Please contact support.",
                    ephemeral=True,
                )
                return

            user_id = str(interaction.user.id)
            guild_id = str(interaction.guild_id) if interaction.guild_id else None
            token = ds.new_pairing_token(discord_user_id=user_id, discord_guild_id=guild_id)

            import stripe as _stripe
            _stripe.api_key = stripe_key
            session = _stripe.checkout.Session.create(
                mode="subscription",
                line_items=[{"price": price_id, "quantity": 1}],
                success_url=f"{base_url}/subscribe/success?goto=https://discord.com/channels/{guild_id or '@me'}",
                cancel_url=f"{base_url}/subscribe/cancelled",
                metadata={
                    "discord_pairing_token": token,
                    "discord_user_id": user_id,
                    "discord_guild_id": guild_id or "",
                    "product": "discord_role",
                },
                subscription_data={
                    "metadata": {
                        "discord_pairing_token": token,
                        "product": "discord_role",
                    },
                },
                allow_promotion_codes=True,
            )
            ds.attach_session(token, session.id)

            embed = discord.Embed(
                title="📡 Insider — $19/mo",
                description=(
                    "Daily AI-powered stock + crypto signals.\n"
                    "Cancel any time. No contracts. Pure alpha."
                ),
                color=0x00d4ff,
                url=session.url,
            )
            embed.add_field(name="✓ Subscribe here", value=f"[Open checkout]({session.url})", inline=False)
            embed.set_footer(text="After payment, your role is granted automatically.")
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logger.exception("subscribe slash failed")
            await interaction.followup.send(f"Couldn't start checkout: {e}", ephemeral=True)

    # Run bot
    token = os.getenv("DISCORD_BOT_TOKEN")
    _started = True
    try:
        await _client.start(token)
    except Exception as e:
        logger.error(f"[discord] Bot crashed: {e}")
        _started = False


async def stop_bot():
    global _started
    if _client and _started:
        try:
            await _client.close()
        except Exception:
            pass
        _started = False

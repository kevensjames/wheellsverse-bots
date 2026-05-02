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

# Per-guild Discord voice clients (populated by /voice join). Keyed by guild_id.
# Stays empty unless DISCORD_VOICE_ENABLED=true and someone runs /voice join.
_voice_clients: dict = {}

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


async def _get_narai_response(text: str, channel_id: str, user_id: str | None = None) -> str:
    """Get NarAI response for a Discord message.

    If user_id is provided, the user's RAG store (PDFs they've uploaded,
    research they've run) is searched and prepended to the system prompt.
    """
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

        # RAG context — user's own uploaded files + their research, if any match.
        # Bug-fix: rag.query returns hits with keys 'content' + 'source' (not
        # 'text'/'source_label'). Filter labels are exact-match in chromadb,
        # so we standardize on flat per-user labels: 'discord:{uid}' (uploads)
        # and 'discord:research:{uid}' (research drops).
        if user_id:
            try:
                from narai.core.rag import query as rag_query
                hits = rag_query(text, n=4, source_filter=f"discord:{user_id}")
                if not hits:
                    hits = rag_query(text, n=4,
                                     source_filter=f"discord:research:{user_id}")
                if hits:
                    ctx = "\n\n".join(
                        f"[{h.get('source','?')}]\n{(h.get('content') or '')[:1200]}"
                        for h in hits[:4]
                    )
                    sys_prompt += (
                        "\n\n---\nThe user has uploaded files / done research. "
                        "Use this context if relevant to their question:\n" + ctx
                    )
            except Exception as _rag_err:
                logger.warning(f"[discord] rag query skipped: {_rag_err}")

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
        from discord import app_commands
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

        # Attachment ingest — drop a file in any channel, NarAI puts it in
        # this user's RAG store so /ask + @mention can use it as context.
        if message.attachments:
            await _ingest_attachments(message)

        # Respond if bot is mentioned — either as a user or via its managed role.
        # Discord's "@NarAI" autocomplete inserts a role mention when the bot's
        # name matches a role; on_message.mentions only lists USER mentions, so
        # without the role check the bot looks unresponsive in normal usage.
        mentioned_directly = _client.user in message.mentions
        mentioned_via_role = False
        if message.guild is not None and message.role_mentions:
            bot_role_ids = {r.id for r in message.guild.me.roles}
            mentioned_via_role = any(r.id in bot_role_ids for r in message.role_mentions)

        if mentioned_directly or mentioned_via_role:
            text = message.content.replace(f"<@{_client.user.id}>", "")
            # Strip whichever bot role(s) were mentioned, too.
            if mentioned_via_role and message.guild is not None:
                for r in message.role_mentions:
                    if r in message.guild.me.roles:
                        text = text.replace(f"<@&{r.id}>", "")
            text = text.strip()
            if text:
                if _is_rate_limited(str(message.author.id)):
                    await message.channel.send("Slow down — max 5 messages per minute.")
                else:
                    async with message.channel.typing():
                        response = await _get_narai_response(
                            text,
                            str(message.channel.id),
                            user_id=str(message.author.id),
                        )
                    await _chunked_reply(message, response)
                    # Voice playback if a /voice join is active in this guild
                    if message.guild is not None:
                        vc = _voice_clients.get(message.guild.id)
                        if vc and vc.is_connected() and not vc.is_playing():
                            await _speak_in_voice(vc, response)
        await _client.process_commands(message)

    async def _speak_in_voice(voice_client, text: str):
        """Synthesize text via configured TTS provider and play through voice client."""
        try:
            import io
            from narai.voice.tts import get_tts
            provider = os.getenv("DISCORD_TTS_PROVIDER", "edge")
            tts = get_tts(provider)
            audio = await tts.synthesize(text[:1500])
            src = discord.FFmpegPCMAudio(io.BytesIO(audio), pipe=True)
            voice_client.play(src)
        except Exception as e:
            logger.warning(f"[discord] tts playback failed: {e}")

    async def _ingest_attachments(message):
        """Save each attachment to a temp file, push it through RAG, react.

        Files >10MB are skipped (RAG chunking would be expensive). Each file
        is namespaced by user_id so /ask only surfaces the asker's own docs.
        """
        import pathlib, tempfile
        for att in message.attachments:
            if att.size and att.size > 10 * 1024 * 1024:
                try:
                    await message.add_reaction("📦")  # too-big indicator
                except Exception:
                    pass
                continue
            ext = pathlib.Path(att.filename).suffix or ".bin"
            tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
            tmp.close()
            try:
                await att.save(tmp.name)
                from narai.core import rag
                # Bug-fix: chromadb where-clause is exact match. Use a flat
                # per-user label so /ask's source_filter=f"discord:{uid}"
                # actually finds these chunks. Filename is shown in the reply
                # below for traceability.
                label = f"discord:{message.author.id}"
                n_chunks = await rag.aingest(tmp.name, source_label=label)
                try:
                    await message.add_reaction("✅")
                except Exception:
                    pass
                await message.reply(
                    f"Ingested **{att.filename}** ({n_chunks} chunks). "
                    f"Mention me or use /ask to query it.",
                    mention_author=False,
                )
            except Exception as e:
                logger.warning(f"[discord] rag ingest failed for {att.filename}: {e}")
                try:
                    await message.add_reaction("⚠️")
                except Exception:
                    pass
            finally:
                try:
                    pathlib.Path(tmp.name).unlink(missing_ok=True)
                except Exception:
                    pass

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

    @_client.tree.command(name="ask", description="Ask NarAI a question (uses your uploaded files as context if relevant)")
    async def slash_ask(interaction: discord.Interaction, question: str):
        await interaction.response.defer()
        response = await _get_narai_response(
            question,
            str(interaction.channel_id),
            user_id=str(interaction.user.id),
        )
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

    # ── /stock <ticker> ──────────────────────────────────────────────────
    @_client.tree.command(name="stock",
                          description="Spot quote + AI forecast for a ticker (e.g. TSLA, BTC-USD)")
    async def slash_stock(interaction: discord.Interaction, ticker: str):
        await interaction.response.defer()
        sym = ticker.strip().upper()
        try:
            import asyncio as _aio
            from narai.integrations.subscriber_content import (
                _safe_quote, _safe_forecast, _arrow,
            )
            quote = await _aio.to_thread(_safe_quote, sym)
            fc    = await _aio.to_thread(_safe_forecast, sym)
        except Exception as e:
            await interaction.followup.send(f"Lookup failed: {e}")
            return

        if not quote:
            await interaction.followup.send(f"Couldn't fetch `{sym}`. Try a different symbol.")
            return

        embed = discord.Embed(title=f"📊 {sym}", color=0x00d4ff)
        embed.add_field(name="Last", value=f"${quote['last']:,.2f}", inline=True)
        embed.add_field(name="1d", value=f"{quote['change_pct']:+.2f}%", inline=True)
        if fc:
            embed.add_field(
                name="AI 5-day forecast",
                value=(f"{_arrow(fc.direction)} **{fc.direction}** "
                       f"({int(fc.confidence*100)}% conf)\n"
                       f"Target: ${fc.prediction:,.2f}"),
                inline=False,
            )
        embed.set_footer(text="Educational only — not investment advice.")
        await interaction.followup.send(embed=embed)

    # ── /research <topic> ────────────────────────────────────────────────
    @_client.tree.command(name="research",
                          description="AI research on any topic (auto-saves to your RAG store)")
    async def slash_research(interaction: discord.Interaction, topic: str):
        await interaction.response.defer()
        try:
            from narai.core.research import ResearchBrief, research as _research
        except Exception as e:
            await interaction.followup.send(f"Research module unavailable: {e}")
            return

        # Per-user RAG namespace so /ask filters can find this later.
        rag_label = f"discord:research:{interaction.user.id}:{int(time.time())}"
        try:
            result = await _research(ResearchBrief(
                query=topic, max_sources=6,
                ingest_to_rag=True, rag_label=rag_label,
            ))
            d = result.to_dict()
        except Exception as e:
            logger.exception("research slash failed")
            await interaction.followup.send(f"Research failed: {e}")
            return

        body = (d.get("combined") or "").strip() or "(no summary produced)"
        sources = d.get("summaries") or []
        embed = discord.Embed(
            title=f"🔬 {topic[:80]}",
            description=body[:3500],
            color=0x7c3aed,
        )
        if sources:
            src_lines = []
            for s in sources[:5]:
                title = (s.get("title") or "source")[:60]
                url = s.get("url") or ""
                src_lines.append(f"• [{title}]({url})" if url else f"• {title}")
            embed.add_field(name="Sources", value="\n".join(src_lines)[:1024], inline=False)
        embed.set_footer(text=f"Saved to RAG · ask follow-ups with /ask")
        await interaction.followup.send(embed=embed)

    # ── /voice join | leave ──────────────────────────────────────────────
    @_client.tree.command(name="voice", description="Voice controls — join | leave")
    @app_commands.choices(action=[
        app_commands.Choice(name="join",  value="join"),
        app_commands.Choice(name="leave", value="leave"),
    ])
    async def slash_voice(interaction: discord.Interaction,
                          action: app_commands.Choice[str]):
        # Choice wraps the value; downstream code expects a plain string.
        action = action.value if hasattr(action, "value") else str(action)
        if os.getenv("DISCORD_VOICE_ENABLED", "false").lower() not in {"true", "1", "yes"}:
            await interaction.response.send_message(
                "Voice is disabled. Set DISCORD_VOICE_ENABLED=true to enable.",
                ephemeral=True,
            )
            return

        action = action.strip().lower()
        gid = interaction.guild_id
        if gid is None:
            await interaction.response.send_message("Voice only works in a server.", ephemeral=True)
            return

        if action == "join":
            ch = interaction.user.voice and interaction.user.voice.channel
            if not ch:
                await interaction.response.send_message(
                    "Join a voice channel first, then run `/voice join`.", ephemeral=True)
                return
            try:
                if gid in _voice_clients and _voice_clients[gid].is_connected():
                    await _voice_clients[gid].move_to(ch)
                else:
                    _voice_clients[gid] = await ch.connect()
                await interaction.response.send_message(f"Joined 🔊 {ch.name}", ephemeral=True)
            except Exception as e:
                logger.exception("voice join failed")
                await interaction.response.send_message(f"Couldn't join voice: {e}", ephemeral=True)
        elif action == "leave":
            vc = _voice_clients.pop(gid, None)
            if vc:
                try:
                    await vc.disconnect(force=False)
                except Exception:
                    pass
            await interaction.response.send_message("Left voice.", ephemeral=True)
        else:
            await interaction.response.send_message(
                "Use `/voice join` or `/voice leave`.", ephemeral=True)

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

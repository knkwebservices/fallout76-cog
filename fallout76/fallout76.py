"""
Fallout76 — nuke launch codes and Minerva's rotation schedule, as a
Red-DiscordBot cog. Ported from the `fallout76` cog in TS6 Roadie
(a TeamSpeak bot) to work the same way on Discord.

Commands:
    [p]nukes              show today's nuke launch codes (via NukaCrypt)
    [p]minerva            show Minerva's current/upcoming vendor location
    [p]minervaset add     (admin) add a dated schedule entry
    [p]minervaset remove  (admin) remove a dated schedule entry
    [p]minervaset list    (admin) list all stored schedule entries
"""

import asyncio
from datetime import date, datetime
from typing import Optional

import aiohttp
import discord
from redbot.core import Config, checks, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box

NUKACRYPT_CODES_URL = "https://api.nukacrypt.com/api/codes"
DATE_FORMAT = "%Y-%m-%d"


def _parse_date(value: str) -> Optional[date]:
    try:
        return datetime.strptime(value.strip(), DATE_FORMAT).date()
    except ValueError:
        return None


class Fallout76(commands.Cog):
    """Fallout 76 nuke codes and Minerva's rotation schedule."""

    __version__ = "1.0.0"
    __author__ = "Rob Keck (knkwebservices)"

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xFA17076, force_registration=True)
        # Minerva's schedule is game-wide, not server-specific, so it's
        # stored globally rather than per-guild — same as TS6 Roadie.
        self.config.register_global(minerva_schedule=[])
        self.session = aiohttp.ClientSession()

    def cog_unload(self):
        asyncio.create_task(self.session.close())

    # ------------------------------------------------------------ nukes

    @commands.command()
    @commands.cooldown(1, 10, commands.BucketType.guild)
    async def nukes(self, ctx: commands.Context):
        """Show today's Fallout 76 nuke launch codes."""
        async with ctx.typing():
            try:
                async with self.session.get(
                    NUKACRYPT_CODES_URL, timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status != 200:
                        await ctx.send(
                            f"NukaCrypt returned an error (status {resp.status}). Try again later."
                        )
                        return
                    data = await resp.json()
            except (aiohttp.ClientError, asyncio.TimeoutError):
                await ctx.send("Couldn't reach NukaCrypt right now. Try again later.")
                return

        alpha = data.get("ALPHA") or data.get("alpha")
        bravo = data.get("BRAVO") or data.get("bravo")
        charlie = data.get("CHARLIE") or data.get("charlie")
        active_date = data.get("date") or data.get("active_date")

        if not any([alpha, bravo, charlie]):
            await ctx.send("NukaCrypt didn't return any codes — their API shape may have changed.")
            return

        embed = discord.Embed(
            title="☢️ Fallout 76 Nuke Launch Codes",
            color=await ctx.embed_color(),
        )
        if alpha:
            embed.add_field(name="Alpha", value=f"`{alpha}`", inline=True)
        if bravo:
            embed.add_field(name="Bravo", value=f"`{bravo}`", inline=True)
        if charlie:
            embed.add_field(name="Charlie", value=f"`{charlie}`", inline=True)
        if active_date:
            embed.add_field(name="Active since", value=str(active_date), inline=False)
        embed.set_footer(text="Codes courtesy of NukaCrypt (api.nukacrypt.com)")

        await ctx.send(embed=embed)

    # ---------------------------------------------------------- minerva

    @commands.command()
    async def minerva(self, ctx: commands.Context):
        """Show Minerva's current and upcoming vendor locations.

        Minerva's rotation skips weeks unpredictably, so this is a
        manually-maintained schedule rather than a calculated one — ask
        a server admin to keep it updated with `[p]minervaset add`.
        """
        schedule = await self.config.minerva_schedule()
        if not schedule:
            await ctx.send(
                "No Minerva schedule entries yet. Ask an admin to add some with "
                f"`{ctx.clean_prefix}minervaset add <YYYY-MM-DD> <location>`."
            )
            return

        today = date.today()
        parsed = []
        for entry in schedule:
            d = _parse_date(entry["date"])
            if d:
                parsed.append((d, entry["location"]))
        parsed.sort(key=lambda pair: pair[0])

        past = [p for p in parsed if p[0] <= today]
        future = [p for p in parsed if p[0] > today]

        current = past[-1] if past else None
        upcoming = future[:3]

        embed = discord.Embed(title="🛒 Minerva's Schedule", color=await ctx.embed_color())
        if current:
            embed.add_field(
                name="Current location",
                value=f"**{current[1]}** (since {current[0].isoformat()})",
                inline=False,
            )
        else:
            embed.add_field(name="Current location", value="Unknown — no past entries logged.", inline=False)

        if upcoming:
            lines = [f"{d.isoformat()} — {loc}" for d, loc in upcoming]
            embed.add_field(name="Upcoming", value="\n".join(lines), inline=False)

        embed.set_footer(text="Schedule is manually maintained — her rotation can skip weeks.")
        await ctx.send(embed=embed)

    @commands.group()
    @checks.admin_or_permissions(manage_guild=True)
    async def minervaset(self, ctx: commands.Context):
        """Manage Minerva's schedule entries."""

    @minervaset.command(name="add")
    async def minervaset_add(self, ctx: commands.Context, entry_date: str, *, location: str):
        """Add or update a schedule entry.

        `entry_date` must be in YYYY-MM-DD format.

        Example: `[p]minervaset add 2026-10-06 Foundation`
        """
        parsed = _parse_date(entry_date)
        if not parsed:
            await ctx.send("Date must be in `YYYY-MM-DD` format, e.g. `2026-10-06`.")
            return

        async with self.config.minerva_schedule() as schedule:
            # Replace an existing entry for the same date, if any
            schedule[:] = [e for e in schedule if e["date"] != parsed.isoformat()]
            schedule.append({"date": parsed.isoformat(), "location": location.strip()})

        await ctx.send(f"Set Minerva's location for {parsed.isoformat()} to **{location.strip()}**.")

    @minervaset.command(name="remove")
    async def minervaset_remove(self, ctx: commands.Context, entry_date: str):
        """Remove a schedule entry by date (YYYY-MM-DD)."""
        parsed = _parse_date(entry_date)
        if not parsed:
            await ctx.send("Date must be in `YYYY-MM-DD` format, e.g. `2026-10-06`.")
            return

        async with self.config.minerva_schedule() as schedule:
            before = len(schedule)
            schedule[:] = [e for e in schedule if e["date"] != parsed.isoformat()]
            removed = before != len(schedule)

        if removed:
            await ctx.send(f"Removed the entry for {parsed.isoformat()}.")
        else:
            await ctx.send(f"No entry found for {parsed.isoformat()}.")

    @minervaset.command(name="list")
    async def minervaset_list(self, ctx: commands.Context):
        """List every stored schedule entry, past and future."""
        schedule = await self.config.minerva_schedule()
        if not schedule:
            await ctx.send("No schedule entries stored yet.")
            return

        parsed = sorted(
            ((d, e["location"]) for e in schedule if (d := _parse_date(e["date"]))),
            key=lambda pair: pair[0],
        )
        lines = [f"{d.isoformat()} — {loc}" for d, loc in parsed]
        await ctx.send(box("\n".join(lines), lang="yaml"))

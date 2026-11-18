"""'Squads for today' prompt shown when play resumes (next day after stumps, or after a pause).

Both XIs are listed so captains can see who played before and substitute anyone who isn't there today
(`sub <out> <in>`). Play starts when the host or a captain presses **Start play** (or types `resume`),
or by itself when the timer runs out.
"""
import asyncio

import discord

from core.backend.permissions import can_control


class SquadCheckView(discord.ui.View):
    def __init__(self, match_instance, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.match_instance = match_instance
        self.message = None
        self.done = asyncio.Event()
        self.started_by = None

    async def finish(self, who=None):
        if self.done.is_set():
            return
        self.started_by = who
        self.done.set()
        self.stop()
        if self.message:
            try:
                text = f"▶️ Play started by **{who.name}**." if who is not None else "▶️ Play is starting."
                await self.message.edit(content=text, view=None)
            except Exception:
                pass

    @discord.ui.button(label="Start play", emoji="▶️", style=discord.ButtonStyle.green)
    async def start_play(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_control(self.match_instance, interaction.user):
            await interaction.response.send_message("Only the host or a captain can start play.", ephemeral=True)
            return
        if self.done.is_set():
            await interaction.response.send_message("Play has already started.", ephemeral=True)
            return
        await interaction.response.defer()
        await self.finish(interaction.user)

    async def on_timeout(self):
        await self.finish(None)

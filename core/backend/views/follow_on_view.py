import asyncio
import discord
from discord.ext import commands
import logging

logger = logging.getLogger(__name__)


class FollowOnView(discord.ui.View):
    def __init__(self, match_instance, message: discord.Message, allowed_user: discord.User, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.match_instance = match_instance
        self.message = message
        self.allowed_user = allowed_user
        self.done = asyncio.Event()

    async def answer_follow_on(self, interaction: discord.Interaction, enforce: bool):
        if interaction.user.id != self.allowed_user.id:
            await interaction.response.send_message(
                "You are not allowed to make this choice.",
                ephemeral=True
            )
            return
        if self.done.is_set():
            await interaction.response.send_message("The follow-on decision has already been made.", ephemeral=True)
            return
        await interaction.response.defer()
        self.match_instance.follow_on_enforced = enforce   # FIX (B3): was mi.innings_declared = True
        self.done.set()
        self.stop()
        verb = "enforced" if enforce else "declined"
        await self.message.edit(content=f"**{self.allowed_user.name}** {verb} the follow-on.", embed=None, view=None)

    @discord.ui.button(
        label="Enforce follow-on",
        style=discord.ButtonStyle.red)
    async def follow_on_yes_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await self.answer_follow_on(interaction, True)

    @discord.ui.button(
        label="Bat again ourselves",
        style=discord.ButtonStyle.green)
    async def follow_on_no_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await self.answer_follow_on(interaction, False)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.done.is_set():
            return
        self.match_instance.follow_on_enforced = False   # timeout = declined (normal alternation)
        self.done.set()
        if self.message:
            try:
                await self.message.edit(content="⏱️ No decision — the follow-on was not enforced.", embed=None, view=None)
            except Exception:
                pass

    async def wait_done(self):
        try:
            await asyncio.wait_for(self.done.wait(), timeout=(self.timeout or 120) + 5)
        except asyncio.TimeoutError:
            await self.on_timeout()

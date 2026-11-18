import discord
from discord.ext import commands
import logging
import random
from core.backend.views.batball_view import BatBallView
from core.config import config
from core.ui import theme
from core.backend.cpu import is_cpu

logger = logging.getLogger(__name__)


class TossView(discord.ui.View):
    def __init__(self, match_instance, message: discord.Message, allowed_user: discord.User):
        super().__init__(timeout=config.game["decision_timeout"])
        self.match_instance = match_instance
        self.message = message
        self.allowed_user = allowed_user
        self.decided = False

    async def choose_call(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.allowed_user.id:
            await interaction.response.send_message(
                "You are not allowed to make this choice.",
                ephemeral=True
            )
            return
        if self.decided:
            await interaction.response.send_message("The toss has already been decided.", ephemeral=True)
            return
        self.decided = True
        self.stop()
        await interaction.response.defer()
        await self.message.edit(view=None)
        await self.decide_toss_winner(button)

    @discord.ui.button(
        label="Heads",
        emoji="🪙",
        style=discord.ButtonStyle.green)
    async def create_heads_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await self.choose_call(interaction, button)

    @discord.ui.button(
        label="Tails",
        emoji="🪙",
        style=discord.ButtonStyle.blurple)
    async def create_tails_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await self.choose_call(interaction, button)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if not self.decided and self.message:   # FIX (B18): one edit, after the loop
            try:
                await self.message.edit(content=f"⏱️ Toss timed out. The host can run `{config.prefix}toss` again.", view=None)
            except Exception:
                pass

    async def auto_call(self):
        """A CPU captain calls the toss straight away."""
        if self.decided:
            return
        self.decided = True
        self.stop()
        if self.message:
            try:
                await self.message.edit(view=None)
            except Exception:
                pass
        await self.decide_by_label(random.choice(["Heads", "Tails"]))

    async def decide_toss_winner(self, button: discord.ui.Button):
        await self.decide_by_label(button.label)

    async def decide_by_label(self, call: str):
        mi = self.match_instance
        result = random.choice(["Heads", "Tails"])

        if result.lower() == call.lower():
            toss_winner = self.allowed_user
            won = True
        else:
            toss_winner = (
                mi.teamA_captain
                if self.allowed_user == mi.teamB_captain
                else mi.teamB_captain
            )
            won = False

        mi.toss_winner = toss_winner
        mi.toss_decision = None

        batballview = BatBallView(mi, None, toss_winner)

        winner_team = (
            mi.team_settings["Team A name"]
            if toss_winner == mi.teamA_captain
            else mi.team_settings["Team B name"]
        )

        embed = discord.Embed(
            title="🪙 The coin is in the air...",
            description=(
                f"{self.allowed_user.mention} called **{call}** — it landed **{result}**!\n\n"
                f"**{winner_team}** won the toss.\n{toss_winner.mention}, choose to **Bat** or **Bowl** first."
            ),
            color=theme.GOLD if won else theme.BLUE,
        )
        embed.set_footer(text=theme.footer_text("Toss"))
        batball_message = await self.message.reply(content=toss_winner.mention, embed=embed, view=batballview)
        batballview.message = batball_message
        if is_cpu(toss_winner):
            await batballview.auto_choose()

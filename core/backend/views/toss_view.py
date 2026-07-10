import discord
from discord.ext import commands
import logging
import random
from core.backend.views.batball_view import BatBallView

logger = logging.getLogger(__name__)


class TossView(discord.ui.View):
    def __init__(self, match_instance, message: discord.Message, allowed_user: discord.User):
        super().__init__(timeout=180) # 3 minutes timeout
        self.match_instance = match_instance
        self.message = message
        self.allowed_user = allowed_user

    @discord.ui.button(
        label="Heads",
        style=discord.ButtonStyle.green)
    async def create_heads_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if interaction.user.id != self.allowed_user.id:
            await interaction.response.send_message(
                "You are not allowed to make this choice.",
                ephemeral=True
            )
            return
        await interaction.response.defer()
        await self.decide_toss_winner(button)
        await self.message.edit(view=None)  

    @discord.ui.button(
        label="Tails",
        style=discord.ButtonStyle.green)
    async def create_tails_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if interaction.user.id != self.allowed_user.id:
            await interaction.response.send_message(
                "You are not allowed to make this choice.",
                ephemeral=True
            )
            return
        await interaction.response.defer()
        await self.decide_toss_winner(button)
        await self.message.edit(view=None)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
            await self.message.edit(content="Toss timed out.", view=None)



    async def decide_toss_winner(self, button: discord.ui.Button):
        result = random.choice(["Heads", "Tails"])

        if result.lower() == button.label.lower():
            toss_winner = self.allowed_user
            won = True
        else:
            toss_winner = (
                self.match_instance.teamA_captain
                if self.allowed_user == self.match_instance.teamB_captain
                else self.match_instance.teamB_captain
            )
            won = False

        self.match_instance.toss_winner = toss_winner

        batballview = BatBallView(
            self.match_instance,
            None,
            toss_winner
        )

        winner_team = (
            self.match_instance.team_settings["Team A name"]
            if toss_winner == self.match_instance.teamA_captain
            else self.match_instance.team_settings["Team B name"]
        )

        if won:
            text = (
                f"**{winner_team}** won the toss! "
                f"{toss_winner.mention} choose **Bat** or **Bowl**."
            )
        else:
            loser_team = (
                self.match_instance.team_settings["Team A name"]
                if self.allowed_user == self.match_instance.teamA_captain
                else self.match_instance.team_settings["Team B name"]
            )
            text = (
                f"**{winner_team}** won the toss.\n"
                f"{toss_winner.mention} choose **Bat** or **Bowl**."
            )

        batball_message = await self.message.reply(text, view=batballview)
        batballview.message = batball_message
            
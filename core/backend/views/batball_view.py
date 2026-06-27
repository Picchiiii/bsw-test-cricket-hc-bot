import discord
from discord.ext import commands
import logging
import random

logger = logging.getLogger(__name__)


class BatBallView(discord.ui.View):
    def __init__(self, match_instance, message: discord.Message, allowed_user: discord.User):
        super().__init__(timeout=None) 
        self.match_instance = match_instance
        self.message = message
        self.allowed_user = allowed_user

    @discord.ui.button(
        label="Bat",
        style=discord.ButtonStyle.green)
    async def create_bat_button(
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
        await self.bat_or_bowl_choice(button)
        await self.message.edit(view=None)

    @discord.ui.button(
        label="Bowl",
        style=discord.ButtonStyle.green)
    async def create_bowl_button(
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
        await self.bat_or_bowl_choice(button)
        await self.message.edit(view=None)

        
    async def bat_or_bowl_choice(self, button: discord.ui.Button):
        toss_winner_is_teamA = (
            self.match_instance.toss_winner == self.match_instance.teamA_captain
        )

        if button.label.lower() == "bat":
            # Toss winner bats
            self.match_instance.batting_turn = "A" if toss_winner_is_teamA else "B"
            self.match_instance.bowling_turn = "B" if toss_winner_is_teamA else "A"
            decision = "bat"

        else:
            # Toss winner bowls, so the other team bats
            self.match_instance.batting_turn = "B" if toss_winner_is_teamA else "A"
            self.match_instance.bowling_turn = "A" if toss_winner_is_teamA else "B"
            decision = "bowl"

        toss_winner_name = (
            self.match_instance.team_settings["Team A name"]
            if toss_winner_is_teamA
            else self.match_instance.team_settings["Team B name"]
        )

        await self.message.reply(
            f"Team {toss_winner_name} has decided to {decision} first. Use `.s` to start the match."
        )
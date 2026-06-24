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
    async def create_button(
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

    @discord.ui.button(
        label="Bowl",
        style=discord.ButtonStyle.green)
    async def create_button(
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
        result = random.choice(["Heads", "Tails"])
        if result.lower() == button.label.lower():
            self.match_instance.toss_winner = self.allowed_user
            return True
        else:
            return False

    async def bat_or_bowl_choice(self, button: discord.ui.Button):
        if button.label.lower() == "bat":
            self.match_instance.batting_team = self.match_instance.toss_winner
            self.match_instance.bowling_team = self.match_instance.teamA_captain if self.match_instance.toss_winner == self.match_instance.teamB_captain else self.match_instance.teamB_captain
            await self.message.reply(f"Team {self.match_instance.teamA_name if self.match_instance.toss_winner == self.match_instance.teamA_captain else self.match_instance.teamB_name} has decided to bat first. Use `.s` to start the match.")
        else:
            self.match_instance.bowling_team = self.match_instance.toss_winner
            self.match_instance.batting_team = self.match_instance.teamA_captain if self.match_instance.toss_winner == self.match_instance.teamB_captain else self.match_instance.teamB_captain
            await self.message.reply(f"Team {self.match_instance.teamA_name if self.match_instance.toss_winner == self.match_instance.teamA_captain else self.match_instance.teamB_name} has decided to bowl first. Use `.s` to start the match.")

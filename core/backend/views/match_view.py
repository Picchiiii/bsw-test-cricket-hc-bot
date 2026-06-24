import discord
from discord.ext import commands
import logging


logger = logging.getLogger(__name__)


class JoinMatchView(discord.ui.View):
    def __init__(self, players):
        super().__init__(timeout=None)
        self.players = players

    @discord.ui.button(
        label="Join Match",
        style=discord.ButtonStyle.green)
    async def create_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if interaction.user.id not in self.players:
            await interaction.response.defer()  
            self.players.append(interaction.user.id)
            await interaction.channel.send(
                f"**{interaction.user.name}** has joined the game. <:correct:1519046913666715749>"
            )
        else:
            await interaction.response.send_message(
                f"You have already joined the game.",
                ephemeral=True
            )
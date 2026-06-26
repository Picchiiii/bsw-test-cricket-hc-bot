import discord
from discord.ext import commands
import logging
from core.backend.instance import join_segregate_player

logger = logging.getLogger(__name__)


class JoinMatchView(discord.ui.View):
    def __init__(self, match_instance, message):
        super().__init__(timeout=180)
        self.match_instance = match_instance
        self.message = message

    @discord.ui.button(
        label="Join Match",
        style=discord.ButtonStyle.green)
    async def create_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if interaction.user.id not in self.match_instance.players:
            await interaction.response.defer()  
            self.match_instance.players.append(interaction.user)
            join_segregate_player(self.match_instance, interaction.user)

            await interaction.channel.send(
                f"**{interaction.user.name}** has joined the game. <:correct:1519046913666715749>"
            )
        else:
            await interaction.response.send_message(
                f"You have already joined the game.",
                ephemeral=True
            )


    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        await self.message.edit(view=self)
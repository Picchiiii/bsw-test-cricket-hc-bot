import discord
from discord.ext import commands
import logging

logger = logging.getLogger(__name__)


class YeetMatchView(discord.ui.View):
    def __init__(self, match_instance, message, ctx: commands.Context):
        super().__init__(timeout=60)
        self.match_instance = match_instance
        self.message = message
        self.ctx = ctx

    @discord.ui.button(
        label="Yes",
        style=discord.ButtonStyle.red)
    async def yes_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        
        if not interaction.user.id == self.match_instance.host.id:
            await interaction.response.send_message("Only the host can yeet the match.", ephemeral=True)
            return
        
        await interaction.response.defer()
        del self.ctx.bot.active_matches[self.match_instance.channel.id]
        await self.message.edit(content="The match has been yeeted! :leaves:", view=None)


    @discord.ui.button(
            label="No",
            style=discord.ButtonStyle.green)
    async def no_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
    
        if not interaction.user.id == self.match_instance.host.id:
            await interaction.response.send_message("Only the host can yeet the match.", ephemeral=True)
            return
        
        await interaction.response.defer()
        await self.message.edit(content="The yeet has been canceled.", view=None)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        await self.message.edit(content="The prompt has timed out.", view=self)
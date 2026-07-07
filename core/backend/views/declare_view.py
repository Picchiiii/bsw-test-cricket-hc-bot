import discord
import logging

logger = logging.getLogger(__name__)


class DeclarationView(discord.ui.View):
    def __init__(self, match_instance, message: discord.Message, allowed_user: discord.User):
        super().__init__(timeout=120) # 2 minutes timeout
        self.match_instance = match_instance
        self.message = message
        self.allowed_user = allowed_user

    @discord.ui.button(
        label="Yes",
        style=discord.ButtonStyle.green)
    async def create_yes_button(
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
        self.match_instance.innings_declared = True
        await self.message.edit(content=f"**{self.allowed_user.name}** has declared the innings.", view=None)  

    @discord.ui.button(
        label="No",
        style=discord.ButtonStyle.green)
    async def create_no_button(
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
        await self.message.edit(content=f"**{self.allowed_user.name}** has chosen not to declare the innings.", view=None)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
            await self.message.edit(content="Declaration timed out.")

        
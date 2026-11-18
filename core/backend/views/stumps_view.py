import discord

from core.backend.permissions import can_control


class StumpsView(discord.ui.View):
    """'Start next day' button shown at stumps. Same effect as the resume command."""

    def __init__(self, match_instance):
        super().__init__(timeout=None)
        self.match_instance = match_instance
        self.message = None

    @discord.ui.button(label="Start next day", emoji="☀️", style=discord.ButtonStyle.green)
    async def next_day(self, interaction: discord.Interaction, button: discord.ui.Button):
        mi = self.match_instance
        if not can_control(mi, interaction.user):
            await interaction.response.send_message("Only the host or a captain can start the next day.", ephemeral=True)
            return
        if not mi.stumps_called or mi.game is None:
            await interaction.response.send_message("Play is already in progress.", ephemeral=True)
            return
        await interaction.response.defer()
        what = mi.game.resume_play()
        self.stop()
        try:
            await self.message.edit(view=None)
        except Exception:
            pass
        if what:
            await interaction.channel.send(what)

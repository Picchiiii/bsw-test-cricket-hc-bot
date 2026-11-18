import discord
from discord.ext import commands
import logging
from core.backend.lobby import try_join, try_leave, lobby_embed

logger = logging.getLogger(__name__)


class JoinMatchView(discord.ui.View):
    """Lobby card buttons. Applies exactly the same rules as the join/leave commands (fixes B17)."""

    def __init__(self, match_instance, message):
        super().__init__(timeout=900)
        self.match_instance = match_instance
        self.message = message

    async def refresh_card(self):
        if self.message:
            try:
                await self.message.edit(embed=lobby_embed(self.match_instance), view=self)
            except Exception:
                pass

    @discord.ui.button(
        label="Join Match",
        emoji="🏏",
        style=discord.ButtonStyle.green)
    async def create_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        mi = self.match_instance
        if interaction.client.active_matches.get(mi.channel.id) is not mi:
            await interaction.response.send_message("This lobby is no longer active.", ephemeral=True)
            return
        if getattr(mi, "tournament", None):
            await interaction.client.tournaments.refresh_rosters(mi)
        ok, msg = try_join(mi, interaction.user)
        if not ok:
            await interaction.response.send_message(msg, ephemeral=True)
            return
        await interaction.response.defer()
        await interaction.channel.send(msg)
        await self.refresh_card()

    @discord.ui.button(
        label="Leave",
        style=discord.ButtonStyle.grey)
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        mi = self.match_instance
        ok, msg = try_leave(mi, interaction.user)
        if not ok:
            await interaction.response.send_message(msg, ephemeral=True)
            return
        await interaction.response.defer()
        await interaction.channel.send(msg)
        await self.refresh_card()

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

import discord
from discord.ext import commands
import logging

logger = logging.getLogger(__name__)


async def yeet(bot, match_instance):
    """Remove a lobby, or abandon a running match (its game loop cleans up and saves nothing)."""
    mi = match_instance
    if mi.game_started and mi.task is not None and not mi.task.done():
        mi.match_abandoned = True
        mi.interrupt.set()
        mi.resume_event.set()      # wake it up if it is waiting at stumps / pause
        for v in list(mi.pending_views.values()):
            v.stop()
        return
    if mi.game_started and mi.game is not None:
        # no running task (e.g. paused after an error / restored but not resumed)
        mi.match_abandoned = True
        await mi.game.abandon()
        return
    if bot.active_matches.get(mi.channel.id) is mi:
        del bot.active_matches[mi.channel.id]
    store = getattr(bot, "store", None)
    if store is not None:
        await store.delete_state(mi)


class YeetMatchView(discord.ui.View):
    def __init__(self, match_instance, message, ctx: commands.Context):
        super().__init__(timeout=60)
        self.match_instance = match_instance
        self.message = message
        self.ctx = ctx
        self.answered = False

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
        if self.answered:
            return
        self.answered = True
        self.stop()
        await interaction.response.defer()
        await self.message.edit(content="The match has been yeeted! :leaves:", view=None)
        await yeet(self.ctx.bot, self.match_instance)

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
        self.answered = True
        self.stop()
        await interaction.response.defer()
        await self.message.edit(content="The yeet has been canceled.", view=None)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if not self.answered and self.message:
            try:
                await self.message.edit(content="The prompt has timed out.", view=self)
            except Exception:
                pass

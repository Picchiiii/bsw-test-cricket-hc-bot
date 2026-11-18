import discord
import logging

from core.ui import theme

logger = logging.getLogger(__name__)


def declaration_block_reason(mi, user) -> str | None:
    """Rules for declaring (spec §6). Returns a reason string if the declaration is not allowed."""
    if not mi.game_started or mi.phase != "innings":
        return "There is no innings in progress."
    if mi.stumps_called:
        return "You can't declare during stumps."
    batting_captain = mi.captain(mi.batting_turn)
    if user != batting_captain:
        return "Only the captain of the batting team can declare."
    if mi.innings == 4:
        return "You can't declare in the final innings."
    if mi.innings_declared:
        return "The innings has already been declared."
    min_overs = mi.match_settings.get('min_declare_overs', mi.min_declare_overs)
    if mi.overs < min_overs:
        return f"At least **{min_overs}** overs must be bowled in this innings before declaring (currently {mi.overs})."
    return None


class DeclarationView(discord.ui.View):
    def __init__(self, match_instance, message: discord.Message, allowed_user: discord.User):
        super().__init__(timeout=120)  # 2 minutes timeout
        self.match_instance = match_instance
        self.message = message
        self.allowed_user = allowed_user
        self.answered = False

    @discord.ui.button(
        label="Yes, declare",
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
        mi = self.match_instance
        reason = declaration_block_reason(mi, interaction.user)
        if reason:
            await interaction.response.send_message(reason, ephemeral=True)
            return
        self.answered = True
        self.stop()
        await interaction.response.defer()
        mi.innings_declared = True
        mi.declared = True
        mi.interrupt.set()   # stop waiting for the current ball immediately
        await self.message.edit(
            content=None,
            embed=theme.embed("Innings declared!",
                              f"**{self.allowed_user.name}** has declared the innings closed at "
                              f"**{mi.score}/{mi.wickets}** ({mi.overs}.{mi.balls_this_over}).", theme.GOLD),
            view=None)

    @discord.ui.button(
        label="No",
        style=discord.ButtonStyle.grey)
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
        self.answered = True
        self.stop()
        await interaction.response.defer()
        await self.message.edit(content=f"**{self.allowed_user.name}** has chosen not to declare the innings.", view=None)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if not self.answered and self.message:
            try:
                await self.message.edit(content="Declaration timed out.", view=None)
            except Exception:
                pass

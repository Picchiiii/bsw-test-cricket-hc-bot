import discord
from discord.ext import commands
import logging
from core.config import config
from core.ui import theme

logger = logging.getLogger(__name__)


class BatBallView(discord.ui.View):
    def __init__(self, match_instance, message: discord.Message, allowed_user: discord.User):
        super().__init__(timeout=config.game["decision_timeout"])
        self.match_instance = match_instance
        self.message = message
        self.allowed_user = allowed_user
        self.decided = False

    async def choose_side(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.allowed_user.id:
            await interaction.response.send_message(
                "You are not allowed to make this choice.",
                ephemeral=True
            )
            return
        if self.decided or self.match_instance.game_started:
            await interaction.response.send_message("This choice has already been made.", ephemeral=True)
            return
        self.decided = True
        self.stop()
        await interaction.response.defer()
        await self.bat_or_bowl_choice(button)
        await self.message.edit(view=None)

    @discord.ui.button(
        label="Bat",
        emoji="🏏",
        style=discord.ButtonStyle.green)
    async def create_bat_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await self.choose_side(interaction, button)

    @discord.ui.button(
        label="Bowl",
        emoji="🥎",
        style=discord.ButtonStyle.blurple)
    async def create_bowl_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await self.choose_side(interaction, button)

    async def on_timeout(self):
        if self.decided:
            return
        # Nobody chose: clear the toss so the host can redo it.
        self.match_instance.toss_winner = None
        if self.message:
            try:
                await self.message.edit(
                    content=f"⏱️ No choice was made. The host can run `{config.prefix}toss` again.", view=None)
            except Exception:
                pass

    async def auto_choose(self):
        """A CPU toss winner chooses to bat."""
        if self.decided or self.match_instance.game_started:
            return
        self.decided = True
        self.stop()
        await self.choose_by_label("Bat")
        if self.message:
            try:
                await self.message.edit(view=None)
            except Exception:
                pass

    async def bat_or_bowl_choice(self, button: discord.ui.Button):
        await self.choose_by_label(button.label)

    async def choose_by_label(self, label: str):
        mi = self.match_instance
        toss_winner_is_teamA = (mi.toss_winner == mi.teamA_captain)

        if label.lower() == "bat":
            # Toss winner bats
            mi.batting_turn = "A" if toss_winner_is_teamA else "B"
            mi.bowling_turn = "B" if toss_winner_is_teamA else "A"
            decision = "bat"
        else:
            # Toss winner bowls, so the other team bats
            mi.batting_turn = "B" if toss_winner_is_teamA else "A"
            mi.bowling_turn = "A" if toss_winner_is_teamA else "B"
            decision = "bowl"

        mi.toss_decision = decision
        mi.match_settings['team_batting_first'] = decision
        toss_winner_name = (
            mi.team_settings["Team A name"]
            if toss_winner_is_teamA
            else mi.team_settings["Team B name"]
        )

        embed = discord.Embed(
            description=(
                f"**{toss_winner_name}** won the toss and elected to **{decision}** first.\n"
                f"{mi.team_name(mi.batting_turn)} will bat first.\n\n"
                f"Host, use `{config.prefix}start` to start the match. {theme.STADIUM}"
            ),
            color=theme.GREEN,
        )
        await self.message.reply(embed=embed)

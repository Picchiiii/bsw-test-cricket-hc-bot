"""Buttons and menus used by tournament commands."""
import discord

from core.config import config
from core.tournament import logic
from core.tournament.actions import TournamentError
from core.ui import theme

P = config.prefix


async def _deny(interaction, text: str):
    await interaction.response.send_message(text, ephemeral=True)


class ConfirmView(discord.ui.View):
    """Yes / No for destructive actions. `await view.wait()` then read `view.value`."""

    def __init__(self, user_id: int, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.value = None
        self.message = None

    async def answer(self, interaction, value: bool):
        if interaction.user.id != self.user_id:
            await _deny(interaction, "Only the person who ran the command can answer.")
            return
        if self.value is not None:
            return
        self.value = value
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="Yes, do it", style=discord.ButtonStyle.red)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.answer(interaction, True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.answer(interaction, False)

    async def on_timeout(self):
        if self.message is not None:
            try:
                await self.message.edit(content="Timed out — nothing was changed.", view=None)
            except Exception:
                pass


class FixtureSelect(discord.ui.Select):
    def __init__(self, fixtures: list[dict]):
        options = []
        for fx in fixtures[:25]:
            stage = logic.stage_label(fx["stage"]) if fx["stage"] != "group" else (
                f"Pool {fx['group_name']}" if fx["group_name"] else f"Round {fx['round']}")
            options.append(discord.SelectOption(
                label=f"#{fx['number']} {fx['_a']['name']} v {fx['_b']['name']}"[:100],
                description=stage[:100], value=str(fx["number"])))
        super().__init__(placeholder="Which tournament match is this?", options=options)

    async def callback(self, interaction: discord.Interaction):
        await self.view.choose(interaction, int(self.values[0]))


class FixturePickView(discord.ui.View):
    """Pick which fixture a lobby is. Only the person who asked can choose."""

    def __init__(self, bot, mi, t: dict, fixtures: list[dict], user_id: int):
        super().__init__(timeout=config.game["decision_timeout"])
        self.bot, self.mi, self.t, self.user_id = bot, mi, t, user_id
        self.fixtures = {fx["number"]: fx for fx in fixtures}
        self.message = None
        self.done = False
        self.add_item(FixtureSelect(fixtures))

    async def choose(self, interaction, number: int):
        if interaction.user.id != self.user_id:
            await _deny(interaction, "Only the person who ran the command can choose.")
            return
        if self.done:
            return
        if self.bot.active_matches.get(self.mi.channel.id) is not self.mi:
            await _deny(interaction, "This lobby is no longer active.")
            return
        try:
            text = await self.bot.tournaments.mark_lobby(self.mi, self.t, self.fixtures[number], interaction.user)
        except TournamentError as e:
            await _deny(interaction, str(e))
            return
        self.done = True
        self.stop()
        await interaction.response.edit_message(content=text, embed=None, view=None)

    async def on_timeout(self):
        if self.message is not None and not self.done:
            try:
                await self.message.edit(content=f"No match was picked. Use `{P}tm <match number>` when you're ready.", view=None)
            except Exception:
                pass


class TournamentPromptView(discord.ui.View):
    """Shown after `create` while a tournament is running: is this a tournament match?"""

    def __init__(self, bot, mi, t: dict):
        super().__init__(timeout=max(60, config.game["decision_timeout"]))
        self.bot, self.mi, self.t = bot, mi, t
        self.message = None
        self.done = False

    async def guard(self, interaction) -> bool:
        if interaction.user.id != self.mi.host.id:
            await _deny(interaction, "Only the match host can answer.")
            return False
        if self.done or self.bot.active_matches.get(self.mi.channel.id) is not self.mi or self.mi.game_started:
            await _deny(interaction, "This prompt is no longer active.")
            return False
        return True

    @discord.ui.button(label="Yes — tournament match", emoji="🏆", style=discord.ButtonStyle.green)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.guard(interaction):
            return
        mgr = self.bot.tournaments
        organizer = await mgr.is_organizer(self.t, interaction.user)
        options = await mgr.playable(self.t, interaction.user, organizer)
        if not options:
            await _deny(interaction, "There is no tournament match you can start right now. Captains can start their own "
                                     f"team's fixtures; organisers can start any (`{P}tour fixtures`).")
            return
        self.done = True
        self.stop()
        if len(options) == 1:
            try:
                text = await mgr.mark_lobby(self.mi, self.t, options[0], interaction.user)
            except TournamentError as e:
                text = str(e)
            await interaction.response.edit_message(content=text, embed=None, view=None)
            return
        view = FixturePickView(self.bot, self.mi, self.t, options, interaction.user.id)
        view.message = interaction.message
        await interaction.response.edit_message(content="Which tournament match is this?", embed=None, view=view)

    @discord.ui.button(label="No — friendly", style=discord.ButtonStyle.grey)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.guard(interaction):
            return
        self.done = True
        self.stop()
        await interaction.response.edit_message(
            content=f"👍 Friendly match — it won't count for **{self.t['name']}**. (Changed your mind? `{P}tm`)",
            embed=None, view=None)

    async def on_timeout(self):
        if self.message is not None and not self.done:
            try:
                await self.message.edit(content=f"Treated as a friendly. Use `{P}tm` to make it a tournament match.",
                                        embed=None, view=None)
            except Exception:
                pass


class InviteView(discord.ui.View):
    """Accept / decline a team invite (the invite also works later with `t accept`)."""

    def __init__(self, bot, tournament_id: str, team: dict, user_id: int):
        super().__init__(timeout=600)
        self.bot, self.tournament_id, self.team, self.user_id = bot, tournament_id, team, user_id
        self.message = None
        self.done = False

    async def respond(self, interaction, action: str):
        if interaction.user.id != self.user_id:
            await _deny(interaction, "This invite isn't for you.")
            return
        if self.done:
            return
        from core.tournament import store
        t = await store.get(self.bot.db, self.tournament_id)
        if t is None:
            await _deny(interaction, "That tournament no longer exists.")
            return
        try:
            result = await self.bot.tournaments.run(interaction.guild, t, interaction.user, action,
                                                    {"team": self.team["team_id"]})
        except TournamentError as e:
            await _deny(interaction, str(e))
            return
        self.done = True
        self.stop()
        await interaction.response.edit_message(content=result.message, embed=None, view=None)

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.green)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.respond(interaction, "invite.accept")

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.grey)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.respond(interaction, "invite.decline")

    async def on_timeout(self):
        if self.message is not None and not self.done:
            try:
                await self.message.edit(view=None)
            except Exception:
                pass


def prompt_embed(t: dict) -> discord.Embed:
    return theme.embed(f"🏆 {t['name']} is running in this server",
                       "Is this a **tournament match**? Tournament matches use the tournament's teams and rules and "
                       "count for the table and stats.", theme.GOLD)

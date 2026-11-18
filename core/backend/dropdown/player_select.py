import asyncio
import discord
from core.backend.utils import get_performance
from core.ui import theme


class PlayerSelect(discord.ui.Select):
    def __init__(self, player_type: str, player_data: dict, allowed_user: discord.User):
        self.player_type = player_type
        self.player_data = player_data
        self.allowed_user = allowed_user

        options = []

        for player_id, player in player_data.items():
            if not isinstance(player_id, int):
                continue

            performance = get_performance(self.player_type, player)

            options.append(
                discord.SelectOption(
                    label=player["player_name"][:100],
                    description=performance[:100],
                    value=str(player_id),
                    emoji=theme.BAT if player_type == "batsman" else theme.BALL,
                )
            )

        super().__init__(
            placeholder=f"Select the next {'batter' if player_type == 'batsman' else 'bowler'}...",
            min_values=1,
            max_values=1,
            options=options[:25]
        )

    async def callback(self, interaction: discord.Interaction):
        view: "PlayerView" = self.view
        mi = view.match_instance
        allowed = mi.captain(view.side) if (mi is not None and view.side) else self.allowed_user
        if interaction.user != allowed:
            await interaction.response.send_message(
                "You are not allowed to make this choice.",
                ephemeral=True
            )
            return
        if view.chosen is not None:
            await interaction.response.send_message("A player has already been selected.", ephemeral=True)
            return

        player_id = int(self.values[0])
        await interaction.response.defer()
        await view.apply_choice(player_id, auto=False)


class PlayerView(discord.ui.View):
    """Captain's dropdown for the next batter/bowler.

    The selection is written to match_instance.nxt_batsman / nxt_bowler. If the captain doesn't
    respond in time the first eligible player is auto-picked (spec §8.2) so the match never stalls.
    """

    def __init__(self, player_type: str, player_data: dict, allowed_user: discord.User,
                 match_instance=None, side: str = None, timeout: float = 30):
        super().__init__(timeout=timeout)
        self.message = None
        self.player_type = player_type
        self.player_data = player_data
        self.allowed_user = allowed_user
        self.match_instance = match_instance
        self.side = side
        self.chosen = None
        self.auto_picked = False
        self.done = asyncio.Event()
        self.add_item(PlayerSelect(player_type, player_data, allowed_user))

    def resolve_member(self, player_id: int):
        if self.match_instance is not None:
            m = self.match_instance.member(player_id)
            if m is not None:
                return m
        guild = getattr(getattr(self.message, "channel", None), "guild", None)
        return guild.get_member(player_id) if guild else None

    async def apply_choice(self, player_id: int, auto: bool):
        if self.chosen is not None:
            return
        member = self.resolve_member(player_id)
        if member is None:
            return
        self.chosen = member
        self.auto_picked = auto
        mi = self.match_instance
        if mi is not None:
            if self.player_type == "batsman":
                mi.nxt_batsman = member
            else:
                mi.nxt_bowler = member
        self.done.set()
        role = "batter" if self.player_type == "batsman" else "bowler"
        name = self.player_data.get(player_id, {}).get("player_name", member.name)
        if auto:
            text = f"⏱️ {self.allowed_user.mention} didn't pick in time — auto-picked **{name}** as the next {role}."
        else:
            text = f"{theme.TICK} Next {role} is **{name}**!"
        self.stop()
        if self.message:
            try:
                await self.message.edit(content=text, view=None)
            except Exception:
                pass

    async def on_timeout(self):  # FIX (B9): a real method of the class, not nested in __init__
        for child in self.children:
            child.disabled = True
        if self.chosen is not None:
            return
        ids = [pid for pid in self.player_data if isinstance(pid, int)]
        if ids:
            await self.apply_choice(ids[0], auto=True)
        else:
            self.done.set()
            if self.message:
                try:
                    await self.message.edit(content="No eligible players to choose from.", view=None)
                except Exception:
                    pass

    async def wait_done(self, extra: float = 5.0) -> bool:
        """Wait until a choice is made (manually or auto). Returns True if a player was chosen."""
        try:
            await asyncio.wait_for(self.done.wait(), timeout=(self.timeout or 30) + extra)
        except asyncio.TimeoutError:
            await self.on_timeout()
        return self.chosen is not None

import asyncio
import discord

from core.ui import theme


class PickButton(discord.ui.Button):
    def __init__(self, value: int, role: str):
        style = discord.ButtonStyle.grey
        if value in (4, 6):
            style = discord.ButtonStyle.green
        if role == "bowler" and value == 0:
            style = discord.ButtonStyle.red
        label = f"{value}" if not (role == "bowler" and value == 0) else "0 (NB)"
        super().__init__(label=label, style=style, row=0 if value <= 3 else 1)
        self.value = value

    async def callback(self, interaction: discord.Interaction):
        view: "PickView" = self.view
        if interaction.user.id != view.player.id:
            await interaction.response.send_message("This isn't your ball!", ephemeral=True)
            return
        if view.future.done():
            await interaction.response.send_message("You've already locked in a number for this ball.", ephemeral=True)
            return
        if view.is_finished():
            await interaction.response.send_message("This ball is already over — wait for the next prompt.", ephemeral=True)
            return
        view.lock_in(self.value)
        try:
            await interaction.response.edit_message(view=view)
        except discord.HTTPException:
            pass   # prompt was deleted at the same moment; the pick still counts if it was in time


class PickView(discord.ui.View):
    """0-6 buttons on the DM prompt. Typing the number in DMs works too (original behaviour)."""

    def __init__(self, player, role: str, timeout: float):
        super().__init__(timeout=timeout + 5)
        self.player = player
        self.role = role
        self.message = None
        self.future: asyncio.Future = asyncio.get_event_loop().create_future()
        for v in range(7):
            self.add_item(PickButton(v, role))

    def lock_in(self, value: int):
        if not self.future.done():
            self.future.set_result(value)
        for child in self.children:
            child.disabled = True
            if isinstance(child, PickButton) and child.value == value:
                child.style = discord.ButtonStyle.blurple
                child.label = f"{child.label} ✓"

    async def future_wait(self):
        return await asyncio.shield(self.future)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True

import discord


class Paginator(discord.ui.View):
    """◀ ▶ buttons over a list of embeds. Only the invoking user can flip pages."""

    def __init__(self, pages: list[discord.Embed], owner_id: int, timeout: float = 180):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.owner_id = owner_id
        self.index = 0
        self.message = None
        self.sync_buttons()

    def sync_buttons(self):
        self.prev.disabled = self.index == 0
        self.next.disabled = self.index >= len(self.pages) - 1
        self.counter.label = f"{self.index + 1}/{len(self.pages)}"

    async def flip_page(self, interaction: discord.Interaction, delta: int):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Run the command yourself to flip pages.", ephemeral=True)
            return
        self.index = max(0, min(len(self.pages) - 1, self.index + delta))
        self.sync_buttons()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.grey)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.flip_page(interaction, -1)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.blurple, disabled=True)
    async def counter(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.grey)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.flip_page(interaction, 1)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


async def send_pages(ctx, pages: list[discord.Embed]):
    if len(pages) == 1:
        return await ctx.send(embed=pages[0])
    view = Paginator(pages, ctx.author.id)
    view.message = await ctx.send(embed=pages[0], view=view)
    return view.message

import discord
import logging

from core.ui import theme

logger = logging.getLogger(__name__)


class ChannelLinkView(discord.ui.View):
    def __init__(self, match_instance):
        super().__init__(timeout=60)  # 1 minute timeout
        self.mi = match_instance

        url = getattr(self.mi.channel, "jump_url", None)
        if url:
            self.add_item(
                discord.ui.Button(
                    label="Back to Pavilion",
                    style=discord.ButtonStyle.link,
                    url=url
                )
            )

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


class MatchLinksView(discord.ui.View):
    """Link buttons under the result card (website scorecard)."""

    def __init__(self, match_instance):
        super().__init__(timeout=None)
        url = theme.match_url(match_instance.match_id)
        if url:
            self.add_item(discord.ui.Button(label="Full scorecard", emoji="📊", style=discord.ButtonStyle.link, url=url))

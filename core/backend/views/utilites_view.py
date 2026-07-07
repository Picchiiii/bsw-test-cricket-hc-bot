import discord
import logging


logger = logging.getLogger(__name__)

class ChannelLinkView(discord.ui.View):
    def __init__(self, match_instance):
        super().__init__(timeout=60) # 1 minute timeout
        self.mi = match_instance

        self.add_item(
            discord.ui.Button(
                label="Back to Pavillion",
                style=discord.ButtonStyle.link,
                url=self.mi.channel.jump_url
            )
        )


    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
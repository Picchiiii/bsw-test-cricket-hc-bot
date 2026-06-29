import discord
from core.backend.utils import get_performance

class PlayerSelect(discord.ui.Select):
    def __init__(self, player_type: str, player_data: dict):
        self.player_type = player_type
        self.player_data = player_data

        options = []

        for player_id, player in player_data.items():
            if not isinstance(player_id, int):
                continue

            performance = get_performance(self.player_type, player)

            options.append(
                discord.SelectOption(
                    label=player["player_name"],
                    description=performance,
                    value=str(player_id)
                )
            )

        super().__init__(
            placeholder="Select an option...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        player_id = int(self.values[0])  
        player = self.player_data[player_id]

        await interaction.response.defer()

        match_instance = interaction.client.active_matches.get(interaction.channel.id)
        _player = interaction.guild.get_member(player_id)

        if self.player_type == "batsman":
            match_instance.curr_batsman = _player
        else:
            match_instance.curr_bowler = _player

        await self.view.message.edit(
            content=f"Player has been selected:\nNext {self.player_type} is **{player['player_name']}!**.",
            view=None
        )

class PlayerView(discord.ui.View):
    def __init__(self, player_type: str, player_data: dict):
        super().__init__()
        self.message = None
        self.add_item(PlayerSelect(player_type, player_data))
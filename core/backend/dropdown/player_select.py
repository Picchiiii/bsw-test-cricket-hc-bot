import discord
from core.backend.utils import get_performance

class PlayerSelect(discord.ui.Select):
    def __init__(self, type: str, player_data: dict): ## Player data will be a dict and will be sent from the team_stats dict
        options = []

        for player_id, player in player_data.items():
            if not isinstance(player_id, int):
                continue

            performance = get_performance(type, player)

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
        player_id = self.values[0]

        await interaction.response.send_message(
            f"Selected value: {player_id}",
            ephemeral=True
        )


class PlayerView(discord.ui.View):
    def __init__(self, type: str, player_data: dict):
        super().__init__()
        self.add_item(PlayerSelect(type, player_data))
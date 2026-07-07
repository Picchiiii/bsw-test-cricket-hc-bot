import discord
from core.backend.utils import get_performance

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
        if interaction.user.id != self.allowed_user.id:
            await interaction.response.send_message(
                "You are not allowed to make this choice.",
                ephemeral=True
            )
            return
        
        player_id = int(self.values[0])  
        player = self.player_data[player_id]

        await interaction.response.defer()

        match_instance = interaction.client.active_matches.get(interaction.channel.id)
        _player = interaction.guild.get_member(player_id)

        if self.player_type == "batsman":
            match_instance.nxt_batsman = _player
        else:
            match_instance.nxt_bowler = _player

        await self.view.message.edit(
            content=f"Player has been selected:\nNext {self.player_type} is **{player['player_name']}!**.",
            view=None
        )
    
class PlayerView(discord.ui.View):
    def __init__(self, player_type: str, player_data: dict, allowed_user: discord.User):
        super().__init__(timeout=20)  # 2 minutes timeout
        self.message = None
        self.add_item(PlayerSelect(player_type, player_data, allowed_user))


        async def on_timeout(self):
            for child in self.children:
                child.disabled = True
            
            if self.message:
                await self.message.edit(content="Player will be chosen randomly or do np", view=None)
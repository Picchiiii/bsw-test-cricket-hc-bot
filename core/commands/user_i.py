import discord
from discord.ext import commands
from discord import app_commands

def user_installs(bot: commands.Bot):

    @app_commands.command(name="say", description="bot says what you want it to say")
    @app_commands.allowed_installs(users= True, guilds=False)
    async def botsay(interaction: discord.Interaction, message: str):
        await interaction.response.send_message("Sent!", ephemeral=True)
        await interaction.channel.send(message)
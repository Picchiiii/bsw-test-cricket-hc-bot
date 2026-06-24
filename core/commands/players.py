import discord
import asyncio
from discord.ext import commands
import logging
from core.backend.instance import join_segregate_player, leave_segregate_player
logger = logging.getLogger(__name__)

def players(bot: commands.Bot):

    @bot.command(name="join", aliases=["j"])
    async def join_match(ctx: commands.Context):    
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        #= Add logic to ensure player is not able to join after match is started or the lobby is locked
        if match_instance and not match_instance.lobby_lock:
            if ctx.author.id not in match_instance.players:
                match_instance.players.append(ctx.author.id)
                join_segregate_player(match_instance, ctx.author.id)
                await ctx.send(
                    f"**{ctx.author.name}** has joined the game. <:correct:1519046913666715749>"
                )
            else:
                await ctx.send("You have already joined the game.")
        else:
            await ctx.send("No active match in this channel." if not match_instance else "The lobby is locked. You cannot join the match at this time.")

    @bot.command(name="leave", aliases=["l"])
    async def leave_match(ctx: commands.Context):
        #= Add logic to ensure player is not able to leave after match is started
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        
        if match_instance:
            if ctx.author.id in match_instance.players:
                match_instance.players.remove(ctx.author.id)
                leave_segregate_player(match_instance, ctx.author.id)
                await ctx.send(
                    f"**{ctx.author.name}** has left the game."
                )
            else:
                await ctx.send("You are not part of the game.")
        else:
            await ctx.send("No active match in this channel.")

    @bot.command(name="players", aliases=["pl"])
    async def list_players(ctx: commands.Context):
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        if match_instance:
            if match_instance.players:
                lobby_embed = discord.Embed(
                    title=f"{ctx.channel.name}'s Match Lobby",
                    description=(
                        f"Host: **{match_instance.host.name}**\n"
                        f"Total Players: **{len(match_instance.players)}/22**\n"
                        f"Overs: **{match_instance.overs if match_instance.overs != 0 else '<:redcross:1519046806338670633>'}**\n"
                        "――――――――――――――――――――"
                    ),
                    color=discord.Color.blue()
                )
                                
                team_a_value = (
                    "```\n" +
                    "\n".join(
                        f"{i}. {ctx.guild.get_member(player_id).name}"
                        for i, player_id in enumerate(match_instance.teamA, start=1)
                    ) +
                    "\n```"
                ) if match_instance.teamA else "```No players yet.```"

                team_b_value = (
                    "```\n" +
                    "\n".join(
                        f"{i}. {ctx.guild.get_member(player_id).name}"
                        for i, player_id in enumerate(match_instance.teamB, start=1)
                    ) +
                    "\n```"
                ) if match_instance.teamB else "```No players yet.```"

                lobby_embed.add_field(
                    name=match_instance.team_settings["Team A name"],
                    value=team_a_value,
                    inline=True
                )

                lobby_embed.add_field(
                    name=match_instance.team_settings["Team B name"],
                    value=team_b_value,
                    inline=True
                )
                elapsed_time = int(asyncio.get_event_loop().time() - match_instance.created_at)
                minutes = divmod(elapsed_time, 60)
                lobby_embed.set_footer(text=f"Created: {minutes[0]} min {minutes[1]} sec ago")
                await ctx.send(embed=lobby_embed)
            else:
                await ctx.send("No players have joined the match yet.")
        else:
            await ctx.send("No active match in this channel.")

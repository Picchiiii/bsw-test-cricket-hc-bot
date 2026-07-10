import discord
import asyncio
from discord.ext import commands
from core.backend.instance import MatchInstance
import logging
from core.backend.views.declare_view import DeclarationView
from core.backend.instance import join_segregate_player, leave_segregate_player
logger = logging.getLogger(__name__)

def players(bot: commands.Bot):

    @bot.command(name="join", aliases=["j"])
    async def join_match(ctx: commands.Context, *args):    
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        rep = " ".join(args).lower() if args else None
        if rep and rep not in ["r","rep", "representative"]:
            await ctx.send("Invalid representative type. Please use 'r', 'rep', or 'representative'.")
            return
        
        #= Add logic to get reps in as well
        if match_instance:
            if ctx.author not in match_instance.players:
                if match_instance.lobby_lock:
                    await ctx.send("The lobby is locked. You cannot join the match at this time.")
                    return
                if match_instance.game_started:
                    await ctx.send("The match has already started. You cannot join now.")
                    return
                
                if rep:
                    if ctx.author.id in match_instance.players:
                        await ctx.send("You have already joined the match as a representative.")
                        return
                    match_instance.players.append(ctx.author.id)
                    await ctx.send(
                        f"**{ctx.author.name}** has joined the game as a representative. <:correct:1519046913666715749>"
                    )
                    #= Fix the rep code
                
                match_instance.players.append(ctx.author)
                join_segregate_player(match_instance, ctx.author)
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
            if ctx.author == match_instance.host:
                await ctx.send("The host cannot leave the match. Change the host before you leave.")
                return
            
            if ctx.author == match_instance.teamA_captain or ctx.author == match_instance.teamB_captain:
                await ctx.send("The captain cannot leave the match. Change the captain before you leave.")
                return
            
            if match_instance.game_started:
                await ctx.send("You cannot leave the match after it has started.")
                return
            
            if ctx.author in match_instance.players:
                match_instance.players.remove(ctx.author)
                leave_segregate_player(match_instance, ctx.author)
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
                        f"Overs: **{match_instance.match_settings['overs'] if match_instance.match_settings['overs'] != 0 else '<:redcross:1519046806338670633>'}**\n"
                        f"Days: **{match_instance.match_settings['days'] if match_instance.match_settings['days'] != 0 else '<:redcross:1519046806338670633>'}**\n"
                        "――――――――――――――――――――"
                    ),
                    color=discord.Color.blue()
                )
                                
                team_a_value = (
                    "```\n" +
                    "\n".join(
                        f"{i}. {player.name} {get_player_suffix(player, match_instance)}"
                        for i, player in enumerate(match_instance.teamA, start=1)
                    ) +
                    "\n```"
                ) if match_instance.teamA else "```No players yet.```"

                team_b_value = (
                    "```\n" +
                    "\n".join(
                        f"{i}. {player.name} {get_player_suffix(player, match_instance)}"
                        for i, player in enumerate(match_instance.teamB, start=1)
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


    def get_player_suffix(player, match_instance):
        suffixes = []

        if player == match_instance.host:
            suffixes.append("(H)")

        if player == match_instance.teamA_captain or \
        player == match_instance.teamB_captain:
            suffixes.append("(C)")

        return " " + " ".join(suffixes) if suffixes else ""
    
    @bot.command(name="declare", aliases=["dec"])
    async def declare_innings(ctx: commands.Context):
        match_instance: MatchInstance = ctx.bot.active_matches.get(ctx.channel.id)
        if match_instance:
            if ctx.author.id == match_instance.teamA_captain and match_instance.batting_team == "A":
                if not match_instance.innings_declared:
                    declaration_view = DeclarationView(match_instance, None, ctx.author)
                    message = await ctx.send(f"Do you want to declare the innings?", view=declaration_view)
                    declaration_view.message = message
                else:
                    await ctx.send("The innings has already been declared.")

            elif ctx.author.id == match_instance.teamB_captain and match_instance.batting_team == "B":
                if not match_instance.innings_declared:
                    declaration_view = DeclarationView(match_instance, None, ctx.author)
                    message = await ctx.send(f"Do you want to declare the innings?", view=declaration_view)
                    declaration_view.message = message
                else:
                    await ctx.send("The innings has already been declared.")
            else:
                await ctx.send("You are not the captain of the batting team.")

        else:
            await ctx.send("No active match in this channel.")
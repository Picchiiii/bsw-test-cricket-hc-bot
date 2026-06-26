import discord
from discord.ext import commands
import logging
from core.config import config
from core.backend.views.match_view import JoinMatchView
from core.backend.instance import MatchInstance

logger = logging.getLogger(__name__)

def host(bot: commands.Bot):
    bot.active_matches = {}
    
    @bot.command(name="create", aliases=["c"])
    async def create_match(ctx: commands.Context):
        #+ Add logic to add the match here
        match_instance = MatchInstance(bot, ctx)
        ctx.bot.active_matches[ctx.channel.id] = match_instance
        join_match_view = JoinMatchView(match_instance, None)
        join_message = await ctx.send(
            f"A match of hand cricket has been created by **{ctx.author.name}**. Click below or use {config.prefix}join to join the match.",
            view=join_match_view
        )
        join_match_view.message = join_message
        

    @bot.command(name="check")
    async def check_match(ctx: commands.Context):
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        if match_instance:
            await ctx.send(
                f"Match created by **{match_instance.host.name}** is currently active. "
            )
        else:
            await ctx.send("No active match in this channel.")


    @bot.command(name="yeet", aliases=["y"])
    async def yeet_match(ctx: commands.Context):
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        if match_instance and match_instance.host.id == ctx.author.id:
            del ctx.bot.active_matches[ctx.channel.id]
            await ctx.send(
                f"Match created by **{match_instance.host.name}** has been yeeted."
            )
        else:
            await ctx.send("No active match in this channel." if not match_instance else "Only the host can yeet the match.")


    @bot.command(name="change_host", aliases=["ch"])
    async def change_host(ctx: commands.Context, new_host: discord.Member):
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        if match_instance and match_instance.host.id == ctx.author.id:
            if new_host.id in match_instance.players:
                match_instance.host = new_host
                await ctx.send(
                    f"Host has been changed to **{new_host.name}**."
                    )
            else:
                await ctx.send("The new host must be a player in the match.")
        else:
            await ctx.send("No active match in this channel." if not match_instance else "Only the host can change the host.")

    @bot.command(name="lock_lobby", aliases=["ll"])
    async def lock_lobby(ctx: commands.Context):
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        if match_instance and match_instance.host.id == ctx.author.id:
            match_instance.lobby_lock = True
            await ctx.send(
                f"The lobby has been locked. No new players can join."
            )
        else:
            await ctx.send("No active match in this channel." if not match_instance else "Only the host can lock the lobby.")
    
    @bot.command(name="unlock_lobby", aliases=["ul"])
    async def unlock_lobby(ctx: commands.Context):
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        if match_instance and match_instance.host.id == ctx.author.id:
            match_instance.lobby_lock = False
            await ctx.send(
                f"The lobby has been unlocked. New players can now join."
            )
        else:
            await ctx.send("No active match in this channel." if not match_instance else "Only the host can unlock the lobby.")

    @bot.command(name="set_overs", aliases=["so"])
    async def set_overs(ctx: commands.Context, overs: int):
        if not isinstance(overs, int) or overs < 10 or overs > 90:
            await ctx.send("Overs can only be set between 10 and 90.")
            return
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        if match_instance and ctx.author.id == match_instance.host.id:
            match_instance.overs = overs
            await ctx.send(
                f"The number of overs has been set to **{overs}**."
            )
        else:
            await ctx.send("No active match in this channel." if not match_instance else "Only the host can set the number of overs.")

    @bot.command(name="change_team_name", aliases=["ctn"])
    async def change_team_name(ctx: commands.Context, team: str, *, new_name: str):
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        if match_instance and ctx.author.id == match_instance.host.id:
            if team.lower() in ("a", "1"):
                match_instance.team_settings['Team A name'] = new_name
                await ctx.send(
                    f"Team A's name has been changed to **{new_name}**."
                    )
            elif team.lower() in ("b", "2"):
                match_instance.team_settings['Team B name'] = new_name
                await ctx.send(
                    f"Team B's name has been changed to **{new_name}**."
                )
            else:
                await ctx.send("Invalid team. Use 'A/1' or 'B/2'.")
        else:
            await ctx.send("No active match in this channel." if not match_instance else "Only the host can change team names.")
    
    @bot.command(name="change_captain", aliases=["cc"])
    async def change_captain(ctx: commands.Context, team: str, new_captain: discord.Member):
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        if match_instance and (ctx.author.id == match_instance.host.id or match_instance.teamA_captain == ctx.author or match_instance.teamB_captain == ctx.author):
                if team.lower() in ("a", "1"):
                    if new_captain in match_instance.players:
                        match_instance.teamA_captain = new_captain
                        await ctx.send(
                            f"Team A's captain has been changed to **{new_captain.name}**."
                        )
                    else:
                        await ctx.send("The new captain must be a player in the match.")
                elif team.lower() in ("b", "2"):
                    if new_captain in match_instance.players:
                        match_instance.teamB_captain = new_captain
                        await ctx.send(
                            f"Team B's captain has been changed to **{new_captain.name}**."
                        )
                    else:
                        await ctx.send("The new captain must be a player in the match.")
                else:
                    await ctx.send("Invalid team. Use 'A/1' or 'B/2'.")
        else:
            await ctx.send("No active match in this channel." if not match_instance else "Only the host or current captains can change team captains.")

    @bot.command(name="kick", aliases=["k"])
    async def kick_player(ctx: commands.Context, player: discord.Member):
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        if match_instance and ctx.author.id == match_instance.host.id:
            if player.id in match_instance.players:
                match_instance.players.remove(player.id)
                match_instance.teamA.remove(player.id) if player.id in match_instance.teamA else match_instance.teamB.remove(player.id)
                await ctx.send(
                        f"**{player.name}** has been kicked from the game."
                    )
            else:
                await ctx.send("The specified player is not in the game.")
        else:
            await ctx.send("No active match in this channel." if not match_instance else "Only the host can kick players.")

    @bot.command(name="swap", aliases=["sw"])
    async def swap_players(ctx: commands.Context, player1: discord.Member, player2: discord.Member):
        match_instance = bot.active_matches.get(ctx.channel.id)
        if match_instance and ctx.author.id == match_instance.host.id:
            if player1.id in match_instance.players and player2.id in match_instance.players:
                # Swap players between teams
                if player1.id in match_instance.teamA and player2.id in match_instance.teamB:
                    match_instance.teamA.remove(player1.id)
                    match_instance.teamB.remove(player2.id)
                    match_instance.teamA.append(player2.id)
                    match_instance.teamB.append(player1.id)
                    await ctx.send(
                        f"**{player1.name}** and **{player2.name}** have been swapped between teams."
                    )
                elif player1.id in match_instance.teamB and player2.id in match_instance.teamA:
                    match_instance.teamB.remove(player1.id)
                    match_instance.teamA.remove(player2.id)
                    match_instance.teamB.append(player2.id)
                    match_instance.teamA.append(player1.id)
                    await ctx.send(
                        f"**{player1.name}** and **{player2.name}** have been swapped between teams."
                    )
                else:
                    await ctx.send("Both players must be on different teams to swap.")
            else:
                await ctx.send("Both players must be part of the game to swap.")
        else:
            await ctx.send("No active match in this channel." if not match_instance else "Only the host can swap players.")
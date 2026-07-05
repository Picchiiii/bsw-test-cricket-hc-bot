import discord
from discord.ext import commands
import logging
from core.config import config
from core.backend.views.match_view import JoinMatchView
from core.backend.views.yeet_view import YeetMatchView
from core.backend.instance import MatchInstance
from core.backend.instance import join_segregate_player
logger = logging.getLogger(__name__)

def host(bot: commands.Bot):
    bot.active_matches = {}
    
    @bot.command(name="create", aliases=["c"])
    async def create_match(ctx: commands.Context):
        if ctx.channel.id in ctx.bot.active_matches:
            await ctx.send("A match is already active in this channel.")
            return
        
        match_instance = MatchInstance(bot, ctx)
        ctx.bot.active_matches[ctx.channel.id] = match_instance

        match_instance.players.append(ctx.author)
        join_segregate_player(match_instance, ctx.author)

        join_match_view = JoinMatchView(match_instance, None)
        join_message = await ctx.send(
            f"A match of hand cricket has been created by **{ctx.author.name}**. Click below or use {config.prefix}join to join the match.",
            view=join_match_view
        )
        join_match_view.message = join_message
        

    import pprint

    @bot.command(name="dump")
    @commands.is_owner()
    async def dump_match(ctx):
        match = ctx.bot.active_matches.get(ctx.channel.id)

        if not match:
            await ctx.send("No active match.")
            return

        data = pprint.pformat(vars(match), indent=2, width=120)

        # Split into Discord-sized chunks
        for i in range(0, len(data), 1900):
            await ctx.send(f"```py\n{data[i:i+1900]}\n```")


    @bot.command(name="instance", aliases=["i"])
    async def check_instance(ctx: commands.Context):
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        if match_instance:
            embed = discord.Embed(
                title=f"Match Instance Details",
                description=(
                    f"Created: {match_instance.created_at}\n"
                    f"Host: **{match_instance.host.name}**\n"
                    f"Players: {', '.join([player.name for player in match_instance.players])}\n"
                    f"Lobby Lock: {'Locked' if match_instance.lobby_lock else 'Unlocked'}\n"
                    f"Overs: {match_instance.overs}\n"
                    f"Team A Captain: **{match_instance.teamA_captain.name if match_instance.teamA_captain else 'Not set'}**\n"
                    f"Team B Captain: **{match_instance.teamB_captain.name if match_instance.teamB_captain else 'Not set'}**\n"
                    f"Toss Winner: **{match_instance.toss_winner.name if match_instance.toss_winner else 'Not set'}**\n"
                    f"Current Batsman: **{match_instance.curr_batsman.name if match_instance.curr_batsman else 'Not set'}**\n"
                    f"Current Bowler: **{match_instance.curr_bowler.name if match_instance.curr_bowler else 'Not set'}**\n"
                    f"Batting Team: **{match_instance.batting_team if match_instance.batting_team else 'Not set'}**\n"
                    f"Bowling Team: **{match_instance.bowling_team if match_instance.bowling_team else 'Not set'}**\n"
                    f"Team A Stats: {match_instance.batting_team_stats}\n"
                    f"Team B Stats: {match_instance.bowling_team_stats}\n"
                    ), color=discord.Color.blue()
                )
            await ctx.send(embed=embed)
        else:
            await ctx.send("No active match in this channel.")

    @bot.command(name="show", aliases=["sho"])
    async def show_match_info(ctx: commands.Context, param: str):
        if ctx.channel.id not in ctx.bot.active_matches:
            await ctx.send("No active match in this channel.")
            return
        
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        embed = discord.Embed(title=f"{param.capitalize()} Information", 
                              description=f"Here is the {param.lower()} information for the active match.\n\n{getattr(match_instance, param, 'Information not available.')}",
                              color=discord.Color.blue())

        await ctx.send(embed=embed)

    @bot.command(name="yeet", aliases=["y"])
    async def yeet_match(ctx: commands.Context):
        if ctx.channel.id not in ctx.bot.active_matches:
            await ctx.send("No active match in this channel.")
            return
        
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        if match_instance.host.id == ctx.author.id:
            yeet_view = YeetMatchView(match_instance, None, ctx)
            yeet_message = await ctx.send(
                f"Are you sure you want to yeet the match created by **{match_instance.host.name}**? This action cannot be undone.",
                view=yeet_view
            )
            yeet_view.message = yeet_message
        else:
            await ctx.send("Only the host can yeet the match.")


    @bot.command(name="change_host", aliases=["ch"])
    async def change_host(ctx: commands.Context, new_host: discord.Member):
        if ctx.channel.id not in ctx.bot.active_matches:
            await ctx.send("No active match in this channel.")
            return
        
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        if match_instance.host.id == ctx.author.id:
            if new_host.id in match_instance.players:
                match_instance.host = new_host
                await ctx.send(
                    f"Host has been changed to **{new_host.name}**."
                    )
            else:
                await ctx.send("The new host must be a player in the match.")
        else:
            await ctx.send("Only the host can change the host.")


    @bot.command(name="lock_lobby", aliases=["ll"])
    async def lock_lobby(ctx: commands.Context):
        if ctx.channel.id not in ctx.bot.active_matches:
            await ctx.send("No active match in this channel.")
            return
        
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        if match_instance.host.id == ctx.author.id:
            match_instance.lobby_lock = True
            await ctx.send(
                f"The lobby has been locked. No new players can join."
            )
        else:
            await ctx.send("Only the host can lock the lobby.")
    
    @bot.command(name="unlock_lobby", aliases=["ul"])
    async def unlock_lobby(ctx: commands.Context):
        if ctx.channel.id not in ctx.bot.active_matches:
            await ctx.send("No active match in this channel.")
            return

        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        if match_instance.host.id == ctx.author.id:
            match_instance.lobby_lock = False
            await ctx.send(
                f"The lobby has been unlocked. New players can now join."
            )
        else:
            await ctx.send("Only the host can unlock the lobby.")

    @bot.command(name="set_overs", aliases=["so"])
    async def set_overs(ctx: commands.Context, overs: int):
        if ctx.channel.id not in ctx.bot.active_matches:
            await ctx.send("No active match in this channel.")
            return
        
        if not isinstance(overs, int) or overs < 10 or overs > 90:
            await ctx.send("Overs can only be set between 10 and 90.")
            return
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        if ctx.author.id == match_instance.host.id:
            match_instance.match_settings['overs'] = overs
            await ctx.send(
                f"The number of overs has been set to **{overs}**."
            )
        else:
            await ctx.send("Only the host can set the number of overs.")

    @bot.command(name="change_team_name", aliases=["ctn"])
    async def change_team_name(ctx: commands.Context, team: str, *, new_name: str):
        if ctx.channel.id not in ctx.bot.active_matches:
            await ctx.send("No active match in this channel.")
            return
        
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        if ctx.author.id == match_instance.host.id:
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
            await ctx.send("Only the host can change team names.")

    @bot.command(name="change_captain", aliases=["cc"])
    async def change_captain(ctx: commands.Context, team: str, new_captain: discord.Member):
        if ctx.channel.id not in ctx.bot.active_matches:
            await ctx.send("No active match in this channel.")
            return

        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        if ctx.author.id == match_instance.host.id or match_instance.teamA_captain == ctx.author or match_instance.teamB_captain == ctx.author:
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
            await ctx.send("Only the host or current captains can change team captains.")

    @bot.command(name="kick", aliases=["k"])
    async def kick_player(ctx: commands.Context, player: discord.Member):
        if ctx.channel.id not in ctx.bot.active_matches:
            await ctx.send("No active match in this channel.")
            return
        
        match_instance = ctx.bot.active_matches.get(ctx.channel.id)
        if ctx.author.id == match_instance.host.id or match_instance.teamA_captain == ctx.author or match_instance.teamB_captain == ctx.author:
            if player.id in match_instance.players:
                match_instance.players.remove(player.id)
                match_instance.teamA.remove(player.id) if player.id in match_instance.teamA else match_instance.teamB.remove(player.id)
                await ctx.send(
                        f"**{player.name}** has been kicked from the game."
                    )
            else:
                await ctx.send("The specified player is not in the game.")
        else:
            await ctx.send("Only the host or captains of their respective teams can kick players.")

    @bot.command(name="swap", aliases=["sw"])
    async def swap_players(ctx: commands.Context, player1: discord.Member, player2: discord.Member):
        
        if ctx.channel.id not in ctx.bot.active_matches:
            await ctx.send("No active match in this channel.")
            return
        
        match_instance = bot.active_matches.get(ctx.channel.id)
        if ctx.author.id == match_instance.host.id:
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
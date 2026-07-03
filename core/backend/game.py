import discord
from discord.ext import commands
import logging
import asyncio
import time
from core.backend.instance import MatchInstance
from core.backend.dropdown.player_select import PlayerView
from collections import deque
from core.backend.checks import GameChecks

logger = logging.getLogger(__name__)

class Game:
    def __init__(self, ctx: commands.Context, match_instance: MatchInstance):
        self.ctx = ctx
        self.mi = match_instance



    def generate_scorecard_embed(self):

        description = f"""**{self.mi.team_settings['Team A name']} v/s {self.mi.team_settings['Team B name']}**\n
                    **Day {self.mi.crr_day} | Innings {self.mi.innings}**\n
                    -# {self.mi.team_settings['Team A name'] if self.mi.toss_winner == self.mi.teamA_captain else self.mi.team_settings['Team B name']} won the toss and elected to {"Bat" if self.mi.match_settings['team_batting_first'] == "bat" else "Bowl"}\n\n

                    `BSW 1st Innings 204/3d (40.1)`\n
                    # RB 247/2 (64.2) \n
                    RB lead by 43 runs\n
                    -# CRR: 3.92\n\n

                    -# Last Wicket: picchiii - 66/2 at 13.2 overs\n
                    -# Last 10 Overs: 35 Runs, 0 wkts\n\n

                    `Batter`\n
                    ```ansi
                    [1;37msudarshan[0m
                    104(184) | 56.52 SR
                    ```\n
                    `Bowler`\n
                    ```ansi
                    [1;37mpicchi[0m
                    1-63 (23.2) | 2.74 ECO
                    ```\n
                    """
        embed = discord.Embed(title=f"MATCH SUMMARY", 
                              description=description,
                              color=discord.Color.blue())
        embed.add_field(name="Timeline", value=f"{self.mi.timeline_logdisplay}", inline=False)
        embed.add_field(name="FOW", value=f"{self.mi.teamA_scores['inning_one']['FOW']}", inline=False)
        embed.set_footer(text=f"Overs left today {self.mi.overs - self.mi.balls_this_over// 6} | Overs left in match {self.mi.match_settings['overs'] - self.mi.overs // 6}")
        return embed

    async def initialise(self):
        self.mi.game_started = True 
        dict_a, dict_b = {}, {}

        for player in self.mi.teamA:
            dict_a[player.id] = {'player_name': player.name,
                                 'runs': 0,
                                 'balls': 0,
                                 'wickets': 0,
                                 'runs_given': 0,
                                 'balls_given': 0,
                                 'last_action': 0,
                                 'is_human': True if len(str(player.id)) > 4 else False,
                                 'is_out': False,
                                 'timeline': deque(['','','','','',''], maxlen=6),
                                 'hattrick': False,
                                 'duck': False,
                                 'result': None
                                }

        dict_a.update( {'name': self.mi.team_settings['Team A name'], 'runs': 0, 'balls': 0, 'wickets': 0} )
        self.TeamA = dict_a

        for player in self.mi.teamB:
            dict_b[player.id] = {'player_name': player.name,
                                 'runs': 0,
                                 'balls': 0,
                                 'wickets': 0,
                                 'runs_given': 0,
                                 'balls_given': 0,
                                 'last_action': 0,
                                 'is_human': True if len(str(player.id)) > 4 else False,
                                 'is_out': False,
                                 'timeline': deque(['','','','','',''], maxlen=6),
                                 'hattrick': False,
                                 'duck': False,
                                 'result': None
                                }

        dict_b.update( {'name': self.mi.team_settings['Team B name'], 'runs': 0, 'balls': 0, 'wickets': 0} )
        self.TeamB = dict_b
        #  Converted the teams into a list 
        # self.mi.batting_team = self.mi.teamA if self.mi.teamA_turn == 'bat' else self.mi.teamB
        # self.mi.bowling_team = self.mi.teamA if self.mi.teamA_turn == 'bowl' else self.mi.teamB
        self.teams = {
            "A": self.TeamA,
            "B": self.TeamB,
        }

        self.captains = {
            "A": self.mi.teamA_captain,
            "B": self.mi.teamB_captain,
        }

    async def start_game(self):
        await self.initialise()
        await self.ctx.send("The match has started!")
        await GameChecks.game_continue_check(self.mi)


    async def next_batsman(self):
        batting_players_data = self.teams[self.mi.batting_turn]
        not_out_players = {
            pid: pdata
            for pid, pdata in batting_players_data.items()
            if isinstance(pid, int) and not pdata["is_out"]
        }
        batting_team_captain = self.captains[self.mi.batting_turn]
        player_view = PlayerView("batsman", not_out_players)
        message = await self.ctx.send(
            f"{batting_team_captain.mention}, Select your next batsman:",
            view=player_view
        )
        player_view.message = message  

    async def next_bowler(self):
        bowling_players_data = self.teams[self.mi.bowling_turn]
        bowling_team_captain = self.captains[self.mi.bowling_turn]
        player_view = PlayerView("bowler", bowling_players_data)
        message = await self.ctx.send(
            f"{bowling_team_captain.mention}, Select your next bowler:",
            view=player_view
        )
        player_view.message = message

        await player_view.wait() # wait for selection for 15 seconds

    async def countdown(self, messages, duration=30, interval=5):
        remaining = duration

        while remaining > 0:
            await asyncio.sleep(interval)
            remaining -= interval

            if remaining <= 0:
                break

            for msg in messages:
                try:
                    await msg.edit(content=f"Put your input\n⏳ {remaining} seconds remaining.")
                except Exception:
                    # Ignore if message can't be edited
                    pass

    async def get_players_response(self):
        batsman = self.mi.curr_batsman
        bowler = self.mi.curr_bowler

        if self.mi.balls_this_over == 0 and self.mi.curr_batter_stats["balls"] == 0:
            
            bat_message = await batsman.send("Put your input\n⏳ 30 seconds remaining.")
            bowl_message = await bowler.send("Put your input\n⏳ 30 seconds remaining.")
        else:
            bat_message = await batsman.send("Put your input\n⏳ 30 seconds remaining.")
            bowl_message = await bowler.send("Put your input\n⏳ 30 seconds remaining.")

        # Start countdown in the background
        countdown_task = asyncio.create_task(
            self.countdown([bat_message, bowl_message], duration=30, interval=5)
        )

        # Wait for both players concurrently
        bat_response, bowl_response = await asyncio.gather(
            self.wait_for_response(batsman, bat_message, timeout=30),
            self.wait_for_response(bowler, bowl_message, timeout=30),
        )

        # Stop the countdown if it is still running
        countdown_task.cancel()
        try:
            await countdown_task
        except asyncio.CancelledError:
            pass

        return bat_response, bowl_response

    async def request_ball(self, ctx: commands.Context):

        valid_responses = {0,1,2,3,4,5,6}


        bat_response, bowl_response = await self.get_players_response()

        # CASE 1: AFK HANDLING
        if bat_response is None or bowl_response is None:

            who_afk = []

            if bat_response is None:
                who_afk.append(self.mi.curr_batsman)

            if bowl_response is None:
                who_afk.append(self.mi.curr_bowler)

            #= Handle AFK players
            await self.handle_afk(who_afk)

            return None, None  

        # CASE 2: INVALID INPUT
        if int(bat_response) not in valid_responses or int(bowl_response) not in valid_responses:

            await self.ctx.send("Invalid input detected. Please enter only 0–6.")


            # VALID INPUT
        return bat_response, bowl_response

    async def wait_for_response(self, player, message, timeout=30):

        def check(m: discord.Message):
            return (
                m.author == player
                and isinstance(m.content, str)
                and m.content.strip().isdigit()
            )

        try:
            msg = await self.ctx.bot.wait_for(
                "message",
                timeout=timeout,
                check=check
            )

            return int(msg.content.strip())  # returns 1 - 6 as int

        except asyncio.TimeoutError:
            return None

    async def continue_game(self):
        while await GameChecks.game_continue_check(self.mi):
            await self.next_batsman()
            await self.next_bowler()

            if not await GameChecks.game_continue_check(self.mi):
                break

    async def resolve_ball(self, bat_response, bowl_response):
        if bowl_response == 0:
            # no ball
            self.mi.score += 1
            self.mi.current_bowler_stats["runs_given"] += 1
            self.mi.current_bowler_stats["timeline"].append("NB")
            self.mi.current_bowler_stats["last_action"] = "NB"
            # bowler cannot choose 0
            # Handle the case where the bowler chose 0
            await self.ctx.send("The bowler cannot choose 0. The batsman scores runs!")
        elif bat_response == bowl_response:
            self.dismiss_batsman(bat_response)
        elif bat_response == 0:
            if self.mi.zeros_by_batsman == 4 :
                self.dismiss_batsman(bat_response)
                return
            await self.add_score(0)
            self.mi.zeros_by_batsman += 1
        else:
            await self.add_score(int(bat_response))
        
    async def dismiss_batsman(self, bat_response):
            self.mi.wickets += 1
            self.mi.balls_this_over += 1
            self.mi.current_batter_stats["is_out"] = True
            self.mi.current_bowler_stats["balls_given"] += 1
            self.mi.current_bowler_stats["wickets"] += 1
            self.mi.current_bowler_stats["timeline"].append(str(bat_response))
            self.mi.current_batter_stats["timeline"].append(str(bat_response))
            self.mi.current_bowler_stats["last_action"] = bat_response
            self.mi.current_batter_stats["last_action"] = bat_response


    async def add_score(self, runs):
        self.mi.score += runs
        self.mi.current_batter_stats["runs"] += runs
        self.mi.current_batter_stats["balls"] += 1
        self.mi.current_bowler_stats["runs_given"] += runs
        self.mi.current_bowler_stats["balls_given"] += 1
        self.mi.current_bowler_stats["timeline"].append(str(runs))
        self.mi.current_batter_stats["timeline"].append(str(runs))
        self.mi.balls_this_over += 1
        self.mi.current_bowler_stats["last_action"] = 0
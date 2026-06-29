import discord
from discord.ext import commands
import logging
from core.backend.instance import MatchInstance
from core.backend.dropdown.player_select import PlayerView
from collections import deque
from core.backend.checks import GameChecks
logger = logging.getLogger(__name__)

class Game:
    def __init__(self, ctx: commands.Context, match_instance: MatchInstance):
        self.ctx = ctx
        self.match_instance = match_instance

    async def initialise(self):
        self.match_instance.game_started = True
        dict_a, dict_b = {}, {}

        for player in self.match_instance.teamA:
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

        dict_a.update( {'name': self.match_instance.team_settings['Team A name'], 'runs': 0, 'balls': 0, 'wickets': 0} )
        self.TeamA = dict_a

        for player in self.match_instance.teamB:
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

        dict_b.update( {'name': self.match_instance.team_settings['Team B name'], 'runs': 0, 'balls': 0, 'wickets': 0} )
        self.TeamB = dict_b
        #  Converted the teams into a list 
        # self.match_instance.batting_team = self.match_instance.teamA if self.match_instance.teamA_turn == 'bat' else self.match_instance.teamB
        # self.match_instance.bowling_team = self.match_instance.teamA if self.match_instance.teamA_turn == 'bowl' else self.match_instance.teamB
        self.teams = {
            "A": self.TeamA,
            "B": self.TeamB,
        }

        self.captains = {
            "A": self.match_instance.teamA_captain,
            "B": self.match_instance.teamB_captain,
        }

    async def start_game(self):
        await self.initialise()
        await self.ctx.send("The match has started!")
        await self.next_batsman()
        await self.next_bowler()    


    async def next_batsman(self):
        batting_players_data = self.teams[self.match_instance.batting_turn]
        not_out_players = {
            pid: pdata
            for pid, pdata in batting_players_data.items()
            if isinstance(pid, int) and not pdata["is_out"]
        }
        batting_team_captain = self.captains[self.match_instance.batting_turn]
        player_view = PlayerView("batsman", not_out_players)
        message = await self.ctx.send(
            f"{batting_team_captain.mention}, Select your next batsman:",
            view=player_view
        )
        player_view.message = message  

    async def next_bowler(self):
        bowling_players_data = self.teams[self.match_instance.bowling_turn]
        bowling_team_captain = self.captains[self.match_instance.bowling_turn]
        player_view = PlayerView("bowler", bowling_players_data)
        message = await self.ctx.send(
            f"{bowling_team_captain.mention}, Select your next bowler:",
            view=player_view
        )
        player_view.message = message

    

    async def continue_game(self):
        while await GameChecks.game_continue_check(self.ctx.channel.id):
            await self.next_batsman()
            await self.next_bowler()
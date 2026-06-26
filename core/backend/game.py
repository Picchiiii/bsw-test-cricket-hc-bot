import discord
from discord.ext import commands
import logging
from core.backend.instance import MatchInstance
from core.backend.dropdown.player_select import PlayerView
from collections import deque

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
        self.match_instance.batting_team = self.match_instance.teamA if self.match_instance.teamA_turn == 'bat' else self.match_instance.teamB
        self.match_instance.bowling_team = self.match_instance.teamA if self.match_instance.teamA_turn == 'bowl' else self.match_instance.teamB

    async def start_game(self):
        await self.initialise()
        await self.ctx.send("The match has started! :cricket_bat_and_ball:")
        player_data = self.match_instance.batting_team_stats
        player_view = PlayerView("batsman", player_data)
        batting_team_captain = self.match_instance.teamA_captain if self.match_instance.batting_team == self.match_instance.teamA else self.match_instance.teamB_captain
        await self.ctx.send(f"{batting_team_captain.mention}, Select your next player:", view=player_view)

    

    async def next_batsman(self, player_data: dict):
        player_view = PlayerView("batsman", player_data)
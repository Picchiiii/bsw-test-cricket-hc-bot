from discord.ext import commands
import discord
import asyncio
import logging
from collections import deque

logger = logging.getLogger(__name__)

class MatchInstance:
    def __init__(self, bot: commands.Bot, ctx: commands.Context):
        self.bot = bot
        self.channel = ctx.channel
        self.host = ctx.author
        self.created_at = asyncio.get_event_loop().time()
        self.players: list = []
        self.teamA: list = []
        self.teamB: list = []
        self.score = 0
        self.overs = 0
        self.wickets = 0
        self.innings = 1
        self.result = None
        self.target = None

        self.teamA_captain: discord.User = None
        self.teamB_captain: discord.User = None
        self.toss_winner: discord.User = None
        self.teamA_turn = None
        self.curr_batsman: discord.User = None
        self.nxt_batsman: discord.User = None
        self.curr_bowler: discord.User = None
        self.nxt_bowler: discord.User = None
        self.batting_team = None
        self.bowling_team = None
        self.batting_team_stats = {}
        self.bowling_team_stats = {}
        # self.teamA_stats = {player_id: {"username": "", "runs_made": 0, "balls_faced": 0, "runs_conceded": 0, "balls_bowled": 0, "wickets": 0, "out":1} for player_id in self.players}
        # self.teamB_stats = {player_id: {"username": "", "runs_made": 0, "balls_faced": 0, "runs_conceded": 0, "balls_bowled": 0, "wickets": 0, "out":1} for player_id in self.players}
        self.team_settings = { 'Team A name':'Team A' , 'Team B name':'Team B' }

        self.players_queue = []
        self.lobby_lock = False
        self.game_started = False
        self.lock = asyncio.Lock()


def join_segregate_player(match_instance: MatchInstance, player: discord.User):
    if len(match_instance.teamA) <= len(match_instance.teamB):
        match_instance.teamA.append(player)
    else:
        match_instance.teamB.append(player)

def leave_segregate_player(match_instance: MatchInstance, player: discord.User):
    if player in match_instance.teamA:
        match_instance.teamA.remove(player)
    elif player in match_instance.teamB:
        match_instance.teamB.remove(player)
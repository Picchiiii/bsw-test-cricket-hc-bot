from discord.ext import commands
import discord
import asyncio
import logging
import time
from collections import deque 

logger = logging.getLogger(__name__)

class MatchInstance:
    def __init__(self, bot: commands.Bot, ctx: commands.Context):
        self.bot = bot
        self.channel = ctx.channel
        self.host = ctx.author
        self.created_at = time.time()
        self.players: list = []
        self.teamA: list = []
        self.teamB: list = []
        self.score = 0
        self.overs = 0
        self.wickets = 0
        self.no_of_days = 1
        self.crr_day = 1
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
        self.batting_turn = None
        self.bowling_turn = None
        self.teamA_scores = {"inning_one": {"runs": 0, "balls": 0, "wickets": 0, "follow_on": False, "declared": False, "FOW": []}, "inning_two": {"runs": 0, "balls": 0, "wickets": 0, "follow_on": False, "declared": False, "FOW": []}}
        self.teamB_scores = {"inning_one": {"runs": 0, "balls": 0, "wickets": 0, "follow_on": False, "declared": False, "FOW": []}, "inning_two": {"runs": 0, "balls": 0, "wickets": 0, "follow_on": False, "declared": False, "FOW": []}}
        self.current_batter_stats = {"runs": 0, "balls": 0, "is_out": False, "timeline": deque(['','','','','',''], maxlen=6)}
        self.current_bowler_stats = {"runs_given": 0, "balls_given": 0, "wickets": 0, "last_action": 0, "hattrick": False, "duck": False, "timeline": deque(['','','','','',''], maxlen=6)}
        # self.teamA_stats = {player_id: {"username": "", "runs_made": 0, "balls_faced": 0, "runs_conceded": 0, "balls_bowled": 0, "wickets": 0, "out":1} for player_id in self.players}
        # self.teamB_stats = {player_id: {"username": "", "runs_made": 0, "balls_faced": 0, "runs_conceded": 0, "balls_bowled": 0, "wickets": 0, "out":1} for player_id in self.players}
        self.team_settings = { 'Team A name':'Team A' , 'Team B name':'Team B' }
        self.match_settings = { 'overs': "", 'days': "" , 'team_batting_first': ""}
        self.players_queue = []
        self.lobby_lock = False
        self.game_started = False

        self.balls_this_over = 0
        self.zeros_by_batsman = 0
        self.last_over_bowler: discord.User = None
        self.timeline_logdisplay = []
        self.afk_players = []
        self.afk_warned_players = []
        self.declared = False
        self.innings_history = {"innings_1": {}, "innings_2": {}, "innings_3": {}, "innings_4": {}}

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
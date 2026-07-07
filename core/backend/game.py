import random
import discord
from discord.ext import commands
import logging
import asyncio
import time
from core.backend.instance import MatchInstance
from core.backend.dropdown.player_select import PlayerView
from collections import deque
from core.backend.checks import GameChecks
from core.backend.innings import Innings

logger = logging.getLogger(__name__)

class Game:
    def __init__(self, ctx: commands.Context, match_instance: MatchInstance):
        self.ctx = ctx
        self.mi = match_instance
        self.emoji_map ={
                        "0": "<:zero:1523349130934489201>",
                        "1": "<:one:1523349128724218007>",
                        "2": "<:two:1523349126425612513>",
                        "3": "<:three:1523349122378235904>",
                        "4": "<:four:1523349119643685056>",
                        "5": "<:five:1523349117252665384>",
                        "6": "<:six:1523349115289997362>",
                        "W": "<:w_:1523349110290120856>",
                        "NB": "<:nb:1523349112471158965>"
                    }


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


    def generate_scorecard_embed(self):

        description = f"""**{self.mi.team_settings['Team A name']} v/s {self.mi.team_settings['Team B name']}**\n**Day {self.mi.crr_day} | Innings {self.mi.innings}**\n{self.compute_scorecard()}\n\n`Batter`\n```ansi\n[1;37m{self.mi.curr_batsman.name}[0m\n{self.mi.current_batter_stats["runs"]}({self.mi.current_batter_stats["balls"]}) | {(self.mi.current_batter_stats['runs'] / self.mi.current_batter_stats['balls'] * 100) if self.mi.current_batter_stats['balls'] else 0:.2f} SR```\n`Bowler`\n```ansi\n[1;37m{self.mi.curr_bowler.name}[0m\n{self.mi.current_bowler_stats['wickets']}-{self.mi.current_bowler_stats['runs_given']} ({self.mi.current_bowler_stats['balls_given']//6}.{self.mi.current_bowler_stats['balls_given']%6}) | {(self.mi.current_bowler_stats['runs_given']/self.mi.current_bowler_stats['balls_given'] * 6) if self.mi.current_bowler_stats['balls_given'] > 0 else 0:.2f} ECO```\n"""
        embed = discord.Embed(title=f"MATCH SUMMARY", 
                              description=description,
                              color=0xf6dc9a)
        embed.add_field(name="Timeline", value=f"{self.format_timeline()}", inline=False)
        if self.mi.wickets > 0:
            embed.add_field(name="FOW", value=f"{self.format_fow()}", inline=False)
        
        total_balls = self.mi.match_settings["overs"] * 6
        balls_bowled = self.mi.overs * 6 + self.mi.balls_this_over
        balls_left = total_balls - balls_bowled

        overs_left = balls_left // 6
        balls_left = balls_left % 6

        overs_left_today = f"{overs_left}.{balls_left}"
        embed.set_footer(text=f"Overs left today {overs_left_today} | Overs left in match {self.mi.match_settings['overs'] - self.mi.overs // 6}")
        return embed

    def format_timeline(self):
        output = []

        for line in self.mi.timeline_logdisplay:  # line 0 → 10
            for item in line:  # oldest → newest
                if not item:
                    continue

                parts = str(item).split("|")

                for p in parts:
                    if not p:
                        continue

                    output.append(self.emoji_map.get(p, p))

        return " | ".join(output)
    
    def format_over_timeline(self):
        entries = []

        # Flatten timeline
        for line in self.mi.timeline_logdisplay:
            for item in line:
                if not item:
                    continue

                entries.extend(
                    p for p in str(item).split("|") if p
                )

        # Only keep the latest 6 events
        latest = entries[-6:]

        output = []

        for event in latest:
            parts = event.split("|")

            # NB first (if present)
            if "NB" in parts:
                output.append(self.emoji_map["NB"])

            # Then the actual ball result(s)
            for part in parts:
                if part == "NB":
                    continue

                output.append(self.emoji_map.get(part, part))

        return " | ".join(output)

    def format_fow(self):
        output = []
        index = 1

        for wicket_line in self.mi.fow:
            for item in wicket_line:
                if not item:
                    continue

                # item format: "66/2 at 13.2"
                parts = str(item).split(" at ")

                if len(parts) != 2:
                    continue

                score_part = parts[0]        # "66/2"
                overs_part = parts[1]        # "13.2"

                runs = score_part.split("/")[0]  # "66"

                output.append(f"{index}- {runs} ({overs_part})")
                index += 1

        return "\n".join(output)
    
    def ordinal(self, n):
        if 10 <= n % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix}"


    def main_score_calc(self):
        lines = []

        for i, innings in enumerate(self.mi.innings_history.values(), start=1):
            team_name = innings.get("team_name")
            score = innings.get("score")

            # Skip empty innings
            if not team_name or not score:
                continue

            lines.append(f"`{team_name} {self.ordinal(i)} Innings {score}`")

        past_innings = "\n".join(lines)
        return past_innings
    
    def lead_trail_or_target(self):
        if self.mi.innings == 1:
            return f"{self.mi.team_settings['Team A name'] if self.mi.toss_winner == self.mi.teamA_captain else self.mi.team_settings['Team B name']} won the toss and elected to {"Bat" if self.mi.match_settings['team_batting_first'] == "bat" else "Bowl" } first."
        elif self.mi.innings == 2:
            if self.mi.batting_team == "A":
                lead = self.mi.teamA_scores['inning_one']['runs'] - self.mi.teamB_scores['inning_one']['runs']
                if lead > 0:
                    return f"{self.mi.batting_team} lead by {lead} runs."
                elif lead < 0:
                    if self.mi.wickets >= (len(self.mi.players))/4:
                        return f"{self.mi.batting_team} trail by {abs(lead)} runs. | {self.follow_on_check()[1] + ' left to avoid follow-on' if self.follow_on_check()[0] else ''} {len(self.mi.players)/4 - self.mi.wickets} wickets remaining."
                else:
                    return "The match is currently tied."
            else:
                lead = self.mi.teamB_scores['inning_one']['runs'] - self.mi.teamA_scores['inning_one']['runs']
                if lead > 0:
                    return f"{self.mi.batting_team} lead by {lead} runs."
                elif lead < 0:
                    if self.mi.wickets >= (len(self.mi.players))/4:
                        return f"{self.mi.batting_team} trail by {abs(lead)} runs. | {self.follow_on_check()[1] + ' left to avoid follow-on' if self.follow_on_check()[0] else ''}, {len(self.mi.players)/4 - self.mi.wickets} wickets remaining."
                    return f"{self.mi.batting_team} trail by {abs(lead)} runs."
                else:
                    return "The match is currently tied."
                
        elif self.mi.innings == 3:
            if self.mi.batting_team == "A":
                lead = self.mi.teamA_scores['inning_one']['runs'] + self.mi.teamA_scores['inning_two']['runs'] - self.mi.teamB_scores['inning_one']['runs'] - self.mi.teamB_scores['inning_two']['runs']
                if lead > 0:
                    return f"{self.mi.batting_team} lead by {lead} runs."
                elif lead < 0:
                    if self.mi.wickets >= (len(self.mi.players))/4:
                        return f"{self.mi.batting_team} trail by {abs(lead)} runs. | {len(self.mi.players)/2 - self.mi.wickets} wickets remaining."
                    return f"{self.mi.batting_team} trail by {abs(lead)} runs."
                else:
                    return "The match is currently tied."
            else:
                lead = self.mi.teamB_scores['inning_one']['runs'] + self.mi.teamB_scores['inning_two']['runs'] - self.mi.teamA_scores['inning_one']['runs'] - self.mi.teamA_scores['inning_two']['runs']
                if lead > 0:
                    return f"{self.mi.batting_team} lead by {lead} runs."
                elif lead < 0:
                    if self.mi.wickets >= (len(self.mi.players))/4:
                        return f"{self.mi.batting_team} trail by {abs(lead)} runs. | {len(self.mi.players)/2 - self.mi.wickets} wickets remaining."
                    return f"{self.mi.batting_team} trail by {abs(lead)} runs."
                else:
                    return "The match is currently tied."
                
        elif self.mi.innings == 4:
            if self.mi.batting_team == "A":
                target = self.mi.teamA_scores['inning_one']['runs'] + self.mi.teamA_scores['inning_two']['runs'] - self.mi.teamB_scores['inning_one']['runs'] - self.mi.teamB_scores['inning_two']['runs'] + 1
                if target > 0:
                    return f"{self.mi.batting_team} needs {abs(target)} more runs to win, with {len(self.mi.players)/2 - self.mi.wickets} wickets remaining."
                else:
                    return "The match is currently tied."
            else:
                target = self.mi.teamA_scores['inning_one']['runs'] + self.mi.teamA_scores['inning_two']['runs'] - self.mi.teamB_scores['inning_one']['runs'] - self.mi.teamB_scores['inning_two']['runs'] + 1
                if target > 0:
                    return f"{self.mi.batting_team} needs {abs(target)} more runs to win, with {len(self.mi.players)/2 - self.mi.wickets} wickets remaining."
                else:
                    return "The match is currently tied."
    
    def follow_on_check(self):
        inning_one_score = self.mi.innings_history["innings_1"]["score"]
        inning_one_runs = int(inning_one_score.split("/")[0])
        if self.mi.score < inning_one_runs/2:
            left_to_avoid_follow_on = (inning_one_runs/2) - self.mi.score
            return True, left_to_avoid_follow_on
        return False, ""
    
    def over_history(self):
        total_runs = 0
        total_wickets = 0

        for over in self.mi.ten_over_history:
            for entry in over:   # FIX: iterate full deque, not just [0]
                if not entry:
                    continue

                try:
                    runs, wickets = str(entry).split("/")
                    total_runs += int(runs)
                    total_wickets += int(wickets)
                except:
                    continue

        return total_runs, total_wickets

    def compute_scorecard(self):
        past_innings = self.main_score_calc()
        current_innings = f"{self.mi.team_settings['Team A name']} {self.mi.score}/{self.mi.wickets} ({self.mi.overs}.{self.mi.balls_this_over})"

        lead_trail_or_target = self.lead_trail_or_target()

        crr = (
            f"CRR: {self.mi.score / (self.mi.overs + self.mi.balls_this_over / 6):.2f}"
            if self.mi.overs + self.mi.balls_this_over / 6 > 0
            else "CRR: 0.00"
        )

        # ---------------- Last Wicket ----------------
        last_wicket = None

        if self.mi.wickets > 0 and self.mi.fow:
            fow_entry = list(self.mi.fow[self.mi.wickets - 1])[-1]

            if fow_entry:
                score_part, overs_part = str(fow_entry).split(" at ")
                runs = score_part.split("/")[0]

                last_wicket = (
                    f"Last Wicket: {self.mi.last_wicket.name} - {runs} ({overs_part})"
                )

        # ---------------- Last 10 Overs ----------------
        over_history = None

        if self.mi.overs > 5 and self.mi.ten_over_history:
            last_over = None

            for over in reversed(self.mi.ten_over_history):
                if over and over[-1]:
                    last_over = over[-1]
                    break

            if last_over:
                try:
                    runs, wickets = str(last_over).split("/")
                    over_history = (
                        f"Last {min(int(self.mi.overs), 10)} Overs: "
                        f"{runs} Runs, {wickets} Wickets"
                    )
                except Exception:
                    pass

        # ---------------- Build Output ----------------
        lines = []

        if past_innings:
            lines.append(past_innings)

        lines.append(f"# {current_innings}")

        if lead_trail_or_target:
            lines.append(f"-# {lead_trail_or_target}")

        lines.append(f"-# {crr}")

        if last_wicket:
            lines.append(f"-# {last_wicket}")

        if over_history:
            lines.append(f"-# {over_history}")

        return "\n".join(lines)

    async def start_game(self):
        await GameChecks.game_continue_check(self.mi)

        innings = Innings(self.ctx, self.mi)
        await innings.one.start_first_innings()


    async def next_batsman(self):
        batting_players_data = self.teams[self.mi.batting_turn]
        not_out_players = {
            pid: pdata
            for pid, pdata in batting_players_data.items()
            if isinstance(pid, int) and not pdata["is_out"]
        }
        batting_team_captain = self.captains[self.mi.batting_turn]
        player_view = PlayerView("batsman", not_out_players, batting_team_captain)
        message = await self.ctx.send(
            f"{batting_team_captain.mention}, Select your next batsman:",
            view=player_view
        )
        player_view.message = message  

    async def next_bowler(self):
        bowling_players_data = self.teams[self.mi.bowling_turn]
        bowling_team_captain = self.captains[self.mi.bowling_turn]
        player_view = PlayerView("bowler", bowling_players_data, bowling_team_captain)
        message = await self.ctx.send(
            f"{bowling_team_captain.mention}, Select your next bowler:",
            view=player_view
        )
        player_view.message = message

    def send_next_batsman(self):
        if self.mi.nxt_batsman is None:
            batting_team = self.teams[self.mi.batting_turn]
            self.mi.curr_batsman = random.choice(list(batting_team.values()))
        else:
            self.mi.curr_batsman = self.mi.nxt_batsman
        self.mi.nxt_batsman = None

    def send_next_bowler(self):
        if self.mi.nxt_bowler is None:
            bowling_team = self.teams[self.mi.bowling_turn]
            bowling_team_except_last_bowler = {pid: pdata for pid, pdata in bowling_team.items() if pdata != self.mi.curr_bowler}
            self.mi.curr_bowler = random.choice(list(bowling_team_except_last_bowler.values()))
        else:
            self.mi.curr_bowler = self.mi.nxt_bowler
        self.mi.nxt_bowler = None

    async def complete_over(self):
        self.mi.overs += 1
        self.mi.balls_this_over = 0
        self.mi.zeros_by_batsman = 0

        embed = discord.Embed(
            title=f"Over {self.mi.overs} completed!",
            description=f"Next bowler is {self.mi.nxt_bowler.name}.",
            color=0x00ff00
        )
        embed.add_field(name="Score", value=f"{self.mi.score}/{self.mi.wickets} ({self.mi.overs}.{self.mi.balls_this_over})", inline=False)
        embed.add_field(name=f"{self.mi.curr_batsman.name}'s Score", value=f"╰`{self.mi.current_batter_stats['runs']} ({self.mi.current_batter_stats['balls']})`", inline=False)
        embed.add_field(name=f"{self.mi.curr_bowler.name}'s Score", value=f"╰`{self.mi.current_bowler_stats['wickets']} - {self.mi.current_bowler_stats['runs_given']} ({self.mi.current_bowler_stats['balls_given']//6}.{self.mi.current_bowler_stats['balls_given']%6})`", inline=False)
        embed.add_field(name="Over Timeline", value=f"{self.format_over_timeline()}", inline=False) # only last 6 balls of the over
        embed.set_footer(text=f"Overs left today {self.mi.match_settings['overs'] - self.mi.overs // 6}.{self.mi.match_settings['overs'] - self.mi.overs % 6} | Overs left in match {self.mi.match_settings['overs'] - self.mi.overs // 6}")

        self.mi.last_over_bowler = self.mi.curr_bowler
        self.mi.curr_bowler = self.mi.nxt_bowler
        self.mi.nxt_bowler = None

        await self.ctx.send(content=self.mi.curr_bowler.mention, embed=embed)

    async def countdown(self, messages, duration=30, interval=5):
        remaining = duration

        while remaining > 0:
            await asyncio.sleep(interval)
            remaining -= interval

            if remaining <= 0:
                break

            for msg in messages:
                try:
                    await msg.edit(content=f"Put your input\n⏳ **{remaining} seconds remaining.**")
                except Exception:
                    # Ignore if message can't be edited
                    pass

    async def get_players_response(self):
        batsman = self.mi.curr_batsman
        bowler = self.mi.curr_bowler

        if self.mi.balls_this_over == 0:
            bowl_message = await bowler.send("It's your turn to **Bowl**!\nPut your input\n⏳ **30 seconds remaining.**") 
        else:
            bowl_message = await bowler.send("Put your input\n⏳ **30 seconds remaining.**")
        if self.mi.current_batter_stats["balls"] == 0:  
            bat_message = await batsman.send("It's your turn to **Bat**!\nPut your input\n⏳ **30 seconds remaining.**")
        else:
            bat_message = await batsman.send("Put your input\n⏳ **30 seconds remaining.**")

        # Start countdown in the background
        countdown_task = asyncio.create_task(
            self.countdown([bat_message, bowl_message], duration=30, interval=5)
        )

        # Wait for both players concurrently
        (bat_response, bat_msg), (bowl_response, bowl_msg) = await asyncio.gather(
            self.wait_for_response(batsman, bat_message, timeout=30),
            self.wait_for_response(bowler, bowl_message, timeout=30),
        )

        # Stop the countdown if it is still running
        countdown_task.cancel()
        try:
            await countdown_task
        except asyncio.CancelledError:
            pass
        
        await bat_message.delete()
        await bowl_message.delete()

        return bat_response, bowl_response, bat_msg, bowl_msg

    async def request_ball(self):

        valid_responses = {0,1,2,3,4,5,6}


        bat_response, bowl_response, bat_msg, bowl_msg = await self.get_players_response()

        # CASE 1: AFK HANDLING
        if bat_response is None or bowl_response is None:

            who_afk = []

            if bat_response is None:
                who_afk.append(self.mi.curr_batsman)

            if bowl_response is None:
                who_afk.append(self.mi.curr_bowler)

            #= Handle AFK players
            await self.handle_afk(who_afk)

            return None, None, None, None


        if bat_response in valid_responses and bowl_response in valid_responses:
            await bat_msg.add_reaction("✅")
            await bowl_msg.add_reaction("✅")

        # CASE 2: INVALID INPUT
        if int(bat_response) not in valid_responses or int(bowl_response) not in valid_responses:

            await self.ctx.send("Invalid input detected. Please enter only 0–6.")


            # VALID INPUT
        await self.resolve_ball(int(bat_response), int(bowl_response), bat_msg, bowl_msg)

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

            value = int(msg.content.strip())
            return value, msg

        except asyncio.TimeoutError:
            return None, None


    async def resolve_ball(self, bat_response, bowl_response, bat_msg, bowl_msg):
        if bowl_response == 0: ## The Bowler cannot choose 0, as it is considered a No Ball. The batting team will get a free run and the ball will be replayed.
            await self.handle_noball()
        elif bat_response == bowl_response:
            await self.handle_dismissal(bat_response)
        elif bat_response == 0:
            if self.mi.zeros_by_batsman == 4 :
                await self.handle_dismissal(bat_response)
                return
            await self.add_score(0)
            self.add_timeline_entry("0")
            self.mi.zeros_by_batsman += 1
        else:
            await self.add_score(int(bat_response))
            self.add_timeline_entry(str(int(bat_response)))

    async def handle_dismissal(self, bat_response):
        self.mi.wickets += 1
        self.mi.balls_this_over += 1
        self.mi.current_batter_stats["is_out"] = True
        self.mi.current_bowler_stats["balls_given"] += 1
        self.mi.current_bowler_stats["wickets"] += 1
        self.mi.current_bowler_stats["timeline"].append(str(bat_response))
        self.mi.current_batter_stats["timeline"].append(str(bat_response))
        self.mi.current_bowler_stats["last_action"] = bat_response
        self.mi.current_batter_stats["last_action"] = bat_response
        self.add_timeline_entry("W")

        await self.mi.curr_batsman.send(f"**You are Out!**\nYou scored {self.mi.current_batter_stats['runs']} runs off {self.mi.current_batter_stats['balls']} balls.")

        embed = discord.Embed(
            title="Batter is Out!",
            description=f"**{self.mi.curr_batsman.name}** is out!**.",
            color=0xff0000
        )
        
        embed.add_field(name=f"{self.mi.curr_batsman.name}", value=f"╰`{self.mi.current_batter_stats["runs"]} ({self.mi.current_batter_stats["balls"]})`", inline=False)
        embed.add_field(name=f"{self.mi.curr_bowler.name}", value=f"╰`{self.mi.current_bowler_stats["wickets"]} - {self.mi.current_bowler_stats["runs_given"]} ({self.mi.current_bowler_stats["balls_given"]//6}.{self.mi.balls_this_over})`", inline=False)
        embed.add_field(name="Score", value=f"{self.mi.score}/{self.mi.wickets} ({self.mi.overs}.{self.mi.balls_this_over})", inline=False)
        await self.mi.channel.send(embed=embed)

    async def handle_four_ball_dismissal(self):
        pass

    async def handle_afk(self, afk_players): ## Check
        for player in afk_players:
            if player not in self.mi.afk_warned_players:
                self.mi.afk_warned_players.append(player)
                await self.ctx.send(f"{player.mention}, you have been warned for being AFK. Please respond within the next 30 seconds.")
            else:
                self.mi.afk_players.append(player)
                await self.ctx.send(f"{player.mention} has been removed from the game for being AFK.")
                if player == self.mi.curr_batsman:
                    await self.handle_dismissal(0)  # Dismiss the batsman
                elif player == self.mi.curr_bowler:
                    await self.handle_dismissal(0)  # Dismiss the bowler


    async def handle_noball(self):
        self.mi.score += 1
        self.mi.current_bowler_stats["runs_given"] += 1
        self.mi.current_bowler_stats["timeline"].append("NB")
        self.mi.current_bowler_stats["last_action"] = "NB"
        self.add_timeline_entry("NB")
        embed = discord.Embed(
            title="No Ball!",
            description=f"**{self.mi.curr_bowler.name}** bowled a No Ball by putting 0. The ball is considered a No Ball.",
            color=0xff0000
        )
        embed.set_footer(text=f"Over {self.mi.overs}.{self.mi.balls_this_over} | The ball will be replayed again.")
        await self.mi.curr_batsman.send(f"**{self.mi.curr_bowler.name} bowled a No Ball. The Ball will be replayed again.**")
        await self.mi.curr_bowler.send(f"**You bowled a No Ball by putting 0. The Ball will be replayed again.**")
        await self.mi.channel.send(embed=embed)

    def add_timeline_entry(self, entry):
        for line in self.mi.timeline_logdisplay:
            if len(line) < line.maxlen:
                line.append(entry)
                return

        # If all lines are full, remove the oldest entry from the first line and add the new entry
        self.mi.timeline_logdisplay[0].popleft()
        self.mi.timeline_logdisplay[0].append(entry)

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
import random
import time
import discord
from discord.ext import commands
import logging
import asyncio
from collections import deque

from core.backend.instance import MatchInstance, fresh_batter_stats, fresh_bowler_stats
from core.backend.dropdown.player_select import PlayerView
from core.backend.checks import GameChecks
from core.backend.views.utilites_view import ChannelLinkView
from core.backend import cpu as cpu_mod
from core.backend.cpu import is_cpu
from core.config import config
from core.ui import theme

logger = logging.getLogger(__name__)

INTERRUPTED = "INTERRUPTED"
ANSI_BOLD_WHITE = "\u001b[1;37m"
ANSI_RESET = "\u001b[0m"
OVER_BREAK = "||"


class Game:
    def __init__(self, ctx: commands.Context, match_instance: MatchInstance):
        self.ctx = ctx
        self.mi = match_instance
        self.bot = match_instance.bot
        self.emoji_map = theme.EMOJI_MAP
        self.teams = {"A": {}, "B": {}}
        self.TeamA = self.teams["A"]
        self.TeamB = self.teams["B"]
        self._dm_failed = set()
        match_instance.game = self

    # ------------------------------------------------------------ properties
    @property
    def captains(self):
        # Always read live so a captain change mid-match is respected.
        return {"A": self.mi.teamA_captain, "B": self.mi.teamB_captain}

    @property
    def channel(self):
        return self.mi.channel

    async def send(self, *args, **kwargs):
        try:
            return await self.mi.channel.send(*args, **kwargs)
        except discord.HTTPException as e:
            logger.warning("channel send failed in %s: %s", self.mi.channel.id, e)
            return None

    # ------------------------------------------------------------ set-up
    def _player_row(self, player) -> dict:
        mi = self.mi
        sub_for = next((s["out_name"] for s in reversed(getattr(mi, "substitutions", []))
                        if s.get("in_id") == player.id and s.get("phase") == "match"), None)
        return {'player_name': player.name,
                'is_rep': player in mi.reps,
                'is_cpu': is_cpu(player),
                'sub_for': sub_for,        # name of the player this substitute replaced (None = original XI)
                'subbed_out': False,       # True once this player has been substituted out of the match
                'sub_by': None,            # name of the substitute who replaced them
                'retired': None,           # "rep_cap" | "substituted" when they left the crease without being out
                'runs': 0,
                'balls': 0,
                'fours': 0,
                'sixes': 0,
                'dots': 0,
                'wickets': 0,
                'runs_given': 0,
                'balls_given': 0,
                'no_balls': 0,
                'maidens': 0,
                'last_action': 0,
                'is_human': not is_cpu(player),
                'is_out': False,
                'batted': False,
                'timeline': deque(['', '', '', '', '', ''], maxlen=6),
                'hattrick': False,
                'hattricks': 0,
                'wicket_streak': 0,
                'duck': False,
                'dismissal': None,
                'dismissed_by': None,
                'fifty': False,
                'hundred': False,
                }

    def reset_team_rows(self):
        """Fresh per-player rows for a new innings (self.teams = figures for the innings in progress)."""
        for side, team in (("A", self.mi.teamA), ("B", self.mi.teamB)):
            rows = self.teams[side]
            rows.clear()
            for player in team:
                rows[player.id] = self._player_row(player)

    async def initialise(self):
        self.mi.game_started = True
        if getattr(self.mi, "_restored_teams", None):
            for side in ("A", "B"):
                rows = self.teams[side]
                rows.clear()
                for key, row in (self.mi._restored_teams.get(side) or {}).items():
                    r = dict(row)
                    r["timeline"] = deque(r.get("timeline", []), maxlen=6)
                    rows[int(key)] = r
                # players added to the team after the snapshot (shouldn't happen) get blank rows
                for player in self.mi.team(side):
                    rows.setdefault(player.id, self._player_row(player))
            self.mi._restored_teams = None
        else:
            self.reset_team_rows()

    def row(self, player):
        if player is None:
            return None
        side = self.mi.side_of(player)
        if side is None:
            # someone substituted out: their row stays on the card for this innings
            for rows in self.teams.values():
                if player.id in rows:
                    return rows[player.id]
            return None
        rows = self.teams[side]
        if player.id not in rows:
            rows[player.id] = self._player_row(player)
        return rows[player.id]

    # ------------------------------------------------------------ formatting
    def generate_scorecard_embed(self):
        mi = self.mi
        bat = mi.curr_batsman
        bowl = mi.curr_bowler
        bat_line = "To be selected"
        bowl_line = "To be selected"
        if bat is not None:
            r = self.row(bat) or {}
            runs, balls = r.get("runs", 0), r.get("balls", 0)
            tag = " (R)" if mi.is_rep(bat) else ""
            cap = self.rep_cap_for(bat)
            cap_txt = f" | rep cap {runs}/{cap}" if cap else ""
            bat_line = (f"{ANSI_BOLD_WHITE}{bat.name}{tag}{ANSI_RESET}\n"
                        f"{runs}({balls}) | {theme.strike_rate(runs, balls):.2f} SR{cap_txt}")
        if bowl is not None:
            r = self.row(bowl) or {}
            rg, bg, w = r.get("runs_given", 0), r.get("balls_given", 0), r.get("wickets", 0)
            bowl_line = (f"{ANSI_BOLD_WHITE}{bowl.name}{' (R)' if mi.is_rep(bowl) else ''}{ANSI_RESET}\n"
                         f"{w}-{rg} ({theme.overs_str(bg)}) | {theme.economy_rate(rg, bg):.2f} ECO")

        description = (
            f"**{mi.team_settings['Team A name']} v/s {mi.team_settings['Team B name']}**\n"
            f"**Day {mi.crr_day} | Innings {mi.innings}**\n{self.compute_scorecard()}\n\n"
            f"`Batter`\n```ansi\n{bat_line}```\n`Bowler`\n```ansi\n{bowl_line}```\n"
        )
        embed = discord.Embed(title=f"{theme.STADIUM} MATCH SUMMARY",
                              description=theme.truncate(description, 4000),
                              color=theme.CREAM)
        this_over = self.format_over_timeline()
        if this_over:
            embed.add_field(name="This Over", value=theme.truncate(this_over), inline=False)
        embed.add_field(name="Timeline", value=theme.truncate(self.format_timeline() or "—"), inline=False)
        if mi.wickets > 0:
            embed.add_field(name="FOW", value=theme.truncate(self.format_fow()), inline=False)

        overs_left_today = max(0, mi.overs_per_day * 6 - mi.overs_in_the_day * 6 - mi.balls_this_over)
        total_left = max(0, mi.overs_per_day * 6 * max(1, mi.match_settings['days'] or 1) - self.match_balls())
        status = ""
        if mi.paused:
            status = " | ⏸️ Paused"
        elif mi.stumps_called:
            status = " | 🌙 Stumps"
        embed.set_footer(text=theme.footer_text(
            f"Overs left today: {theme.overs_str(overs_left_today)} | Overs left in match: {theme.overs_str(total_left)}{status}"))
        url = theme.match_url(mi.match_id)
        if url:
            embed.url = url
        return embed

    def _flat_timeline(self):
        entries = []
        for line in self.mi.timeline_logdisplay:
            for item in line:
                if not item:
                    continue
                if item == OVER_BREAK:
                    entries.append(OVER_BREAK)
                else:
                    entries.extend(p for p in str(item).split("|") if p)
        return entries

    def format_timeline(self, limit: int = 1000):
        """Recent balls of this innings, newest last, trimmed to fit an embed field (fixes overflow)."""
        out = []
        size = 0
        for entry in reversed(self._flat_timeline()):
            token = "┃" if entry == OVER_BREAK else self.emoji_map.get(entry, entry)
            if size + len(token) + 1 > limit:
                break
            out.append(token)
            size += len(token) + 1
        while out and out[-1] == "┃":
            out.pop()
        while out and out[0] == "┃":
            out.pop(0)
        return " ".join(reversed(out))

    def format_over_timeline(self):
        """Events of the current over (NB included)."""
        entries = []
        for entry in reversed(self._flat_timeline()):
            if entry == OVER_BREAK:
                break
            entries.append(entry)
        entries.reverse()
        return " | ".join(self.emoji_map.get(e, e) for e in entries)

    def format_last_over(self):
        """Events of the over that just completed (used by the over summary)."""
        flat = self._flat_timeline()
        if flat and flat[-1] == OVER_BREAK:
            flat = flat[:-1]
        entries = []
        for entry in reversed(flat):
            if entry == OVER_BREAK:
                break
            entries.append(entry)
        entries.reverse()
        return " | ".join(self.emoji_map.get(e, e) for e in entries) or "—"

    def format_dm_over_timeline(self, type: str):
        source = self.mi.current_bowler_stats["over_timeline"] if type == "bowler" else self.mi.current_batter_stats["over_timeline"]
        # FIX: iterate entries, not the characters inside each entry
        return " | ".join(self.emoji_map.get(str(e), str(e)) for e in source if e != "")

    def format_fow(self):
        output = []
        for index, item in enumerate(self.mi.fow, start=1):
            # item format: "66/2 at 13.2|PlayerName"
            text, _, name = str(item).partition("|")
            parts = text.split(" at ")
            if len(parts) != 2:
                continue
            runs = parts[0].split("/")[0]
            output.append(f"{index}- {runs} ({parts[1]}){' ' + name if name else ''}")
        return "\n".join(output) or "—"

    def ordinal(self, n):
        return theme.ordinal(n)

    def main_score_calc(self):
        lines = []
        for i, innings in enumerate(self.mi.innings_history.values(), start=1):
            team_name = innings.get("team_name")
            score = innings.get("score")
            if not team_name or not score or i >= self.mi.innings and self.mi.phase == "innings":
                continue
            lines.append(f"`{team_name} {self.ordinal(i)} Innings {score}`")
        return "\n".join(lines)

    def lead_trail_or_target(self):
        mi = self.mi
        if not mi.batting_turn:
            return ""
        batting = mi.batting_turn
        bowling = mi.other(batting)
        bat_name = mi.team_name(batting)
        limit = GameChecks.all_out_limit(mi)
        wkts_left = max(0, limit - mi.wickets - mi.retired_not_out)
        if mi.innings == 1:
            if not mi.toss_winner:
                return ""
            toss_side = mi.side_of(mi.toss_winner) or ("A" if mi.toss_winner == mi.teamA_captain else "B")
            decision = "Bat" if mi.match_settings['team_batting_first'] == "bat" else "Bowl"
            return f"{mi.team_name(toss_side)} won the toss and elected to {decision} first."
        if mi.innings == 4:
            if mi.target is None:
                return ""
            need = mi.target - mi.score
            if need <= 0:
                return f"{bat_name} have reached the target!"
            return f"{bat_name} need {need} more runs to win, with {wkts_left} wickets remaining."
        # innings 2 and 3: lead / trail on match aggregate
        lead = mi.team_totals(batting) + mi.score - mi.team_totals(bowling)
        if lead > 0:
            text = f"{bat_name} lead by {lead} runs."
        elif lead < 0:
            text = f"{bat_name} trail by {abs(lead)} runs."
        else:
            text = "The scores are level."
        if mi.innings == 2:
            fo, left = self.follow_on_check()
            if fo:
                text += f" | {left} more to avoid the follow-on"
        if lead < 0 or mi.innings == 3:
            text += f" | {wkts_left} wickets remaining."
        return text

    def follow_on_check(self):
        """(follow_on_threatened, runs_needed_to_avoid) for the side batting in innings 2."""
        inning_one_score = self.mi.innings_history["innings_1"]["score"]
        if not inning_one_score:
            return False, ""
        inning_one_runs = int(str(inning_one_score).split("/")[0])
        pct = self.mi.match_settings.get('follow_on_pct', 50) / 100
        threshold = inning_one_runs * pct
        if self.mi.score < threshold:
            left = int(threshold - self.mi.score) + (0 if float(threshold).is_integer() else 1)
            return True, max(1, left)
        return False, ""

    def over_history(self):
        total_runs = 0
        total_wickets = 0
        for entry in self.mi.ten_over_history:
            try:
                runs, wickets = str(entry).split("/")
                total_runs += int(runs)
                total_wickets += int(wickets)
            except Exception:
                continue
        return total_runs, total_wickets

    def compute_scorecard(self):
        mi = self.mi
        past_innings = self.main_score_calc()
        bat_name = mi.team_name(mi.batting_turn) if mi.batting_turn else mi.team_settings['Team A name']
        declared = " d" if mi.innings_declared else ""
        current_innings = f"{bat_name} {mi.score}/{mi.wickets}{declared} ({mi.overs}.{mi.balls_this_over})"

        lead_trail_or_target = self.lead_trail_or_target()
        balls = mi.overs * 6 + mi.balls_this_over
        crr = f"CRR: {mi.score / (balls / 6):.2f}" if balls > 0 else "CRR: 0.00"
        if mi.innings == 4 and mi.target is not None and mi.score < mi.target and balls > 0:
            crr += f" | Target: {mi.target}"

        last_wicket = None
        if mi.wickets > 0 and mi.fow:
            text, _, name = str(mi.fow[-1]).partition("|")
            if " at " in text:
                score_part, overs_part = text.split(" at ")
                runs = score_part.split("/")[0]
                who = name or (mi.last_wicket.name if mi.last_wicket else "")
                last_wicket = f"Last Wicket: {who} - {runs} ({overs_part})"

        over_history = None
        if mi.overs > 5 and mi.ten_over_history:
            runs, wickets = self.over_history()
            over_history = f"Last {len(mi.ten_over_history)} Overs: {runs} Runs, {wickets} Wickets"

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

    def match_balls(self) -> int:
        done = sum(card.get("balls", 0) for n, card in self.mi.innings_scorecards.items() if n != self.mi.innings or self.mi.phase != "innings")
        if self.mi.phase == "innings":
            done += self.mi.overs * 6 + self.mi.balls_this_over
        return done

    # ------------------------------------------------------------ persistence
    def persist(self, force: bool = False):
        store = getattr(self.bot, "store", None)
        if store is None:
            return None
        return store.schedule(self.mi, force=force)

    async def persist_now(self):
        store = getattr(self.bot, "store", None)
        if store is not None:
            await store.flush(self.mi)

    # ------------------------------------------------------------ driver
    async def start_game(self):
        """Called by the start command: launch the match as a background task (one task per match)."""
        await self.initialise()
        mi = self.mi
        mi.phase = "innings"
        mi.innings = 1
        mi.started_at = time.time()
        self.begin_innings_state(1)
        self.start_task(resume=False)

    def start_task(self, resume: bool):
        mi = self.mi
        if mi.task is not None and not mi.task.done():
            return mi.task
        mi.task = asyncio.create_task(self.run(resume=resume), name=f"match-{mi.channel.id}")
        return mi.task

    async def run(self, resume: bool = False):
        mi = self.mi
        try:
            while True:
                if mi.match_abandoned:
                    await self.abandon()
                    return
                if mi.phase == "innings":
                    await self.play_innings(mi.innings, resume=resume)
                    resume = False
                elif mi.phase == "break":
                    await self.end_innings(mi.innings)
                elif mi.phase == "finished":
                    await self.finalise_result()
                    return
                else:
                    logger.error("unknown phase %s", mi.phase)
                    return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("match loop crashed in channel %s", mi.channel.id)
            mi.paused = True
            mi.pause_reason = "error"
            reporter = getattr(self.bot, "report_error", None)
            if reporter:
                try:
                    await reporter(e, where=f"match {mi.match_id} in #{getattr(mi.channel, 'name', mi.channel.id)}")
                except Exception:
                    pass
            await self.send(embed=theme.embed(
                "⚠️ Match paused",
                f"Something went wrong, so the match has been paused and saved.\n"
                f"The host can continue with `{config.prefix}resume`.",
                theme.RED))
            await self.persist_now()

    # ------------------------------------------------------------ innings
    def begin_innings_state(self, innings_no: int):
        mi = self.mi
        mi.innings = innings_no
        mi.phase = "innings"
        mi.score = 0
        mi.wickets = 0
        mi.overs = 0
        mi.balls_this_over = 0
        mi.zeros_by_batsman = 0
        mi.no_balls_this_over = 0
        mi.extras = 0
        mi.retired_not_out = 0
        mi.fow = []
        mi.timeline_logdisplay = [deque(maxlen=12) for _ in range(11)]
        mi.ten_over_history = deque(maxlen=10)
        mi.current_batter_stats = fresh_batter_stats()
        mi.current_bowler_stats = fresh_bowler_stats()
        mi.curr_batsman = mi.nxt_batsman = None
        mi.curr_bowler = mi.nxt_bowler = None
        mi.last_over_bowler = None
        mi.last_wicket = None
        mi.afk_players = []
        mi.afk_warned_players = []
        mi.innings_declared = False
        mi.declared = False
        mi.batting_order = []
        mi.bowling_order = []
        mi.over_runs = 0
        mi.over_wickets = 0
        mi.pending_views = {}
        mi.innings_batting[innings_no] = mi.batting_turn
        mi.batting_team = mi.team_name(mi.batting_turn)
        mi.bowling_team = mi.team_name(mi.bowling_turn)
        mi.innings_history[f"innings_{innings_no}"] = {"team_name": mi.batting_team, "score": None}
        self.reset_team_rows()

    async def play_innings(self, innings_no: int, resume: bool = False):
        mi = self.mi
        started = bool(mi.batting_order) or (mi.overs * 6 + mi.balls_this_over) > 0
        if not started and not await self.check_day_end():
            # the final day ended exactly at the previous innings break: no play in this innings
            mi.innings_history[f"innings_{innings_no}"] = {"team_name": None, "score": None}
            mi.phase = "finished"
            return
        while mi.paused or mi.stumps_called:
            await self.wait_for_resume()
            if mi.match_abandoned:
                return
        if resume and started:
            await self.send(embed=theme.embed(
                f"🔄 Play resumes — Innings {innings_no}",
                f"{mi.team_name(mi.batting_turn)} are batting. Picking up exactly where we left off.",
                theme.BLUE))
        else:
            await self.announce_innings_start(innings_no)

        if mi.curr_batsman is None or mi.curr_bowler is None or (self.row(mi.curr_batsman) or {}).get("is_out"):
            await self.ensure_openers()
        if mi.match_abandoned:
            return
        await self.queue_on_deck()

        mi.scorecard_message = await self.send(embed=self.generate_scorecard_embed())
        self.persist(force=True)

        while True:
            if mi.match_abandoned:
                return
            if mi.paused or mi.stumps_called:
                await self.wait_for_resume()
                if mi.match_abandoned:
                    return
                await self.refresh_scorecard(resend=True)
                continue
            if mi.innings_declared:
                break
            if not await GameChecks.game_continue_check(mi):
                break
            if not await self.check_day_end():
                break
            if mi.stumps_called:
                continue

            if mi.squad_check_pending:
                # play is resuming (next day / after a pause): show the squads before the next ball
                mi.squad_check_pending = False
                await self.squad_check()
                continue

            mi.interrupt.clear()
            outcome = await self.request_ball()
            if outcome == INTERRUPTED:
                continue
            if mi.balls_this_over >= 6:
                live = (not mi.innings_declared) and await GameChecks.game_continue_check(mi)
                await self.complete_over(live=live)
            await self.refresh_scorecard()
            self.persist()

        await self._close_innings(innings_no)

    async def _close_innings(self, innings_no: int):
        mi = self.mi
        await self.refresh_scorecard()
        for v in list(mi.pending_views.values()):
            v.stop()
            if v.message:
                try:
                    await v.message.edit(view=None)
                except Exception:
                    pass
        mi.pending_views = {}
        await self.snapshot_innings(innings_no)
        mi.innings_declared = False   # reset for the next innings
        mi.phase = "break"
        await self.announce_innings_end(innings_no)
        await self.persist_now()

    async def announce_innings_start(self, innings_no: int):
        mi = self.mi
        e = discord.Embed(
            title=f"{theme.BAT} Innings {innings_no} has started!",
            description=(f"**{mi.team_name(mi.batting_turn)}** bat • **{mi.team_name(mi.bowling_turn)}** bowl\n"
                         f"Day {mi.crr_day} of {mi.match_settings['days']}"),
            color=theme.GREEN,
        )
        if innings_no == 4 and mi.target is not None:
            e.add_field(name="🎯 Target", value=f"**{mi.target}** runs to win", inline=False)
        elif innings_no >= 2:
            e.add_field(name="Match so far", value=self.main_score_calc() or "—", inline=False)
        e.set_footer(text=theme.footer_text("Captains: pick your openers below"))
        await self.send(embed=e)

    async def announce_innings_end(self, innings_no: int):
        mi = self.mi
        card = mi.innings_scorecards.get(innings_no, {})
        how = "declared" if card.get("declared") else ("all out" if card.get("all_out") else "innings closed")
        if mi.result and mi.result.get("reason") == "target_chased":
            how = "target chased"
        if mi.result and mi.result.get("reason") == "days_exhausted":
            how = "stumps on the final day"
        e = discord.Embed(
            title=f"Innings {innings_no} over — {card.get('team_name', '')}",
            description=f"# {card.get('runs', 0)}/{card.get('wickets', 0)}{' d' if card.get('declared') else ''} "
                        f"({card.get('overs', '0.0')})\n-# {how}",
            color=theme.BLUE,
        )
        best_bat = sorted(card.get("batting", []), key=lambda r: (-r["runs"], r["balls"]))[:3]
        best_bowl = sorted(card.get("bowling", []), key=lambda r: (-r["wickets"], r["runs"]))[:3]
        if best_bat:
            e.add_field(name=f"{theme.BAT} Top batters", value="\n".join(
                f"**{r['name']}** {r['runs']}{'*' if not r['is_out'] else ''} ({r['balls']})" for r in best_bat), inline=True)
        if best_bowl:
            e.add_field(name=f"{theme.BALL} Top bowlers", value="\n".join(
                f"**{r['name']}** {r['wickets']}-{r['runs']} ({r['overs']})" for r in best_bowl), inline=True)
        e.set_footer(text=theme.footer_text(f"Use {config.prefix}scorecard {innings_no} for the full card"))
        await self.send(embed=e)

    async def refresh_scorecard(self, resend: bool = False):
        mi = self.mi
        embed = self.generate_scorecard_embed()
        if mi.scorecard_message is not None and not resend:
            try:
                await mi.scorecard_message.edit(embed=embed)
                return
            except discord.HTTPException:
                pass
        mi.scorecard_message = await self.send(embed=embed)

    async def snapshot_innings(self, innings_no: int):
        """Write the closed-book history for this innings (spec §5.2, fixes B2)."""
        mi = self.mi
        batting_team = mi.batting_turn
        team_name = mi.team_name(batting_team)
        scores_dict = mi.teamA_scores if batting_team == 'A' else mi.teamB_scores
        slot = 'inning_two' if scores_dict['inning_one']['batted'] else 'inning_one'
        all_out = GameChecks.is_all_out(mi)
        scores_dict[slot]['runs'] = mi.score
        scores_dict[slot]['balls'] = mi.overs * 6 + mi.balls_this_over
        scores_dict[slot]['wickets'] = mi.wickets
        scores_dict[slot]['declared'] = mi.innings_declared
        scores_dict[slot]['follow_on'] = bool(innings_no == 3 and mi.follow_on_enforced)
        scores_dict[slot]['FOW'] = list(mi.fow)
        scores_dict[slot]['batted'] = True
        mi.innings_history[f'innings_{innings_no}']['team_name'] = team_name
        mi.innings_history[f'innings_{innings_no}']['score'] = f"{mi.score}/{mi.wickets}{'d' if mi.innings_declared else ''}"
        card = self.build_innings_card()
        card["all_out"] = all_out
        for r in card["batting"]:
            if r["status"] == "batting":     # the innings is closed: whoever was in is "not out"
                r["status"] = "not out"
        mi.innings_scorecards[innings_no] = card

    def build_innings_card(self) -> dict:
        """Structured scorecard of the innings in progress (used by embeds, website and stats)."""
        mi = self.mi
        bat_side, bowl_side = mi.batting_turn, mi.bowling_turn
        bat_rows = self.teams.get(bat_side, {})
        bowl_rows = self.teams.get(bowl_side, {})
        batting = []
        for pid in mi.batting_order:
            r = bat_rows.get(pid)
            if not r:
                continue
            if r["is_out"]:
                status = self.dismissal_text(r)
            elif r.get("retired") == "substituted":
                status = f"retired — substituted ({r.get('sub_by') or 'sub'})"
            elif r.get("retired") == "rep_cap":
                status = "retired not out (rep limit)"
            elif mi.curr_batsman is not None and mi.curr_batsman.id == pid and mi.phase == "innings":
                status = "batting"
            else:
                status = "not out"
            batting.append({
                "id": str(pid), "name": r["player_name"], "runs": r["runs"], "balls": r["balls"],
                "fours": r["fours"], "sixes": r["sixes"], "dots": r.get("dots", 0),
                "sr": round(theme.strike_rate(r["runs"], r["balls"]), 2),
                "is_out": r["is_out"], "dismissal": r["dismissal"], "status": status,
                **self._row_flags(r),
            })
        yet = [r["player_name"] + (" (R)" if r.get("is_rep") else "")
               for pid, r in bat_rows.items() if pid not in mi.batting_order and not r.get("subbed_out")]
        bowling = []
        for pid in mi.bowling_order:
            r = bowl_rows.get(pid)
            if not r:
                continue
            bowling.append({
                "id": str(pid), "name": r["player_name"], "balls": r["balls_given"],
                "overs": theme.overs_str(r["balls_given"]), "maidens": r.get("maidens", 0),
                "runs": r["runs_given"], "wickets": r["wickets"], "no_balls": r.get("no_balls", 0),
                "econ": round(theme.economy_rate(r["runs_given"], r["balls_given"]), 2),
                "hattricks": r.get("hattricks", 0),
                **self._row_flags(r),
            })
        fow = []
        for i, item in enumerate(mi.fow, start=1):
            text, _, name = str(item).partition("|")
            if " at " in text:
                s, o = text.split(" at ")
                fow.append({"wicket": i, "runs": int(s.split("/")[0]), "overs": o, "player": name})
        balls = mi.overs * 6 + mi.balls_this_over
        return {
            "innings": mi.innings, "team": bat_side, "team_name": mi.team_name(bat_side),
            "bowling_team": bowl_side, "bowling_team_name": mi.team_name(bowl_side),
            "runs": mi.score, "wickets": mi.wickets, "balls": balls, "overs": theme.overs_str(balls),
            "declared": mi.innings_declared, "all_out": GameChecks.is_all_out(mi),
            "follow_on": bool(mi.innings == 3 and mi.follow_on_enforced),
            "extras": mi.extras, "run_rate": round(mi.score / (balls / 6), 2) if balls else 0.0,
            "batting": batting, "yet_to_bat": yet, "bowling": bowling, "fow": fow,
            "retired_not_out": getattr(mi, "retired_not_out", 0),
            "rep_run_cap": mi.match_settings.get("rep_run_cap", 0),
            "substitutions": [dict(x) for x in getattr(mi, "substitutions", [])
                              if x.get("phase") == "match" and x.get("innings") == mi.innings],
            "timeline": [e for e in self._flat_timeline()][-60:],
        }

    @staticmethod
    def _row_flags(r: dict) -> dict:
        return {"rep": bool(r.get("is_rep")), "cpu": bool(r.get("is_cpu")), "sub_for": r.get("sub_for"),
                "subbed_out": bool(r.get("subbed_out")), "sub_by": r.get("sub_by"), "retired": r.get("retired")}

    @staticmethod
    def dismissal_text(r: dict) -> str:
        d = r.get("dismissal")
        by = r.get("dismissed_by") or "?"
        if d == "rep_retired":
            return "retired out (rep limit)"
        if d == "clash":
            return f"b {by}"
        if d == "four_zeros":
            return f"5 dots (b {by})"
        if d == "afk_timeout":
            return "AFK"
        return "out"

    async def end_innings(self, innings_no: int):
        """Route 1 -> 2 -> 3 -> 4 -> result (spec §5.3)."""
        mi = self.mi
        if mi.result:
            mi.phase = "finished"
            return
        if innings_no == 1:
            mi.batting_turn, mi.bowling_turn = mi.bowling_turn, mi.batting_turn
            self.begin_innings_state(2)
        elif innings_no == 2:
            mi.follow_on_enforced = False
            if self.is_follow_on_eligible():
                mi.follow_on_available = True
                await self.offer_follow_on()
            if mi.follow_on_enforced:
                # the team that just batted (2nd) bats again -> batting_turn UNCHANGED
                await self.send(embed=theme.embed(
                    "Follow-on enforced!",
                    f"**{mi.team_name(mi.batting_turn)}** will bat again.", theme.RED))
            else:
                mi.batting_turn, mi.bowling_turn = mi.bowling_turn, mi.batting_turn
            self.begin_innings_state(3)
        elif innings_no == 3:
            mi.batting_turn, mi.bowling_turn = mi.bowling_turn, mi.batting_turn
            mi.target = self.compute_target()
            if mi.target <= 0:
                # side batting last already leads on aggregate: innings victory
                margin = mi.team_totals(mi.batting_turn) - mi.team_totals(mi.bowling_turn)
                mi.result = {'type': 'win', 'winner': mi.batting_turn,
                             'margin': f"an innings and {margin} run{'s' if margin != 1 else ''}",
                             'reason': 'innings_victory'}
                mi.phase = "finished"
                return
            self.begin_innings_state(4)
        else:
            mi.phase = "finished"
            return
        self.persist(force=True)

    def compute_target(self):
        """Runs the side batting last needs: (opponent aggregate - own aggregate) + 1."""
        mi = self.mi
        chasing = mi.batting_turn
        return mi.team_totals(mi.other(chasing)) - mi.team_totals(chasing) + 1

    def is_follow_on_eligible(self) -> bool:
        mi = self.mi
        if mi.innings != 2:
            return False
        first = mi.innings_scorecards.get(1)
        second = mi.innings_scorecards.get(2)
        if not first or not second:
            return False
        pct = mi.match_settings.get('follow_on_pct', 50) / 100
        return second["runs"] < first["runs"] * pct

    def current_lead(self) -> int:
        mi = self.mi
        return mi.team_totals(mi.bowling_turn) - mi.team_totals(mi.batting_turn)

    async def offer_follow_on(self):
        from core.backend.views.follow_on_view import FollowOnView
        mi = self.mi
        captain = mi.captain(mi.bowling_turn)   # team that led
        if is_cpu(captain):
            mi.follow_on_enforced = True
            await self.send(f"{captain.mention} enforces the follow-on.")
            return
        e = discord.Embed(
            title="Follow-on available",
            description=(f"{captain.mention}, **{mi.team_name(mi.bowling_turn)}** lead by **{self.current_lead()}** runs.\n"
                         f"Enforce the follow-on and make **{mi.team_name(mi.batting_turn)}** bat again?"),
            color=theme.GOLD,
        )
        e.set_footer(text=theme.footer_text(f"Declines automatically after {mi.match_settings['decision_timeout']}s"))
        view = FollowOnView(mi, None, captain, timeout=mi.match_settings['decision_timeout'])
        message = await self.send(content=captain.mention, embed=e, view=view)
        view.message = message
        if message is None:
            return
        mi.interrupt.clear()
        waiter = asyncio.create_task(view.wait_done())
        stopper = asyncio.create_task(mi.interrupt.wait())
        await asyncio.wait([waiter, stopper], return_when=asyncio.FIRST_COMPLETED)
        for t in (waiter, stopper):
            t.cancel()

    # ------------------------------------------------------------ image scorecard
    async def scorecard_file(self, mode: str):
        """PNG scorecard for stumps / result as a discord.File, or None if it can't be drawn."""
        try:
            from core.ui.scorecard_image import build_scorecard_data, render_scorecard
            data = build_scorecard_data(self.mi, mode)
            png = await asyncio.to_thread(render_scorecard, data)
            import io
            return discord.File(io.BytesIO(png), filename="scorecard.png")
        except Exception:
            logger.exception("could not render the %s scorecard image", mode)
            return None

    # ------------------------------------------------------------ days / stumps / pause
    async def check_day_end(self) -> bool:
        """Call stumps when the day's overs are bowled. Returns False if the match must end (draw)."""
        mi = self.mi
        if mi.balls_this_over != 0 or mi.overs_per_day <= 0:
            return True
        if mi.overs_in_the_day < mi.overs_per_day:
            return True
        days = mi.match_settings['days'] or 1
        if mi.crr_day >= days:
            mi.result = {'type': 'draw', 'reason': 'days_exhausted'}
            return False
        await self.call_stumps()
        return True

    async def call_stumps(self):
        from core.backend.views.stumps_view import StumpsView
        mi = self.mi
        mi.stumps_called = True
        e = discord.Embed(
            title=f"🌙 Stumps — End of Day {mi.crr_day}",
            description=f"{self.compute_scorecard()}",
            color=theme.GREY,
        )
        e.add_field(name="Next", value=(f"Day {mi.crr_day + 1} of {mi.match_settings['days']} starts when the host "
                                       f"or a captain presses the button or types `{config.prefix}resume`."),
                    inline=False)
        e.set_footer(text=theme.footer_text("Match saved — it is safe to stop here and continue later"))
        view = StumpsView(mi)
        image = await self.scorecard_file("stumps")
        if image is not None:
            e.set_image(url="attachment://scorecard.png")
            msg = await self.send(embed=e, view=view, file=image)
        else:
            msg = await self.send(embed=e, view=view)
        view.message = msg
        await self.persist_now()

    async def wait_for_resume(self):
        mi = self.mi
        if not (mi.paused or mi.stumps_called) or mi.match_abandoned:
            return
        self.persist(force=True)
        while (mi.paused or mi.stumps_called) and not mi.match_abandoned:
            mi.resume_event.clear()
            if not (mi.paused or mi.stumps_called) or mi.match_abandoned:
                break
            await mi.resume_event.wait()

    def resume_play(self) -> str:
        """Called by the resume command / stumps button. Returns a description of what happened."""
        mi = self.mi
        if mi.stumps_called:
            mi.stumps_called = False
            mi.crr_day += 1
            mi.overs_in_the_day = 0   # only the daily counter resets on a day boundary
            what = f"☀️ **Day {mi.crr_day}** — play resumes!"
        elif mi.paused:
            mi.paused = False
            mi.pause_reason = ""
            what = "▶️ Play resumes!"
        else:
            return ""
        mi.squad_check_pending = True
        mi.resume_event.set()
        if mi.task is None or mi.task.done():
            self.start_task(resume=True)
        self.persist(force=True)
        return what

    # ------------------------------------------------------------ selections
    def can_bowl(self, player_or_id) -> bool:
        """Reps may not bowl unless the match allows it; substituted-out players never bowl again."""
        mi = self.mi
        pid = getattr(player_or_id, "id", player_or_id)
        member = mi.member(pid)
        if member is None:
            return False
        if mi.is_rep(member) and not mi.match_settings.get("rep_can_bowl"):
            return False
        return True

    def get_eligible_bowlers(self, exclude_ids=()) -> dict:
        """Single source of truth for bowler eligibility (fixes B15). Reps and subbed-out players are never
        offered (unless the rep_can_bowl setting is on); the other filters relax if nobody is left."""
        mi = self.mi
        rows = self.teams[mi.bowling_turn]
        afk = {p.id for p in mi.afk_players}
        excl = set(exclude_ids)
        pool = {pid: r for pid, r in rows.items() if isinstance(pid, int) and not r.get("subbed_out")}
        allowed = {pid: r for pid, r in pool.items() if self.can_bowl(pid)}
        if not allowed:
            allowed = pool   # safety net only: the start check makes sure every side has a bowler
        eligible = {pid: r for pid, r in allowed.items() if pid not in excl and pid not in afk}
        if not eligible:
            eligible = {pid: r for pid, r in allowed.items() if pid not in afk}
        if not eligible:
            eligible = dict(allowed)
        return eligible

    def get_eligible_batsmen(self) -> dict:
        mi = self.mi
        rows = self.teams[mi.batting_turn]
        cur = mi.curr_batsman.id if mi.curr_batsman else None
        return {pid: r for pid, r in rows.items()
                if isinstance(pid, int) and not r["is_out"] and pid != cur and pid not in mi.batting_order
                and not r.get("subbed_out") and mi.member(pid) is not None}

    async def _send_selection(self, kind: str, data: dict, on_deck: bool):
        mi = self.mi
        side = mi.batting_turn if kind == "batsman" else mi.bowling_turn
        captain = self.captains[side]
        if not data or captain is None:
            return None
        if len(data) == 1 or is_cpu(captain):
            # only one option (or a CPU captain): no point asking
            pid = next(iter(data)) if len(data) == 1 else cpu_mod.choose_from(data, "bowler" if kind == "bowler" else "batsman")
            member = mi.member(pid)
            if kind == "batsman":
                mi.nxt_batsman = member
            else:
                mi.nxt_bowler = member
            return None
        view = PlayerView(kind, data, captain, match_instance=mi, side=side,
                          timeout=mi.match_settings['selection_timeout'])
        role = "batter" if kind == "batsman" else "bowler"
        when = " (on deck — they come in next)" if on_deck else ""
        message = await self.send(f"{captain.mention}, Select your next {role}{when}:", view=view)
        view.message = message
        if message is None:
            await view.on_timeout()
            return None
        mi.pending_views[kind] = view
        return view

    async def next_batsman(self, on_deck: bool = True):
        return await self._send_selection("batsman", self.get_eligible_batsmen(), on_deck)

    async def next_bowler(self, on_deck: bool = True, exclude_ids=None):
        mi = self.mi
        if exclude_ids is None:
            exclude_ids = [mi.curr_bowler.id] if mi.curr_bowler else []
        return await self._send_selection("bowler", self.get_eligible_bowlers(exclude_ids), on_deck)

    async def _await_pending(self, kind: str):
        view = self.mi.pending_views.pop(kind, None)
        if view is not None and view.chosen is None:
            await view.wait_done()

    def send_next_batsman(self):
        mi = self.mi
        eligible = self.get_eligible_batsmen()
        if mi.nxt_batsman is None or mi.nxt_batsman.id not in eligible:
            if not eligible:
                return False
            mi.curr_batsman = mi.member(random.choice(list(eligible.keys())))
        else:
            mi.curr_batsman = mi.nxt_batsman
        mi.zeros_by_batsman = 0   # FIX (B7): fresh batter gets a fresh dot-ball count
        mi.nxt_batsman = None
        mi.current_batter_stats = fresh_batter_stats()
        mi.batting_order.append(mi.curr_batsman.id)
        r = self.row(mi.curr_batsman)
        if r is not None:
            r["batted"] = True
        return True

    def send_next_bowler(self, exclude_ids=None):
        mi = self.mi
        if exclude_ids is None:
            exclude_ids = [mi.last_over_bowler.id] if mi.last_over_bowler else []
        eligible = self.get_eligible_bowlers(exclude_ids)
        if mi.nxt_bowler is None or mi.nxt_bowler.id not in eligible:
            mi.curr_bowler = mi.member(random.choice(list(eligible.keys())))
        else:
            mi.curr_bowler = mi.nxt_bowler
        mi.nxt_bowler = None
        mi.current_bowler_stats = fresh_bowler_stats()
        mi.no_balls_this_over = 0
        if mi.curr_bowler.id not in mi.bowling_order:
            mi.bowling_order.append(mi.curr_bowler.id)

    async def ensure_openers(self):
        """Opening batter/bowler picks (captains choose, auto-pick on timeout)."""
        mi = self.mi
        views = []
        if mi.curr_batsman is None or (self.row(mi.curr_batsman) or {}).get("is_out"):
            mi.curr_batsman = None
            views.append(await self.next_batsman(on_deck=False))
        if mi.curr_bowler is None:
            views.append(await self._send_selection("bowler", self.get_eligible_bowlers(
                [mi.last_over_bowler.id] if mi.last_over_bowler else []), on_deck=False))
        await asyncio.gather(*[v.wait_done() for v in views if v is not None])
        mi.pending_views = {}
        if mi.curr_batsman is None:
            self.send_next_batsman()
        if mi.curr_bowler is None:
            self.send_next_bowler()
        embed = discord.Embed(
            title=f"Innings {mi.innings} — openers",
            description=f"First batter is {mi.curr_batsman.mention}\n\nFirst bowler is {mi.curr_bowler.mention}",
            color=theme.BLUE,
        )
        embed.set_footer(text=theme.footer_text("Start sending your actions in my DMs (0-6)"))
        await self.send(content=f"{mi.curr_batsman.mention} {mi.curr_bowler.mention}", embed=embed)

    async def queue_on_deck(self):
        """Ask captains for the on-deck batter / next over's bowler without blocking play."""
        mi = self.mi
        if mi.nxt_batsman is None and "batsman" not in mi.pending_views:
            await self.next_batsman()
        if mi.nxt_bowler is None and "bowler" not in mi.pending_views:
            await self.next_bowler()

    async def promote_next_batsman(self):
        await self._await_pending("batsman")
        ok = self.send_next_batsman()
        if ok:
            await self.next_batsman()
        return ok

    async def promote_next_bowler(self):
        await self._await_pending("bowler")
        self.send_next_bowler()
        await self.next_bowler()

    # ------------------------------------------------------------ ball engine
    async def safe_dm(self, user, **kwargs):
        try:
            return await user.send(**kwargs)
        except (discord.Forbidden, discord.HTTPException):
            if user.id not in self._dm_failed:
                self._dm_failed.add(user.id)
                await self.send(f"⚠️ {user.mention}, I can't DM you! Enable **Direct Messages** from server members "
                                f"so you can play your balls.")
            return None

    async def countdown(self, messages, duration=30, interval=5):
        """Edits the prompts twice (half-time and 5s left) instead of every 5s — spec §11.1."""
        marks = sorted({m for m in (duration // 2, 5) if 0 < m < duration}, reverse=True)
        elapsed = 0
        for remaining in marks:
            await asyncio.sleep((duration - remaining) - elapsed)
            elapsed = duration - remaining
            for msg, embed in messages:
                if msg is None:
                    continue
                try:
                    embed.set_footer(text=f"⏳ {remaining} seconds remaining")
                    await msg.edit(embed=embed)
                except Exception:
                    pass

    def _prompt_embed(self, role: str) -> discord.Embed:
        mi = self.mi
        bat_name = mi.team_name(mi.batting_turn)
        if role == "bowler":
            title = f"{theme.BALL} Your turn to Bowl!" if mi.balls_this_over == 0 else f"{theme.BALL} Bowl"
            opp = mi.curr_batsman.name
            tip = "Pick **1-6** (0 is a **No Ball** — +1 run and the ball is replayed)."
            color = theme.BLUE
        else:
            title = f"{theme.BAT} Your turn to Bat!" if mi.current_batter_stats["balls"] == 0 else f"{theme.BAT} Bat"
            opp = mi.curr_bowler.name
            tip = f"Pick **0-6**. Dots this over: **{mi.zeros_by_batsman}/4** (a 5th dot is out)."
            cap = self.rep_cap_for(mi.curr_batsman)
            if cap:
                runs = (self.row(mi.curr_batsman) or {}).get("runs", 0)
                tip += f"\nYou are a **rep (R)**: you retire at **{cap}** runs ({runs}/{cap})."
            color = theme.GREEN
        e = discord.Embed(
            title=title,
            description=(f"**{bat_name} {mi.score}/{mi.wickets}** ({mi.overs}.{mi.balls_this_over}) • "
                         f"vs **{opp}**\n{tip}\n**Type your number here.**"),
            color=color,
        )
        e.set_footer(text=f"⏳ {mi.match_settings['ball_timeout']} seconds remaining")
        return e

    async def get_players_response(self):
        mi = self.mi
        batsman = mi.curr_batsman
        bowler = mi.curr_bowler
        timeout = mi.match_settings['ball_timeout']

        bowl_embed = self._prompt_embed("bowler")
        bat_embed = self._prompt_embed("batsman")
        bowl_message = None if is_cpu(bowler) else await self.safe_dm(bowler, embed=bowl_embed)
        bat_message = None if is_cpu(batsman) else await self.safe_dm(batsman, embed=bat_embed)

        countdown_task = asyncio.create_task(
            self.countdown([(bat_message, bat_embed), (bowl_message, bowl_embed)], duration=timeout)
        )
        try:
            mi.awaiting_ball = True
            (bat_response, bat_msg), (bowl_response, bowl_msg) = await asyncio.gather(
                self.cpu_response("batsman") if is_cpu(batsman) else self.wait_for_response(batsman, bat_message, timeout=timeout),
                self.cpu_response("bowler") if is_cpu(bowler) else self.wait_for_response(bowler, bowl_message, timeout=timeout),
            )
        finally:
            mi.awaiting_ball = False
            countdown_task.cancel()
            try:
                await countdown_task
            except asyncio.CancelledError:
                pass
            for m in (bat_message, bowl_message):
                if m is not None:
                    try:
                        await m.delete()
                    except Exception:
                        pass
        return bat_response, bowl_response, bat_msg, bowl_msg

    async def request_ball(self):
        valid_responses = {0, 1, 2, 3, 4, 5, 6}
        mi = self.mi
        bat_response, bowl_response, bat_msg, bowl_msg = await self.get_players_response()

        if bat_response == INTERRUPTED or bowl_response == INTERRUPTED:
            return INTERRUPTED

        # players who answered in time get their AFK strikes reset (consecutive misses only)
        if bat_response is not None:
            mi.afk_strikes[mi.curr_batsman.id] = 0
        if bowl_response is not None:
            mi.afk_strikes[mi.curr_bowler.id] = 0

        # CASE 1: AFK HANDLING
        if bat_response is None or bowl_response is None:
            who_afk = []
            if bat_response is None:
                who_afk.append(mi.curr_batsman)
            if bowl_response is None:
                who_afk.append(mi.curr_bowler)
            await self.handle_afk(who_afk)
            return None

        # CASE 2: INVALID INPUT — never reaches resolve_ball (fixes B8); wait_for_response already
        # filters to 0-6, this is a defensive re-check.
        if int(bat_response) not in valid_responses or int(bowl_response) not in valid_responses:
            await self.send("Invalid input detected. Please enter only 0–6.")
            return None

        for m in (bat_msg, bowl_msg):
            if m is not None:
                try:
                    await m.add_reaction("✅")
                except Exception:
                    pass

        async with mi.lock:   # FIX (B14): atomic resolution
            await self.resolve_ball(int(bat_response), int(bowl_response))
        mi.touch()
        return "OK"

    async def cpu_response(self, role: str):
        """A CPU's pick after a short 'thinking' pause (interrupted like a human pick)."""
        mi = self.mi
        think = asyncio.create_task(cpu_mod.think())
        stop = asyncio.create_task(mi.interrupt.wait())
        try:
            done, _ = await asyncio.wait([think, stop], return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in (think, stop):
                if not t.done():
                    t.cancel()
        if stop in done and not think in done:
            return INTERRUPTED, None
        return cpu_mod.cpu_pick(role, mi), None

    async def wait_for_response(self, player, message, timeout=30):
        """Wait for a 0-6 pick typed in DMs. Returns (value, message|None)."""
        mi = self.mi
        if message is None:
            # couldn't DM this player -> counts as no response
            await asyncio.sleep(0)
            return None, None
        sent_at = getattr(message, "created_at", None)

        def check(m: discord.Message):
            if m.author.id != player.id or m.guild is not None:
                return False
            content = (m.content or "").strip()
            if not content.isdigit():
                return False
            if sent_at is not None and m.created_at < sent_at:
                return False
            if int(content) > 6:
                asyncio.create_task(self._reject(m))
                return False
            return True

        msg_task = asyncio.create_task(self.bot.wait_for("message", check=check))
        int_task = asyncio.create_task(mi.interrupt.wait())
        tasks = [msg_task, int_task]
        try:
            done, _ = await asyncio.wait(tasks, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()
        if msg_task in done and not msg_task.cancelled() and msg_task.exception() is None:
            msg = msg_task.result()
            return int(msg.content.strip()), msg
        if int_task in done:
            return INTERRUPTED, None
        return None, None

    async def _reject(self, m):
        try:
            await m.add_reaction("❌")
            await m.channel.send("Only numbers from **0 to 6** count — try again!")
        except Exception:
            pass

    def _commentary(self, text: str):
        mi = self.mi
        balls = mi.overs * 6 + mi.balls_this_over
        mi.commentary.append({"o": f"{mi.overs}.{mi.balls_this_over}", "i": mi.innings, "t": text, "b": balls})

    async def resolve_ball(self, bat_response, bowl_response):
        mi = self.mi
        if bowl_response == 0:  ## The Bowler cannot choose 0, as it is considered a No Ball. The batting team will get a free run and the ball will be replayed.
            await self.handle_noball(bat_response)
        elif bat_response == bowl_response:
            await self.handle_dismissal(bat_response, bowl_response)
        elif bat_response == 0:
            if mi.zeros_by_batsman >= 4:
                await self.handle_four_ball_dismissal(bowl_response)
                return
            mi.zeros_by_batsman += 1
            await self.add_score(0, int(bowl_response))
            await self._send_ball_dms(bat_response, bowl_response)
        else:
            credited = await self.add_score(int(bat_response), int(bowl_response))
            await self._send_ball_dms(credited, bowl_response)
            await self.check_rep_cap()

    # ------------------------------------------------------------ representatives
    def rep_cap_for(self, player) -> int:
        """The run cap that applies to this batter (0 = none)."""
        mi = self.mi
        if player is None or not mi.is_rep(player):
            return 0
        try:
            return max(0, int(mi.match_settings.get("rep_run_cap") or 0))
        except (TypeError, ValueError):
            return 0

    def capped_runs(self, runs: int) -> int:
        """Runs a rep is allowed to add: nothing beyond the cap counts (e.g. 28 + a six = 30)."""
        cap = self.rep_cap_for(self.mi.curr_batsman)
        if not cap:
            return runs
        have = (self.row(self.mi.curr_batsman) or {}).get("runs", 0)
        return max(0, min(runs, cap - have))

    async def check_rep_cap(self):
        """A rep who reaches the cap leaves the crease: retired out (a wicket) or retired not out (setting)."""
        mi = self.mi
        bat = mi.curr_batsman
        cap = self.rep_cap_for(bat)
        r = self.row(bat)
        if not cap or r is None or r["is_out"] or r.get("retired") or r["runs"] < cap:
            return
        if mi.innings == 4 and mi.target is not None and mi.score >= mi.target:
            return   # the winning hit: nobody needs to walk off
        counts = bool(mi.match_settings.get("rep_retire_counts_wicket", True))
        if counts:
            mi.wickets += 1
            mi.over_wickets += 1
            r["is_out"] = True
            r["dismissal"] = "rep_retired"
            r["dismissed_by"] = None
            mi.current_batter_stats["is_out"] = True
            mi.fow.append(self._fow_entry())
            how = "retired out — it counts as a wicket"
        else:
            r["retired"] = "rep_cap"
            mi.retired_not_out += 1
            how = "retired not out"
        mi.last_wicket = bat
        self._commentary(f"{bat.name} (R) reaches the rep limit of {cap} and is {how.split(' —')[0]}.")
        all_out = GameChecks.is_all_out(mi)
        e = discord.Embed(
            title="🎗️ Rep limit reached",
            description=(f"**{bat.name}** (R) has reached the representative limit of **{cap}** runs and is **{how}**."),
            color=theme.GOLD)
        e.add_field(name="Score", value=f"{mi.score}/{mi.wickets} ({theme.overs_str(mi.overs * 6 + mi.balls_this_over)})",
                    inline=False)
        if all_out:
            e.add_field(name="Innings", value="Nobody left to bat — the innings is over.", inline=False)
        await self.send(embed=e)
        await self.safe_dm(bat, embed=discord.Embed(
            description=f"You reached the rep limit of **{cap}** runs and are {how}. Well batted!", color=theme.GOLD))
        if not all_out:
            if await self.promote_next_batsman():
                await self.send(f"{theme.BAT} {mi.curr_batsman.mention} walks out to bat.")

    # ------------------------------------------------------------ squads on resume
    def squads_embed(self) -> discord.Embed:
        """Both XIs as they stand — everyone who is in the match — with captain/rep/sub tags."""
        mi = self.mi
        from core.backend.lobby import get_player_suffix
        e = discord.Embed(
            title=f"📋 Squads — Day {mi.crr_day}, Innings {mi.innings}",
            description=("These players are in the match. **Is anyone missing today?** The host or that team's "
                         f"captain can replace them: `{config.prefix}sub <player out> <player in>`.\n"
                         + ("A substitute can be anyone who isn't already in this match."
                            if not getattr(mi, "tournament", None) else
                            "In this tournament match the substitute must be on the team's registered squad"
                            + (" (outside players are allowed in this tournament)." if mi.tournament.get("outside_subs") else ".")))
                        ,
            color=theme.BLUE)
        for side in ("A", "B"):
            lines = []
            for p in mi.team(side):
                role = ""
                if p == mi.curr_batsman:
                    role = " 🏏 at the crease"
                elif p == mi.curr_bowler:
                    role = " 🥎 bowling"
                elif p == mi.nxt_batsman:
                    role = " (next in)"
                lines.append(f"{p.name}{get_player_suffix(p, mi)}{role}")
            gone = [s["name"] for s in mi.subbed_out if s.get("side") == side]
            if gone:
                lines.append(f"-# subbed out: {', '.join(gone)}")
            e.add_field(name=f"{'🟡' if side == 'A' else '🟢'} {mi.team_name(side)}",
                        value=theme.truncate("\n".join(lines) or "—"), inline=True)
        return e

    async def squad_check(self):
        """When play resumes, show both squads and give captains time to sub anyone who isn't there."""
        from core.backend.views.squad_view import SquadCheckView
        mi = self.mi
        secs = mi.match_settings.get("squad_check_seconds", config.game.get("squad_check_seconds", 60)) or 0
        if secs <= 0 or mi.match_abandoned or mi.phase != "innings":
            return
        view = SquadCheckView(mi, timeout=secs)
        e = self.squads_embed()
        e.set_footer(text=theme.footer_text(f"Play starts in {int(secs)}s, or when the host/a captain presses Start play"))
        names = " ".join(p.mention for p in (mi.teamA_captain, mi.teamB_captain) if p is not None and not is_cpu(p))
        msg = await self.send(content=names or None, embed=e, view=view)
        if msg is None:
            return
        view.message = msg
        mi.squad_check_view = view
        try:
            loop = asyncio.get_event_loop()
            end = loop.time() + secs + 2
            while not view.done.is_set() and loop.time() < end:
                if mi.match_abandoned or mi.paused or mi.stumps_called:
                    break
                try:
                    await asyncio.wait_for(view.done.wait(), timeout=0.25)
                except asyncio.TimeoutError:
                    pass
            if not view.done.is_set():
                await view.finish(None)
        finally:
            mi.squad_check_view = None
        mi.interrupt.clear()

    # ------------------------------------------------------------ substitutes
    def substitution_problem(self, out, sub) -> str | None:
        """Why this substitution can't be made right now (None = fine). Lobby checks live in the command."""
        mi = self.mi
        if mi.phase == "finished":
            return "The match is over."
        if not (mi.paused or mi.stumps_called or getattr(mi, "awaiting_ball", False)
                or getattr(mi, "squad_check_view", None) is not None):
            return "Substitutions are made between deliveries — try again in a moment (or pause the match first)."
        side = mi.side_of(out)
        if mi.bowling_turn == side and mi.phase == "innings":
            # the bowling side must still have somebody allowed to bowl
            if mi.is_rep(sub) and not mi.match_settings.get("rep_can_bowl"):
                others = [p for p in mi.team(side) if p != out and self.can_bowl(p)]
                if not others:
                    return f"**{mi.team_name(side)}** would have nobody left who can bowl (reps can't bowl)."
        return None

    def apply_substitution(self, out, sub, as_rep: bool, by=None) -> dict:
        """Swap `sub` in for `out` mid-match. The ball in progress is replayed with the new player.

        The outgoing player's figures stay on the card ("retired — substituted" if they were batting); the
        substitute takes over their place in the XI, the crease or the over, and the captaincy if they had it."""
        mi = self.mi
        side = mi.side_of(out)
        team = mi.team(side)
        team[team.index(out)] = sub
        mi.players[mi.players.index(out)] = sub
        if mi.captain(side) == out:
            if side == "A":
                mi.teamA_captain = sub
            else:
                mi.teamB_captain = sub
        if out in mi.reps:
            mi.reps.remove(out)
        if as_rep and sub not in mi.reps:
            mi.reps.append(sub)
        for members in mi.bench.values():
            if sub in members:
                members.remove(sub)
        mi.afk_strikes.pop(out.id, None)
        balls = mi.overs * 6 + mi.balls_this_over
        entry = {"side": side, "out_id": out.id, "out_name": out.name, "in_id": sub.id, "in_name": sub.name,
                 "rep": bool(as_rep), "innings": mi.innings, "over": theme.overs_str(balls), "day": mi.crr_day,
                 "phase": "match", "by": getattr(by, "name", None)}
        mi.substitutions.append(entry)
        mi.subbed_out.append({"id": out.id, "name": out.name, "side": side, "member": out})

        rows = self.teams[side]
        out_row = rows.get(out.id)
        if out_row is not None:
            bowled = bool(out_row.get("balls_given") or out_row.get("runs_given"))
            if out.id in mi.bowling_order and not bowled:
                mi.bowling_order.remove(out.id)     # picked to bowl but never delivered a ball
            used = out_row.get("batted") or bowled or out.id in mi.batting_order
            if used:
                out_row["subbed_out"] = True
                out_row["sub_by"] = sub.name
            else:
                rows.pop(out.id, None)
        rows[sub.id] = self._player_row(sub)

        if mi.curr_batsman == out:
            out_row = rows.get(out.id)
            if out_row is not None and not out_row["is_out"]:
                out_row["retired"] = "substituted"
            mi.curr_batsman = sub
            mi.batting_order.append(sub.id)
            rows[sub.id]["batted"] = True
            mi.current_batter_stats = fresh_batter_stats()
            mi.zeros_by_batsman = 0
        if mi.nxt_batsman == out:
            mi.nxt_batsman = None
        if mi.curr_bowler == out:
            if self.can_bowl(sub):
                mi.curr_bowler = sub
            else:
                excl = [out.id] + ([mi.last_over_bowler.id] if mi.last_over_bowler else [])
                options = self.get_eligible_bowlers(excl)
                pick = mi.nxt_bowler if (mi.nxt_bowler is not None and mi.nxt_bowler.id in options) else None
                mi.curr_bowler = pick or mi.member(next(iter(options)))
                if mi.nxt_bowler == mi.curr_bowler:
                    mi.nxt_bowler = None
            if mi.curr_bowler.id not in mi.bowling_order:
                mi.bowling_order.append(mi.curr_bowler.id)
            entry["bowler_now"] = mi.curr_bowler.name
        if mi.nxt_bowler == out:
            mi.nxt_bowler = None
        self._commentary(f"Substitution for {mi.team_name(side)}: {sub.name} replaces {out.name}.")
        mi.touch()
        mi.interrupt.set()      # replay the pending ball with the new player
        self.persist(force=True)
        return entry

    async def _send_ball_dms(self, bat_response, bowl_response):
        mi = self.mi
        runs = int(bat_response)
        color = theme.GREEN if runs >= 4 else (theme.GREY if runs == 0 else theme.CREAM)
        headline = {0: "Dot ball", 4: "FOUR! 🔥", 6: "SIX! 🚀"}.get(runs, f"{runs} run{'s' if runs != 1 else ''}")
        r = self.row(mi.curr_batsman) or {}
        bat_e = discord.Embed(
            description=(f"**{headline}**\nBowler's Last Action: **{bowl_response}**\n"
                         f"Your Score: **{r.get('runs', 0)} ({r.get('balls', 0)})**\n{self._dm_timeline('batsman')}"),
            color=color)
        bowl_e = discord.Embed(
            description=(f"**{headline}**\nBatter's Last Action: **{bat_response}**\n"
                         f"Batter Score: **{r.get('runs', 0)} ({r.get('balls', 0)})**\n{self._dm_timeline('bowler')}"),
            color=color)
        await self.safe_dm(mi.curr_batsman, embed=bat_e)
        await self.safe_dm(mi.curr_bowler, embed=bowl_e)

    def _dm_timeline(self, player_type):
        bowler_timeline = self.format_dm_over_timeline("bowler") or "—"
        batter_timeline = self.format_dm_over_timeline("batsman") or "—"

        if player_type == "batsman":
            timeline_text = f"-# Your Input: {batter_timeline}\n-# Bowler's Input: {bowler_timeline}"
        elif player_type == "bowler":
            timeline_text = f"-# Your Input: {bowler_timeline}\n-# Batter's Input: {batter_timeline}"
        else:
            timeline_text = f"-# Timeline: {bowler_timeline} | {batter_timeline}"

        return timeline_text

    def _fow_entry(self):
        mi = self.mi
        balls = mi.overs * 6 + mi.balls_this_over
        return f"{mi.score}/{mi.wickets} at {theme.overs_str(balls)}|{mi.curr_batsman.name}"

    async def _after_wicket(self, title: str, description: str, extra_bowler_line: bool = True):
        """Shared wicket announcement + next batter promotion."""
        mi = self.mi
        out_player = mi.curr_batsman
        bat_row = self.row(out_player) or {}
        bowl_row = self.row(mi.curr_bowler) or {}
        mi.last_wicket = out_player
        all_out = GameChecks.is_all_out(mi)

        link_view = ChannelLinkView(mi)
        out_e = discord.Embed(
            title="You are Out! 🔴",
            description=(f"{description}\nBowler's Last Action: **{mi.current_bowler_stats['last_action']}**\n"
                         f"Score: **{bat_row.get('runs', 0)} ({bat_row.get('balls', 0)})**"),
            color=theme.RED)
        await self.safe_dm(out_player, embed=out_e, view=link_view)

        next_name = None
        if not all_out and mi.nxt_batsman is not None:
            next_name = mi.nxt_batsman.name
        bowl_text = (f"**{out_player.name}** is Out!\nBatter's Last Action: **{mi.current_batter_stats['last_action']}**\n"
                     f"Score: **{bat_row.get('runs', 0)} ({bat_row.get('balls', 0)})**")
        if all_out:
            bowl_text += "\n\nThat's the end of the innings!"
        elif next_name:
            bowl_text += f"\n\nNext batsman is **{next_name}**"
        await self.safe_dm(mi.curr_bowler, embed=discord.Embed(description=bowl_text, color=theme.GREEN))

        embed = discord.Embed(title=title, description=description, color=theme.RED)
        embed.add_field(name=f"{out_player.name}", value=f"╰`{bat_row.get('runs', 0)} ({bat_row.get('balls', 0)})`", inline=True)
        embed.add_field(name=f"{mi.curr_bowler.name}",
                        value=f"╰`{bowl_row.get('wickets', 0)} - {bowl_row.get('runs_given', 0)} ({theme.overs_str(bowl_row.get('balls_given', 0))})`",
                        inline=True)
        balls = mi.overs * 6 + mi.balls_this_over
        embed.add_field(name="Score", value=f"{mi.score}/{mi.wickets} ({theme.overs_str(balls)})", inline=False)
        if all_out:
            embed.add_field(name="Innings", value="All out!", inline=False)
        else:
            embed.add_field(name="Next batsman", value=f"{next_name or 'To be selected'}", inline=False)
        await self.send(content=mi.nxt_batsman.mention if (next_name and mi.nxt_batsman) else None, embed=embed)

        if not all_out:
            previous_pick = mi.nxt_batsman
            if await self.promote_next_batsman():
                if previous_pick is None or previous_pick != mi.curr_batsman:
                    await self.send(f"{theme.BAT} {mi.curr_batsman.mention} walks out to bat.")

    def _register_legal_ball_for_bowler(self, wicket: bool):
        r = self.row(self.mi.curr_bowler)
        if r is None:
            return False
        if wicket:
            r["wicket_streak"] = r.get("wicket_streak", 0) + 1
            if r["wicket_streak"] >= 3 and r["wicket_streak"] % 3 == 0:
                r["hattricks"] = r.get("hattricks", 0) + 1
                r["hattrick"] = True
                self.mi.current_bowler_stats["hattrick"] = True
                return True
        else:
            r["wicket_streak"] = 0
        return False

    async def handle_dismissal(self, bat_response, bowl_response=None):
        mi = self.mi
        bowl_response = bat_response if bowl_response is None else bowl_response
        mi.wickets += 1
        mi.balls_this_over += 1
        mi.over_wickets += 1
        mi.current_batter_stats["is_out"] = True
        mi.current_batter_stats["balls"] += 1
        mi.current_bowler_stats["balls_given"] += 1
        mi.current_bowler_stats["wickets"] += 1
        mi.current_bowler_stats["over_timeline"].append("W")
        mi.current_batter_stats["over_timeline"].append(str(bat_response))
        mi.current_bowler_stats["last_action"] = bowl_response
        mi.current_batter_stats["last_action"] = bat_response
        bat_row = self.row(mi.curr_batsman)
        bowl_row = self.row(mi.curr_bowler)
        bat_row["balls"] += 1
        bat_row["is_out"] = True
        bat_row["dismissal"] = "clash"
        bat_row["dismissed_by"] = mi.curr_bowler.name
        bat_row["timeline"].append("W")
        bat_row["duck"] = bat_row["runs"] == 0
        bowl_row["balls_given"] += 1
        bowl_row["wickets"] += 1
        hattrick = self._register_legal_ball_for_bowler(wicket=True)
        mi.fow.append(self._fow_entry())
        self.add_timeline_entry("W")
        self._commentary(f"{mi.curr_bowler.name} to {mi.curr_batsman.name}: OUT! Both picked {bat_response}.")

        await self._after_wicket(
            "Batter is Out!",
            f"**{mi.curr_batsman.name}** is out! Both picked **{bat_response}**."
            + (" 🦆 Duck!" if bat_row["duck"] else ""))
        if hattrick:
            await self.send(embed=theme.embed("🎩 HAT-TRICK!", f"**{mi.curr_bowler.name}** takes three in three!", theme.GOLD))

    async def handle_four_ball_dismissal(self, bowler_response, method: str = "four_zeros"):
        mi = self.mi
        mi.wickets += 1
        mi.balls_this_over += 1
        mi.over_wickets += 1
        mi.current_batter_stats["is_out"] = True
        mi.current_batter_stats["balls"] += 1
        mi.current_bowler_stats["balls_given"] += 1
        # NOTE (B6): no bowler-wickets increment here -- this was never a clash
        mi.current_bowler_stats["over_timeline"].append("W")
        mi.current_batter_stats["over_timeline"].append("0")
        mi.current_bowler_stats["last_action"] = bowler_response
        mi.current_batter_stats["last_action"] = 0
        bat_row = self.row(mi.curr_batsman)
        bowl_row = self.row(mi.curr_bowler)
        bat_row["balls"] += 1
        bat_row["is_out"] = True
        bat_row["dismissal"] = method
        bat_row["dismissed_by"] = mi.curr_bowler.name
        bat_row["timeline"].append("W")
        bat_row["duck"] = bat_row["runs"] == 0
        bowl_row["balls_given"] += 1
        self._register_legal_ball_for_bowler(wicket=False)
        mi.fow.append(self._fow_entry())
        self.add_timeline_entry("W")

        if method == "afk_timeout":
            title = "Batter is Out — AFK!"
            desc = f"**{mi.curr_batsman.name}** didn't respond and has been given out."
            self._commentary(f"{mi.curr_batsman.name} is out — AFK.")
        else:
            title = "Batter is Out by Four 0s!"
            desc = f"**{mi.curr_batsman.name}** is out! They played more than Four 0s in this over."
            self._commentary(f"{mi.curr_bowler.name} to {mi.curr_batsman.name}: OUT! A fifth dot ball in the over.")
        await self._after_wicket(title, desc)

    async def handle_afk(self, afk_players):
        """Strike-based AFK handling, branching by role (spec §8.1, fixes B13)."""
        mi = self.mi
        max_strikes = mi.match_settings.get('afk_max_strikes', 3)
        for player in afk_players:
            mi.afk_strikes[player.id] = mi.afk_strikes.get(player.id, 0) + 1
            strikes = mi.afk_strikes[player.id]
            if player not in mi.afk_warned_players:
                mi.afk_warned_players.append(player)
            if strikes < max_strikes:
                await self.send(f"⏱️ {player.mention} did not respond (strike {strikes}/{max_strikes}). "
                                f"The ball will be replayed.")
                continue
            mi.afk_strikes[player.id] = 0
            if player == mi.curr_batsman:
                await self.send(f"🚫 {player.mention} has been AFK for {max_strikes} balls in a row.")
                await self.handle_afk_dismissal(player)
            elif player == mi.curr_bowler:
                await self.replace_afk_bowler(player)

    async def handle_afk_dismissal(self, afk_player):
        if afk_player == self.mi.curr_batsman:
            await self.handle_four_ball_dismissal(0, method="afk_timeout")
        elif afk_player == self.mi.curr_bowler:
            await self.replace_afk_bowler(afk_player)

    async def replace_afk_bowler(self, player, ban: bool = True, reason: str = None):
        """Swap the bowler mid-over (AFK or too many no-balls). The new bowler finishes the over."""
        mi = self.mi
        if player not in mi.afk_players:
            mi.afk_players.append(player)
        excl = [player.id] + ([mi.last_over_bowler.id] if mi.last_over_bowler else [])
        others = {pid: r for pid, r in self.get_eligible_bowlers(excl).items() if pid != player.id}
        if not others:
            mi.afk_players.remove(player)
            await self.send(f"⏱️ {player.mention} can't be replaced — there is nobody else to bowl. Carrying on.")
            return
        await self.send(reason or f"🚫 {player.mention} is AFK — a new bowler must be chosen to finish the over.")
        if mi.nxt_bowler == player:
            mi.nxt_bowler = None
        await self._await_pending("bowler")
        if mi.nxt_bowler is None or mi.nxt_bowler.id not in others:
            mi.nxt_bowler = None
            view = await self._send_selection("bowler", others, on_deck=False)
            if view is not None:
                await view.wait_done()
                mi.pending_views.pop("bowler", None)
        timeline = list(mi.current_bowler_stats["over_timeline"])
        partial = {k: mi.current_bowler_stats[k] for k in ("runs_given", "balls_given", "wickets")}
        self.send_next_bowler(exclude_ids=excl)
        if mi.curr_bowler == player:   # safety net, should not happen
            mi.curr_bowler = mi.member(next(iter(others)))
        mi.current_bowler_stats["over_timeline"].extend(timeline)
        mi.current_bowler_stats.update(partial)
        if not ban:
            mi.afk_players.remove(player)
        await self.send(f"{theme.BALL} {mi.curr_bowler.mention} will finish the over.")
        await self.next_bowler()

    async def handle_noball(self, bat_response=None):
        mi = self.mi
        mi.score += 1
        mi.extras += 1
        mi.over_runs += 1
        mi.no_balls_this_over += 1
        mi.current_bowler_stats["runs_given"] += 1
        mi.current_bowler_stats["over_timeline"].append("NB")
        mi.current_bowler_stats["last_action"] = "NB"
        bowler_row = self.row(mi.curr_bowler)
        bowler_row["runs_given"] += 1
        bowler_row["no_balls"] = bowler_row.get("no_balls", 0) + 1
        self.add_timeline_entry("NB")
        self._commentary(f"{mi.curr_bowler.name} bowls a NO BALL. +1 run, ball replayed.")
        embed = discord.Embed(
            title="No Ball!",
            description=f"**{mi.curr_bowler.name}** bowled a 0. The ball is considered a No Ball. **+1 run**.",
            color=theme.GOLD
        )
        embed.set_footer(text=f"Over {mi.overs}.{mi.balls_this_over} | The ball will be replayed again.")
        await self.safe_dm(mi.curr_batsman, embed=discord.Embed(
            description=f"**{mi.curr_bowler.name} bowled a No Ball. The Ball will be replayed again.**", color=theme.GOLD))
        await self.safe_dm(mi.curr_bowler, embed=discord.Embed(
            description="**You bowled a No Ball by putting 0. The Ball will be replayed again.**", color=theme.GOLD))
        await self.send(embed=embed)

        limit = mi.match_settings.get('max_no_balls_per_over', 0)
        if limit and mi.no_balls_this_over >= limit:
            await self.replace_afk_bowler(
                mi.curr_bowler, ban=False,
                reason=f"{mi.curr_bowler.mention} has bowled too many no-balls this over — a new bowler must be chosen.")

    def add_timeline_entry(self, entry):
        """Append to the rolling timeline (11 lines x 12). Oldest entries scroll off in order."""
        lines = self.mi.timeline_logdisplay
        for line in lines:
            if len(line) < line.maxlen:
                line.append(entry)
                return
        flat = [e for line in lines for e in line][1:] + [entry]
        for i, line in enumerate(lines):
            line.clear()
            line.extend(flat[i * 12:(i + 1) * 12])

    async def add_score(self, bat_response, bowl_response):
        mi = self.mi
        runs = self.capped_runs(int(bat_response))   # reps can't score past their cap
        mi.score += runs
        mi.over_runs += runs
        mi.current_batter_stats["runs"] += runs
        mi.current_batter_stats["balls"] += 1
        mi.current_bowler_stats["runs_given"] += runs
        mi.current_bowler_stats["balls_given"] += 1
        mi.current_bowler_stats["over_timeline"].append(str(bowl_response))
        mi.current_batter_stats["over_timeline"].append(str(runs))
        mi.balls_this_over += 1
        mi.current_bowler_stats["last_action"] = bowl_response
        mi.current_batter_stats["last_action"] = bat_response
        bat_row = self.row(mi.curr_batsman)
        bowl_row = self.row(mi.curr_bowler)
        before = bat_row["runs"]
        bat_row["runs"] += runs
        bat_row["balls"] += 1
        bat_row["timeline"].append(str(runs))
        if runs == 0:
            bat_row["dots"] = bat_row.get("dots", 0) + 1
        elif runs == 4:
            bat_row["fours"] += 1
        elif runs == 6:
            bat_row["sixes"] += 1
        bowl_row["runs_given"] += runs
        bowl_row["balls_given"] += 1
        self._register_legal_ball_for_bowler(wicket=False)
        self.add_timeline_entry(str(runs))   # FIX: only one timeline entry per ball (dots were doubled)
        word = {0: "no run", 4: "FOUR!", 6: "SIX!"}.get(runs, f"{runs} run{'s' if runs != 1 else ''}")
        self._commentary(f"{mi.curr_bowler.name} to {mi.curr_batsman.name}: {word}")

        for mark, key, label in ((100, "hundred", "💯 HUNDRED!"), (50, "fifty", "🎉 FIFTY!")):
            if before < mark <= bat_row["runs"] and not bat_row.get(key):
                bat_row[key] = True
                await self.send(embed=theme.embed(
                    label, f"**{mi.curr_batsman.name}** reaches **{bat_row['runs']}** off {bat_row['balls']} balls!",
                    theme.GOLD))
                break
        return runs

    async def complete_over(self, live: bool = True):
        mi = self.mi
        bowler = mi.curr_bowler
        bowl_row = self.row(bowler) or {}
        over_no = mi.overs + 1
        if mi.over_runs == 0:
            bowl_row["maidens"] = bowl_row.get("maidens", 0) + 1
        mi.ten_over_history.append(f"{mi.over_runs}/{mi.over_wickets}")
        over_summary = f"{mi.over_runs} run{'s' if mi.over_runs != 1 else ''}, {mi.over_wickets} wkt{'s' if mi.over_wickets != 1 else ''}"

        mi.overs += 1
        mi.balls_this_over = 0
        mi.zeros_by_batsman = 0
        mi.no_balls_this_over = 0
        mi.overs_in_the_day += 1
        mi.over_runs = 0
        mi.over_wickets = 0
        self.add_timeline_entry(OVER_BREAK)
        mi.current_batter_stats["over_timeline"].clear()
        mi.last_over_bowler = bowler

        if not live:
            mi.current_bowler_stats = fresh_bowler_stats()
            return

        bat_row = self.row(mi.curr_batsman) or {}
        embed = discord.Embed(
            title=f"Over {over_no} completed!",
            description=f"{over_summary} • **{mi.score}/{mi.wickets}** ({mi.overs}.0)",
            color=theme.BLUE
        )
        embed.add_field(name=f"{mi.curr_batsman.name}'s Score", value=f"╰`{bat_row.get('runs', 0)} ({bat_row.get('balls', 0)})`", inline=True)
        embed.add_field(name=f"{bowler.name}'s Figures",
                        value=f"╰`{bowl_row.get('wickets', 0)} - {bowl_row.get('runs_given', 0)} ({theme.overs_str(bowl_row.get('balls_given', 0))})`",
                        inline=True)
        embed.add_field(name="Over Timeline", value=theme.truncate(self.format_last_over()), inline=False)

        await self.promote_next_bowler()
        embed.add_field(name="Next bowler", value=f"{mi.curr_bowler.name}", inline=False)
        left_today = max(0, mi.overs_per_day - mi.overs_in_the_day)
        embed.set_footer(text=theme.footer_text(f"Overs left today: {left_today} | Day {mi.crr_day}"))
        await self.send(content=mi.curr_bowler.mention, embed=embed)

    # ------------------------------------------------------------ result
    def result_text(self) -> str:
        mi = self.mi
        res = mi.result or {}
        t = res.get("type")
        if t == "win":
            return f"{mi.team_name(res['winner'])} won by {res.get('margin', '')}".strip()
        if t == "tie":
            return "Match tied"
        if t == "draw":
            return "Match drawn"
        if t == "abandoned":
            return "Match abandoned"
        return "Result pending"

    def compute_result(self):
        """Result after the 4th innings (spec §5.6, extended with ties/draws/innings wins)."""
        mi = self.mi
        res = mi.result or {}
        if res.get("type") == "win" and "margin" in res:
            return
        if res.get("type") in ("draw", "tie", "abandoned"):
            return
        if mi.target is not None and mi.innings == 4 and mi.score >= mi.target:
            wickets_left = GameChecks.all_out_limit(mi) - mi.wickets - mi.retired_not_out
            mi.result = {'type': 'win', 'winner': mi.batting_turn,
                         'margin': f"{wickets_left} wicket{'s' if wickets_left != 1 else ''}", 'reason': 'target_chased'}
        elif mi.innings == 4 and mi.target is not None and GameChecks.is_all_out(mi):
            runs_short = mi.target - mi.score - 1
            if runs_short == 0:
                mi.result = {'type': 'tie', 'reason': 'scores_level'}
            else:
                mi.result = {'type': 'win', 'winner': mi.bowling_turn,
                             'margin': f"{runs_short} run{'s' if runs_short != 1 else ''}", 'reason': 'all_out'}
        else:
            mi.result = {'type': 'draw', 'reason': (mi.result or {}).get('reason', 'time')}

    def pick_player_of_match(self):
        mi = self.mi
        totals = {}
        for card in mi.innings_scorecards.values():
            for r in card.get("batting", []):
                t = totals.setdefault(r["id"], {"name": r["name"], "runs": 0, "wickets": 0, "score": 0})
                t["runs"] += r["runs"]
                t["score"] += r["runs"] + (10 if r["runs"] >= 50 else 0)
            for r in card.get("bowling", []):
                t = totals.setdefault(r["id"], {"name": r["name"], "runs": 0, "wickets": 0, "score": 0})
                t["wickets"] += r["wickets"]
                t["score"] += r["wickets"] * 20 + r.get("hattricks", 0) * 20 - r["runs"] * 0.1
        if not totals:
            return None
        winner = mi.result.get("winner") if mi.result else None
        winners = {str(p.id) for p in mi.team(winner)} if winner else set()

        def key(item):
            pid, t = item
            return (t["score"] + (5 if pid in winners else 0), t["runs"], t["wickets"])
        pid, _ = max(totals.items(), key=key)
        mi.potm = pid
        return pid

    def generate_result_embed(self, rewards: dict | None = None):
        mi = self.mi
        res = mi.result or {}
        color = theme.GOLD if res.get("type") == "win" else theme.BLUE
        e = discord.Embed(title=f"{theme.TROPHY} {self.result_text()}", color=color)
        lines = []
        for n in sorted(mi.innings_scorecards):
            c = mi.innings_scorecards[n]
            tag = " (f/o)" if c.get("follow_on") else ""
            lines.append(f"`{c['team_name']} {theme.ordinal(n)} inns {c['runs']}/{c['wickets']}{'d' if c.get('declared') else ''} "
                         f"({c['overs']}){tag}`")
        e.description = (f"**{mi.team_settings['Team A name']} v/s {mi.team_settings['Team B name']}** • "
                         f"{mi.crr_day} day{'s' if mi.crr_day != 1 else ''} played\n" + "\n".join(lines))
        if mi.potm:
            name = next((r["name"] for c in mi.innings_scorecards.values() for r in c.get("batting", []) + c.get("bowling", [])
                         if r["id"] == str(mi.potm)), None)
            if name:
                runs = sum(r["runs"] for c in mi.innings_scorecards.values() for r in c.get("batting", []) if r["id"] == str(mi.potm))
                wkts = sum(r["wickets"] for c in mi.innings_scorecards.values() for r in c.get("bowling", []) if r["id"] == str(mi.potm))
                e.add_field(name="🌟 Player of the Match", value=f"**{name}** — {runs} runs, {wkts} wickets", inline=False)
        top_bat = {}
        top_bowl = {}
        for c in mi.innings_scorecards.values():
            for r in c.get("batting", []):
                top_bat[r["name"]] = top_bat.get(r["name"], 0) + r["runs"]
            for r in c.get("bowling", []):
                w, rr = top_bowl.get(r["name"], (0, 0))
                top_bowl[r["name"]] = (w + r["wickets"], rr + r["runs"])
        if top_bat:
            best = sorted(top_bat.items(), key=lambda x: -x[1])[:3]
            e.add_field(name=f"{theme.BAT} Most runs", value="\n".join(f"**{n}** {r}" for n, r in best), inline=True)
        if top_bowl:
            best = sorted(top_bowl.items(), key=lambda x: (-x[1][0], x[1][1]))[:3]
            e.add_field(name=f"{theme.BALL} Most wickets", value="\n".join(f"**{n}** {w}/{r}" for n, (w, r) in best), inline=True)
        if rewards:
            top = sorted(rewards.items(), key=lambda x: -x[1])[:8]
            names = {str(p.id): p.name for p in mi.players}
            e.add_field(name=f"{theme.COIN} {theme.CURRENCY} earned",
                        value=theme.truncate("\n".join(f"{names.get(str(pid), pid)}: +{amt}" for pid, amt in top)),
                        inline=False)
        url = theme.match_url(mi.match_id)
        if url:
            e.url = url
        e.set_footer(text=theme.footer_text(f"Match ID {mi.match_id} • {config.prefix}scorecard for full cards"))
        return e

    async def finalise_result(self):
        mi = self.mi
        self.compute_result()
        mi.phase = "finished"
        mi.ended_at = time.time()
        self.pick_player_of_match()
        rewards = {}
        recorder = getattr(self.bot, "record_match", None)
        if recorder is not None:
            try:
                rewards = await recorder(mi) or {}
            except Exception as e:
                logger.exception("failed to record match stats")
                reporter = getattr(self.bot, "report_error", None)
                if reporter:
                    await reporter(e, where=f"recording match {mi.match_id}")
        mi.rewards = rewards
        mgr = getattr(self.bot, "tournaments", None)
        if mgr is not None and getattr(mi, "tournament", None):
            await mgr.on_match_finished(mi)        # fixture result, table, bracket (never raises)
        from core.backend.views.utilites_view import MatchLinksView
        view = MatchLinksView(mi)
        embed = self.generate_result_embed(rewards)
        image = await self.scorecard_file("result")
        if image is not None:
            embed.set_image(url="attachment://scorecard.png")
            await self.send(embed=embed, view=view if view.children else None, file=image)
        else:
            await self.send(embed=embed, view=view if view.children else None)
        sheet = self.match_sheet_file()
        if sheet is not None:
            await self.send(content=f"📄 **Match sheet** — `match_{mi.match_id}.json` (public match data). "
                                    f"`{config.prefix}matchsheet {mi.match_id}` gets it again.", file=sheet)
        await self.close()

    def match_sheet_file(self):
        """The public JSON match sheet (match_<id>.json) as a discord.File, or None. Never raises."""
        if not config.game.get("match_sheet_file", True):
            return None
        try:
            from core.backend.match_sheet import build_match_sheet, sheet_file
            sheet = build_match_sheet(self.mi)
            self.mi.match_sheet = sheet
            return sheet_file(sheet)
        except Exception:
            logger.exception("could not build the match sheet")
            return None

    async def abandon(self):
        mi = self.mi
        mi.result = {"type": "abandoned", "reason": "abandoned"}
        mi.phase = "finished"
        mi.ended_at = time.time()
        for v in list(mi.pending_views.values()):
            v.stop()
        await self.send(embed=theme.embed("Match abandoned 🍂", "This match was abandoned. No stats or coins were recorded.", theme.GREY))
        mgr = getattr(self.bot, "tournaments", None)
        if mgr is not None and getattr(mi, "tournament", None):
            await mgr.on_match_abandoned(mi)       # the fixture goes back to "to be played"
        await self.close(delete_state=True)

    async def close(self, delete_state: bool = True):
        mi = self.mi
        if self.bot.active_matches.get(mi.channel.id) is mi:
            del self.bot.active_matches[mi.channel.id]
        if not hasattr(self.bot, "recent_matches"):
            self.bot.recent_matches = {}
        self.bot.recent_matches[mi.channel.id] = mi   # lets `scorecard` work right after the result
        store = getattr(self.bot, "store", None)
        if store is not None and delete_state:
            try:
                await store.finish(mi)
            except Exception:
                logger.exception("failed to finalise match storage")

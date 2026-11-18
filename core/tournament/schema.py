"""Tournament settings: the single definition used by the bot, the `t set` command and the website form.

Each entry: key -> dict(type, default, label, help, group, and min/max or choices where relevant).
Types: int | bool | choice | text | role | roles | channel.
`owner_only` settings can only be changed by the bot owner (they create coins).
The bot publishes this schema to the database (bot_settings key `tournament.schema`) so the website
renders and validates exactly the same fields.
"""

FORMATS = {
    "league": "League — everyone plays everyone, then optional play-offs",
    "groups": "Pools + knockout — round-robin pools, the best teams go to a knockout",
    "knockout": "Knockout — single elimination bracket",
}

STATUSES = ("setup", "registration", "ongoing", "completed", "cancelled")
ACTIVE_STATUSES = ("setup", "registration", "ongoing")

SETTINGS: dict[str, dict] = {
    # ── format
    "format": dict(type="choice", default="league", choices=list(FORMATS), group="Format", label="Format",
                   help="league, groups (pools + knockout) or knockout"),
    "groups": dict(type="int", default=2, min=1, max=8, group="Format", label="Number of pools",
                   help="Pools in the group stage (only for the groups format)"),
    "rounds": dict(type="int", default=1, min=1, max=2, group="Format", label="Round-robin legs",
                   help="1 = each pair meets once, 2 = home and away"),
    "qualifiers": dict(type="int", default=2, min=0, max=8, group="Format", label="Teams that qualify per pool",
                       help="Teams from each pool (or from the league table) that reach the knockout. 0 = no knockout: "
                            "the table decides the champion"),
    "max_teams": dict(type="int", default=16, min=2, max=64, group="Format", label="Maximum teams",
                      help="Team limit for this tournament"),
    # ── match rules
    "overs": dict(type="int", default=10, min=1, max=90, group="Match rules", label="Overs per day",
                  help="Overs bowled each day of a tournament match"),
    "days": dict(type="int", default=2, min=1, max=5, group="Match rules", label="Days per match",
                 help="Days in each tournament match"),
    "innings_overs": dict(type="int", default=-1, min=-1, max=450, group="Match rules", label="Innings over cap",
                          help="Most overs in one innings. -1 = same as overs per day, 0 = no cap"),
    "follow_on_pct": dict(type="int", default=50, min=0, max=100, group="Match rules", label="Follow-on %",
                          help="Follow-on is offered when the 2nd innings is below this % of the 1st"),
    "min_declare_overs": dict(type="int", default=5, min=0, max=90, group="Match rules", label="Overs before declaring",
                              help="Overs that must be bowled before a captain may declare"),
    "last_man_bats": dict(type="bool", default=False, group="Match rules", label="Last batter bats alone",
                          help="On: the innings ends only when every batter is out"),
    # ── teams
    "min_players": dict(type="int", default=2, min=1, max=11, group="Teams", label="Minimum players to play",
                        help="Players each side needs in the lobby before a tournament match can start"),
    "max_players": dict(type="int", default=11, min=1, max=11, group="Teams", label="Players per side",
                        help="Most players a side can field in one match"),
    "max_squad": dict(type="int", default=15, min=1, max=30, group="Teams", label="Squad size",
                      help="Most players on a team's roster"),
    # ── reps & substitutes
    "rep_run_cap": dict(type="int", default=30, min=0, max=500, group="Reps & substitutes", label="Rep run cap",
                        help="Most runs a representative (R) may score in one innings. 0 = no cap"),
    "rep_can_bowl": dict(type="bool", default=False, group="Reps & substitutes", label="Reps can bowl",
                         help="Off: representatives never bowl"),
    "rep_retire_counts_wicket": dict(type="bool", default=True, group="Reps & substitutes",
                                     label="Rep retiring counts as a wicket",
                                     help="On: a rep who reaches the cap is retired out (a wicket). Off: retired not out"),
    "max_reps": dict(type="int", default=0, min=0, max=11, group="Reps & substitutes", label="Reps per side",
                     help="Most reps a side may field in one match. 0 = no limit"),
    "allow_subs": dict(type="bool", default=True, group="Reps & substitutes", label="Substitutes during a match",
                       help="On: captains may bring in a roster player for someone who isn't available, mid-match"),
    "subs_outside_squad": dict(type="bool", default=False, group="Reps & substitutes",
                               label="Substitutes from outside the squad",
                               help="On: a substitute may be anyone not in the match (not only the team's registered "
                                    "squad). Players registered with the opponent are still refused. "
                                    "Quick switch: tour subs on|off"),
    "max_subs": dict(type="int", default=0, min=0, max=11, group="Reps & substitutes", label="Substitutions per side",
                     help="Most substitutions a side may make in one match. 0 = no limit"),
    # ── registration
    "team_creation": dict(type="choice", default="open", choices=["open", "staff"], group="Registration",
                          label="Who creates teams",
                          help="open = any registered player can create a team, staff = organisers only"),
    "team_join": dict(type="choice", default="invite", choices=["invite", "open", "staff"], group="Registration",
                      label="How players join teams",
                      help="invite = captains invite and players accept, open = players join any team with space, "
                           "staff = organisers place every player"),
    "registration_role": dict(type="role", default="", group="Registration", label="Role needed to register",
                              help="Only members with this role can register. Empty = everyone"),
    # ── points
    "points_win": dict(type="int", default=4, min=0, max=100, group="Points", label="Win", help="Points for a win"),
    "points_tie": dict(type="int", default=2, min=0, max=100, group="Points", label="Tie", help="Points for a tie"),
    "points_draw": dict(type="int", default=2, min=0, max=100, group="Points", label="Draw", help="Points for a draw"),
    "points_loss": dict(type="int", default=0, min=0, max=100, group="Points", label="Loss", help="Points for a loss"),
    "points_no_result": dict(type="int", default=1, min=0, max=100, group="Points", label="No result",
                             help="Points each when a match is recorded as no result"),
    "bonus_innings_win": dict(type="int", default=0, min=0, max=100, group="Points", label="Innings-win bonus",
                              help="Extra points for winning by an innings"),
    "bonus_first_innings_lead": dict(type="int", default=0, min=0, max=100, group="Points",
                                     label="First-innings lead bonus (draws)",
                                     help="Extra points in a drawn match for the side that led on first innings"),
    "knockout_draw_rule": dict(type="choice", default="first_innings", choices=["first_innings", "organiser"],
                               group="Points", label="Drawn knockout match",
                               help="first_innings = the side with the first-innings lead goes through, "
                                    "organiser = an organiser decides with the result command"),
    # ── automation
    "prompt_on_create": dict(type="bool", default=True, group="Automation", label="Ask on every new match",
                             help="When someone creates a match, ask whether it is a tournament match"),
    "captain_hosting": dict(type="bool", default=True, group="Automation", label="Captains can start their fixtures",
                            help="On: a captain of either team can mark a lobby as their tournament match. "
                                 "Off: organisers only"),
    "auto_advance": dict(type="bool", default=True, group="Automation", label="Advance stages automatically",
                         help="Build the knockout bracket when the pools finish, and close the tournament after the final"),
    "reminder_minutes": dict(type="int", default=15, min=0, max=1440, group="Automation", label="Fixture reminder",
                             help="Minutes before a scheduled fixture that the bot pings both teams. 0 = off"),
    "public": dict(type="bool", default=True, group="Automation", label="Show on the website",
                   help="Off: only members of this server who are logged in can open the tournament page"),
    # ── roles & channels
    "organizer_roles": dict(type="roles", default=[], group="Roles & channels", label="Organiser roles",
                            help="Members with any of these roles can run the tournament"),
    "player_role": dict(type="role", default="", group="Roles & channels", label="Player role",
                        help="Given to every player on a team"),
    "captain_role": dict(type="role", default="", group="Roles & channels", label="Captain role",
                         help="Given to team captains"),
    "auto_team_roles": dict(type="bool", default=False, group="Roles & channels", label="Create a role per team",
                            help="On: the bot creates and assigns a role for each team"),
    "announce_channel": dict(type="channel", default="", group="Roles & channels", label="Announcements channel",
                             help="Where the bot posts fixtures, reminders and news"),
    "results_channel": dict(type="channel", default="", group="Roles & channels", label="Results channel",
                            help="Where results are posted. Empty = the announcements channel"),
    "log_channel": dict(type="channel", default="", group="Roles & channels", label="Staff log channel",
                        help="Every organiser action is logged here"),
    # ── prizes (owner only: they create coins)
    "prize_champion": dict(type="int", default=0, min=0, max=10_000_000, group="Prizes", owner_only=True,
                           label="Champions (each player)", help="Coins for every player of the winning team"),
    "prize_runner_up": dict(type="int", default=0, min=0, max=10_000_000, group="Prizes", owner_only=True,
                            label="Runners-up (each player)", help="Coins for every player of the losing finalist"),
    "prize_mvp": dict(type="int", default=0, min=0, max=10_000_000, group="Prizes", owner_only=True,
                      label="Player of the tournament", help="Coins for the tournament's most valuable player"),
    "prize_participation": dict(type="int", default=0, min=0, max=10_000_000, group="Prizes", owner_only=True,
                                label="Every player", help="Coins for everyone who played at least one match"),
}

GROUP_LETTERS = "ABCDEFGH"


class SettingError(ValueError):
    pass


def defaults() -> dict:
    out = {}
    for key, spec in SETTINGS.items():
        d = spec["default"]
        out[key] = list(d) if isinstance(d, list) else d
    return out


def merged(settings: dict | None) -> dict:
    """Saved settings on top of the defaults (so new settings appear in old tournaments)."""
    out = defaults()
    for k, v in (settings or {}).items():
        if k in SETTINGS:
            out[k] = v
    return out


def _clean_id(value) -> str:
    import re
    m = re.search(r"\d{15,21}", str(value or ""))
    return m.group(0) if m else ""


def coerce(key: str, value):
    """Validate and convert one setting value. Raises SettingError with a user-facing message."""
    spec = SETTINGS.get(key)
    if spec is None:
        raise SettingError(f"There is no setting called `{key}`.")
    kind = spec["type"]
    if kind == "int":
        try:
            n = int(str(value).strip())
        except (TypeError, ValueError):
            raise SettingError(f"`{key}` needs a whole number.")
        if not spec["min"] <= n <= spec["max"]:
            raise SettingError(f"`{key}` must be between {spec['min']} and {spec['max']}.")
        return n
    if kind == "bool":
        if isinstance(value, bool):
            return value
        t = str(value).strip().lower()
        if t in ("1", "on", "true", "yes", "y", "enable", "enabled"):
            return True
        if t in ("0", "off", "false", "no", "n", "disable", "disabled"):
            return False
        raise SettingError(f"`{key}` is a switch: use `on` or `off`.")
    if kind == "choice":
        t = str(value).strip().lower()
        if t == "organizer":
            t = "organiser"
        if t not in spec["choices"]:
            raise SettingError(f"`{key}` must be one of: {', '.join(spec['choices'])}.")
        return t
    if kind in ("role", "channel"):
        t = str(value or "").strip().lower()
        if t in ("", "none", "off", "clear", "0", "null"):
            return ""
        cid = _clean_id(value)
        if not cid:
            raise SettingError(f"`{key}` needs a {kind} (mention it or use its ID), or `none` to clear it.")
        return cid
    if kind == "roles":
        if isinstance(value, (list, tuple)):
            items = [_clean_id(v) for v in value]
        else:
            t = str(value or "").strip().lower()
            if t in ("", "none", "off", "clear", "0"):
                return []
            import re
            items = re.findall(r"\d{15,21}", str(value))
            if not items:
                raise SettingError(f"`{key}` needs one or more roles, or `none` to clear it.")
        out = []
        for i in items:
            if i and i not in out:
                out.append(i)
        return out[:10]
    return str(value or "").strip()[:200]


def describe(key: str, value) -> str:
    """Human-readable value for embeds."""
    spec = SETTINGS[key]
    kind = spec["type"]
    if kind == "bool":
        return "on" if value else "off"
    if kind == "role":
        return f"<@&{value}>" if value else "not set"
    if kind == "channel":
        return f"<#{value}>" if value else "not set"
    if kind == "roles":
        return " ".join(f"<@&{v}>" for v in value) if value else "not set"
    return str(value)


def public_schema() -> dict:
    """JSON-friendly schema for the website."""
    return {"formats": FORMATS, "settings": [dict(key=k, **v) for k, v in SETTINGS.items()]}

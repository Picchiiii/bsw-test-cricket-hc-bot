"""Full innings scorecard embeds (batting + bowling tables)."""
import discord

from core.ui import theme


def _name(n: str, width: int = 13) -> str:
    n = n or "?"
    return (n[: width - 1] + "…") if len(n) > width else n.ljust(width)


def tagged(r: dict) -> str:
    """Name with its scorecard tags: (R) representative, (sub) substitute, 🤖 CPU."""
    n = r.get("name") or "?"
    if r.get("rep"):
        n += " (R)"
    if r.get("sub_for"):
        n += " (sub)"
    if r.get("cpu"):
        n += " 🤖"
    return n


def innings_card_embed(card: dict, match_title: str = "", footer: str = "") -> discord.Embed:
    n = card.get("innings", 1)
    tag = []
    if card.get("declared"):
        tag.append("declared")
    if card.get("follow_on"):
        tag.append("follow-on")
    if card.get("live"):
        tag.append("LIVE")
    e = discord.Embed(
        title=f"{card.get('team_name')} — {theme.ordinal(n)} innings",
        description=(f"{match_title}\n# {card.get('runs', 0)}/{card.get('wickets', 0)}{'d' if card.get('declared') else ''} "
                     f"({card.get('overs', '0.0')} ov)\n-# RR {card.get('run_rate', 0):.2f} • Extras (nb) {card.get('extras', 0)}"
                     + (f" • {', '.join(tag)}" if tag else "")),
        color=theme.CREAM,
    )
    lines = [f"{'Batter':<17} {'R':>3} {'B':>3} {'4s':>2} {'6s':>2} {'SR':>6}"]
    for r in card.get("batting", []):
        star = "*" if not r.get("is_out") else " "
        lines.append(f"{_name(tagged(r) + star, 17)} {r['runs']:>3} {r['balls']:>3} {r['fours']:>2} {r['sixes']:>2} {r['sr']:>6.1f}")
        lines.append(f"  └ {r['status']}"[:40])
    bat_block = "```\n" + "\n".join(lines) + "\n```"
    if len(bat_block) > 1024:
        bat_block = "```\n" + "\n".join(l for l in lines if not l.startswith("  └"))[:1000] + "\n```"
    e.add_field(name=f"{theme.BAT} Batting", value=bat_block, inline=False)
    if card.get("yet_to_bat"):
        e.add_field(name="Did not bat", value=theme.truncate(", ".join(card["yet_to_bat"])), inline=False)

    lines = [f"{'Bowler':<13} {'O':>4} {'M':>2} {'R':>3} {'W':>2} {'NB':>2} {'Eco':>5}"]
    for r in card.get("bowling", []):
        lines.append(f"{_name(tagged(r))} {r['overs']:>4} {r.get('maidens', 0):>2} {r['runs']:>3} {r['wickets']:>2} "
                     f"{r.get('no_balls', 0):>2} {r['econ']:>5.2f}")
    e.add_field(name=f"{theme.BALL} Bowling", value=theme.truncate("```\n" + "\n".join(lines) + "\n```"), inline=False)

    subs = card.get("substitutions") or []
    if subs:
        e.add_field(name="🔁 Substitutions", value=theme.truncate("\n".join(
            f"{x['in_name']}{' (R)' if x.get('rep') else ''} for {x['out_name']} (over {x['over']})" for x in subs)),
            inline=False)
    fow = card.get("fow", [])
    if fow:
        e.add_field(name="Fall of wickets",
                    value=theme.truncate(", ".join(f"{f['runs']}-{f['wicket']} ({f['player']}, {f['overs']})" for f in fow)),
                    inline=False)
    if any(r.get("rep") for r in card.get("batting", []) + card.get("bowling", [])):
        cap = card.get("rep_run_cap")
        footer = (footer + " • " if footer else "") + "(R) rep" + (f" — max {cap} runs" if cap else "")
    e.set_footer(text=theme.footer_text(footer))
    return e


class InningsSelect(discord.ui.Select):
    def __init__(self, cards: list, match_title: str, footer: str):
        self.cards = {str(c["innings"]): c for c in cards}
        self.match_title = match_title
        self.footer = footer
        options = [discord.SelectOption(label=f"Innings {c['innings']} — {c['team_name']}",
                                        description=f"{c['runs']}/{c['wickets']} ({c['overs']} ov)",
                                        value=str(c["innings"])) for c in cards]
        super().__init__(placeholder="Switch innings…", options=options[:25])

    async def callback(self, interaction: discord.Interaction):
        card = self.cards[self.values[0]]
        await interaction.response.edit_message(embed=innings_card_embed(card, self.match_title, self.footer), view=self.view)


class InningsView(discord.ui.View):
    def __init__(self, cards: list, match_title: str, footer: str = ""):
        super().__init__(timeout=300)
        if len(cards) > 1:
            self.add_item(InningsSelect(cards, match_title, footer))

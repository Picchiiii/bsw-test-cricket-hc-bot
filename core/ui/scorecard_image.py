"""PNG scorecard posted at stumps and at the end of a match.

build_scorecard_data(mi) takes a plain-data snapshot (safe to render in a worker thread);
render_scorecard(data) draws it with Pillow and returns PNG bytes.
The look matches the website: a green manual scoreboard header with tile numerals, then the
batting and bowling card of every innings.
"""
import io
import os

from core.config import config

FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")
BOLD = os.path.join(FONT_DIR, "DejaVuSansCondensed-Bold.ttf")
REGULAR = os.path.join(FONT_DIR, "DejaVuSansCondensed.ttf")

STONE = (232, 235, 228)
PAPER = (247, 248, 244)
BOARD = (22, 64, 43)
BOARD_DEEP = (15, 46, 31)
CHALK = (244, 246, 239)
SOFT = (200, 211, 200)
GOLD = (226, 169, 59)
RED = (168, 50, 45)
INK = (29, 38, 32)
MUTED = (93, 106, 96)
LINE = (214, 220, 209)
HEAD = (238, 241, 234)

W = 1200
PAD = 44
ROW = 34


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def build_scorecard_data(mi, mode: str) -> dict:
    """Snapshot everything the image needs. mode: 'stumps' or 'result'."""
    game = mi.game
    cards = [mi.innings_scorecards[n] for n in sorted(mi.innings_scorecards)]
    if mi.phase == "innings" and game is not None and (mi.overs or mi.balls_this_over or mi.batting_order):
        live = game.build_innings_card()
        cards = [c for c in cards if c["innings"] != mi.innings] + [live]
    if mode == "result":
        headline = game.result_text() if game else "Result"
        state = f"Result • {mi.crr_day} day{'s' if mi.crr_day != 1 else ''} played"
        status = ""
    else:
        headline = ""
        state = f"Stumps • End of day {mi.crr_day} of {mi.match_settings.get('days') or '?'}"
        status = game.lead_trail_or_target() if game else ""
    potm = None
    if mi.potm:
        for c in cards:
            for r in c.get("batting", []) + c.get("bowling", []):
                if r["id"] == str(mi.potm):
                    potm = r["name"]
    return {
        "mode": mode,
        "team_a": mi.team_settings["Team A name"],
        "team_b": mi.team_settings["Team B name"],
        "state": state,
        "headline": headline,
        "status": status,
        "cards": cards,
        "potm": potm,
        "match_id": mi.match_id,
        "website": config.website_url,
        "bot_name": config.bot_name,
    }


def render_scorecard(data: dict) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    def font(size, bold=False):
        try:
            return ImageFont.truetype(BOLD if bold else REGULAR, size)
        except OSError:
            return ImageFont.load_default(size)

    f_brand = font(22, True)
    f_title = font(44, True)
    f_state = font(22)
    f_tile = font(84, True)
    f_head = font(54, True)
    f_strip = font(21)
    f_strip_b = font(21, True)
    f_sec = font(27, True)
    f_th = font(17, True)
    f_row = font(20)
    f_row_b = font(20, True)
    f_small = font(16)

    def fit(draw, text, f, width):
        text = str(text)
        if draw.textlength(text, font=f) <= width:
            return text
        while text and draw.textlength(text + "…", font=f) > width:
            text = text[:-1]
        return text + "…"

    def wrap(draw, text, f, width):
        words, lines, cur = str(text).split(), [], ""
        for w in words:
            trial = f"{cur} {w}".strip()
            if draw.textlength(trial, font=f) <= width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines[:3]

    cards = data["cards"]
    scratch = ImageDraw.Draw(Image.new("RGB", (10, 10)))

    # ── heights ──
    head_lines = wrap(scratch, data["headline"], f_head, W - 2 * PAD - 60) if data["mode"] == "result" else []
    board_h = 40 + 30 + 56 + 36 + 22
    if data["mode"] == "result":
        board_h += len(head_lines) * 62 + 10
    elif cards:
        board_h += 120
    if data["status"]:
        board_h += 40
    done_cards = [c for c in cards]
    if done_cards:
        board_h += 46
    sections_h = 0
    for c in cards:
        rows = max(len(c.get("batting", [])) + 2, len(c.get("bowling", [])) + 1)
        sections_h += 60 + 40 + rows * ROW + (34 if c.get("fow") else 0) + 30
    foot_h = 80
    H = PAD + board_h + 26 + sections_h + foot_h

    img = Image.new("RGB", (W, H), STONE)
    d = ImageDraw.Draw(img)

    # ── scoreboard header ──
    x0, y0, x1 = PAD, PAD, W - PAD
    d.rounded_rectangle((x0, y0, x1, y0 + board_h), radius=10, fill=BOARD_DEEP)
    d.rounded_rectangle((x0 + 7, y0 + 7, x1 - 7, y0 + board_h - 7), radius=7, fill=BOARD)
    x = x0 + 34
    y = y0 + 30
    d.text((x, y), data["bot_name"], font=f_brand, fill=GOLD)
    y += 34
    d.text((x, y), fit(d, f"{data['team_a']} v {data['team_b']}", f_title, x1 - x - 40), font=f_title, fill=CHALK)
    y += 56
    dot_col = GOLD if data["mode"] == "result" else SOFT
    d.ellipse((x, y + 8, x + 12, y + 20), fill=dot_col)
    d.text((x + 20, y), data["state"], font=f_state, fill=SOFT)
    y += 40

    if data["mode"] == "result":
        for line in head_lines:
            d.text((x, y), line, font=f_head, fill=GOLD)
            y += 62
        y += 10
    elif cards:
        c = cards[-1]
        d.text((x, y), fit(d, f"{c['team_name']} • {_ordinal(c['innings'])} innings", f_strip_b, 600), font=f_strip_b, fill=SOFT)
        ty = y + 30
        tx = x
        score = f"{c['runs']}/{c['wickets']}{'d' if c.get('declared') else ''}"
        for ch in score:
            if ch == "/":
                d.text((tx + 4, ty - 2), "/", font=f_tile, fill=GOLD)
                tx += int(d.textlength("/", font=f_tile)) + 10
                continue
            cw = max(62, int(d.textlength(ch, font=f_tile)) + 16)
            d.rounded_rectangle((tx, ty, tx + cw, ty + 84), radius=5, fill=BOARD_DEEP)
            d.text((tx + cw / 2, ty + 42), ch, font=f_tile, fill=CHALK, anchor="mm")
            tx += cw + 6
        ox = max(tx + 50, x + 420)
        d.text((ox, ty + 6), "Overs", font=f_small, fill=SOFT)
        d.text((ox, ty + 28), str(c["overs"]), font=f_sec, fill=CHALK)
        d.text((ox + 140, ty + 6), "Run rate", font=f_small, fill=SOFT)
        d.text((ox + 140, ty + 28), f"{c.get('run_rate', 0):.2f}", font=f_sec, fill=CHALK)
        not_out = [r for r in c.get("batting", []) if not r["is_out"]]
        if not_out:
            r = not_out[-1]
            d.text((ox + 280, ty + 6), "Not out", font=f_small, fill=SOFT)
            d.text((ox + 280, ty + 28), fit(d, f"{r['name']} {r['runs']}*", f_sec, x1 - ox - 320), font=f_sec, fill=CHALK)
        y += 120
    if data["status"]:
        d.text((x, y), fit(d, data["status"], f_strip, x1 - x - 40), font=f_strip, fill=CHALK)
        y += 40
    if done_cards:
        d.line((x, y, x1 - 34, y), fill=(44, 91, 64), width=1)
        y += 12
        sx = x
        for c in done_cards:
            label = f"{c['team_name']} {_ordinal(c['innings'])}"
            score = f" {c['runs']}/{c['wickets']}{'d' if c.get('declared') else ''}"
            lw = d.textlength(label, font=f_strip)
            sw = d.textlength(score, font=f_strip_b)
            if sx + lw + sw > x1 - 40:
                break
            d.text((sx, y), label, font=f_strip, fill=SOFT)
            d.text((sx + lw, y), score, font=f_strip_b, fill=CHALK)
            sx += lw + sw + 34

    # ── innings sections ──
    y = PAD + board_h + 26
    bat_x, bat_w = PAD, 690
    bowl_x = PAD + bat_w + 24
    bowl_w = W - PAD - bowl_x
    for c in cards:
        title = f"{c['team_name']} — {_ordinal(c['innings'])} innings"
        if c.get("follow_on"):
            title += " (following on)"
        total = f"{c['runs']}/{c['wickets']}{'d' if c.get('declared') else ''}  ({c['overs']} ov)"
        d.text((PAD, y + 12), fit(d, title, f_sec, W - 2 * PAD - 260), font=f_sec, fill=INK)
        d.text((W - PAD, y + 14), total, font=f_sec, fill=BOARD, anchor="ra")
        d.line((PAD, y + 52, W - PAD, y + 52), fill=BOARD, width=3)
        y += 60

        # batting table
        rows = c.get("batting", [])
        n_bat = len(rows) + 2
        d.rectangle((bat_x, y, bat_x + bat_w, y + 40 + n_bat * ROW), fill=PAPER, outline=LINE)
        d.rectangle((bat_x, y, bat_x + bat_w, y + 40), fill=HEAD)
        cols = [("R", bat_x + bat_w - 210), ("B", bat_x + bat_w - 150), ("4s", bat_x + bat_w - 95), ("6s", bat_x + bat_w - 40)]
        d.text((bat_x + 14, y + 11), "Batter", font=f_th, fill=MUTED)
        for label, cx in cols:
            d.text((cx, y + 11), label, font=f_th, fill=MUTED, anchor="ra")
        ry = y + 40
        for r in rows:
            name = r["name"] + (" (R)" if r.get("rep") else "") + (" (sub)" if r.get("sub_for") else "") \
                + ("" if r["is_out"] else "*")
            d.text((bat_x + 14, ry + 7), fit(d, name, f_row_b, 200), font=f_row_b, fill=INK)
            how = "not out" if r["status"] in ("batting", "not out") else r["status"]
            d.text((bat_x + 224, ry + 9), fit(d, how, f_small, bat_w - 224 - 240), font=f_small,
                   fill=RED if r["is_out"] else MUTED)
            for (label, cx), val in zip(cols, (r["runs"], r["balls"], r["fours"], r["sixes"])):
                d.text((cx, ry + 7), str(val), font=f_row_b if label == "R" else f_row, fill=INK, anchor="ra")
            d.line((bat_x + 1, ry + ROW, bat_x + bat_w - 1, ry + ROW), fill=LINE)
            ry += ROW
        d.text((bat_x + 14, ry + 7), "Extras (no-balls)", font=f_row, fill=MUTED)
        d.text((cols[0][1], ry + 7), str(c.get("extras", 0)), font=f_row, fill=INK, anchor="ra")
        ry += ROW
        d.text((bat_x + 14, ry + 7), "Total", font=f_row_b, fill=INK)
        d.text((cols[0][1], ry + 7), f"{c['runs']}/{c['wickets']}", font=f_row_b, fill=INK, anchor="ra")
        d.text((bat_x + bat_w - 14, ry + 7), f"RR {c.get('run_rate', 0):.2f}", font=f_row, fill=MUTED, anchor="ra")
        bat_bottom = ry + ROW

        # bowling table
        brows = c.get("bowling", [])
        n_bowl = max(1, len(brows))
        d.rectangle((bowl_x, y, bowl_x + bowl_w, y + 40 + n_bowl * ROW), fill=PAPER, outline=LINE)
        d.rectangle((bowl_x, y, bowl_x + bowl_w, y + 40), fill=HEAD)
        bcols = [("O", bowl_x + bowl_w - 160), ("M", bowl_x + bowl_w - 118), ("R", bowl_x + bowl_w - 66), ("W", bowl_x + bowl_w - 18)]
        d.text((bowl_x + 14, y + 11), "Bowler", font=f_th, fill=MUTED)
        for label, cx in bcols:
            d.text((cx, y + 11), label, font=f_th, fill=MUTED, anchor="ra")
        ry = y + 40
        for r in brows:
            d.text((bowl_x + 14, ry + 7), fit(d, r["name"] + (" (R)" if r.get("rep") else "") + (" (sub)" if r.get("sub_for") else ""),
                                              f_row, bowl_w - 200), font=f_row, fill=INK)
            for (label, cx), val in zip(bcols, (r["overs"], r.get("maidens", 0), r["runs"], r["wickets"])):
                d.text((cx, ry + 7), str(val), font=f_row_b if label == "W" else f_row, fill=INK, anchor="ra")
            d.line((bowl_x + 1, ry + ROW, bowl_x + bowl_w - 1, ry + ROW), fill=LINE)
            ry += ROW
        if not brows:
            d.text((bowl_x + 14, ry + 7), "No balls bowled", font=f_row, fill=MUTED)
            ry += ROW

        y = max(bat_bottom, ry) + 8
        if c.get("fow"):
            fow = "FOW: " + ", ".join(f"{f['runs']}-{f['wicket']} ({f['player']}, {f['overs']})" for f in c["fow"])
            d.text((PAD, y + 4), fit(d, fow, f_small, W - 2 * PAD), font=f_small, fill=MUTED)
            y += 34
        y += 22

    # ── footer ──
    y = H - foot_h + 16
    d.line((PAD, y - 10, W - PAD, y - 10), fill=LINE, width=1)
    left = f"Player of the match: {data['potm']}" if data.get("potm") else ""
    if left:
        d.text((PAD, y + 4), fit(d, left, f_row_b, W - 2 * PAD - 430), font=f_row_b, fill=INK)
    right = f"Match {data['match_id']}"
    if data.get("website"):
        right = f"{data['website'].replace('https://', '')}  •  {right}"
    d.text((W - PAD, y + 6), right, font=f_small, fill=MUTED, anchor="ra")

    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()

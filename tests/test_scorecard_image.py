import io
import os
import random

from PIL import Image

from harness import World, make_players, random_strategy, never_out, wait_until
from util import run

OUT = os.getenv("BSW_IMAGE_DIR")


def _png(msg):
    assert msg.embed.image == "attachment://scorecard.png"
    f = msg.files[0]
    assert f.filename == "scorecard.png"
    data = f.fp.getvalue()
    img = Image.open(io.BytesIO(data))
    assert img.format == "PNG" and img.width == 1200 and img.height > 400
    assert len(data) < 8 * 1024 * 1024, "Discord upload limit"
    return data


@run
async def test_image_at_stumps_and_result():
    random.seed(12)
    w = World()
    await w.setup()
    ch = w.channel()
    names_a = ["Rohit", "Virat", "Shubman", "Rishabh", "Ravindra", "Jasprit"]
    names_b = ["Pat", "Steve", "Marnus", "Travis", "Mitchell", "Nathan"]
    a = make_players(w, names_a, strategy=random_strategy)
    b = make_players(w, names_b, strategy=random_strategy)
    mi = await w.setup_match(ch, a, b, overs=3, days=5)
    mi.team_settings["Team A name"], mi.team_settings["Team B name"] = "India", "Australia"
    await w.finish(mi, timeout=120)
    stumps = [m for m in ch.messages if m.embed and (m.embed.title or "").startswith("🌙 Stumps")]
    result = [m for m in ch.messages if m.embed and (m.embed.title or "").startswith("🏆")]
    assert stumps, "at least one day ended in this match"
    assert len(result) == 1
    for i, m in enumerate(stumps):
        data = _png(m)
        if OUT:
            open(os.path.join(OUT, f"stumps_{i + 1}.png"), "wb").write(data)
    data = _png(result[0])
    if OUT:
        open(os.path.join(OUT, "result.png"), "wb").write(data)


@run
async def test_long_names_and_full_teams_render():
    w = World()
    await w.setup()
    ch = w.channel()
    a = make_players(w, [f"A_very_long_username_number_{i}_ξψζ" for i in range(11)], strategy=never_out)
    b = make_players(w, [f"Bowler{i}" for i in range(11)], strategy=never_out)
    mi = await w.setup_match(ch, a, b, overs=2, days=1, innings_overs=0)
    await w.finish(mi, timeout=60)
    msg = [m for m in ch.messages if m.embed and (m.embed.title or "").startswith("🏆")][0]
    data = _png(msg)
    if OUT:
        open(os.path.join(OUT, "long_names.png"), "wb").write(data)


@run
async def test_missing_pillow_still_posts_result(monkeypatch=None):
    import core.ui.scorecard_image as sc
    original = sc.render_scorecard

    def boom(_):
        raise ImportError("No module named PIL")
    sc.render_scorecard = boom
    try:
        w = World()
        await w.setup()
        ch = w.channel()
        a = make_players(w, ["A0", "A1"], strategy=random_strategy)
        b = make_players(w, ["B0", "B1"], strategy=random_strategy)
        mi = await w.setup_match(ch, a, b, overs=2, days=2)
        await w.finish(mi)
        result = [m for m in ch.messages if m.embed and (m.embed.title or "").startswith("🏆")]
        assert len(result) == 1 and not result[0].files
    finally:
        sc.render_scorecard = original

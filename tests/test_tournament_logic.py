"""Pure tournament maths: round-robins, brackets, points tables, qualifiers, time parsing, settings."""
import pytest

from core.tournament import logic, schema


def test_round_robin_everyone_meets_once():
    for n in (2, 3, 4, 5, 6, 7, 8):
        teams = [f"T{i}" for i in range(n)]
        rounds = logic.round_robin(teams)
        pairs = [frozenset(p) for rnd in rounds for p in rnd]
        assert len(pairs) == n * (n - 1) // 2
        assert len(set(pairs)) == len(pairs)
        for rnd in rounds:                      # nobody plays twice in one round
            flat = [x for p in rnd for x in p]
            assert len(flat) == len(set(flat))
    assert logic.round_robin(["A"]) == []


def test_round_robin_two_legs_swaps_home_and_away():
    rounds = logic.round_robin(["A", "B", "C", "D"], legs=2)
    games = [p for rnd in rounds for p in rnd]
    assert len(games) == 12
    assert all((b, a) in games for a, b in games)


def test_bracket_order_keeps_top_seeds_apart():
    assert logic.bracket_order(2) == [1, 2]
    assert logic.bracket_order(4) == [1, 4, 2, 3]
    assert logic.bracket_order(8) == [1, 8, 4, 5, 2, 7, 3, 6]


def test_knockout_with_power_of_two():
    fx = logic.build_knockout(["s1", "s2", "s3", "s4"])
    assert [f["stage"] for f in fx] == ["sf", "sf", "final"]
    assert (fx[0]["team_a"], fx[0]["team_b"]) == ("s1", "s4")
    assert (fx[1]["team_a"], fx[1]["team_b"]) == ("s2", "s3")
    assert fx[2]["source_a"] == fx[0]["key"] and fx[2]["source_b"] == fx[1]["key"]


def test_knockout_byes_go_to_top_seeds():
    fx = logic.build_knockout(["s1", "s2", "s3"])
    assert len(fx) == 2
    semi, final = fx
    assert (semi["team_a"], semi["team_b"]) == ("s2", "s3")
    assert final["stage"] == "final" and final["team_a"] == "s1" and final["source_b"] == semi["key"]
    six = logic.build_knockout([f"s{i}" for i in range(1, 7)])
    assert len(six) == 5                              # 2 quarter-finals, 2 semis, final
    assert [f["stage"] for f in six].count("qf") == 2
    semis = [f for f in six if f["stage"] == "sf"]
    assert {semis[0]["team_a"], semis[1]["team_a"]} == {"s1", "s2"}     # the two byes
    assert logic.build_knockout(["only"]) == []


def _fx(n, a, b, rtype, winner=None, summary=None, group="", stage="group"):
    return {"number": n, "stage": stage, "status": "walkover" if rtype == "walkover" else "completed", "group_name": group,
            "team_a_id": a, "team_b_id": b, "result_type": rtype, "winner_team_id": winner, "summary": summary or {},
            "updated_at": n}


def _teams(*names, group=""):
    return [{"team_id": n, "name": n, "tag": n[:3], "group_name": group, "status": "active"} for n in names]


def test_points_table_points_nrr_and_order():
    s = schema.defaults()
    s.update(bonus_innings_win=1, bonus_first_innings_lead=1)
    teams = _teams("A", "B", "C")
    fixtures = [
        _fx(1, "A", "B", "win", "A", {"teams": {"A": {"runs": 120, "balls": 60}, "B": {"runs": 60, "balls": 60}},
                                      "innings_win": True}),
        _fx(2, "B", "C", "draw", None, {"teams": {"B": {"runs": 50, "balls": 60}, "C": {"runs": 40, "balls": 60}},
                                        "fi_leader": "B"}),
        _fx(3, "A", "C", "tie", None, {}),
        _fx(4, "A", "C", "walkover", "C"),
        _fx(5, "A", "B", "win", "A", stage="final"),          # knockout matches never count for the table
    ]
    table = logic.compute_standings(teams, fixtures, s)[""]
    by = {r["team_id"]: r for r in table}
    assert by["A"]["points"] == s["points_win"] + 1 + s["points_tie"] + s["points_loss"]
    assert by["B"]["points"] == s["points_loss"] + s["points_draw"] + 1
    assert by["C"]["points"] == s["points_draw"] + s["points_tie"] + s["points_win"]
    assert (by["A"]["played"], by["A"]["won"], by["A"]["lost"], by["A"]["tied"]) == (3, 1, 1, 1)
    assert by["A"]["nrr"] == pytest.approx(12.0 - 6.0)
    assert by["C"]["nrr"] == pytest.approx(4.0 - 5.0)         # the walkover does not touch net run rate
    assert [r["rank"] for r in table] == [1, 2, 3]
    assert table[0]["points"] >= table[1]["points"] >= table[2]["points"]
    assert by["A"]["form"] == ["W", "T", "L"]


def test_qualifiers_cross_pool_pairings():
    def table(g):
        return [{"team_id": f"{g}{i}", "name": f"{g}{i}", "points": 10 - i, "won": 3 - i, "nrr": 0, "status": "active"}
                for i in (1, 2, 3)]
    two = logic.pick_qualifiers({"A": table("A"), "B": table("B")}, 2)
    assert two == ["A1", "B1", "A2", "B2"]
    semis = logic.build_knockout(two)
    assert {(f["team_a"], f["team_b"]) for f in semis if f["stage"] == "sf"} == {("A1", "B2"), ("B1", "A2")}
    four = logic.pick_qualifiers({g: table(g) for g in "ABCD"}, 2)
    qf = {frozenset((f["team_a"], f["team_b"])) for f in logic.build_knockout(four) if f["stage"] == "qf"}
    assert qf == {frozenset(p) for p in (("A1", "B2"), ("B1", "A2"), ("C1", "D2"), ("D1", "C2"))}
    assert logic.pick_qualifiers({"": table("L")}, 2) == ["L1", "L2"]
    assert logic.pick_qualifiers({"": table("L")}, 0) == []


def test_player_table_and_leaderboards():
    rows = [
        {"userid": "1", "name": "Ann", "innings_batted": 2, "not_outs": 1, "runs": 80, "balls": 60, "fours": 4, "sixes": 2,
         "highest": 55, "outs": 1, "fifties": 1, "hundreds": 0, "ducks": 0, "wickets": 1, "balls_bowled": 12,
         "runs_conceded": 20, "maidens": 0, "five_wickets": 0, "hattricks": 0, "best_w": 1, "best_r": 20, "potm": 1},
        {"userid": "1", "name": "Ann", "innings_batted": 1, "not_outs": 0, "runs": 20, "balls": 20, "fours": 1, "sixes": 0,
         "highest": 20, "outs": 1, "fifties": 0, "hundreds": 0, "ducks": 0, "wickets": 3, "balls_bowled": 12,
         "runs_conceded": 9, "maidens": 1, "five_wickets": 0, "hattricks": 1, "best_w": 3, "best_r": 9, "potm": 0},
        {"userid": "2", "name": "Bob", "innings_batted": 1, "not_outs": 0, "runs": 0, "balls": 3, "fours": 0, "sixes": 0,
         "highest": 0, "outs": 1, "fifties": 0, "hundreds": 0, "ducks": 1, "wickets": 0, "balls_bowled": 0,
         "runs_conceded": 0, "maidens": 0, "five_wickets": 0, "hattricks": 0, "best_w": 0, "best_r": 0, "potm": 0},
    ]
    table = logic.aggregate_players(rows, {"1": "T1"})
    ann = next(r for r in table if r["userid"] == "1")
    assert (ann["matches"], ann["runs"], ann["highest"], ann["wickets"]) == (2, 100, 55, 4)
    assert ann["average"] == 50.0 and (ann["best_w"], ann["best_r"]) == (3, 9) and ann["team_id"] == "T1"
    assert ann["mvp"] == 100 + 80 + 10 + 20 + 15
    assert logic.leaders(table, "runs")[0]["name"] == "Ann"
    assert [r["name"] for r in logic.leaders(table, "wickets")] == ["Ann"]      # Bob never bowled
    for cat in logic.LEADERBOARDS:
        for r in logic.leaders(table, cat):
            assert isinstance(logic.LEADERBOARDS[cat][2](r), str)


def test_parse_time():
    now = 1_700_000_000
    assert logic.parse_time("+2h", now) == now + 7200
    assert logic.parse_time("in 1d12h", now) == now + 36 * 3600
    assert logic.parse_time("90m", now) == now + 5400
    assert logic.parse_time("2030-01-02 18:30", now) == 1893609000
    assert logic.parse_time("<t:1893609000:F>", now) == 1893609000
    assert logic.parse_time("1893609000", now) == 1893609000
    assert logic.parse_time("none", now) == 0
    with pytest.raises(ValueError):
        logic.parse_time("next tuesday maybe", now)


def test_settings_validation():
    assert schema.coerce("overs", "12") == 12
    assert schema.coerce("last_man_bats", "on") is True and schema.coerce("public", "off") is False
    assert schema.coerce("format", "GROUPS") == "groups"
    assert schema.coerce("player_role", "<@&123456789012345678>") == "123456789012345678"
    assert schema.coerce("player_role", "none") == ""
    assert schema.coerce("organizer_roles", "<@&123456789012345678> <@&223456789012345678>") == [
        "123456789012345678", "223456789012345678"]
    assert schema.coerce("announce_channel", "<#123456789012345678>") == "123456789012345678"
    for key, bad in (("overs", "500"), ("overs", "x"), ("format", "swiss"), ("public", "maybe"),
                     ("player_role", "everyone"), ("nope", "1")):
        with pytest.raises(schema.SettingError):
            schema.coerce(key, bad)
    merged = schema.merged({"overs": 20, "gone_setting": 1})
    assert merged["overs"] == 20 and "gone_setting" not in merged and merged["days"] == 2
    assert set(merged) == set(schema.SETTINGS)
    assert all(s["group"] and s["label"] and s["help"] for s in schema.SETTINGS.values())



def get_performance(type: str, player_data: dict):
    if type == "batsman":
        runs = player_data.get("runs", 0)
        balls = player_data.get("balls", 0)
        strike_rate = (runs / balls) * 100 if balls > 0 else 0
        performance = f"{runs}r, {balls}b, {strike_rate:.2f}sr"
    elif type == "bowler":
        balls = player_data.get("balls_given", 0)
        overs = balls // 6
        remaining_balls = balls % 6

        overs_bowled = f"{overs}.{remaining_balls}"
        runs = player_data.get("runs_given", 0)
        wickets = player_data.get("wickets", 0)
        Economy = runs / (balls / 6) if balls > 0 else 0

        performance = f"{overs_bowled}o, {runs}r, {wickets}w, {Economy:.2f}eco"
    else:
        performance = "Invalid player type. Must be 'batsman' or 'bowler'."

    return performance

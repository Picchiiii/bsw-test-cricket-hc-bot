

def get_performance(type: str, player_data: dict):
    if type == "batsman":
        runs = player_data["runs"]
        balls = player_data["balls"]
        strike_rate = (runs / balls) * 100 if balls > 0 else 0
        performance = f"{runs} Runs, {balls} Balls, {strike_rate:.2f} Strike Rate"
    elif type == "bowler":
        balls = player_data["balls_given"]
        overs = balls // 6
        remaining_balls = balls % 6

        overs_bowled = f"{overs}.{remaining_balls}"
        runs = player_data["runs_given"]
        wickets = player_data["wickets"]
        Economy = runs / (balls / 6) if balls > 0 else 0

        performance = f"{overs_bowled} Overs, {runs} Runs, {wickets} Wickets, {Economy:.2f} Economy"
    else:
        performance = "Invalid player type. Must be 'batsman' or 'bowler'."

    return performance
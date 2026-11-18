"""Shop catalogue. Purely cosmetic items so coins never affect match outcomes."""

ITEMS = [
    # titles (shown under your name on profile)
    {"id": "rookie", "name": "Rookie", "type": "title", "price": 500, "value": "Rookie"},
    {"id": "net_bowler", "name": "Net Bowler", "type": "title", "price": 1500, "value": "Net Bowler"},
    {"id": "opener", "name": "Opener", "type": "title", "price": 2500, "value": "Opener"},
    {"id": "night_watchman", "name": "Night Watchman", "type": "title", "price": 4000, "value": "Night Watchman"},
    {"id": "the_wall", "name": "The Wall", "type": "title", "price": 7500, "value": "The Wall"},
    {"id": "spin_wizard", "name": "Spin Wizard", "type": "title", "price": 7500, "value": "Spin Wizard"},
    {"id": "captain_cool", "name": "Captain Cool", "type": "title", "price": 10000, "value": "Captain Cool"},
    {"id": "test_legend", "name": "Test Legend", "type": "title", "price": 25000, "value": "Test Legend"},
    # profile colours (embed colour of your profile)
    {"id": "emerald", "name": "Emerald Green", "type": "color", "price": 2000, "value": "1F6B3A"},
    {"id": "royal_blue", "name": "Royal Blue", "type": "color", "price": 2000, "value": "2F5DD6"},
    {"id": "crimson", "name": "Crimson", "type": "color", "price": 2000, "value": "C0283C"},
    {"id": "midnight", "name": "Midnight", "type": "color", "price": 3000, "value": "1B1E2B"},
    {"id": "sakura", "name": "Sakura Pink", "type": "color", "price": 3000, "value": "F19CBB"},
    {"id": "gold", "name": "Gold", "type": "color", "price": 5000, "value": "E8B84A"},
    # badges (all owned badges are shown on your profile)
    {"id": "badge_bat", "name": "Willow", "type": "badge", "price": 1000, "value": "🏏"},
    {"id": "badge_ball", "name": "New Ball", "type": "badge", "price": 1000, "value": "🥎"},
    {"id": "badge_fire", "name": "On Fire", "type": "badge", "price": 3000, "value": "🔥"},
    {"id": "badge_cap", "name": "Test Cap", "type": "badge", "price": 6000, "value": "🧢"},
    {"id": "badge_trophy", "name": "Silverware", "type": "badge", "price": 12000, "value": "🏆"},
    {"id": "badge_crown", "name": "Crown", "type": "badge", "price": 30000, "value": "👑"},
    {"id": "badge_diamond", "name": "Diamond", "type": "badge", "price": 50000, "value": "💎"},
]

BY_ID = {i["id"]: i for i in ITEMS}


def find_item(query: str):
    q = (query or "").strip().lower().replace(" ", "_")
    if q in BY_ID:
        return BY_ID[q]
    for item in ITEMS:
        if item["name"].lower().replace(" ", "_") == q or item["name"].lower() == (query or "").strip().lower():
            return item
    for item in ITEMS:
        if q and q in item["id"]:
            return item
    return None

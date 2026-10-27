
XP_LEVELS = {
    1:0,
    2:100,
    3:250,
    4:500,
    5:1000
}

def calculate_level(total_xp:int) -> int:
    level = 1

    for current_level,required_xp in XP_LEVELS.items():
        if total_xp >= required_xp:
            level = current_level
        else:
            break

    return level

from app.services.xp import calculate_level

test_values = [0,50,100,120,249,250,500,999,1000]

for xp in test_values:
    level = calculate_level(xp)

    print(f"xp={xp:4}->Level = {level}")
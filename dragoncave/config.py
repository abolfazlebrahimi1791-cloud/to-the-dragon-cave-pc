#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""To the Dragon Cave - global configuration and game data.

All values (levels, enemies, weapons, prices, timings) were reverse-
engineered from the original Android APK (IL2CPP dump + ARM disassembly)
including the game's original bugs and quirks.
"""

import os
import random

# ----------------------------------------------------------------------------
# Paths - the package lives in <game>/dragoncave/, data next to it
# ----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIO_DIR = os.path.join(BASE_DIR, "audio")
# Player save data = plain JSON file next to the program:
#   save.json     - full GameSession (progress, gold, difficulty, ...)
GAME_SESSION_FILE = os.path.join(BASE_DIR, "save.json")

# ----------------------------------------------------------------------------
# Unity-compatible random helpers (bugs included!)
# ----------------------------------------------------------------------------
def unity_random_range_int(a, b):
    """Unity Random.Range(int,int): result = (int)(a + rnd*(b-a)).
    The original game uses e.g. Range(10, 2) (min>max bug) - we reproduce
    the exact behaviour of that call instead of 'fixing' it."""
    return int(a + random.random() * (b - a))

def unity_random_range_float(a, b):
    return a + random.random() * (b - a)

def unity_sign(v):
    if v > 0: return 1.0
    if v < 0: return -1.0
    return 0.0

# ----------------------------------------------------------------------------
# Game constants (all values from the original binary)
# ----------------------------------------------------------------------------
DIFFICULTY_EASY_MULTIPLIER = 0.5
DIFFICULTY_HARD_MULTIPLIER = 1.2
DIFFICULTY_HARD_HEALTH_MULTIPLIER = 1.5

MONEY_FOR_KILL = 10
CROSSBOW_KILLS_BONUS = 5
FIREBALL_KILLS_BONUS = 5
DISTANT_KILLS_BONUS = 5
DISTANCE_BONUS = 20.0

ATTACKER_DISTANCE = 50.0
MIN_ANGLE = 2.0
MAX_ANGLE = 60.0
SWIPE_ANGLE_THRESHOLD = 35.0     # degrees
RAD2DEG = 57.295780181884766

# Projectile hit envelope (Projectile.OnTriggerEnter is Unity physics: the
# enemy collider has a real width, so its angular size = atan2(radius, dist).
# Enemies spawn at 50 units (AttackerSpawner constant) and walk in; the floor
# keeps distant shots hittable with keyboard turning.
ARROW_HIT_RADIUS = 3.0           # enemy body + player-contact trigger width
ARROW_HIT_FLOOR = 8.0            # degrees - centered-sound tolerance
FIREBALL_HIT_RADIUS = 4.0        # fireballs are wider
FIREBALL_HIT_FLOOR = 12.0        # degrees

NUMBER_OF_LEVELS = 24
FIREBALL_AVAILABLE_FROM_LEVEL = 13

MARKET_PRICES = {   # from MarketPlace.Awake()
    "arrows5":      (5, 15),
    "arrows10":     (10, 25),
    "arrows20":     (20, 25),
    "healPotion":   (1, 25),
    "fireball":     (1, 50),
    "swordUpgrade": (1, 250),
}

# Enemy prefabs (name, damage, attackSpeed, moveSpeed, startingHealth)
ENEMY_STATS = {
    "Goblin":          (10, 2.5, 2.0, 100),
    "Griffin":         (10, 2.5, 3.0, 200),
    "Werewolf":        (20, 2.0, 3.0, 200),
    "Harpy":           (15, 2.0, 2.0, 150),
    "MageApprentice":  (5,  2.0, 2.0, 100),
    "Spider":          (20, 2.5, 2.5, 100),
    "Treant":          (40, 1.5, 1.5, 300),
    "TreantStronger":  (40, 1.5, 1.5, 450),
    "Kelpie":          (20, 2.0, 2.5, 200),
    "Snowhund":        (20, 2.0, 3.0, 150),
    "Mammoth":         (35, 2.0, 1.5, 400),
    "Wight":           (20, 2.0, 2.0, 250),
    "Wraith":          (10, 2.0, 3.0, 100),
    "YoungDragon":     (30, 2.0, 2.0, 600),
    "Wizard":          (20, 4.0, 0.7, 800),
    "Dragon":          (50, 6.0, 1.2, 1500),
}

# 24 story levels - spawner/enemy sequences exactly as extracted from the scenes
# ("delay" tuple = original (minSpawnDelay, maxSpawnDelay) - including the min>max bug)
LEVELS = {
    1:  dict(delay=(0, 0),   max_at_once=1, to_spawn=6,  seq=False, enemies=["Goblin"],
             time=1.0, market=True,  intro="Level 1 Intro",  outro="Level 1 Outro",
             introduction=True),   # original useIntroduction: tutorial voice after 2 missed shots
    2:  dict(delay=(0, 0),   max_at_once=1, to_spawn=6,  seq=False, enemies=["GoblinFast"],
             time=1.0, market=False, intro="Level 2 Intro",  outro="Level 2 Outro"),
    3:  dict(delay=(0, 0),   max_at_once=1, to_spawn=7,  seq=True,
             enemies=["Goblin", "GoblinFast", "Goblin", "GoblinFast", "GoblinFast", "Goblin", "Goblin"],
             time=1.0, market=False, intro="Level 3 Intro",  outro="Level 3 Outro"),
    4:  dict(delay=(10, 2),  max_at_once=2, to_spawn=10, seq=True,
             enemies=["Goblin", "GoblinFast", "Goblin", "Goblin", "GoblinFast", "GoblinFast",
                      "GoblinFast", "Goblin", "GoblinFast", "Goblin"],
             time=1.0, market=False, intro="Level 4 Intro",  outro="Silence"),
    5:  dict(delay=(6, 10),  max_at_once=2, to_spawn=0,  seq=False, enemies=[],
             time=60.0, market=False, intro="Level 5 Intro",  outro="Level 5 Outro",
             boss="troll", troll=dict(damage=35, attack_duration=3.2, move_speed=1.0,
                                      next_min=5.0, next_max=10.0, lifetime=60.0, move_window=1.3)),
    6:  dict(delay=(10, 2),  max_at_once=2, to_spawn=10, seq=False, enemies=["Harpy"],
             time=1.0, market=False, intro="Level 6 Intro",  outro="Level 6 Outro"),
    7:  dict(delay=(5, 7),   max_at_once=2, to_spawn=14, seq=True,
             enemies=["Werewolf", "Harpy"] * 7,
             time=1.0, market=False, intro="Level 7 Intro",  outro="Level 7 Outro"),
    8:  dict(delay=(6, 10),  max_at_once=2, to_spawn=0,  seq=False, enemies=[],
             time=120.0, market=False, intro="Level 8 Intro", outro="Silence",
             boss="snakes", snakes=dict(damage=20, attack_duration=2.0, next_min=4.0,
                                        next_max=8.0, move_window=2.0)),
    9:  dict(delay=(1, 1),   max_at_once=1, to_spawn=6,  seq=False, enemies=["Spider"],
             time=1.0, market=False, intro="Level 9 Intro",  outro="Level 9 Outro"),
    10: dict(delay=(1, 1),   max_at_once=1, to_spawn=6,  seq=False, enemies=["MageApprentice"],
             time=1.0, market=False, intro="Level 10 Intro", outro="Level 10 Outro"),
    11: dict(delay=(4, 6),   max_at_once=2, to_spawn=10, seq=True,
             enemies=["MageApprentice", "Spider", "MageApprentice", "MageApprentice", "Spider",
                      "MageApprentice", "Spider", "Spider", "MageApprentice", "MageApprentice"],
             time=1.0, market=False, intro="Level 11 Intro", outro="Silence"),
    12: dict(delay=(1, 1),   max_at_once=1, to_spawn=1,  seq=False, enemies=["Wizard"],
             time=1.0, market=False, intro="Level 12 Intro", outro="Level 12 Outro",
             boss="wizard", allow_crouch=True, crouch_time=4.0, rot_clamp=80.0),
    13: dict(delay=(1, 1),   max_at_once=1, to_spawn=6,  seq=False, enemies=["Treant"],
             time=1.0, market=False, intro="Level 13 Intro", outro="Level 13 Outro"),
    14: dict(delay=(5, 5),   max_at_once=2, to_spawn=8,  seq=True,
             enemies=["Treant", "Goblin", "Goblin", "Goblin", "Treant", "Goblin", "Goblin",
                      "Treant", "Goblin", "Goblin"],
             time=1.0, market=False, intro="Level 14 Intro", outro="Level 14 Outro"),
    15: dict(delay=(5, 5),   max_at_once=2, to_spawn=8,  seq=True,
             enemies=["TreantStronger", "Goblin", "Goblin", "TreantStronger", "Goblin", "Goblin",
                      "Goblin", "TreantStronger"],
             time=1.0, market=False, intro="Level 15 Intro", outro="Level 15 Outro"),
    16: dict(delay=(1, 1),   max_at_once=1, to_spawn=10, seq=False, enemies=["Kelpie"],
             time=1.0, market=False, intro="Level 16 Intro", outro="Level 16 Outro"),
    17: dict(delay=(6, 10),  max_at_once=2, to_spawn=0,  seq=False, enemies=[],
             time=120.0, market=False, intro="Level 17 Intro", outro="Silence",
             boss="waves", waves=dict(damage=20, attack_duration=5.0, next_min=8.0,
                                      next_max=10.0, move_window=4.0)),
    18: dict(delay=(1, 1),   max_at_once=1, to_spawn=0,  seq=False, enemies=[],
             time=3600.0, market=False, intro="Level 18 Intro", outro="Level 18 Outro",
             boss="kraken", kraken=dict(pause=12.0, tentacles=6, tentacle_hp=10,
                                        tentacle_damage=20, attack_speed=2.0,
                                        waterball_speed=80.0, waterball_damage=20)),
    19: dict(delay=(1, 1),   max_at_once=1, to_spawn=8,  seq=True,
             enemies=["Snowhund", "Mammoth", "Snowhund", "Snowhund", "Mammoth", "Snowhund",
                      "Mammoth", "Mammoth"],
             time=1.0, market=False, intro="Level 19 Intro", outro="Level 19 Outro"),
    20: dict(delay=(5, 6),   max_at_once=2, to_spawn=12, seq=True,
             enemies=["Snowhund", "Snowhund", "Mammoth", "Snowhund", "Mammoth", "Snowhund",
                      "Snowhund", "Mammoth", "Snowhund", "Snowhund", "Snowhund", "Mammoth"],
             time=1.0, market=False, intro="Level 20 Intro", outro="Level 20 Outro"),
    21: dict(delay=(0, 0),   max_at_once=1, to_spawn=0,  seq=False, enemies=[],
             time=1.0, market=True,  intro="Level 21 Intro", outro="Silence",
             allow_crouch=True, crouch_time=4.0, rot_clamp=80.0),
    22: dict(delay=(4, 6),   max_at_once=2, to_spawn=16, seq=True,
             enemies=(["Wight", "Wraith"] * 8),
             time=1.0, market=False, intro="Level 22 Intro", outro="Level 22 Outro"),
    23: dict(delay=(0, 0),   max_at_once=1, to_spawn=1,  seq=False, enemies=["YoungDragon"],
             time=1.0, market=False, intro="Level 23 Intro", outro="Level 23 Outro"),
    24: dict(delay=(0, 0),   max_at_once=1, to_spawn=1,  seq=True,  enemies=["Dragon"],
             time=1.0, market=False, intro="Level 24 Intro", outro="Level 24 Outro",
             boss="dragon", allow_crouch=True, crouch_time=4.0,
             dragon=dict(heads=3, hp=1500, damage=50, attack_speed=6.0, move_speed=1.2,
                         fireball_speed=500.0, fireball_damage=30)),
}

ENDLESS = dict(delay=(5, 5), max_at_once=1, to_spawn=999999, seq=False, time=1.0,
               intro="Silence", outro="Silence", max_tier=5)

# projectile speeds/damages (from serialized prefabs)
PROJECTILE = dict(
    arrow=dict(speed=3000.0, damage=100),
    fireball=dict(speed=300.0, damage=500),
    waterball=dict(speed=80.0, damage=20),
    lightning=dict(speed=500.0, damage=30),
    dragon_fireball=dict(speed=500.0, damage=30),
    doveball=dict(speed=100.0, damage=0),
)
SWORD_DAMAGE = 100          # -> 50 normal hit, 100 with diamond sword (dmg/2 << upgraded)
SWORD_SWING_SPEED = 400.0
CROSSBOW_ATTACK_SPEED = 2.2
SWORD_ATTACK_SPEED = 0.8

# Language names supported by the original game
LANGUAGES = ["English"]   # English-only build: voices ship as the English banks

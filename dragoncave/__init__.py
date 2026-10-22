#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""To the Dragon Cave - Python/Pygame port package.

Modules:
    config  - game data (levels, enemies, prices) + paths + Unity random helpers
    speech  - speech backends (Orca D-Bus / accessible_output2 / pyttsx3)
    audio   - AudioEngine (stereo positional OGG playback) + sfx resolver
    keys    - keyboard bindings (CONTROLS) + is_action matching
    save    - GameSessionData (save.json) + LevelStats
    world   - Attacker / Projectile / GameWorld entities
    game    - the Game application (menus, combat, bosses, render)
    main    - pygame main loop entry point
"""

from .config import (BASE_DIR, AUDIO_DIR, GAME_SESSION_FILE, LEVELS, ENDLESS,
                     ENEMY_STATS, PROJECTILE, MARKET_PRICES, NUMBER_OF_LEVELS,
                     LANGUAGES, unity_random_range_int, unity_random_range_float,
                     unity_sign)
from .speech import SPEECH, _OrcaDBus
from .audio import AUDIO, sfx
from .keys import CONTROLS, ACTION_KEYS, ACTION_COMBOS, is_action, help_text
from .save import SESSION, LevelStats, GameSessionData
from .world import Attacker, Projectile, GameWorld
from .game import Game
from .main import main

__all__ = [
    "BASE_DIR", "AUDIO_DIR", "GAME_SESSION_FILE", "LEVELS", "ENDLESS",
    "ENEMY_STATS", "PROJECTILE", "MARKET_PRICES", "NUMBER_OF_LEVELS",
    "LANGUAGES", "unity_random_range_int", "unity_random_range_float",
    "unity_sign", "SPEECH", "_OrcaDBus", "AUDIO", "sfx", "CONTROLS",
    "ACTION_KEYS", "ACTION_COMBOS", "is_action", "help_text",
    "SESSION", "LevelStats", "GameSessionData", "Attacker", "Projectile",
    "GameWorld", "Game", "main",
]

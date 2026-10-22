#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
To the Dragon Cave - Python/Pygame port for Windows/Linux
=========================================================
Faithful port of the Android audio game "To the Dragon Cave" (Kikiriki Games, 2022)
to Python 3 + Pygame, including the game's original bugs and quirks.

Reverse-engineered from the original APK (IL2CPP dump + ARM disassembly).
All game data (levels, enemies, weapons, prices, timings) comes from the
original serialized game data.

PROJECT STRUCTURE (multi-file):
    dragon_cave.py            - this launcher (run the game with `py -3 dragon_cave.py`)
    dragoncave/__init__.py    - package: re-exports the public API
    dragoncave/config.py      - game data (24 levels, enemies, prices), paths
    dragoncave/speech.py      - speech backends (Orca D-Bus, accessible_output2, pyttsx3)
    dragoncave/audio.py       - AudioEngine: stereo positional OGG playback + UI sounds
    dragoncave/keys.py        - keyboard bindings (CONTROLS) and key matching
    dragoncave/save.py        - save.json player session + LevelStats
    dragoncave/world.py       - Attacker / Projectile / GameWorld entities
    dragoncave/game.py        - menus, combat, boss fights, marketplace, rendering
    dragoncave/main.py        - pygame main loop
    audio/                    - all 800+ game sounds from the original FMOD banks

Original controls were touch gestures; this port maps them to keyboard.
All bindings are fixed constants (dragoncave/keys.py, the CONTROLS table) -
every action documents which original gesture it replaces. Defaults
chosen by the user:

    Up arrow .................. attack with current weapon (swipe up)
    Down arrow ................ duck (swipe down; only some levels)
    Space ..................... draw crossbow (2-finger swipe left)
    Ctrl + Space .............. draw sword   (2-finger swipe right)
    P ......................... drink healing potion (2-finger swipe up)
    F ......................... throw fireball (shake phone)
    Left/Right arrows ......... turn (like dragging one finger)
    Tab ....................... read status (health, arrows, gold...)
    Enter ..................... confirm / select / skip dialogue
    Escape .................... pause menu / go back
    F1 ........................ read the key list aloud
    Page Up / Page Down ....... music volume up / down (works everywhere)

Audio:
    All 807 sounds ship from the ORIGINAL FMOD banks. Every voice line
    (level intros/outros, the 4 ending stories, the tutorial and the
    theme song) comes from the dedicated English voice banks
    (StoryMultiLang_English / Introduction_English) - English only,
    the Czech/German/Polish voice files are never used. Menus play the
    game's original UI sounds (focus / click / open / close / error /
    purchase) and the theme song plays in the menu.

Speech output:
    Windows : accessible_output2 (NVDA / JAWS / SAPI), then pyttsx3
    Linux   : Orca over D-Bus (org.gnome.Orca.Service, PresentMessage -
              same method the nvda2speechd Orca backend uses),
              then accessible_output2, then pyttsx3

Player save data is a plain JSON file next to the program: save.json.
"""

# Re-export the package API so `import dragon_cave` keeps working
# (tests and tools can use dragon_cave.Game, dragon_cave.AUDIO, ...).
from dragoncave import (  # noqa: F401
    BASE_DIR, AUDIO_DIR, GAME_SESSION_FILE, LEVELS, ENDLESS, ENEMY_STATS,
    PROJECTILE, MARKET_PRICES, NUMBER_OF_LEVELS, LANGUAGES,
    unity_random_range_int, unity_random_range_float, unity_sign,
    SPEECH, _OrcaDBus, AUDIO, sfx, CONTROLS, ACTION_KEYS, ACTION_COMBOS,
    is_action, help_text, SESSION, LevelStats, GameSessionData,
    Attacker, Projectile, GameWorld, Game, main,
)

if __name__ == "__main__":
    main()

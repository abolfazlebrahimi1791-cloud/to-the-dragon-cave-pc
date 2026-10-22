To the Dragon Cave - PC Port (Python + Pygame)
================================================
Unofficial PC port of the Android audio game "To the Dragon Cave"
(Kikiriki Games, 2022), reverse-engineered from the original APK
(IL2CPP dump + FMOD bank extraction + ARM disassembly).

English edition. All 24 story levels, 5 bosses, 4 endings, the endless
battle mode and the complete original English sound set are included:
807 sounds - every voice line comes from the game's dedicated English
FMOD voice banks (StoryMultiLang_English + Introduction_English),
including all level intro/outro narrations, the 4 ending stories and
the theme song with English vocals. Menu navigation, selection, open,
close, purchase and error cues use the game's original UI sounds.

Requirements
------------
- Python 3.8+  (https://python.org)
- pygame           ->  pip install pygame
- Speech (optional but recommended):
    Windows: accessible_output2  ->  pip install accessible_output2
             (NVDA / JAWS / SAPI are used automatically; pyttsx3 as
             fallback)
    Linux   : run Orca on your desktop. The game speaks through Orca's
              D-Bus service (org.gnome.Orca.Service, method
              PresentMessage) using DASBUS - the same D-Bus method used
              by the nvda2speechd Orca backend. Install it with
              "pip install dasbus" (python3-dbus is used as a fallback).
              If Orca is not available the game falls back to
              accessible_output2, then to pyttsx3.

Run
---
    python dragon_cave.py
(or run.bat on Windows, run.sh on Linux; alternatively
"python -m dragoncave" from the game folder)

Project structure (multi-file)
------------------------------
    dragon_cave.py            launcher - run the game with this file
    dragoncave/config.py      game data: 24 levels, enemies, prices, paths
    dragoncave/speech.py      speech backends (Orca D-Bus, accessible_output2,
                              pyttsx3)
    dragoncave/audio.py       AudioEngine - stereo positional OGG playback,
                              UI sounds, sfx resolver
    dragoncave/keys.py        keyboard bindings (CONTROLS) + key matching
    dragoncave/save.py        save.json player session + LevelStats
    dragoncave/world.py       Attacker / Projectile / GameWorld entities
    dragoncave/game.py        menus, combat, boss fights, marketplace, render
    dragoncave/main.py        pygame main loop
    audio/                    all 800+ original game sounds (OGG)

Keys - every key action is one original touch gesture
------------------------------------------------------
    Up arrow .......... attack with the current weapon   (swipe up)
    Down arrow ........ duck / crouch                    (swipe down;
                        only levels 12, 21 and 24)
    Space ............. draw the crossbow                (2-finger swipe left)
    Ctrl + Space ...... draw the sword                   (2-finger swipe right)
    P ................. drink a healing potion           (2-finger swipe up)
    F ................. throw a fireball                 (shake the phone)
    Left/Right arrows . turn                             (drag one finger)
    Tab ............... read status: health, ammo, gold  (double tap)
    Enter ............. confirm / select / skip dialogue (tap)
    Escape ............ pause menu, go back              (system back)
    F1 ................ read this key list aloud
    Page Up ........... music volume up   (works everywhere)
    Page Down ......... music volume down (works everywhere)

The pause menu offers Resume, Restart level and Main menu
(up/down arrows to choose, Enter to activate, Escape to resume).

The key bindings are fixed constants in the CONTROLS table inside
dragoncave/keys.py - every action there documents which original touch
gesture it replaces. No external configuration file is used.

Player data (JSON)
------------------
Progress (level, gold, health, potions, difficulty, endings, ...) is
saved as a plain JSON file next to the program:
    save.json
Delete it to start from scratch. A legacy "save/GameSession.gd" file
from older builds is migrated automatically on first start.

The game
--------
You are the blind prince, guided by your dove Dovelog. Escape the
dragon's cave, travel the land of Ladonia, fight goblins, spiders,
wolves, treants, mammoths and ghosts, defeat the 5 bosses (the Troll,
the snakes of the Crystal Palace, the Wizard, the Kraken and finally
the three-headed Dragon) and reach one of 4 endings - your choices
matter (kill the frog or save it?).

Gold: crossbow kills from more than 20 units distance earn a bonus.
After some levels the Marketplace opens: buy arrows, healing potions,
fireballs (available from level 13) or the diamond sword upgrade.

Accessibility notes
-------------------
The game is fully audible: enemies are positioned in real stereo, they
approach from up to 60 degrees to the left or right, and you have one
second after hearing an enemy attack to dodge or strike. All menus,
intro/outro dialogues and status information are spoken in English.
The theme song plays in the main menu and the final song in the credits;
adjust the music volume any time with Page Up / Page Down (announced
aloud, saved in save.json).

Credits
-------
Original game: Kikiriki Games (Czech Republic, 2022), made for blind
and low-vision gamers. Please support the original release. This
unofficial port was produced by reverse engineering for educational
and accessibility purposes.

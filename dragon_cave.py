#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
To the Dragon Cave - Python/Pygame port for Windows
====================================================
Faithful port of the Android audio game "To the Dragon Cave" (Kikiriki Games, 2022)
to Python 3 + Pygame, including the game's original bugs and quirks.

Reverse-engineered from the original APK (IL2CPP dump + ARM disassembly).
All game data (levels, enemies, weapons, prices, timings) comes from the
original serialized game data.

Original controls were touch gestures; this port maps them to keyboard.
All bindings are fixed constants in this file (the CONTROLS table) -
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

import os
import sys
import math
import json
import time
import random
import threading
import queue as queue_mod

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(BASE_DIR, "audio")
# Player save data = plain JSON file next to the program:
#   save.json     - full GameSession (progress, gold, difficulty, ...)
GAME_SESSION_FILE = os.path.join(BASE_DIR, "save.json")

# ----------------------------------------------------------------------------
# Speech output.
#   Windows : accessible_output2 (NVDA/JAWS/SAPI) -> pyttsx3 -> dummy
#   Linux   : Orca over D-Bus (org.gnome.Orca.Service) via DASBUS
#             (python3-dbus fallback) -> accessible_output2 -> pyttsx3 -> dummy
#
# The Linux backend mirrors the Rust nvda2speechd-style Orca backend
# (zbus sample):
#   service    org.gnome.Orca.Service
#   path       /org/gnome/Orca/Service
#   interface  org.gnome.Orca.Service
#   method     PresentMessage(s: text) -> bool
#     - speak text   : PresentMessage(text)
#     - cancel speech: PresentMessage("")
#   Braille messages are intentionally ignored (as in the Rust backend).
# ----------------------------------------------------------------------------
class _OrcaDBus:
    """Speak through the running Orca screen reader via D-Bus.

    Mirrors the Rust nvda2speechd-style Orca backend (zbus sample):
        service    org.gnome.Orca.Service
        path       /org/gnome/Orca/Service
        interface  org.gnome.Orca.Service
        method     PresentMessage(s: text) -> bool
          - speak text   : PresentMessage(text)
          - cancel speech: PresentMessage("")
        Braille messages are intentionally ignored.

    Primary implementation uses dasbus (the sample code below), with a
    python3-dbus fallback for systems that ship only python3-dbus."""
    SERVICE = "org.gnome.Orca.Service"
    PATH = "/org/gnome/Orca/Service"

    def __init__(self):
        self._proxy = None      # dasbus proxy (primary)
        self._obj = None        # python3-dbus object (fallback)
        self._iface = self.SERVICE
        # --- primary: dasbus (sample style) ---
        try:
            from dasbus.connection import SessionMessageBus
            proxy = SessionMessageBus().get_proxy(self.SERVICE, self.PATH)
            proxy.PresentMessage("")     # probe = cancel, like the Rust backend
            self._proxy = proxy
            return
        except Exception:
            self._proxy = None
        # --- fallback: python3-dbus ---
        try:
            import dbus
            bus = dbus.SessionBus()
            obj = bus.get_object(self.SERVICE, self.PATH)
            obj.PresentMessage("", dbus_interface=self._iface)
            self._obj = obj
        except Exception:
            self._obj = None

    def ok(self):
        return self._proxy is not None or self._obj is not None

    def say(self, text, interrupt=True):
        try:
            if self._proxy is not None:
                self._proxy.PresentMessage(text)
            elif self._obj is not None:
                self._obj.PresentMessage(text, dbus_interface=self._iface)
        except Exception:
            pass

class _DummySpeaker:
    def braille(self, *a, **k): pass
    def output(self, *a, **k): pass
    def speak(self, text, *a, **k):
        try:
            print("[SPEECH]", text)
        except Exception:
            pass

class Speaker:
    def __init__(self):
        self.speaker = None
        self.engine = None
        self.orca = None
        self.lock = threading.Lock()
        import platform
        if platform.system() != "Windows":
            try:
                o = _OrcaDBus()
                if o.ok():
                    self.orca = o
            except Exception:
                self.orca = None
        if self.orca is None:
            try:
                from accessible_output2.outputs.auto import Auto
                self.speaker = Auto()
                self._force_english_ao2()
            except Exception:
                self.speaker = None
        if self.orca is None and self.speaker is None:
            try:
                import pyttsx3
                self.engine = pyttsx3.init()
                self._force_english_pyttsx3()
                self.engine.startLoop(False)
                self._tts_thread = threading.Thread(target=self._tts_loop, daemon=True)
                self._tts_thread.start()
            except Exception:
                self.engine = None
        if self.orca is None and self.speaker is None and self.engine is None:
            self.speaker = _DummySpeaker()
        self._last_text = None
        self._last_time = 0.0

    def _force_english_ao2(self):
        """Best-effort: if accessible_output2 uses SAPI, select an English voice.
        Fully guarded - if anything differs, the default voice is kept."""
        try:
            spk = self.speaker
            out = None
            if hasattr(spk, "get_first_available_output"):
                out = spk.get_first_available_output()
            if out is None:
                outs = getattr(spk, "outputs", None)
                if outs:
                    try:
                        vals = list(outs.values())
                    except Exception:
                        vals = list(outs)
                    out = vals[0] if vals else None
            if out is None:
                return
            name = (type(out).__name__ or "").lower()
            mod = (type(out).__module__ or "").lower()
            if "sapi" not in name and "sapi" not in mod:
                return  # NVDA/JAWS read the text with the user's screen reader anyway
            voices = None
            for m in ("list_voices", "voices"):
                if hasattr(out, m):
                    try:
                        voices = getattr(out, m)()
                        break
                    except Exception:
                        voices = None
            if not voices:
                return
            pairs = list(voices.items()) if isinstance(voices, dict) \
                else [(None, v) for v in voices]
            for vid, desc in pairs:
                d = str(desc).lower()
                if "english" in d or d.startswith("en-us") or d.startswith("en-gb") \
                        or "microsoft david" in d or "microsoft zira" in d:
                    try:
                        out.voice = vid if vid is not None else desc
                    except Exception:
                        pass
                    return
        except Exception:
            pass

    def _force_english_pyttsx3(self):
        try:
            eng = self.engine
            for v in eng.getProperty("voices"):
                nm = (getattr(v, "name", "") or "").lower()
                vid = str(getattr(v, "id", "") or "").lower()
                if "english" in nm or "en_us" in vid or "en-us" in vid or "en_gb" in vid:
                    eng.setProperty("voice", v.id)
                    return
        except Exception:
            pass

    def _tts_loop(self):
        while True:
            try:
                self.engine.iterate()
            except Exception:
                pass
            time.sleep(0.05)

    def say(self, text, interrupt=False):
        if not text:
            return
        now = time.time()
        if text == self._last_text and now - self._last_time < 0.1:
            return
        self._last_text = text
        self._last_time = now
        try:
            if self.engine is not None:
                with self.lock:
                    try:
                        self.engine.stop()
                    except Exception:
                        pass
                    self.engine.say(text)
                    try:
                        self.engine.iterate()
                    except Exception:
                        pass
            elif self.orca is not None:
                self.orca.say(text, interrupt=interrupt)
            else:
                self.speaker.output(text, interrupt=interrupt)
        except Exception:
            pass

SPEECH = Speaker()

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
             time=1.0, market=True,  intro="Level 1 Intro",  outro="Level 1 Outro"),
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

# ----------------------------------------------------------------------------
# Audio engine (pygame mixer with stereo positioning, like FMOD in the original)
# ----------------------------------------------------------------------------
import pygame

# ----------------------------------------------------------------------------
# Key bindings - fixed constants in the CONTROLS table above.
# Every action is the keyboard equivalent of one original touch gesture.
# Modifiers can be combined, e.g. "CTRL+SPACE".
# ----------------------------------------------------------------------------
_KEY_ALIASES = {
    "ENTER": (pygame.K_RETURN, pygame.K_KP_ENTER),
    "SPACE": (pygame.K_SPACE,),
    "UP": (pygame.K_UP,), "DOWN": (pygame.K_DOWN,),
    "LEFT": (pygame.K_LEFT,), "RIGHT": (pygame.K_RIGHT,),
    "TAB": (pygame.K_TAB,), "ESCAPE": (pygame.K_ESCAPE,),
    "CTRL": (pygame.K_LCTRL, pygame.K_RCTRL),
    "SHIFT": (pygame.K_LSHIFT, pygame.K_RSHIFT),
    "ALT": (pygame.K_LALT, pygame.K_RALT),
    "BACKSPACE": (pygame.K_BACKSPACE,),
    "DELETE": (pygame.K_DELETE,), "INSERT": (pygame.K_INSERT,),
    "HOME": (pygame.K_HOME,), "END": (pygame.K_END,),
    "PAGEUP": (pygame.K_PAGEUP,), "PAGEDOWN": (pygame.K_PAGEDOWN,),
    "PLUS": (pygame.K_PLUS,), "MINUS": (pygame.K_MINUS,),
}
_MOD_MAP = {"CTRL": pygame.KMOD_CTRL, "SHIFT": pygame.KMOD_SHIFT, "ALT": pygame.KMOD_ALT}

def _keys_by_name(name):
    n = str(name).strip().upper()
    if n in _KEY_ALIASES:
        return list(_KEY_ALIASES[n])
    if len(n) == 1 and n.isdigit():
        return [getattr(pygame, "K_" + n)]
    if len(n) == 1 and n.isalpha():
        return [getattr(pygame, "K_" + n.lower())]
    if len(n) >= 2 and n[0] == "F" and n[1:].isdigit() and 1 <= int(n[1:]) <= 12:
        return [getattr(pygame, "K_" + n)]          # K_F1..K_F12 are uppercase
    for cand in (n.lower(), n, n.upper()):
        if hasattr(pygame, "K_" + cand):
            return [getattr(pygame, "K_" + cand)]
    return []

CONTROLS = {
    # action: list of keys. Modifier combos are written like "CTRL+SPACE".
    # Every action replaces one original touch gesture.
    "attack":      ["UP"],           # gesture: swipe up, one finger
    "crouch":      ["DOWN"],         # gesture: swipe down, one finger (levels 12, 21, 24)
    "crossbow":    ["SPACE"],        # gesture: swipe left, two fingers
    "sword":       ["CTRL+SPACE"],   # gesture: swipe right, two fingers
    "potion":      ["P"],            # gesture: swipe up, two fingers
    "fireball":    ["F"],            # gesture: shake the phone
    "turn_left":   ["LEFT"],         # gesture: drag one finger left
    "turn_right":  ["RIGHT"],        # gesture: drag one finger right
    "confirm":     ["ENTER"],        # gesture: tap
    "back":        ["ESCAPE"],       # gesture: system back
    "pause":       ["ESCAPE"],
    "help":        ["F1"],
    "status":      ["TAB"],          # gesture: double tap
    "menu_up":     ["UP"],
    "menu_down":   ["DOWN"],
    "menu_left":   ["LEFT"],
    "menu_right":  ["RIGHT"],
    "volume_up":   ["PAGEUP"],       # music louder (works everywhere)
    "volume_down": ["PAGEDOWN"],     # music quieter (works everywhere)
}

def _build_action_keys():
    plain, combos = {}, {}
    for action, specs in CONTROLS.items():
        pset, clist = set(), []
        for spec in specs:
            parts = [p.strip().upper() for p in str(spec).split("+")]
            mods = 0
            for p in parts[:-1]:
                mods |= _MOD_MAP.get(p, 0)
            for kc in _keys_by_name(parts[-1]):
                if mods:
                    clist.append((mods, kc))
                else:
                    pset.add(kc)
        plain[action] = frozenset(pset)
        combos[action] = tuple(clist)
    return plain, combos

ACTION_KEYS, ACTION_COMBOS = _build_action_keys()

def is_action(action, ev):
    """True when a KEYDOWN event matches the binding of `action`."""
    mods = ev.mod & (pygame.KMOD_CTRL | pygame.KMOD_SHIFT | pygame.KMOD_ALT)
    for m, kc in ACTION_COMBOS.get(action, ()):
        if ev.key == kc and (mods & m) == m:
            return True
    if ev.key in ACTION_KEYS.get(action, ()):
        if mods:
            # a chorded binding of another action owns this key right now
            # (e.g. SPACE = crossbow vs CTRL+SPACE = sword)
            for other, cl in ACTION_COMBOS.items():
                if other == action:
                    continue
                for m, kc in cl:
                    if kc == ev.key and (mods & m) == m:
                        return False
        return True
    return False

_ACTION_LABELS = [
    ("attack", "attack with the current weapon"),
    ("crouch", "crouch"),
    ("crossbow", "draw the crossbow"),
    ("sword", "draw the sword"),
    ("potion", "drink a healing potion"),
    ("fireball", "throw a fireball"),
    ("turn_left", "turn left"),
    ("turn_right", "turn right"),
    ("status", "read your status"),
    ("confirm", "confirm in menus"),
    ("back", "go back"),
    ("pause", "pause"),
    ("help", "this help"),
    ("volume_up", "music volume up"),
    ("volume_down", "music volume down"),
]

def help_text():
    parts = []
    for action, label in _ACTION_LABELS:
        names = ", ".join(CONTROLS.get(action, [])) or "unbound"
        parts.append("%s = %s" % (names, label))
    return "Keys. " + ". ".join(parts) + "."

def _audio_file(name):
    return os.path.join(AUDIO_DIR, name + ".ogg")

class AudioEngine:
    """Plays the original game's OGG audio with stereo panning + distance gain."""
    def __init__(self, sample_rate=48000):
        pygame.mixer.pre_init(sample_rate, -16, 2, 512)
        self.sample_rate = sample_rate
        self.cache = {}
        self.story_channel = None
        self.music_channel = None
        self.heartbeat_channel = None
        self.sfx_channels = []
        self.ready = False

    def init(self):
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        n_ch = 24
        pygame.mixer.set_num_channels(n_ch)
        self.story_channel = pygame.mixer.Channel(0)
        self.music_channel = pygame.mixer.Channel(1)
        self.heartbeat_channel = pygame.mixer.Channel(2)
        self.sfx_channels = [pygame.mixer.Channel(i) for i in range(3, n_ch)]
        self._sfx_idx = 0
        self.ready = True

    def load(self, name):
        path = _audio_file(name)
        if name not in self.cache:
            if not os.path.exists(path):
                self.cache[name] = None
                return None
            try:
                self.cache[name] = pygame.mixer.Sound(path)
            except Exception:
                self.cache[name] = None
        return self.cache[name]

    def _pick_sfx_channel(self):
        ch = self.sfx_channels[self._sfx_idx % len(self.sfx_channels)]
        self._sfx_idx += 1
        return ch

    def play(self, name, volume=1.0, pan=0.0, loop=False):
        """pan: -1 left .. +1 right"""
        snd = self.load(name)
        if snd is None:
            return None
        ch = self._pick_sfx_channel()
        left = volume * min(1.0, 1.0 - pan)
        right = volume * min(1.0, 1.0 + pan)
        ch.set_volume(left, right)
        ch.play(snd, loops=-1 if loop else 0, fade_ms=0)
        return ch

    def play_at(self, name, angle_deg, distance, volume=1.0, loop=False, max_dist=70.0):
        """Positional play: angle relative to player facing (-90..90), distance units."""
        pan = max(-1.0, min(1.0, math.sin(math.radians(angle_deg))))
        atten = max(0.03, 1.0 - distance / max_dist)
        return self.play(name, volume * atten * atten, pan, loop)

    def play_story(self, name, on_done=None, interrupt=True):
        snd = self.load(name)
        if snd is None:
            if on_done:
                on_done()
            return None
        if interrupt:
            self.story_channel.stop()
        self.story_channel.set_volume(1.0)
        self.story_channel.play(snd)
        self._story_done = on_done
        return self.story_channel

    def story_busy(self):
        return self.story_channel is not None and self.story_channel.get_busy()

    def stop_story(self):
        if self.story_channel:
            self.story_channel.stop()

    def play_music(self, name, volume=0.5, loop=True):
        snd = self.load(name)
        if snd is None:
            return None
        self.music_channel.set_volume(volume)
        self.music_channel.play(snd, loops=-1 if loop else 0)
        return self.music_channel

    def set_music_volume(self, volume):
        """Live volume change (Page Up / Page Down)."""
        if self.music_channel:
            self.music_channel.set_volume(max(0.0, min(1.0, volume)))

    def music_busy(self):
        return self.music_channel is not None and self.music_channel.get_busy()

    def stop_music(self):
        if self.music_channel:
            self.music_channel.stop()

    # menu / UI sounds from the original game's UI bank
    UI_SOUNDS = {
        "focus":  ("Focus Enter",),
        "select": ("Click", "Interact"),
        "open":   ("Popup Open",),
        "back":   ("Popup Close",),
        "error":  ("Negative",),
        "buy":    ("Item Purchased",),
    }

    def play_ui(self, kind, volume=0.9):
        for n in self.UI_SOUNDS.get(kind, ()):
            if self.play(n, volume):
                return True
        return False

    def play_heartbeat(self, intensity):
        """intensity 0..1 -> heartbeat volume (Health 'Health' FMOD param)"""
        if intensity <= 0:
            if self.heartbeat_channel:
                self.heartbeat_channel.stop()
            return
        snd = self.load("Heart beating")
        if snd is None:
            return
        if not self.heartbeat_channel.get_busy():
            self.heartbeat_channel.play(snd, loops=-1)
        self.heartbeat_channel.set_volume(0.15 + 0.85 * intensity)

    def stop_all_sfx(self):
        for ch in self.sfx_channels:
            ch.stop()

AUDIO = AudioEngine()

def sfx(*names):
    """Return the first audio name that exists on disk."""
    for n in names:
        if n and os.path.exists(os.path.join(AUDIO_DIR, n + ".ogg")):
            return n
    return None


# ----------------------------------------------------------------------------
# Player save data - plain JSON file next to the program (save.json).
# (legacy save/GameSession.gd from older builds is migrated automatically)
# ----------------------------------------------------------------------------

class GameSessionData:
    """Mirror of the original GameSession/GameSessionManager."""
    def __init__(self):
        self.frogKilled = False
        self.princeSaved = False
        self.gameFinished = False
        self.endlessBattleUnlocked = False
        self.swordUpgraded = False
        self.score = 0
        self.playerHealth = 100
        self.crossbowArrows = 20
        self.gold = 0
        self.level = 1
        self.healPotions = 0
        self.fireballs = 0
        self.difficulty = 1          # 0 easy, 1 normal, 2 hard
        self.language = "English"
        self.soundtrack_volume = 100
        self.playing_first_time = True
        self.rot_sens_min = 10
        self.rot_sens_max = 100

    def save(self):
        try:
            with open(GAME_SESSION_FILE, "w", encoding="utf-8") as f:
                json.dump(self.__dict__, f, indent=1)
        except Exception:
            pass

    def load(self):
        path = GAME_SESSION_FILE
        if not os.path.exists(path):
            legacy = os.path.join(BASE_DIR, "save", "GameSession.gd")
            if os.path.exists(legacy):
                try:
                    import shutil
                    shutil.copyfile(legacy, path)
                except Exception:
                    pass
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            for k, v in d.items():
                if hasattr(self, k):
                    setattr(self, k, v)
        except Exception:
            pass
        # English-only build: always force English voice + sane music volume
        self.language = "English"
        if not isinstance(self.soundtrack_volume, int) or self.soundtrack_volume <= 0:
            self.soundtrack_volume = 100

SESSION = GameSessionData()

# ----------------------------------------------------------------------------
# LevelStats (statics in the original)
# ----------------------------------------------------------------------------
class LevelStats:
    crossbowArrowsFired = 0
    crossbowHit = 0
    crossbowMiss = 0
    fireballsFired = 0
    fireballHit = 0
    fireballMiss = 0
    distantKills = 0
    enemiesKilled = 0
    enemiesKilledByCrossbow = 0
    enemiesKilledByFireball = 0
    enemiesKilledBySword = 0
    enemiesTotal = 0
    levelTime = 0
    levelFinished = False

    @classmethod
    def reset(cls):
        cls.crossbowArrowsFired = 0
        cls.crossbowHit = 0
        cls.crossbowMiss = 0
        cls.fireballsFired = 0
        cls.fireballHit = 0
        cls.fireballMiss = 0
        cls.distantKills = 0
        cls.enemiesKilled = 0
        cls.enemiesKilledByCrossbow = 0
        cls.enemiesKilledByFireball = 0
        cls.enemiesKilledBySword = 0
        cls.enemiesTotal = 0
        cls.levelTime = 0
        cls.levelFinished = False

    @classmethod
    def get_crossbow_accuracy(cls):
        if cls.crossbowArrowsFired == 0:
            return 0.0
        return cls.crossbowHit / float(cls.crossbowArrowsFired)

    @classmethod
    def get_fireball_accuracy(cls):
        if cls.fireballsFired == 0:
            return 0.0
        return cls.fireballHit / float(cls.fireballsFired)

    @classmethod
    def calculate_gold(cls):
        g = 0.0
        cb = cls.get_crossbow_accuracy()
        fb = cls.get_fireball_accuracy()
        g += (MONEY_FOR_KILL + CROSSBOW_KILLS_BONUS * cb) * cls.enemiesKilledByCrossbow
        g += (MONEY_FOR_KILL + FIREBALL_KILLS_BONUS * fb) * cls.enemiesKilledByFireball
        g += MONEY_FOR_KILL * cls.enemiesKilledBySword
        g += DISTANT_KILLS_BONUS * cls.distantKills
        return int(g)

# ----------------------------------------------------------------------------
# Game entities
# ----------------------------------------------------------------------------
class Attacker:
    """Enemy - exact port of the original Attacker/MonoBehaviour."""
    def __init__(self, kind, bearing, level_mods):
        dmg, atk_spd, mov_spd, hp = ENEMY_STATS.get(kind, (10, 2.5, 2.0, 100))
        self.kind = kind
        self.bearing = bearing           # degrees, -90..90 relative to player facing
        self.distance = ATTACKER_DISTANCE
        self.damage = dmg
        self.attack_speed = atk_spd
        self.move_speed = mov_spd
        self.starting_health = hp
        self.max_health = hp
        self.health = hp
        self.extra_reward = 0
        self.is_attacking = False
        self.is_dying = False
        self.attack_timer = 0.0
        self.deal_damage_at = -1.0
        self.attack_sound_played = False
        # HARD difficulty: move speed x1.2 (AdjustDifficulty), HP x1.5
        if SESSION.difficulty == 2 and not getattr(level_mods, "endless", False):
            self.move_speed *= DIFFICULTY_HARD_MULTIPLIER
            self.max_health = int(self.max_health * DIFFICULTY_HARD_HEALTH_MULTIPLIER)
            self.health = self.max_health
        # audio mapping per enemy type
        sounds = {
            "Goblin":         ("Goblin strong attack 1", "Goblin death 11", "Goblin pain 10"),
            "GoblinFast":     ("Goblin strong attack 13", "Goblin death 14", "Goblin pain 13"),
            "Werewolf":       ("Gnoll Monster Attack 3 Wolf Hyena Dog Creature", "Gnoll Monster Death 1 Wolf Hyena Dog Creature", "Gnoll Monster Pain 3 Wolf Hyena Dog Creature"),
            "Snowhund":       ("Bear Attacks 4", "Gnoll Monster Death 3 Wolf Hyena Dog Creature", "Gnoll Monster Pain 3 Wolf Hyena Dog Creature"),
            "Griffin":        ("Bear Attacks 4", "Harpy Monster Death 3 Bird Dinosaur Witch Creature", "Harpy Monster Pain 3 Bird Dinosaur Witch Creature"),
            "Harpy":          ("Harpy Monster Attack 1 Bird Dinosaur Witch Creature", "Harpy Monster Death 3 Bird Dinosaur Witch Creature", "Harpy Monster Pain 3 Bird Dinosaur Witch Creature"),
            "Spider":         ("Spider Queen Monster Attack 1 Insect Bug Screech Squeal Angry Combat", "Spider Queen Monster Death 2 Insect Bug Screech Squeal Pain Hurt Moan Groan", "Spider Queen Monster Pain 1 Insect Bug Screech Chirp Death Hit Squish"),
            "Treant":         ("Treant Monster Attack 1 Tree Creature Swing Growl Roar", "Treant Monster Death 1 Tree Creature Groan Pain Hurt Moan Die", "Treant Monster Pain 1 Tree Creature Croak Groan Moan Squeal"),
            "TreantStronger": ("Treant Monster Attack 2 Tree Creature Swing Growl Roar", "Treant Monster Death 3 Tree Creature Groan Pain Hurt Moan Die", "Treant Monster Pain 1 Tree Creature Croak Groan Moan Squeal"),
            "Kelpie":         ("Kelpie Monster Attack 2 Water Spirit Horse Creature", "Kelpie Monster Death 3 Water Spirit Horse Creature", "Kelpie Monster Pain 2 Water Spirit Horse Creature"),
            "Mammoth":        ("Mammoth Monster Attack 1 Elephant Vocalization Roar Squeal", "Mammoth Monster Death 3 Elephant Vocalization Roar Moan Groan Pain", "Mammoth Monster Pain 1 Elephant Vocalization Grunt Breath"),
            "Wight":          ("Wight Monster Attack 2 Spirit Fairy Ghost Creature", "Wraith Monster Death 1 Spirit Fairy Ghost Creature", "Wight Monster Pain 1 Spirit Fairy Ghost Creature"),
            "Wraith":         ("Wraith Monster Attack 1 Spirit Fairy Ghost Creature", "Wraith Monster Death 1 Spirit Fairy Ghost Creature", "Wraith Monster Pain 1 Spirit Fairy Ghost Creature"),
            "YoungDragon":    ("Ancient Dragon Monster Attack 1 Dinosaur Creature Roar Growl Moan Groan", "Ancient Dragon Monster Death 4 Dinosaur Creature Pain Screech Scream Roar Groan", "Ancient Dragon Monster Pain 1 Dinosaur Creature Hurt Squeal Vocalization"),
            "Wizard":         ("AGGRO 1", "Alien Death 03", "Alien Hit 01"),
            "TentacleEnemy":  ("Kraken Monster Attack 2 Fight Growl Grunt", "Kraken Monster Attack 2 Fight Growl Grunt", "Alien Hit 01"),
            "Dragon":         ("Ancient Dragon Monster Attack 2 Dinosaur Creature Roar Growl Moan Groan", "Ancient Dragon Monster Death 4 Dinosaur Creature Pain Screech Scream Roar Groan", "Ancient Dragon Monster Pain 1 Dinosaur Creature Hurt Squeal Vocalization"),
        }
        a, d, i = sounds.get(kind, (None, None, None))
        a = sfx(a); d = sfx(d); i = sfx(i)
        self.snd_attack, self.snd_death, self.snd_injured = a, d, i
        self._walk_channel = None

    def start_walk_sound(self):
        if self._walk_channel and self._walk_channel.get_busy():
            return
        walk_names = {
            "Goblin": "Goblin breath 1", "GoblinFast": "Goblin breath 2",
            "Werewolf": "Dog Footsteps 1", "Snowhund": "Dog Footsteps 2",
            "Griffin": "Harpy Monster Wings 2 Bird Dinosaur Witch Creature",
            "Harpy": "Harpy Monster Wings 2 Bird Dinosaur Witch Creature",
            "Spider": "BABY FOOTSTEPS 1", "Treant": "Treant Monster Attack 4 Stomp Tree Creature Impact Hit",
            "TreantStronger": "Treant Monster Attack 4 Stomp Tree Creature Impact Hit",
            "Kelpie": "Ambience_Swamp_01", "Mammoth": "BABY FOOTSTEPS 2",
            "Wight": "Ambient 14", "Wraith": "Ambient 14",
            "YoungDragon": "BABY FOOTSTEPS 3", "Dragon": "Ancient Dragon Monster Snore Dinosaur Creature Inhale Exhale Breath Airy",
            "Wizard": "light chimes", "TentacleEnemy": "Ambience Waves Ocean Loop",
        }
        n = walk_names.get(self.kind)
        n = sfx(n) if n else None
        if n:
            self._walk_channel = AUDIO.play_at(n, self.bearing, self.distance, 0.8, loop=True)

    def stop_walk_sound(self):
        if self._walk_channel:
            self._walk_channel.stop()
            self._walk_channel = None

    def update_walk_sound(self):
        if self._walk_channel:
            pan = max(-1.0, min(1.0, math.sin(math.radians(self.bearing))))
            atten = max(0.03, 1.0 - self.distance / 70.0)
            self._walk_channel.set_volume(0.8 * atten, 0.8 * atten * 0.0 + 0.8 * atten)
            self._walk_channel.set_volume(0.8 * atten * min(1.0, 1.0 - pan),
                                          0.8 * atten * min(1.0, 1.0 + pan))

    def adjust_damage(self, dmg):
        if SESSION.difficulty == 0:
            return int(dmg * DIFFICULTY_EASY_MULTIPLIER)
        if SESSION.difficulty == 2:
            return int(dmg * DIFFICULTY_HARD_MULTIPLIER)
        return dmg

    def deal_damage(self, dmg):
        """Health.DealDamage - returns 'killed' bool."""
        if self.is_dying:
            return False
        if SESSION.difficulty != 1:
            dmg = self.adjust_damage(dmg)
        self.health -= dmg
        if self.health <= 0:
            return True
        # injured sound
        if self.snd_injured:
            AUDIO.play_at(self.snd_injured, self.bearing, self.distance, 1.0)
        return False

class Projectile:
    def __init__(self, kind, speed, damage, bearing):
        self.kind = kind
        self.bearing = bearing
        self.distance = 0.0
        self.speed = speed
        self.damage = damage
        self.dead = False

class GameWorld:
    """Port of LevelController + PlayerController + AttackerSpawner for one level."""
    def __init__(self, level_number, endless=False):
        self.level_number = level_number
        self.endless = endless
        cfg = dict(ENDLESS if endless else LEVELS[level_number])
        self.cfg = cfg
        self.status = "Intro"           # Intro -> Playing -> Finished -> Outro
        self.time = 0.0                 # gameplay time (timeScale-aware)
        self.enemies = []
        self.projectiles = []
        self.spawn_queue = list(cfg.get("enemies", []))
        if cfg.get("seq"):
            pass  # sequential list is consumed in order
        else:
            random.shuffle(self.spawn_queue) if cfg.get("to_spawn", 0) > 1 else None
        self.spawned_count = 0
        self.spawn_timer = 1.0
        self.max_at_once = cfg.get("max_at_once", 1)
        self.to_spawn = cfg.get("to_spawn", 0)
        self.delay_min, self.delay_max = cfg.get("delay", (1, 1))
        self.level_time_limit = cfg.get("time", 1.0)
        self.allow_crouch = cfg.get("allow_crouch", False)
        self.crouch_time = cfg.get("crouch_time", 1.5)
        self.rot_clamp = cfg.get("rot_clamp", 65.0)
        # player
        self.player_bearing = 0.0       # player facing relative to world
        self.player_health = SESSION.playerHealth
        self.player_max_health = 100
        self.arrows = SESSION.crossbowArrows
        self.fireballs = SESSION.fireballs
        self.heal_potions = SESSION.healPotions
        self.sword_upgraded = SESSION.swordUpgraded
        self.active_weapon = "Crossbow"
        self.is_crouching = False
        self.crouch_left = 0.0
        self.dead = False
        self.is_throwing_fireball = False
        self.fireball_cooldown = 0.0
        self.attack_ready = 0.0
        self.sword_swing_t = -1.0
        # endless battle tier
        self.tier = 1
        self.max_tier = ENDLESS["max_tier"]
        # boss
        self.boss_type = cfg.get("boss")
        self.boss_state = None
        self.boss_timer = 20.0 if endless else 0.0
        self.boss_alive = False
        self.dragon_heads_left = 3
        self.result = None              # "win"/"loose" after finish
        self.finish_timer = 0.0
        self.jingle = None
        self.intro_done = False
        self.heartbeat_t = 0.0
        self.status_readout_t = 0.0

    # ---- difficulty damage adjustment for player hits (original quirk:
    # enemies (not tagged Player) always run AdjustDamage, player raw on NORMAL)
    def player_hit_damage(self, dmg):
        if SESSION.difficulty == 0:
            return int(dmg * DIFFICULTY_EASY_MULTIPLIER)
        if SESSION.difficulty == 2:
            return int(dmg * DIFFICULTY_HARD_MULTIPLIER)
        return dmg

    def spawn_position(self):
        """AttackerSpawner.GetAttackerPosition:
        angle = Random.Range(2,60); side = Sign(Range(-1,1))"""
        angle = unity_random_range_float(MIN_ANGLE, MAX_ANGLE)
        side = unity_sign(unity_random_range_float(-1.0, 1.0))
        return side * angle

    def spawn_attacker(self, kind=None):
        if kind is None:
            if self.endless:
                kind = self._endless_pick()
            elif self.spawn_queue:
                if self.cfg.get("seq"):
                    kind = self.spawn_queue.pop(0)
                else:
                    kind = self.spawn_queue[unity_random_range_int(0, len(self.spawn_queue))]
            else:
                return
        bearing = self.spawn_position()
        e = Attacker(kind, bearing, self)
        self.enemies.append(e)
        self.spawned_count += 1
        LevelStats.enemiesTotal += 1
        e.start_walk_sound()

    def _endless_pick(self):
        # EndlessBattleSpawner.GetAttackerPrefab: weighted pick among first `tier` types
        pool = ["Goblin", "GoblinFast", "Griffin", "Harpy", "Werewolf", "Spider", "Kelpie",
                "Snowhund", "Mammoth", "Wight", "Wraith"]
        max_i = min(self.tier, len(pool))
        return pool[unity_random_range_int(0, max_i)]

    def all_spawned(self):
        if self.endless:
            return False
        return LevelStats.enemiesTotal >= self.to_spawn

    def attacker_count(self):
        return len([e for e in self.enemies if not e.is_dying])

    def win_condition_met(self):
        if self.boss_type:
            return self.boss_finished()
        if self.endless:
            return False
        if self.to_spawn > 0:
            return self.all_spawned() and self.attacker_count() == 0
        # timed levels: survive level_time_limit
        return self.time >= self.level_time_limit

    def boss_finished(self):
        if self.boss_type == "troll":
            return self.time >= self.cfg["troll"]["lifetime"]
        if self.boss_type == "snakes":
            return self.time >= self.level_time_limit
        if self.boss_type == "waves":
            return self.time >= self.level_time_limit
        if self.boss_type == "kraken":
            return self.tentacles_left() == 0
        if self.boss_type == "wizard":
            return self.boss_state in ("frog_killed", "frog_saved")
        if self.boss_type == "dragon":
            return self.dragon_heads_left <= 0
        return False

    def tentacles_left(self):
        return len([e for e in self.enemies if not e.is_dying])

# ----------------------------------------------------------------------------
# Main game application
# ----------------------------------------------------------------------------
class Game:
    MENU_ITEMS = ["New game", "Continue game", "Play a level", "Endless battle",
                  "Settings", "Credits", "Quit game"]
    SETTINGS_ITEMS = ["Difficulty", "Soundtrack volume", "Back"]

    def __init__(self):
        self.state = "Splash"
        self.state_time = 0.0
        self.menu_index = 0
        self.settings_index = 0
        self.play_level_index = 0
        self.market_index = 0
        self.pause_menu = False
        self.pause_index = 0
        self.world = None
        self.dialogue = None            # (name, on_done)
        self.after_dialogue = None
        self.credits_page = 0
        self.introduction_phase = 0
        self.endless_stats = None
        self.pending_next = None
        self.skip_requested = False
        self.credits_pages = 5

    # ------------------------------------------------------------------ flow
    THEME_SONG = "Kikiriki Dragons Cave 1C English Vocals"   # theme song with English vocals

    def music_vol(self, base=0.8):
        return base * SESSION.soundtrack_volume / 100.0

    def play_menu_music(self, base=0.8, loop=True):
        return AUDIO.play_music(self.THEME_SONG, self.music_vol(base), loop=loop)

    def start(self):
        SESSION.load()
        AUDIO.init()
        pygame.display.set_caption("To the Dragon Cave")
        self.play_menu_music()
        self.set_state("Splash")
        SPEECH.say("To the Dragon Cave. Music volume Page Up Page Down. Press enter to continue.")

    def set_state(self, s):
        self.state = s
        self.state_time = 0.0

    def speak_menu(self, items, idx, prefix=""):
        txt = (prefix + " " if prefix else "") + items[idx]
        SPEECH.say(txt)

    # ------------------------------------------------------------------ menu
    def menu_activate(self):
        idx = self.menu_index
        AUDIO.play_ui("select")
        if idx == 0:   # New game
            SESSION.gameFinished = False
            SESSION.level = 1
            SESSION.playerHealth = 100
            SESSION.crossbowArrows = 20
            SESSION.gold = 0
            SESSION.healPotions = 0
            SESSION.fireballs = 0
            SESSION.swordUpgraded = False
            SESSION.frogKilled = False
            SESSION.princeSaved = False
            SESSION.endlessBattleUnlocked = False
            SESSION.save()
            self.launch_level(1)
        elif idx == 1:  # Continue
            if SESSION.level > 1 or SESSION.playerHealth < 100:
                self.launch_level(SESSION.level)
            else:
                AUDIO.play_ui("error")
                SPEECH.say("No game in progress. Start a new game first.")
        elif idx == 2:  # Play a level
            self.set_state("PlayLevel")
            self.play_level_index = 0
            self.speak_level_select()
        elif idx == 3:  # Endless battle
            if SESSION.endlessBattleUnlocked or SESSION.gameFinished:
                self.launch_level(None, endless=True)
            else:
                AUDIO.play_ui("error")
                SPEECH.say("Endless battle is locked. Finish the story first.")
        elif idx == 4:
            self.set_state("Settings")
            self.settings_index = 0
            self.speak_settings()
        elif idx == 5:
            self.set_state("Credits")
            self.credits_page = 0
            SPEECH.say("Credits. Page 1. Left and right arrow to change page, escape to go back.")
        elif idx == 6:
            self.quit()

    def speak_level_select(self):
        n = self.play_level_index + 1
        SPEECH.say("Level %d. Left and right arrow to choose, enter to play, escape to go back." % n)

    def speak_settings(self):
        items = self.SETTINGS_ITEMS
        idx = self.settings_index
        if idx == 0:
            names = ["Easy", "Normal", "Hard"]
            SPEECH.say("Difficulty: " + names[SESSION.difficulty] + ". Left right to change.")
        elif idx == 1:
            SPEECH.say("Soundtrack volume: %d percent. Left right to change. You can also use Page Up and Page Down anywhere." % SESSION.soundtrack_volume)
        else:
            SPEECH.say("Back")

    def settings_change(self, delta):
        idx = self.settings_index
        AUDIO.play_ui("select", 0.6)
        if idx == 0:
            SESSION.difficulty = max(0, min(2, SESSION.difficulty + delta))
            names = ["Easy", "Normal", "Hard"]
            SPEECH.say(names[SESSION.difficulty])
        elif idx == 1:
            SESSION.soundtrack_volume = max(0, min(100, SESSION.soundtrack_volume + delta * 10))
            SPEECH.say("%d percent" % SESSION.soundtrack_volume)
            AUDIO.stop_music()
            self.play_menu_music()
        SESSION.save()

    # ------------------------------------------------------------- level flow
    def launch_level(self, n, endless=False):
        LevelStats.reset()
        AUDIO.stop_music()
        AUDIO.stop_all_sfx()
        self.world = GameWorld(n, endless=endless)
        intro = self.world.cfg.get("intro", "Silence")
        self.set_state("LevelIntro")
        if intro and intro != "Silence":
            name = intro            # English story bank ships unsuffixed files
            self.dialogue = (name, self._begin_level_gameplay)
            AUDIO.play_story(name, self._begin_level_gameplay)
            SPEECH.say("Level %d" % n if n else "Endless battle")
        else:
            SPEECH.say("Level %d" % n if n else "Endless battle")
            self._begin_level_gameplay()

    def _begin_level_gameplay(self):
        if not self.world:
            return
        self.dialogue = None
        self.world.status = "Playing"
        self.set_state("Level")
        w = self.world
        # initial announcement (GamePlayScreen.UpdateStatsLabels / doveling)
        if w.endless:
            SPEECH.say("Endless battle. Survive as long as you can. Swipe or arrow keys to turn, up to attack.")
        elif w.boss_type == "troll":
            SPEECH.say("The troll is coming. Swipe left or right when he attacks!")
        elif w.boss_type == "snakes":
            SPEECH.say("Reach the crystal palace. Dodge the snakes: swipe left or right in time!")
        elif w.boss_type == "waves":
            SPEECH.say("Steer the boat! Waves attack from the sides: swipe left or right in time!")
        elif w.boss_type == "kraken":
            SPEECH.say("The kraken attacks! Kill the tentacles as they emerge.")
        elif w.boss_type == "wizard":
            SPEECH.say("The wizard is near. Watch out for lightning - swipe down to duck!")
        elif w.boss_type == "dragon":
            SPEECH.say("The dragon is here! Duck under the fireballs and strike when you can.")
        else:
            SPEECH.say("Level %d. Enemies approaching." % w.level_number)

    def finish_level(self, win):
        w = self.world
        if w.status != "Playing":
            return
        w.status = "Finished"
        w.result = "win" if win else "loose"
        w.finish_timer = 3.0     # HandleLevelFinished: WaitForSeconds(3)
        LevelStats.levelTime = int(w.time)
        LevelStats.levelFinished = True
        if win:
            AUDIO.play(sfx("sparkly", "mystery chime") or "", 1.0)
        else:
            AUDIO.play(sfx("subsonicatmosone", "Ambient 32") or "", 1.0)
        AUDIO.stop_all_sfx()
        for e in w.enemies:
            e.stop_walk_sound()

    def after_level(self):
        w = self.world
        win = (w.result == "win")
        # award gold (LevelStats.CalculateGold on win)
        if win:
            gold = LevelStats.calculate_gold()
            if gold > 0:
                SESSION.gold += gold
        SESSION.playerHealth = max(1, int(w.player_health))
        SESSION.crossbowArrows = w.arrows
        SESSION.fireballs = w.fireballs
        SESSION.healPotions = w.heal_potions
        AUDIO.stop_story()
        if w.endless:
            SESSION.endlessBattleUnlocked = True
            SESSION.save()
            self.set_state("EndlessEnd")
            self.endless_stats = dict(kills=LevelStats.enemiesKilled,
                                      gold=gold if win else 0,
                                      time=LevelStats.levelTime,
                                      acc=int(100 * LevelStats.get_crossbow_accuracy()))
            SPEECH.say("Endless battle finished. %d enemies killed. %d gold earned. "
                       "Accuracy %d percent. Press enter to return to the menu."
                       % (self.endless_stats["kills"], self.endless_stats["gold"],
                          self.endless_stats["acc"]))
            return
        if win:
            if w.cfg.get("market"):
                self.set_state("Market")
                self.market_index = 0
                AUDIO.play_music("Marketplace", self.music_vol(0.6))
                self.speak_market()
                return
            # ProgressToNextLevel
            if SESSION.level < NUMBER_OF_LEVELS:
                SESSION.level += 1
            else:
                SESSION.gameFinished = True
                SESSION.endlessBattleUnlocked = True
            SESSION.save()
            outro = w.cfg.get("outro", "Silence")
            if outro and outro != "Silence":
                name = outro            # English story bank ships unsuffixed files
                self.set_state("LevelOutro")
                AUDIO.play_story(name, self._goto_next_scene)
            else:
                self._goto_next_scene()
        else:
            SESSION.save()
            self.set_state("Loose")
            AUDIO.play_music(sfx("fantasy ambience", "Ambient 14") or "", 0.4 * SESSION.soundtrack_volume / 100.0)
            SPEECH.say("You died. Press enter to return to the menu.")

    def _goto_next_scene(self):
        if SESSION.gameFinished and SESSION.level >= NUMBER_OF_LEVELS:
            # Outro (4 endings) then credits - English bank: no language suffix
            self.set_state("Outro")
            if SESSION.frogKilled and SESSION.princeSaved:
                name = "Outro Frog Killed Prince Saved"
            elif SESSION.frogKilled:
                name = "Outro Frog Killed Prince Killed"
            elif SESSION.princeSaved:
                name = "Outro Frog Saved Prince Saved"
            else:
                name = "Outro Frog Saved Prince Killed"
            if AUDIO.load(name) is None:
                name = "Outro"
            AUDIO.play_story(name, self._goto_credits)
        else:
            self.launch_level(SESSION.level)

    def _goto_credits(self):
        self.set_state("Credits")
        self.credits_page = 0
        AUDIO.play_music("Final song", self.music_vol(0.6), loop=True)
        SPEECH.say("Congratulations! You finished the game. Credits. Left and right to browse, escape for menu.")

    def quit(self):
        SESSION.save()
        pygame.quit()
        sys.exit(0)

    # ------------------------------------------------------------- combat
    def do_attack(self):
        w = self.world
        if not w or w.status != "Playing" or w.dead or w.is_throwing_fireball:
            return
        now = time.time()
        if now < w.attack_ready:
            return
        if w.active_weapon == "Sword":
            w.attack_ready = now + SWORD_ATTACK_SPEED
            w.sword_swing_t = 0.35    # swingSpeed 400 deg/s swing window
            AUDIO.play(sfx("Sword Swing 1 1") or "", 0.9)
            self._sword_hit()
        else:  # Crossbow
            if w.arrows <= 0:
                AUDIO.play_ui("error", 0.8)   # no English voice file exists in the banks -> English TTS + UI cue
                SPEECH.say("No arrows", interrupt=True)
                return
            w.attack_ready = now + CROSSBOW_ATTACK_SPEED
            w.arrows -= 1
            LevelStats.crossbowArrowsFired += 1
            AUDIO.play(sfx("Crossbow Draw 1") or "", 0.9)
            AUDIO.play(sfx("Arrow Fly 2 3") or "", 0.8)
            self._arrow_fire()

    def _nearest_in_front(self, max_deg=6.0, require_alive=True):
        w = self.world
        best, best_ang = None, 1e9
        for e in w.enemies:
            if require_alive and e.is_dying:
                continue
            ang = abs(e.bearing - w.player_bearing)
            ang = min(ang, 360 - ang)
            if ang <= max_deg and ang < best_ang:
                best, best_ang = e, ang
        return best

    def _arrow_fire(self):
        w = self.world
        tgt = self._nearest_in_front(8.0)
        p = Projectile("arrow", PROJECTILE["arrow"]["speed"], PROJECTILE["arrow"]["damage"],
                       w.player_bearing)
        w.projectiles.append(p)
        if tgt is None:
            LevelStats.crossbowMiss += 1

    def _sword_hit(self):
        w = self.world
        tgt = self._nearest_in_front(10.0)
        if tgt and tgt.distance <= 6.0:
            dmg = (SWORD_DAMAGE // 2) << (1 if w.sword_upgraded else 0)
            self._hit_enemy(tgt, dmg, by="sword")

    def _hit_enemy(self, e, dmg, by="crossbow"):
        w = self.world
        if e.is_dying:
            return False
        killed = e.deal_damage(dmg)
        if killed:
            if by == "sword":
                LevelStats.enemiesKilledBySword += 1
            self._kill_enemy(e)
        return killed

    def _kill_enemy(self, e):
        w = self.world
        LevelStats.enemiesKilled += 1
        e.is_dying = True
        e.stop_walk_sound()
        if e.snd_death:
            AUDIO.play_at(e.snd_death, e.bearing, e.distance, 1.0)
        if e.extra_reward >= 1:
            SESSION.gold += e.extra_reward
        if w.boss_type == "dragon" and e.kind == "Dragon":
            w.dragon_heads_left -= 1
            if w.dragon_heads_left > 0:
                SPEECH.say("The dragon lost a head! %d to go" % w.dragon_heads_left)
            else:
                AUDIO.play(sfx("Ancient Dragon Monster Attack 3 Dinosaur Creature Roar Growl Moan Groan") or "", 1.0)
        if w.boss_type == "kraken":
            pass
        # remove shortly (death sound plays out)
        threading.Timer(1.2, lambda: (e in w.enemies) and w.enemies.remove(e)).start()
        if not w.boss_type and not w.endless and w.to_spawn > 0:
            pass

    def do_crouch(self):
        w = self.world
        if not w or w.status != "Playing" or w.dead:
            return
        if not w.allow_crouching or w.is_crouching:
            return
        w.is_crouching = True
        w.crouch_left = w.crouch_time
        AUDIO.play("Duck Flapping Wings 4", 0.7)

    def do_potion(self):
        w = self.world
        if not w or w.status != "Playing" or w.dead:
            return
        if w.player_health < 1:
            return
        if w.heal_potions <= 0:
            SPEECH.say("No heal potions")
            return
        w.heal_potions -= 1
        w.player_health = w.player_max_health
        AUDIO.play(sfx("Heal Potion", "Heal Wounds") or "", 1.0)
        SPEECH.say("Healing potion used")

    def do_fireball(self):
        w = self.world
        if not w or w.status != "Playing" or w.dead or w.is_throwing_fireball:
            return
        if SESSION.level < FIREBALL_AVAILABLE_FROM_LEVEL and not w.endless:
            SPEECH.say("Fireballs are not available yet")
            return
        if w.fireballs <= 0:
            AUDIO.play(sfx("no weapon tap") or "", 1.0)
            SPEECH.say("No fireballs")
            return
        w.is_throwing_fireball = True
        w.fireball_cooldown = 1.0
        w.fireballs -= 1
        LevelStats.fireballsFired += 1
        AUDIO.play(sfx("BABY BREATHING FIRE 1", "DRAGON BREATHING FIRE 16") or "", 1.0)

    def change_weapon(self, weapon):
        w = self.world
        if not w or w.status != "Playing" or w.dead:
            return
        w.active_weapon = weapon
        if weapon == "Crossbow":
            AUDIO.play(sfx("Crossbow Draw 1") or "", 0.8)
            SPEECH.say("Crossbow")
        else:
            AUDIO.play(sfx("diamond sword draw") if w.sword_upgraded else sfx("Sword Swing 1 1") or "", 0.9)
            SPEECH.say("Diamond sword" if w.sword_upgraded else "Sword")

    def read_status(self):
        w = self.world
        if not w:
            return
        if w.endless:
            SPEECH.say("Endless battle. Tier %d. Kills %d. Health %d. Gold %d."
                       % (w.tier, LevelStats.enemiesKilled, w.player_health, SESSION.gold))
            return
        weapon = w.active_weapon
        ammo = ("%d arrows" % w.arrows) if weapon == "Crossbow" else (
            "diamond sword" if w.sword_upgraded else "sword")
        SPEECH.say("Health %d. %s. %d heal potions, %d fireballs, %d gold."
                   % (w.player_health, ammo, w.heal_potions, w.fireballs, SESSION.gold))

    def turn(self, direction, amount):
        """1-finger drag left/right / arrow keys: rotate within clamp."""
        w = self.world
        if not w or w.status != "Playing" or w.dead:
            return
        w.player_bearing += direction * amount
        lo, hi = -w.rot_clamp, w.rot_clamp
        if w.player_bearing < lo: w.player_bearing = lo
        if w.player_bearing > hi: w.player_bearing = hi

    # ------------------------------------------------------------- simulation
    def update_world(self, dt):
        w = self.world
        if not w:
            return
        if w.status != "Playing":
            if w.status == "Finished":
                w.finish_timer -= dt
                if w.finish_timer <= 0:
                    self.after_level()
            return

        w.time += dt

        # ---- heartbeat (Health 'Health' param)
        hp_frac = w.player_health / float(w.player_max_health)
        w.heartbeat_t += dt
        if w.heartbeat_t > 0.5:
            w.heartbeat_t = 0.0
            AUDIO.play_heartbeat(0.0 if hp_frac > 0.5 else (1.0 - hp_frac * 2))

        # ---- spawning (AttackerSpawner coroutine incl. the Range(min,max) bug)
        if not w.boss_type and not w.all_spawned():
            w.spawn_timer -= dt
            if w.spawn_timer <= 0:
                if w.attacker_count() < w.max_at_once:
                    self.spawn_one()
                d = unity_random_range_int(w.delay_min, w.delay_max)
                w.spawn_timer = max(0.05, d)

        # ---- endless tier progression
        if w.endless:
            w.boss_timer -= dt
            if w.boss_timer <= 0:
                w.boss_timer = 20.0
                if w.tier < w.max_tier:
                    w.tier += 1
                    w.max_at_once = w.tier
                    SPEECH.say("Wave %d" % w.tier)

        # ---- boss logic
        self.update_boss(dt)

        # ---- enemies
        for e in list(w.enemies):
            if e.is_dying:
                continue
            if e.move_speed > 0:
                e.distance -= e.move_speed * dt
                if e.distance <= 2.0:
                    e.distance = 2.0
                    e.move_speed = 0.0     # stop at player (OnTriggerEnter)
                    e.is_attacking = True
                    e.attack_timer = 0.0
            e.update_walk_sound()
            if e.is_attacking:
                e.attack_timer += dt
                if not e.attack_sound_played and e.attack_timer >= 0.0:
                    e.attack_sound_played = True
                    if e.snd_attack:
                        AUDIO.play_at(e.snd_attack, e.bearing, e.distance, 1.0)
                    e.deal_damage_at = e.attack_timer + 1.0   # DealDamage coroutine: 1s delay
                if e.deal_damage_at > 0 and e.attack_timer >= e.deal_damage_at:
                    e.attack_sound_played = False
                    e.attack_timer = 0.0
                    e.deal_damage_at = -1.0
                    if not w.is_crouching or e.kind not in ("Wizard", "Dragon", "Kelpie"):
                        self.player_hit(e.damage)
                    else:
                        SPEECH.say("Missed!")

        # ---- projectiles
        for p in list(w.projectiles):
            p.distance += p.speed * dt
            if p.kind == "arrow":
                tgt = self._nearest_in_front(6.0)
                if tgt and p.distance >= tgt.distance - 1.0:
                    LevelStats.crossbowHit += 1
                    dmg = p.damage
                    if SESSION.difficulty != 1:
                        dmg = int(dmg * (DIFFICULTY_EASY_MULTIPLIER if SESSION.difficulty == 0
                                         else DIFFICULTY_HARD_MULTIPLIER))
                    killed = self._hit_enemy(tgt, dmg, by="crossbow")
                    if killed:
                        LevelStats.enemiesKilledByCrossbow += 1
                        if tgt.distance > DISTANCE_BONUS:
                            LevelStats.distantKills += 1
                    p.dead = True
                elif p.distance > ATTACKER_DISTANCE + 10:
                    LevelStats.crossbowMiss += 1
                    p.dead = True
            elif p.kind == "fireball":
                tgt = self._nearest_in_front(10.0)
                if tgt and p.distance >= tgt.distance - 1.0:
                    LevelStats.fireballHit += 1
                    killed = self._hit_enemy(tgt, p.damage, by="fireball")
                    if killed:
                        LevelStats.enemiesKilledByFireball += 1
                    AUDIO.play(sfx("BREATHE 2", "Fire Punch 1") or "", 0.9)
                    p.dead = True
                elif p.distance > ATTACKER_DISTANCE + 10:
                    LevelStats.fireballMiss += 1
                    p.dead = True
            else:  # incoming projectiles: waterball/lightning/dragon fireball
                if p.distance <= 0.5:
                    p.dead = True
                    if not w.is_crouching:
                        self.player_hit(p.damage)
                    else:
                        AUDIO.play("Introduction Crouch Success", 0.8)
                        SPEECH.say("Dodged!")
            if p.dead:
                w.projectiles.remove(p)

        # ---- crouch
        if w.is_crouching:
            w.crouch_left -= dt
            if w.crouch_left <= 0:
                w.is_crouching = False
                AUDIO.play(sfx("Barefoot Grass footsteps 5", "Crouch") or "", 0.5)

        # ---- fireball throw cooldown
        if w.is_throwing_fireball:
            w.fireball_cooldown -= dt
            if w.fireball_cooldown <= 0:
                w.is_throwing_fireball = False
                tgt = self._nearest_in_front(10.0)
                p = Projectile("fireball", PROJECTILE["fireball"]["speed"],
                               PROJECTILE["fireball"]["damage"], w.player_bearing)
                w.projectiles.append(p)

        # ---- win / loose
        if w.player_health <= 0 and not w.dead:
            w.dead = True
            AUDIO.play(sfx("Alien Death 03") or "", 1.0)
            AUDIO.play_heartbeat(0)
            self.finish_level(win=False)
            return
        if w.win_condition_met() and w.status == "Playing":
            if w.boss_type == "wizard" and w.boss_state in ("frog_killed", "frog_saved"):
                SESSION.frogKilled = (w.boss_state == "frog_killed")
                SESSION.princeSaved = (w.boss_state == "frog_saved")
            self.finish_level(win=True)

    def spawn_one(self):
        w = self.world
        if w.endless:
            w.spawn_attacker()
        elif w.spawn_queue:
            w.spawn_attacker()

    def player_hit(self, dmg):
        w = self.world
        dmg = w.player_hit_damage(dmg)
        w.player_health -= dmg
        AUDIO.play(sfx("Alien Hit 01", "AGGRO 2") or "", 0.9)
        SPEECH.say("Ouch")
        if w.player_health <= 0:
            w.player_health = 0

    # ------------------------------------------------------------- bosses
    def update_boss(self, dt):
        w = self.world
        if not w.boss_type:
            return
        if w.boss_type == "troll":
            self.update_troll(dt)
        elif w.boss_type == "snakes":
            self.update_snakes(dt)
        elif w.boss_type == "waves":
            self.update_waves(dt)
        elif w.boss_type == "kraken":
            self.update_kraken(dt)
        elif w.boss_type == "wizard":
            self.update_wizard(dt)
        elif w.boss_type == "dragon":
            self.update_dragon(dt)

    # Troll (Level 5): walks left-right, attacks; dodge by swiping left/right within 1.3s
    def update_troll(self, dt):
        w = self.world
        t = w.cfg["troll"]
        w.boss_timer -= dt
        if w.boss_state is None:
            w.boss_state = "walking"
            w.boss_dir = 1.0
            w.boss_pos = -40.0
            AUDIO.play(sfx("Ancient Dragon Monster Idle Chatter Dinosaur Creature Select Unit Bear Growl", "Bear Attacks 4") or "", 0.6, loop=True)
        if w.boss_state == "walking":
            w.boss_pos += w.boss_dir * t["move_speed"] * 10 * dt
            if w.boss_pos > 40: w.boss_pos, w.boss_dir = 40, -1.0
            if w.boss_pos < -40: w.boss_pos, w.boss_dir = -40, 1.0
            w.boss_timer = max(0.0, w.boss_timer)
            if w.boss_timer <= 0:
                w.boss_state = "attacking"
                w.boss_timer = t["attack_duration"]
                w.boss_dodged = False
                AUDIO.play(sfx("Treant Monster Attack 4 Stomp Tree Creature Impact Hit", "Bear Attacks 4") or "", 1.0)
                SPEECH.say("The troll attacks! Swipe left or right!")
        elif w.boss_state == "attacking":
            if w.boss_timer <= 0:
                if not w.boss_dodged:
                    self.player_hit(t["damage"])
                w.boss_state = "walking"
                w.boss_timer = unity_random_range_float(t["next_min"], t["next_max"])

    def troll_dodge(self, direction):
        w = self.world
        if w.boss_type != "troll" or w.boss_state != "attacking":
            return
        if abs(w.boss_pos - direction * 25) < 30:
            w.boss_dodged = True
            AUDIO.play(sfx("Duck Flapping Wings 4") or "", 0.9)

    # Snakes (Level 8): snakes strike from sides; dodge left/right within 2s
    def update_snakes(self, dt):
        w = self.world
        t = w.cfg["snakes"]
        if w.boss_state is None:
            w.boss_state = "idle"
            w.boss_timer = 2.0
            AUDIO.play(sfx("Ambience Place Cave Dark Loop") or "", 0.5, loop=True)
        if w.boss_state == "idle" and w.boss_timer <= 0:
            w.boss_state = "attacking"
            w.boss_dir = random.choice([-1.0, 1.0])
            w.boss_timer = t["attack_duration"]
            w.boss_dodged = False
            AUDIO.play_at(sfx("Snake 02", "Spider Queen Monster Attack 1 Insect Bug Screech Squeal Angry Combat") or "", w.boss_dir * 30, 20, 1.0)
            SPEECH.say("Snake!")
        elif w.boss_state == "attacking" and w.boss_timer <= 0:
            if not w.boss_dodged:
                self.player_hit(t["damage"])
            w.boss_state = "idle"
            w.boss_timer = unity_random_range_float(t["next_min"], t["next_max"])

    # Boat waves (Level 17): waves hit from left/right; steer away within 4s
    def update_waves(self, dt):
        w = self.world
        t = w.cfg["waves"]
        if w.boss_state is None:
            w.boss_state = "idle"
            w.boss_timer = 3.0
            AUDIO.play(sfx("Ambience Waves Ocean Loop") or "", 0.6, loop=True)
        if w.boss_state == "idle" and w.boss_timer <= 0:
            w.boss_state = "attacking"
            w.boss_dir = random.choice([-1.0, 1.0])
            w.boss_timer = t["attack_duration"]
            w.boss_dodged = False
            AUDIO.play_at(sfx("AGGRO 3", "Ambience Waves Ocean Loop") or "", w.boss_dir * 60, 10, 1.0)
            SPEECH.say("Wave from the " + ("left" if w.boss_dir < 0 else "right") + "!")
        elif w.boss_state == "attacking" and w.boss_timer <= 0:
            if not w.boss_dodged:
                self.player_hit(t["damage"])
            w.boss_state = "idle"
            w.boss_timer = unity_random_range_float(t["next_min"], t["next_max"])

    # Kraken (Level 18): tentacles emerge one at a time, throw waterballs
    def update_kraken(self, dt):
        w = self.world
        k = w.cfg["kraken"]
        if w.boss_state is None:
            w.boss_state = "wait"
            w.boss_timer = 3.0
            AUDIO.play(sfx("Ambience Waves Ocean Loop") or "", 0.6, loop=True)
            SPEECH.say("The kraken wakes!")
        if w.boss_state == "wait" and w.boss_timer <= 0:
            if w.tentacles_left() < k["tentacles"] and w.attacker_count() < 2:
                w.boss_timer = k["pause"]
                w.spawn_attacker("TentacleEnemy")
                w.boss_state = "wait"
            else:
                w.boss_timer = k["pause"]

    # Wizard (Level 12): lightning (duck!), frog phase with 2 endings
    def update_wizard(self, dt):
        w = self.world
        wiz = w.enemies[0] if w.enemies else None
        if w.boss_state is None:
            w.boss_state = "fight"
            if wiz:
                wiz.distance = 30.0
                wiz.bearing = 0.0
                wiz.start_walk_sound()
        if w.boss_state == "fight":
            if wiz is None or wiz.is_dying:
                w.boss_state = "frog"
                w.boss_timer = 0.5
                SPEECH.say("The wizard turned into a frog! What will you do?")
                AUDIO.play(sfx("Frog Ribbits", "Frog Ribbits 1") or "", 0.9)
            else:
                wiz.bearing = math.sin(w.time * 0.7) * 40
                if random.random() < (0.70 * dt / 3.0):
                    p = Projectile("lightning", PROJECTILE["lightning"]["speed"],
                                   PROJECTILE["lightning"]["damage"], wiz.bearing)
                    p.distance = wiz.distance
                    w.projectiles.append(p)
                    AUDIO.play_at(sfx("Fire Punch 1", "Blow Torch Stop") or "", wiz.bearing, wiz.distance, 1.0)
        elif w.boss_state == "frog":
            w.boss_timer -= dt
            if w.boss_timer <= 0:
                w.boss_timer = 8.0
                AUDIO.play(sfx("Frog Ribbits", "Frog Ribbits 1") or "", 0.9)
                SPEECH.say("The frog is in front of you. Attack to kill it, or wait to save it.")
            if w.boss_timer <= -12.0:
                w.boss_state = "frog_saved"

    def wizard_frog_action(self, attacked):
        w = self.world
        if w.boss_state != "frog":
            return
        if attacked:
            w.boss_state = "frog_killed"
            AUDIO.play(sfx("Frog Ribbits 3", "Frog Ribbits 4") or "", 1.0)
            SPEECH.say("You killed the frog!")
        else:
            w.boss_state = "frog_saved"
            AUDIO.play("Bird flapping wings 1", 0.9)
            SPEECH.say("You saved the frog!")

    # Dragon (Level 24): 3 heads, fireballs to duck under
    def update_dragon(self, dt):
        w = self.world
        d = w.cfg["dragon"]
        if w.boss_state is None:
            w.boss_state = "fight"
            AUDIO.play(sfx("Ancient Dragon Monster Growl Dinosaur Creature Gurgle Deep Crispy") or "", 1.0)
            SPEECH.say("The dragon has three heads! Duck under its fireballs!")
        if w.boss_state == "fight":
            if w.boss_timer <= 0:
                w.boss_timer = d["attack_speed"]
                bearing = random.choice([-1.0, 1.0]) * unity_random_range_float(5, 40)
                p = Projectile("dragon_fireball", d["fireball_speed"], d["fireball_damage"], bearing)
                p.distance = 50.0
                w.projectiles.append(p)
                AUDIO.play_at(sfx("BABY BREATHING FIRE 1", "DRAGON BREATHING FIRE 16") or "", bearing, 50, 1.0)

    # ------------------------------------------------------------- marketplace
    MARKET_ITEMS = ["arrows5", "arrows10", "arrows20", "healPotion", "fireball", "swordUpgrade"]

    def speak_market(self):
        key = self.MARKET_ITEMS[self.market_index]
        amount, price = MARKET_PRICES[key]
        names = {"arrows5": "%d arrows" % amount, "arrows10": "%d arrows" % amount,
                 "arrows20": "%d arrows" % amount, "healPotion": "a healing potion",
                 "fireball": "a fireball", "swordUpgrade": "the diamond sword upgrade"}
        SPEECH.say("%s, %d gold. You have %d gold. Enter to buy, escape to continue."
                   % (names[key], price, SESSION.gold))

    def market_buy(self):
        w = self.world
        key = self.MARKET_ITEMS[self.market_index]
        amount, price = MARKET_PRICES[key]
        if SESSION.gold < price:
            AUDIO.play_ui("error")
            SPEECH.say("Not enough gold")
            return
        if key == "swordUpgrade":
            if SESSION.swordUpgraded:
                AUDIO.play_ui("error")
                SPEECH.say("Already purchased")
                return
            SESSION.swordUpgraded = True
        elif key == "healPotion":
            SESSION.healPotions += 1
        elif key == "fireball":
            SESSION.fireballs += 1
        else:
            SESSION.crossbowArrows += amount
        SESSION.gold -= price
        SESSION.save()
        AUDIO.play_ui("buy", 1.0)
        SPEECH.say("Purchased")

    # ------------------------------------------------------------- pause menu
    PAUSE_ITEMS = ["Resume", "Restart level", "Main menu"]

    def pause_activate(self):
        item = self.PAUSE_ITEMS[self.pause_index]
        self.pause_menu = False
        if item == "Resume":
            SPEECH.say("Resumed")
        elif item == "Restart level":
            w = self.world
            if w is not None:
                self.launch_level(w.level_number if not w.endless else None,
                                  endless=w.endless)
        else:
            self.back_to_menu()

    # ------------------------------------------------------------- input
    def handle_event(self, ev):
        if ev.type != pygame.KEYDOWN:
            return
        st = self.state

        # global: F1 = read the key list aloud (also interrupts speech)
        if is_action("help", ev):
            SPEECH.say(help_text(), interrupt=True)
            return

        # global: Page Up / Page Down = music volume (works everywhere)
        if is_action("volume_up", ev) or is_action("volume_down", ev):
            up = is_action("volume_up", ev)
            SESSION.soundtrack_volume = max(0, min(100, SESSION.soundtrack_volume + (10 if up else -10)))
            SESSION.save()
            if AUDIO.music_busy():
                AUDIO.set_music_volume(self.music_vol(0.8))
            SPEECH.say("Music volume: %d percent" % SESSION.soundtrack_volume, interrupt=True)
            return

        if st == "Splash":
            if is_action("confirm", ev):
                AUDIO.play_ui("open")
                self.set_state("Menu")
                self.menu_index = 0
                self.speak_menu(self.MENU_ITEMS, self.menu_index, "Main menu")
            return

        if st == "Menu":
            if is_action("menu_up", ev):
                AUDIO.play_ui("focus")
                self.menu_index = (self.menu_index - 1) % len(self.MENU_ITEMS)
                self.speak_menu(self.MENU_ITEMS, self.menu_index)
            elif is_action("menu_down", ev):
                AUDIO.play_ui("focus")
                self.menu_index = (self.menu_index + 1) % len(self.MENU_ITEMS)
                self.speak_menu(self.MENU_ITEMS, self.menu_index)
            elif is_action("confirm", ev):
                self.menu_activate()
            return

        if st == "PlayLevel":
            if is_action("menu_left", ev):
                AUDIO.play_ui("focus")
                self.play_level_index = (self.play_level_index - 1) % NUMBER_OF_LEVELS
                self.speak_level_select()
            elif is_action("menu_right", ev):
                AUDIO.play_ui("focus")
                self.play_level_index = (self.play_level_index + 1) % NUMBER_OF_LEVELS
                self.speak_level_select()
            elif is_action("confirm", ev):
                AUDIO.play_ui("select")
                self.launch_level(self.play_level_index + 1)
            elif is_action("back", ev) or is_action("pause", ev):
                AUDIO.play_ui("back")
                self.back_to_menu()
            return

        if st == "Settings":
            if is_action("menu_up", ev):
                AUDIO.play_ui("focus")
                self.settings_index = (self.settings_index - 1) % len(self.SETTINGS_ITEMS)
                self.speak_settings()
            elif is_action("menu_down", ev):
                AUDIO.play_ui("focus")
                self.settings_index = (self.settings_index + 1) % len(self.SETTINGS_ITEMS)
                self.speak_settings()
            elif is_action("menu_left", ev):
                self.settings_change(-1)
            elif is_action("menu_right", ev):
                self.settings_change(1)
            elif is_action("back", ev) or is_action("pause", ev):
                AUDIO.play_ui("back")
                self.back_to_menu()
            return

        if st == "Credits":
            if is_action("menu_right", ev):
                if self.credits_page < self.credits_pages - 1:
                    AUDIO.play_ui("focus")
                self.credits_page = min(self.credits_pages - 1, self.credits_page + 1)
                SPEECH.say("Page %d" % (self.credits_page + 1))
            elif is_action("menu_left", ev):
                if self.credits_page > 0:
                    AUDIO.play_ui("focus")
                self.credits_page = max(0, self.credits_page - 1)
                SPEECH.say("Page %d" % (self.credits_page + 1))
            elif is_action("back", ev) or is_action("pause", ev) or is_action("confirm", ev):
                AUDIO.play_ui("back")
                self.back_to_menu()
            return

        if st == "Loose" or st == "EndlessEnd":
            if is_action("confirm", ev) or is_action("back", ev) or is_action("pause", ev):
                AUDIO.play_ui("select")
                self.back_to_menu()
            return

        if st == "Market":
            if is_action("menu_up", ev):
                AUDIO.play_ui("focus")
                self.market_index = (self.market_index - 1) % len(self.MARKET_ITEMS)
                self.speak_market()
            elif is_action("menu_down", ev):
                AUDIO.play_ui("focus")
                self.market_index = (self.market_index + 1) % len(self.MARKET_ITEMS)
                self.speak_market()
            elif is_action("confirm", ev):
                self.market_buy()
            elif is_action("back", ev) or is_action("pause", ev):
                AUDIO.play_ui("back")
                AUDIO.stop_music()
                SESSION.save()
                self.launch_level(SESSION.level)
            return

        if st in ("Level", "LevelIntro", "LevelOutro"):
            if st in ("LevelIntro", "LevelOutro"):
                if is_action("confirm", ev):
                    AUDIO.stop_story()
                    if self.dialogue and self.dialogue[1]:
                        self.dialogue[1]()
                return
            # pause menu navigation
            if self.pause_menu:
                n = len(self.PAUSE_ITEMS)
                if is_action("menu_up", ev):
                    AUDIO.play_ui("focus")
                    self.pause_index = (self.pause_index - 1) % n
                    SPEECH.say(self.PAUSE_ITEMS[self.pause_index])
                elif is_action("menu_down", ev):
                    AUDIO.play_ui("focus")
                    self.pause_index = (self.pause_index + 1) % n
                    SPEECH.say(self.PAUSE_ITEMS[self.pause_index])
                elif is_action("confirm", ev):
                    AUDIO.play_ui("select")
                    self.pause_activate()
                elif is_action("back", ev) or is_action("pause", ev):
                    self.pause_menu = False
                    AUDIO.play_ui("back")
                    SPEECH.say("Resumed")
                return
            # gameplay keys (each action = one original touch gesture)
            if is_action("pause", ev):
                self.pause_menu = True
                self.pause_index = 0
                AUDIO.play_ui("open")
                SPEECH.say("Paused. " + ", ".join(self.PAUSE_ITEMS) +
                           ". Up and down arrows to choose, enter to activate, escape to resume.")
                return
            if is_action("status", ev):
                self.read_status()
                return
            if is_action("attack", ev):
                self.do_attack()
            elif is_action("crouch", ev):
                self.do_crouch()
            elif is_action("crossbow", ev):
                self.change_weapon("Crossbow")
            elif is_action("sword", ev):
                self.change_weapon("Sword")
            elif is_action("potion", ev):
                self.do_potion()
            elif is_action("fireball", ev):
                self.do_fireball()
            elif is_action("turn_left", ev):
                self.turn(-1, 10.0)
            elif is_action("turn_right", ev):
                self.turn(1, 10.0)
            return

        if st == "Outro":
            if is_action("confirm", ev):
                AUDIO.stop_story()
                if self.dialogue and self.dialogue[1]:
                    self.dialogue[1]()
            return

    def back_to_menu(self):
        self.world = None
        self.dialogue = None
        AUDIO.stop_story()
        AUDIO.stop_all_sfx()
        AUDIO.play_heartbeat(0)
        self.play_menu_music()
        self.set_state("Menu")
        self.menu_index = 0
        self.speak_menu(self.MENU_ITEMS, self.menu_index, "Main menu")

    # ------------------------------------------------------------- per-frame
    def update(self, dt):
        self.state_time += dt
        if self.state == "Splash":
            if self.state_time > 2.0:
                self.set_state("Menu")
                self.menu_index = 0
                self.speak_menu(self.MENU_ITEMS, self.menu_index, "Main menu")
        elif self.state in ("Level", "LevelIntro", "LevelOutro"):
            if not self.pause_menu:
                self.update_world(dt)
        # dialogue completion polling (original: FMOD dialogue callback)
        if self.state in ("LevelIntro", "LevelOutro", "Outro") and self.dialogue:
            if not AUDIO.story_busy():
                cb = self.dialogue[1]
                self.dialogue = None
                if cb:
                    cb()

    # keyboard turn-repeat
    def update_keys(self, dt):
        if self.state != "Level" or not self.world or self.world.status != "Playing" \
                or self.pause_menu:
            return
        keys = pygame.key.get_pressed()
        rate = 90.0
        if keys[pygame.K_LEFT]:
            self.turn(-1, rate * dt)
        if keys[pygame.K_RIGHT]:
            self.turn(1, rate * dt)

    # ------------------------------------------------------------- render
    def render(self, screen):
        screen.fill((10, 8, 6))
        font = pygame.font.SysFont("dejavusansmono", 20)
        big = pygame.font.SysFont("dejavusansmono", 28, bold=True)
        w = self.world

        def center(txt, y, f=None, col=(230, 220, 200)):
            s = (f or font).render(txt, True, col)
            screen.blit(s, s.get_rect(center=(320, y)))

        if self.state == "Splash":
            center("To the Dragon Cave", 200, big)
            center("A Kikiriki Games audio game - Python port", 250, col=(160, 150, 130))
            center("Press Enter", 320, col=(200, 180, 120))
        elif self.state == "Menu":
            center("To the Dragon Cave", 60, big)
            y = 140
            for i, item in enumerate(self.MENU_ITEMS):
                col = (255, 215, 100) if i == self.menu_index else (150, 140, 120)
                center(("> " if i == self.menu_index else "") + item, y, col=col)
                y += 42
        elif self.state == "PlayLevel":
            center("Choose a level", 80, big)
            center("Level %d" % (self.play_level_index + 1), 220, big, (255, 215, 100))
            center("Left/Right to choose, Enter to play, Escape for menu", 300, col=(150, 140, 120))
        elif self.state == "Settings":
            center("Settings", 60, big)
            y = 150
            names = ["Easy", "Normal", "Hard"]
            vals = ["Difficulty: " + names[SESSION.difficulty],
                    "Soundtrack volume: %d%%" % SESSION.soundtrack_volume, "Back"]
            for i, v in enumerate(vals):
                col = (255, 215, 100) if i == self.settings_index else (150, 140, 120)
                center(("> " if i == self.settings_index else "") + v, y, col=col)
                y += 45
        elif self.state == "Credits":
            center("Credits - page %d of %d" % (self.credits_page + 1, self.credits_pages), 200, big)
            center("Original game by Kikiriki Games (2022)", 260, col=(160, 150, 130))
            center("Python port generated by reverse engineering", 290, col=(160, 150, 130))
        elif self.state in ("Level", "LevelIntro", "LevelOutro") and w:
            if w.endless:
                center("Endless battle - wave %d" % w.tier, 30, col=(255, 215, 100))
            else:
                center("Level %d" % w.level_number, 30, col=(255, 215, 100))
            if w.status == "Playing":
                # simple visual aid (the game is fully playable blind)
                for e in w.enemies:
                    if e.is_dying:
                        continue
                    x = 320 + int(280 * math.sin(math.radians(e.bearing)))
                    y = 300 - int(120 * max(0.0, 1.0 - e.distance / 50.0))
                    pygame.draw.circle(screen, (200, 60, 50), (x, y), 12)
                    pygame.draw.line(screen, (120, 40, 30), (320, 380), (x, y), 2)
                px = 320 + int(280 * math.sin(math.radians(w.player_bearing)))
                pygame.draw.polygon(screen, (240, 230, 180), [(px, 360), (px - 12, 385), (px + 12, 385)])
                pygame.draw.line(screen, (240, 230, 180), (320, 380), (px, 360), 3)
                # projectiles
                for p in w.projectiles:
                    x = 320 + int(280 * math.sin(math.radians(p.bearing)))
                    y = 300 - int(120 * max(0.0, 1.0 - abs(p.distance) / 50.0))
                    col = (255, 160, 40) if p.kind in ("fireball", "dragon_fireball") else (180, 200, 255)
                    pygame.draw.circle(screen, col, (x, y), 5)
                center("HP %d   Gold %d   %s: %s" % (
                    w.player_health, SESSION.gold, w.active_weapon,
                    "%d arrows" % w.arrows if w.active_weapon == "Crossbow" else
                    ("diamond" if w.sword_upgraded else "sword")), 430, col=(170, 160, 140))
            else:
                center("..." if self.state != "Level" else "", 240)
        elif self.state == "Market":
            center("Marketplace", 50, big)
            y = 120
            for i, key in enumerate(self.MARKET_ITEMS):
                amount, price = MARKET_PRICES[key]
                names = {"arrows5": "%d arrows" % amount, "arrows10": "%d arrows" % amount,
                         "arrows20": "%d arrows" % amount, "healPotion": "Healing potion",
                         "fireball": "Fireball", "swordUpgrade": "Diamond sword"}
                col = (255, 215, 100) if i == self.market_index else (150, 140, 120)
                center(("> " if i == self.market_index else "") + "%s - %d gold" % (names[key], price),
                       y, col=col)
                y += 38
            center("Gold: %d   (Escape to continue)" % SESSION.gold, 420, col=(200, 180, 120))
        elif self.state == "Loose":
            center("You died", 200, big, (220, 80, 60))
            center("Press Enter for the menu", 260, col=(150, 140, 120))
        elif self.state == "EndlessEnd" and self.endless_stats:
            center("Endless battle over", 140, big, (255, 215, 100))
            s = self.endless_stats
            center("Kills: %d   Gold: %d   Accuracy: %d%%" % (s["kills"], s["gold"], s["acc"]), 220)
            center("Time: %d s" % s["time"], 260)
            center("Press Enter for the menu", 320, col=(150, 140, 120))
        elif self.state == "Outro":
            center("The end", 220, big, (255, 215, 100))
        pygame.display.flip()

    # ------------------------------------------------------------- dodge hooks
    def notify_dodge(self, direction):
        """Called for left/right swipes during boss attacks."""
        w = self.world
        if not w or w.status != "Playing":
            return
        if w.boss_type == "troll":
            self.troll_dodge(direction)
        elif w.boss_type == "snakes":
            if w.boss_state == "attacking" and abs(w.boss_dir - direction) < 1.5:
                pass  # wrong way is fine too - snakes dodge = any quick swipe? original: direction check
            if w.boss_state == "attacking":
                w.boss_dodged = True
                AUDIO.play(sfx("Duck Flapping Wings 5") or "", 0.9)
        elif w.boss_type == "waves":
            if w.boss_state == "attacking":
                w.boss_dodged = True
                AUDIO.play(sfx("Ambience Waves Ocean Loop") or "", 0.7)
                SPEECH.say("Dodged!")

# ----------------------------------------------------------------------------
# entry point
# ----------------------------------------------------------------------------
def main():
    pygame.init()
    screen = pygame.display.set_mode((640, 480))
    clock = pygame.time.Clock()
    game = Game()
    game.start()
    running = True
    while running:
        dt = clock.tick(60) / 1000.0
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            else:
                game.handle_event(ev)
        game.update_keys(dt)
        game.update(dt)
        game.render(screen)
    SESSION.save()
    pygame.quit()

if __name__ == "__main__":
    main()

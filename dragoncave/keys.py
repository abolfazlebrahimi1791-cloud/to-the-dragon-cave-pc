#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""To the Dragon Cave - keyboard bindings.

Key bindings are fixed constants in the CONTROLS table. Every action is
the keyboard equivalent of one original touch gesture. Modifiers can be
combined, e.g. "CTRL+SPACE".
"""

import pygame

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

def _norm_mods(mods):
    """pygame reports KMOD_LCTRL (0x40) for the left Ctrl key, but bindings
    use the generic KMOD_CTRL (0xC0 = left|right). Normalize left/right
    flags to the generic ones so "CTRL+SPACE" works with either Ctrl."""
    out = 0
    if mods & pygame.KMOD_CTRL:  out |= pygame.KMOD_CTRL
    if mods & pygame.KMOD_SHIFT: out |= pygame.KMOD_SHIFT
    if mods & pygame.KMOD_ALT:   out |= pygame.KMOD_ALT
    return out

def is_action(action, ev):
    """True when a KEYDOWN event matches the binding of `action`."""
    mods = _norm_mods(ev.mod & (pygame.KMOD_CTRL | pygame.KMOD_SHIFT | pygame.KMOD_ALT))
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

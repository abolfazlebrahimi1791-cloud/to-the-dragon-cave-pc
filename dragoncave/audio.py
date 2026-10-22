#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""To the Dragon Cave - audio engine.

Plays the original game's OGG audio (all extracted from the FMOD banks)
with stereo panning + distance gain, like FMOD in the original. Also hosts
the sfx() name resolver and the original game's UI sound set.
"""

import os
import math

import pygame

from .config import AUDIO_DIR

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

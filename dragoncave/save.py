#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""To the Dragon Cave - player save data and level statistics.

Player save data is a plain JSON file next to the program (save.json).
(legacy save/GameSession.gd from older builds is migrated automatically)
"""

import os
import json

from .config import (GAME_SESSION_FILE, BASE_DIR, MONEY_FOR_KILL,
                     CROSSBOW_KILLS_BONUS, FIREBALL_KILLS_BONUS, DISTANT_KILLS_BONUS)

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

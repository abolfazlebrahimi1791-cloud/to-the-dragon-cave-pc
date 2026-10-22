#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""To the Dragon Cave - game entities and level world simulation.

Attacker  - exact port of the original Attacker/MonoBehaviour
Projectile- arrow / fireball / incoming projectiles
GameWorld - port of LevelController + PlayerController + AttackerSpawner
            for one level
"""

import math
import random

from .config import (LEVELS, ENDLESS, ENEMY_STATS, ATTACKER_DISTANCE,
                     MIN_ANGLE, MAX_ANGLE, DIFFICULTY_EASY_MULTIPLIER,
                     DIFFICULTY_HARD_MULTIPLIER, DIFFICULTY_HARD_HEALTH_MULTIPLIER,
                     unity_random_range_int, unity_random_range_float, unity_sign)
from .save import SESSION, LevelStats
from .audio import AUDIO, sfx

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

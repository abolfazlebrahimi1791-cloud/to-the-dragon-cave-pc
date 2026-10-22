#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""To the Dragon Cave - main game application.

Game flow, menus, combat, boss fights, marketplace, input handling and
rendering. Port of the original Unity scenes/controllers.
"""

import math
import random
import time
import threading
import sys

import pygame

from .config import (LEVELS, ENDLESS, PROJECTILE, MARKET_PRICES,
                     NUMBER_OF_LEVELS, FIREBALL_AVAILABLE_FROM_LEVEL,
                     SWORD_DAMAGE, SWORD_ATTACK_SPEED, CROSSBOW_ATTACK_SPEED,
                     DISTANCE_BONUS, ATTACKER_DISTANCE,
                     DIFFICULTY_EASY_MULTIPLIER, DIFFICULTY_HARD_MULTIPLIER,
                     unity_random_range_int, unity_random_range_float)
from .speech import SPEECH
from .audio import AUDIO, sfx
from .keys import is_action, help_text
from .save import SESSION, LevelStats
from .world import GameWorld, Projectile

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
        # wizard frog phase: attack = kill the frog (the other ending = wait)
        if w.boss_type == "wizard" and w.boss_state == "frog":
            self.wizard_frog_action(True)
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
            AUDIO.play_at(e.snd_death, e.rel_bearing(), e.distance, 1.0)
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
        if not w.allow_crouch or w.is_crouching:   # FIX: was allow_crouching (crash)
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
        """1-finger drag left/right / arrow keys: rotate within clamp.
        The same gesture dodges boss attacks (troll/snakes/waves)."""
        w = self.world
        if not w or w.status != "Playing" or w.dead:
            return
        w.player_bearing += direction * amount
        lo, hi = -w.rot_clamp, w.rot_clamp
        if w.player_bearing < lo: w.player_bearing = lo
        if w.player_bearing > hi: w.player_bearing = hi
        self.notify_dodge(direction)   # FIX: dodge was never wired up

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
                        AUDIO.play_at(e.snd_attack, e.rel_bearing(), e.distance, 1.0)
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
                    AUDIO.play_at(sfx("Fire Punch 1", "Blow Torch Stop") or "", wiz.rel_bearing(), wiz.distance, 1.0)
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
                AUDIO.play_at(sfx("BABY BREATHING FIRE 1", "DRAGON BREATHING FIRE 16") or "",
                              bearing - w.player_bearing, 50, 1.0)

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
            n_items = len(self.SETTINGS_ITEMS)
            if is_action("menu_up", ev):
                AUDIO.play_ui("focus")
                self.settings_index = (self.settings_index - 1) % n_items
                self.speak_settings()
            elif is_action("menu_down", ev):
                AUDIO.play_ui("focus")
                self.settings_index = (self.settings_index + 1) % n_items
                self.speak_settings()
            elif is_action("menu_left", ev):
                if self.settings_index < n_items - 1:      # no value to change on "Back"
                    self.settings_change(-1)
                else:
                    SPEECH.say("Back")
            elif is_action("menu_right", ev):
                if self.settings_index < n_items - 1:      # no value to change on "Back"
                    self.settings_change(1)
                else:
                    SPEECH.say("Back")
            elif is_action("confirm", ev):
                if self.settings_index >= n_items - 1:     # Enter on the "Back" item
                    AUDIO.play_ui("back")
                    self.back_to_menu()
                else:
                    self.speak_settings()                  # repeat the current setting
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
                # Enter skips the dialogue; Escape also goes back/skips
                if is_action("confirm", ev):
                    AUDIO.stop_story()
                    if self.dialogue and self.dialogue[1]:
                        self.dialogue[1]()
                elif is_action("back", ev) or is_action("pause", ev):
                    AUDIO.play_ui("back")
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
            elif is_action("back", ev) or is_action("pause", ev):
                AUDIO.play_ui("back")
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
        # keep the theme song playing if it already is (Settings -> Back etc.),
        # otherwise start it (coming from Credits / Loose / ...)
        if AUDIO.current_music != self.THEME_SONG or not AUDIO.music_busy():
            AUDIO.stop_music()
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
        """Called for left/right turns during boss attacks (original:
        the same swipe that turns also dodges)."""
        w = self.world
        if not w or w.status != "Playing":
            return
        if w.boss_type == "troll":
            self.troll_dodge(direction)
        elif w.boss_type == "snakes":
            if w.boss_state == "attacking":
                w.boss_dodged = True
                AUDIO.play(sfx("Duck Flapping Wings 5") or "", 0.9)
        elif w.boss_type == "waves":
            if w.boss_state == "attacking":
                w.boss_dodged = True
                AUDIO.play(sfx("Ambience Waves Ocean Loop") or "", 0.7)
                SPEECH.say("Dodged!")

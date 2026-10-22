#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""To the Dragon Cave - program entry point (pygame main loop)."""

import sys

import pygame

from .game import Game
from .save import SESSION

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

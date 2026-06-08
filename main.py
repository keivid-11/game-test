#!/usr/bin/env python3
# ============================================================
# main.py — AlgoQuest: Jogo Educativo de Algoritmos
#           Abre janela nativa via pygame
# ============================================================
# Requer: pip install pygame
# Executa: python main.py
# ============================================================

import sys
import math
import pygame

from audio import door_sound, book_sound, MUSIC_PATH
from data      import (TILE, COLS, ROWS, FLOORS, BOOKS,
                       DOOR_COLS, ROOM_RANGES, C, build_floor_map)
from hashmap   import HashMap
from graph     import GridGraph, TSPSolver
import renderer as _renderer
from renderer  import (init_fonts, render_map, render_room_labels,
                       render_path, render_npc, render_book_drop,
                       render_player, render_click_indicator,
                       render_hud, render_scanlines, render_dark_overlay,
                       blit_text, blit_text_center, HUD_X, HUD_W)
from dialog    import DialogSystem

# ── Janela ────────────────────────────────────────────────────
GAME_W = COLS * TILE   # 800
GAME_H = ROWS * TILE   # 576
WIN_W  = GAME_W + HUD_W
WIN_H  = GAME_H
FPS    = 60


# ─────────────────────────────────────────────────────────────
# ESTADO DO JOGO
# ─────────────────────────────────────────────────────────────

class GameState:
    def __init__(self):
        self.screen_mode = "splash"   # splash | game
        self.floor_idx   = 0
        self.grid        = None
        self.graph       = None
        self.open_doors     : set  = set()
        self.revealed_rooms : set  = set()
        self.elevator_on    : bool = False

        # Personagem
        self.player = {
            "col": 3, "row": 8,
            "px": 3 * TILE, "py": 8 * TILE,   # posição pixel suave
            "path": [],
            "moving": False,
            "speed": 3.5,      # pixels por frame
        }

        # NPCs e livros
        self.npcs            : list = []
        self.defeated        : set  = set()
        self.book_drops      : list = []
        self.entered_rooms   : set  = set()
        self.professors_met  : int  = 0
        self.professors_needed = 2

        # TSP
        self.tsp_route : list = []
        self.tsp_ptr   : int  = 0
        self.tsp_dist  : float = 0.0

        # Inventário (HashMap)
        self.inventory = HashMap()

        # Clique
        self.click_indicator = None   # (col, row, t, max_t)

        # Tick global
        self.tick = 0

        # Andar atual
        self.floor_name = ""

    # ── Carrega andar ────────────────────────────────────────
    def load_floor(self, idx: int):
        self.floor_idx       = idx
        floor_def            = FLOORS[idx]
        self.floor_name      = floor_def["name"]
        self.grid            = build_floor_map()
        self.graph           = GridGraph(self.grid, COLS, ROWS)
        self.open_doors      = set()
        self.revealed_rooms  = set()
        self.elevator_on     = False
        self.professors_met  = 0
        self.entered_rooms   = set()
        self.book_drops      = []

        # Posição do player: corredor central
        self.player["col"]  = 3
        self.player["row"]  = 8
        self.player["px"]   = 3 * TILE
        self.player["py"]   = 8 * TILE
        self.player["path"] = []
        self.player["moving"] = False

        # NPCs do andar
        self.npcs = [dict(n) for n in floor_def["npcs"]]
        self.defeated = self.defeated  # mantém derrotados cross-floor? não — limpa
        self.defeated = set()

        # TSP
        start = (self.player["col"], self.player["row"])
        nodes = [{"id": n["id"], "col": n["tx"], "row": n["ty"],
                  "name": n["name"].split()[-1]} for n in self.npcs]
        self.tsp_route = TSPSolver.nearest_neighbor(start, nodes)
        self.tsp_ptr   = 0
        self.tsp_dist  = round(TSPSolver.route_distance(start, self.tsp_route))

    def hud_state(self):
        return {
            "floor_name":  self.floor_name,
            "defeated":    self.defeated,
            "tsp_ptr":     self.tsp_ptr,
            "tsp_dist":    self.tsp_dist,
        }


# ─────────────────────────────────────────────────────────────
# LÓGICA DE MOVIMENTO
# ─────────────────────────────────────────────────────────────

def update_player(gs: GameState, dlg=None):
    p = gs.player
    if not p["moving"] or not p["path"]:
        p["moving"] = False
        return

    target_col, target_row = p["path"][0]
    tx = target_col * TILE
    ty = target_row * TILE
    dx = tx - p["px"]
    dy = ty - p["py"]
    dist = math.hypot(dx, dy)

    if dist <= p["speed"]:
        p["px"] = tx
        p["py"] = ty
        p["col"] = target_col
        p["row"] = target_row
        p["path"].pop(0)
        open_nearby_doors(gs)
        if not p["path"]:
            p["moving"] = False
            on_player_arrived(gs, dlg)
    else:
        p["px"] += dx / dist * p["speed"]
        p["py"] += dy / dist * p["speed"]


def open_nearby_doors(gs: GameState):
    col, row = gs.player["col"], gs.player["row"]
    for dc, dr in ((0, 0), (0, -1), (0, 1), (-1, 0), (1, 0)):
        c, r = col + dc, row + dr
        if 0 <= r < ROWS and 0 <= c < COLS:
            door_id = f"{c},{r}"

        if gs.grid[r][c] == 2 and door_id not in gs.open_doors:
            gs.open_doors.add(door_id)
            door_sound.play()

        # Porta de sala (row 6) → revela a sala correspondente
        if r == 6 and c in DOOR_COLS:
            gs.revealed_rooms.add(DOOR_COLS.index(c))


def on_player_arrived(gs: GameState, dlg: "DialogSystem" = None):
    p = gs.player
    col, row = p["col"], p["row"]

    # Perto de NPC?
    for npc in gs.npcs:
        if npc["id"] in gs.defeated:
            continue
        if abs(col - npc["tx"]) <= 1 and abs(row - npc["ty"]) <= 1:
            if dlg:
                trigger_npc(gs, npc, dlg)
            return

    # Perto de livro no chão?
    for drop in gs.book_drops:
        if not drop["visible"]:
            continue
        if abs(col - drop["col"]) <= 1 and abs(row - drop["row"]) <= 1:
            collect_book(gs, drop, dlg)
            return

    # Entrou em sala?
    if row <= 5:
        check_room_entry(gs, dlg)


def check_room_entry(gs: GameState, dlg):
    col = gs.player["col"]
    floor_def = FLOORS[gs.floor_idx]
    for i, (cs, ce) in enumerate(ROOM_RANGES):
        if cs <= col <= ce:
            room = floor_def["rooms"][i]
            if room["id"] not in gs.entered_rooms:
                gs.entered_rooms.add(room["id"])
                if not room["has_prof"]:
                    if dlg:
                        dlg.notify(f"Professor nao esta na {room['name']}...",
                                   C["gray"])
            return


# ─────────────────────────────────────────────────────────────
# INTERAÇÃO COM NPC
# ─────────────────────────────────────────────────────────────

def trigger_npc(gs: GameState, npc: dict, dlg: DialogSystem):
    def on_complete(completed_npc):
        gs.defeated.add(completed_npc["id"])
        gs.professors_met += 1
        gs.tsp_ptr = min(gs.tsp_ptr + 1, len(gs.tsp_route))

        # Drop do livro
        book = BOOKS[completed_npc["book_id"]]
        drop = {
            "col": completed_npc["tx"],
            "row": completed_npc["ty"] + 1,
            "bookId": completed_npc["book_id"],
            "visible": True,
            "color": book["color"],
        }
        gs.book_drops.append(drop)

        # Mostra o livro
        dlg.show_book(book)
        dlg.notify(f"Livro dropado! Va pegar!", C["book"])

        # Verifica elevador
        if gs.professors_met >= gs.professors_needed:
            gs.elevator_on = True
            dlg.notify("ELEVADOR DESBLOQUEADO! Suba para o proximo andar!",
                       C["elev_on"], 300)

    dlg.start_npc(npc, on_complete)


def collect_book(gs: GameState, drop: dict, dlg):
    drop["visible"] = False
    book = BOOKS[drop["bookId"]]
    gs.inventory.put(book["id"], book)
    book_sound.play()
    if dlg:
        dlg.notify(f"  {book['name']} coletado!  ", book["color"])
    check_win(gs, dlg)


def check_win(gs: GameState, dlg):
    if len(gs.inventory) >= len(BOOKS):
        if dlg:
            dlg.show_win()


# ─────────────────────────────────────────────────────────────
# SPLASH SCREEN
# ─────────────────────────────────────────────────────────────

def draw_splash(surf, tick):
    surf.fill(C["bg"])
    cx = WIN_W // 2
    cy = WIN_H // 2

    # Título
    pulse = int(math.sin(tick * 0.05) * 10)
    title_col = (74, min(255, 200 + pulse), min(255, 180 + pulse))
    blit_text_center(surf, "ALGO", cx, cy - 100, _renderer.font_large, title_col)
    blit_text_center(surf, "QUEST", cx, cy - 68, _renderer.font_large, title_col)

    # Subtítulo
    blit_text_center(surf, "Jogo Educativo de Algoritmos",
                     cx, cy - 20, _renderer.font_medium, C["white"])

    # Tópicos
    topics = [
        ("HashMap", C["hud_border"]),
        ("Grafos + BFS", (60, 200, 255)),
        ("TSP - Viz. Mais Proximo", (255, 160, 60)),
        ("Mochila - Prog. Dinamica", (255, 100, 140)),
    ]
    ty = cy + 20
    for name, col in topics:
        blit_text_center(surf, f"  {name}  ", cx, ty, _renderer.font_small, col)
        ty += 22

    # Botão START
    blink = (tick // 30) % 2 == 0
    if blink:
        blit_text_center(surf, "[ PRESSIONE ENTER PARA INICIAR ]",
                         cx, cy + 140, _renderer.font_medium, C["yellow"])

    # Créditos
    blit_text_center(surf, "Controles: Click p/ mover  |  I: Inventario  |  ESC: Sair",
                     cx, WIN_H - 28, _renderer.font_small, C["gray"])


# ─────────────────────────────────────────────────────────────
# LOOP PRINCIPAL
# ─────────────────────────────────────────────────────────────

def main():
    pygame.init()
    pygame.mixer.init()
  
    pygame.mixer.music.load(MUSIC_PATH)
    pygame.mixer.music.set_volume(0.3)
    pygame.mixer.music.play(-1)
    info = pygame.display.Info()
    screen = pygame.display.set_mode(
        (info.current_w, info.current_h), pygame.FULLSCREEN
    )
    pygame.display.set_caption("AlgoQuest — Jogo Educativo de Algoritmos")
    clock  = pygame.time.Clock()
    init_fonts()

    # Surface interna na resolução original; escalada para a tela cheia
    render_surf = pygame.Surface((WIN_W, WIN_H))
    scr_w, scr_h = screen.get_size()
    scale    = min(scr_w / WIN_W, scr_h / WIN_H)
    scaled_w = int(WIN_W * scale)
    scaled_h = int(WIN_H * scale)
    off_x    = (scr_w - scaled_w) // 2
    off_y    = (scr_h - scaled_h) // 2

    def to_game_pos(sx, sy):
        """Converte coordenada de tela para coordenada do render_surf."""
        return ((sx - off_x) / scale, (sy - off_y) / scale)

    gs  = GameState()
    dlg = DialogSystem()

    # Surface de jogo (separada do HUD)
    game_surf = pygame.Surface((GAME_W, GAME_H))

    running = True
    while running:
        events = pygame.event.get()
        raw_mouse  = pygame.mouse.get_pos()
        game_mouse = to_game_pos(*raw_mouse)

        for event in events:
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False

                # Splash → jogo
                if gs.screen_mode == "splash":
                    if event.key in (pygame.K_RETURN, pygame.K_SPACE):               
                        gs.screen_mode = "game"
                        gs.load_floor(0)
                        dlg.notify(f"Bem-vindo ao 1 Andar! Clique para mover.", C["player"], 240)

                # Inventário
                elif (event.key == pygame.K_i
                      and gs.screen_mode == "game"
                      and not dlg.is_active()):
                    books = gs.inventory.values()
                    dlg.show_inventory(books)

            # Clique no mapa → BFS
            if (event.type == pygame.MOUSEBUTTONDOWN
                    and event.button == 1
                    and gs.screen_mode == "game"
                    and not dlg.is_active()):

                mx, my = to_game_pos(*event.pos)
                if mx < GAME_W:   # dentro da área do jogo
                    click_col = int(mx) // TILE
                    click_row = int(my) // TILE

                    # Clique no elevador
                    if (gs.elevator_on
                            and 21 <= click_col <= 23
                            and 11 <= click_row <= 13):
                        go_next_floor(gs, dlg)
                        continue

                    # Pathfinding BFS
                    path = gs.graph.find_path(
                        gs.player["col"], gs.player["row"],
                        click_col, click_row,
                        gs.open_doors,
                    )
                    if path:
                        gs.player["path"]   = path
                        gs.player["moving"] = True
                        gs.click_indicator  = [click_col, click_row, 0, 25]
                    else:
                        dlg.notify("Caminho bloqueado!", C["red"], 90)

        # ── Update ──────────────────────────────────────────
        gs.tick += 1

        if gs.screen_mode == "game":
            if not dlg.is_active():
                update_player(gs, dlg)
            else:
                # Parar player enquanto dialoga
                gs.player["moving"] = False

            # Indicador de clique
            if gs.click_indicator:
                gs.click_indicator[2] += 1
                if gs.click_indicator[2] >= gs.click_indicator[3]:
                    gs.click_indicator = None

        dlg.update(events, game_mouse)

        # ── Render ──────────────────────────────────────────
        render_surf.fill(C["bg"])

        if gs.screen_mode == "splash":
            draw_splash(render_surf, gs.tick)

        else:
            # Jogo
            game_surf.fill(C["bg"])

            render_map(game_surf, gs.grid, gs.open_doors, gs.elevator_on,
                       gs.revealed_rooms)
            render_room_labels(game_surf, FLOORS[gs.floor_idx]["rooms"],
                               gs.revealed_rooms)

            # Path preview
            if not dlg.is_active():
                render_path(game_surf, gs.player["path"])

            # Livros no chão (só em salas reveladas)
            for drop in gs.book_drops:
                drop_room = next((i for i, (cs, ce) in enumerate(ROOM_RANGES)
                                  if cs <= drop["col"] <= ce), None)
                if drop_room is None or drop_room in gs.revealed_rooms:
                    render_book_drop(game_surf, drop, gs.tick)

            # NPCs (só em salas reveladas)
            for npc in gs.npcs:
                if npc["room_idx"] in gs.revealed_rooms:
                    render_npc(game_surf, npc, npc["id"] in gs.defeated, gs.tick)

            # Player
            render_player(game_surf, gs.player, gs.tick)

            # Indicador de clique
            render_click_indicator(game_surf, gs.click_indicator)

            render_scanlines(game_surf, GAME_W, GAME_H)

            render_surf.blit(game_surf, (0, 0))

            # HUD lateral
            render_hud(render_surf, gs.hud_state(), gs.tsp_route, gs.inventory)

        # Diálogo (sempre por cima)
        dlg.draw(render_surf)

        # Escala para tela cheia com letterbox
        screen.fill((0, 0, 0))
        scaled = pygame.transform.scale(render_surf, (scaled_w, scaled_h))
        screen.blit(scaled, (off_x, off_y))

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()
    sys.exit(0)


# ─────────────────────────────────────────────────────────────
# TRANSIÇÃO DE ANDAR
# ─────────────────────────────────────────────────────────────

def go_next_floor(gs: GameState, dlg: DialogSystem):
    next_idx = gs.floor_idx + 1
    if next_idx >= len(FLOORS):
        # Último andar — checa vitória
        check_win(gs, dlg)
        return

    # Flash de elevador (simples: recarrega andar)
    gs.load_floor(next_idx)
    dlg.notify(f"Subindo para o {next_idx + 1}o Andar!", C["elev_on"], 240)


if __name__ == "__main__":
    main()

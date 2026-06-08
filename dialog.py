# ============================================================
# dialog.py — Sistema de diálogo, Q&A e notificações
# ============================================================

import pygame
import renderer as _renderer
from audio import correct_sound, wrong_sound
from renderer import (blit_text, blit_text_center, draw_rect_border,
                      render_dialog_bg, render_dark_overlay)
from data import C, COLS, ROWS, TILE

GAME_W = COLS * TILE
GAME_H = ROWS * TILE
HUD_W  = 230
WIN_W  = GAME_W + HUD_W
WIN_H  = GAME_H


# ─────────────────────────────────────────────────────────────
# BOTÃO PIXEL ART
# ─────────────────────────────────────────────────────────────

class Button:
    def __init__(self, rect, text, color=None):
        self.rect  = pygame.Rect(rect)
        self.text  = text
        self.color = color or C["hud_border"]
        self.hovered = False
        self.state   = "normal"  # normal | correct | wrong

    def draw(self, surf):
        if self.state == "correct":
            bg, border = (20, 60, 40), C["green"]
        elif self.state == "wrong":
            bg, border = (60, 20, 20), C["red"]
        elif self.hovered:
            bg, border = self.color, C["dark"]
        else:
            bg, border = C["hud_bg"], self.color

        pygame.draw.rect(surf, bg, self.rect)
        pygame.draw.rect(surf, border, self.rect, 2)
        col_t = C["dark"] if self.hovered and self.state == "normal" else C["white"]
        cx = self.rect.centerx
        cy = self.rect.centery - _renderer.font_small.get_height() // 2
        blit_text_center(surf, self.text, cx, cy, _renderer.font_small, col_t)

    def update(self, mouse_pos):
        self.hovered = self.rect.collidepoint(mouse_pos)

    def check_click(self, event):
        if (event.type == pygame.MOUSEBUTTONDOWN
                and event.button == 1
                and self.rect.collidepoint(event.pos)):
            return True
        return False


# ─────────────────────────────────────────────────────────────
# TYPEWRITER
# ─────────────────────────────────────────────────────────────

class Typewriter:
    def __init__(self, speed=2):
        self.full_text = ""
        self.visible   = ""
        self.speed     = speed   # chars por frame
        self._accum    = 0.0
        self.done      = True

    def set(self, text: str):
        self.full_text = text
        self.visible   = ""
        self._accum    = 0.0
        self.done      = False

    def update(self):
        if self.done:
            return
        self._accum += self.speed
        while self._accum >= 1 and len(self.visible) < len(self.full_text):
            self.visible += self.full_text[len(self.visible)]
            self._accum  -= 1
        if len(self.visible) >= len(self.full_text):
            self.done = True

    def skip(self):
        self.visible = self.full_text
        self.done    = True

    def draw(self, surf, x, y, w, font, color):
        """Renderiza texto com quebra de linha automática."""
        line_h = font.get_height() + 3
        cy = y
        for raw_line in self.visible.split("\n"):
            words = raw_line.split(" ")
            line  = ""
            for word in words:
                test = (line + " " + word).strip()
                if font.size(test)[0] <= w:
                    line = test
                else:
                    if line:
                        blit_text(surf, line, x, cy, font, color)
                        cy += line_h
                    line = word
            if line:
                blit_text(surf, line, x, cy, font, color)
                cy += line_h
        return cy  # retorna y final


# ─────────────────────────────────────────────────────────────
# SISTEMA DE DIÁLOGO (NPC, desafio, inventário, livro)
# ─────────────────────────────────────────────────────────────

class DialogSystem:
    STATE_IDLE     = "idle"
    STATE_NPC      = "npc"        # exibindo linhas do NPC
    STATE_QUIZ     = "quiz"       # pergunta Q&A
    STATE_RESULT   = "result"     # certo / errado
    STATE_BOOK     = "book"       # mostrar livro coletado
    STATE_INVENTORY= "inventory"  # ver inventário
    STATE_WIN      = "win"        # tela de vitória

    def __init__(self):
        self.state      = self.STATE_IDLE
        self.npc        = None
        self.lines      = []
        self.line_idx   = 0
        self.typewriter = Typewriter(speed=2)
        self.buttons    = []
        self.q_idx      = 0
        self.on_complete= None    # callback(npc)
        self.result_msg = ""
        self.result_ok  = False
        self.book_data  = None
        self.inv_data   = []
        self.inv_scroll = 0

        # Notificação flutuante
        self.notif_text    = ""
        self.notif_timer   = 0
        self.notif_color   = C["yellow"]

    # ── Estado ──────────────────────────────────────────────
    def is_active(self):
        return self.state != self.STATE_IDLE

    # ── Notificações ─────────────────────────────────────────
    def notify(self, text: str, color=None, duration=180):
        self.notif_text  = text
        self.notif_timer = duration
        self.notif_color = color or C["yellow"]

    # ── Inicia conversa com NPC ──────────────────────────────
    def start_npc(self, npc: dict, on_complete):
        self.npc        = npc
        self.lines      = npc["lines"]
        self.line_idx   = 0
        self.on_complete= on_complete
        self.state      = self.STATE_NPC
        self._set_line(0)

    def _set_line(self, idx):
        text = self.lines[idx]
        if text == "---":
            text = "─" * 28
        self.typewriter.set(text)
        self._build_npc_buttons()

    def _build_npc_buttons(self):
        bw, bh = 180, 28
        bx = GAME_W // 2 - bw // 2
        by = GAME_H - 55
        self.buttons = [Button((bx, by, bw, bh), "[ CONTINUAR ]")]
        if not self.typewriter.done:
            self.buttons.append(
                Button((bx + bw + 6, by, 100, bh), "[ PULAR ]", C["gray"]))

    # ── Inicia quiz ──────────────────────────────────────────
    def _start_quiz(self):
        self.state = self.STATE_QUIZ
        self.q_idx = 0
        self._build_quiz_buttons()

    def _build_quiz_buttons(self):
        q = self.npc["questions"][self.q_idx]
        self.typewriter.set(q["q"])
        self.buttons = []
        opts = q["options"]
        bw, bh = 200, 28
        cols   = 2
        for i, opt in enumerate(opts):
            col_i = i % cols
            row_i = i // cols
            bx = GAME_W // 2 - bw - 4 + col_i * (bw + 8)
            by = GAME_H - 120 + row_i * (bh + 6)
            btn = Button((bx, by, bw, bh), opt)
            btn._opt_idx = i
            self.buttons.append(btn)

    # ── Verifica resposta ────────────────────────────────────
    def _check_answer(self, opt_idx: int):
        q = self.npc["questions"][self.q_idx]
        if opt_idx == q["correct"]:
            correct_sound.play()
            self.result_ok  = True
            self.result_msg = "CORRETO!\n" + q["explain"]
            self.buttons[opt_idx].state = "correct"
        else:
            wrong_sound.play()
            self.result_ok  = False
            self.result_msg = "ERRADO! Tente novamente.\n" + q["explain"]
            self.buttons[opt_idx].state = "wrong"
            self.buttons[q["correct"]].state = "correct"
        self.typewriter.set(self.result_msg)
        self.state = self.STATE_RESULT
        ok_text = "[ PROXIMA PERGUNTA ]" if self.result_ok else "[ TENTAR NOVAMENTE ]"
        bw = 240
        self.buttons = [Button((GAME_W // 2 - bw//2, GAME_H - 55, bw, 28), ok_text,
                               C["green"] if self.result_ok else C["red"])]

    # ── Avança resultado ─────────────────────────────────────
    def _advance_result(self):
        if self.result_ok:
            self.q_idx += 1
            if self.q_idx >= len(self.npc["questions"]):
                # Quiz completo!
                self.state = self.STATE_IDLE
                self.on_complete(self.npc)
            else:
                self.state = self.STATE_QUIZ
                self._build_quiz_buttons()
        else:
            # Tenta de novo
            self.state = self.STATE_QUIZ
            self._build_quiz_buttons()

    # ── Mostrar livro ────────────────────────────────────────
    def show_book(self, book: dict):
        self.book_data = book
        self.state     = self.STATE_BOOK
        bw = 200
        self.buttons = [
            Button((GAME_W // 2 - bw//2, GAME_H - 65, bw, 28),
                   "[ PEGAR LIVRO! ]", C["book"])
        ]

    # ── Mostrar inventário ───────────────────────────────────
    def show_inventory(self, books: list):
        self.inv_data   = books
        self.inv_scroll = 0
        self.state      = self.STATE_INVENTORY
        bw = 160
        self.buttons = [Button((GAME_W // 2 - bw//2, GAME_H - 55, bw, 28),
                               "[ FECHAR ]")]

    # ── Tela de vitória ──────────────────────────────────────
    def show_win(self):
        self.state = self.STATE_WIN
        bw = 240
        self.buttons = [Button((WIN_W // 2 - bw//2, WIN_H - 100, bw, 36),
                               "[ JOGAR NOVAMENTE ]", C["yellow"])]

    # ── Update ───────────────────────────────────────────────
    def update(self, events, mouse_pos):
        self.typewriter.update()
        for btn in self.buttons:
            btn.update(mouse_pos)

        # Atualiza notificação
        if self.notif_timer > 0:
            self.notif_timer -= 1

        for event in events:
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_SPACE:
                    if not self.typewriter.done:
                        self.typewriter.skip()
                    elif self.state == self.STATE_NPC:
                        self._advance_npc()

            for btn in self.buttons:
                if btn.check_click(event):
                    self._handle_btn(btn)

    def _advance_npc(self):
        nxt = self.line_idx + 1
        if nxt < len(self.lines):
            self.line_idx = nxt
            self._set_line(nxt)
        else:
            # Terminou as linhas — inicia quiz
            self._start_quiz()

    def _handle_btn(self, btn):
        if not self.typewriter.done:
            self.typewriter.skip()
            self._build_npc_buttons()
            return

        if self.state == self.STATE_NPC:
            if "PULAR" in btn.text:
                self.typewriter.skip()
                self._build_npc_buttons()
            else:
                self._advance_npc()

        elif self.state == self.STATE_QUIZ:
            self._check_answer(btn._opt_idx)

        elif self.state == self.STATE_RESULT:
            self._advance_result()

        elif self.state == self.STATE_BOOK:
            self.state = self.STATE_IDLE

        elif self.state == self.STATE_INVENTORY:
            self.state = self.STATE_IDLE

        elif self.state == self.STATE_WIN:
            pygame.event.post(pygame.event.Event(pygame.QUIT))

    # ── Draw ────────────────────────────────────────────────
    def draw(self, surf):
        self._draw_notification(surf)
        if self.state == self.STATE_IDLE:
            return
        if self.state == self.STATE_WIN:
            self._draw_win(surf); return
        if self.state == self.STATE_INVENTORY:
            self._draw_inventory(surf); return
        if self.state == self.STATE_BOOK:
            self._draw_book(surf); return

        # Overlay semi-transparente
        ov = pygame.Surface((GAME_W, GAME_H), pygame.SRCALPHA)
        ov.fill((6, 10, 20, 160))
        surf.blit(ov, (0, 0))

        # Painel do diálogo
        panel_h = 200
        panel_y = GAME_H - panel_h - 4
        render_dialog_bg(surf, (4, panel_y, GAME_W - 8, panel_h))

        # Speaker
        if self.npc:
            blit_text(surf, f"[ {self.npc['name']} ]",
                      16, panel_y + 8, _renderer.font_small, self.npc["color"])
            # Ícone do NPC (pequeno)
            pygame.draw.rect(surf, self.npc["color"],
                             (GAME_W - 50, panel_y + 6, 40, 40))
            pygame.draw.rect(surf, self.npc["hat_color"],
                             (GAME_W - 48, panel_y + 4, 36, 8))
            pygame.draw.rect(surf, C["player_skin"],
                             (GAME_W - 45, panel_y + 14, 28, 18))
            pygame.draw.rect(surf, C["dark"],
                             (GAME_W - 42, panel_y + 18, 6, 5))
            pygame.draw.rect(surf, C["dark"],
                             (GAME_W - 30, panel_y + 18, 6, 5))

        # Texto principal
        if self.state in (self.STATE_NPC, self.STATE_RESULT):
            self.typewriter.draw(surf, 16, panel_y + 28,
                                 GAME_W - 70, _renderer.font_medium, C["white"])
        elif self.state == self.STATE_QUIZ:
            q_text = self.npc["questions"][self.q_idx]["q"]
            y_q    = panel_y + 12
            for line in q_text.split("\n"):
                blit_text(surf, line, 16, y_q, _renderer.font_medium, C["yellow"])
                y_q += _renderer.font_medium.get_height() + 4
            # Label pergunta
            total_q = len(self.npc["questions"])
            lbl = f"Pergunta {self.q_idx + 1}/{total_q}"
            blit_text(surf, lbl, GAME_W - 160, panel_y + 10,
                      _renderer.font_small, C["gray"])

        # Botões
        for btn in self.buttons:
            btn.draw(surf)

        # Indicador de progresso
        if self.state == self.STATE_NPC:
            prog = self.line_idx / max(len(self.lines) - 1, 1)
            bar_w = GAME_W - 30
            pygame.draw.rect(surf, C["hud_dim"], (15, panel_y + 2, bar_w, 3))
            pygame.draw.rect(surf, C["hud_border"],
                             (15, panel_y + 2, int(bar_w * prog), 3))

    def _draw_book(self, surf):
        render_dark_overlay(surf, WIN_W, WIN_H, 210)
        book = self.book_data
        pw, ph = 440, 320
        px = GAME_W // 2 - pw // 2
        py = GAME_H // 2 - ph // 2

        render_dialog_bg(surf, (px, py, pw, ph))

        # Capa
        pygame.draw.rect(surf, book["color"], (px + 10, py + 10, 60, 80))
        pygame.draw.rect(surf, C["book_spine"], (px + 10, py + 10, 10, 80))
        for ly in [20, 28, 36, 44]:
            pygame.draw.rect(surf, C["book_spine"], (px + 25, py + ly, 30, 3))

        # Título
        blit_text(surf, book["name"], px + 80, py + 14, _renderer.font_large, book["color"])

        # Descrição
        y = py + 50
        for line in book["desc"]:
            blit_text(surf, line, px + 80, y, _renderer.font_small, C["white"])
            y += 18

        # Q&A
        y = py + 160
        blit_text(surf, "[ PERGUNTAS & RESPOSTAS ]", px + 10, y, _renderer.font_small, C["yellow"])
        y += 18
        for q, a in book["qa"]:
            blit_text(surf, f"P: {q}", px + 10, y, _renderer.font_small, C["gray"])
            y += 16
            blit_text(surf, f"R: {a}", px + 20, y, _renderer.font_small, C["green"])
            y += 20

        for btn in self.buttons:
            btn.draw(surf)

    def _draw_inventory(self, surf):
        render_dark_overlay(surf, WIN_W, WIN_H, 200)
        pw, ph = 500, 400
        px = GAME_W // 2 - pw // 2
        py = GAME_H // 2 - ph // 2

        render_dialog_bg(surf, (px, py, pw, ph))
        blit_text_center(surf, "[ INVENTARIO ]", px + pw // 2, py + 10,
                         _renderer.font_large, C["hud_border"])

        y = py + 45
        if not self.inv_data:
            blit_text_center(surf, "Vazio — explore o mapa!",
                             px + pw // 2, y, _renderer.font_medium, C["gray"])
        else:
            for book in self.inv_data:
                pygame.draw.rect(surf, book["color"], (px + 12, y, 10, 60))
                pygame.draw.rect(surf, (20, 25, 40), (px + 26, y, pw - 40, 60))
                pygame.draw.rect(surf, book["color"], (px + 26, y, pw - 40, 60), 1)
                blit_text(surf, book["name"], px + 34, y + 6, _renderer.font_medium, book["color"])
                desc_y = y + 26
                for d in book["desc"][:2]:
                    blit_text(surf, d, px + 34, desc_y, _renderer.font_small, C["gray"])
                    desc_y += 14
                y += 70

        for btn in self.buttons:
            btn.draw(surf)

    def _draw_win(self, surf):
        render_dark_overlay(surf, WIN_W, WIN_H, 230)
        cx = WIN_W // 2
        blit_text_center(surf, "PARABENS!", cx, 60, _renderer.font_large, C["yellow"])
        blit_text_center(surf, "Voce coletou todos os livros!", cx, 120, _renderer.font_medium, C["white"])
        blit_text_center(surf, "Seu TCC foi craftado com sucesso.", cx, 150, _renderer.font_medium, C["green"])
        blit_text_center(surf, "Agora voce domina:", cx, 200, _renderer.font_medium, C["white"])
        topics = ["HashMap  |  Grafos / BFS",
                  "TSP (Vizinho Mais Proximo)",
                  "Mochila (Prog. Dinamica)"]
        y = 230
        for t in topics:
            blit_text_center(surf, t, cx, y, _renderer.font_small, C["player"])
            y += 22

        for btn in self.buttons:
            btn.draw(surf)

    def _draw_notification(self, surf):
        if self.notif_timer <= 0:
            return
        alpha = min(255, self.notif_timer * 8)
        nw = _renderer.font_medium.size(self.notif_text)[0] + 24
        nx = GAME_W // 2 - nw // 2
        ny = 14
        notif_s = pygame.Surface((nw, 30), pygame.SRCALPHA)
        notif_s.fill((*C["hud_bg"], alpha))
        surf.blit(notif_s, (nx, ny))
        pygame.draw.rect(surf, (*self.notif_color, alpha), (nx, ny, nw, 30), 2)
        blit_text_center(surf, self.notif_text, nx + nw // 2, ny + 7,
                         _renderer.font_medium, (*self.notif_color[:3],))

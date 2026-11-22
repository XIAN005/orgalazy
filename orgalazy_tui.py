#!/usr/bin/env python3
"""
orgalazy_tui.py — Interface texte interactive (TUI) pour Orgalazy.

Doit être placé dans le même dossier que orgalazy.py (import direct).
Uniquement la bibliothèque standard (curses inclus depuis toujours sur Linux/macOS).

Usage :
    python3 orgalazy_tui.py

Navigation :
    Flèches haut/bas : se déplacer
    Entrée            : sélectionner / ouvrir une catégorie
    Espace             : cocher/décocher une option
    a                  : appliquer les actions (depuis l'écran d'aperçu)
    q / Échap          : retour / quitter

Un écran "Aide" est disponible dans le menu principal.
"""

from __future__ import annotations

import curses
import sys
from pathlib import Path

import orgalazy


# --------------------------------------------------------------------------
# ASCII art
# --------------------------------------------------------------------------

ASCII_ART = [
    r" ██████╗ ██████╗  ██████╗  █████╗ ██╗      █████╗ ███████╗██╗   ██╗",
    r"██╔═══██╗██╔══██╗██╔════╝ ██╔══██╗██║     ██╔══██╗╚══███╔╝╚██╗ ██╔╝",
    r"██║   ██║██████╔╝██║  ███╗███████║██║     ███████║  ███╔╝  ╚████╔╝ ",
    r"██║   ██║██╔══██╗██║   ██║██╔══██║██║     ██╔══██║ ███╔╝    ╚██╔╝  ",
    r"╚██████╔╝██║  ██║╚██████╔╝██║  ██║███████╗██║  ██║███████╗   ██║   ",
    r" ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚══════╝   ╚═╝   ",
]
ASCII_ART_WIDTH = max(len(line) for line in ASCII_ART)


# --------------------------------------------------------------------------
# État de l'application
# --------------------------------------------------------------------------

class AppState:
    def __init__(self) -> None:
        self.target_dir_str: str = str(Path.home() / "Downloads")
        self.recursive: bool = False
        self.dedupe: bool = True
        self.exclude_str: str = ""
        self.config_path_str: str = ""
        self.actions: list[orgalazy.Action] = []


# --------------------------------------------------------------------------
# Petits utilitaires d'affichage curses
# --------------------------------------------------------------------------

def safe_addstr(win, y: int, x: int, text: str, attr=0) -> None:
    """Évite les crashs si le texte dépasse la fenêtre (terminal trop petit)."""
    max_y, max_x = win.getmaxyx()
    if y < 0 or y >= max_y or x >= max_x:
        return
    try:
        win.addstr(y, x, text[: max(0, max_x - x - 1)], attr)
    except curses.error:
        pass


def prompt_text(stdscr, prompt: str, initial: str = "") -> str | None:
    """Affiche une invite de saisie en bas d'écran. Retourne None si annulé (Échap)."""
    curses.curs_set(1)
    max_y, max_x = stdscr.getmaxyx()
    y = max_y - 2
    text = initial
    while True:
        stdscr.move(y, 0)
        stdscr.clrtoeol()
        safe_addstr(stdscr, y, 0, f"{prompt}{text}", curses.A_BOLD)
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (curses.KEY_ENTER, 10, 13):
            curses.curs_set(0)
            return text
        elif ch == 27:  # Échap
            curses.curs_set(0)
            return None
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            text = text[:-1]
        elif 32 <= ch <= 126:
            text += chr(ch)


def show_message(stdscr, lines: list[str], title: str = "") -> None:
    """Affiche un message simple, attend une touche."""
    stdscr.clear()
    y = 1
    if title:
        safe_addstr(stdscr, y, 2, title, curses.A_BOLD | curses.A_UNDERLINE)
        y += 2
    for line in lines:
        safe_addstr(stdscr, y, 2, line)
        y += 1
    safe_addstr(stdscr, y + 1, 2, "-- Appuyez sur une touche pour continuer --", curses.A_DIM)
    stdscr.refresh()
    stdscr.getch()


# --------------------------------------------------------------------------
# Écrans
# --------------------------------------------------------------------------

def screen_main_menu(stdscr, state: AppState) -> str:
    """Menu principal. Retourne l'action choisie : 'scan', 'undo', 'help', 'quit'."""
    items = [
        ("Scanner un dossier", "scan"),
        ("Annuler la dernière exécution appliquée", "undo"),
        ("Aide", "help"),
        ("Quitter", "quit"),
    ]
    selected = 0
    curses.curs_set(0)

    while True:
        stdscr.clear()
        max_y, max_x = stdscr.getmaxyx()
        y = 1

        if max_x >= ASCII_ART_WIDTH + 4:
            x = max(0, (max_x - ASCII_ART_WIDTH) // 2)
            for line in ASCII_ART:
                safe_addstr(stdscr, y, x, line, curses.A_BOLD)
                y += 1
            y += 1
        else:
            safe_addstr(stdscr, y, 2, "=== ORGALAZY ===", curses.A_BOLD)
            y += 2

        subtitle = "Rangeur de fichiers par catégorie — sûr, sans dépendances, sans surprise"
        safe_addstr(stdscr, y, max(0, (max_x - len(subtitle)) // 2), subtitle, curses.A_DIM)
        y += 2

        for i, (label, _) in enumerate(items):
            attr = curses.A_REVERSE if i == selected else 0
            safe_addstr(stdscr, y + i, 4, f"  {label}", attr)

        safe_addstr(stdscr, y + len(items) + 2, 2, "↑↓ naviguer · Entrée valider · q quitter", curses.A_DIM)
        stdscr.refresh()

        ch = stdscr.getch()
        if ch in (curses.KEY_UP, ord("k")):
            selected = (selected - 1) % len(items)
        elif ch in (curses.KEY_DOWN, ord("j")):
            selected = (selected + 1) % len(items)
        elif ch in (curses.KEY_ENTER, 10, 13):
            return items[selected][1]
        elif ch in (ord("q"), 27):
            return "quit"


def screen_help(stdscr) -> None:
    lines = [
        "SCANNER UN DOSSIER",
        "  1. Choisis le dossier cible, les options (récursif, doublons, exclusions).",
        "  2. Le scan est une SIMULATION : rien n'est modifié tant que tu n'appliques pas.",
        "  3. Dans l'aperçu, ouvre une catégorie pour voir le détail des fichiers concernés.",
        "  4. Appuie sur 'a' pour appliquer réellement (confirmation demandée).",
        "",
        "ANNULER",
        "  Restaure les fichiers d'une exécution appliquée à leur emplacement d'origine.",
        "  Nécessite le même dossier que celui utilisé lors du scan appliqué.",
        "",
        "RACCOURCIS GLOBAUX",
        "  Flèches / j k     : se déplacer",
        "  Entrée            : valider / ouvrir",
        "  Espace            : cocher une case",
        "  a                 : appliquer (écran d'aperçu)",
        "  q / Échap         : retour / annuler la saisie",
    ]
    show_message(stdscr, lines, "Aide")


def screen_setup(stdscr, state: AppState) -> bool:
    """Écran de configuration du scan. Retourne False si annulé."""
    options = [
        ("Dossier cible", "dir"),
        ("Récursif (sous-dossiers)", "recursive"),
        ("Détecter les doublons", "dedupe"),
        ("Exclure (noms séparés par espace)", "exclude"),
        ("Config personnalisée (JSON, optionnel)", "config"),
        (">>> Lancer le scan", "scan"),
    ]
    selected = 0

    while True:
        stdscr.clear()
        safe_addstr(stdscr, 1, 2, "=== Configuration du scan ===", curses.A_BOLD)

        for i, (label, key) in enumerate(options):
            attr = curses.A_REVERSE if i == selected else 0
            if key == "dir":
                value = state.target_dir_str
            elif key == "recursive":
                value = "[x]" if state.recursive else "[ ]"
            elif key == "dedupe":
                value = "[x]" if state.dedupe else "[ ]"
            elif key == "exclude":
                value = state.exclude_str or "(aucun)"
            elif key == "config":
                value = state.config_path_str or "(catégories par défaut)"
            else:
                value = ""
            safe_addstr(stdscr, 4 + i, 4, f"{label:<38} {value}", attr)

        safe_addstr(stdscr, 4 + len(options) + 2, 2,
                    "↑↓ naviguer · Entrée modifier/valider · Espace cocher · q retour", curses.A_DIM)
        stdscr.refresh()

        ch = stdscr.getch()
        key = options[selected][1]

        if ch in (curses.KEY_UP, ord("k")):
            selected = (selected - 1) % len(options)
        elif ch in (curses.KEY_DOWN, ord("j")):
            selected = (selected + 1) % len(options)
        elif ch == ord(" "):
            if key == "recursive":
                state.recursive = not state.recursive
            elif key == "dedupe":
                state.dedupe = not state.dedupe
        elif ch in (curses.KEY_ENTER, 10, 13):
            if key == "dir":
                result = prompt_text(stdscr, "Dossier cible : ", state.target_dir_str)
                if result is not None:
                    state.target_dir_str = result
            elif key == "exclude":
                result = prompt_text(stdscr, "Exclure (ex: ProjetX Archive) : ", state.exclude_str)
                if result is not None:
                    state.exclude_str = result
            elif key == "config":
                result = prompt_text(stdscr, "Chemin du fichier JSON de config : ", state.config_path_str)
                if result is not None:
                    state.config_path_str = result
            elif key == "recursive":
                state.recursive = not state.recursive
            elif key == "dedupe":
                state.dedupe = not state.dedupe
            elif key == "scan":
                return True
        elif ch in (ord("q"), 27):
            return False


def run_scan(stdscr, state: AppState) -> str | None:
    """Exécute plan_actions(). Retourne un message d'erreur, ou None si succès."""
    target_dir = Path(state.target_dir_str).expanduser().resolve()
    if not target_dir.exists() or not target_dir.is_dir():
        return f"Le dossier '{target_dir}' n'existe pas ou n'est pas un dossier."

    exclude = set(state.exclude_str.split()) if state.exclude_str.strip() else set()

    categories = orgalazy.DEFAULT_CATEGORIES
    if state.config_path_str.strip():
        config_path = Path(state.config_path_str).expanduser().resolve()
        if not config_path.exists():
            return f"Fichier de config introuvable : '{config_path}'."
        try:
            data = orgalazy.json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, orgalazy.json.JSONDecodeError) as e:
            return f"Erreur de lecture de la config : {e}"
        if not isinstance(data, dict):
            return "Le fichier de config doit contenir un objet JSON {catégorie: [extensions]}."
        categories = data

    try:
        state.actions = orgalazy.plan_actions(
            target_dir=target_dir,
            categories=categories,
            dedupe=state.dedupe,
            recursive=state.recursive,
            exclude=exclude,
        )
    except OSError as e:
        return f"Erreur pendant le scan : {e}"

    return None


def screen_preview(stdscr, state: AppState) -> None:
    """
    Écran d'aperçu : navigue dans les catégories, affiche les fichiers concernés,
    permet d'appliquer réellement les actions avec 'a'.
    """
    target_dir = Path(state.target_dir_str).expanduser().resolve()

    if not state.actions:
        show_message(stdscr, ["Aucun fichier à traiter (déjà rangé, ou dossier vide)."], "Aperçu")
        return

    # Regrouper par catégorie
    by_category: dict[str, list[orgalazy.Action]] = {}
    for action in state.actions:
        by_category.setdefault(action.category, []).append(action)

    categories = sorted(by_category.keys())
    cat_selected = 0
    expanded: str | None = None   # catégorie actuellement dépliée
    file_selected = 0

    while True:
        stdscr.clear()
        safe_addstr(stdscr, 1, 2, f"=== Aperçu : {target_dir} ===", curses.A_BOLD)
        total = len(state.actions)
        safe_addstr(stdscr, 2, 2, f"{total} action(s) planifiée(s) — SIMULATION, rien n'est encore modifié", curses.A_DIM)

        y = 4
        for i, cat in enumerate(categories):
            count = len(by_category[cat])
            is_cat_selected = (i == cat_selected and expanded is None)
            attr = curses.A_REVERSE if is_cat_selected else curses.A_BOLD
            prefix = "▼" if expanded == cat else "▶"
            safe_addstr(stdscr, y, 4, f"{prefix} {cat} ({count} fichier(s))", attr)
            y += 1

            if expanded == cat:
                for j, action in enumerate(by_category[cat]):
                    is_file_selected = (j == file_selected)
                    attr = curses.A_REVERSE if is_file_selected else 0
                    tag = "[doublon] " if action.kind == "duplicate" else ""
                    line = f"    {tag}{action.src.name}"
                    safe_addstr(stdscr, y, 4, line, attr)
                    y += 1
                    if y >= curses.LINES - 4:
                        break

        help_y = curses.LINES - 3
        safe_addstr(stdscr, help_y, 2,
                    "↑↓ naviguer · Entrée déplier/replier · a appliquer · q retour", curses.A_DIM)
        stdscr.refresh()

        ch = stdscr.getch()

        if expanded is None:
            if ch in (curses.KEY_UP, ord("k")):
                cat_selected = (cat_selected - 1) % len(categories)
            elif ch in (curses.KEY_DOWN, ord("j")):
                cat_selected = (cat_selected + 1) % len(categories)
            elif ch in (curses.KEY_ENTER, 10, 13):
                expanded = categories[cat_selected]
                file_selected = 0
            elif ch == ord("a"):
                if confirm_apply(stdscr, total):
                    undo_log_path = target_dir / orgalazy.UNDO_LOG_FILENAME
                    orgalazy.apply_actions(state.actions, undo_log_path=undo_log_path)
                    show_message(stdscr, [f"{total} action(s) appliquée(s) avec succès.",
                                           f"Journal d'annulation : {undo_log_path}"], "Terminé")
                    state.actions = []
                    return
            elif ch in (ord("q"), 27):
                return
        else:
            n_files = len(by_category[expanded])
            if ch in (curses.KEY_UP, ord("k")):
                file_selected = (file_selected - 1) % n_files
            elif ch in (curses.KEY_DOWN, ord("j")):
                file_selected = (file_selected + 1) % n_files
            elif ch in (curses.KEY_ENTER, 10, 13, ord("q"), 27):
                expanded = None


def confirm_apply(stdscr, count: int) -> bool:
    stdscr.clear()
    safe_addstr(stdscr, 2, 2, f"Confirmer l'application de {count} action(s) ? (o/n)", curses.A_BOLD)
    stdscr.refresh()
    while True:
        ch = stdscr.getch()
        if ch in (ord("o"), ord("O"), ord("y"), ord("Y")):
            return True
        if ch in (ord("n"), ord("N"), 27):
            return False


def screen_undo(stdscr, state: AppState) -> None:
    result = prompt_text(stdscr, "Dossier concerné : ", state.target_dir_str)
    if result is None:
        return
    target_dir = Path(result).expanduser().resolve()
    undo_log_path = target_dir / orgalazy.UNDO_LOG_FILENAME

    if not undo_log_path.exists():
        show_message(stdscr, [f"Aucun journal d'annulation trouvé dans {target_dir}.",
                               "(Il faut avoir appliqué une exécution au préalable.)"], "Annulation")
        return

    try:
        restored, errors = orgalazy.undo_last_run(undo_log_path)
    except (OSError, ValueError) as e:
        show_message(stdscr, [f"Erreur lors de l'annulation : {e}"], "Annulation")
        return

    lines = [f"{restored} fichier(s) restauré(s) à leur emplacement d'origine."]
    if errors:
        lines.append("")
        lines.append("Erreurs rencontrées :")
        lines.extend(errors[:10])
    show_message(stdscr, lines, "Annulation terminée")


# --------------------------------------------------------------------------
# Boucle principale
# --------------------------------------------------------------------------

def main(stdscr) -> None:
    curses.curs_set(0)
    state = AppState()

    while True:
        choice = screen_main_menu(stdscr, state)

        if choice == "quit":
            break
        elif choice == "help":
            screen_help(stdscr)
        elif choice == "undo":
            screen_undo(stdscr, state)
        elif choice == "scan":
            if not screen_setup(stdscr, state):
                continue
            error = run_scan(stdscr, state)
            if error:
                show_message(stdscr, [error], "Erreur")
                continue
            screen_preview(stdscr, state)


if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        sys.exit(130)

#!/usr/bin/env python3
"""
orgalazy.py — Range automatiquement un dossier par catégorie (ou par date) et gère les doublons.

Conçu pour être :
- Autonome : uniquement la bibliothèque standard Python (aucune dépendance externe
  à installer/maintenir -> pas de risque de "cassage" dans 10 ans).
- Sûr par défaut : mode simulation (--dry-run implicite) actif tant qu'on ne demande
  pas --apply.
- Idempotent : relancer le script plusieurs fois ne casse rien.
- Traçable : toutes les actions réellement effectuées sont journalisées dans un fichier log.

Usage :
    python3 orgalazy.py ~/Downloads                     # simulation, affiche ce qui serait fait
    python3 orgalazy.py ~/Downloads --apply             # applique réellement
    python3 orgalazy.py ~/Downloads --apply --dedupe    # + déplace les doublons à part
    python3 orgalazy.py ~/Downloads --apply --by-date   # range dans des dossiers 2026-11
    python3 orgalazy.py ~/Downloads --apply --include-hidden
    python3 orgalazy.py ~/Downloads --undo          # annule les déplacements enregistrés
    python3 orgalazy.py ~/Downloads --config mon_config.json

Compatibilité Python 3.8+ (les annotations `X | None` sont rendues inoffensives
par `from __future__ import annotations`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

__version__ = "2.0.0"

# --------------------------------------------------------------------------
# Catégories par défaut (extension -> nom de dossier)
# Modifiable via un fichier de config JSON externe (--config).
# --------------------------------------------------------------------------

DEFAULT_CATEGORIES = {
    "Images": [
        "jpg", "jpeg", "png", "gif", "bmp", "svg", "webp", "heic", "heif",
        "tiff", "tif", "ico", "raw", "cr2", "nef", "arw",
    ],
    "Videos": [
        "mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v", "mpg",
        "mpeg", "3gp", "ts",
    ],
    "Audio": [
        "mp3", "wav", "flac", "aac", "ogg", "m4a", "wma", "opus", "aiff",
    ],
    "Documents": [
        "pdf", "doc", "docx", "odt", "txt", "rtf", "md", "tex", "pages",
    ],
    "Spreadsheets": [
        "xls", "xlsx", "ods", "csv", "tsv",
    ],
    "Presentations": [
        "ppt", "pptx", "odp", "key",
    ],
    "Archives": [
        "zip", "rar", "7z", "tar", "gz", "bz2", "xz", "tgz", "iso",
    ],
    "Code": [
        "py", "js", "ts", "html", "css", "c", "cpp", "h", "hpp", "java",
        "rs", "go", "rb", "php", "sh", "json", "yaml", "yml", "xml", "sql",
    ],
    "Executables": [
        "exe", "msi", "deb", "rpm", "appimage", "run", "bin",
    ],
    "Fonts": [
        "ttf", "otf", "woff", "woff2",
    ],
    "Ebooks": [
        "epub", "mobi", "azw", "azw3", "fb2",
    ],
}

DUPLICATES_DIRNAME = "_Doublons"
OTHERS_DIRNAME = "Autres"
LOG_FILENAME = ".orgalazy_log.txt"
UNDO_LOG_FILENAME = ".orgalazy_undo.json"
HASH_CHUNK_SIZE = 65536  # 64 Ko, bon compromis mémoire/vitesse

VALID_LAYOUTS = ("type", "date")


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

def validate_categories(data: object) -> dict[str, list[str]]:
    """
    Vérifie et normalise une config {catégorie: [extensions]}.

    On refuse les noms de catégorie qui pourraient sortir du dossier cible
    (ex: "../evil") ou écraser le dossier interne des doublons.
    """
    if not isinstance(data, dict):
        raise ValueError(
            "Le fichier de config doit contenir un objet JSON {catégorie: [extensions]}"
        )

    cleaned: dict[str, list[str]] = {}
    for category, extensions in data.items():
        if not isinstance(category, str) or not category.strip():
            raise ValueError("Chaque nom de catégorie doit être une chaîne non vide.")
        if category in (".", "..") or "/" in category or "\\" in category:
            raise ValueError(f"Nom de catégorie interdit (chemin) : {category!r}")
        if category == DUPLICATES_DIRNAME:
            raise ValueError(f"Le nom de catégorie {DUPLICATES_DIRNAME!r} est réservé.")
        if not isinstance(extensions, list) or not all(isinstance(e, str) for e in extensions):
            raise ValueError(
                f"Les extensions de la catégorie {category!r} doivent être une liste de chaînes."
            )
        cleaned[category] = [e.lower().lstrip(".") for e in extensions if e.strip()]

    return cleaned


def load_categories(config_path: Path | None) -> dict[str, list[str]]:
    """Charge les catégories depuis un JSON externe, sinon utilise les défauts."""
    if config_path is None:
        return DEFAULT_CATEGORIES
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return validate_categories(data)
    except Exception as e:
        logging.error(
            "Impossible de charger la config %s : %s. Utilisation des catégories par défaut.",
            config_path, e,
        )
        return DEFAULT_CATEGORIES


def build_extension_map(categories: dict[str, list[str]]) -> dict[str, str]:
    """Inverse le mapping catégorie->extensions en extension->catégorie."""
    ext_map: dict[str, str] = {}
    for category, extensions in categories.items():
        for ext in extensions:
            ext_map[ext.lower().lstrip(".")] = category
    return ext_map


# --------------------------------------------------------------------------
# Détection de doublons
# --------------------------------------------------------------------------

def file_hash(path: Path) -> str:
    """SHA-256 d'un fichier, lu par blocs pour ne pas saturer la RAM sur les gros fichiers."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(HASH_CHUNK_SIZE):
            h.update(chunk)
    return h.hexdigest()


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return float("inf")


def find_duplicates(files: list[Path]) -> list[list[Path]]:
    """
    Retourne une liste de groupes de doublons (fichiers de contenu identique).
    Optimisation : on ne hash que les fichiers qui partagent déjà la même taille,
    ce qui évite de hasher inutilement tout un disque.

    Dans chaque groupe, le premier fichier est l'original (le plus ancien).
    """
    by_size: dict[int, list[Path]] = defaultdict(list)
    for f in files:
        try:
            by_size[f.stat().st_size].append(f)
        except OSError as e:
            logging.warning("Impossible de lire la taille de %s : %s", f, e)

    duplicate_groups: list[list[Path]] = []
    for candidates in by_size.values():
        if len(candidates) < 2:
            continue
        by_hash: dict[str, list[Path]] = defaultdict(list)
        for f in candidates:
            try:
                by_hash[file_hash(f)].append(f)
            except OSError as e:
                logging.warning("Impossible de hasher %s : %s", f, e)
        for group in by_hash.values():
            if len(group) > 1:
                duplicate_groups.append(
                    sorted(group, key=lambda p: (_safe_mtime(p), str(p).casefold()))
                )
    return duplicate_groups


# --------------------------------------------------------------------------
# Utilitaires
# --------------------------------------------------------------------------

def _path_key(path: Path) -> str:
    """Clé normalisée pour comparer deux chemins de destination (sensible à l'OS)."""
    return os.path.normcase(os.path.abspath(str(path)))


def unique_destination(dest: Path, reserved: set[str] | None = None) -> Path:
    """
    Si `dest` existe déjà (nom en conflit, pas un doublon de contenu) ou a déjà
    été réservé par une autre action planifiée, ajoute un suffixe numérique pour
    ne jamais écraser un fichier existant.

    `reserved` contient les clés (voir `_path_key`) des destinations déjà
    attribuées ; la destination choisie y est ajoutée.
    """
    reserved = reserved if reserved is not None else set()

    def available(candidate: Path) -> bool:
        return not candidate.exists() and _path_key(candidate) not in reserved

    if available(dest):
        reserved.add(_path_key(dest))
        return dest

    stem, suffix, parent = dest.stem, dest.suffix, dest.parent
    counter = 1
    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        if available(candidate):
            reserved.add(_path_key(candidate))
            return candidate
        counter += 1


def category_for(path: Path, ext_map: dict[str, str], layout: str = "type") -> str:
    """Retourne le dossier de destination d'un fichier."""
    if layout == "date":
        try:
            timestamp = path.stat().st_mtime
        except OSError:
            return OTHERS_DIRNAME
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m")

    ext = path.suffix.lower().lstrip(".")
    return ext_map.get(ext, OTHERS_DIRNAME)


# --------------------------------------------------------------------------
# Sélection des fichiers
# --------------------------------------------------------------------------

def iter_candidate_files(
    target_dir: Path,
    categories: dict[str, list[str]],
    recursive: bool,
    exclude: set[str] | None = None,
    include_hidden: bool = False,
):
    """
    Énumère les fichiers à traiter, sans descendre dans les dossiers déjà
    organisés (catégories, _Doublons) ni dans les dossiers exclus.

    Les fichiers cachés (commençant par un point) sont ignorés par défaut :
    indispensable pour ne pas déplacer .bashrc, .config, etc. si on lance le
    script sur le dossier personnel.
    """
    exclude = exclude or set()
    organized_names = set(categories) | {OTHERS_DIRNAME, DUPLICATES_DIRNAME}
    skipped_names = {LOG_FILENAME, UNDO_LOG_FILENAME}

    for dirpath, dirnames, filenames in os.walk(target_dir, topdown=True):
        if recursive:
            dirnames[:] = [
                d for d in dirnames
                if d not in organized_names
                and d not in exclude
                and (include_hidden or not d.startswith("."))
            ]
        else:
            dirnames[:] = []

        for name in sorted(filenames, key=str.casefold):
            if name in skipped_names:
                continue
            if not include_hidden and name.startswith("."):
                continue
            path = Path(dirpath) / name
            try:
                if not path.is_file():
                    continue
            except OSError:
                continue
            yield path


# --------------------------------------------------------------------------
# Plan d'actions (calcul pur, sans effet de bord — réutilisé par le CLI et le TUI)
# --------------------------------------------------------------------------

@dataclass
class Action:
    kind: str          # "move" (catégorisation) ou "duplicate"
    src: Path
    dest: Path
    category: str       # nom de catégorie ("_Doublons" pour les doublons)


def plan_actions(
    target_dir: Path,
    categories: dict[str, list[str]],
    dedupe: bool,
    recursive: bool,
    exclude: set[str] | None = None,
    layout: str = "type",
    include_hidden: bool = False,
) -> list[Action]:
    """Calcule la liste des actions à effectuer, sans rien déplacer sur le disque."""
    if layout not in VALID_LAYOUTS:
        raise ValueError(f"Layout inconnu : {layout!r} (attendu : {', '.join(VALID_LAYOUTS)})")

    ext_map = build_extension_map(categories) if layout == "type" else {}
    all_files = sorted(
        iter_candidate_files(target_dir, categories, recursive, exclude, include_hidden),
        key=lambda p: str(p).casefold(),
    )

    actions: list[Action] = []
    reserved: set[str] = set()
    files_to_categorize = all_files

    if dedupe:
        duplicate_groups = find_duplicates(all_files)
        files_marked_as_duplicate: set[Path] = set()
        for group in duplicate_groups:
            _original, *dupes = group
            for dupe in dupes:
                files_marked_as_duplicate.add(dupe)
                dest_dir = target_dir / DUPLICATES_DIRNAME
                dest = unique_destination(dest_dir / dupe.name, reserved)
                actions.append(Action("duplicate", dupe, dest, DUPLICATES_DIRNAME))
        files_to_categorize = [f for f in all_files if f not in files_marked_as_duplicate]

    for f in files_to_categorize:
        category = category_for(f, ext_map, layout)
        dest_dir = target_dir / category
        if dest_dir == f.parent:
            continue
        dest = unique_destination(dest_dir / f.name, reserved)
        actions.append(Action("move", f, dest, category))

    return actions


def _read_undo_entries(undo_log_path: Path) -> list[dict]:
    """Lit le journal d'annulation existant, en ignorant silencieusement un fichier corrompu."""
    if not undo_log_path.exists():
        return []
    try:
        data = json.loads(undo_log_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("le journal n'est pas une liste")
        return [
            entry for entry in data
            if isinstance(entry, dict)
            and isinstance(entry.get("src"), str)
            and isinstance(entry.get("dest"), str)
        ]
    except (OSError, ValueError) as e:
        logging.warning("Journal d'annulation illisible (%s) : %s", undo_log_path, e)
        return []


def _write_undo_log(undo_log_path: Path, entries: list[dict]) -> None:
    """Écrit le journal de façon atomique (fichier temporaire puis remplacement)."""
    if not entries:
        return
    undo_log_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = undo_log_path.with_name(undo_log_path.name + ".tmp")
    tmp_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, undo_log_path)


def apply_actions(actions: list[Action], undo_log_path: Path | None = None) -> list[str]:
    """
    Exécute réellement les déplacements et complète le journal d'annulation.

    Une erreur sur un fichier n'interrompt pas les autres déplacements : les
    actions réussies restent annulables. Retourne la liste des erreurs.
    """
    executed: list[dict] = []
    errors: list[str] = []
    reserved: set[str] = set()

    for action in actions:
        try:
            action.dest.parent.mkdir(parents=True, exist_ok=True)
            if action.dest.exists() or _path_key(action.dest) in reserved:
                action.dest = unique_destination(action.dest, reserved)
            else:
                reserved.add(_path_key(action.dest))

            shutil.move(str(action.src), str(action.dest))
            executed.append({"src": str(action.src), "dest": str(action.dest)})
        except OSError as e:
            errors.append(f"{action.src} -> {action.dest} : {e}")

    if undo_log_path is not None and executed:
        # On conserve les entrées des exécutions précédentes non annulées :
        # une annulation restaure ainsi toutes les actions encore en place.
        previous = _read_undo_entries(undo_log_path)
        _write_undo_log(undo_log_path, previous + executed)

    return errors


def undo_last_run(undo_log_path: Path) -> tuple[int, list[str]]:
    """
    Rejoue le journal d'annulation à l'envers : déplace chaque fichier de `dest` vers `src`.
    Retourne (nombre de fichiers restaurés, liste des erreurs rencontrées).
    """
    try:
        entries = json.loads(undo_log_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"Journal d'annulation illisible : {e}") from e

    if not isinstance(entries, list):
        raise ValueError("Journal d'annulation invalide : une liste d'entrées est attendue.")
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("src"), str)
            or not isinstance(entry.get("dest"), str)
        ):
            raise ValueError("Journal d'annulation invalide : entrée sans 'src'/'dest'.")

    restored = 0
    errors: list[str] = []

    for entry in reversed(entries):
        src, dest = Path(entry["src"]), Path(entry["dest"])
        try:
            if not dest.exists():
                errors.append(f"Introuvable (déjà déplacé/supprimé ?) : {dest}")
                continue
            src.parent.mkdir(parents=True, exist_ok=True)
            final_src = unique_destination(src)  # au cas où un fichier a été recréé entretemps
            shutil.move(str(dest), str(final_src))
            restored += 1
        except OSError as e:
            errors.append(f"{dest} -> {src} : {e}")

    # Nettoie les dossiers de catégorie devenus vides après restauration
    dest_dirs = {Path(entry["dest"]).parent for entry in entries}
    for dest_dir in sorted(dest_dirs, key=lambda p: len(p.parts), reverse=True):
        try:
            if dest_dir.exists() and dest_dir.is_dir() and not any(dest_dir.iterdir()):
                dest_dir.rmdir()
        except OSError:
            pass

    if not errors:
        undo_log_path.unlink(missing_ok=True)

    return restored, errors


# --------------------------------------------------------------------------
# Cœur du programme (CLI) — s'appuie sur plan_actions() / apply_actions()
# --------------------------------------------------------------------------

def organize(
    target_dir: Path,
    categories: dict[str, list[str]],
    apply: bool,
    dedupe: bool,
    recursive: bool,
    exclude: set[str] | None = None,
    layout: str = "type",
    include_hidden: bool = False,
) -> list[str]:
    actions = plan_actions(
        target_dir, categories, dedupe, recursive, exclude, layout, include_hidden
    )

    if not actions:
        logging.info("Aucun fichier à traiter dans %s.", target_dir)
        return []

    counts = Counter(action.category for action in actions)
    logging.info(
        "Résumé : %s",
        ", ".join(f"{category}={count}" for category, count in sorted(counts.items())),
    )

    for action in actions:
        label = "DÉPLACER (doublon)" if action.kind == "duplicate" else "DÉPLACER"
        logging.info("%s : %s -> %s", label, action.src, action.dest)

    moved_count = sum(1 for a in actions if a.kind == "move")
    duplicate_count = sum(1 for a in actions if a.kind == "duplicate")

    errors: list[str] = []
    if apply:
        undo_log_path = target_dir / UNDO_LOG_FILENAME
        errors = apply_actions(actions, undo_log_path=undo_log_path)
        for error in errors:
            logging.error("Échec : %s", error)

    mode = "APPLIQUÉ" if apply else "SIMULATION (aucun fichier modifié — relancer avec --apply)"
    suffix = f" — {len(errors)} échec(s)" if errors else ""
    logging.info(
        "Terminé [%s] : %d fichier(s) classé(s), %d doublon(s) traité(s)%s.",
        mode, moved_count, duplicate_count, suffix,
    )
    return errors


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def setup_logging(target_dir: Path) -> None:
    root = logging.getLogger()
    if getattr(root, "_orgalazy_configured", False):
        return

    log_path = target_dir / LOG_FILENAME
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    root.setLevel(logging.INFO)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    try:
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as e:
        logging.warning("Impossible d'écrire le log dans %s : %s", log_path, e)

    root._orgalazy_configured = True  # type: ignore[attr-defined]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Range automatiquement un dossier par catégorie (ou par date) et gère les doublons.",
    )
    parser.add_argument("directory", type=str, help="Dossier à organiser (ex: ~/Downloads)")
    action_group = parser.add_mutually_exclusive_group()
    action_group.add_argument(
        "--apply", action="store_true",
        help="Applique réellement les changements (par défaut : simulation uniquement).",
    )
    action_group.add_argument(
        "--undo", action="store_true",
        help="Annule les déplacements enregistrés dans le journal d'annulation du dossier.",
    )
    parser.add_argument(
        "--dedupe", action="store_true",
        help="Détecte les doublons (contenu identique) et les déplace dans le dossier _Doublons.",
    )
    parser.add_argument(
        "--recursive", action="store_true",
        help="Parcourt aussi les sous-dossiers (par défaut : dossier racine uniquement).",
    )
    parser.add_argument(
        "--by-date", action="store_true",
        help="Range par mois de modification (dossiers 2026-11) au lieu de par type de fichier.",
    )
    parser.add_argument(
        "--include-hidden", action="store_true",
        help="Traite aussi les fichiers et dossiers cachés (ignorés par défaut pour éviter .bashrc, .config, etc.).",
    )
    parser.add_argument(
        "--exclude", type=str, nargs="+", default=[],
        help="Nom(s) de sous-dossier(s) à ignorer complètement, ex: --exclude ProjetX Archive",
    )
    parser.add_argument(
        "--config", type=str, default=None,
        help="Chemin vers un fichier JSON personnalisé {\"Catégorie\": [\"ext1\", \"ext2\"]}.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    target_dir = Path(args.directory).expanduser().resolve()
    if not target_dir.exists():
        print(f"Erreur : le dossier {target_dir} n'existe pas.", file=sys.stderr)
        return 1
    if not target_dir.is_dir():
        print(f"Erreur : {target_dir} n'est pas un dossier.", file=sys.stderr)
        return 1

    config_path = Path(args.config).expanduser().resolve() if args.config else None
    if config_path is not None and not config_path.is_file():
        print(f"Erreur : le fichier de config {config_path} n'existe pas.", file=sys.stderr)
        return 1

    undo_log_path = target_dir / UNDO_LOG_FILENAME
    if args.undo and not undo_log_path.exists():
        print(f"Erreur : aucun journal d'annulation dans {target_dir}.", file=sys.stderr)
        return 1

    setup_logging(target_dir)
    categories = load_categories(config_path)

    logging.info("=== orgalazy.py %s — démarrage (%s) ===", __version__, datetime.now().isoformat(timespec="seconds"))
    logging.info("Dossier cible : %s", target_dir)

    if args.undo:
        try:
            restored, undo_errors = undo_last_run(undo_log_path)
        except (OSError, ValueError) as e:
            logging.error("Annulation impossible : %s", e)
            return 1
        logging.info("Annulation : %d fichier(s) restauré(s).", restored)
        for error in undo_errors:
            logging.error("Échec : %s", error)
        return 1 if undo_errors else 0

    logging.info(
        "Mode : %s | layout=%s | dedupe=%s | recursive=%s | hidden=%s | exclude=%s",
        "APPLY" if args.apply else "DRY-RUN",
        "date" if args.by_date else "type",
        args.dedupe, args.recursive, args.include_hidden,
        args.exclude or "aucun",
    )

    try:
        errors = organize(
            target_dir=target_dir,
            categories=categories,
            apply=args.apply,
            dedupe=args.dedupe,
            recursive=args.recursive,
            exclude=set(args.exclude),
            layout="date" if args.by_date else "type",
            include_hidden=args.include_hidden,
        )
    except KeyboardInterrupt:
        logging.warning("Interrompu par l'utilisateur.")
        return 130
    except Exception as e:
        logging.exception("Erreur inattendue : %s", e)
        return 1

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

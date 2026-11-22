# Orgalazy

> Range automatiquement un dossier par type de fichier (ou par date), sans dépendance et sans jamais supprimer vos fichiers.

![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![Tests](https://github.com/XIAN005/orgalazy/actions/workflows/tests.yml/badge.svg)
![License](https://img.shields.io/badge/license-MIT-green)

**Orgalazy** est un petit utilitaire en ligne de commande — avec une interface texte (TUI) — écrit uniquement avec la bibliothèque standard de Python. Il déplace les fichiers encombrants d'un dossier (`~/Downloads`, un bureau, etc.) dans des sous-dossiers clairs : `Images`, `Documents`, `Videos`, `Archives`…

Le mode **simulation** est actif par défaut : rien n'est déplacé tant que vous n'ajoutez pas `--apply`.

---

## Sommaire

- [Fonctionnalités](#fonctionnalités)
- [Sécurité](#sécurité)
- [Prérequis](#prérequis)
- [Installation](#installation)
- [Utilisation rapide](#utilisation-rapide)
- [Options de la ligne de commande](#options-de-la-ligne-de-commande)
- [Ranger par date](#ranger-par-date)
- [Doublons](#doublons)
- [Annuler une exécution](#annuler-une-exécution)
- [Configuration personnalisée](#configuration-personnalisée)
- [Interface TUI](#interface-tui)
- [Tests](#tests)
- [Structure du projet](#structure-du-projet)
- [Licence](#licence)

---

## Fonctionnalités

- **Classement par type** : images, vidéos, audio, documents, tableurs, archives, code, polices, ebooks…
- **Classement par date** avec `--by-date` : dossiers `2026-11`, `2026-10`, etc.
- **Détection de doublons** par empreinte SHA-256, sans suppression : les copies sont déplacées dans `_Doublons`.
- **Mode simulation par défaut** : aperçu complet avant toute modification.
- **Annulation** des déplacements grâce à un journal `.orgalazy_undo.json`.
- **Aucun écrasement** : en cas de conflit de nom, un suffixe est ajouté (`photo (1).jpg`).
- **Fichiers cachés ignorés par défaut** : indispensable si vous lancez l'outil sur votre dossier personnel.
- **Aucune dépendance externe** : un seul fichier Python à copier ou cloner.
- **Interface TUI** en curses pour naviguer, prévisualiser et appliquer.

## Sécurité

Orgalazy est conçu pour être prudent :

| Garantie | Détail |
|---|---|
| Rien n'est supprimé | Les doublons sont **déplacés**, jamais effacés. |
| Rien n'est écrasé | Une destination existante devient `nom (1).ext`, `nom (2).ext`, etc. |
| Simulation par défaut | Sans `--apply`, le programme affiche seulement le plan d'action. |
| Fichiers cachés protégés | `.bashrc`, `.config`, `.cache`… sont ignorés sauf avec `--include-hidden`. |
| Erreurs non bloquantes | Un fichier illisible n'empêche pas les autres déplacements. |
| Journal d'annulation | Les déplacements réussis restent annulables, même en cas d'échec partiel. |
| Configuration validée | Les noms de catégorie contenant des chemins (`../`) sont refusés. |

> Conseil : lancez toujours une première fois **sans** `--apply`, puis relisez l'aperçu.

## Prérequis

- Python **3.8 ou plus récent**
- Linux ou macOS pour la TUI (`curses`). La ligne de commande fonctionne aussi sous Windows.
- Aucun paquet à installer.

## Installation

```bash
git clone https://github.com/XIAN005/orgalazy.git
cd orgalazy
chmod +x orgalazy.py orgalazy_tui.py

python3 orgalazy.py --version
```

Vous pouvez aussi simplement télécharger `orgalazy.py` et le lancer directement :

```bash
python3 orgalazy.py ~/Downloads
```

Pour l'utiliser comme commande globale :

```bash
mkdir -p ~/.local/bin
ln -s "$PWD/orgalazy.py" ~/.local/bin/orgalazy
orgalazy ~/Downloads
```

## Utilisation rapide

```bash
# 1. Simulation : affiche ce qui serait déplacé, ne touche à rien
python3 orgalazy.py ~/Downloads

# 2. Application réelle
python3 orgalazy.py ~/Downloads --apply

# 3. Avec détection des doublons
python3 orgalazy.py ~/Downloads --apply --dedupe

# 4. Ranger par mois de modification
python3 orgalazy.py ~/Downloads --apply --by-date

# 5. Parcourir les sous-dossiers en excluant certains dossiers
python3 orgalazy.py ~/Documents --apply --recursive --exclude Projets Archives

# 6. Inclure les fichiers cachés (à utiliser en connaissance de cause)
python3 orgalazy.py ~/Downloads --apply --include-hidden
```

Un journal lisible est écrit dans le dossier cible : `.orgalazy_log.txt`.

## Options de la ligne de commande

```text
python3 orgalazy.py DOSSIER [options]
```

| Option | Effet |
|---|---|
| `--apply` | Applique réellement les déplacements. Sans cette option : simulation. |
| `--undo` | Annule les déplacements enregistrés dans le journal du dossier. |
| `--dedupe` | Détecte les doublons de contenu et les déplace dans `_Doublons`. |
| `--recursive` | Parcourt aussi les sous-dossiers. |
| `--by-date` | Range par mois (`AAAA-MM`) au lieu de ranger par type. |
| `--include-hidden` | Traite aussi les fichiers et dossiers cachés. |
| `--exclude NOM [NOM ...]` | Ignore complètement les sous-dossiers indiqués. |
| `--config FICHIER.json` | Utilise une configuration de catégories personnalisée. |
| `--version` | Affiche la version. |

`--apply` et `--undo` sont incompatibles.

## Ranger par date

```bash
python3 orgalazy.py ~/Pictures --by-date          # aperçu
python3 orgalazy.py ~/Pictures --by-date --apply  # application
```

Les fichiers sont regroupés selon leur date de dernière modification :

```text
Pictures/
├── 2026-11/
├── 2026-10/
└── 2026-09/
```

Relancer le script sur un dossier déjà rangé par date ne déplace pas les fichiers à nouveau.

## Doublons

```bash
python3 orgalazy.py ~/Downloads --dedupe
```

- Deux fichiers sont considérés identiques s'ils ont le **même contenu** (SHA-256), pas seulement le même nom.
- Le plus ancien (date de modification) est conservé à sa place.
- Les copies sont déplacées dans `_Doublons/`, jamais supprimées.
- Le dossier `_Doublons` est ignoré lors des exécutions suivantes.

## Annuler une exécution

```bash
python3 orgalazy.py ~/Downloads --undo
```

Le journal `.orgalazy_undo.json` contient les couples source/destination. L'annulation restaure les fichiers dans leur dossier d'origine et supprime les dossiers de catégorie devenus vides.

Le journal est **cumulatif** : si vous appliquez plusieurs exécutions sans annuler, `--undo` restaure l'ensemble des déplacements encore en place.

## Configuration personnalisée

Le fichier [`examples/config.json`](examples/config.json) montre comment définir ses propres catégories :

```json
{
  "Images": ["jpg", "jpeg", "png", "gif", "webp", "svg"],
  "Documents": ["pdf", "docx", "odt", "txt", "md"],
  "Archives": ["zip", "tar", "gz", "7z"],
  "Code": ["py", "js", "ts", "html", "css", "json"],
  "3D": ["blend", "obj", "fbx", "stl"],
  "Projets": ["psd", "ai", "fig"]
}
```

```bash
python3 orgalazy.py ~/Downloads --config examples/config.json
```

Les clés sont les noms de dossiers, les valeurs sont les extensions (avec ou sans point). Si le fichier est invalide, Orgalazy revient aux catégories par défaut et l'indique dans le journal.

## Interface TUI

```bash
python3 orgalazy_tui.py
```

L'interface permet de :

1. choisir le dossier cible ;
2. activer le mode récursif et la détection de doublons ;
3. exclure des dossiers et charger une configuration JSON ;
4. prévisualiser les actions par catégorie ;
5. appliquer avec la touche `a` après confirmation ;
6. annuler la dernière exécution depuis le menu principal.

| Touche | Action |
|---|---|
| `↑` `↓` ou `j` `k` | Se déplacer |
| `Entrée` | Valider / ouvrir une catégorie |
| `Espace` | Cocher / décocher une option |
| `a` | Appliquer le plan affiché |
| `q` / `Échap` | Retour / quitter |

La TUI utilise le classement par type. Pour `--by-date` et `--include-hidden`, utilisez la ligne de commande.

## Tests

La suite de tests ne touche qu'à des dossiers temporaires :

```bash
python3 -m unittest -v test_orgalazy.py
```

Elle couvre notamment : le classement, les collisions de noms, les doublons, l'annulation, les échecs partiels, les fichiers cachés et le mode par date.

Une intégration continue GitHub Actions exécute ces tests sur plusieurs versions de Python à chaque `push` et `pull request`.

## Structure du projet

```text
.
├── orgalazy.py                  # CLI + logique de classement
├── orgalazy_tui.py              # interface texte (curses)
├── test_orgalazy.py             # tests unitaires (unittest)
├── examples/
│   └── config.json              # exemple de configuration
├── .github/
│   └── workflows/
│       └── tests.yml            # intégration continue
├── .gitignore
├── LICENSE
└── README.md
```

## Licence

Distribué sous licence [MIT](LICENSE). Vous pouvez l'utiliser, le modifier et le redistribuer librement.

---

## English summary

Orgalazy is a dependency-free Python CLI and TUI that sorts files by type or modification month. It previews changes by default, never deletes anything, detects duplicates via SHA-256, avoids overwriting files, and supports undo. Run it without `--apply` to see the plan first.

#!/bin/bash
# Installation de CE greffon dans le venv Spyder d'une machine SmartOS (mecanisme .pth
# "editable" : le greffon reste dans ce depot, seul un pointeur part dans site-packages).
# Sorti d'installation_SmartPythonEditor.sh le 08/08/2026 (demande utilisateur : les notes et
# verifications de chaque greffon vivent dans SON depot) - le script SmartOS n'est plus qu'un
# appel d'une ligne vers ce fichier. L'installation DISTRIBUEE (install.sh du fork
# SmartPythonEditor) n'utilise PAS ce script : elle passe par pip.
#
# Usage : installer_dans_venv.sh <python du venv Spyder> <sans_tests true|false> \
#                                <install_spyder_plugin.py> <spyder_config_set.py> <spyder.ini>
set -u
SPYDER_PYTHON="${1:?python du venv Spyder}"
SANS_TESTS="${2:-true}"
OUTIL_INSTALL="${3:?chemin de install_spyder_plugin.py}"
OUTIL_CONFIG="${4:?chemin de spyder_config_set.py}"
SPYDER_INI="${5:?chemin du spyder.ini}"
PLUGIN_DIR="$(cd "$(dirname "$(realpath "${BASH_SOURCE[0]}")")/.." && pwd)"

# =============================================================================
# Plugin Spyder "Claude" — les instances de Claude Code dans un dock
# =============================================================================
# Installe le greffon versionne dans ce depot (spyder_claude/.
#
# CE QU'IL EST. Un panneau a onglets ou chaque onglet est une instance de Claude Code
# lancee par `claude -r`, dans le repertoire courant de Spyder. Il HERITE du greffon
# Terminal natif (meme moteur Konsole, meme cadre, meme bouton « + ») et n'ajoute que ce
# qui lui est propre : la commande, l'identite de session, la couleur d'etat et la
# mosaique quand le panneau est agrandi.
#
# ⚠ IL DEPEND DU GREFFON TERMINAL NATIF, par un simple import Python — pas par pip (le
# venv fige de Spyder n'a pas setuptools, cf. install_spyder_plugin.py). Ce script verifie
# donc sa presence AVANT d'installer quoi que ce soit : sans lui, le greffon Claude
# s'installerait et disparaitrait ensuite en silence, Spyder avalant les exceptions de
# chargement de greffon.
#
# ⚠ ET IL DEPEND D'UNE VERSION A JOUR DE claude-window.sh. Le comportement des instances
# (fond rouge/vert, arbitrage du clavier) n'est pas implemente dans le greffon : il vient
# du hook, qui doit savoir reconnaitre une session hebergee par un panneau. Le test
# d'interoperabilite ci-dessous le verifie sur la copie DEPLOYEE, celle qui tourne
# reellement — une source du depot a jour et un hook deploye perime donnerait un panneau
# sans couleurs, sans un message d'erreur.
#
# Invocation : installation_SmartPythonEditor.sh --greffon claude
# =============================================================================

# PAS de "set -e" : error_handler.sh installe un trap ERR interactif, incompatible avec
# errexit (cf. l'explication detaillee en tete de installation_SmartPythonEditor.sh).

if [ ! -f "$PLUGIN_DIR/pyproject.toml" ]; then
  echo "ERREUR : plugin introuvable dans $PLUGIN_DIR - abandon." >&2
  exit 1
fi

if [ ! -x "$SPYDER_PYTHON" ]; then
  echo "ERREUR : $SPYDER_PYTHON introuvable." >&2
  echo "         Installez d'abord Spyder (./installation_SmartPythonEditor.sh)." >&2
  exit 1
fi
echo "Environnement Spyder cible : $SPYDER_PYTHON"

# --- Prerequis : le moteur de terminal partage -------------------------------
# Le moteur Konsole n'est pas un greffon mais une BIBLIOTHEQUE, importee par les deux
# panneaux a terminaux. Le prerequis est donc SYMETRIQUE — aucun greffon ne depend de
# l'autre — la ou le greffon Claude dependait autrefois du greffon Terminal.
# Depuis le 09/08/2026 le moteur vit dans le greffon Terminal (spyder_konsole,
# dependance pip de ce greffon-ci - fusion du paquet smartos_konsole sur decision
# utilisateur) : le prerequis est donc ce greffon-la, et son installateur porte toute la
# logique du binding (prerequis pacman, alignement PySide6/Qt systeme, build.sh).
# La condition porte sur l'ETAT FINAL (moteur importable ET binding construit), pas sur le
# seul import : conditionne a l'import, un moteur installe SANS binding restait
# definitivement en l'etat (constate le 08/08/2026 au soir).
echo
echo "--- Prerequis : greffon Terminal natif (porte le moteur Konsole) ---"
if ! QT_QPA_PLATFORM=offscreen "$SPYDER_PYTHON" -c \
     "import qtermwidget; import spyder_konsole.konsole_view" 2>/dev/null; then
  bash "$(dirname "$PLUGIN_DIR")/spyder_konsole/outils_smartos/installer_dans_venv.sh" "$SPYDER_PYTHON" "$SANS_TESTS" "$OUTIL_INSTALL" "$OUTIL_CONFIG" "$SPYDER_INI" || {
    echo "ERREUR : le greffon Terminal natif (moteur Konsole) n'a pas pu etre installe." >&2
    echo "         Le panneau n'a alors ni terminal ni shell." >&2
    exit 1; }
fi
echo "Moteur Konsole present."

# --- Tests --------------------------------------------------------------------
if [ "$SANS_TESTS" = false ]; then
  echo
  echo "--- Tests du greffon ---"
  # 1. Le protocole d'etat partage avec claude-window.sh : Python pur, pas de Qt.
  python3 "$PLUGIN_DIR/tests/test_etat_instances.py" \
    || { echo "ERREUR : les tests du registre d'etat echouent." >&2; exit 1; }
  # 1 bis. Le protocole de consommation partage avec claude-statusline.sh : meme nature,
  #    Python pur (31/07/2026 — jauges et tachymetres du panneau).
  python3 "$PLUGIN_DIR/tests/test_usage.py" \
    || { echo "ERREUR : les tests du registre de consommation echouent." >&2; exit 1; }
  # 2. La mosaique : offscreen, sans Spyder ni moteur de terminal.
  QT_QPA_PLATFORM=offscreen "$SPYDER_PYTHON" "$PLUGIN_DIR/tests/test_mosaique.py" \
    || { echo "ERREUR : les tests de la mosaique echouent." >&2; exit 1; }
  # 2 bis. Les widgets de consommation (cadran, bande des jauges) : offscreen, sans
  #    Spyder — meme discipline que la mosaique.
  QT_QPA_PLATFORM=offscreen "$SPYDER_PYTHON" "$PLUGIN_DIR/tests/test_compteurs.py" \
    || { echo "ERREUR : les tests des widgets de consommation echouent." >&2; exit 1; }
  # 2 ter. LE PANNEAU LUI-MEME, monte hors de Spyder. Ce banc n'existait pas avant le
  #    31/07/2026, et son absence avait laisse passer quatre defauts muets (cf. son
  #    en-tete). C'est le seul qui eprouve la classe qui assemble tout le reste — y
  #    compris, depuis le meme jour, la greffe du tachymetre sur un vrai onglet Spyder.
  QT_QPA_PLATFORM=offscreen "$SPYDER_PYTHON" "$PLUGIN_DIR/tests/test_panneau.py" \
    || { echo "ERREUR : les tests du panneau echouent." >&2; exit 1; }
  # 3. Les jeux de couleurs d'etat, vus par le MOTEUR : c'est le point ou le dispositif
  #    peut echouer sans rien dire (cache des jeux de couleurs de qtermwidget).
  QT_QPA_PLATFORM=offscreen "$SPYDER_PYTHON" "$PLUGIN_DIR/tests/test_schemas_detat.py" \
    || { echo "ERREUR : les tests des jeux de couleurs d'etat echouent." >&2; exit 1; }
  # 4. L'interoperabilite avec le hook DEPLOYE — le seul test qui traverse la frontiere
  #    entre les deux programmes. Non fatal : le hook peut n'avoir pas encore ete
  #    redeploye (installation_Claude.sh), et le greffon fonctionne alors sans couleurs.
  HOOK="$HOME/.claude/hooks/claude-window.sh" \
    bash "$PLUGIN_DIR/tests/test_hook_panneau.sh" || {
    echo "ATTENTION : le hook deploye ne reconnait pas les sessions de panneau." >&2
    echo "            Relancer ./installation_Claude.sh pour redeployer les hooks," >&2
    echo "            sinon les onglets resteront sans couleur d'etat." >&2; }
  # 4 bis. Meme interoperabilite, cote consommation. Egalement non fatal : le script
  #    statusLine peut n'avoir pas encore ete redeploye lui non plus.
  SCRIPT="$HOME/.claude/hooks/claude-statusline.sh" \
    bash "$PLUGIN_DIR/tests/test_statusline.sh" || {
    echo "ATTENTION : le script statusLine deploye ne produit pas le fichier attendu." >&2
    echo "            Relancer ./installation_Claude.sh pour le redeployer," >&2
    echo "            sinon les jauges du panneau resteront a vide." >&2; }
fi

# --- Verification de chargement ----------------------------------------------
echo
echo "--- Chargement du greffon ---"
QT_QPA_PLATFORM=offscreen PYTHONPATH="$PLUGIN_DIR" "$SPYDER_PYTHON" -c "
from qtpy.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

from spyder_claude.spyder.plugin import GreffonClaude
assert GreffonClaude.NAME == 'claude_pane'

# L'icone est le seul element visible du greffon avant qu'on l'ouvre : un nom qtawesome
# invalide leve dans setup(), et Spyder AVALE cette exception - le greffon serait
# simplement absent du menu, sans un mot.
import qtawesome as qta
assert not qta.icon('mdi.robot-outline').isNull()
assert not qta.icon('mdi.circle-medium').isNull()

# L'INDEPENDANCE DES AFFICHAGES SE VERIFIE ICI, et c'est le seul endroit ou elle se
# verrait rompre : une reprise de code entre les deux PANNEAUX jumeaux reviendrait sans
# bruit. Depuis le 09/08/2026 la frontiere est le panneau, pas le paquet : le MOTEUR
# (spyder_konsole.konsole_view) est une dependance assumee, mais aucun module
# d'affichage de l'autre greffon (spyder_konsole.spyder.*) ne doit etre tire.
import sys
assert not [m for m in sys.modules if m.startswith('spyder_konsole.spyder')], \
    'le greffon Claude ne doit pas importer le panneau du greffon Terminal'

from spyder_konsole.konsole_view import VueKonsole, preparer_schema
assert hasattr(VueKonsole, 'appliquer_schema')
import inspect
assert 'nom_derive' in inspect.signature(preparer_schema).parameters
from spyder_claude.spyder.main_widget import PanneauClaude
assert 'environnement' in inspect.signature(PanneauClaude.ouvrir_terminal).parameters

from spyder_konsole.konsole_view import DISPONIBLE
print('OK  greffon Claude chargeable ; moteur Konsole :',
      'present' if DISPONIBLE else 'ABSENT (binding a construire)')
" || { echo "ERREUR : le greffon ne se charge pas - installation annulee." >&2; exit 1; }

# --- Installation ------------------------------------------------------------
echo
# ⚠ PAS de "pip install" ici : le venv pyenv de Spyder est construit a partir d'un
# requirements fige qui NE CONTIENT PAS setuptools (cf. l'en-tete de
# install_spyder_plugin.py).
python3 "$OUTIL_INSTALL" \
    "$PLUGIN_DIR" "$SPYDER_PYTHON" || {
  echo "ERREUR : l'installation du plugin a echoue." >&2; exit 1; }

echo
echo "Plugin 'Claude' installe."

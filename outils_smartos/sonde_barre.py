#!/usr/bin/env python3
"""Sonde de validation de la barre de defilement emulee (spyder_claude/defilement.py) sur le
VRAI Claude Code — reserve du Superviseur du 19/10/2026 : les tests du faux terminal valident
le modele contre lui-meme, seule une mesure sur Claude dit si la regle tient.

Ce qu'elle fait, sans Spyder : la vraie VueKonsole (hors ecran) et la vraie barre, branchees
comme dans le greffon, lancent le lanceur du compte isole dans le rendu par defaut (plein
ecran). Claude ecrit les nombres de 1 a 250, un par ligne : un nombre visible n au rang r donne
la VRAIE position, independamment du modele — d = r + (N - n) - R, ou N est le dernier nombre
de la reponse et R son rang une fois en bas. Le plus grand nombre visible ne suffit pas : sous
N restent des lignes non numerotees, et pres du bas N reste visible alors qu'on a remonte. Chaque essai pilote la barre comme le ferait la souris, puis ecrit dans le
JSON ce que la barre CROIT (d, T, haut connu) a cote de ce qui est OBSERVE.

    QT_API=pyside6 python sonde_barre.py [fichier_json]

Essais : paquets envoyes d'un seul jet, sauts par pages (etalonnage compris), inversion, Ctrl+End puis remontee, detection du
haut puis redescente, Entree tapee en haut (doit redescendre avant d'envoyer), et une sortie
qui arrive pendant qu'on est remonte.
"""

import json
import os
import re
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_API", "pyside6")
ICI = os.path.dirname(os.path.abspath(__file__))
for chemin in (os.path.join(ICI, ".."), os.path.join(ICI, "..", "..", "spyder_konsole"),
               os.path.join(ICI, "..", "..", "spyder_konsole", "qtermwidget_binding", "build")):
    sys.path.insert(0, chemin)

from qtpy.QtCore import QCoreApplication, QEvent, Qt  # noqa: E402
from qtpy.QtGui import QKeyEvent  # noqa: E402
from qtpy.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

from spyder_claude.defilement import BarreDefilementEmulee  # noqa: E402
from spyder_konsole.konsole_view import VueKonsole  # noqa: E402

DOSSIER = "/DATA/Python/FORKS/SmartPythonEditor_generator"
SORTIE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(DOSSIER, "sonde_barre.json")
CONSIGNE = ("Test de defilement, reponds sans outil : ecris les nombres de 1 a 250, un par "
            "ligne, sans rien d'autre, puis le bloc ===== SYNTHESE VOCALE ===== avec le seul "
            "mot fini.")
SECONDE = ("Meme test : ecris les nombres de 1001 a 1060, un par ligne, sans rien d'autre, "
           "puis le bloc ===== SYNTHESE VOCALE ===== avec le seul mot fini.")
NOMBRE = re.compile(r"^\s*(\d+)\b")

vue = VueKonsole(couleur_fond="#19232D", couleur_texte="#DFE1E2")
barre = BarreDefilementEmulee(vue)
vue.resize(1100, 800)
vue.show()
derniere = [time.monotonic()]
vue.sig_sortie.connect(lambda: derniere.__setitem__(0, time.monotonic()))
fini = [False]
vue.sig_termine.connect(lambda _code: fini.__setitem__(0, True))
vue.demarrer(["sudo", os.path.expanduser("~/.scripts/claude_compte_isole.sh"), DOSSIER],
             repertoire=DOSSIER)


def attendre(calme, plafond):
    """Rend quand la sortie s'est tue `calme` s et que la barre n'a plus rien en vol."""
    debut = time.monotonic()
    while time.monotonic() - debut < plafond and not fini[0]:
        QCoreApplication.processEvents()
        time.sleep(0.02)
        if (time.monotonic() - derniere[0] >= calme and time.monotonic() - debut >= calme
                and barre._verification is None and barre._paquet is None
                and barre._cible == barre.modele.d):
            return True
    return False


def reperes(lignes, plage):
    """(rang, nombre) du plus grand nombre de `plage` en tete de ligne, question (ligne 0) exceptee."""
    trouves = [(int(m.group(1)), r) for r, m in enumerate(map(NOMBRE.match, lignes))
               if r and m and plage[0] <= int(m.group(1)) <= plage[1]]
    return None if not trouves else max(trouves)[::-1]


def observe(entree):
    """d vrai d'un essai, des que le bas de sa reponse est connu."""
    if entree["repere"] and bas[0]:
        (r, n), (R, N) = entree["repere"], bas[0]
        entree["observe_d"] = r + (N - n) - R
        entree["juste"] = entree["observe_d"] == entree["modele_d"]


def taper(touche, texte=""):
    """Une touche comme au clavier : par le filtre d'evenements, donc vue par la barre."""
    cible = vue.widgets_du_terminal()[0].focusProxy() or vue.widgets_du_terminal()[0]
    for type_ in (QEvent.KeyPress, QEvent.KeyRelease):
        QApplication.sendEvent(cible, QKeyEvent(type_, touche, Qt.NoModifier, texte))


rapport = {"debut": time.strftime("%F %T"), "essais": []}
bas = [None]                      # (rang, nombre) du dernier nombre, une fois en bas
plage = [(1, 250)]


def essai(nom, action, calme=0.8, plafond=20):
    action()
    calme_atteint = attendre(calme, plafond)
    ecran = vue.texte_ecran()
    m = barre.modele
    entree = {"essai": nom, "calme": calme_atteint, "cible": barre._cible,
              "modele_d": m.d, "modele_T": m.T, "haut_connu": m.haut_connu,
              "inversions": m.inversions, "page_claude": barre._page_claude, "repere": reperes(ecran, plage[0]),
              "observe_d": None, "juste": False, "ecran": ecran}
    observe(entree)
    rapport["essais"].append(entree)
    print(f"{nom:34s} modele {m.d:4d} (T {m.T:4d}{', haut' if m.haut_connu else ''})"
          f"  observe {entree['observe_d']}  {'OK' if entree['juste'] else 'ECART'}",
          flush=True)


try:
    rapport["demarrage_calme"] = attendre(4, 90)
    rapport["barre_active"] = barre._actif
    vue.envoyer(CONSIGNE)
    attendre(1, 5)
    taper(Qt.Key_Return, "\r")
    attendre(1, 10)
    rapport["reponse_calme"] = attendre(6, 240)
    rapport["barre_active_apres_reponse"] = barre._actif
    bas[0] = reperes(vue.texte_ecran(), plage[0])
    rapport["bas"] = bas[0]

    essai("paquet de 10 d'un seul jet", lambda: barre.aller_a(10))
    essai("redescente a 4 (inversion)", lambda: barre.aller_a(4))
    essai("remontee a 15 (inversion)", lambda: barre.aller_a(15))
    essai("Ctrl+End (cible 0)", lambda: barre.aller_a(0))
    essai("3 crans juste apres Ctrl+End", lambda: barre.aller_a(3))
    essai("jusqu'au haut", lambda: barre.aller_a(10 ** 6), plafond=120)
    essai("redescente a haut - 5", lambda: barre.aller_a(barre.modele.T - 5))
    essai("saut a 150 (PgDn puis molette)", lambda: barre.aller_a(150))
    # ecart d'une ligne sur 150 -> 20 (3e sonde, 19/10/2026) : Ctrl+End, PgUp, 2 crans. On isole.
    essai("Ctrl+End depuis 150", lambda: barre.aller_a(0))
    essai("une page seule depuis le bas", lambda: barre.aller_a(barre._page_claude or 18))
    essai("puis 2 crans", lambda: barre.aller_a(barre.modele.d + 2))
    essai("retour a 150", lambda: barre.aller_a(150))
    essai("remontee a 20 avant Entree", lambda: barre.aller_a(20))
    # Entree tapee remonte : la barre doit redescendre AVANT que la touche parte. On
    # remonte ensuite pendant que la seconde reponse arrive ; sa verite n'est connue
    # qu'une fois revenu en bas (nouveau dernier nombre), d'ou le recalage a posteriori.
    vue.envoyer(SECONDE)
    plage[0], bas[0] = (1001, 1060), None
    attendre(1, 5)
    taper(Qt.Key_Return, "\r")
    rapport["d_juste_apres_entree"] = barre.modele.d
    attendre(1.5, 10)
    essai("remontee de 8 pendant la sortie", lambda: barre.aller_a(8), calme=6, plafond=240)
    pendant = rapport["essais"][-1]
    essai("retour en bas apres la seconde", lambda: barre.aller_a(0))
    bas[0] = reperes(vue.texte_ecran(), plage[0])
    rapport["bas_2"] = bas[0]
    observe(pendant)
    observe(rapport["essais"][-1])    # le retour en bas aussi : il a ete releve avant bas_2
    essai("paquet de 12 apres la seconde", lambda: barre.aller_a(12))
finally:
    vue.envoyer("/exit\r")
    attendre(2, 10)
    rapport["fin"] = time.strftime("%F %T")
    rapport["justes"] = sum(e["juste"] for e in rapport["essais"])
    with open(SORTIE, "w", encoding="utf-8") as fichier:
        json.dump(rapport, fichier, ensure_ascii=False, indent=1)
    print("SONDE TERMINEE ->", SORTIE, flush=True)

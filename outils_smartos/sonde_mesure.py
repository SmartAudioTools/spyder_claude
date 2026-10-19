#!/usr/bin/env python3
"""Sonde de BarreDefilementEmulee.mesurer (spyder_claude/defilement.py) - 19/10/2026.

LA QUESTION. A la reouverture d'une session, la barre mesure l'etendue sous le voile de
lancement (PLAFOND_VOILE = 10 s) : combien de lignes par seconde monte-t-elle reellement, donc
quelle longueur de session tient sous le plafond MESURE ? Une nouvelle conversation du compte
isole recoit une longue reponse, puis le modele est oublie (comme a une reouverture) et
`mesurer` est chronometre. Le JSON donne T, haut detecte, duree et lignes par seconde.

    QT_API=pyside6 python sonde_mesure.py [fichier_json]
"""

import json
import os
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
SORTIE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(DOSSIER, "sonde_mesure.json")
QUESTION = ("Test de defilement, reponds sans outil : ecris les nombres de 1 a 600, un par "
            "ligne, sans rien d'autre. Termine par le bloc ===== SYNTHESE VOCALE ===== avec le "
            "seul mot fini.")

vue = VueKonsole(couleur_fond="#19232D", couleur_texte="#DFE1E2")
barre = BarreDefilementEmulee(vue)
barre.MESURE = 60000                    # la sonde veut la duree vraie, pas le plafond
vue.resize(1100, 800)
vue.show()
derniere = [time.monotonic()]
vue.sig_sortie.connect(lambda: derniere.__setitem__(0, time.monotonic()))
vue.demarrer(["sudo", os.path.expanduser("~/.scripts/claude_compte_isole.sh"), DOSSIER],
             repertoire=DOSSIER)


def attendre(calme, plafond):
    debut = time.monotonic()
    while time.monotonic() - debut < plafond:
        QCoreApplication.processEvents()
        time.sleep(0.01)
        if time.monotonic() - derniere[0] >= calme and time.monotonic() - debut >= calme:
            return True
    return False


def taper(touche, texte=""):
    cible = vue.widgets_du_terminal()[0].focusProxy() or vue.widgets_du_terminal()[0]
    for type_ in (QEvent.KeyPress, QEvent.KeyRelease):
        QApplication.sendEvent(cible, QKeyEvent(type_, touche, Qt.NoModifier, texte))


rapport = {"debut": time.strftime("%F %T")}
try:
    rapport["demarrage_calme"] = attendre(4, 90)
    vue.envoyer("\x1b")
    attendre(1.5, 5)
    vue.envoyer(QUESTION)
    attendre(1, 5)
    taper(Qt.Key_Return, "\r")
    rapport["reponse_calme"] = attendre(8, 400)
    rapport["barre_active"] = barre._actif
    rapport["lignes_ecran"] = vue.lignes_ecran()
    rapport["ecran"] = vue.texte_ecran()
    # « on ne peut pas parcourir plus vite ? » (19/10/2026) : chaque pas attend CALME ms de
    # silence avant de relire ; plus court, une relecture en plein dessin ferait croire au haut
    for calme, essai in [(c, e) for c in (120, 60, 40, 25) for e in range(2)]:
        barre.CALME_MESURE = calme
        barre._sur_mode(True)           # comme a une reouverture : rien de connu
        fini = []
        debut = time.monotonic()
        barre.mesurer(lambda: fini.append(time.monotonic()))
        while not fini and time.monotonic() - debut < 120:
            QCoreApplication.processEvents()
            time.sleep(0.005)
        duree = (fini[0] if fini else time.monotonic()) - debut
        m = barre.modele
        rapport.setdefault("essais", []).append(
            {"calme_ms": calme, "T": m.T, "haut": m.haut_connu, "d_fin": m.d, "duree_s": round(duree, 2),
             "lignes_par_s": round(m.T / duree, 1) if duree else None,
             "page": barre._page_claude})
        print(rapport["essais"][-1], flush=True)
        attendre(1, 5)
finally:
    vue.envoyer("/exit\r")
    attendre(2, 10)
    rapport["fin"] = time.strftime("%F %T")
    with open(SORTIE, "w", encoding="utf-8") as fichier:
        json.dump(rapport, fichier, ensure_ascii=False, indent=1)
    print("SONDE TERMINEE ->", SORTIE, flush=True)

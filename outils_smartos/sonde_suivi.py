#!/usr/bin/env python3
"""Sonde du SUIVI DES REPONSES pour la barre emulee (spyder_claude/defilement.py) — 19/10/2026.

LA QUESTION. Apres chaque question, le pouce se hachure : la reponse a fait grandir le
contenu d'une quantite inconnue tant qu'on n'est pas remonte jusqu'en haut (demande de
l'utilisateur : « on ne peut vraiment pas mesurer le nombre de lignes apporte par chaque
nouvelle reponse ?? »). L'idee a valider : pendant que Claude ecrit, en bas, le texte de
l'ecran REMONTE ; la somme de ces decalages est la croissance de l'etendue T. Ecartes : un
aller-retour Ctrl+Home / Ctrl+End sous un ecran fige (1 a 2 s, « beaucoup trop long »).

CE QU'ELLE MESURE, sans Spyder : la vraie VueKonsole (hors ecran) et la vraie barre lancent le
lanceur du compte isole, nouvelle conversation (T = 0 connu). A chaque salve de sortie (au plus
une lecture toutes les CADENCE ms), l'ecran est relu et `suivre` (defilement.py, ou il vit depuis l'integration) en deduit le decalage, ou le
declare AMBIGU (jamais devine). Apres chaque reponse, la VERITE : la barre remonte jusqu'en
haut (detection exacte, validee par sonde_barre) puis redescend ; la croissance vraie est la
difference des T. Le JSON met cote a cote somme suivie, verite, ambiguites et temps de lecture.

Reponses essayees : nombres (lignes toutes distinctes), markdown realiste (lignes vides, titres,
bloc de code), reponse courte, lecture d'un fichier par un outil (affichage replie), et une
reponse pendant laquelle on est REMONTE (Claude fige-t-il la vue ?). Puis un changement de
HAUTEUR seule : Claude rereplie-t-il les lignes (T + hauteur visible doit rester constant) ?

    QT_API=pyside6 python sonde_suivi.py [fichier_json]
"""

import json
import os
import sys
import time

CADENCE = 40          # ms entre deux lectures d'ecran pendant la sortie

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_API", "pyside6")
ICI = os.path.dirname(os.path.abspath(__file__))
for chemin in (os.path.join(ICI, ".."), os.path.join(ICI, "..", "..", "spyder_konsole"),
               os.path.join(ICI, "..", "..", "spyder_konsole", "qtermwidget_binding", "build")):
    sys.path.insert(0, chemin)

from qtpy.QtCore import QCoreApplication, QEvent, Qt, QTimer  # noqa: E402
from qtpy.QtGui import QKeyEvent  # noqa: E402
from qtpy.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

from spyder_claude.defilement import BarreDefilementEmulee, suivre  # noqa: E402
from spyder_konsole.konsole_view import VueKonsole  # noqa: E402

DOSSIER = "/DATA/Python/FORKS/SmartPythonEditor_generator"
SORTIE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(DOSSIER, "sonde_suivi.json")
FIN = " Termine par le bloc ===== SYNTHESE VOCALE ===== avec le seul mot fini."
QUESTIONS = [
    ("nombres", "Test de defilement, reponds sans outil : ecris les nombres de 1 a 120, un "
                "par ligne, sans rien d'autre." + FIN),
    ("markdown", "Test de defilement, reponds sans outil : explique les listes Python en trois "
                 "sections avec titres, listes a puces, paragraphes separes par des lignes "
                 "vides, et un bloc de code Python d'une vingtaine de lignes, environ 90 "
                 "lignes en tout." + FIN),
    ("courte", "Reponds seulement : ok." + FIN),
    ("outil", "Lis le fichier README.md du dossier courant avec l'outil Read, puis resume-le "
              "en 8 lignes." + FIN),
    ("remonte", "Test de defilement, reponds sans outil : ecris les nombres de 2001 a 2080, "
                "un par ligne, sans rien d'autre." + FIN),
]

vue = VueKonsole(couleur_fond="#19232D", couleur_texte="#DFE1E2")
barre = BarreDefilementEmulee(vue)
vue.resize(1100, 800)
vue.show()
derniere = [time.monotonic()]
fini = [False]
vue.sig_termine.connect(lambda _code: fini.__setitem__(0, True))

# -- le suivi, tel que la barre le ferait
suivi = {"actif": False, "ecran": None, "somme": 0, "salves": [], "lectures_ms": []}
minuteur = QTimer()
minuteur.setSingleShot(True)
minuteur.setInterval(CADENCE)


def lire():
    debut = time.perf_counter()
    ecran = vue.texte_ecran()
    suivi["lectures_ms"].append(round(1000 * (time.perf_counter() - debut), 2))
    return ecran


def relever():
    if not suivi["actif"]:
        return
    ecran = lire()
    k, votes = suivre(suivi["ecran"], ecran)
    if ecran != suivi["ecran"]:             # 3e sonde : 1 ligne perdue sans ambiguite -> tout garder
        suivi["salves"].append({"t": round(time.monotonic() - suivi["t0"], 3), "k": k,
                                "votes": votes, "avant": suivi["ecran"], "apres": ecran})
    if k:
        suivi["somme"] += k
    suivi["ecran"] = ecran


def sur_sortie():
    derniere[0] = time.monotonic()
    if suivi["actif"] and not minuteur.isActive():
        minuteur.start()


minuteur.timeout.connect(relever)
vue.sig_sortie.connect(sur_sortie)
vue.demarrer(["sudo", os.path.expanduser("~/.scripts/claude_compte_isole.sh"), DOSSIER],
             repertoire=DOSSIER)


def attendre(calme, plafond):
    """Rend quand la sortie s'est tue `calme` s et que la barre n'a plus rien en vol."""
    debut = time.monotonic()
    while time.monotonic() - debut < plafond and not fini[0]:
        QCoreApplication.processEvents()
        time.sleep(0.01)
        if (time.monotonic() - derniere[0] >= calme and time.monotonic() - debut >= calme
                and barre._verification is None and barre._paquet is None
                and barre._cible == barre.modele.d):
            return True
    return False


def taper(touche, texte=""):
    """Une touche comme au clavier : par le filtre d'evenements, donc vue par la barre."""
    cible = vue.widgets_du_terminal()[0].focusProxy() or vue.widgets_du_terminal()[0]
    for type_ in (QEvent.KeyPress, QEvent.KeyRelease):
        QApplication.sendEvent(cible, QKeyEvent(type_, touche, Qt.NoModifier, texte))


def verite():
    """T exact : jusqu'en haut par la barre, puis retour en bas. Rend (T, haut detecte)."""
    barre.aller_a(10 ** 6)
    attendre(0.8, 120)
    T, connu = barre.modele.T, barre.modele.haut_connu
    barre.aller_a(0)
    attendre(0.8, 20)
    return T, connu


rapport = {"debut": time.strftime("%F %T"), "cadence_ms": CADENCE, "reponses": []}
try:
    rapport["demarrage_calme"] = attendre(4, 90)
    rapport["barre_active"] = barre._actif
    rapport["lignes_ecran"] = vue.lignes_ecran()
    T_avant, connu = verite()
    rapport["T_initial"] = [T_avant, connu]
    for nom, question in QUESTIONS:
        # suivi ouvert AVANT de taper : la saisie elle-meme peut decaler l'ecran (3e sonde,
        # 1 ligne perdue sur les deux questions les plus longues)
        suivi.update(actif=True, ecran=lire(), somme=0, salves=[], lectures_ms=[],
                     t0=time.monotonic())
        vue.envoyer("\x1b")                     # ferme un dialogue surgi (2e sonde : « Teach
        attendre(1.5, 5)                        # auto mode » a avale 4 questions sur 5)
        vue.envoyer(question)
        attendre(1, 5)
        relever()
        taper(Qt.Key_Return, "\r")
        if nom == "remonte":
            attendre(1.5, 15)                       # la sortie a commence : on remonte de 6
            barre.aller_a(6)
        calme = attendre(6, 300)
        relever()
        suivi["actif"] = False
        # nos propres crans decalent aussi l'ecran (k < 0 en remontant) : on les rend
        suivi["somme"] += barre.modele.d
        T_apres, connu = verite()
        lectures = suivi["lectures_ms"]
        entree = {"reponse": nom, "calme": calme, "somme_suivie": suivi["somme"],
                  "croissance_vraie": T_apres - T_avant, "T": T_apres, "haut_detecte": connu,
                  "ambigues": sum(s["k"] is None for s in suivi["salves"]),
                  "decalages": [(s["t"], s["k"]) for s in suivi["salves"] if s["k"] != 0],
                  "salves": suivi["salves"],
                  "lectures": len(lectures),
                  "lecture_ms_moy": round(sum(lectures) / len(lectures), 2) if lectures else None,
                  "lecture_ms_max": max(lectures) if lectures else None,
                  "ambiguites": [s for s in suivi["salves"] if s["k"] is None][:5],
                  "ecran_final": vue.texte_ecran()}
        entree["juste"] = entree["somme_suivie"] == entree["croissance_vraie"]
        rapport["reponses"].append(entree)
        print(f"{nom:10s} suivi {entree['somme_suivie']:4d}  vrai {entree['croissance_vraie']:4d}"
              f"  ambigues {entree['ambigues']:3d}  lectures {entree['lectures']:4d}"
              f" ({entree['lecture_ms_moy']} ms)  {'OK' if entree['juste'] else 'ECART'}",
              flush=True)
        T_avant = T_apres
    # hauteur seule : si Claude ne rereplie pas, T + lignes visibles reste constant
    for hauteur in (600, 800):
        lignes = vue.lignes_ecran()
        vue.resize(1100, hauteur)
        attendre(2, 20)
        T, connu = verite()
        rapport.setdefault("hauteur", []).append(
            {"hauteur": hauteur, "lignes_avant": lignes, "lignes_apres": vue.lignes_ecran(),
             "T_avant": T_avant, "T_apres": T, "haut_detecte": connu,
             "somme_constante": T_avant + lignes == T + vue.lignes_ecran()})
        print("hauteur", rapport["hauteur"][-1], flush=True)
        T_avant = T
finally:
    suivi["actif"] = False
    vue.envoyer("/exit\r")
    attendre(2, 10)
    rapport["fin"] = time.strftime("%F %T")
    rapport["justes"] = sum(r["juste"] for r in rapport["reponses"])
    with open(SORTIE, "w", encoding="utf-8") as fichier:
        json.dump(rapport, fichier, ensure_ascii=False, indent=1)
    print("SONDE TERMINEE ->", SORTIE, flush=True)

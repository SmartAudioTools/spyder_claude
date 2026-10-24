#!/usr/bin/env python3
"""Sonde de la barre emulee SUR PLUSIEURS ECHANGES (spyder_claude/defilement.py) — 24/10/2026.

LA QUESTION. « le defilement rapide de 3 lignes par 3 lignes ne semble pas fonctionner, la
hauteur totale est tres vite perdue au bout de quelques echanges ». sonde_suivi mesurait
`suivre` a part, et refaisait la verite apres chaque reponse : elle ne dit pas ce que la
BARRE garde d'un echange au suivant, ni pourquoi elle perd le haut.

CE QU'ELLE MESURE, sans Spyder (vraie VueKonsole hors ecran, vraie barre, Claude du compte
isole, nouvelle conversation) :
  - a chaque echange, partant d'un haut connu et exact : T et haut_connu de la barre a la fin
    de la reponse, puis la verite (haut oublie de force, remontee par paquets) ; chaque passage
    de haut_connu a faux avec la fonction qui l'a fait, et chaque lecture AMBIGUE de `suivre`
    avec ses deux ecrans. Variantes : question envoyee en bas, envoyee vue remontee (Entree
    avec d non nul), vue remontee PENDANT la reponse ;
  - la molette : salves de crans a 25, 100 et 300 ms d'ecart, la chronologie (t, cible, d)
    jusqu'a l'arrivee, en zone connue puis en zone inconnue (haut oublie).

    QT_API=pyside6 python sonde_echanges.py [fichier_json]
    SONDE_JETS=1 ... : deux echanges (du contenu a remonter) puis les seuls jets de molette
    SONDE_PENDANT=1 ... : la seule variante remonte_pendant, quatre fois (JET 1, 1, 3, 3), toutes
    les lectures de `suivre` (ecrans compris) et tous les envois de crans
    journalises, la verite remesuree a 0 et 20 s, ecrans du haut et du bas gardes (ecart
    de 2 lignes, 24/10)
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

from qtpy.QtCore import QCoreApplication, QEvent, QPoint, Qt  # noqa: E402
from qtpy.QtGui import QKeyEvent  # noqa: E402
from qtpy.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

import spyder_claude.defilement as D  # noqa: E402
from spyder_konsole.konsole_view import VueKonsole  # noqa: E402

DOSSIER = "/DATA/Python/FORKS/SmartPythonEditor_generator"
ESSAIS = "/DATA/Python/FORKS/SmartPythonEditor_generator_essais/defilement_echanges"
os.makedirs(ESSAIS, exist_ok=True)
JETS = bool(os.environ.get("SONDE_JETS"))
PENDANT = bool(os.environ.get("SONDE_PENDANT")) and not JETS    # deux modes exclusifs
SORTIE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    ESSAIS, time.strftime("sonde_echanges_%Y%m%d_%H%M%S.json"))
FIN = " Termine par le bloc ===== SYNTHESE VOCALE ===== avec le seul mot fini."
ECHANGES = [            # (nom, variante, question) ; variante : bas, remonte_avant, remonte_pendant
    ("listes", "bas", "Test de defilement, reponds sans outil : explique les listes Python en "
     "trois sections avec titres, puces, paragraphes separes par des lignes vides et un bloc de "
     "code d'une quinzaine de lignes, environ 60 lignes en tout." + FIN),
    ("dicos", "remonte_avant", "Test de defilement, reponds sans outil : meme exercice pour les "
     "dictionnaires Python, environ 60 lignes." + FIN),
    ("boucles", "remonte_pendant", "Test de defilement, reponds sans outil : meme exercice pour "
     "les boucles for et while, environ 60 lignes." + FIN),
    ("courte", "remonte_avant", "Reponds seulement : ok." + FIN),
    ("fonctions", "bas", "Test de defilement, reponds sans outil : meme exercice pour les "
     "fonctions Python, environ 60 lignes." + FIN),
    ("classes", "remonte_avant", "Test de defilement, reponds sans outil : meme exercice pour "
     "les classes Python, environ 60 lignes." + FIN),
]
if JETS:
    ECHANGES = ECHANGES[:2]
if PENDANT:     # (nom, variante, question, JET) : le contenu d'abord, puis la variante sous JET 3 et 1
    ECHANGES = [ECHANGES[0]] + [(nom, "remonte_pendant", question, jet) for (nom, _v, question), jet
                                in zip([ECHANGES[i] for i in (2, 4, 5, 1)], (1, 1, 3, 3))]

# -- journal : qui fait passer haut_connu a faux, et ce que `suivre` rend dans la barre
journal = {"pertes": [], "suivre": [], "trace": True}


def tracer(self, nom, valeur):
    if (journal["trace"] and nom == "haut_connu" and not valeur
            and getattr(self, "haut_connu", False)):
        appelant = sys._getframe(1)
        journal["pertes"].append({
            "t": round(time.monotonic() - T0, 3), "par": appelant.f_code.co_name,
            "ligne": appelant.f_lineno, "depuis": appelant.f_back.f_code.co_name,
            "d": self.d, "T": self.T})
    object.__setattr__(self, nom, valeur)


D.ModeleDefilement.__setattr__ = tracer
suivre_vrai = D.suivre


def suivre_trace(avant, apres):
    k, votes = suivre_vrai(avant, apres)
    entree = {"t": round(time.monotonic() - T0, 3), "k": k, "d": barre.modele.d}
    if k is None or PENDANT:
        entree.update(votes={str(c): n for c, n in votes.items()}, avant=avant, apres=apres)
    journal["suivre"].append(entree)
    return k, votes


D.suivre = suivre_trace
T0 = time.monotonic()

vue = VueKonsole(couleur_fond="#19232D", couleur_texte="#DFE1E2")
barre = D.BarreDefilementEmulee(vue)
vue.resize(1100, 800)
envoyer_molette_vrai = vue.envoyer_molette


def envoyer_molette_trace(crans):
    if journal["trace"]:
        journal.setdefault("envois", []).append(
            {"t": round(time.monotonic() - T0, 3), "crans": crans, "d_avant": barre.modele.d})
    envoyer_molette_vrai(crans)


vue.envoyer_molette = envoyer_molette_trace
vue.show()
derniere = [time.monotonic()]
fini = [False]
vue.sig_termine.connect(lambda _code: fini.__setitem__(0, True))
vue.sig_sortie.connect(lambda: derniere.__setitem__(0, time.monotonic()))
vue.demarrer(["sudo", os.path.expanduser("~/.scripts/claude_compte_isole.sh"), DOSSIER],
             repertoire=DOSSIER)


def pomper(secondes):
    fin = time.monotonic() + secondes
    while time.monotonic() < fin:
        QCoreApplication.processEvents()
        time.sleep(0.005)


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
    """T exact : haut oublie (sans trace), remontee par paquets, retour en bas. Rend T."""
    journal["trace"] = False
    barre.modele.haut_connu = False
    barre.aller_a(10 ** 6)
    attendre(0.8, 180)
    T, connu = barre.modele.T, barre.modele.haut_connu
    journal["haut"] = vue.texte_ecran()
    barre.aller_a(0)
    attendre(0.8, 20)
    journal["trace"] = True
    return T, connu


class Cran:
    """Un evenement de molette d'un cran (120 huitiemes de degre) vers le haut."""

    @staticmethod
    def angleDelta():  # noqa: N802 - API Qt
        return QPoint(0, 120)


def salve(crans, ecart_ms):
    """`crans` crans espaces de `ecart_ms`, puis la chronologie jusqu'a l'arrivee."""
    chrono, debut = [], time.monotonic()
    for i in range(crans):
        barre.wheelEvent(Cran())
        chrono.append((round(time.monotonic() - debut, 3), barre._cible, barre.modele.d))
        fin = time.monotonic() + ecart_ms / 1000
        while time.monotonic() < fin:
            QCoreApplication.processEvents()
            time.sleep(0.002)
    fin_salve = time.monotonic() - debut
    while time.monotonic() - debut < 30 and (barre._cible != barre.modele.d
                                             or barre._paquet or barre._verification):
        QCoreApplication.processEvents()
        time.sleep(0.005)
        point = (round(time.monotonic() - debut, 3), barre._cible, barre.modele.d)
        if point[1:] != chrono[-1][1:]:
            chrono.append(point)
    return {"crans": crans, "ecart_ms": ecart_ms, "cible": barre._cible, "d": barre.modele.d,
            "duree_salve_s": round(fin_salve, 3),
            "arrivee_s": round(time.monotonic() - debut, 3), "haut_connu": barre.modele.haut_connu,
            "chrono": chrono}


rapport = {"debut": time.strftime("%F %T"), "wheelScrollLines": QApplication.wheelScrollLines(),
           "echanges": [], "molette": []}
try:
    rapport["demarrage_calme"] = attendre(4, 90)
    rapport["barre_active"] = barre._actif
    rapport["lignes_ecran"] = vue.lignes_ecran()
    rapport["T_initial"] = verite()
    for nom, variante, question, *jet in ECHANGES:
        barre.JET = jet[0] if jet else D.BarreDefilementEmulee.JET
        jet_echange = barre.JET
        T_avant = barre.modele.T
        journal["pertes"], journal["suivre"], journal["envois"] = [], [], []
        vue.envoyer("\x1b")                     # ferme un dialogue surgi (cf. sonde_suivi)
        attendre(1.5, 5)
        vue.envoyer(question)
        attendre(1, 5)
        if variante == "remonte_avant":
            barre.aller_a(8)
            attendre(0.5, 10)
        d_entree = barre.modele.d
        taper(Qt.Key_Return, "\r")
        if variante == "remonte_pendant":
            attendre(1.5, 15)
            barre.aller_a(6)
        calme = attendre(6, 300)
        barre.aller_a(0)
        attendre(0.8, 10)
        T_barre, connu_barre = barre.modele.T, barre.modele.haut_connu
        pertes, lectures = list(journal["pertes"]), list(journal["suivre"])
        envois = list(journal["envois"])
        if PENDANT:     # la verite ne depend pas de JET (115152) mais grandit apres coup : quand, quoi ?
            temps, debut = [], time.monotonic()
            for pause in (0, 20):
                pomper(pause)
                T_t, _c = verite()
                temps.append({"t": round(time.monotonic() - debut, 1), "T": T_t,
                              "haut": journal["haut"], "bas": vue.texte_ecran()})
        T_vrai, connu_vrai = verite()
        entree = {"echange": nom, "variante": variante, "d_a_l_entree": d_entree,
                  "calme": calme, "T_avant": T_avant, "T_barre": T_barre,
                  "haut_connu_barre": connu_barre, "T_vrai": T_vrai, "verite_ok": connu_vrai,
                  "ecart": T_barre - T_vrai, "pertes": pertes,
                  "lectures": len(lectures),
                  "ambigues": [s for s in lectures if s["k"] is None], "jet": jet_echange}
        if PENDANT:
            entree.update(lectures_completes=lectures, envois=envois, verites=temps)
        rapport["echanges"].append(entree)
        print(f"{nom:10s} {variante:16s} JET {jet_echange} T barre {T_barre:4d} ({'connu' if connu_barre else 'perdu'})"
              f"  vrai {T_vrai:4d}  ambigues {len(entree['ambigues']):2d}/{len(lectures):3d}"
              f"  pertes {[p['par'] for p in pertes]}"
              + (f"  verites {[(v['t'], v['T']) for v in temps]}" if PENDANT else ""), flush=True)
    # -- molette, en bas, haut connu puis oublie
    for zone in () if JETS or PENDANT else ("connue", "inconnue"):
        for crans, ecart in ((10, 25), (10, 100), (5, 300)):
            barre.aller_a(0)
            attendre(0.5, 10)
            if zone == "inconnue":
                journal["trace"] = False
                barre.modele.haut_connu = False
                barre.modele.T = 0
                journal["trace"] = True
            mesure = salve(crans, ecart)
            mesure["zone"] = zone
            rapport["molette"].append(mesure)
            print(f"molette {zone:8s} {crans:2d} crans / {ecart:3d} ms -> d {mesure['d']:3d}"
                  f" en {mesure['arrivee_s']} s (salve {mesure['duree_salve_s']} s)", flush=True)
    # -- ce que Claude fait de `n` crans d'UNE seule ecriture, repetee `fois` fois a `ecart` ms :
    # le decalage lu a l'ecran (suivre), depuis le bas, Ctrl+End entre deux essais
    rapport["jets"] = []
    for n, fois, ecart in () if PENDANT else ((1, 1, 0), (2, 1, 0), (3, 1, 0), (4, 1, 0), (6, 1, 0),
                           (3, 5, 30), (3, 5, 60), (3, 5, 100), (3, 5, 150)):
        for essai in range(3):
            barre._en_bas()
            attendre(0.6, 10)
            journal["trace"] = False
            avant = vue.texte_ecran()
            for i in range(fois):
                vue.envoyer_molette(n)
                pomper(ecart / 1000)
            pomper(0.4)
            k, _votes = suivre_vrai(avant, vue.texte_ecran())
            journal["trace"] = True
            rapport["jets"].append({"crans": n, "fois": fois, "ecart_ms": ecart, "essai": essai,
                                    "lignes": None if k is None else -k})
            print(f"jet {n} crans x {fois} a {ecart:3d} ms -> {None if k is None else -k} lignes",
                  flush=True)
    barre._en_bas()
    attendre(0.6, 10)
finally:
    vue.envoyer("/exit\r")
    attendre(2, 10)
    rapport["fin"] = time.strftime("%F %T")
    with open(SORTIE, "w", encoding="utf-8") as fichier:
        json.dump(rapport, fichier, ensure_ascii=False, indent=1)
    print("SONDE TERMINEE ->", SORTIE, flush=True)

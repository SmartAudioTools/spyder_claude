#!/usr/bin/env python3
"""Sonde : combien de lignes Claude Code (rendu plein ecran) defile-t-il par cran de molette ?

Question posee le 19/10/2026 avant tout prototype de barre de defilement emulee pour le
greffon Claude : la barre ne peut dire vrai que si chaque cran fait defiler un nombre CONSTANT
de lignes (avis du Superviseur). On ne peut pas lancer Claude depuis le bac a sable d'une
session : cette sonde se lance depuis le terminal de l'utilisateur.

Ce qu'elle fait, sans Spyder : un QTermWidget hors ecran (QT_QPA_PLATFORM=offscreen, aucune
configuration d'application touchee) lance le lanceur du compte isole SANS --onglet-spyder,
donc dans le rendu par defaut (plein ecran attendu, verifie dans le flux : ?1049h, ?1006h),
demande a Claude une sortie numerotee, puis envoie des crans de molette SGR (ce que ferait la
barre) et relit l'ecran par la selection (seule lecture qu'offre QTermWidget) apres chacun.

    python sonde_molette.py [--alternance] [fichier_json]

Le JSON porte les ecrans bruts et le decalage mesure de chaque essai.

--alternance (second passage, 19/10/2026) : le premier passage a perdu le premier cran vers le
bas apres une montee. Cette serie alterne les sens, separe changement de sens et simple pause
dans le meme sens, puis verifie que Ctrl+End (« Jump to bottom » affiche par Claude) ramene
exactement a l'ecran du bas.

--cadence (troisieme passage, 19/10/2026) : la sonde de la barre (sonde_barre.py) a montre
que des crans envoyes d'un seul jet sont ACCELERES (10 crans -> 12 lignes, 12 -> 22). Cette
serie envoie 12 crans vers le haut a chaque intervalle, revient en bas par Ctrl+End entre
deux, et mesure la vraie position par le rang des nombres (pas par le dernier nombre : le
bas de la reponse porte des lignes non numerotees).

--pages (quatrieme passage, 19/10/2026) : la molette, seule regle sans acceleration, plafonne a
20 lignes/s. Cette serie mesure si Page precedente / Page suivante et Ctrl+Home font un pas
CONSTANT (donc modelisable), s'ils accelerent en jet, et s'ils se melangent a la molette sans
perdre de cran (la regle d'inversion vaut-elle entre une touche et un cran ?).
"""

import json
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "spyder_konsole",
                                "qtermwidget_binding", "build"))

import qtermwidget as qtw  # noqa: E402
from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

DOSSIER = "/DATA/Python/FORKS/SmartPythonEditor_generator"
ALTERNANCE = "--alternance" in sys.argv
CADENCE = "--cadence" in sys.argv
PAGES = "--pages" in sys.argv
ARGUMENTS = [a for a in sys.argv[1:] if not a.startswith("--")]
SORTIE = ARGUMENTS[0] if ARGUMENTS else os.path.join(
    DOSSIER, "sonde_molette_alternance.json" if ALTERNANCE
    else "sonde_molette_cadence.json" if CADENCE
    else "sonde_molette_pages.json" if PAGES else "sonde_molette.json")
CONSIGNE = ("Test de defilement, reponds sans outil : ecris les nombres de 1 a 250, un par "
            "ligne, sans rien d'autre, puis le bloc ===== SYNTHESE VOCALE ===== avec le seul "
            "mot fini.")
MODES = ("?1049h", "?1000h", "?1002h", "?1003h", "?1006h", "?2004h")

app = QApplication(sys.argv)
terminal = qtw.QTermWidget(0)
terminal.resize(1100, 800)
terminal.setHistorySize(0)
terminal.setShellProgram("sudo")
terminal.setArgs([os.path.expanduser("~/.scripts/claude_compte_isole.sh"), DOSSIER])
terminal.setWorkingDirectory(DOSSIER)
terminal.setEnvironment([f"{k}={v}" for k, v in os.environ.items()] + ["TERM=xterm-256color"])
flux = []
derniere = [time.monotonic()]
fini = [False]


def recu(texte):
    flux.append(texte)
    derniere[0] = time.monotonic()


terminal.receivedData.connect(recu)
terminal.finished.connect(lambda: fini.__setitem__(0, True))
terminal.show()
terminal.startShellProgram()


def attendre(calme, plafond):
    """Rend quand la sortie s'est tue `calme` secondes (ou au plafond) ; dit lequel."""
    debut = time.monotonic()
    while time.monotonic() - debut < plafond and not fini[0]:
        QCoreApplication.processEvents()
        time.sleep(0.02)
        if time.monotonic() - derniere[0] >= calme and time.monotonic() - debut >= calme:
            return True
    return False


def ecran():
    lignes, colonnes = terminal.screenLinesCount(), terminal.screenColumnsCount()
    terminal.setSelectionStart(0, 0)
    terminal.setSelectionEnd(lignes - 1, colonnes)
    texte = terminal.selectedText(True)
    terminal.setSelectionStart(0, 0)
    terminal.setSelectionEnd(0, -1)
    return texte.split("\n")


def decalage(avant, apres):
    """Decalage k (lignes) qui superpose le mieux `apres` a `avant` : k > 0, contenu descendu."""
    meilleur, score_max = 0, -1
    for k in range(-len(avant) + 1, len(avant)):
        paires = [(avant[i], apres[i + k]) for i in range(len(avant))
                  if 0 <= i + k < len(apres) and avant[i].strip()]
        score = sum(a == b for a, b in paires)
        if score > score_max:
            meilleur, score_max = k, score
    return meilleur, score_max


def molette(n, haut=True, intervalle=0.05):
    ligne, colonne = terminal.screenLinesCount() // 3, terminal.screenColumnsCount() // 2
    code = 64 if haut else 65
    if not intervalle:                 # d'un seul jet, comme la barre jusqu'ici
        terminal.sendText(f"\x1b[<{code};{colonne};{ligne}M" * n)
    for _ in range(n if intervalle else 0):
        terminal.sendText(f"\x1b[<{code};{colonne};{ligne}M")
        debut = time.monotonic()
        while time.monotonic() - debut < intervalle:
            QCoreApplication.processEvents()
            time.sleep(0.001)
    attendre(0.8, 5)


def position(lignes, rang_du_dernier):
    """Lignes au-dessus du bas, par le rang du premier nombre visible (ligne 0 epinglee)."""
    for i, texte in enumerate(lignes[1:], 1):
        if texte.strip().isdigit():
            return i - rang_du_dernier + (250 - int(texte))
    return None


rapport = {"debut": time.strftime("%F %T"), "essais": []}
try:
    rapport["demarrage_calme"] = attendre(4, 90)
    terminal.sendText(CONSIGNE)
    attendre(1, 5)
    terminal.sendText("\r")
    attendre(1, 10)
    rapport["reponse_calme"] = attendre(6, 240)
    rapport["taille"] = [terminal.screenLinesCount(), terminal.screenColumnsCount()]
    tout = "".join(flux)
    rapport["modes"] = {m: (m in tout) for m in MODES}
    rapport["ecran_bas"] = ecran()

    def essai(nom, action):
        avant = ecran()
        action()
        apres = ecran()
        k, score = decalage(avant, apres)
        rapport["essais"].append({"essai": nom, "decalage": k, "lignes_concordantes": score,
                                  "apres": apres})
        print(f"{nom:28s} decalage {k:+4d}  ({score} lignes concordantes)", flush=True)

    if PAGES:
        rang = next(i for i, t in enumerate(rapport["ecran_bas"]) if t.strip() == "250")
        rapport["rang_de_250_en_bas"] = rang
        rapport["pages"] = []
        HAUT, BAS, MOL_HAUT, MOL_BAS = "\x1b[5~", "\x1b[6~", "molette+", "molette-"

        def pas(nom, *touches, jet=False):
            avant = position(ecran(), rang)
            if jet:
                terminal.sendText("".join(touches))
            for touche in ([] if jet else touches):
                if touche in (MOL_HAUT, MOL_BAS):
                    molette(1, touche == MOL_HAUT)
                else:
                    terminal.sendText(touche)
                    attendre(0.3, 3)
            attendre(0.8, 5)
            apres = position(ecran(), rang)
            rapport["pages"].append({"essai": nom, "avant": avant, "apres": apres})
            print(f"{nom:34s} {avant} -> {apres}  ({None if None in (avant, apres) else apres - avant:+})",
                  flush=True)

        for i in range(3):
            pas("PgUp %d" % (i + 1), HAUT)
        pas("PgDn", BAS)
        pas("PgDn", BAS)
        pas("PgUp puis PgDn (inversion)", HAUT, BAS)
        pas("3 PgUp d'un seul jet", HAUT, HAUT, HAUT, jet=True)
        terminal.sendText("\x1b[1;5F")
        attendre(0.8, 5)
        pas("molette +1 apres Ctrl+End", MOL_HAUT)
        pas("PgUp apres molette +", HAUT)
        pas("molette -1 apres PgUp", MOL_BAS)
        pas("molette -1 encore", MOL_BAS)
        pas("PgDn apres molette -", BAS)
        pas("molette +1 apres PgDn", MOL_HAUT)
        pas("molette +1 encore", MOL_HAUT)
        pas("Ctrl+Home", "\x1b[1;5H")
        pas("PgUp en haut (butee)", HAUT)
        pas("Ctrl+End", "\x1b[1;5F")
        rapport["taille_finale"] = [terminal.screenLinesCount(), terminal.screenColumnsCount()]
        raise SystemExit
    if CADENCE:
        rang = next(i for i, t in enumerate(rapport["ecran_bas"]) if t.strip() == "250")
        rapport["rang_de_250_en_bas"] = rang
        rapport["cadence"] = []
        for intervalle in (0, 0.005, 0.01, 0.02, 0.03, 0.05, 0.1, 0) :
            molette(12, True, intervalle)
            d = position(ecran(), rang)
            rapport["cadence"].append({"intervalle_ms": intervalle * 1000, "lignes": d})
            print(f"12 crans, intervalle {intervalle * 1000:5.1f} ms -> {d} lignes", flush=True)
            terminal.sendText("\x1b[1;5F")
            attendre(0.8, 5)
        raise SystemExit
    if ALTERNANCE:
        # Attendu si seul le changement de sens perd un cran : 0 sur chaque premier cran apres
        # inversion, 1 ailleurs - y compris apres une pause de 3 s dans le meme sens.
        for n, haut in ((10, True), (1, False), (1, False), (1, False), (1, True), (1, True),
                        (1, False), (1, True), (3, False), (3, True)):
            essai(f"{'haut' if haut else 'bas'} x{n}", lambda n=n, h=haut: molette(n, h))
        essai("pause 3 s puis haut x1", lambda: (attendre(3, 3), molette(1, True)))
        essai("pause 3 s puis haut x1", lambda: (attendre(3, 3), molette(1, True)))
        essai("ctrl+End", lambda: (terminal.sendText("\x1b[1;5F"), attendre(0.8, 5)))
        rapport["ctrl_end_revient_en_bas"] = ecran() == rapport["ecran_bas"]
        print("ctrl+End revient a l'ecran du bas :", rapport["ctrl_end_revient_en_bas"],
              flush=True)
        raise SystemExit
    for n in (1, 1, 2, 5, 3, 1):
        essai(f"haut x{n}", lambda n=n: molette(n, True))
    for n in (1, 2, 5):
        essai(f"bas x{n}", lambda n=n: molette(n, False))
    # Retour en bas a la frappe ? (point le plus fragile selon le Superviseur)
    molette(5, True)
    essai("frappe d'une lettre", lambda: (terminal.sendText("a"), attendre(0.8, 5)))
    terminal.sendText("\x7f")
    attendre(0.8, 5)
    # Detection du haut : l'ecran cesse de bouger.
    crans = 0
    while crans < 400:
        avant = ecran()
        molette(5, True)
        crans += 5
        if ecran() == avant:
            break
    rapport["crans_jusqu_au_haut"] = crans
    rapport["ecran_haut"] = ecran()
    essai("haut x1 en butee", lambda: molette(1, True))
finally:
    terminal.sendText("/exit\r")
    attendre(2, 10)
    rapport["fin"] = time.strftime("%F %T")
    with open(SORTIE, "w", encoding="utf-8") as fichier:
        json.dump(rapport, fichier, ensure_ascii=False, indent=1)
    print("SONDE TERMINEE ->", SORTIE, flush=True)

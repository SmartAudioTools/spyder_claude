# -*- coding: utf-8 -*-
"""Echantillonneur de la boucle d'evenements du Claude Dock, declenche par un fichier.

SONDE TEMPORAIRE : a retirer, avec son appel dans main() de fenetre.py, une fois la frappe
jugee fluide - entree « CLAUDE DOCK - SONDES TEMPORAIRES A RETIRER » de TODO - Spyder.txt.

POURQUOI (12/11/2026, « taper au clavier reste tres saccade avec les 18 sessions ») : ni
py-spy ni ptrace depuis le compte claude, et relancer le dock avec un profileur coute la
restauration de toutes les sessions. Une fois cette sonde chargee, une mesure se demande
SANS relance :

    echo 20 > $XDG_RUNTIME_DIR/claude-windows/dock-echantillonner     (duree en secondes)

Pendant la duree, deux mesures, ecrites ensuite dans <dossier>/echantillons-<heure>.txt :
  - RETARD de la boucle : un QTimer de 10 ms note de combien chaque tic arrive en retard.
    C'est ce que sent le clavier, que le temps soit pris en Python OU en C++ (peinture Qt) ;
  - PILE Python du fil principal, relevee toutes les 5 ms par un fil a part
    (sys._current_frames) : fonctions en propre et cumulees. Une pile reduite a l'appel de
    exec() veut dire « Qt seul » : repos, ou travail C++ que le retard dira. Biais connu :
    le fil releveur attend le GIL, il sous-compte donc le Python qui tourne sans rendre la
    main (essai : 50 % de boucle Python vue a 32 %). Les PROPORTIONS entre fonctions Python
    restent justes, et le retard, lui, n'a pas ce biais ;
  - EVENEMENTS Qt (ajout du 12/11/2026, pour voir ce qui coute AVANT que la frappe saccade) :
    un filtre pose sur l'application compte, par seconde, les repeintes par classe de widget
    (et combien de widgets distincts) et les evenements de minuterie par classe de receveur.

RECHARGEMENT A CHAUD : chaque declenchement recharge ce module (importlib.reload) avant de
mesurer. Une nouvelle version de la sonde s'essaie donc SANS relancer le dock ; seule la
toute premiere version qui sait se recharger demande une relance.
"""
import importlib
import collections
import os
import sys
import threading
import time

from qtpy.QtCore import QEvent, QObject, Qt, QTimer
from qtpy.QtWidgets import QApplication

from spyder_claude.etat_instances import dossier_etat

DOSSIER_DEFAUT = "/DATA/Python/FORKS/SmartPythonEditor_generator_essais/dock_perf"
PAS_PILE = 0.005
PAS_RETARD_MS = 10


class Echantillonneur:
    def __init__(self, dossier=None):
        self._dossier = dossier or os.environ.get("CLAUDE_DOCK_ECHANTILLONS") or DOSSIER_DEFAUT
        self._veille = QTimer()
        self._veille.timeout.connect(self._regarder)
        self._veille.start(1000)
        self._en_cours = False
        self._mesure = None

    def _regarder(self):
        declencheur = os.path.join(dossier_etat(), "dock-echantillonner")
        if self._en_cours or not os.path.exists(declencheur):
            return
        try:
            with open(declencheur, encoding="utf-8") as f:
                mots = f.read().split()
            os.remove(declencheur)
            duree = float(mots[0]) if mots else 20.0
        except (OSError, ValueError):
            mots, duree = [], 20.0
        duree = max(1.0, min(duree, 300.0))
        try:
            module = importlib.reload(sys.modules[__name__])
        except Exception:  # version neuve cassee : mesurer avec celle qui tourne
            module = sys.modules[__name__]
        if "opaque" in mots:  # ESSAI : rendre les terminaux opaques avant de mesurer
            module.rendre_terminaux_opaques()
        self._mesure = module.Mesure(self._dossier, duree, self._terminee)
        self._en_cours = True

    def _terminee(self):
        self._en_cours = False
        self._mesure = None


class CompteurEvenements(QObject):
    def __init__(self):
        super().__init__()
        self.repeintes = collections.Counter()
        self.widgets = collections.defaultdict(set)
        self.surface = collections.Counter()
        self.opaques = collections.Counter()
        self.erreur = None
        self.minuteries = collections.Counter()
        self.total = collections.Counter()
        self.sous_fenetre = collections.Counter()

    def eventFilter(self, objet, evenement):
        try:
            self._compter(objet, evenement)
        except Exception as exc:  # une sonde ne doit jamais casser le dock ni se taire
            if self.erreur is None:
                self.erreur = repr(exc)
        return False

    def _compter(self, objet, evenement):
        genre = evenement.type()
        if genre == QEvent.Paint and objet.isWidgetType():
            # Classe C++ reelle (PySide nomme QWidget toute classe qu'il ne connait pas)
            classe = "%s/%s" % (type(objet).__name__, objet.metaObject().className())
            self.repeintes[classe] += 1
            self.widgets[classe].add(id(objet))
            region = evenement.region()
            zone = region.boundingRect()
            # Surface reelle : deux petites zones eloignees ont le rectangle englobant de toute
            # la fenetre ; seuls les rectangles de la region disent ce qui est vraiment repeint.
            surface = sum(r.width() * r.height() for r in region)
            self.surface[classe] += surface
            if objet.testAttribute(Qt.WA_OpaquePaintEvent) or objet.autoFillBackground():
                self.opaques[classe] += 1
            if objet.isWindow():  # qui, dessous, force la fenetre entiere a repeindre ?
                cible = objet.childAt(zone.center())
                chaine = []
                while cible is not None and cible is not objet and len(chaine) < 3:
                    chaine.append(cible.metaObject().className())
                    cible = cible.parentWidget()
                cle = "%dx%d (%d rect., %d kpx) %s" % (
                    zone.width(), zone.height(), region.rectCount(), surface // 1000,
                    " < ".join(chaine) or "-")
                self.sous_fenetre[cle] += 1
        elif genre == QEvent.Timer:
            self.minuteries[type(objet).__name__] += 1
        self.total[int(genre)] += 1


class Mesure:
    def __init__(self, dossier, duree, fin):
        opaque = os.path.join(dossier_etat(), "dock-opaque")  # ESSAI (code neuf, relu ici)
        if os.path.exists(opaque):
            os.remove(opaque)
            rendre_terminaux_opaques()
        self._dossier = dossier
        self._fin = fin
        self._fil_principal = threading.main_thread().ident
        self._tic = QTimer()
        self._tic.setInterval(PAS_RETARD_MS)
        self._tic.timeout.connect(self._noter_tic)
        self._demarrer(duree)

    def _demarrer(self, duree):
        self._retards = []
        self._propre = collections.Counter()
        self._cumul = collections.Counter()
        self._piles = 0
        self._debut = time.perf_counter()
        self._cpu_debut = time.process_time()
        self._dernier_tic = self._debut
        self._evenements = CompteurEvenements()
        QApplication.instance().installEventFilter(self._evenements)
        self._tic.start()
        threading.Thread(target=self._relever_piles, args=(duree,), daemon=True).start()
        QTimer.singleShot(int(duree * 1000), self._finir)

    def _noter_tic(self):
        maintenant = time.perf_counter()
        self._retards.append((maintenant - self._dernier_tic) * 1000 - PAS_RETARD_MS)
        self._dernier_tic = maintenant

    def _relever_piles(self, duree):
        fin = time.perf_counter() + duree
        while time.perf_counter() < fin:
            cadre = sys._current_frames().get(self._fil_principal)
            vues = set()
            premier = True
            while cadre is not None:
                code = cadre.f_code
                nom = "%s:%d %s" % (os.path.basename(code.co_filename), code.co_firstlineno,
                                    code.co_name)
                if premier:
                    self._propre[nom] += 1
                    premier = False
                if nom not in vues:
                    self._cumul[nom] += 1
                    vues.add(nom)
                cadre = cadre.f_back
            self._piles += 1
            time.sleep(PAS_PILE)

    def _finir(self):
        self._tic.stop()
        QApplication.instance().removeEventFilter(self._evenements)
        mur = time.perf_counter() - self._debut
        cpu = time.process_time() - self._cpu_debut
        retards = sorted(self._retards) or [0.0]
        bloque = sum(r for r in retards if r > 20)
        lignes = [
            "duree %.1f s, CPU du processus %.1f s (%.0f %% d'un coeur), %d piles relevees"
            % (mur, cpu, 100 * cpu / mur, self._piles),
            "retard de la boucle (tic de %d ms, %d tics) : median %.1f ms, p90 %.1f, p99 %.1f, "
            "max %.1f ; temps perdu en blocages > 20 ms : %.1f s (%.0f %%)"
            % (PAS_RETARD_MS, len(retards), retards[len(retards) // 2],
               retards[int(len(retards) * 0.9)], retards[int(len(retards) * 0.99)],
               retards[-1], bloque / 1000, 100 * bloque / 1000 / mur),
            "", "EN PROPRE (haut de pile ; exec seul = Qt / C++ ou repos) :"]
        total = max(self._piles, 1)
        lignes += ["  %5.1f %%  %s" % (100 * n / total, nom)
                   for nom, n in self._propre.most_common(30)]
        lignes += ["", "CUMULE (present dans la pile) :"]
        lignes += ["  %5.1f %%  %s" % (100 * n / total, nom)
                   for nom, n in self._cumul.most_common(40)]
        ev = self._evenements
        lignes += ["", "ETAT DES WIDGETS en fin de mesure :"] + _etat_des_widgets()
        if ev.erreur:
            lignes += ["", "ERREUR DANS LE FILTRE (premiere) : " + ev.erreur]
        if ev.sous_fenetre:
            lignes += ["", "REPEINTES DE FENETRE : taille de la zone, widget au centre < parents"]
            for cle, n in ev.sous_fenetre.most_common(12):
                lignes.append("  %7.1f /s  %s" % (n / mur, cle))
        lignes += ["", "REPEINTES par seconde, par classe Python/C++ (widgets distincts ; "
                   "kpx repeints par seconde ; part des repeintes sur widget opaque) :"]
        lignes += ["  %7.1f /s  %s (%d) %8.0f kpx/s  opaque %3.0f %%"
                   % (n / mur, classe, len(ev.widgets[classe]), ev.surface[classe] / mur / 1000,
                      100 * ev.opaques[classe] / n)
                   for classe, n in ev.repeintes.most_common(25)]
        lignes += ["", "MINUTERIES par seconde, par classe du receveur :"]
        lignes += ["  %7.1f /s  %s" % (n / mur, classe)
                   for classe, n in ev.minuteries.most_common(20)]
        lignes += ["", "EVENEMENTS par seconde, par type QEvent :"]
        lignes += ["  %7.1f /s  %s" % (n / mur, _nom_evenement(genre))
                   for genre, n in ev.total.most_common(15)]
        try:
            os.makedirs(self._dossier, exist_ok=True)
            with open(os.path.join(self._dossier, time.strftime("echantillons-%H-%M-%S.txt")),
                      "w", encoding="utf-8") as f:
                f.write("\n".join(lignes) + "\n")
        except OSError:
            pass
        self._fin()


def rendre_terminaux_opaques():
    """Essai en direct (echo "10 opaque" > ...) : le terminal peint tout son rectangle, le
    dire a Qt lui evite de repeindre les parents dessous. Effet jusqu'a la relance du dock."""
    for widget in QApplication.allWidgets():
        if widget.metaObject().className() == "Konsole::TerminalDisplay":
            widget.setAttribute(Qt.WA_OpaquePaintEvent, True)


def _etat_des_widgets():
    """Ce qui fait remonter une repeinte aux parents : enfant non opaque, effet graphique."""
    opacite = collections.Counter()
    effets = collections.Counter()
    for widget in QApplication.allWidgets():
        classe = widget.metaObject().className()
        if classe in ("Konsole::TerminalDisplay", "Konsole::ScrollBar"):
            opacite["%s visible=%s opaque=%s" % (
                classe, widget.isVisible(), widget.testAttribute(Qt.WA_OpaquePaintEvent))] += 1
        if widget.graphicsEffect() is not None:
            effets["%s visible=%s" % (classe, widget.isVisible())] += 1
    lignes = ["  %4d  %s" % (n, cle) for cle, n in sorted(opacite.items())]
    lignes += ["  %4d  effet graphique pose sur %s" % (n, cle) for cle, n in sorted(effets.items())]
    return lignes


def _nom_evenement(genre):
    try:  # PySide6 : enum Python, dir(QEvent) ne liste pas ses membres
        nom = getattr(QEvent.Type(genre), "name", None)
    except (ValueError, TypeError):
        nom = None
    if isinstance(nom, str):
        return nom
    for nom in dir(QEvent):  # PyQt5 : Type est un entier, ses membres sont sur QEvent
        valeur = getattr(QEvent, nom)
        if isinstance(valeur, QEvent.Type) and int(valeur) == genre:
            return nom
    return str(genre)


def installer(parent=None):
    """La seule ligne a ajouter au demarrage du dock : `echantillonneur.installer()`.
    Garde une reference sur l'objet (sinon ses QTimer seraient detruits)."""
    global _INSTANCE
    _INSTANCE = Echantillonneur()
    return _INSTANCE


_INSTANCE = globals().get("_INSTANCE")  # survit au rechargement a chaud

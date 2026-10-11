# -*- coding: utf-8 -*-
"""Le dock Claude HORS de Spyder : une fenetre a lui, les memes briques que le panneau.

DEMANDE (11/10/2026) : « Crée une petite application autonome qui lance le dock Claude
seul, hors de Spyder. Elle réutilise les briques Qt pures de spyder_claude (mosaique,
compteurs, etat_instances, usage) et spyder_konsole/konsole_view.py, avec ses propres
onglets et une configuration QSettings. Ne pas toucher au plugin spyder_claude/spyder/ » ;
puis « je voudrais egalement pouvoir reprendre toutes les sessions où elles en sont après
une fermeture / reouverture ».

⚠ RECOPIE, PAS PARTAGE. La logique des sessions (ouverture, voile de lancement, bandeau de
nouvelle session, titres, battement du registre, memorisation et reprise) vit dans
`spyder/main_widget.py`, que la demande interdit de toucher, et ce module-la herite de
PluginMainWidget — il ne s'importe pas sans Spyder. Elle est donc RECOPIEE ici, methode par
methode, avec les memes noms : un correctif a l'une est a reporter a l'autre (la liste des
methodes recopiees est dans la note DONE du 11/10/2026, « dock autonome »).

Ce qui DIFFERE du panneau, et pourquoi :
  - le coin d'onglet (tachymetre + croix) herite de `CoinDOnglet`, mais lui donne une croix
    a nous : la croix native de Qt identifie son onglet par l'EMETTEUR du clic — reparentee,
    son clic serait perdu (cf. `CoinOnglet`) ;
  - le menu contextuel de Dolphin (« Nouveau Claude », « Reprendre Claude ») ouvre un
    onglet ICI quand le dock tourne : cf. `ecouter` et `claude_dolphin.sh` ;
  - la reprise ne relance pas une conversation deja ouverte ailleurs (le dock de Spyder
    rouvre aussi les siennes) : cf. `rouvrir_les_sessions` ;
  - le RENDU est celui de SmartPythonEditor, pris chez lui et non imite (demande du
    11/10/2026 : « Je veux quelque chose de beaucoup plus proche du rendu de
    SmartPythonEditor ! ») : sa feuille d'application, sa palette, la feuille de ses barres
    d'onglets de volets et le fond de son editeur (cf. `theme_smartpythoneditor`), le
    cadre bleu au focus (`_appliquer_cadre`, `_repartir_les_cadres`, recopies), les
    poignees de la mosaique ;
  - pas de barre de titre, comme SmartPythonEditor (demande du 11/10/2026) : ses boutons
    de fenetre et ses poignees (spyder_window_controls) a droite du coin des onglets, apres
    [+][grille] et les interrupteurs de parole et de dictee, independants (cf.
    `basculer_vocal`) ;
  - la liste des sessions s'ecrit en JSON dans le QSettings : une liste de listes ne
    survit pas telle quelle a un fichier INI.
"""

import ast
import configparser
import json
import os
import shutil
import sys
import time
import uuid

import qtawesome as qta
from qtpy.QtCore import QEvent, QProcess, QSettings, QSize, Qt, QTimer
from qtpy.QtGui import QBitmap, QColor, QImage, QPainter, QRegion
from qtpy.QtNetwork import QLocalServer, QLocalSocket
from qtpy.QtWidgets import (QApplication, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                            QMainWindow, QPushButton, QSizePolicy, QStyle,
                            QStyleOptionTab, QStylePainter, QTabBar, QTabWidget,
                            QToolButton, QVBoxLayout, QWidget)

from spyder_claude import etat_instances, usage
from spyder_claude.compteurs import BandeauUsage
from spyder_claude.mosaique import Cellule, Mosaique
from spyder_claude.spyder.onglet_compteur import CoinDOnglet
from spyder_konsole import konsole_view

try:   # les controles de fenetre de SmartPythonEditor ; absents : barre de titre du systeme
    from spyder_window_controls.spyder.resize import ResizeGrips
    from spyder_window_controls.spyder.widgets import HoverButton, glyph_icon, hover_icon
except ImportError:
    ResizeGrips = None


def chemin_du_canal():
    """Le socket du dock, ou `claude_dolphin.sh` depose ses demandes (cf. `ecouter`).

    Dans XDG_RUNTIME_DIR, 0700 a l'utilisateur : seul son propre compte peut y ecrire. Un
    port TCP local a ete ecarte pour cette raison — le compte isole claude pourrait s'y
    connecter et faire ouvrir des sessions sous le compte de l'utilisateur.
    """
    return os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "claude-dock.sock")


def _spyder_ini():
    """Le spyder.ini de SmartPythonEditor, lu par configparser — jamais par CONF (cf.
    `police_de_l_editeur`). Fichier absent : un parseur vide."""
    dossier = os.environ.get("SPYDER_CONFDIR") or os.path.expanduser("~/.config/spyder-py3")
    ini = configparser.RawConfigParser()
    ini.read(os.path.join(dossier, "config", "spyder.ini"), encoding="utf-8")
    return ini


def sessions_de_smartpythoneditor():
    """Les conversations que le dock de SmartPythonEditor a memorisees ([session, dossier]).

    `main_widget._memoriser_les_sessions` les ecrit par `set_conf`, dans la section du
    greffon (`claude_pane`), cle `sessions_ouvertes` : CONF y range la repr Python de la
    liste. Lecture seule ; illisible ou absente : liste vide.
    """
    try:
        valeur = ast.literal_eval(_spyder_ini().get("claude_pane", "sessions_ouvertes"))
    except (configparser.Error, ValueError, SyntaxError, OSError):
        return []
    return valeur if isinstance(valeur, list) else []


def police_de_l_editeur():
    """(famille, taille) de l'editeur de SmartPythonEditor, ou (None, None).

    Lue dans son spyder.ini avec configparser, EN LECTURE SEULE : importer `spyder.config`
    instancierait CONF, qui peut reecrire ~/.config/spyder-py3 pendant que Spyder tourne.
    `font/family` y est une liste de repli (comme `get_family` de Spyder : la premiere
    installee gagne)."""
    from qtpy.QtGui import QFontDatabase
    try:
        ini = _spyder_ini()
        familles = ini.get("appearance", "font/family")
        taille = ini.getint("appearance", "font/size")
    except (configparser.Error, ValueError, OSError):
        return None, None
    try:
        familles = ast.literal_eval(familles)
    except (ValueError, SyntaxError):
        pass
    familles = [familles] if isinstance(familles, str) else list(familles)
    installees = set(QFontDatabase.families())
    famille = next((f for f in familles if f in installees), None)
    return famille, (taille if famille else None)


def theme_smartpythoneditor(application):
    """Le rendu de SmartPythonEditor, pris CHEZ LUI : sa feuille d'application (qdarkstyle
    et les retouches SmartOS du fork : separateurs au fond de l'editeur, volets eclaircis
    au focus), sa palette, la feuille de ses barres d'onglets de volets, le fond de son
    editeur et le conge qu'il peint au pied de l'onglet actif.

    ⚠ JAMAIS CONTRE LA VRAIE CONFIGURATION. Ces objets lisent CONF, et instancier CONF peut
    reecrire ~/.config/spyder-py3 — que Spyder, s'il tourne, reecrira a son tour en se
    fermant. CONF est donc instancie sur une COPIE de spyder.ini (SPYDER_CONFDIR, pose avant
    le premier import de spyder), puis la variable est retiree de l'environnement : les
    shells des sessions en heriteraient, et un Spyder lance depuis l'une d'elles prendrait
    la copie. CONF garde ses chemins : il n'en relit plus la variable.

    Rend un dict (palette, fond, feuille_onglets, peindre_conges) ; sans Spyder dans le
    venv, la seule feuille de qdarkstyle (ce que faisait le dock jusqu'ici) ; None sans
    qdarkstyle non plus.
    """
    copie = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                         "claude-dock", "spyder-py3")
    source = os.path.expanduser("~/.config/spyder-py3/config/spyder.ini")
    try:
        os.makedirs(os.path.join(copie, "config"), exist_ok=True)
        if os.path.isfile(source):
            shutil.copyfile(source, os.path.join(copie, "config", "spyder.ini"))
        os.environ["SPYDER_CONFDIR"] = copie
        from spyder.utils import stylesheet
        from spyder.utils.palette import SpyderPalette
        from spyder.widgets import tabs
        application.setStyleSheet(str(stylesheet.APP_STYLESHEET))
        fond = getattr(stylesheet, "smartos_editor_background",
                       lambda: SpyderPalette.COLOR_BACKGROUND_1)()
        return {"palette": SpyderPalette, "fond": fond,
                "feuille_onglets": str(stylesheet.PANES_TABBAR_STYLESHEET),
                # Ajout du fork (patch_spyder_arrondi_onglet.py) : absent d'un Spyder nu.
                "peindre_conges": getattr(tabs, "_smartos_peindre_conges", None)}
    except Exception:   # Spyder absent, ou casse : le dock doit s'ouvrir quand meme
        pass
    finally:
        os.environ.pop("SPYDER_CONFDIR", None)
    try:
        import qdarkstyle
        from qdarkstyle.dark.palette import DarkPalette
    except ImportError:
        return None
    application.setStyleSheet(qdarkstyle.load_stylesheet(palette=DarkPalette))
    return {"palette": DarkPalette, "fond": DarkPalette.COLOR_BACKGROUND_1,
            "feuille_onglets": "", "peindre_conges": None}


class BarreOnglets(QTabBar):
    """La barre d'onglets des volets de SmartPythonEditor : le nom « pane-tabbar » que
    vise sa feuille, et le conge concave au pied de l'onglet actif (`TabBar.paintEvent`
    du fork). Pas `spyder.widgets.tabs.TabBar` lui-meme : il apporte le glisser-deposer
    ENTRE volets de Spyder, branche sur son `ancestor` et sur `sig_move_tab`, qui n'ont
    pas d'equivalent ici."""

    def __init__(self, parent, peindre_conges=None):
        super().__init__(parent)
        self.setObjectName("pane-tabbar")
        self._peindre_conges = peindre_conges

    def paintEvent(self, evenement):  # noqa: N802 - API Qt
        super().paintEvent(evenement)
        if self._peindre_conges is not None:
            peintre = QPainter(self)
            self._peindre_conges(self, peintre)
            peintre.end()


class CoinOnglet(CoinDOnglet):
    """[tachymetre][croix], pose a droite de chaque onglet : le coin du panneau de Spyder.

    HERITE de `CoinDOnglet` (spyder_claude/spyder/onglet_compteur.py) pour en partager le
    CALAGE du cadran sur le texte du titre (`dimensionner_compteur` + `_suivre`), au lieu
    d'une copie qui avait deja diverge : le dock le centrait sur la croix, 5 px trop haut,
    le defaut corrige dans le panneau le 04/10/2026. Demande de l'utilisateur, 11/10/2026 :
    « fais partager le calage entre le dock et le panneau ». Seule la croix est propre au
    dock (le panneau adopte le `CloseTabButton` de Spyder, que le dock n'a pas).

    La croix retrouve SON onglet au clic en parcourant la barre (`tabButton(i) is coin`) :
    l'index d'un onglet change des qu'on en ferme ou deplace un autre.

    Croix aux mesures de `CloseTabButton` de Spyder (icone 16 px dans 18 x 22) : QTabBar
    tire la hauteur de l'onglet du sizeHint de ce coin, et celui d'un QToolButton nu sous
    la feuille de Spyder (49 x 56) donnait des onglets de 80 px au lieu de 46 (banc du
    11/10/2026 ; remarque de l'utilisateur : « les onglets sont beaucoup trop grand
    verticalement »).

    ⚠ Meme ordre que le panneau : `setTabButton` D'ABORD, `adopter_la_croix` APRES (cf.
    `FenetreClaude._ajouter_onglet` et le module onglet_compteur).
    """

    TAILLE_ICONE = 16  # CloseTabButton.SIZE

    def __init__(self, barre, fermer, icone_croix, survol=None):
        croix = QToolButton(barre)
        croix.setIcon(icone_croix)
        croix.setIconSize(QSize(self.TAILLE_ICONE, self.TAILLE_ICONE))
        croix.setFixedSize(self.TAILLE_ICONE + 2, self.TAILLE_ICONE + 6)
        croix.setStyleSheet(
            "QToolButton { padding: 0px; border: none; border-radius: 3px;"
            " background: transparent; }"
            + ("QToolButton:hover { background: %s; }" % survol if survol else ""))
        croix.setAutoRaise(True)
        croix.setFocusPolicy(Qt.NoFocus)
        croix.setToolTip("Fermer cette instance")
        super().__init__(barre, croix)
        croix.clicked.connect(lambda: fermer(self))
        self.croix_prevue = croix

    #: Le calage herite (`CoinDOnglet._suivre`) suppose les 12 px de `margin-top` que Spyder
    #: pose au-dessus des onglets ; le dock les retire (FenetreClaude._feuille_onglets) : le
    #: texte remonte de 12, ce coin, centre par QTabBar sur l'onglet entier, de 6 seulement.
    #: Sans cette remontee le cadran tombait 6 px sous le titre (banc du 11/10/2026).
    REMONTEE_CADRAN = 6

    def _suivre(self):
        super()._suivre()
        self._compteur.move(self._compteur.x(), self._compteur.y() - self.REMONTEE_CADRAN)

    @property
    def compteur(self):
        return self._compteur


class _CoinDesOnglets(QWidget):
    """Le coin [+][grille]...[fermer] des onglets, aligne en HAUT de la barre.

    Qt pose le coin contre le BAS de la barre, a la hauteur de son sizeHint : avec la feuille de
    Spyder (barre de 46 px, boutons de 24) la rangee descendait de 20 px (11/10/2026 : « tout
    descend en vue onglets »). Il prend donc toute la hauteur de la barre, la rangee en haut."""

    def sizeHint(self):
        taille = super().sizeHint()
        taille.setHeight(max(taille.height(), self.parent().tabBar().sizeHint().height()))
        return taille


class FenetreClaude(QMainWindow):
    """Les instances Claude en onglets, ou en mosaique, et les jauges de consommation."""

    COMMANDE_DEFAUT = "claude -r"
    VITESSE_MAXIMALE_DEFAUT = 50.0
    PERIODE_SONDAGE = 500
    CLE_SESSIONS = "sessions_ouvertes"
    PERIODE_RELANCE = 100
    PLAFOND_RELANCE = 10000
    PLAFOND_VOILE = 10000
    DELAI_CALME = 250
    TITRE_SELECTEUR = "claude · resume"
    DUREE_MINIMALE = 2.0
    PAUSE_VALIDATION_DICTEE = 300
    NOUVELLES_SESSIONS = (
        ("Nouveau superviseur Fable", "--model claude-fable-5-1 -n Superviseur supervise"),
        ("Nouveau worker Fable", "--model claude-fable-5-1"),
        ("Nouveau worker Opus", "--model claude-opus-5-5"),
    )

    #: Boutons de fenetre : les mesures et le style de spyder_window_controls (plugin.py,
    #: `_NO_HOVER_BG_MODELE`), sans sa marge basse, qui ne sert que dans sa barre d'outils.
    BOITE_BOUTON_FENETRE = 21
    #: Cote de TOUS les boutons de la rangee, onglets comme mosaique : celle des boutons
    #: de fenetre (24, mesure du 11/10/2026).
    COTE_BOUTON = 24
    STYLE_BOUTON_FENETRE = (
        "QToolButton { border: none; background: transparent; width: 21px; height: 21px;"
        " margin: 0px; padding: 0px; }"
        "QToolButton:hover, QToolButton:pressed { background: transparent; border: none; }")
    CERCLE_FERMER = "#C0392B"
    ICONES_VOCALES = {"parole": ("mdi.volume-high", "mdi.volume-off", "la synthèse vocale"),
                      "dictee": ("mdi.microphone", "mdi.microphone-off", "la dictée")}

    def __init__(self, reglages=None, dossier=None, fabrique_vue=None, theme=None,
                 script_voix=None):
        """`reglages` : un QSettings (un fichier jetable dans les tests).
        `dossier` : ou s'ouvrent les nouvelles sessions (defaut : reglage, puis $HOME).
        `fabrique_vue(parent)` : remplace VueKonsole — le banc y met une vue inerte.
        `theme` : celui de SmartPythonEditor (`theme_smartpythoneditor`) ; le terminal en
        prend fond et texte, comme `_habillage` du panneau dans Spyder, et le cadre de
        focus ses couleurs. Sans lui, ni cadre ni teinte des poignees.
        `script_voix` : claude-voix.sh, que les boutons de parole et de dictee appellent
        (le banc y met un script factice).
        """
        super().__init__()
        self._reglages = reglages if reglages is not None else QSettings(
            "SmartOS", "claude-dock")
        self._dossier = (dossier or self._reglages.value("dossier", "")
                         or os.path.expanduser("~"))
        # Reglage d'abord, puis la police de l'editeur de SmartPythonEditor (celle que le
        # panneau passe au terminal dans Spyder), puis None : VueKonsole prend le profil.
        famille, taille = police_de_l_editeur()
        self._habillage = {
            "police": self._reglages.value("police", "") or famille,
            "taille_police": int(self._reglages.value("taille_police", 0) or 0) or taille}
        self._theme = theme
        # Les icones a la couleur de celles de Spyder (`ima.MAIN_FG_COLOR`, ICON_1 de sa
        # palette) : la couleur par defaut de qtawesome est un gris sombre, quasi
        # invisible sur le fond (remarque de l'utilisateur, 11/10/2026). La palette de
        # qdarkstyle (repli sans Spyder) n'a pas ICON_1 : son texte en tient lieu.
        self._couleur_icones = theme and getattr(theme["palette"], "ICON_1",
                                                 theme["palette"].COLOR_TEXT_1)
        if theme is not None:
            palette = theme["palette"]
            self._habillage.update(couleur_fond=palette.COLOR_BACKGROUND_1,
                                   couleur_texte=palette.COLOR_TEXT_1,
                                   couleur_fond_intense=palette.COLOR_BACKGROUND_2)
        self._fabrique_vue = fabrique_vue or (
            lambda parent: konsole_view.VueKonsole(parent, **self._habillage))
        self._moteur = fabrique_vue is not None or konsole_view.DISPONIBLE

        self._vues = []
        self._titres = {}
        self._identifiants = {}
        self._identifiants_fermes = set()
        self._etats = {}
        self._etats_osc = {}
        self._dernieres_vitesses = {}
        self._lisseur = usage.Lisseur()
        self._dernieres_fenetres = None
        self._coins = {}
        self._bandeaux = {}
        self._relances = {}
        self._calmes = {}
        self._conversations = {}
        self._sessions_memorisees = None
        self._en_mosaique = False
        self._en_fermeture = False
        self._debut_derniere_session = 0.0
        self._script_voix = script_voix or os.path.expanduser("~/.scripts/claude-voix.sh")
        self._boutons_max = []
        self._boutons_vocaux = {"parole": [], "dictee": []}
        self._etat_vocal = None

        self.setWindowTitle("Claude")
        self.setWindowIcon(self._icone("mdi.robot-outline"))
        # Sans barre de titre seulement si on sait la remplacer : sans spyder_window_controls,
        # la fenetre ne se deplacerait ni ne se redimensionnerait plus.
        if ResizeGrips is not None:
            self.setWindowFlag(Qt.FramelessWindowHint, True)
        centre = QWidget(self)
        disposition = QVBoxLayout(centre)
        disposition.setContentsMargins(0, 0, 0, 0)
        disposition.setSpacing(0)

        self._onglets = QTabWidget(centre)
        self._onglets.setTabBar(BarreOnglets(
            self._onglets, theme and theme["peindre_conges"]))
        self._onglets.setDocumentMode(True)
        self._onglets.setMovable(True)
        self._onglets.tabBar().installEventFilter(self)   # cf. `_teinter_les_onglets`
        # Les titres en entier tant qu'ils tiennent tous ; au-dela, Qt les raccourcit tous
        # par la gauche plutot que de faire defiler.
        self._onglets.tabBar().setElideMode(Qt.ElideLeft)
        self._onglets.setUsesScrollButtons(False)
        coin = _CoinDesOnglets(self._onglets)
        rangee = QHBoxLayout(coin)
        # Memes ecarts que la rangee de la mosaique (Cellule.MARGE entre boutons), et le pixel
        # que `right-corner { top: -1px; right: -1px }` de Spyder retire : les boutons ne
        # bougent pas d'une vue a l'autre (11/10/2026, mesure : x et y identiques).
        rangee.setContentsMargins(0, 1, 1, 0)
        rangee.setSpacing(Cellule.MARGE)
        rangee.setAlignment(Qt.AlignTop)
        # [+][grille][parole][dictee][reduire][agrandir][fermer] (demandes du 11/10/2026).
        vocaux, de_fenetre = self._fabriquer_boutons_de_titre(coin)
        for icone, infobulle, rappel in (
                ("mdi.plus", "Ouvrir une instance Claude", self.ouvrir_session),
                ("mdi.view-grid", "Afficher les instances en mosaïque",
                 lambda: self.basculer_mosaique(True))):
            bouton = QToolButton(coin)
            bouton.setIcon(self._icone(icone))
            bouton.setAutoRaise(True)
            bouton.setToolTip(infobulle)
            bouton.clicked.connect(lambda checked=False, r=rappel: r())
            rangee.addWidget(bouton)
        for bouton in vocaux + de_fenetre:
            rangee.addWidget(bouton)
        # La feuille de Spyder porte ses QToolButton a 44 x 44 : tous a la taille des
        # boutons de fenetre (11/10/2026 : « les boutons sont 2x trop grands en vue onglets »).
        for i in range(rangee.count()):
            rangee.itemAt(i).widget().setFixedSize(self.COTE_BOUTON, self.COTE_BOUTON)
        self._onglets.setCornerWidget(coin, Qt.TopRightCorner)
        disposition.addWidget(self._onglets)

        self._mosaique = Mosaique(centre)
        self._mosaique.hide()
        # Un seul geste de sortie : ici « reduire » et « onglets » reviendraient au meme,
        # il n'y a pas de volet agrandi a rendre. Le bouton de reduction n'est pas pose.
        # Meme rangee que le coin des onglets, dans le meme ordre. Un second jeu : un widget
        # n'a qu'un parent, et la mosaique deplace les siens de cellule en cellule.
        vocaux, de_fenetre = self._fabriquer_boutons_de_titre(self._mosaique)
        for bouton in vocaux + de_fenetre:
            bouton.hide()
        self._mosaique._boutons_de_titre = (
            self._mosaique._bouton_nouveau, self._mosaique._bouton_disposition,
            *vocaux, *de_fenetre)
        self._mosaique._bouton_reduire.hide()
        # Tout en haut, a la meme hauteur : « + » et grille perdent leurs 44 x 44 pour la
        # taille des autres, et l'onglet de cellule monte sans bandeau au-dessus de lui
        # (11/10/2026 : « tout aligner en haut, et enlever la marge au dessus des titres »).
        self._mosaique.hauteur_bandeau = 0
        for bouton in self._mosaique._boutons_de_titre:
            bouton.setFixedSize(self.COTE_BOUTON, self.COTE_BOUTON)
        self._mosaique.poser_icone_disposition(self._icone("mdi.tab", hflip=True))
        self._mosaique.poser_icone_nouveau(self._icone("mdi.plus"))
        self._mosaique.poser_icone_fermer(self._icone("mdi.close"))
        self._mosaique.sig_disposition_demandee.connect(
            lambda: self.basculer_mosaique(False))
        self._mosaique.sig_nouvelle_demande.connect(lambda: self.ouvrir_session())
        self._mosaique.sig_fermeture_demandee.connect(self._fermer_session)
        self._mosaique.poser_pleine_echelle(self.vitesse_maximale())
        disposition.addWidget(self._mosaique)

        self._bandeau = BandeauUsage(centre)
        disposition.addWidget(self._bandeau)
        self.setCentralWidget(centre)

        # Fond des onglets inactifs : alpha 2, pas transparent (cf. main_widget, meme
        # attribut) — `_teinter_les_onglets` reconnait l'onglet a la couleur de son centre.
        self._feuille_onglets = (
            (theme["feuille_onglets"] if theme else "")
            + "QTabBar#pane-tabbar::tab:!selected { background: rgba(0, 0, 0, 2); }"
            # Les 12 px que PanesTabBarStyleSheet pose au-dessus des onglets (place des boutons
            # de coin de Spyder) : retires, onglets en haut comme ceux de la mosaique
            # (11/10/2026 : « les onglets doivent remonter dans la vue onglets »).
            + "QTabBar#pane-tabbar::tab { margin-top: 0px; }"
            # ... et la meme marge, posee par la meme feuille sur les QToolButton de la barre,
            # donc sur la croix : sans ce retrait elle tombait 6 px sous le titre (banc du
            # 11/10/2026, croix y 20-25 pour un texte y 7-24).
            + "QTabBar#pane-tabbar QToolButton { margin-top: 0px; }")
        self._appliquer_cadre(focus=False)
        QApplication.instance().focusChanged.connect(self._suivre_le_focus)

        # Les jeux de couleurs des etats AVANT toute session : qtermwidget met la liste
        # en cache a la premiere lecture (cf. main_widget._preparer_schemas_detat). Pas
        # avec des vues fournies (le banc) : ils s'ecrivent dans le dossier de l'utilisateur.
        if fabrique_vue is None and konsole_view.DISPONIBLE:
            profil = konsole_view.profil_konsole()
            for etat, nom in etat_instances.SCHEMAS.items():
                couleur = etat_instances.COULEURS.get(etat)
                if nom and couleur:
                    konsole_view.preparer_schema(profil, couleur, None, couleur,
                                                 nom_derive=nom)

        geometrie = self._reglages.value("geometrie")
        if geometrie is not None:
            self.restoreGeometry(geometrie)
        else:
            self.resize(900, 700)

        if ResizeGrips is not None:
            self._poignees = ResizeGrips(self)
        self._rafraichir_vocal()

        self._minuteur = QTimer(self)
        self._minuteur.setInterval(self.PERIODE_SONDAGE)
        self._minuteur.timeout.connect(self.relire_le_registre)

    def demarrer(self):
        """Rouvre les conversations de la derniere fois (ou en ouvre une), puis sonde."""
        self.rouvrir_les_sessions()
        if not self._vues:
            self.ouvrir_session()
        self._minuteur.start()

    # ------------------------------------------------------------------ reglages

    def commande_claude(self):
        return self._reglages.value("commande", "") or self.COMMANDE_DEFAUT

    def vitesse_maximale(self):
        try:
            return float(self._reglages.value("vitesse_maximale", 0) or 0) \
                or self.VITESSE_MAXIMALE_DEFAUT
        except (TypeError, ValueError):
            return self.VITESSE_MAXIMALE_DEFAUT

    def sessions(self):
        return list(self._vues)

    def identifiant_de(self, vue):
        return self._identifiants.get(vue)

    # ------------------------------------------------------------------ sessions

    def ouvrir_session(self, dossier=None, conversation=None, nouvelle=False):
        """main_widget.ouvrir_terminal. `conversation` reprend ce session_id par `-r` ;
        `nouvelle` lance `claude` sans selecteur (« Nouveau Claude » de Dolphin)."""
        if not self._moteur:
            self._etat_vide("Le moteur de Konsole n'est pas construit sur cette machine.\n\n"
                            "Lancer le script qtermwidget_binding/build.sh du dépôt "
                            "spyder_konsole, puis relancer claude-dock.")
            return None
        self._retirer_etat_vide()
        dossier = dossier or self._dossier
        identifiant = uuid.uuid4().hex[:12]
        variables = etat_instances.variables_de_session(identifiant, os.getpid())

        vue = self._fabrique_vue(self._onglets)
        titre = "Claude : %s" % (os.path.basename(dossier.rstrip("/")) or "/")
        self._vues.append(vue)
        self._titres[vue] = titre
        self._identifiants[vue] = identifiant
        if self._en_mosaique:
            self._mosaique.disposer(self._elements())
            self._rafraichir_letat_affiche()
        else:
            self._onglets.setCurrentIndex(self._ajouter_onglet(vue))

        vue.sig_titre.connect(lambda texte, v=vue: self._titre_change(v, texte))
        vue.sig_sortie.connect(lambda v=vue: self._relancer_calme(v))
        vue.sig_fond.connect(lambda couleur, v=vue: self._fond_demande(v, couleur))
        vue.sig_termine.connect(lambda code, v=vue: self._session_terminee(v, code))
        self._debut_derniere_session = time.monotonic()
        vue.demarrer(commande=None, repertoire=dossier, environnement=variables)
        if conversation:
            self._conversations[vue] = (conversation, dossier)
            self._lancer(vue, self._commande_nouvelle_session("-r " + conversation))
        elif nouvelle:
            self._lancer(vue, self._commande_nouvelle_session(""))
        else:
            self._lancer(vue, self.commande_claude())
            self._poser_bandeau(vue)
        vue.setFocus()
        return vue

    # ------------------------------------------------------------------ menu de Dolphin

    def ecouter(self):
        """Recoit « Nouveau Claude » / « Reprendre Claude » du menu de Dolphin.

        DEMANDE (11/10/2026) : « les entrée du menu contextuel d'un dossier "Nouveau Claude"
        et "Reprendre Claude" peuvent ouvrir un nouvel onglet dans Claude Dock ? », puis
        « fait le maintenant ». Une ligne par demande, `lancer|reprendre<TAB>dossier`,
        reponse `ok` ; `claude_dolphin.sh` l'envoie par socat et retombe sur sa Konsole
        quand personne ne repond. Faux si un autre dock ecoute deja : c'est lui qui sert.
        """
        chemin = chemin_du_canal()
        sonde = QLocalSocket(self)
        sonde.connectToServer(chemin)
        if sonde.waitForConnected(200):
            sonde.abort()
            return False
        QLocalServer.removeServer(chemin)   # socket orphelin d'un dock mort
        self._serveur = QLocalServer(self)
        self._serveur.newConnection.connect(self._accepter)
        return self._serveur.listen(chemin)

    def _accepter(self):
        while self._serveur.hasPendingConnections():
            client = self._serveur.nextPendingConnection()
            client.readyRead.connect(lambda c=client: self._lire_demande(c))
            client.disconnected.connect(client.deleteLater)

    def _lire_demande(self, client):
        if not client.canReadLine():
            return
        ligne = bytes(client.readLine()).decode("utf-8", "replace")
        client.write(b"ok\n" if self.demande_du_menu(ligne) else b"refus\n")
        client.flush()
        client.disconnectFromServer()

    def demande_du_menu(self, ligne):
        """`lancer<TAB>dossier` : session neuve ; `reprendre<TAB>dossier` : le selecteur."""
        mode, _, dossier = ligne.rstrip("\n").partition("\t")
        if mode not in ("lancer", "reprendre") or not os.path.isdir(dossier):
            return False
        if self.ouvrir_session(dossier, nouvelle=(mode == "lancer")) is None:
            return False
        self._se_montrer()
        return True

    def _se_montrer(self):
        if self.isMinimized():
            self.showNormal()
        # Sous Wayland, raise_/activateWindow de Qt sont sans effet : seul kdotool (KWin)
        # passe au premier plan une fenetre que l'utilisateur n'a pas cliquee.
        QProcess.startDetached("kdotool", ["search", "--class", "claude-dock",
                                           "windowactivate"])

    # ------------------------------------------------------------------ titre de fenetre

    def _fabriquer_boutons_de_titre(self, parent):
        """([parole][dictee], [reduire][agrandir][fermer]) pour `parent` (le coin des onglets
        ou la mosaique) : [+][grille] a gauche, puis les interrupteurs vocaux, les boutons
        de fenetre a droite de tout (demandes du 11/10/2026). Sans spyder_window_controls, la barre de
        titre du systeme est gardee, et la seconde liste est vide."""
        vocaux, de_fenetre = [], []
        if ResizeGrips is not None:
            de_fenetre = [
                self._bouton_de_fenetre(parent, "min", self.showMinimized, "Réduire"),
                self._bouton_de_fenetre(parent, "max", self._basculer_agrandi,
                                        "Agrandir / restaurer"),
                self._bouton_de_fenetre(parent, "close", self.close, "Fermer",
                                        cercle=self.CERCLE_FERMER, glyphe_survol="white")]
            self._boutons_max.append(de_fenetre[1])
        for moitie in ("parole", "dictee"):
            bouton = QToolButton(parent)
            bouton.setAutoRaise(True)
            bouton.clicked.connect(lambda *_ignore, m=moitie: self.basculer_vocal(m))
            self._boutons_vocaux[moitie].append(bouton)
            vocaux.append(bouton)
        return vocaux, de_fenetre

    def _couleurs_de_fenetre(self):
        """(glyphe, rond de survol) : ICON_1 et COLOR_BACKGROUND_5, ceux que
        spyder_window_controls prend dans SmartPythonEditor."""
        palette = self._theme and self._theme["palette"]
        return (self._couleur_icones or self.palette().windowText().color().name(),
                getattr(palette, "COLOR_BACKGROUND_5", "#54687A"))

    def _bouton_de_fenetre(self, parent, genre, rappel, infobulle, cercle=None,
                           glyphe_survol=None):
        glyphe, gris = self._couleurs_de_fenetre()
        bouton = HoverButton(glyph_icon(genre, glyphe),
                             hover_icon(genre, glyphe_survol or glyphe, cercle or gris), parent)
        bouton.setIconSize(QSize(self.BOITE_BOUTON_FENETRE, self.BOITE_BOUTON_FENETRE))
        bouton.setAutoRaise(True)
        bouton.setStyleSheet(self.STYLE_BOUTON_FENETRE)
        bouton.setFocusPolicy(Qt.NoFocus)
        bouton.setToolTip(infobulle)
        # `clicked` passe un booleen : il ne doit atteindre aucun parametre du rappel.
        bouton.clicked.connect(lambda *_ignore: rappel())
        return bouton

    def _basculer_agrandi(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def changeEvent(self, evenement):  # noqa: N802 - API Qt
        """L'icone agrandir / restaurer suit l'etat reel : il change aussi par le
        double-clic, par KWin (raccourci, bord d'ecran) et par `restoreGeometry`."""
        super().changeEvent(evenement)
        if evenement.type() == QEvent.WindowStateChange and self._boutons_max:
            genre = "restore" if self.isMaximized() else "max"
            glyphe, gris = self._couleurs_de_fenetre()
            for bouton in self._boutons_max:
                bouton.set_icons(glyph_icon(genre, glyphe), hover_icon(genre, glyphe, gris))

    def mousePressEvent(self, evenement):  # noqa: N802 - API Qt
        """Sans barre de titre, on deplace la fenetre par les vides de la barre d'onglets,
        du coin et du bandeau : les clics que leurs widgets ignorent remontent jusqu'ici."""
        if (ResizeGrips is not None and evenement.button() == Qt.LeftButton
                and self.windowHandle() is not None
                and self.windowHandle().startSystemMove()):
            evenement.accept()
            return
        super().mousePressEvent(evenement)

    def mouseDoubleClickEvent(self, evenement):  # noqa: N802 - API Qt
        if ResizeGrips is not None and evenement.button() == Qt.LeftButton:
            self._basculer_agrandi()
            evenement.accept()
            return
        super().mouseDoubleClickEvent(evenement)

    # ------------------------------------------------------------------ parole et dictee

    @staticmethod
    def etat_vocal():
        """{"parole": bool, "dictee": bool}, lu dans le registre partage. voix-active est
        l'interrupteur maitre de claude-voix.sh ; chaque moitie s'y coupe par un temoin a
        part (`--parole off` -> parole-coupee), cf. son mode --parole|--dictee."""
        dossier = etat_instances.dossier_etat()
        actif = os.path.exists(os.path.join(dossier, "voix-active"))
        return {moitie: actif and not os.path.exists(
            os.path.join(dossier, moitie + "-coupee")) for moitie in ("parole", "dictee")}

    def basculer_vocal(self, moitie):
        """Allume ou coupe la seule parole, ou la seule dictee. Par claude-voix.sh, jamais en
        ecrivant le registre ici : couper doit aussi faire taire la voix en cours ou fermer
        le micro, et tous les autres lecteurs du registre passent deja par lui."""
        allume = self.etat_vocal()[moitie]
        QProcess.startDetached(self._script_voix,
                               ["--" + moitie, "off" if allume else "on"])

    def _rafraichir_vocal(self):
        etat = self.etat_vocal()
        if etat == self._etat_vocal:
            return
        self._etat_vocal = etat
        for moitie, (allumee, coupee, nom) in self.ICONES_VOCALES.items():
            icone = self._icone(allumee if etat[moitie] else coupee)
            infobulle = ("Couper " if etat[moitie] else "Rallumer ") + nom
            for bouton in self._boutons_vocaux[moitie]:
                bouton.setIcon(icone)
                bouton.setToolTip(infobulle)

    def _icone(self, nom, **options):
        """Les MEMES icones que le panneau dans Spyder (main_widget : `mdi.view-grid`
        plein, `mdi.tab` retournee), a sa couleur."""
        if self._couleur_icones is not None:
            options["color"] = self._couleur_icones
        return qta.icon(nom, **options)

    def _ajouter_onglet(self, vue):
        """Un onglet pour `vue`, avec son coin [tachymetre][croix]. Rend son index.

        Le coin est refait a chaque ajout : `removeTab` (passage en mosaique) detruit les
        boutons de l'onglet retire.
        """
        titre = self._titres.get(vue, "")
        index = self._onglets.addTab(vue, titre or "Claude")
        self._onglets.setTabToolTip(index, titre)
        coin = CoinOnglet(self._onglets.tabBar(), self._fermer_par_coin,
                          self._icone("mdi.close"),
                          self._theme and self._theme["palette"].COLOR_BACKGROUND_6)
        coin.compteur.poser_pleine_echelle(self.vitesse_maximale())
        coin.compteur.poser_valeur(self._dernieres_vitesses.get(vue))
        self._onglets.tabBar().setTabButton(index, QTabBar.RightSide, coin)
        coin.adopter_la_croix(coin.croix_prevue)
        self._coins[vue] = coin
        return index

    def _fermer_par_coin(self, coin):
        barre = self._onglets.tabBar()
        for index in range(barre.count()):
            if barre.tabButton(index, QTabBar.RightSide) is coin:
                self._fermer_session(self._onglets.widget(index))
                return

    def _fermer_session(self, vue):
        """Croix d'onglet ou de cellule : on ARRETE, `_session_terminee` fait le reste."""
        if vue is not None and hasattr(vue, "arreter"):
            vue.arreter()

    def _commande_est_le_selecteur(self):
        return bool({"-r", "--resume"} & set(self.commande_claude().split()))

    def _commande_nouvelle_session(self, options):
        mots = [m for m in self.commande_claude().split()
                if m not in ("-r", "--resume")] or ["claude"]
        return " ".join(mots + options.split())

    def _poser_bandeau(self, vue):
        """Les boutons de nouvelle session au-dessus du selecteur `claude -r`."""
        if not self._commande_est_le_selecteur():
            return
        bandeau = QWidget(vue)
        pile = QVBoxLayout(bandeau)
        pile.setContentsMargins(0, 0, 0, 0)
        for libelle, options in self.NOUVELLES_SESSIONS:
            bouton = QPushButton(libelle, bandeau)
            bouton.clicked.connect(
                lambda checked=False, v=vue, o=options: self._nouvelle_session(v, o))
            pile.addWidget(bouton)
        bandeau.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        vue.layout().insertWidget(0, bandeau)
        self._bandeaux[vue] = bandeau

    def _lancer(self, vue, commande):
        if vue not in self._calmes:
            self._voiler(vue)
        vue.envoyer("clear; " + commande + "\n")

    @staticmethod
    def _ecran(vue):
        disposition = vue.layout()
        return disposition.itemAt(disposition.count() - 1).widget()

    def _voiler(self, vue):
        ecran = self._ecran(vue)
        effet = QGraphicsOpacityEffect(ecran)
        effet.setOpacity(0)
        ecran.setGraphicsEffect(effet)
        calme = QTimer(self)
        calme.setSingleShot(True)
        calme.setInterval(self.DELAI_CALME)
        calme.timeout.connect(lambda v=vue: self._lever_voile(v))
        self._calmes[vue] = calme
        self._differer(vue, self.PLAFOND_VOILE, lambda v=vue: self._lever_voile(v))

    def _relancer_calme(self, vue):
        calme = self._calmes.get(vue)
        if calme is not None and calme.isActive():
            calme.start()

    def _lever_voile(self, vue):
        calme = self._calmes.pop(vue, None)
        if calme is not None:
            calme.stop()
            calme.deleteLater()
        try:
            self._ecran(vue).setGraphicsEffect(None)
        except RuntimeError:
            pass

    def _suivre_titre(self, vue, texte):
        pid_shell = vue.pid_shell()
        if pid_shell <= 0 or vue.pid_premier_plan() == pid_shell:
            return
        calme = self._calmes.get(vue)
        if calme is not None:
            calme.start()
        if texte != self.TITRE_SELECTEUR:
            self._retirer_bandeau(vue)

    def _retirer_bandeau(self, vue):
        bandeau = self._bandeaux.pop(vue, None)
        if bandeau is not None:
            bandeau.setParent(None)
            bandeau.deleteLater()

    def _nouvelle_session(self, vue, options=""):
        self._retirer_bandeau(vue)
        self._voiler(vue)
        vue.envoyer("\x1b")
        minuteur = QTimer(self)
        minuteur.setInterval(self.PERIODE_RELANCE)
        minuteur.timeout.connect(lambda v=vue: self._relancer_si_prete(v))
        self._relances[vue] = [minuteur, 0, options]
        minuteur.start()

    def _relancer_si_prete(self, vue):
        suivi = self._relances.get(vue)
        if suivi is None:
            return
        pid_shell = vue.pid_shell()
        if pid_shell > 0 and vue.pid_premier_plan() == pid_shell:
            self._arreter_relance(vue)
            self._lancer(vue, self._commande_nouvelle_session(suivi[2]))
            vue.setFocus()
            return
        suivi[1] += self.PERIODE_RELANCE
        if suivi[1] >= self.PLAFOND_RELANCE:
            self._arreter_relance(vue)

    def _arreter_relance(self, vue):
        suivi = self._relances.pop(vue, None)
        if suivi is not None:
            suivi[0].stop()
            suivi[0].deleteLater()

    @staticmethod
    def _differer(parent, delai, rappel):
        """Un minuteur ENFANT de `parent` : il meurt avec lui (cf. main_widget._differer)."""
        minuteur = QTimer(parent)
        minuteur.setSingleShot(True)
        minuteur.timeout.connect(rappel)
        minuteur.timeout.connect(minuteur.deleteLater)
        minuteur.start(delai)

    # ------------------------------------------------------------------ titres

    @staticmethod
    def _sans_temoin(texte):
        if texte and (texte[0] == "✳" or "⠀" <= texte[0] <= "⣿"
                      or "◐" <= texte[0] <= "◓"):
            return texte[1:].lstrip()
        return texte

    def _titre_change(self, vue, texte):
        if not texte:
            return
        self._suivre_titre(vue, texte)
        texte = self._sans_temoin(texte)
        self._titres[vue] = texte
        index = self._onglets.indexOf(vue)
        if index >= 0:
            self._onglets.setTabText(index, texte)
            self._onglets.setTabToolTip(index, texte)
        if self._en_mosaique:
            self._mosaique.poser_titre(vue, texte)

    # ------------------------------------------------------------------ fin de session

    def _oublier(self, vue):
        if vue in self._vues:
            self._vues.remove(vue)
        self._titres.pop(vue, None)
        identifiant = self._identifiants.pop(vue, None)
        if identifiant:
            self._identifiants_fermes.add(identifiant)
        self._etats.pop(vue, None)
        self._etats_osc.pop(vue, None)
        self._dernieres_vitesses.pop(vue, None)
        self._conversations.pop(vue, None)
        self._bandeaux.pop(vue, None)
        self._arreter_relance(vue)
        self._coins.pop(vue, None)   # detruit par removeTab avec son onglet

    def _session_terminee(self, vue, _code=0):
        if self._en_fermeture:
            return
        self._oublier(vue)
        if self._en_mosaique:
            self._mosaique.liberer()
            vue.setParent(None)
            vue.deleteLater()
            if self._vues:
                self._mosaique.disposer(self._elements())
                self._rafraichir_letat_affiche()
                return
            self._revenir_aux_onglets()
        else:
            index = self._onglets.indexOf(vue)
            if index >= 0:
                self._onglets.removeTab(index)
            vue.deleteLater()
        self._rouvrir_si_vide()

    def _rouvrir_si_vide(self):
        """Jamais zero session ; garde-fou contre la relance en boucle d'un shell casse."""
        if self._vues or self._onglets.count():
            return
        if time.monotonic() - self._debut_derniere_session < self.DUREE_MINIMALE:
            self._etat_vide(
                "L'instance s'est terminée aussitôt après son ouverture.\n\n"
                "Le bouton + en ouvre une autre ; si le problème persiste, vérifier que "
                "la commande « %s » existe dans le shell." % self.commande_claude())
            return
        self._differer(self, 0, self.ouvrir_session)

    def _etat_vide(self, texte):
        if self._onglets.count():
            return
        message = QLabel(texte, self._onglets)
        message.setAlignment(Qt.AlignCenter)
        message.setWordWrap(True)
        message.setObjectName("etat_vide")
        self._onglets.addTab(message, "—")

    def _retirer_etat_vide(self):
        for index in reversed(range(self._onglets.count())):
            widget = self._onglets.widget(index)
            if widget is not None and widget.objectName() == "etat_vide":
                self._onglets.removeTab(index)
                widget.deleteLater()

    def closeEvent(self, evenement):  # noqa: N802 - API Qt
        """Le battement s'arrete AVANT les sessions : la liste memorisee reste celle
        d'avant la fermeture, c'est elle qui sera reprise (cf. main_widget.on_close)."""
        self._minuteur.stop()
        self._en_fermeture = True
        self._reglages.setValue("geometrie", self.saveGeometry())
        self._reglages.sync()
        for vue in list(self._vues):
            if hasattr(vue, "arreter"):
                vue.arreter(force=True)
        super().closeEvent(evenement)

    # ------------------------------------------------------------------ mosaique

    def _elements(self):
        return [(vue, self._titres.get(vue, "")) for vue in self._vues]

    def en_mosaique(self):
        return self._en_mosaique

    def basculer_mosaique(self, actif=None):
        actif = (not self._en_mosaique) if actif is None else bool(actif)
        if actif == self._en_mosaique or (actif and not self._vues):
            return
        if actif:
            self._passer_en_mosaique()
        else:
            self._revenir_aux_onglets()

    def _passer_en_mosaique(self):
        for index in reversed(range(self._onglets.count())):
            widget = self._onglets.widget(index)
            self._onglets.removeTab(index)
            if widget not in self._vues:
                widget.setParent(None)
                widget.deleteLater()
        self._coins.clear()
        self._onglets.hide()
        self._mosaique.show()
        self._mosaique.disposer(self._elements())
        self._en_mosaique = True
        self._rafraichir_letat_affiche()

    def _revenir_aux_onglets(self):
        actif = self.focusWidget()
        self._mosaique.liberer()
        self._mosaique.hide()
        self._onglets.show()
        courant = 0
        for vue in self._vues:
            index = self._ajouter_onglet(vue)
            if actif is not None and (vue is actif or vue.isAncestorOf(actif)):
                courant = index
        self._en_mosaique = False
        # APRES la bascule, pas avant comme dans main_widget : le focus bouge pendant le
        # retour, et tant que `_en_mosaique` est vrai `_appliquer_cadre` reposerait les
        # feuilles par vue (mesure par TestRendu, 11/10/2026).
        self._rendre_les_cadres_au_panneau()
        if self._onglets.count():
            self._onglets.setCurrentIndex(courant)
        self._rafraichir_letat_affiche()

    def _rafraichir_letat_affiche(self):
        self._mosaique.poser_couleur_poignees(self._habillage.get("couleur_fond"))
        for vue in self._vues:
            self._appliquer_etat(vue, self._etats.get(vue))
            self._appliquer_vitesse(vue, self._dernieres_vitesses.get(vue))
        # Les cellules renaissent a chaque `disposer` : leurs onglets de titre n'ont pas
        # encore la couleur du cadre de leur vue.
        if self._en_mosaique:
            self._repartir_les_cadres()

    # ------------------------------------------------------------------ cadre de focus

    def _appliquer_cadre(self, focus):
        """main_widget._appliquer_cadre : gris au repos, BLEU quand le dock a le clavier.

        Les feuilles sont posees seulement si elles CHANGENT : cette methode suit
        QApplication.focusChanged, et reposer une feuille identique repolit quand meme
        (5 ms, mesure du 05/10/2026 dans Spyder)."""
        if self._theme is None:
            return
        palette = self._theme["palette"]
        couleur = palette.COLOR_ACCENT_3 if focus else palette.COLOR_BACKGROUND_4
        # Sur le widget central : elle descend aux vues, en onglets comme en mosaique.
        feuille = self._feuille_cadre(couleur)
        epais = (f"background-color: {konsole_view.eclaircir(self._theme['fond'])};"
                 if focus else "")
        onglets = (self._feuille_onglets
                   + "QTabBar#pane-tabbar::tab:selected,"
                   f" QTabBar#pane-tabbar::tab:selected:hover {{ border-color: {couleur}; {epais} }}")
        centre = self.centralWidget()
        if feuille != centre.styleSheet():
            centre.setStyleSheet(feuille)
        if onglets != self._onglets.styleSheet():
            self._onglets.setStyleSheet(onglets)
        # Ce que `_smartos_suivre_focus` du fork pose sur la barre du volet actif : lu par
        # PanesTabBarStyleSheet et par le conge. Il n'est branche que par les onglets de
        # Spyder (BaseTabs), jamais construits ici.
        barre = self._onglets.tabBar()
        if bool(barre.property("smartos_focus")) != focus:
            barre.setProperty("smartos_focus", focus)
            barre.style().unpolish(barre)
            barre.style().polish(barre)
            barre.update()
        for vue in self._vues:
            vue.poser_liseret(palette.COLOR_ACCENT_3 if focus else None, double=False)
        if self._en_mosaique:
            self._repartir_les_cadres()

    def _feuille_cadre(self, couleur):
        """Coin haut gauche carre : l'onglet actif s'y raccorde (cf. main_widget)."""
        return ("QFrame#terminal_smartos {"
                f" border: 1px solid {couleur};"
                f" border-radius: {self._theme['palette'].SIZE_BORDER_RADIUS};"
                " border-top-left-radius: 0px; }")

    def _suivre_le_focus(self, _ancien, nouveau):
        self._appliquer_cadre(bool(nouveau is not None and self.isAncestorOf(nouveau)))

    def _repartir_les_cadres(self):
        """main_widget._repartir_les_cadres : en mosaique, bleu sur la SEULE vue qui a le
        clavier. `self.focusWidget()`, pas celui de l'application : il survit a la
        desactivation de la fenetre."""
        if self._theme is None:
            return
        palette = self._theme["palette"]
        actif = self.focusWidget()
        for vue in self._vues:
            a_le_clavier = bool(actif is not None
                                and (vue is actif or vue.isAncestorOf(actif)))
            couleur = palette.COLOR_ACCENT_3 if a_le_clavier else palette.COLOR_BACKGROUND_4
            vue.setStyleSheet(self._feuille_cadre(couleur))
            liseret = palette.COLOR_ACCENT_3 if a_le_clavier else None
            vue.poser_liseret(liseret)
            self._mosaique.poser_cadre(vue, couleur, self._theme["fond"], liseret)

    def _rendre_les_cadres_au_panneau(self):
        """Une feuille posee sur la vue l'emporte sur celle du widget central : sans ce
        menage, les vues garderaient au retour aux onglets le gris de la mosaique."""
        for vue in self._vues:
            vue.setStyleSheet("")

    # ------------------------------------------------------------------ registre

    def relire_le_registre(self):
        """Un battement : etats, demande de focus, dictees, consommation."""
        etats = etat_instances.etats_par_onglet()
        for vue, identifiant in list(self._identifiants.items()):
            etat = etats.get(identifiant, self._etats_osc.get(vue))
            if etat != self._etats.get(vue):
                self._etats[vue] = etat
                self._appliquer_etat(vue, etat)

        self._rafraichir_vocal()
        cible = etat_instances.demande_de_focus()
        if cible:
            self.activer_session(cible)

        dictees = etat_instances.dictees_a_taper(
            set(self._identifiants.values()) | self._identifiants_fermes)
        for vue, identifiant in list(self._identifiants.items()):
            if identifiant in dictees:
                self._taper_la_dictee(vue, dictees.pop(identifiant))
        for identifiant in dictees:
            etat_instances.tracer_dictee(
                "dock autonome : onglet %s ferme avant l'arrivee de la dictee - rien tape"
                % identifiant)

        fenetres = usage.fenetres()
        if fenetres != self._dernieres_fenetres:
            self._dernieres_fenetres = fenetres
            self._bandeau.poser_fenetres(fenetres)

        self._memoriser_les_sessions()

        vitesses = self._lisseur.vitesses()
        for vue, identifiant in list(self._identifiants.items()):
            valeur = vitesses.get(identifiant)
            if valeur != self._dernieres_vitesses.get(vue):
                self._dernieres_vitesses[vue] = valeur
                self._appliquer_vitesse(vue, valeur)

    def _memoriser_les_sessions(self):
        """Ecrit les conversations ouvertes A CHAQUE CHANGEMENT (un plantage ne laisse pas
        le temps d'ecrire a la fermeture). Muet tant que la reprise n'est pas passee."""
        if self._sessions_memorisees is None:
            return
        connues = usage.sessions_par_onglet()
        for vue, identifiant in self._identifiants.items():
            if identifiant in connues:
                self._conversations[vue] = connues[identifiant]
        liste = [list(self._conversations[vue]) for vue in self._vues
                 if vue in self._conversations]
        if liste != self._sessions_memorisees:
            self._sessions_memorisees = liste
            self._reglages.setValue(self.CLE_SESSIONS, json.dumps(liste))
            self._reglages.sync()

    def rouvrir_les_sessions(self):
        """Rouvre les conversations memorisees, et arme la memorisation.

        ⚠ UNE CONVERSATION DEJA PORTEE PAR UNE INSTANCE VIVANTE N'EST PAS REPRISE : le
        dock de Spyder rouvre lui aussi les siennes, et deux `claude -r` sur la meme
        conversation ecriraient le meme transcript a deux mains. Elle reste dans la liste
        memorisee (l'autre dock peut la fermer d'ici le prochain lancement) et l'omission
        est dite dans la barre d'etat.

        Les sessions memorisees par SmartPythonEditor s'y AJOUTENT, apres les siennes et
        sans doublon (remarque de l'utilisateur, 11/10/2026 : « les sessions de
        SmartPythonEditor ne sont pas réouvertes ») ; meme regle pour celles qu'un Spyder
        ouvert porte deja. ⚠ L'inverse n'est pas garde : `main_widget.rouvrir_les_sessions`
        ne saute pas les conversations vivantes, donc un SmartPythonEditor lance APRES le
        dock reprendrait aussi celles que le dock lui a reprises.
        """
        try:
            entrees = json.loads(self._reglages.value(self.CLE_SESSIONS, "") or "[]")
        except (TypeError, ValueError):
            entrees = []
        if not isinstance(entrees, list):
            entrees = []
        a_rouvrir = []
        for entree in entrees + sessions_de_smartpythoneditor():
            try:
                session, dossier = entree
            except (TypeError, ValueError):
                continue
            if session and session not in (s for s, _ in a_rouvrir):
                a_rouvrir.append([session, dossier])
        self._sessions_memorisees = a_rouvrir
        vivantes = usage.sessions_vivantes()
        deja_ouvertes = []
        for session, dossier in a_rouvrir:
            if session in vivantes:
                deja_ouvertes.append(session)
                continue
            vue = self.ouvrir_session(dossier, conversation=session)
            if vue is None:
                break
        if deja_ouvertes:
            self.statusBar().showMessage(
                "Déjà ouverte(s) ailleurs, non reprise(s) : %s" % ", ".join(deja_ouvertes))

    # ------------------------------------------------------------------ etats

    def _appliquer_vitesse(self, vue, valeur):
        self._mosaique.poser_vitesse(vue, valeur)
        coin = self._coins.get(vue)
        if coin is not None:
            coin.compteur.poser_valeur(valeur)

    def _fond_demande(self, vue, couleur):
        """OSC 11 : seul signal d'etat du compte isole (cf. main_widget._fond_demande)."""
        connues = {c.lower(): e for e, c in etat_instances.COULEURS.items() if c}
        self._etats_osc[vue] = etat = connues.get(couleur.lower(), "busy")
        if (self._identifiants.get(vue) not in etat_instances.etats_par_onglet()
                and etat != self._etats.get(vue)):
            self._etats[vue] = etat
            self._appliquer_etat(vue, etat)
            if etat == "waiting":
                self.activer_session(self._identifiants.get(vue))

    def _appliquer_etat(self, vue, etat):
        if hasattr(vue, "appliquer_schema"):
            vue.appliquer_schema(etat_instances.SCHEMAS.get(etat))
        self._onglets.tabBar().update()
        if self._en_mosaique:
            self._mosaique.poser_couleur(vue, etat_instances.COULEURS.get(etat))

    def activer_session(self, identifiant):
        for vue, identifiant_vue in self._identifiants.items():
            if identifiant_vue != identifiant:
                continue
            if not self._en_mosaique:
                index = self._onglets.indexOf(vue)
                if index >= 0:
                    self._onglets.setCurrentIndex(index)
            vue.setFocus()
            # focusChanged se tait quand la fenetre n'est pas active (cf. main_widget).
            self._appliquer_cadre(True)
            return True
        return False

    def _taper_la_dictee(self, vue, texte):
        """Texte, puis un CR SEUL 300 ms plus tard (cf. main_widget._taper_la_dictee)."""
        vue.envoyer(texte)
        self._differer(vue, self.PAUSE_VALIDATION_DICTEE, lambda: vue.envoyer("\r"))

    # ------------------------------------------------------------------ teinte

    def eventFilter(self, objet, evenement):  # noqa: N802 - API Qt
        if evenement.type() == QEvent.Paint and isinstance(objet, QTabBar):
            type(objet).paintEvent(objet, evenement)
            self._teinter_les_onglets(objet)
            return True
        return super().eventFilter(objet, evenement)

    def _teinter_les_onglets(self, barre):
        """La couleur d'etat sur le FOND de chaque onglet (cf. main_widget, meme nom)."""
        peintre = None
        for index in range(barre.count()):
            couleur = etat_instances.COULEURS.get(
                self._etats.get(self._onglets.widget(index)))
            if not couleur:
                continue
            if peintre is None:
                peintre = QStylePainter(barre)
            option = QStyleOptionTab()
            barre.initStyleOption(option, index)
            cadre = option.rect
            forme = QImage(cadre.size(), QImage.Format_ARGB32_Premultiplied)
            forme.fill(Qt.transparent)
            peintre_forme = QPainter(forme)
            peintre_forme.translate(-cadre.topLeft())
            barre.style().drawControl(QStyle.CE_TabBarTabShape, option, peintre_forme,
                                      barre)
            peintre_forme.end()
            fond = forme.pixel(forme.width() // 2, forme.height() // 2)
            masque = QBitmap.fromImage(forme.createMaskFromColor(fond, Qt.MaskOutColor))
            peintre.save()
            peintre.setClipRegion(QRegion(masque).translated(cadre.topLeft()))
            peintre.fillRect(cadre, QColor(couleur))
            peintre.restore()
            peintre.drawControl(QStyle.CE_TabBarTabLabel, option)
        if peintre is not None:
            peintre.end()


def main(argv=None):
    """`claude-dock [dossier]` : le dossier ou s'ouvrent les nouvelles sessions."""
    argv = sys.argv if argv is None else argv
    application = QApplication.instance() or QApplication(argv)
    application.setApplicationName("claude-dock")
    application.setDesktopFileName("claude-dock")
    dossier = os.path.abspath(argv[1]) if len(argv) > 1 else None
    theme = theme_smartpythoneditor(application)
    fenetre = FenetreClaude(dossier=dossier, theme=theme)
    fenetre.show()
    fenetre.demarrer()
    fenetre.ecouter()
    return application.exec_()

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
  - le coin d'onglet (tachymetre + croix) est un widget a nous, pas `CoinDOnglet` : celui-ci
    adopte la croix que Spyder pose sur chaque onglet, et la croix native de Qt identifie
    son onglet par l'EMETTEUR du clic — reparentee, son clic serait perdu ;
  - la reprise ne relance pas une conversation deja ouverte ailleurs (le dock de Spyder
    rouvre aussi les siennes) : cf. `rouvrir_les_sessions` ;
  - pas de cadre de focus ; la feuille de style, les couleurs du terminal et sa police sont
    celles de SmartPythonEditor, retrouvees SANS importer Spyder (cf.
    `appliquer_style_smartpythoneditor`, `police_de_l_editeur`) ;
  - la liste des sessions s'ecrit en JSON dans le QSettings : une liste de listes ne
    survit pas telle quelle a un fichier INI.
"""

import json
import os
import sys
import time
import uuid

import qtawesome as qta
from qtpy.QtCore import QEvent, QSettings, Qt, QTimer
from qtpy.QtGui import QBitmap, QColor, QImage, QPainter, QRegion
from qtpy.QtWidgets import (QApplication, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                            QMainWindow, QPushButton, QSizePolicy, QStyle,
                            QStyleOptionTab, QStylePainter, QTabBar, QTabWidget,
                            QToolButton, QVBoxLayout, QWidget)

from spyder_claude import etat_instances, usage
from spyder_claude.compteurs import BandeauUsage, Compteur
from spyder_claude.mosaique import ESPACE_COMPTEUR_CROIX, Mosaique, dimensionner_compteur
from spyder_konsole import konsole_view


def police_de_l_editeur():
    """(famille, taille) de l'editeur de SmartPythonEditor, ou (None, None).

    Lue dans son spyder.ini avec configparser, EN LECTURE SEULE : importer `spyder.config`
    instancierait CONF, qui peut reecrire ~/.config/spyder-py3 pendant que Spyder tourne.
    `font/family` y est une liste de repli (comme `get_family` de Spyder : la premiere
    installee gagne)."""
    import ast
    import configparser
    from qtpy.QtGui import QFontDatabase
    dossier = os.environ.get("SPYDER_CONFDIR") or os.path.expanduser("~/.config/spyder-py3")
    ini = configparser.RawConfigParser()
    try:
        ini.read(os.path.join(dossier, "config", "spyder.ini"), encoding="utf-8")
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


def appliquer_style_smartpythoneditor(application):
    """La feuille de style de SmartPythonEditor : celle de qdarkstyle sur la palette sombre,
    que `AppStylesheet` de Spyder reprend telle quelle avant ses retouches de police. Rend
    la palette (couleurs du terminal), ou None sans qdarkstyle."""
    try:
        import qdarkstyle
        from qdarkstyle.dark.palette import DarkPalette
    except ImportError:
        return None
    application.setStyleSheet(qdarkstyle.load_stylesheet(palette=DarkPalette))
    return DarkPalette


class CoinOnglet(QWidget):
    """[tachymetre][croix], pose a droite de chaque onglet.

    La croix retrouve SON onglet au clic en parcourant la barre (`tabButton(i) is coin`) :
    l'index d'un onglet change des qu'on en ferme ou deplace un autre.
    """

    def __init__(self, barre, fermer):
        super().__init__(barre)
        disposition = QHBoxLayout(self)
        disposition.setContentsMargins(0, 0, 0, 0)
        disposition.setSpacing(ESPACE_COMPTEUR_CROIX)
        self.compteur = Compteur(self)
        dimensionner_compteur(self.compteur, aligne_sur_onglet=False)
        disposition.addWidget(self.compteur)
        croix = QToolButton(self)
        croix.setIcon(qta.icon("mdi.close"))
        croix.setAutoRaise(True)
        croix.setFocusPolicy(Qt.NoFocus)
        croix.setToolTip("Fermer cette instance")
        croix.clicked.connect(lambda: fermer(self))
        disposition.addWidget(croix)


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

    def __init__(self, reglages=None, dossier=None, fabrique_vue=None, palette=None):
        """`reglages` : un QSettings (un fichier jetable dans les tests).
        `dossier` : ou s'ouvrent les nouvelles sessions (defaut : reglage, puis $HOME).
        `fabrique_vue(parent)` : remplace VueKonsole — le banc y met une vue inerte.
        `palette` : celle de la feuille de style (`appliquer_style_smartpythoneditor`) ; le
        terminal en prend fond et texte, comme `_habillage` du panneau dans Spyder.
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
        if palette is not None:
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

        self.setWindowTitle("Claude")
        self.setWindowIcon(qta.icon("mdi.robot-outline"))
        centre = QWidget(self)
        disposition = QVBoxLayout(centre)
        disposition.setContentsMargins(0, 0, 0, 0)
        disposition.setSpacing(0)

        self._onglets = QTabWidget(centre)
        self._onglets.setDocumentMode(True)
        self._onglets.setMovable(True)
        self._onglets.tabBar().installEventFilter(self)   # cf. `_teinter_les_onglets`
        coin = QWidget(self._onglets)
        rangee = QHBoxLayout(coin)
        rangee.setContentsMargins(0, 0, 0, 0)
        rangee.setSpacing(0)
        for icone, infobulle, rappel in (
                ("mdi.view-grid-outline", "Afficher les instances en mosaïque",
                 lambda: self.basculer_mosaique(True)),
                ("mdi.plus", "Ouvrir une instance Claude", self.ouvrir_session)):
            bouton = QToolButton(coin)
            bouton.setIcon(qta.icon(icone))
            bouton.setAutoRaise(True)
            bouton.setToolTip(infobulle)
            bouton.clicked.connect(lambda checked=False, r=rappel: r())
            rangee.addWidget(bouton)
        self._onglets.setCornerWidget(coin, Qt.TopRightCorner)
        disposition.addWidget(self._onglets)

        self._mosaique = Mosaique(centre)
        self._mosaique.hide()
        # Un seul geste de sortie : ici « reduire » et « onglets » reviendraient au meme,
        # il n'y a pas de volet agrandi a rendre. Le bouton de reduction n'est pas pose.
        self._mosaique._boutons_de_titre = (self._mosaique._bouton_disposition,
                                            self._mosaique._bouton_nouveau)
        self._mosaique._bouton_reduire.hide()
        self._mosaique.poser_icone_disposition(qta.icon("mdi.tab"))
        self._mosaique.poser_icone_nouveau(qta.icon("mdi.plus"))
        self._mosaique.poser_icone_fermer(qta.icon("mdi.close"))
        self._mosaique.sig_disposition_demandee.connect(
            lambda: self.basculer_mosaique(False))
        self._mosaique.sig_nouvelle_demande.connect(lambda: self.ouvrir_session())
        self._mosaique.sig_fermeture_demandee.connect(self._fermer_session)
        self._mosaique.poser_pleine_echelle(self.vitesse_maximale())
        disposition.addWidget(self._mosaique)

        self._bandeau = BandeauUsage(centre)
        disposition.addWidget(self._bandeau)
        self.setCentralWidget(centre)

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

    def ouvrir_session(self, dossier=None, conversation=None):
        """main_widget.ouvrir_terminal. `conversation` reprend ce session_id par `-r`."""
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
        else:
            self._lancer(vue, self.commande_claude())
            self._poser_bandeau(vue)
        vue.setFocus()
        return vue

    def _ajouter_onglet(self, vue):
        """Un onglet pour `vue`, avec son coin [tachymetre][croix]. Rend son index.

        Le coin est refait a chaque ajout : `removeTab` (passage en mosaique) detruit les
        boutons de l'onglet retire.
        """
        titre = self._titres.get(vue, "")
        index = self._onglets.addTab(vue, self._titre_court(titre) or "Claude")
        self._onglets.setTabToolTip(index, titre)
        coin = CoinOnglet(self._onglets.tabBar(), self._fermer_par_coin)
        coin.compteur.poser_pleine_echelle(self.vitesse_maximale())
        coin.compteur.poser_valeur(self._dernieres_vitesses.get(vue))
        self._onglets.tabBar().setTabButton(index, QTabBar.RightSide, coin)
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
    def _titre_court(texte):
        if not texte:
            return ""
        return texte if len(texte) <= 24 else "…" + texte[-23:]

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
            self._onglets.setTabText(index, self._titre_court(texte))
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
        if self._onglets.count():
            self._onglets.setCurrentIndex(courant)
        self._rafraichir_letat_affiche()

    def _rafraichir_letat_affiche(self):
        for vue in self._vues:
            self._appliquer_etat(vue, self._etats.get(vue))
            self._appliquer_vitesse(vue, self._dernieres_vitesses.get(vue))

    # ------------------------------------------------------------------ registre

    def relire_le_registre(self):
        """Un battement : etats, demande de focus, dictees, consommation."""
        etats = etat_instances.etats_par_onglet()
        for vue, identifiant in list(self._identifiants.items()):
            etat = etats.get(identifiant, self._etats_osc.get(vue))
            if etat != self._etats.get(vue):
                self._etats[vue] = etat
                self._appliquer_etat(vue, etat)

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
        """
        try:
            entrees = json.loads(self._reglages.value(self.CLE_SESSIONS, "") or "[]")
        except (TypeError, ValueError):
            entrees = []
        a_rouvrir = []
        for entree in entrees if isinstance(entrees, list) else []:
            try:
                session, dossier = entree
            except (TypeError, ValueError):
                continue
            if session:
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
    palette = appliquer_style_smartpythoneditor(application)
    fenetre = FenetreClaude(dossier=dossier, palette=palette)
    fenetre.show()
    fenetre.demarrer()
    return application.exec_()

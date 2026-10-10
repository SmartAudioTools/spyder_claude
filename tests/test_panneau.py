# -*- coding: utf-8 -*-
"""Le PANNEAU lui-meme, monte hors de Spyder.

CE BANC N'EXISTAIT PAS, et c'est ce qui a laisse passer trois defauts pendant toute la
campagne mosaique du 27 au 31/07/2026. Les bancs precedents couvraient la mosaique et le
moteur Konsole — deux modules sans dependance a Spyder, donc faciles a eprouver — mais
jamais la classe qui les assemble. Les trois defauts vivaient exactement la, et aucun ne
se voyait a l'ecran :

  1. `ACTION_AGRANDIR` n'etait defini que dans la sous-classe Claude. Le panneau Terminal
     lisait donc `self.ACTION_AGRANDIR` sur une classe qui ne l'a pas — dans un
     `try/except Exception` qui rendait None, donc en silence. Son bouton de reduction
     retombait sur le repli, celui-la meme qui produit l'etat intermediaire que
     l'utilisateur avait signale le 27/07 (« on est oblige de reduire deux fois »).
  2. `ouvrir_terminal` n'ajoutait rien a `self._vues`. Seule la surcharge de Claude le
     faisait. Or `_ajuster_affichage` decide d'etaler ou non sur `bool(self._vues)` : la
     mosaique du panneau Terminal ne pouvait donc JAMAIS s'afficher.
  3. `QTimer` n'etait pas importe au niveau du module, alors que la pose differee du
     bouton de disposition l'utilise. Chemin rarement pris — il ne sert que si le coin
     n'existe pas encore — donc une NameError qui attendait son jour.

Les trois sont invisibles a l'oeil et evidents ici. C'est la raison d'etre du fichier.

JUMEAU DE spyder_konsole/tests/test_panneau.py, comme les deux greffons le sont
depuis le 31/07/2026 — a une classe pres, TestRegistreDetat, qui n'a pas d'equivalent
la-bas : lire le registre de claude-window.sh est precisement ce que ce panneau ajoute a un
panneau de terminaux ordinaire.

POURQUOI CE BANC PEUT EXISTER, alors qu'un widget de greffon semble exiger Spyder complet :
il suffit que la classe porte un `CONF_SECTION`, seule chose que reclame le mixin de
configuration. Le panneau accepte `plugin=None` — il ne va jamais chercher dans le registre
des greffons, c'est precisement le decoupage qui le rend testable.

⚠ AUCUNE SESSION N'EST OUVERTE ICI. `ouvrir_terminal` lance un vrai shell sur un vrai pty ;
on ne veut ni la lenteur ni les processus orphelins dans un banc. On monte donc de fausses
vues, ce qui suffit : les defauts cherches sont dans la mecanique du panneau, pas dans le
moteur — lui a deja son banc.
"""

import io
import os
import shutil
import sys
import tempfile
import time
import unittest
import warnings

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from qtpy.QtCore import QEvent, QPointF, Signal  # noqa: E402
from qtpy.QtGui import QEnterEvent  # noqa: E402
from qtpy.QtWidgets import QApplication, QTabBar, QVBoxLayout, QWidget  # noqa: E402

APP = QApplication.instance() or QApplication([])

from spyder_claude import etat_instances, usage  # noqa: E402
from spyder_claude.spyder.main_widget import PanneauClaude  # noqa: E402
from spyder_claude.spyder.onglet_compteur import CoinDOnglet  # noqa: E402

# Monter plusieurs panneaux dans le meme processus fait rouspeter le registre de Spyder :
# chaque instance reenregistre ses boutons sous les memes identifiants. C'est attendu ici —
# hors banc, il n'y a qu'un panneau par greffon — et cinquante lignes d'avertissement
# noieraient le resultat des tests.
#
# ⚠ POSE APRES L'IMPORT DE SPYDER, ET PAS AVANT : Spyder repose ses propres filtres
# a l'import, ce qui effacait celui-ci (mesure du 31/07/2026 — filtre en tete de
# fichier, cinquante avertissements quand meme).
warnings.filterwarnings("ignore", message=r"There already exists a reference")



class Banc(PanneauClaude):
    """Le panneau reel, a un attribut pres : celui qu'exige le mixin de configuration."""

    CONF_SECTION = "claude_pane"


class FausseVue(QWidget):
    """Ce que le panneau attend d'une vue, et rien de plus."""

    sig_sortie = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.arrets = []
        self.envois = []
        #: (pid du shell, pid au premier plan) — egaux quand le shell attend.
        self.pids = (42, 42)
        # Comme VueKonsole : un layout vertical dont le « terminal » occupe le fond,
        # c'est la que le panneau insere le bandeau de nouvelle session.
        disposition = QVBoxLayout(self)
        disposition.addWidget(QWidget(self))

    def arreter(self, force=False):
        self.arrets.append(force)

    def poser_liseret(self, couleur):
        self._liseret = couleur

    def envoyer(self, texte):
        self.envois.append(texte)

    def pid_shell(self):
        return self.pids[0]

    def pid_premier_plan(self):
        return self.pids[1]


def panneau():
    p = Banc(name="claude_pane", plugin=None, parent=None)
    p.setup()
    return p


class TestMontage(unittest.TestCase):
    """Ce que le panneau doit porter pour que ses propres methodes fonctionnent."""

    def setUp(self):
        self.p = panneau()

    def tearDown(self):
        self.p.deleteLater()

    def test_setup_ne_leve_pas(self):
        """DEFAUT 3 : la pose differee du bouton de disposition utilise QTimer.

        Sans l'import au niveau du module, `setup()` leve NameError des que le coin des
        onglets n'existe pas encore — ce qui est le cas ici, et l'est aussi dans Spyder
        selon le moment ou le panneau est monte.
        """
        self.assertIsNotNone(self.p._bouton_disposition)

    def test_action_agrandir_est_definie(self):
        """DEFAUT 1 : lue par `_action_agrandissement`, elle doit exister sur CETTE classe.

        On la cherche dans le dictionnaire de la classe et de ses parents jusqu'a
        PluginMainWidget exclu : `getattr` seul serait satisfait par un attribut herite
        d'une sous-classe, ce qui est exactement le defaut d'origine.
        """
        self.assertTrue(
            any("ACTION_AGRANDIR" in c.__dict__
                for c in type(self.p).__mro__
                if c.__module__.startswith("spyder_claude")),
            "ACTION_AGRANDIR doit etre definie par le greffon lui-meme")
        self.assertIsInstance(self.p.ACTION_AGRANDIR, str)

    def test_action_agrandissement_ne_leve_pas(self):
        """Hors Spyder l'action est introuvable ; la methode doit rendre None, pas lever."""
        self.assertIsNone(self.p._action_agrandissement())


class TestListeDesSessions(unittest.TestCase):
    """`_vues` est le seul etat vrai dans les deux modes ; tout en depend."""

    def setUp(self):
        self.p = panneau()

    def tearDown(self):
        self.p.deleteLater()

    def _ouvrir(self, titre="essai"):
        """Reproduit ce que fait `ouvrir_terminal` APRES la creation de la vue.

        On ne l'appelle pas : elle lance un vrai shell. Ce qui est teste ici est
        l'invariant qu'elle doit tenir, pas le moteur.
        """
        vue = FausseVue(self.p._onglets)
        self.p._onglets.addTab(vue, titre)
        self.p._vues.append(vue)
        self.p._titres[vue] = titre
        return vue

    def test_ouvrir_terminal_alimente_les_vues(self):
        """DEFAUT 2 : sans cette ligne, la mosaique du panneau ne s'affiche jamais.

        On lit la SOURCE de la methode plutot que de l'executer, faute de pouvoir lancer
        un shell dans un banc. C'est une verification faible en soi — mais elle porte sur
        la ligne exacte dont l'absence a rendu la mosaique inatteignable, et elle echoue
        bien si on la retire.
        """
        import inspect
        source = inspect.getsource(PanneauClaude.ouvrir_terminal)
        self.assertIn("self._vues.append(vue)", source)

    def test_nombre_de_sessions_ignore_longlet_dattente(self):
        """L'onglet d'attente n'est pas une session : le greffon en ouvrirait zero.

        `on_mainwindow_visible` n'ouvre une session que si le compte est nul. Compter les
        ONGLETS le rendait non nul des qu'un onglet d'attente etait affiche — donc un
        panneau qui reste vide.
        """
        self.p._etat_vide("rien ici")
        self.assertEqual(self.p._onglets.count(), 1)
        self.assertEqual(self.p.nombre_de_sessions(), 0)

    def test_nombre_de_sessions_compte_en_mosaique(self):
        """En mosaique la barre d'onglets est vide : compter les onglets rendrait zero."""
        self._ouvrir()
        self._ouvrir()
        self.p._passer_en_mosaique()
        self.assertEqual(self.p._onglets.count(), 0)
        self.assertEqual(self.p.nombre_de_sessions(), 2)

    def test_retour_aux_onglets_sur_la_session_qui_avait_le_clavier(self):
        """Demande de l'utilisateur, 10/10/2026 : « le passage en onglet ne va pas sur
        l'onglet qui a le focus, il le faudrait ». Le retour tombait toujours sur l'onglet 0.

        Le changement de focus est simule par l'appel du slot branche sur
        `QApplication.focusChanged` : hors ecran, le vrai focus ne se donne pas.
        """
        self._ouvrir("a")
        self._ouvrir("b")
        troisieme = self._ouvrir("c")
        self.p._passer_en_mosaique()
        self.p._suivre_le_focus(None, troisieme)
        self.p._revenir_aux_onglets()
        self.assertIs(self.p._onglets.currentWidget(), troisieme)

    def test_retour_aux_onglets_apres_fermeture_de_la_session_active(self):
        """La vue retenue est fermee : retour sur le premier onglet, pas d'erreur."""
        premiere = self._ouvrir("a")
        seconde = self._ouvrir("b")
        self.p._passer_en_mosaique()
        self.p._suivre_le_focus(None, seconde)
        self.p._oublier(seconde)
        self.p._revenir_aux_onglets()
        self.assertIs(self.p._onglets.currentWidget(), premiere)

    def test_la_couleur_detat_teint_le_fond_de_longlet(self):
        """Demande de l'utilisateur, 10/10/2026 : « la coloration de la console ne se
        repercute pas sur l'onglet en mode onglets, or il le faudrait ».

        Lu sur les PIXELS de la barre, juste a droite du bord gauche de l'onglet (dans
        le remplissage, avant le texte) ; l'onglet d'une session « busy » garde son fond.
        """
        from qtpy.QtGui import QColor
        attente = self._ouvrir("a")
        occupee = self._ouvrir("b")
        self.p.resize(600, 300)
        self.p.show()
        for vue, etat in ((attente, "waiting"), (occupee, "busy")):
            self.p._etats[vue] = etat
            self.p._appliquer_etat(vue, etat)
        QApplication.processEvents()
        barre = self.p._onglets.tabBar()
        image = barre.grab().toImage()

        def fond(index):
            cadre = barre.tabRect(index)
            return image.pixelColor(cadre.left() + 4, cadre.center().y()).name()

        self.assertEqual(fond(0), QColor(etat_instances.COULEURS["waiting"]).name())
        self.assertNotIn(fond(1), {QColor(c).name()
                                   for c in etat_instances.COULEURS.values() if c})
        # La croix de fermeture ne garde pas son carre gris sur l'onglet teinte.
        bouton = barre.tabButton(0, QTabBar.RightSide)
        croix = bouton.croix() if hasattr(bouton, "croix") else bouton
        from spyder.utils.palette import SpyderPalette
        gris = {QColor(c).name() for c in (SpyderPalette.COLOR_BACKGROUND_4,
                                           SpyderPalette.COLOR_BACKGROUND_5)}
        haut_gauche = croix.mapTo(barre, croix.rect().topLeft())
        pixels = {image.pixelColor(haut_gauche.x() + x, haut_gauche.y() + y).name()
                  for x in range(croix.width()) for y in range(croix.height())}
        self.assertFalse(pixels & gris, pixels & gris)

    def test_oublier_purge_la_vue(self):
        vue = self._ouvrir()
        self.p._oublier(vue)
        self.assertNotIn(vue, self.p._vues)
        self.assertNotIn(vue, self.p._titres)


class TestBascule(unittest.TestCase):
    """Aller-retour mosaique / onglets, sans passer par Spyder."""

    def setUp(self):
        self.p = panneau()
        self.vues = []
        for titre in ("un", "deux"):
            vue = FausseVue(self.p._onglets)
            self.p._onglets.addTab(vue, titre)
            self.p._vues.append(vue)
            self.p._titres[vue] = titre
            self.vues.append(vue)

    def tearDown(self):
        self.p.deleteLater()

    def test_agrandir_etale_puis_reduire_rassemble(self):
        self.p.set_maximized_state(True)
        self.assertTrue(self.p.en_mosaique())
        self.assertEqual(self.p._onglets.count(), 0)

        self.p.set_maximized_state(False)
        self.assertFalse(self.p.en_mosaique())
        self.assertEqual(self.p._onglets.count(), 2)

    def test_les_vues_survivent_a_laller_retour(self):
        """La bascule DEPLACE les vues ; elle n'en detruit ni n'en recree aucune."""
        avant = list(self.p._vues)
        self.p.set_maximized_state(True)
        self.p.set_maximized_state(False)
        self.assertEqual(self.p._vues, avant)

    def test_bouton_de_disposition_visible_seulement_agrandi_en_onglets(self):
        """Il proposerait sinon un etat inatteignable, ou serait cache par la mosaique.

        ⚠ ON LIT `isHidden()`, PAS `isVisible()`. Un widget dont aucun ancetre n'est
        affiche est toujours `isVisible() == False`, et le panneau d'un banc n'est jamais
        montre a l'ecran : l'assertion aurait ete verte quoi qu'il arrive — un test qui ne
        peut pas echouer, donc qui ne prouve rien.
        """
        self.assertTrue(self.p._bouton_disposition.isHidden())
        self.p.set_maximized_state(True)          # agrandi -> mosaique : masque
        self.assertTrue(self.p._bouton_disposition.isHidden())
        self.p._basculer_disposition()            # agrandi -> onglets : visible
        self.assertFalse(self.p.en_mosaique())
        self.assertFalse(self.p._bouton_disposition.isHidden())

    def test_la_preference_survit_a_lagrandissement(self):
        """Sans `_mosaique_voulue`, le retour aux onglets serait aussitot annule."""
        self.p.set_maximized_state(True)
        self.p._basculer_disposition()
        self.p._ajuster_affichage()
        self.assertFalse(self.p.en_mosaique())


class TestFermeture(unittest.TestCase):

    def setUp(self):
        self.p = panneau()

    def tearDown(self):
        self.p.deleteLater()

    def test_on_close_arrete_les_sessions_en_mosaique(self):
        """⚠ ON PARCOURT LES SESSIONS, PAS LES ONGLETS.

        En mosaique la barre est vide : une boucle sur les onglets ne fermerait rien, et
        les shells survivraient a la fermeture de Spyder.
        """
        vues = []
        for titre in ("un", "deux"):
            vue = FausseVue(self.p._onglets)
            self.p._onglets.addTab(vue, titre)
            self.p._vues.append(vue)
            self.p._titres[vue] = titre
            vues.append(vue)
        self.p._passer_en_mosaique()
        self.assertEqual(self.p._onglets.count(), 0)

        self.p.on_close()
        for vue in vues:
            self.assertEqual(vue.arrets, [True], "session non arretee")


class TestBandeauNouvelleSession(unittest.TestCase):
    """Les boutons de nouvelle session au-dessus du selecteur `claude -r` (04/10/2026).

    Le selecteur de Claude Code n'a aucune entree « nouvelle session » : ces boutons la
    fournissent, un par role et modele. `ouvrir_terminal` lançant un vrai shell, on reproduit ici ce qu'elle fait
    autour du bouton — et on verifie par la source qu'elle le fait, comme
    TestListeDesSessions le fait deja pour `_vues`.
    """

    def setUp(self):
        self.p = panneau()

    def tearDown(self):
        self.p.deleteLater()

    def _session(self, identifiant="aaa"):
        vue = FausseVue(self.p._onglets)
        self.p._onglets.addTab(vue, "essai")
        self.p._vues.append(vue)
        self.p._titres[vue] = "essai"
        self.p._identifiants[vue] = identifiant
        return vue

    def _bouton(self, vue, libelle):
        from qtpy.QtWidgets import QPushButton
        for bouton in self.p._bandeaux[vue].findChildren(QPushButton):
            if bouton.text() == libelle:
                return bouton
        self.fail(libelle)

    def test_ouvrir_terminal_pose_le_bandeau(self):
        import inspect
        source = inspect.getsource(PanneauClaude.ouvrir_terminal)
        self.assertIn("self._poser_bandeau(vue)", source)

    def test_le_bandeau_nait_au_dessus_du_terminal(self):
        """Pleine largeur au-dessus du terminal = premiere ligne du layout de la vue."""
        vue = self._session()
        self.p._poser_bandeau(vue)
        bandeau = self.p._bandeaux[vue]
        self.assertIs(vue.layout().itemAt(0).widget(), bandeau)

    def test_les_boutons_sont_empiles_verticalement(self):
        """Demande du 04/10/2026 : « stacké verticalement par horizontalement »."""
        vue = self._session()
        self.p._poser_bandeau(vue)
        self.p.show()
        self.p._onglets.setCurrentWidget(vue)
        QApplication.processEvents()
        boutons = [self._bouton(vue, libelle) for libelle, _o in self.p.NOUVELLES_SESSIONS]
        for haut, bas in zip(boutons, boutons[1:]):
            self.assertEqual(haut.x(), bas.x())
            self.assertGreaterEqual(bas.y(), haut.y() + haut.height())

    def test_le_bandeau_ne_mange_pas_la_hauteur_du_terminal(self):
        """Retour du 04/10/2026 : boutons « super ecartes », la moitie de la fenetre, le
        selecteur relegue en bas. Le bandeau partageait l'espace libre avec le terminal."""
        vue = self._session()
        self.p._poser_bandeau(vue)
        self.p.resize(600, 900)
        self.p.show()
        self.p._onglets.setCurrentWidget(vue)
        QApplication.processEvents()
        bandeau = self.p._bandeaux[vue]
        self.assertLessEqual(bandeau.height(), bandeau.sizeHint().height())

    def test_chaque_bouton_lance_son_role_et_son_modele(self):
        """Demande du 04/10/2026 : « Nouveau Superviseur Fable », « Nouveau worker
        Fable », « Nouveau worker Opus ». Le superviseur est la session NOMMEE
        « Superviseur » a qui l'on dit « supervise » (CLAUDE.md de SmartTeacher)."""
        attendus = {
            "Nouveau superviseur Fable":
                "clear; claude --model claude-fable-5-1 -n Superviseur supervise\n",
            "Nouveau worker Fable": "clear; claude --model claude-fable-5-1\n",
            "Nouveau worker Opus": "clear; claude --model claude-opus-5-5\n",
        }
        for libelle, commande in attendus.items():
            vue = self._session()
            self.p._poser_bandeau(vue)
            vue.pids = (42, 42)
            self._bouton(vue, libelle).click()
            self.p._relancer_si_prete(vue)
            self.assertEqual(vue.envois, ["\x1b", commande], libelle)

    def test_pas_de_bouton_sans_selecteur(self):
        """Sur une commande sans option de reprise, Echap partirait dans une session en
        cours : rien n'est pose."""
        self.p.commande_claude = lambda: "claude"
        vue = self._session()
        self.p._poser_bandeau(vue)
        self.assertNotIn(vue, self.p._bandeaux)

    def test_le_clic_quitte_le_selecteur_puis_lance_une_session_neuve(self):
        vue = self._session()
        self.p._poser_bandeau(vue)
        vue.pids = (42, 77)                       # le selecteur est au premier plan
        self._bouton(vue, "Nouveau worker Opus").click()
        self.assertNotIn(vue, self.p._bandeaux)   # disparu des le clic
        self.assertEqual(vue.envois, ["\x1b"])    # Echap envoye, rien d'autre
        self.assertIsNotNone(self.p._ecran(vue).graphicsEffect())  # voilee des le clic : l'invite
        calme = self.p._calmes[vue]                 # du shell ne se voit pas
        self.p._relancer_si_prete(vue)            # battement : selecteur encore la
        self.assertEqual(vue.envois, ["\x1b"])
        vue.pids = (42, 42)                       # le shell est revenu
        self.p._relancer_si_prete(vue)
        self.assertEqual(vue.envois, ["\x1b", "clear; claude --model claude-opus-5-5\n"])
        self.assertIs(self.p._calmes[vue], calme)   # le meme voile, pas un second
        self.assertNotIn(vue, self.p._relances)

    def test_la_relance_abandonne_au_plafond(self):
        """Taper « claude » dans un selecteur encore ouvert partirait dans son champ de
        recherche : au plafond, on n'insiste pas."""
        vue = self._session()
        self.p._poser_bandeau(vue)
        vue.pids = (42, 77)
        self._bouton(vue, "Nouveau worker Fable").click()
        for _tic in range(self.p.PLAFOND_RELANCE // self.p.PERIODE_RELANCE):
            self.p._relancer_si_prete(vue)
        self.assertNotIn(vue, self.p._relances)
        self.assertEqual(vue.envois, ["\x1b"])

    def test_une_session_choisie_retire_le_bouton(self):
        """Defaut du 04/10/2026 : une session choisie dans l'historique laissait le
        bouton en place (le retrait tenait au registre de claude-window.sh, absent du
        compte isole claude). Le choix se fait au clavier OU a la souris : c'est le
        titre que pose la session demarree qui le dit, pas la touche."""
        vue = self._session()
        self.p._poser_bandeau(vue)
        vue.pids = (42, 77)                       # Claude au premier plan
        self.p._titre_change(vue, self.p.TITRE_SELECTEUR)
        self.assertIn(vue, self.p._bandeaux)      # le selecteur est encore ouvert
        self.p._titre_change(vue, "\u2733 Claude Code")
        self.assertNotIn(vue, self.p._bandeaux)

    def test_le_terminal_reste_voile_jusquau_titre_de_claude(self):
        """Demande du 04/10/2026 : rien du terminal avant que Claude ne s'affiche."""
        vue = self._session()
        self.p._lancer(vue, "claude -r")
        self.assertIsNone(vue.graphicsEffect())   # le cadre (bordure de la vue) reste
        self.assertEqual(vue.envois, ["clear; claude -r\n"])
        self.assertIsNotNone(self.p._ecran(vue).graphicsEffect())
        self.p._titre_change(vue, "zsh")          # titre du shell : voile maintenu
        vue.sig_sortie.emit()                     # sortie avant le titre : n'arme rien
        self.assertFalse(self.p._calmes[vue].isActive())
        vue.pids = (42, 77)                       # Claude au premier plan
        self.p._titre_change(vue, self.p.TITRE_SELECTEUR)
        # Le titre precede la liste (« Loading conversations… ») : voile maintenu,
        # jusqu'a DELAI_CALME de silence.
        self.assertIsNotNone(self.p._ecran(vue).graphicsEffect())
        self.assertTrue(self.p._calmes[vue].isActive())
        limite = time.monotonic() + 5
        while self.p._ecran(vue).graphicsEffect() is not None and time.monotonic() < limite:
            QApplication.processEvents()
            time.sleep(0.01)
        self.assertIsNone(self.p._ecran(vue).graphicsEffect())
        self.assertNotIn(vue, self.p._calmes)

    def test_un_titre_du_shell_garde_le_bouton(self):
        """Un titre pose alors que le shell est au premier plan (avant le selecteur,
        ou apres Echap) n'est pas une session : le bouton reste."""
        vue = self._session()
        self.p._poser_bandeau(vue)
        vue.pids = (42, 42)
        self.p._titre_change(vue, "zsh")
        self.assertIn(vue, self.p._bandeaux)

    def test_oublier_purge_le_bouton_et_la_relance(self):
        """Un bouton ou un minuteur fantome viserait une vue detruite."""
        vue = self._session()
        self.p._poser_bandeau(vue)
        self.p._nouvelle_session(vue)   # arme la relance (et retire le bouton)
        self.p._poser_bandeau(vue)      # un bouton de nouveau present
        self.p._oublier(vue)
        self.assertNotIn(vue, self.p._bandeaux)
        self.assertNotIn(vue, self.p._relances)


class FauxRegistre(unittest.TestCase):
    """Un panneau et un faux registre jetable (XDG_RUNTIME_DIR deplace).

    Base commune de TestRegistreDetat et TestReouvertureDesSessions ; sans test a elle,
    pour que ceux d'une classe ne soient pas rejoues par l'autre."""

    def setUp(self):
        self.p = panneau()
        self.racine = tempfile.mkdtemp(prefix="banc-claude-")
        self.ancien = os.environ.get("XDG_RUNTIME_DIR")
        os.environ["XDG_RUNTIME_DIR"] = self.racine
        self.dossier = etat_instances.dossier_etat()
        os.makedirs(self.dossier, exist_ok=True)

    def tearDown(self):
        if self.ancien is None:
            os.environ.pop("XDG_RUNTIME_DIR", None)
        else:
            os.environ["XDG_RUNTIME_DIR"] = self.ancien
        shutil.rmtree(self.racine, ignore_errors=True)
        self.p.deleteLater()

    def _session(self, identifiant, titre="essai"):
        vue = FausseVue(self.p._onglets)
        self.p._onglets.addTab(vue, titre)
        self.p._vues.append(vue)
        self.p._titres[vue] = titre
        self.p._identifiants[vue] = identifiant
        return vue

    def _declarer(self, identifiant, etat, pid=None):
        """Ecrit dans le faux registre ce qu'y ecrirait claude-window.sh.

        Le nom du fichier porte le PID, et le module ignore les instances mortes : on
        declare donc sous le PID du banc, qui est vivant par construction.
        """
        pid = os.getpid() if pid is None else pid
        chemin = os.path.join(self.dossier, "inst-%d" % pid)
        with io.open(chemin, "w", encoding="utf-8") as fichier:
            fichier.write("CW_SVC=%s\nCW_SESSION=%s\nCW_STATE=%s\nCW_SINCE=0\n"
                          % (etat_instances.SERVICE_SPYDER, identifiant, etat))

class TestRegistreDetat(FauxRegistre):
    """Ce que le panneau Claude ajoute : lire le registre, et le montrer.

    Le registre est un dossier de petits fichiers ecrits par les hooks de Claude Code. On
    en fabrique un faux, et on appelle `relire_le_registre` a la main — c'est justement
    pour cela qu'elle est publique et sans effet de bord cache : aucun minuteur a faire
    tourner dans un banc.
    """

    def test_oublier_purge_aussi_lidentifiant_et_letat(self):
        """Un identifiant fantome ferait poser une couleur sur un onglet detruit."""
        vue = self._session("aaa")
        self.p._etats[vue] = "waiting"
        self.p._oublier(vue)
        self.assertNotIn(vue, self.p._identifiants)
        self.assertNotIn(vue, self.p._etats)

    def test_relire_le_registre_retient_letat(self):
        vue = self._session("aaa")
        self._declarer("aaa", "waiting")
        self.p.relire_le_registre()
        self.assertEqual(self.p._etats.get(vue), "waiting")

    def test_relire_le_registre_ne_leve_pas_sur_un_registre_vide(self):
        """Cas courant : aucune instance declaree, et un battement toutes les demi-secondes."""
        self._session("aaa")
        self.p.relire_le_registre()
        self.assertIsNone(self.p._etats.get(self.p._vues[0]))

    def test_le_fond_osc11_colore_une_session_absente_du_registre(self):
        """Cas du compte isole (09/10/2026) : son registre ne nomme pas l'onglet, seule la
        couleur ecrite sur le pty arrive — et le battement suivant ne doit pas l'effacer."""
        vue = self._session("aaa")
        self.p._fond_demande(vue, "#3A1414")
        self.assertEqual(self.p._etats.get(vue), "waiting")
        self.p.relire_le_registre()
        self.assertEqual(self.p._etats.get(vue), "waiting")
        self.p._fond_demande(vue, "#232627")  # le fond normal, rendu en fin de session
        self.assertEqual(self.p._etats.get(vue), "busy")

    def test_le_fond_osc11_dattente_donne_le_clavier_a_la_session(self):
        """Compte isole, sans arbitre (10/10/2026) : la session qui attend une reponse
        passe devant, comme une fenetre Konsole ; la disponibilite, elle, ne vole rien."""
        vue = self._session("aaa")
        autre = self._session("bbb")
        self.p._onglets.setCurrentWidget(autre)
        self.p._fond_demande(vue, "#14351f")
        self.assertIs(self.p._onglets.currentWidget(), autre)
        self.p._fond_demande(vue, "#3a1414")
        self.assertIs(self.p._onglets.currentWidget(), vue)

    def test_la_session_activee_prend_le_cadre_bleu_double(self):
        """Le cadre suit focusChanged, muet quand la fenetre n'est pas active (banc
        offscreen compris) : activer la session doit le bleuir quand meme, trait de la
        feuille ET second pixel peint par la vue (10/10/2026)."""
        from spyder.utils.palette import SpyderPalette
        vue = self._session("aaa")
        self.p._appliquer_cadre(False)
        self.assertIsNone(vue._liseret)
        self.p.activer_session("aaa")
        self.assertIn("border: 1px solid %s" % SpyderPalette.COLOR_ACCENT_3,
                      self.p.styleSheet())
        self.assertEqual(vue._liseret, SpyderPalette.COLOR_ACCENT_3)

    def test_le_registre_garde_la_priorite_sur_le_fond_osc11(self):
        vue = self._session("aaa")
        self._declarer("aaa", "idle")
        self.p.relire_le_registre()
        self.p._fond_demande(vue, "#3a1414")
        self.assertEqual(self.p._etats.get(vue), "idle")

    def test_une_dictee_deposee_pour_un_onglet_y_est_tapee_puis_validee(self):
        """Compte isole (10/10/2026) : claude-dictee.sh ne peut pas atteindre un onglet du
        panneau par D-Bus, il depose le texte sous l'identifiant de l'onglet. Le texte et
        sa validation sont deux frappes distinctes, et la validation est un CR."""
        vue = self._session("aaa")
        autre = self._session("bbb")
        etat_instances.deposer_dictee("aaa", "bonjour", self.dossier)
        etat_instances.deposer_dictee("zzz", "pour un autre panneau", self.dossier)
        self.p.relire_le_registre()
        self.assertEqual(vue.envois, ["bonjour"])
        self.assertEqual(autre.envois, [])
        fin = time.monotonic() + 3
        while len(vue.envois) < 2 and time.monotonic() < fin:
            APP.processEvents()
        self.assertEqual(vue.envois, ["bonjour", "\r"])
        self.p.relire_le_registre()
        self.assertEqual(vue.envois, ["bonjour", "\r"])  # consommee, pas retapee
        # Un identifiant qui n'est pas a nous reste en place pour son panneau.
        self.assertTrue(os.path.exists(os.path.join(self.dossier, "dictee-pane-zzz")))

    def test_une_dictee_pour_un_onglet_ferme_est_jetee_et_tracee(self):
        """Micro ouvert, onglet ferme avant la fin de la transcription : la dictee est a
        nous, elle ne reste pas dans le registre, et dictee.log dit qu'elle est perdue."""
        vue = self._session("aaa")
        self.p._oublier(vue)
        etat_instances.deposer_dictee("aaa", "trop tard", self.dossier)
        self.p.relire_le_registre()
        self.assertEqual(vue.envois, [])
        self.assertFalse(os.path.exists(os.path.join(self.dossier, "dictee-pane-aaa")))
        with io.open(os.path.join(self.dossier, "dictee.log"), encoding="utf-8") as journal:
            self.assertIn("onglet aaa ferme", journal.read())

    def test_activer_session_repond_faux_sur_un_identifiant_inconnu(self):
        """L'arbitre peut designer une instance de FENETRE : le panneau doit le dire."""
        self._session("aaa")
        self.assertFalse(self.p.activer_session("zzz"))
        self.assertTrue(self.p.activer_session("aaa"))

    def test_on_close_arrete_le_minuteur(self):
        """Un minuteur qui bat apres la fermeture lirait un registre pour rien."""
        self.assertTrue(self.p._minuteur.isActive())
        self.p.on_close()
        self.assertFalse(self.p._minuteur.isActive())

    def _declarer_usage(self, pid=None, **cles):
        """Ecrit un usage-<pid> comme le ferait claude-statusline.sh."""
        pid = os.getpid() if pid is None else pid
        usage.deposer_usage(pid, cles, dossier=self.dossier)

    def test_relire_le_registre_alimente_le_bandeau(self):
        """Le lecteur doit etre BRANCHE, pas seulement ecrit : preuve que
        `relire_le_registre` appelle bien `usage.fenetres()` et pousse le resultat au
        bandeau — pas seulement que le protocole se lit tout seul (deja prouve par
        tests/test_usage.py)."""
        maintenant = int(time.time())
        self._declarer_usage(CU_5H_PCT=74, CU_5H_FIN=maintenant + 3600,
                             CU_7J_PCT=41, CU_7J_FIN=maintenant + 200000,
                             CU_HORODATAGE=maintenant)
        self.p.relire_le_registre()
        fenetres = self.p._bandeau._fenetres
        self.assertEqual(fenetres["cinq_heures"]["pct"], 74)
        self.assertEqual(fenetres["sept_jours"]["pct"], 41)

    def test_relire_le_registre_alimente_le_tachymetre_de_la_cellule(self):
        """Meme preuve que ci-dessus, cote vitesse par conversation — via la mosaique,
        seul support existant tant que le greffon d'onglet n'est pas encore branche."""
        vue = self._session("aaa")
        self._declarer_usage(CU_PANE="aaa", CU_VITESSE=500,
                             CU_HORODATAGE=int(time.time()))
        self.p._passer_en_mosaique()
        self.p.relire_le_registre()
        cellule = self.p._mosaique.cellule_de(vue)
        self.assertIsNotNone(cellule)
        self.assertEqual(cellule._compteur._valeur, 500.0)

    def test_la_vitesse_deja_connue_suit_le_passage_en_mosaique(self):
        """LA CELLULE NEUVE NE PART PAS A ZERO. Sans repousser `_dernieres_vitesses` dans
        `_rafraichir_letat_affiche` (le meme point d'accroche que `_etats`), le garde de
        changement de `_rafraichir_la_consommation` aurait empeche toute reapplication tant
        que l'echantillon reste frais (age <= FENETRE_MIN) : la vitesse decrue ne change
        alors pas d'un battement a l'autre, donc rien ne la distingue d'un « pas de
        nouveaute » — la cellule fraichement creee serait restee eteinte jusqu'a une
        minute, sans qu'aucune valeur n'ait pourtant disparu."""
        vue = self._session("aaa")
        self._declarer_usage(CU_PANE="aaa", CU_VITESSE=500,
                             CU_HORODATAGE=int(time.time()))
        self.p.relire_le_registre()  # etabli EN MODE ONGLETS, avant toute mosaique
        self.assertEqual(self.p._dernieres_vitesses.get(vue), 500.0)
        self.p._passer_en_mosaique()  # aucun nouveau relire_le_registre() apres
        cellule = self.p._mosaique.cellule_de(vue)
        self.assertIsNotNone(cellule)
        self.assertEqual(cellule._compteur._valeur, 500.0)

    def test_un_battement_a_vide_ne_repeint_rien(self):
        """LE GARDE-FOU QUI DOIT RESTER SILENCIEUX. Sans registre d'usage, vingt
        battements ne doivent redessiner le bandeau QU'UNE SEULE FOIS — la transition
        initiale (rien lu -> « aucune fenetre mesurable »). Sans ce garde, un battement de
        500 ms redessinerait le bandeau deux fois par seconde EN PERMANENCE, un cout que
        personne ne signalerait jamais comme un bug puisque rien ne change a l'ecran."""
        appels = []
        self.p._bandeau.poser_fenetres = lambda f: appels.append(f)
        for _ in range(20):
            self.p.relire_le_registre()
        self.assertEqual(len(appels), 1,
                         "le bandeau a ete repeint plus d'une fois a registre inchange")


class TestCompteursDOnglet(unittest.TestCase):
    """Le tachymetre greffe entre le titre d'un onglet et sa croix.

    SEULE PIECE DE CE TRAVAIL COUPLEE AUX INTERNES DE `spyder.widgets.tabs` (une vraie
    barre d'onglets Spyder, un vrai CloseTabButton) : les cinq tests ci-dessous prouvent
    que la greffe respecte le contrat que Spyder attend de ce widget, cf.
    spyder_claude/spyder/onglet_compteur.py.
    """

    def setUp(self):
        self.p = panneau()

    def tearDown(self):
        self.p.deleteLater()

    def _session(self, identifiant, titre="essai"):
        vue = FausseVue(self.p._onglets)
        self.p._onglets.addTab(vue, titre)
        self.p._vues.append(vue)
        self.p._titres[vue] = titre
        self.p._identifiants[vue] = identifiant
        return vue

    def test_la_croix_survit_a_la_greffe(self):
        """ORDRE DE GREFFE : si `adopter_la_croix` etait appele avant `setTabButton`, la
        croix resterait CACHEE — Qt masque le widget precedemment installe dans un slot
        des qu'on en pose un nouveau, avec sa propre reference, quel que soit le parent
        au moment de l'appel.

        `isHidden()`, PAS `isVisible()` : ce banc ne montre jamais la fenetre du panneau
        (aucun `.show()` sur la racine), donc `isVisible()` resterait False meme sans
        aucun bug — seul `isHidden()` distingue « personne n'a appele hide() dessus » de
        « la fenetre elle-meme n'est pas affichee », et c'est la premiere chose qu'on veut
        prouver ici.
        """
        self._session("aaa")
        self.p._rafraichir_les_compteurs()
        barre = self.p._onglets.tabBar()
        coin = barre.tabButton(0, QTabBar.RightSide)
        self.assertIsInstance(coin, CoinDOnglet)
        self.assertIsNotNone(coin.croix())
        self.assertFalse(coin.croix().isHidden(), "la croix a ete cachee par la greffe")

    def test_le_conteneur_repond_a_ce_que_spyder_lui_demande(self):
        """Les cinq appels que `TabBar` fait sur « la croix » sans savoir qu'elle a ete
        enveloppee (cf. _on_tab_changed/_on_tab_moved/tabRemoved et
        CloseTabButton.enterEvent/leaveEvent dans spyder/widgets/tabs.py). Aucun ne doit
        lever, et l'index doit se relire tel qu'ecrit — un sixieme appel qui manquerait un
        jour trouverait ici un endroit evident ou s'ajouter."""
        self._session("aaa")
        self.p._rafraichir_les_compteurs()
        coin = self.p._onglets.tabBar().tabButton(0, QTabBar.RightSide)
        coin.index = 3
        self.assertEqual(coin.index, 3)
        coin.set_selected_color()
        coin.set_not_selected_color()
        coin.setTabToolTip(0, "essai")
        self.assertEqual(coin.tabToolTip(0), "essai")

    def test_survoler_la_croix_ne_leve_pas(self):
        """La croix, une fois reparentee, appelle `self.parent().tabToolTip(...)` sur le
        CONTENEUR (cf. CloseTabButton.enterEvent/leaveEvent) : sans les deux methodes
        proxy, le survol de la souris leve une AttributeError dans un slot Qt."""
        self._session("aaa")
        self.p._rafraichir_les_compteurs()
        croix = self.p._onglets.tabBar().tabButton(0, QTabBar.RightSide).croix()
        point = QPointF(0, 0)
        croix.enterEvent(QEnterEvent(point, point, point))
        croix.leaveEvent(QEvent(QEvent.Leave))

    def test_la_greffe_est_idempotente(self):
        """Rejouee sur un onglet deja greffe (le battement de 500 ms le fait a chaque
        tour) : le MEME conteneur doit rester en place, jamais un second empile dessus."""
        self._session("aaa")
        self.p._rafraichir_les_compteurs()
        premier = self.p._onglets.tabBar().tabButton(0, QTabBar.RightSide)
        self.p._rafraichir_les_compteurs()
        self.p._rafraichir_les_compteurs()
        second = self.p._onglets.tabBar().tabButton(0, QTabBar.RightSide)
        self.assertIs(premier, second)

    def test_la_croix_ferme_le_bon_onglet_apres_un_deplacement(self):
        """LE vrai scenario du proxy `.index` : `Tabs.move_tab` (glisser-deposer) fait
        `removeTab` puis `insertTab`, ce qui installe une croix TOUTE NEUVE a la position
        d'arrivee (`TabBar.tabInserted`). Sans regreffe, cette croix neuve n'a pas de
        tachymetre ; sans le relais `.index`, un clic sur une croix DEJA greffee ailleurs
        fermerait le mauvais onglet apres le deplacement."""
        for i in range(3):
            self._session("s%d" % i)
        self.p._rafraichir_les_compteurs()
        self.p._onglets.move_tab(0, 2)
        self.p._rafraichir_les_compteurs()
        fermetures = []
        self.p._onglets.tabCloseRequested.connect(fermetures.append)
        coin = self.p._onglets.tabBar().tabButton(2, QTabBar.RightSide)
        self.assertIsInstance(coin, CoinDOnglet,
                              "la position d'arrivee n'a pas ete regreffee")
        coin.croix().click()
        self.assertEqual(fermetures, [2], "la croix a ferme le mauvais onglet")

    def test_relever_la_croix_trouve_la_bonne_apres_la_greffe(self):
        """Regression : l'ancienne heuristique par geometrie ne trouvait plus rien une
        fois la croix reparentee (cf. _relever_la_croix_dun_onglet)."""
        self._session("aaa")
        self.p._rafraichir_les_compteurs()
        self.p._relever_la_croix_dun_onglet()
        self.assertIsNotNone(self.p._mosaique._geometrie_croix)
        largeur, hauteur = self.p._mosaique._geometrie_croix
        self.assertGreater(largeur, 0)
        self.assertGreater(hauteur, 0)

    def test_le_cadran_ne_chevauche_pas_la_croix_ni_ne_grandit_longlet(self):
        """Le coin reserve la place de la croix AVANT de l'adopter (QTabBar lit sa taille
        au `setTabButton`), et le cadran, plus haut que la croix, n'est pas dans le coin :
        sinon l'onglet grandissait de 7 px (banc du 04/10/2026)."""
        self._session("aaa", "Essai Claude titre")
        barre = self.p._onglets.tabBar()
        hauteur_avant = barre.tabRect(0).height()
        self.p._rafraichir_les_compteurs()
        # Affiche : le cadran n'est pose qu'a l'affichage du coin (`_suivre`) ; sans
        # cela il reste en (0, 0) et la comparaison d'abscisses ne prouve rien.
        self.p.resize(700, 400)
        self.p.show()
        APP.processEvents()
        coin = barre.tabButton(0, QTabBar.RightSide)
        croix = coin.croix().geometry().translated(coin.pos())
        # Ordre [titre][croix][cadran] : demande de l'utilisateur, 04/10/2026, « la
        # croix [...] a cote du titre, avant le tachymetre ».
        self.assertLess(croix.right(), coin._compteur.geometry().left())
        self.assertEqual(barre.tabRect(0).height(), hauteur_avant)

    def test_le_cadran_tombe_sur_le_texte_de_longlet(self):
        """Signale par l'utilisateur, 04/10/2026 : « le tachymetre n'est pas du tout
        aligne avec le titre des onglets ». Mesure sur l'ENCRE, comme l'oeil : les lignes
        de la barre ou le texte, puis le cadran, s'ecartent du fond. Avant correctif,
        texte y 18-31 et cadran 11-28 — 5 px trop haut."""
        self._session("aaa", "Essai Claude titre")
        self.p.resize(700, 400)
        self.p.show()
        self.p._rafraichir_les_compteurs()
        barre = self.p._onglets.tabBar()
        coin = barre.tabButton(0, QTabBar.RightSide)
        coin.poser_vitesse(2500)
        APP.processEvents()
        image = barre.grab().toImage()
        onglet = barre.tabRect(0)
        cadran = coin._compteur.geometry()

        def encre(x0, x1):
            fond = image.pixelColor(x0, onglet.top() + 1).lightness()
            lignes = [y for y in range(onglet.top() + 1, onglet.bottom())
                      if any(abs(image.pixelColor(x, y).lightness() - fond) > 40
                             for x in range(x0, x1))]
            return (min(lignes) + max(lignes)) / 2.0

        croix = coin.croix().geometry().translated(coin.pos())
        texte = encre(onglet.left() + 4, croix.left() - 2)
        self.assertAlmostEqual(texte, encre(cadran.left(), cadran.right()), delta=1.5)
        # La croix aussi (demande de l'utilisateur, 04/10/2026 : « la croix de fermeture
        # [doit] aussi etre alignee avec le titre »).
        self.assertAlmostEqual(texte, encre(croix.left() + 2, croix.right() - 2),
                               delta=1.5)

    def test_oublier_purge_aussi_le_compteur(self):
        """PAS SEULEMENT LE DICTIONNAIRE : `TabBar.tabRemoved` renumerote les croix
        restantes mais ne detruit jamais celle de l'onglet ferme (verifie dans
        spyder/widgets/tabs.py) — sans un `deleteLater()` explicite, le CoinDOnglet
        restait un enfant orphelin de la barre a chaque fermeture d'onglet. On le prouve
        comme test_mosaique.py le fait deja pour les vues : sous PySide6, toucher un
        widget dont l'objet C++ a ete supprime leve RuntimeError, ce qui rend l'oubli
        impossible a manquer — un simple `assertNotIn` sur le dictionnaire Python ne
        l'aurait pas vu."""
        vue = self._session("aaa")
        self.p._rafraichir_les_compteurs()
        coin = self.p._coins[vue]
        cadran = coin._compteur  # enfant de la BARRE, pas du coin : cf. onglet_compteur
        self.p._oublier(vue)
        self.assertNotIn(vue, self.p._coins)
        # `processEvents()` seul ne suffit pas toujours a faire executer un
        # DeferredDelete hors d'une vraie boucle d'evenements (mesure directe, offscreen) ;
        # `sendPostedEvents` le force explicitement, sans dependre de ce detail de timing.
        APP.sendPostedEvents(None, QEvent.DeferredDelete)
        with self.assertRaises(RuntimeError):
            coin.parent()
        APP.sendPostedEvents(None, QEvent.DeferredDelete)  # celui pose par `destroyed`
        with self.assertRaises(RuntimeError):
            cadran.parent()



class TestCoinsDetruitsParQt(FauxRegistre):
    """`_coins` ne garde JAMAIS un coin que Qt a detruit de son cote.

    `QTabBar.removeTab` detruit lui-meme (deleteLater) les boutons de l'onglet retire :
    le passage en mosaique, qui retire tous les onglets, tuait donc chaque CoinDOnglet
    en laissant sa reference dans `_coins`. Trace du 04/10/2026, en boucle a chaque
    changement de vitesse : « Internal C++ object (Compteur) already deleted ».
    """

    def _en_mosaique_coins_detruits(self):
        vue = self._session("aaa")
        self._session("bbb")
        self.p._rafraichir_les_compteurs()
        self.assertIn(vue, self.p._coins)
        self.p._passer_en_mosaique()
        APP.sendPostedEvents(None, QEvent.DeferredDelete)  # les coins
        APP.sendPostedEvents(None, QEvent.DeferredDelete)  # leurs cadrans (`destroyed`)
        return vue

    def test_la_vitesse_en_mosaique_ne_touche_pas_un_coin_detruit(self):
        vue = self._en_mosaique_coins_detruits()
        self.assertNotIn(vue, self.p._coins)
        self.p._appliquer_vitesse(vue, 1234.0)  # levait RuntimeError
        self.assertEqual(self.p._mosaique.cellule_de(vue)._compteur._valeur, 1234.0)

    def test_fermer_une_session_en_mosaique_apres_destruction_du_coin(self):
        """Meme reference perimee, autre victime : `_oublier` fait `coin.deleteLater()`."""
        vue = self._en_mosaique_coins_detruits()
        self.p._oublier(vue)  # levait RuntimeError
        self.assertNotIn(vue, self.p._vues)

    def test_le_retour_aux_onglets_regreffe_un_coin_vivant(self):
        vue = self._en_mosaique_coins_detruits()
        self.p._revenir_aux_onglets()
        self.p._rafraichir_les_compteurs()
        self.p._appliquer_vitesse(vue, 4321.0)
        self.assertEqual(self.p._coins[vue]._compteur._valeur, 4321.0)


class TestReouvertureDesSessions(FauxRegistre):
    """Rouvrir au demarrage les conversations ouvertes a la fermeture ou au plantage
    precedents (demande du 04/10/2026). Meme faux registre que TestRegistreDetat :
    l'identifiant de conversation arrive par les fichiers usage-<pid> de la statusline."""

    CLE = PanneauClaude.CLE_SESSIONS

    def setUp(self):
        super().setUp()
        # La configuration du banc vit dans le HOME de test et SURVIT d'un lancement a
        # l'autre : on part d'une liste connue.
        self.p.set_conf(self.CLE, [])

    def _conversation(self, pid, onglet, session, dossier):
        usage.deposer_usage(pid, {"CU_PANE": onglet, "CU_SESSION": session,
                                  "CU_DOSSIER": dossier}, dossier=self.dossier)

    def _deux_sessions(self):
        une, deux = self._session("aaa"), self._session("bbb")
        self._conversation(os.getpid(), "aaa", "S1", "/d1")
        self._conversation(os.getppid(), "bbb", "S2", "/d 2")
        return une, deux

    def test_rien_ne_s_ecrit_avant_la_restauration(self):
        """Le battement demarre au montage, avant `rouvrir_les_sessions` : s'il ecrivait,
        il effacerait la liste a rouvrir."""
        self.p.set_conf(self.CLE, [["X", "/x"]])
        self._deux_sessions()
        self.p.relire_le_registre()
        self.assertEqual(self.p.get_conf(self.CLE), [["X", "/x"]])

    def test_la_liste_suit_les_onglets_dans_leur_ordre(self):
        self.p._sessions_memorisees = []
        self._deux_sessions()
        self.p.relire_le_registre()
        self.assertEqual(self.p.get_conf(self.CLE), [["S1", "/d1"], ["S2", "/d 2"]])
        self.p._fermer_onglet(0)
        self.p.relire_le_registre()
        self.assertEqual(self.p.get_conf(self.CLE), [["S2", "/d 2"]])

    def test_un_clear_change_la_conversation_memorisee(self):
        self.p._sessions_memorisees = []
        self._deux_sessions()
        self.p.relire_le_registre()
        self._conversation(os.getpid(), "aaa", "S1-bis", "/d1")
        self.p.relire_le_registre()
        self.assertEqual(self.p.get_conf(self.CLE)[0], ["S1-bis", "/d1"])

    def test_la_conversation_reste_connue_quand_son_fichier_disparait(self):
        """claude sorti, ou session rouverte que la statusline n'a pas encore vue : la
        vue garde sa conversation, elle ne disparait pas de la liste."""
        self.p._sessions_memorisees = []
        self._deux_sessions()
        self.p.relire_le_registre()
        for nom in os.listdir(self.dossier):
            os.remove(os.path.join(self.dossier, nom))
        self.p.relire_le_registre()
        self.assertEqual(len(self.p.get_conf(self.CLE)), 2)

    def test_fermer_spyder_n_efface_pas_la_liste(self):
        self.p._sessions_memorisees = []
        self._deux_sessions()
        self.p.relire_le_registre()
        self.p.on_close()
        self.assertEqual(len(self.p.get_conf(self.CLE)), 2)

    def test_rouvrir_reprend_chaque_conversation_et_saute_l_illisible(self):
        appels = []
        self.p.ouvrir_terminal = lambda dossier, conversation: appels.append(
            (dossier, conversation))
        self.p.set_conf(self.CLE, [["S1", "/d1"], ["illisible"], ["S2", ""]])
        self.p.rouvrir_les_sessions()
        self.assertEqual(appels, [("/d1", "S1"), ("", "S2")])
        self.assertEqual(self.p._sessions_memorisees, [["S1", "/d1"], ["S2", ""]])

    def test_une_conversation_se_reprend_sans_passer_par_le_selecteur(self):
        self.p.set_conf("commande", "claude -r")
        self.assertEqual(self.p._commande_nouvelle_session("-r S1"), "claude -r S1")
        import inspect
        source = inspect.getsource(PanneauClaude.ouvrir_terminal)
        # le bandeau du selecteur n'est pose que dans la branche SANS conversation
        self.assertLess(source.index("if conversation:"),
                        source.index("self._poser_bandeau(vue)"))

if __name__ == "__main__":
    # ⚠ PAS `unittest.main()` : il repose les filtres d'avertissement au demarrage
    # (`simplefilter("default")` des que `sys.warnoptions` est vide), ce qui EFFACE celui
    # pose plus haut — les cinquante lignes du registre de Spyder revenaient donc noyer le
    # resultat. `TextTestRunner`, lui, ne touche aux filtres que si on le lui demande.
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    resultat = unittest.TextTestRunner(verbosity=1).run(suite)
    sys.exit(0 if resultat.wasSuccessful() else 1)

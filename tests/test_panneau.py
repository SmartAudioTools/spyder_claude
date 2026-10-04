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
        # c'est la que le panneau insere le bouton « Nouvelle session ».
        disposition = QVBoxLayout(self)
        disposition.addWidget(QWidget(self))

    def arreter(self, force=False):
        self.arrets.append(force)

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
    """Le bouton « Nouvelle session » au-dessus du selecteur `claude -r` (04/10/2026).

    Le selecteur de Claude Code n'a aucune entree « nouvelle session » : ce bouton la
    fournit. `ouvrir_terminal` lançant un vrai shell, on reproduit ici ce qu'elle fait
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

    def test_ouvrir_terminal_pose_le_bandeau(self):
        import inspect
        source = inspect.getsource(PanneauClaude.ouvrir_terminal)
        self.assertIn("self._poser_bandeau(vue)", source)

    def test_le_bouton_nait_au_dessus_du_terminal(self):
        """Pleine largeur au-dessus du terminal = premiere ligne du layout de la vue."""
        vue = self._session()
        self.p._poser_bandeau(vue)
        bouton = self.p._bandeaux[vue]
        self.assertIs(vue.layout().itemAt(0).widget(), bouton)

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
        self.p._bandeaux[vue].click()
        self.assertNotIn(vue, self.p._bandeaux)   # disparu des le clic
        self.assertEqual(vue.envois, ["\x1b"])    # Echap envoye, rien d'autre
        self.assertIsNotNone(self.p._ecran(vue).graphicsEffect())  # voilee des le clic : l'invite
        calme = self.p._calmes[vue]                 # du shell ne se voit pas
        self.p._relancer_si_prete(vue)            # battement : selecteur encore la
        self.assertEqual(vue.envois, ["\x1b"])
        vue.pids = (42, 42)                       # le shell est revenu
        self.p._relancer_si_prete(vue)
        self.assertEqual(vue.envois, ["\x1b", "clear; claude\n"])
        self.assertIs(self.p._calmes[vue], calme)   # le meme voile, pas un second
        self.assertNotIn(vue, self.p._relances)

    def test_la_relance_abandonne_au_plafond(self):
        """Taper « claude » dans un selecteur encore ouvert partirait dans son champ de
        recherche : au plafond, on n'insiste pas."""
        vue = self._session()
        self.p._poser_bandeau(vue)
        vue.pids = (42, 77)
        self.p._bandeaux[vue].click()
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


class TestRegistreDetat(unittest.TestCase):
    """Ce que le panneau Claude ajoute : lire le registre, et le montrer.

    Le registre est un dossier de petits fichiers ecrits par les hooks de Claude Code. On
    en fabrique un faux, et on appelle `relire_le_registre` a la main — c'est justement
    pour cela qu'elle est publique et sans effet de bord cache : aucun minuteur a faire
    tourner dans un banc.
    """

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

    def test_pastille_seulement_pour_les_etats_qui_se_distinguent(self):
        """« busy » et l'etat inconnu n'en portent pas : une pastille grise partout ne
        distinguerait plus rien."""
        # ⚠ `isNull()`, PAS `availableSizes()` : une icone qtawesome est dessinee a la
        # demande et n'annonce aucune taille disponible, meme quand elle dessine bien
        # quelque chose. La premiere version du test echouait sur une pastille correcte.
        self.assertTrue(self.p._pastille("busy").isNull())
        self.assertTrue(self.p._pastille(None).isNull())
        self.assertFalse(self.p._pastille("waiting").isNull())
        self.assertFalse(self.p._pastille("idle").isNull())

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


if __name__ == "__main__":
    # ⚠ PAS `unittest.main()` : il repose les filtres d'avertissement au demarrage
    # (`simplefilter("default")` des que `sys.warnoptions` est vide), ce qui EFFACE celui
    # pose plus haut — les cinquante lignes du registre de Spyder revenaient donc noyer le
    # resultat. `TextTestRunner`, lui, ne touche aux filtres que si on le lui demande.
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    resultat = unittest.TextTestRunner(verbosity=1).run(suite)
    sys.exit(0 if resultat.wasSuccessful() else 1)

# -*- coding: utf-8 -*-
"""Le dock AUTONOME (`claude-dock`), monte hors de Spyder.

⚠ CE BANC NE LANCE JAMAIS `claude` : les vues sont fausses (aucun shell, aucun pty) et ce
qu'elles « tapent » est seulement enregistre dans `envois`. Un `claude -r <id>` reel sur
un identifiant reel reprendrait une conversation de l'utilisateur — exigence du
Superviseur, 11/10/2026. Les reglages vont dans un QSettings JETABLE (INI sous un dossier
temporaire), le registre dans un XDG_RUNTIME_DIR temporaire : rien du vrai dock n'est lu
ni ecrit.
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from qtpy.QtCore import QSettings, Qt, Signal  # noqa: E402
from qtpy.QtWidgets import QApplication, QTabBar, QVBoxLayout, QWidget  # noqa: E402

APP = QApplication.instance() or QApplication([])

from spyder_claude import usage  # noqa: E402
from spyder_claude.autonome.fenetre import (FenetreClaude,  # noqa: E402
                                            demande_de_la_ligne_de_commande)


class FausseVue(QWidget):
    """Ce que la fenetre attend d'une vue Konsole, et rien de plus."""

    sig_titre = Signal(str)
    sig_termine = Signal(int)
    sig_sortie = Signal()
    sig_fond = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.arrets = []
        self.envois = []
        self.demarrages = []
        self.schemas = []
        self.liserets = []
        self.pids = (42, 42)
        disposition = QVBoxLayout(self)
        disposition.addWidget(QWidget(self))

    def demarrer(self, commande=None, repertoire=None, environnement=None):
        self.demarrages.append((commande, repertoire, environnement))

    def arreter(self, force=False):
        self.arrets.append(force)

    def envoyer(self, texte):
        self.envois.append(texte)

    def appliquer_schema(self, nom):
        self.schemas.append(nom)

    def poser_liseret(self, couleur, double=True):
        self.liserets.append((couleur, double))

    def pid_shell(self):
        return self.pids[0]

    def pid_premier_plan(self):
        return self.pids[1]

    def terminer(self):
        """Ce que fait la vraie vue quand le shell sort."""
        self.sig_termine.emit(0)


class Banc(unittest.TestCase):

    def setUp(self):
        self.temporaire = tempfile.mkdtemp()
        self._xdg = os.environ.get("XDG_RUNTIME_DIR")
        os.environ["XDG_RUNTIME_DIR"] = self.temporaire
        # Jamais le spyder.ini reel : la reprise y lit les sessions de SmartPythonEditor.
        self._confdir = os.environ.get("SPYDER_CONFDIR")
        os.environ["SPYDER_CONFDIR"] = os.path.join(self.temporaire, "spyder-py3")
        self.chemin_reglages = os.path.join(self.temporaire, "claude-dock.ini")
        self.fenetres = []

    def tearDown(self):
        for fenetre in self.fenetres:
            fenetre._minuteur.stop()
            fenetre._en_fermeture = True
            fenetre.deleteLater()
        APP.processEvents()
        if self._xdg is None:
            os.environ.pop("XDG_RUNTIME_DIR", None)
        else:
            os.environ["XDG_RUNTIME_DIR"] = self._xdg
        if self._confdir is None:
            os.environ.pop("SPYDER_CONFDIR", None)
        else:
            os.environ["SPYDER_CONFDIR"] = self._confdir
        shutil.rmtree(self.temporaire, ignore_errors=True)

    def reglages(self, **valeurs):
        reglages = QSettings(self.chemin_reglages, QSettings.IniFormat)
        reglages.setValue("commande", "cat")   # inerte, et jamais lancee : vues fausses
        for cle, valeur in valeurs.items():
            reglages.setValue(cle, valeur)
        reglages.sync()
        return reglages

    def fenetre(self, theme=None, **valeurs):
        # Jamais le vrai claude-voix.sh : un script absent, que `TestTitre` remplace.
        fenetre = FenetreClaude(reglages=self.reglages(**valeurs), dossier=self.temporaire,
                                fabrique_vue=FausseVue, theme=theme,
                                script_voix=getattr(self, "script_voix",
                                                    os.path.join(self.temporaire, "absent")))
        self.fenetres.append(fenetre)
        return fenetre

    def statusline(self, pid, pane, session, dossier="/projet"):
        """Ce qu'ecrit claude-statusline.sh pour une instance vivante (`pid`)."""
        usage.deposer_usage(pid, {"CU_PANE": pane, "CU_SESSION": session,
                                  "CU_DOSSIER": dossier, "CU_HORODATAGE": 1,
                                  "CU_CENTIMES": 0},
                            dossier=os.path.join(self.temporaire, "claude-windows"))


class TestOuverture(Banc):

    def test_demarrer_ouvre_une_session_quand_rien_n_est_memorise(self):
        f = self.fenetre()
        f.demarrer()
        self.assertEqual(len(f.sessions()), 1)
        vue = f.sessions()[0]
        self.assertEqual(vue.demarrages[0][1], self.temporaire)
        self.assertIn("SPYDER_CLAUDE_PANE", vue.demarrages[0][2])
        self.assertEqual(vue.envois, ["clear; cat\n"])
        self.assertEqual(f._onglets.count(), 1)

    def test_le_coin_d_onglet_ferme_son_propre_onglet(self):
        """La croix retrouve SON onglet, meme apres une fermeture qui decale les index."""
        f = self.fenetre()
        a, b, c = f.ouvrir_session(), f.ouvrir_session(), f.ouvrir_session()
        barre = f._onglets.tabBar()
        f._fermer_par_coin(barre.tabButton(2, QTabBar.RightSide))
        self.assertEqual(c.arrets, [False])
        self.assertEqual((a.arrets, b.arrets), ([], []))
        c.terminer()
        self.assertEqual(f.sessions(), [a, b])
        f._fermer_par_coin(barre.tabButton(1, QTabBar.RightSide))
        self.assertEqual(b.arrets, [False])

    def test_jamais_zero_session(self):
        f = self.fenetre()
        vue = f.ouvrir_session()
        f._debut_derniere_session -= 10
        vue.terminer()
        APP.processEvents()
        self.assertEqual(len(f.sessions()), 1)
        self.assertIsNot(f.sessions()[0], vue)

    def test_sortie_immediate_ne_relance_pas_en_boucle(self):
        f = self.fenetre()
        vue = f.ouvrir_session()
        vue.terminer()
        APP.processEvents()
        self.assertEqual(f.sessions(), [])
        self.assertEqual(f._onglets.widget(0).objectName(), "etat_vide")


class TestMosaique(Banc):

    def test_aller_retour_garde_les_sessions_et_leurs_coins(self):
        f = self.fenetre()
        vues = [f.ouvrir_session() for _ in range(3)]
        f.basculer_mosaique(True)
        self.assertTrue(f.en_mosaique())
        self.assertEqual(f._onglets.count(), 0)
        self.assertEqual(len(f._mosaique.cellules()), 3)
        f.basculer_mosaique(False)
        self.assertFalse(f.en_mosaique())
        self.assertEqual([f._onglets.widget(i) for i in range(3)], vues)
        for index in range(3):
            self.assertIsNotNone(f._onglets.tabBar().tabButton(index, QTabBar.RightSide))

    def test_fermeture_en_mosaique(self):
        f = self.fenetre()
        a, b = f.ouvrir_session(), f.ouvrir_session()
        f.basculer_mosaique(True)
        b.terminer()
        self.assertEqual(f.sessions(), [a])
        self.assertTrue(f.en_mosaique())
        self.assertEqual(len(f._mosaique.cellules()), 1)

    def test_le_bouton_reduire_n_est_pas_pose(self):
        f = self.fenetre()
        f.ouvrir_session()
        f.basculer_mosaique(True)
        self.assertNotIn(f._mosaique._bouton_reduire, f._mosaique._boutons_de_titre)
        self.assertFalse(f._mosaique._bouton_reduire.isVisible())


class TestOrdre(Banc):
    """« je souhaite pouvoir reorganiser les onglet par glissé / deposser et les fenetre en
    vu mosaique également » (utilisateur, 19/10/2026). Les onglets se deplacaient deja
    (`setMovable`), mais `_vues` ne suivait pas : l'ordre se perdait en mosaique, au
    retour, et dans les sessions memorisees."""

    def test_l_ordre_des_onglets_survit_a_la_mosaique(self):
        f = self.fenetre()
        a, b, c = f.ouvrir_session(), f.ouvrir_session(), f.ouvrir_session()
        f._onglets.tabBar().moveTab(0, 2)
        self.assertEqual(f.sessions(), [b, c, a])
        f.basculer_mosaique(True)
        self.assertEqual([cellule.vue for cellule in f._mosaique.cellules()], [b, c, a])
        f.basculer_mosaique(False)
        self.assertEqual([f._onglets.widget(i) for i in range(3)], [b, c, a])

    def test_un_depot_en_mosaique_reordonne_et_revient_en_onglets(self):
        f = self.fenetre()
        a, b, c = f.ouvrir_session(), f.ouvrir_session(), f.ouvrir_session()
        f.basculer_mosaique(True)
        f._mosaique.sig_ordre_demande.emit([c, a, b])
        self.assertTrue(f.en_mosaique())
        self.assertEqual([cellule.vue for cellule in f._mosaique.cellules()], [c, a, b])
        f.basculer_mosaique(False)
        self.assertEqual([f._onglets.widget(i) for i in range(3)], [c, a, b])

    def test_l_ordre_est_memorise(self):
        f = self.fenetre()
        f.demarrer()
        a, b = f.sessions()[0], f.ouvrir_session()
        self.statusline(os.getpid(), f.identifiant_de(a), "aaa", "/a")
        self.statusline(os.getppid(), f.identifiant_de(b), "bbb", "/b")  # vivant, lui aussi
        f.relire_le_registre()
        f._onglets.tabBar().moveTab(1, 0)
        self.assertEqual(json.loads(f._reglages.value("sessions_ouvertes")),
                         [["bbb", "/b"], ["aaa", "/a"]])


class TestReprise(Banc):
    """« pouvoir reprendre toutes les sessions où elles en sont après une fermeture /
    reouverture » (utilisateur, 11/10/2026)."""

    def test_memorise_puis_rouvre_par_claude_r(self):
        f = self.fenetre()
        f.demarrer()
        vue = f.sessions()[0]
        self.statusline(os.getpid(), f.identifiant_de(vue), "abc-123", "/projet")
        f.relire_le_registre()
        self.assertEqual(json.loads(f._reglages.value("sessions_ouvertes")),
                         [["abc-123", "/projet"]])

        f.close()
        self.assertEqual(vue.arrets, [True])
        # L'instance s'est arretee avec la fenetre : plus de statusline vivante.
        os.remove(os.path.join(self.temporaire, "claude-windows",
                               "usage-%d" % os.getpid()))

        g = self.fenetre()
        g.demarrer()
        self.assertEqual(len(g.sessions()), 1)
        reprise = g.sessions()[0]
        self.assertEqual(reprise.demarrages[0][1], "/projet")
        self.assertEqual(reprise.envois, ["clear; cat -r abc-123\n"])

    def test_la_fermeture_ne_vide_pas_la_liste(self):
        """Les sessions qui meurent AVEC la fenetre ne sont pas des fermetures voulues."""
        f = self.fenetre()
        f.demarrer()
        vue = f.sessions()[0]
        self.statusline(os.getpid(), f.identifiant_de(vue), "abc-123")
        f.relire_le_registre()
        f.close()
        vue.terminer()
        f.relire_le_registre()
        self.assertEqual(json.loads(f._reglages.value("sessions_ouvertes")),
                         [["abc-123", "/projet"]])
        self.assertEqual(f._sessions_fermees(), [])

    def test_ne_reprend_pas_une_conversation_deja_ouverte_ailleurs(self):
        """GARDE-FOU DE DOUBLE REPRISE (Superviseur, 11/10/2026) : le dock de Spyder rouvre
        lui aussi ses conversations ; une instance VIVANTE qui porte deja ce session_id
        interdit le `claude -r`. Echoue sans le test `session in vivantes`."""
        reglages = {"sessions_ouvertes": json.dumps([["deja-prise", "/a"],
                                                     ["libre", "/b"]])}
        # Une instance vivante (ce processus) porte « deja-prise », depuis un AUTRE dock.
        self.statusline(os.getpid(), "onglet-de-spyder", "deja-prise", "/a")
        f = self.fenetre(**reglages)
        f.demarrer()
        envois = [v.envois for v in f.sessions()]
        self.assertEqual(envois, [["clear; cat -r libre\n"]])
        self.assertIn("deja-prise", f.statusBar().currentMessage())
        # Elle reste memorisee : l'autre dock peut l'avoir fermee au prochain lancement.
        self.assertEqual(f._sessions_memorisees, [["deja-prise", "/a"], ["libre", "/b"]])

    def test_rouvre_aussi_celles_de_smartpythoneditor(self):
        """« les sessions de SmartPythonEditor ne sont pas réouvertes » (utilisateur,
        11/10/2026) : celles de son spyder.ini, apres celles du dock, sans doublon."""
        dossier = os.path.join(os.environ["SPYDER_CONFDIR"], "config")
        os.makedirs(dossier)
        with open(os.path.join(dossier, "spyder.ini"), "w", encoding="utf-8") as ini:
            ini.write("[claude_pane]\nsessions_ouvertes = "
                      "[['commune', '/c'], ['de-spyder', '/s']]\n")
        f = self.fenetre(sessions_ouvertes=json.dumps([["du-dock", "/d"],
                                                       ["commune", "/c"]]))
        f.demarrer()
        self.assertEqual([v.envois for v in f.sessions()],
                         [["clear; cat -r du-dock\n"], ["clear; cat -r commune\n"],
                          ["clear; cat -r de-spyder\n"]])
        self.assertEqual(f.sessions()[2].demarrages[0][1], "/s")

    def spyder_ini(self, *sessions):
        dossier = os.path.join(os.environ["SPYDER_CONFDIR"], "config")
        os.makedirs(dossier, exist_ok=True)
        with open(os.path.join(dossier, "spyder.ini"), "w", encoding="utf-8") as ini:
            ini.write("[claude_pane]\nsessions_ouvertes = %r\n" % [list(s) for s in sessions])

    def test_fermee_dans_le_dock_ne_revient_pas_de_smartpythoneditor(self):
        """« il se souvient de sessions que j'ai pourtant fermées et qui me rouvrent à
        chaque fois que je lance Claude Dock » (utilisateur, 23/10/2026) : le dock lit la
        liste de SmartPythonEditor sans la modifier, il doit donc retenir lui-meme ce qu'il
        a ferme. Echoue sans `_marquer_fermee` / le filtre de `rouvrir_les_sessions`."""
        self.spyder_ini(("de-spyder", "/s"), ("gardee", "/g"))
        f = self.fenetre()
        f.demarrer()
        fermee, gardee = f.sessions()
        self.assertEqual(fermee.envois, ["clear; cat -r de-spyder\n"])
        f._fermer_par_coin(f._onglets.tabBar().tabButton(0, QTabBar.RightSide))
        fermee.terminer()
        self.assertEqual(f._sessions_fermees(), ["de-spyder"])
        f.close()

        g = self.fenetre()
        g.demarrer()
        self.assertEqual([v.envois for v in g.sessions()], [["clear; cat -r gardee\n"]])

    def test_reprise_volontaire_efface_la_fermeture(self):
        """Rouverte par le selecteur ou « Reprendre Claude » : ce n'est plus une fermee."""
        f = self.fenetre(sessions_fermees=json.dumps(["x", "y"]))
        f.demarrer()
        vue = f.sessions()[0]
        self.statusline(os.getpid(), f.identifiant_de(vue), "x", "/x")
        f.relire_le_registre()
        self.assertEqual(f._sessions_fermees(), ["y"])

    def test_les_fermees_suivent_la_liste_de_smartpythoneditor(self):
        """Ce que SmartPythonEditor ne memorise plus n'a plus rien a filtrer : la liste des
        fermees ne grossit pas sans fin. Une liste de SmartPythonEditor vide ou illisible
        ne la vide pas (rien n'est filtre, rien n'est oublie)."""
        f = self.fenetre(sessions_fermees=json.dumps(["vieille", "de-spyder"]))
        f.demarrer()
        self.assertEqual(f._sessions_fermees(), ["vieille", "de-spyder"])
        f.close()
        self.spyder_ini(("de-spyder", "/s"))
        g = self.fenetre(sessions_fermees=json.dumps(["vieille", "de-spyder"]))
        g.demarrer()
        self.assertEqual(g._sessions_fermees(), ["de-spyder"])
        self.assertEqual(g.sessions()[0].envois, ["clear; cat\n"])

    def test_entree_illisible_ignoree(self):
        f = self.fenetre(sessions_ouvertes="pas du json")
        f.demarrer()
        self.assertEqual(len(f.sessions()), 1)
        self.assertEqual(f.sessions()[0].envois, ["clear; cat\n"])

    def test_rien_n_est_ecrit_avant_la_reprise(self):
        """Sinon le premier battement ecraserait la liste avant qu'on l'ait relue."""
        f = self.fenetre(sessions_ouvertes=json.dumps([["x", "/x"]]))
        f.ouvrir_session()
        f.relire_le_registre()
        self.assertEqual(json.loads(f._reglages.value("sessions_ouvertes")), [["x", "/x"]])


class TestRendu(Banc):
    """« la barre de titre de SmartPythonEditor n'a pas la couleur de fond, les poignés non
    plus, tu n'encadre pas en bleu comme SmartPythonEditor » (utilisateur, 11/10/2026).
    Theme de qdarkstyle : les memes noms de couleurs que SpyderPalette, sans Spyder."""

    FOND = "#123456"

    def theme(self):
        from qdarkstyle.dark.palette import DarkPalette
        return {"palette": DarkPalette, "fond": self.FOND, "feuille_onglets": "",
                "peindre_conges": None}

    def fenetre_visible(self):
        f = self.fenetre(theme=self.theme())
        f.show()
        f.activateWindow()
        APP.processEvents()
        return f

    def test_cadre_bleu_quand_le_dock_a_le_clavier(self):
        from qdarkstyle.dark.palette import DarkPalette as P
        f = self.fenetre_visible()
        vue = f.ouvrir_session()
        APP.processEvents()
        self.assertIn(P.COLOR_ACCENT_3, f.centralWidget().styleSheet())
        self.assertIn(P.COLOR_ACCENT_3, f._onglets.styleSheet())
        self.assertTrue(f._onglets.tabBar().property("smartos_focus"))
        self.assertEqual(vue.liserets[-1], (P.COLOR_ACCENT_3, False))
        f._suivre_le_focus(vue, None)          # le clavier quitte la fenetre
        self.assertIn(P.COLOR_BACKGROUND_4, f.centralWidget().styleSheet())
        self.assertNotIn(P.COLOR_ACCENT_3, f._onglets.styleSheet())
        self.assertEqual(vue.liserets[-1], (None, False))

    def test_mosaique_un_seul_cadre_bleu_et_poignees_au_fond(self):
        from qdarkstyle.dark.palette import DarkPalette as P
        f = self.fenetre_visible()
        a, b = f.ouvrir_session(), f.ouvrir_session()
        f.basculer_mosaique(True)
        b.setFocus()
        APP.processEvents()
        self.assertIn(P.COLOR_ACCENT_3, b.styleSheet())
        self.assertIn(P.COLOR_BACKGROUND_4, a.styleSheet())
        self.assertEqual((a.liserets[-1], b.liserets[-1]),
                         ((None, True), (P.COLOR_ACCENT_3, True)))
        self.assertIn(P.COLOR_BACKGROUND_1, f._mosaique._racine.styleSheet())
        f.basculer_mosaique(False)
        self.assertEqual((a.styleSheet(), b.styleSheet()), ("", ""))

    def test_onglets_en_haut_et_boutons_immobiles_d_une_vue_a_l_autre(self):
        """« les boutons bougent d'une vue à l'autre . les onglets doivent remonter dans les
        vue onglets » (utilisateur, 11/10/2026). Les trois regles de PanesTabBarStyleSheet
        en cause, reproduites ici sans importer Spyder (donc CONF)."""
        from qtpy.QtCore import QPoint
        from qtpy.QtWidgets import QTabBar
        theme = dict(self.theme(), feuille_onglets=(
            "QTabBar#pane-tabbar::tab { margin-top: 12px; padding: 4px; }"
            "QTabBar#pane-tabbar QToolButton { margin-top: 12px; }"
            "QTabWidget::pane { border-top: 0px; top: -1px; }"
            "QTabWidget::right-corner { top: -1px; right: -1px; }"))
        f = self.fenetre(theme=theme)
        f.resize(1000, 500)
        f.show()
        f.ouvrir_session(), f.ouvrir_session()
        APP.processEvents()
        barre = f._onglets.tabBar()
        self.assertEqual(barre.tabRect(0).y(), 0)
        # La marge se loge DANS le rectangle de l'onglet (y reste 0) : c'est sa hauteur qui
        # la trahit, le texte et ses 2 x 4 px de padding n'y laissant pas place a 12 px de plus.
        self.assertLess(barre.tabRect(0).height(), barre.fontMetrics().height() + 2 * 4 + 12)
        # La croix centree dans SON bouton : la marge de la feuille la decalait de 6 px vers le
        # bas sans changer la geometrie du bouton, d'ou une mesure sur les pixels peints.
        image = barre.tabButton(0, QTabBar.RightSide).croix().grab().toImage()
        fond = image.pixel(0, 0)
        lignes = [y for y in range(image.height())
                  if any(image.pixel(x, y) != fond for x in range(image.width()))]
        self.assertTrue(lignes)
        self.assertLessEqual(abs((lignes[0] + lignes[-1]) / 2 - (image.height() - 1) / 2), 1)

        def positions(boutons):
            return [b.mapTo(f, QPoint(0, 0)) for b in boutons]
        coin = f._onglets.cornerWidget().layout()
        en_onglets = positions(coin.itemAt(i).widget() for i in range(coin.count()))
        f.basculer_mosaique(True)
        APP.processEvents()
        self.assertEqual(positions(f._mosaique._boutons_de_titre), en_onglets)

    def test_conge_droit_du_dernier_onglet_dans_la_barre(self):
        """« traite Claude Dock » (utilisateur, 12/10/2026) : la barre bute sur les boutons
        de coin, et le conge droit du dernier onglet actif, peint hors d'elle, etait coupe -
        le flanc s'arretait au-dessus du cadre. Un faux conge (un carre rouge a droite du
        flanc, la ou le fork peint le sien) doit se voir, fenetre large ou titres raccourcis."""
        from qtpy.QtCore import QRect
        from qtpy.QtGui import QColor
        from spyder_claude.autonome.fenetre import MARGE_CONGE

        def faux_conge(barre, peintre):
            zone = barre.tabRect(barre.currentIndex())
            peintre.fillRect(QRect(zone.right() + 1, 0, MARGE_CONGE - 1, 4), QColor("red"))
        f = self.fenetre(theme=dict(self.theme(), peindre_conges=faux_conge))
        f.show()
        for _ in range(3):
            f.ouvrir_session()
        barre = f._onglets.tabBar()
        for i in range(3):
            f._onglets.setTabText(i, "une-session-au-titre-long")
        for largeur in (1200, 400):
            f.resize(largeur, 300)
            APP.processEvents()
            zone = barre.tabRect(2)
            image = barre.grab().toImage()
            self.assertEqual(image.pixelColor(zone.right() + MARGE_CONGE - 1, 1).name(),
                             "#ff0000", f"largeur {largeur}")

    def test_croix_du_dernier_onglet_hors_de_la_marge_du_conge(self):
        """« la croix touche le contour » (utilisateur, 12/10/2026) : Qt calait la croix du
        dernier onglet sur son rectangle marge du conge comprise - ecart au flanc -1 px au lieu
        des 5 des autres onglets. Meme ecart partout, large, etroit, et onglet seul."""
        f = self.fenetre(theme=dict(self.theme(), peindre_conges=lambda barre, peintre: None))
        f.show()
        for _ in range(3):
            f.ouvrir_session()
        barre = f._onglets.tabBar()

        def ecarts():
            APP.processEvents()
            return [barre.tabRect(i).right()
                    - barre.tabButton(i, QTabBar.RightSide).geometry().right()
                    for i in range(barre.count())]
        attendu = ecarts()[0]
        for largeur in (1200, 500):
            f.resize(largeur, 300)
            self.assertEqual(set(ecarts()), {attendu}, f"largeur {largeur}")
        f._onglets.removeTab(2)
        f._onglets.removeTab(1)
        self.assertEqual(ecarts(), [attendu], "onglet seul")

    def test_sans_theme_ni_cadre_ni_teinte(self):
        f = self.fenetre()
        f.ouvrir_session()
        f.basculer_mosaique(True)
        self.assertEqual(f.centralWidget().styleSheet(), "")
        self.assertEqual(f._mosaique._racine.styleSheet(), "")


class TestMenuDeDolphin(Banc):
    """« Nouveau Claude » / « Reprendre Claude » de Dolphin, recus par `ecouter`.

    Le TRANSPORT (socket local, socat) n'est pas exerce ici : le bac a sable de Claude
    interdit les sockets AF_UNIX. Seul le traitement de la ligne l'est.
    """

    def fenetre_du_menu(self):
        f = self.fenetre(commande="claude -r")
        f.montrees = []
        f._se_montrer = lambda: f.montrees.append(True)   # jamais de kdotool au banc
        return f

    def test_lancer_ouvre_une_session_neuve_dans_le_dossier(self):
        f = self.fenetre_du_menu()
        self.assertTrue(f.demande_du_menu("lancer\t%s\n" % self.temporaire))
        vue = f.sessions()[-1]
        self.assertEqual(vue.demarrages[0][1], self.temporaire)
        self.assertEqual(vue.envois, ["clear; claude\n"])
        self.assertEqual(f.montrees, [True])

    def test_reprendre_ouvre_le_selecteur(self):
        f = self.fenetre_du_menu()
        self.assertTrue(f.demande_du_menu("reprendre\t%s\n" % self.temporaire))
        self.assertEqual(f.sessions()[-1].envois, ["clear; claude -r\n"])

    def test_refuse_un_mode_inconnu_ou_un_dossier_absent(self):
        f = self.fenetre_du_menu()
        self.assertFalse(f.demande_du_menu("effacer\t%s\n" % self.temporaire))
        self.assertFalse(f.demande_du_menu("lancer\t/nulle/part\n"))
        self.assertEqual(f.sessions(), [])
        self.assertEqual(f.montrees, [])


class TestEquipe(Banc):
    """« Nouvelle équipe » / « Reprendre équipe » du menu de Dolphin (utilisateur,
    23/10/2026 : « une équipe par dépôt », « nouvelle équipe et reprendre équipe »)."""

    def fenetre_du_menu(self):
        f = self.fenetre(commande="claude -r")
        f.demarrer()
        f.montrees = []
        f._se_montrer = lambda: f.montrees.append(True)
        return f

    def depot(self, nom="SmartOS"):
        dossier = os.path.join(self.temporaire, nom)
        os.makedirs(dossier, exist_ok=True)
        return dossier

    def test_nouvelle_equipe_un_onglet_par_role_nomme_et_lance_sur_son_role(self):
        f = self.fenetre_du_menu()
        depot = self.depot()
        self.assertTrue(f.demande_du_menu("equipe\t%s\n" % depot))
        vues = f.sessions()[-2:]
        self.assertEqual([v.demarrages[0][1] for v in vues], [depot, depot])
        self.assertEqual(
            [v.envois for v in vues],
            [["clear; claude --model claude-fable-5-1 -n 'Architecte SmartOS' architecte\n"],
             ["clear; claude --model claude-opus-5-5 -n 'Orchestrateur SmartOS' orchestre\n"]])
        self.assertEqual([f._titres[v] for v in vues],
                         ["Architecte : SmartOS", "Orchestrateur : SmartOS"])
        self.assertEqual(f.montrees, [True])

    def test_l_equipe_est_memorisee_role_par_role_quand_ses_sessions_sont_connues(self):
        f = self.fenetre_du_menu()
        depot = self.depot()
        f.demande_du_menu("equipe\t%s\n" % depot)
        archi, orch = f.sessions()[-2:]
        f.relire_le_registre()
        self.assertEqual(f._equipes(), {})          # rien de connu : rien d'ecrit
        self.statusline(os.getpid(), f.identifiant_de(archi), "sess-archi", depot)
        f.relire_le_registre()
        self.assertEqual(f._equipes(), {depot: {"Architecte": "sess-archi"}})
        self.statusline(os.getpid() + 1, f.identifiant_de(orch), "sess-orch", depot)
        f.relire_le_registre()
        self.assertEqual(f._equipes(), {depot: {"Architecte": "sess-archi",
                                                 "Orchestrateur": "sess-orch"}})

    def test_reprendre_equipe_rouvre_ses_sessions_par_claude_r(self):
        depot = self.depot()
        f = self.fenetre(commande="claude -r",
                         equipes=json.dumps({depot: {"Architecte": "sess-archi",
                                                     "Orchestrateur": "sess-orch"}}))
        f.demarrer()
        f.montrees = []
        f._se_montrer = lambda: f.montrees.append(True)
        self.assertTrue(f.demande_du_menu("reprendre-equipe\t%s\n" % depot))
        vues = f.sessions()[-2:]
        self.assertEqual([v.envois for v in vues],
                         [["clear; claude -r sess-archi\n"], ["clear; claude -r sess-orch\n"]])
        self.assertEqual([f._titres[v] for v in vues],
                         ["Architecte : SmartOS", "Orchestrateur : SmartOS"])
        self.assertEqual([v.demarrages[0][1] for v in vues], [depot, depot])
        self.assertEqual(f.montrees, [True])

    def test_reprendre_equipe_saute_ce_qui_est_deja_ouvert(self):
        """Ici (meme dock) comme ailleurs (instance vivante) : jamais deux `claude -r` sur
        la meme conversation. Une equipe entierement ouverte reste un succes."""
        depot = self.depot()
        f = self.fenetre(commande="claude -r",
                         equipes=json.dumps({depot: {"Architecte": "sess-archi",
                                                     "Orchestrateur": "sess-orch"}}))
        f.demarrer()
        f.montrees = []
        f._se_montrer = lambda: f.montrees.append(True)
        self.statusline(os.getpid() + 1, "onglet-ailleurs", "sess-orch", depot)
        self.assertTrue(f.demande_du_menu("reprendre-equipe\t%s\n" % depot))
        self.assertEqual([v.envois for v in f.sessions()[1:]],
                         [["clear; claude -r sess-archi\n"]])
        archi = f.sessions()[-1]
        self.statusline(os.getpid(), f.identifiant_de(archi), "sess-archi", depot)
        f.relire_le_registre()
        self.assertTrue(f.demande_du_menu("reprendre-equipe\t%s\n" % depot))
        self.assertEqual(len(f.sessions()), 2)
        self.assertEqual(f.montrees, [True, True])

    def test_sans_equipe_memorisee_refus(self):
        f = self.fenetre_du_menu()
        self.assertFalse(f.demande_du_menu("reprendre-equipe\t%s\n" % self.depot()))
        self.assertEqual(len(f.sessions()), 1)
        self.assertEqual(f.montrees, [])

    def test_nouvelle_equipe_remplace_l_ancienne_du_meme_depot_seulement(self):
        depot = self.depot()
        autre = self.depot("qtpy6")
        f = self.fenetre(commande="claude -r",
                         equipes=json.dumps({depot: {"Architecte": "vieille"},
                                             autre: {"Architecte": "intacte"}}))
        f.demarrer()
        f._se_montrer = lambda: None
        self.assertTrue(f.demande_du_menu("equipe\t%s\n" % depot))
        self.assertEqual(f._equipes(), {autre: {"Architecte": "intacte"}})
        archi = f.sessions()[-2]
        self.statusline(os.getpid(), f.identifiant_de(archi), "neuve", depot)
        f.relire_le_registre()
        self.assertEqual(f._equipes(), {autre: {"Architecte": "intacte"},
                                        depot: {"Architecte": "neuve"}})

    def test_ligne_de_commande_sans_dock_qui_ecoute(self):
        """`claude_dolphin.sh` lance le dock lui-meme avec la demande (pas de Konsole de
        repli pour une equipe)."""
        depot = self.depot()
        self.assertEqual(demande_de_la_ligne_de_commande(["dock", "--equipe", depot]),
                         (depot, "equipe\t%s\n" % depot))
        self.assertEqual(demande_de_la_ligne_de_commande(["dock", "--reprendre-equipe", depot]),
                         (depot, "reprendre-equipe\t%s\n" % depot))
        self.assertEqual(demande_de_la_ligne_de_commande(["dock", depot]), (depot, None))
        self.assertEqual(demande_de_la_ligne_de_commande(["dock"]), (None, None))

    def test_equipes_illisibles_ignorees(self):
        f = self.fenetre(commande="claude -r", equipes="pas du json")
        f.demarrer()
        self.assertEqual(f._equipes(), {})
        self.assertFalse(f.demande_du_menu("reprendre-equipe\t%s\n" % self.depot()))


class TestTitre(Banc):
    """« cacher la barre de titre et reporter les bouton de fenetre à gauche des boutons de
    bascule mosaique/onglet et + [...] deux boutons, un pour la synthèse vocale et un pour la
    dictée, indépendants (entre le plus et le boutons de fenetre) [...] elargir la taille des
    onglets en vue onglet » (utilisateur, 11/10/2026)."""

    def setUp(self):
        super().setUp()
        self.registre = os.path.join(self.temporaire, "claude-windows")
        os.makedirs(self.registre, exist_ok=True)
        self.appels = os.path.join(self.temporaire, "appels")
        self.script_voix = os.path.join(self.temporaire, "claude-voix.sh")
        with open(self.script_voix, "w") as fichier:
            fichier.write('#!/bin/sh\necho "$@" >> %s\n' % self.appels)
        os.chmod(self.script_voix, 0o755)

    def temoin(self, nom):
        open(os.path.join(self.registre, nom), "w").close()

    @staticmethod
    def rangee(f):
        coin = f._onglets.cornerWidget(Qt.TopRightCorner)
        disposition = coin.layout()
        return [disposition.itemAt(i).widget().toolTip() for i in range(disposition.count())]

    def test_sans_barre_et_boutons_dans_l_ordre(self):
        f = self.fenetre()
        self.assertTrue(f.windowFlags() & Qt.FramelessWindowHint)
        self.assertEqual(self.rangee(f)[:2], ["Ouvrir une instance Claude",
                                              "Afficher les instances en mosaïque"])
        self.assertIn("synthèse vocale", self.rangee(f)[2])
        self.assertIn("dictée", self.rangee(f)[3])
        self.assertEqual(self.rangee(f)[4:], ["Réduire", "Agrandir / restaurer", "Fermer"])
        mosaique = f._mosaique._boutons_de_titre
        self.assertEqual(mosaique[:2], (f._mosaique._bouton_nouveau,
                                        f._mosaique._bouton_disposition))
        self.assertEqual([b.toolTip() for b in mosaique[2:]], self.rangee(f)[2:])
        # Tous de la meme taille, et pas de bandeau au-dessus des onglets de cellule.
        self.assertEqual({(b.width(), b.height()) for b in mosaique}, {(24, 24)})
        coin = f._onglets.cornerWidget().layout()
        self.assertEqual({(coin.itemAt(i).widget().width(), coin.itemAt(i).widget().height()) for i in range(coin.count())},
                         {(24, 24)})
        # Le coin couvre toute la barre, rangee en haut : Qt le cale sinon contre le bas.
        barre = f._onglets.tabBar().sizeHint().height()
        self.assertGreaterEqual(f._onglets.cornerWidget().sizeHint().height(), barre)
        self.assertEqual(coin.alignment(), Qt.AlignTop)
        self.assertEqual(f._mosaique.hauteur_bandeau, 0)
        self.assertFalse(any(b.isVisible() for b in mosaique))

    def test_titre_entier_et_raccourci_par_la_gauche(self):
        f = self.fenetre()
        f.demarrer()
        titre = "Une conversation au titre nettement plus long que vingt-quatre"
        f._titre_change(f.sessions()[0], titre)
        self.assertEqual(f._onglets.tabText(0), titre)
        self.assertEqual(f._onglets.tabBar().elideMode(), Qt.ElideLeft)
        self.assertFalse(f._onglets.usesScrollButtons())

    def test_etat_vocal_lu_dans_le_registre(self):
        f = self.fenetre()
        self.assertEqual(f.etat_vocal(), {"parole": False, "dictee": False})
        self.temoin("voix-active")
        self.temoin("parole-coupee")
        self.assertEqual(f.etat_vocal(), {"parole": False, "dictee": True})
        f.relire_le_registre()
        self.assertIn("Rallumer", f._boutons_vocaux["parole"][0].toolTip())
        self.assertIn("Couper", f._boutons_vocaux["dictee"][1].toolTip())

    def test_les_boutons_appellent_claude_voix(self):
        f = self.fenetre()
        self.temoin("voix-active")
        f._boutons_vocaux["dictee"][0].click()
        f.basculer_vocal("parole")
        for _ in range(500):   # startDetached : attendre le script par son effet
            if len(self.lignes_appelees()) == 2:
                break
            time.sleep(0.01)
        self.assertEqual(sorted(self.lignes_appelees()), ["--dictee off", "--parole off"])

    def lignes_appelees(self):
        try:
            with open(self.appels) as fichier:
                return fichier.read().splitlines()
        except FileNotFoundError:
            return []


if __name__ == "__main__":
    unittest.main()

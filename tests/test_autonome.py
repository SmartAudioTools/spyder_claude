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
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from qtpy.QtCore import QSettings, Signal  # noqa: E402
from qtpy.QtWidgets import QApplication, QTabBar, QVBoxLayout, QWidget  # noqa: E402

APP = QApplication.instance() or QApplication([])

from spyder_claude import usage  # noqa: E402
from spyder_claude.autonome.fenetre import FenetreClaude  # noqa: E402


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
        shutil.rmtree(self.temporaire, ignore_errors=True)

    def reglages(self, **valeurs):
        reglages = QSettings(self.chemin_reglages, QSettings.IniFormat)
        reglages.setValue("commande", "cat")   # inerte, et jamais lancee : vues fausses
        for cle, valeur in valeurs.items():
            reglages.setValue(cle, valeur)
        reglages.sync()
        return reglages

    def fenetre(self, **valeurs):
        fenetre = FenetreClaude(reglages=self.reglages(**valeurs), dossier=self.temporaire,
                                fabrique_vue=FausseVue)
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


if __name__ == "__main__":
    unittest.main()

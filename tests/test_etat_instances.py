# -*- coding: utf-8 -*-
"""Tests du protocole d'etat partage avec claude-window.sh.

CE QU'ILS PROUVENT, et qu'aucune lecture de code ne prouve : que le format ecrit par le
hook est bien celui que le panneau relit. C'est le seul endroit ou deux programmes ecrits
dans deux langages se donnent rendez-vous, donc le seul endroit ou une faute de frappe
dans un nom de cle passerait inapercue jusqu'a l'usage — un panneau qui n'affiche jamais
la moindre couleur, sans un message d'erreur.

Le registre est deplace par XDG_RUNTIME_DIR : aucun test n'ecrit dans le vrai dossier,
ou tournent les instances de l'utilisateur.

Lancement :
    python3 tests/test_etat_instances.py
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spyder_claude import etat_instances  # noqa: E402


class BaseRegistre(unittest.TestCase):
    """Un registre jetable par test, dans un dossier temporaire."""

    def setUp(self):
        self.dossier_racine = tempfile.mkdtemp(prefix="claude-etat-")
        self._ancien = os.environ.get("XDG_RUNTIME_DIR")
        os.environ["XDG_RUNTIME_DIR"] = self.dossier_racine
        self.registre = etat_instances.dossier_etat()
        os.makedirs(self.registre, exist_ok=True)

    def tearDown(self):
        if self._ancien is None:
            os.environ.pop("XDG_RUNTIME_DIR", None)
        else:
            os.environ["XDG_RUNTIME_DIR"] = self._ancien
        shutil.rmtree(self.dossier_racine, ignore_errors=True)

    def ecrire_instance(self, pid, etat, session, service="spyder", depuis=1):
        """Ecrit un fichier inst-<pid> EXACTEMENT comme le fait claude-window.sh."""
        with open(os.path.join(self.registre, "inst-%s" % pid), "w",
                  encoding="utf-8") as fichier:
            fichier.write("CW_STATE=%s\n" % etat)
            fichier.write("CW_SINCE=%s\n" % depuis)
            fichier.write("CW_KONSOLE=4242\n")
            fichier.write("CW_SVC=%s\n" % service)
            fichier.write("CW_SESSION=%s\n" % session)


class TestLectureDuRegistre(BaseRegistre):

    def test_une_instance_de_panneau_est_lue(self):
        self.ecrire_instance(os.getpid(), "waiting", "abc123")
        self.assertEqual(etat_instances.etats_par_onglet(), {"abc123": "waiting"})

    def test_une_instance_konsole_est_ignoree(self):
        """Le panneau ne doit colorer QUE ses propres onglets.

        Sans ce filtre, une fenetre Konsole dont le numero de session vaut « 1 »
        teindrait l'onglet d'un panneau dont l'identifiant vaudrait « 1 » : les deux
        espaces de nommage n'ont rien a voir.
        """
        self.ecrire_instance(os.getpid(), "waiting", "1",
                             service="org.kde.konsole-999")
        self.assertEqual(etat_instances.etats_par_onglet(), {})

    def test_une_instance_morte_est_ignoree(self):
        """Un PID libre ne doit rien colorer — sinon un onglet reste rouge pour toujours."""
        # PID hors de portee : aucun processus ne peut le porter.
        self.ecrire_instance(2 ** 31 - 1, "waiting", "mort")
        self.assertEqual(etat_instances.etats_par_onglet(), {})

    def test_le_registre_absent_ne_leve_pas(self):
        shutil.rmtree(self.registre)
        self.assertEqual(etat_instances.etats_par_onglet(), {})

    def test_un_fichier_illisible_ne_leve_pas(self):
        with open(os.path.join(self.registre, "inst-%s" % os.getpid()), "wb") as fichier:
            fichier.write(b"\xff\xfe pas du texte\n")
        self.assertEqual(etat_instances.etats_par_onglet(), {})

    def test_le_fichier_n_est_pas_execute(self):
        """Le registre est du TEXTE, jamais du code.

        Il vit dans $XDG_RUNTIME_DIR : y sourcer un fichier donnerait a n'importe quel
        programme capable d'y ecrire les droits du processus Spyder.
        """
        temoin = os.path.join(self.dossier_racine, "temoin")
        with open(os.path.join(self.registre, "inst-%s" % os.getpid()), "w",
                  encoding="utf-8") as fichier:
            fichier.write("CW_STATE=$(touch %s)idle\n" % temoin)
            fichier.write("CW_SVC=spyder\nCW_SESSION=x\n")
        etats = etat_instances.etats_par_onglet()
        self.assertFalse(os.path.exists(temoin))
        self.assertEqual(etats["x"], "$(touch %s)idle" % temoin)


class TestDemandeDeFocus(BaseRegistre):

    def test_absente_par_defaut(self):
        self.assertIsNone(etat_instances.demande_de_focus())

    def test_deposee_puis_consommee_une_seule_fois(self):
        """UNE demande, UNE activation.

        Si elle se relisait, le panneau reprendrait le clavier a chaque battement de son
        minuteur : impossible de changer d'onglet a la main.
        """
        etat_instances.deposer_demande_de_focus("abc123")
        self.assertEqual(etat_instances.demande_de_focus(), "abc123")
        self.assertIsNone(etat_instances.demande_de_focus())

    def test_lecture_sans_consommation(self):
        etat_instances.deposer_demande_de_focus("abc123")
        self.assertEqual(etat_instances.demande_de_focus(consommer=False), "abc123")
        self.assertEqual(etat_instances.demande_de_focus(), "abc123")


class TestVariablesDeSession(unittest.TestCase):

    def test_les_deux_variables_attendues_par_le_hook(self):
        variables = etat_instances.variables_de_session("abc123", 4242)
        self.assertEqual(variables["SPYDER_CLAUDE_PANE"], "abc123")
        self.assertEqual(variables["SPYDER_CLAUDE_WINDOW"], "4242")

    def test_rendu_classique_pour_garder_l_historique_du_terminal(self):
        variables = etat_instances.variables_de_session("abc123", 4242)
        self.assertEqual(variables["CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN"], "1")

    def test_les_couleurs_sont_celles_du_hook(self):
        """Les teintes sont recopiees de claude-window.sh : elles doivent coller.

        Ce test n'a l'air de rien, mais c'est lui qui attrapera le jour ou l'une des deux
        listes bougera sans l'autre — l'utilisateur verrait alors deux rouges differents
        selon que l'instance est en fenetre ou en panneau.
        """
        self.assertEqual(etat_instances.COULEURS["waiting"], "#3a1414")
        self.assertEqual(etat_instances.COULEURS["idle"], "#14351f")
        self.assertIsNone(etat_instances.COULEURS["busy"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

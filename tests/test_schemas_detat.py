# -*- coding: utf-8 -*-
"""Tests des jeux de couleurs d'etat — le fond rouge/vert, reporte dans le panneau.

CE QU'ILS PROUVENT, et qu'aucune lecture de code ne prouve : que le moteur de Konsole VOIT
les jeux fabriques par le greffon. C'est le point exact ou ce dispositif peut echouer sans
rien dire — qtermwidget met la liste de ses jeux de couleurs EN CACHE a la premiere
lecture, si bien qu'un jeu ecrit une milliseconde trop tard n'existe simplement pas, et
que `setColorScheme` le refuse en silence. Le panneau afficherait alors des instances
toutes grises, sans le moindre message.

Lancement :
    QT_QPA_PLATFORM=offscreen <python du venv Spyder> tests/test_schemas_detat.py
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from qtpy.QtWidgets import QApplication  # noqa: E402

from smartos_konsole import konsole_view  # noqa: E402

from spyder_claude import etat_instances  # noqa: E402


APPLICATION = QApplication.instance() or QApplication(sys.argv)


def preparer_tous_les_schemas():
    """Ce que fait PanneauClaude a sa construction, avant toute session."""
    profil = konsole_view.profil_konsole()
    ecrits = {}
    for etat, nom in etat_instances.SCHEMAS.items():
        couleur = etat_instances.COULEURS.get(etat)
        if nom and couleur:
            ecrits[etat] = konsole_view.preparer_schema(
                profil, couleur, "#DFE1E2", couleur, nom_derive=nom)
    return ecrits


class TestFabrication(unittest.TestCase):
    """Cette moitie-la ne demande pas le moteur : elle n'ecrit que des fichiers INI."""

    def test_un_jeu_par_etat_signalable(self):
        ecrits = preparer_tous_les_schemas()
        self.assertEqual(ecrits.get("waiting"), "ClaudeAttente")
        self.assertEqual(ecrits.get("idle"), "ClaudeDisponible")

    def test_busy_ne_fabrique_rien(self):
        """« Claude travaille » n'a pas de couleur : c'est le fond normal de l'IDE."""
        self.assertIsNone(etat_instances.SCHEMAS["busy"])

    def test_le_fond_ecrit_est_bien_celui_du_hook(self):
        preparer_tous_les_schemas()
        chemin = os.path.join(konsole_view.DOSSIER_SCHEMAS,
                              "ClaudeAttente.colorscheme")
        self.assertTrue(os.path.isfile(chemin))
        contenu = konsole_view._lire_ini(chemin)
        # « #3a1414 » s'ecrit « 58,20,20 » dans un .colorscheme.
        self.assertEqual(contenu["Background"]["Color"], "58,20,20")

    def test_les_seize_couleurs_ansi_ne_sont_pas_touchees(self):
        """Le fond change, la palette non : c'est elle qui rend `ls` et l'invite lisibles."""
        preparer_tous_les_schemas()
        contenu = konsole_view._lire_ini(
            os.path.join(konsole_view.DOSSIER_SCHEMAS, "ClaudeAttente.colorscheme"))
        self.assertIn("Color3", contenu)
        self.assertNotEqual(contenu["Color3"]["Color"], "58,20,20")


@unittest.skipUnless(konsole_view.DISPONIBLE, "binding qtermwidget non construit")
class TestLeMoteurLesVoit(unittest.TestCase):
    """La moitie qui compte : le moteur connait-il les jeux, et les accepte-t-il ?"""

    @classmethod
    def setUpClass(cls):
        # AVANT toute creation de widget — c'est tout le sujet de ce test.
        preparer_tous_les_schemas()
        cls.vue = konsole_view.VueKonsole(None, couleur_fond="#19232D",
                                          couleur_texte="#DFE1E2")

    @classmethod
    def tearDownClass(cls):
        cls.vue.arreter(force=True)
        cls.vue.deleteLater()
        APPLICATION.processEvents()

    def test_les_jeux_sont_dans_la_liste_du_moteur(self):
        disponibles = list(self.vue._terminal.availableColorSchemes())
        self.assertIn("ClaudeAttente", disponibles)
        self.assertIn("ClaudeDisponible", disponibles)

    def test_appliquer_un_jeu_d_etat(self):
        self.assertTrue(self.vue.appliquer_schema("ClaudeAttente"))
        self.assertTrue(self.vue.appliquer_schema("ClaudeDisponible"))

    def test_revenir_au_fond_de_l_ide(self):
        """Sans nom, on revient au jeu d'origine — c'est l'etat « busy »."""
        self.assertTrue(self.vue.appliquer_schema(None))


if __name__ == "__main__":
    unittest.main(verbosity=2)

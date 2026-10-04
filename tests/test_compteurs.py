# -*- coding: utf-8 -*-
"""Tests des widgets de consommation — offscreen, sans Spyder.

CE QU'ILS PROUVENT : que le dessin ne LEVE JAMAIS, quelle que soit la donnee (absente, a
zero, en plein, au-dela de l'echelle) — une exception dans paintEvent laisse le peintre
desequilibre et fait tomber le processus en segfault a la capture suivante (cf. le piege
SpyderPalette.SIZE_BORDER_RADIUS documente dans compteurs.py). Et qu'une donnee absente
n'affiche jamais un 0 % qui rassurerait a tort.

Lancement :
    QT_QPA_PLATFORM=offscreen <python du venv Spyder> tests/test_compteurs.py
"""

import os
import sys
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from qtpy.QtWidgets import QApplication  # noqa: E402

from spyder_claude import compteurs  # noqa: E402

APPLICATION = QApplication.instance() or QApplication(sys.argv)


class TestCompteur(unittest.TestCase):

    def _cadran(self, cote=18):
        cadran = compteurs.Compteur()
        cadran.resize(cote, cote)
        return cadran

    def test_le_compteur_se_dessine_sans_lever_a_vide(self):
        cadran = self._cadran()
        cadran.poser_valeur(None)
        cadran.grab()  # ne doit pas lever

    def test_le_compteur_se_dessine_sans_lever_a_zero(self):
        cadran = self._cadran()
        cadran.poser_valeur(0)
        cadran.grab()

    def test_rien_nest_dessine_a_larret(self):
        """Demande de l'utilisateur, 04/10/2026 : « il devrait etre invisible quand la
        vitesse est a zero, pour ne pas poluer l'affichage pour rien ». Ni a zero, ni sans
        mesure : pas meme la piste grise."""
        for valeur in (None, 0):
            cadran = self._cadran()
            cadran.poser_valeur(valeur)
            image = cadran.grab().toImage()
            fond = image.pixel(0, 0)
            self.assertTrue(all(image.pixel(x, y) == fond
                                for x in range(image.width()) for y in range(image.height())),
                            "quelque chose est peint a %r" % (valeur,))

    def test_le_compteur_se_dessine_sans_lever_a_mi_course(self):
        cadran = self._cadran()
        cadran.poser_pleine_echelle(6.0)
        cadran.poser_valeur(300)  # 3,00 $/h sur une echelle a 6,00 $/h
        cadran.grab()

    def test_le_compteur_se_dessine_sans_lever_au_plein(self):
        cadran = self._cadran()
        cadran.poser_pleine_echelle(6.0)
        cadran.poser_valeur(600)
        cadran.grab()

    def test_le_compteur_se_dessine_sans_lever_au_dela_du_plein(self):
        """Une conversation qui s'emballe peut depasser l'echelle : le cadran doit
        rester a fond, pas s'etendre hors de son cercle."""
        cadran = self._cadran()
        cadran.poser_pleine_echelle(6.0)
        cadran.poser_valeur(3 * 600)
        cadran.grab()

    def test_le_compteur_se_dessine_sans_lever_a_taille_nulle(self):
        """Un widget pas encore mis en page (largeur/hauteur a 0) ne doit pas diviser
        par zero dans le calcul de la piste."""
        cadran = compteurs.Compteur()
        cadran.poser_valeur(100)
        cadran.grab()


class TestBandeauUsage(unittest.TestCase):

    def _bande(self, largeur=200):
        bande = compteurs.BandeauUsage()
        bande.resize(largeur, compteurs.BandeauUsage.HAUTEUR)
        return bande

    def test_le_bandeau_ne_grandit_pas(self):
        bande = self._bande()
        self.assertEqual(bande.sizeHint().height(), compteurs.BandeauUsage.HAUTEUR)
        self.assertEqual(bande.height(), compteurs.BandeauUsage.HAUTEUR)

    def test_une_jauge_sans_donnee_naffiche_pas_zero_pour_cent(self):
        """Rien a montrer : le dessin ne doit pas lever, et le contrat de poser_fenetres
        (None = non mesurable) doit rester distinct d'un vrai 0 %, verifie ici cote
        widget — usage.py garantit deja la distinction cote donnees."""
        bande = self._bande()
        bande.poser_fenetres({"cinq_heures": None, "sept_jours": None})
        bande.grab()  # ne doit pas lever

    def test_une_jauge_avec_donnee_se_dessine_sans_lever(self):
        bande = self._bande()
        bande.poser_fenetres({
            "cinq_heures": {"pct": 74, "fin": time.time() + 3600, "age": 5},
            "sept_jours": {"pct": 41, "fin": time.time() + 200000, "age": 5},
        })
        bande.grab()

    def test_une_jauge_perimee_se_dessine_sans_lever(self):
        bande = self._bande()
        bande.poser_fenetres({
            "cinq_heures": {"pct": 90, "fin": time.time() + 3600,
                           "age": compteurs.usage.PEREMPTION + 1},
            "sept_jours": None,
        })
        bande.grab()

    def test_un_rayon_en_chaine_ne_fait_pas_tomber_le_peintre(self):
        """Le vrai scenario : SpyderPalette.SIZE_BORDER_RADIUS vaut '4px', une chaine, pas
        un nombre. On le simule en substituant _rayon_cadre_defaut - c'est exactement ce
        que ferait un vrai theme Spyder importe."""
        bande = self._bande()
        bande.poser_fenetres({
            "cinq_heures": {"pct": 50, "fin": 0, "age": 5},
            "sept_jours": {"pct": 50, "fin": 0, "age": 5},
        })
        original = compteurs._rayon_cadre_defaut
        compteurs._rayon_cadre = None
        compteurs._rayon_cadre_defaut = lambda: "4px"
        try:
            bande.grab()  # ne doit pas lever
        finally:
            compteurs._rayon_cadre_defaut = original
            compteurs._rayon_cadre = None


class TestCouleurParAllure(unittest.TestCase):
    """Preuve visuelle, par ECHANTILLONNAGE DE PIXEL — pas seulement sur les fonctions
    pures — que la couleur du remplissage suit bien l'ecart avec l'allure ideale."""

    def _bande_avec(self, pct, fin_dans_s, largeur=200):
        bande = compteurs.BandeauUsage()
        bande.resize(largeur, compteurs.BandeauUsage.HAUTEUR)
        bande.poser_fenetres({
            "cinq_heures": {"pct": pct, "fin": time.time() + fin_dans_s, "age": 1},
            "sept_jours": None,
        })
        return bande

    def _bande_avec_7j(self, pct, fin_dans_s, largeur=200):
        bande = compteurs.BandeauUsage()
        bande.resize(largeur, compteurs.BandeauUsage.HAUTEUR)
        bande.poser_fenetres({
            "cinq_heures": None,
            "sept_jours": {"pct": pct, "fin": time.time() + fin_dans_s, "age": 1},
        })
        return bande

    def test_le_cas_reel_du_31_07_est_maintenant_orange(self):
        """Releve EN DIRECT le 31/07/2026 sur la fenetre de 7 jours : 19 % consomme avec
        environ 1 jour ecoule sur 7 (~14,3 % d'allure ideale), un ecart de 4,7 points qui
        restait VERT avec le premier reglage (5, 15) — l'utilisateur le voyait pourtant
        clairement en avance. Verrouille le resserrement a (2, 8).

        A 19 %, le remplissage ne fait que ~18 px de large (sur une jauge de ~97 px) :
        l'echantillon doit rester DANS ce remplissage etroit, pas a un decalage fixe copie
        des autres tests (qui, eux, portent sur des remplissages bien plus larges)."""
        largeur = 200
        gauche_7j = (largeur - compteurs.BandeauUsage.ECART) / 2.0 + compteurs.BandeauUsage.ECART
        bande = self._bande_avec_7j(pct=19, fin_dans_s=6 * 86400, largeur=largeur)
        couleur = self._couleur_a(bande, int(gauche_7j) + 8)
        self.assertEqual((couleur.red(), couleur.green(), couleur.blue()), (255, 152, 0))

    def _couleur_a(self, bande, x):
        image = bande.grab().toImage()
        # PRES DU HAUT, pas au milieu : le texte est centre verticalement sur la jauge
        # (AlignCenter dans tout le rectangle) et un echantillon au milieu de la hauteur
        # tombe parfois sur un trait de lettre (blanc), pas sur le remplissage — mesure en
        # direct. y=4 reste au-dessus du texte, sous le contour et les coins arrondis, et
        # au-dessus de la zone des graduations (limitee au dernier quart depuis le bas).
        return image.pixelColor(x, 4)

    def test_bien_en_avance_sur_lallure_est_rouge(self):
        # 90 % consomme, fenetre de 5 h a peine entamee (10 min sur 300) : tres en avance.
        bande = self._bande_avec(pct=90, fin_dans_s=5 * 3600 - 600)
        couleur = self._couleur_a(bande, 50)
        self.assertEqual((couleur.red(), couleur.green(), couleur.blue()), (211, 47, 47))

    def test_bien_en_retard_sur_lallure_est_vert(self):
        # 40 % consomme, fenetre de 5 h presque terminee (1 min restante) : loin derriere
        # l'allure, donc rassurant malgre un pourcentage qui pourrait sembler eleve.
        bande = self._bande_avec(pct=40, fin_dans_s=60)
        couleur = self._couleur_a(bande, 20)
        self.assertEqual((couleur.red(), couleur.green(), couleur.blue()), (76, 175, 80))


class TestFractionEcoulee(unittest.TestCase):

    def test_sans_fin_rend_none(self):
        self.assertIsNone(compteurs.fraction_ecoulee({"fin": None}, 3600))
        self.assertIsNone(compteurs.fraction_ecoulee({"fin": 0}, 3600))

    def test_sans_duree_rend_none(self):
        self.assertIsNone(compteurs.fraction_ecoulee({"fin": 1000}, None))

    def test_fenetre_absente_rend_none(self):
        self.assertIsNone(compteurs.fraction_ecoulee(None, 3600))

    def test_a_mi_chemin(self):
        """Fin dans 1800 s, fenetre de 3600 s : la moitie est deja ecoulee."""
        maintenant = 10_000.0
        fraction = compteurs.fraction_ecoulee(
            {"fin": maintenant + 1800}, 3600, maintenant=maintenant)
        self.assertAlmostEqual(fraction, 0.5)

    def test_toute_fraiche(self):
        maintenant = 10_000.0
        fraction = compteurs.fraction_ecoulee(
            {"fin": maintenant + 3600}, 3600, maintenant=maintenant)
        self.assertAlmostEqual(fraction, 0.0)

    def test_bornee_a_1_si_la_fin_est_deja_passee(self):
        """La fenetre est en train de se reinitialiser : la barre reste DANS le cadre,
        jamais au-dela — un depassement visuel laisserait croire a un defaut de dessin."""
        maintenant = 10_000.0
        fraction = compteurs.fraction_ecoulee(
            {"fin": maintenant - 500}, 3600, maintenant=maintenant)
        self.assertEqual(fraction, 1.0)

    def test_bornee_a_0_si_la_fin_est_plus_loin_que_la_duree(self):
        """Un `fin` incoherent (plus loin que la duree connue de la fenetre) ne doit pas
        faire remonter la barre avant le bord gauche."""
        maintenant = 10_000.0
        fraction = compteurs.fraction_ecoulee(
            {"fin": maintenant + 7200}, 3600, maintenant=maintenant)
        self.assertEqual(fraction, 0.0)


class TestNombre(unittest.TestCase):

    def test_chaine_avec_px(self):
        self.assertEqual(compteurs._nombre("4px", 0.0), 4.0)

    def test_chaine_sans_unite(self):
        self.assertEqual(compteurs._nombre("4", 0.0), 4.0)

    def test_deja_un_nombre(self):
        self.assertEqual(compteurs._nombre(4, 0.0), 4.0)

    def test_forme_illisible_rend_le_defaut(self):
        self.assertEqual(compteurs._nombre("pas un nombre", 2.5), 2.5)
        self.assertEqual(compteurs._nombre(None, 2.5), 2.5)


class TestCouleurSeuil(unittest.TestCase):

    def test_les_trois_paliers_sont_nets(self):
        vert = compteurs.couleur_seuil(10, 50, 80)
        orange = compteurs.couleur_seuil(60, 50, 80)
        rouge = compteurs.couleur_seuil(90, 50, 80)
        self.assertEqual(vert.getRgb()[:3], (76, 175, 80))
        self.assertEqual(orange.getRgb()[:3], (255, 152, 0))
        self.assertEqual(rouge.getRgb()[:3], (211, 47, 47))


if __name__ == "__main__":
    unittest.main(verbosity=2)

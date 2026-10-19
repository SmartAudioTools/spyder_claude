# -*- coding: utf-8 -*-
"""Tests de la barre de defilement emulee — offscreen, sans Claude et sans moteur de terminal.

CE QU'ILS PROUVENT, ET CE QU'ILS NE PROUVENT PAS. Un faux Claude applique la regle mesuree
par les sondes du 19/10/2026 (un cran = une ligne, deux s'ils arrivent a moins de 40 ms du
precedent, cran perdu a l'inversion, Ctrl+End en bas, butee en haut, touches page d'un
nombre constant de lignes ; ni les touches ni Ctrl+End ne changent le precedent de la
molette) ; les tests verifient que la barre en deduit la VRAIE position, que le haut se
detecte exactement et qu'un ecran uniforme ne le fait pas conclure a tort. Ils valident la
logique de la file et du modele, PAS la regle elle-meme : c'est la sonde reelle
(outils_smartos/sonde_barre.py) qui la confronte a Claude Code.

Lancement :
    QT_QPA_PLATFORM=offscreen <python du venv Spyder> tests/test_defilement.py
"""

import os
import re
import sys
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from qtpy.QtCore import QCoreApplication, QPoint, QPointF, Qt, Signal  # noqa: E402
from qtpy.QtGui import QWheelEvent  # noqa: E402
from qtpy.QtWidgets import QApplication, QHBoxLayout, QWidget  # noqa: E402

from spyder_claude.defilement import (CTRL_FIN, PAGE_BAS, PAGE_HAUT,  # noqa: E402
                                      BarreDefilementEmulee, ModeleDefilement,
                                      suivre)

APPLICATION = QApplication.instance() or QApplication(sys.argv)
GARDES = []
SGR = re.compile(r"\x1b\[<(64|65);\d+;\d+M")


class FauxTerminal(QWidget):
    selection = ""

    def selectedText(self, _sauts):  # noqa: N802 - API QTermWidget
        return self.selection


class FauxClaude(QWidget):
    """Tient lieu de VueKonsole : une sortie de `contenu` lignes, vue par `page` lignes."""

    sig_sortie = Signal()
    sig_defilement_au_programme = Signal(bool)

    def __init__(self, contenu, page=10, uniforme=False, touche=4):
        super().__init__()
        self.touche = touche       # lignes par touche page (18 sur 44 lignes chez Claude)
        self.pages = 0
        QHBoxLayout(self)
        self.terminal = FauxTerminal(self)
        self.layout().addWidget(self.terminal)
        self.page = page
        self.lignes = ["" if uniforme else "ligne %d" % i for i in range(contenu)]
        self.p = 0                 # vraie position, lignes au-dessus du bas
        self._precedent = 0        # sens du dernier cran qui a agi
        self._instant = 0.0        # du dernier cran recu
        self.ctrl_fin = 0
        self._annulable = (0, 0)      # (instant, p) d'avant le dernier Ctrl+End

    # -- l'interface de VueKonsole dont la barre se sert
    def widgets_du_terminal(self):
        return [self.terminal]

    def ajouter_a_droite(self, widget):
        self.layout().addWidget(widget)

    def lignes_ecran(self):
        return self.page

    def texte_ecran(self):
        fin = len(self.lignes) - self.p
        return ["> question"] + self.lignes[max(0, fin - self.page + 1):fin]

    def envoyer(self, texte):
        if texte == CTRL_FIN:
            self._annulable = (time.monotonic(), self.p)
            self.p = 0                         # le precedent de la molette reste (sonde_barre)
            self.ctrl_fin += 1
        else:
            self._annuler_ctrl_fin()
        for sens, sequence in ((1, PAGE_HAUT), (-1, PAGE_BAS)):
            for _ in range(texte.count(sequence)):
                self.p = min(max(0, self.p + sens * self.touche), self.haut)
                self.pages += 1
        self.sig_sortie.emit()

    def envoyer_molette(self, crans):
        sens = 1 if crans > 0 else -1
        for _ in range(abs(crans)):
            self.molette(sens)
        self.sig_sortie.emit()

    # -- la regle mesuree
    def _annuler_ctrl_fin(self):
        """Ctrl+End suivi d'autre chose a moins de 40 ms ne compte pas (sonde_barre)."""
        instant, p = self._annulable
        if time.monotonic() - instant < 0.04:
            self.p = p
            self.ctrl_fin -= 1
        self._annulable = (0, 0)

    def molette(self, sens):
        self._annuler_ctrl_fin()
        if self._precedent == -sens:
            self._precedent = 0                # perdu, et ne compte pas comme precedent
            self._instant = time.monotonic()
            return
        self._precedent = sens
        maintenant, precedent = time.monotonic(), self._instant
        self._instant = maintenant
        pas = 2 if maintenant - precedent < 0.04 else 1     # acceleration (sonde --cadence)
        self.p = min(max(0, self.p + sens * pas), self.haut)

    def ecrire(self, n):
        """Claude ajoute `n` lignes : la vue garde sa distance au bas (sonde_suivi, « remonte »)."""
        debut = len(self.lignes)
        self.lignes += ["sortie %d" % i for i in range(debut, debut + n)]
        self.sig_sortie.emit()

    @property
    def haut(self):
        return len(self.lignes) - self.page + 1


def attendre(barre, plafond=15):
    """Jusqu'a ce que la file soit vide : crans espaces, paquets relus."""
    debut = time.monotonic()
    while (barre._verification is not None or barre._paquet or barre._cadence.isActive()
           ) and time.monotonic() - debut < plafond:
        QCoreApplication.processEvents()
        time.sleep(0.01)


class TestSuivre(unittest.TestCase):
    """La lecture du glissement de l'ecran (ex auto-test de sonde_suivi)."""

    def test_cas(self):
        def assert_k(avant, apres, k):
            self.assertEqual(suivre(avant, apres)[0], k)
        pied = ["", "> ", "", "? for shortcuts"]
        texte = ["ligne %d" % i for i in range(200)]

        def ecran(fin, hauteur=20):
            return ["> question"] + texte[fin - hauteur:fin] + pied
        assert_k(ecran(50), ecran(53), 3)
        assert_k(ecran(50), ecran(50), 0)
        assert_k(ecran(50), ecran(50 + 25), None)          # plus d'un ecran : rien en commun
        vide = ["> question"] + [""] * 20 + pied
        assert_k(vide, vide[:5] + ["x"] + vide[6:], 0)      # le pied atteste l'immobilite
        vide = [""] * 20 + ["> "]
        assert_k(vide, vide[:5] + ["x"] + vide[6:], None)   # rien d'unique qui bouge
        # ligne en cours d'ecriture qui change sans defilement
        a, b = ecran(50), ecran(50)
        b[20] = b[20] + " suite"
        assert_k(a, b, 0)
        # repetitions : les lignes vides et les barrieres ne votent pas
        texte[40:60] = ["", "```"] * 10
        assert_k(ecran(70), ecran(72), 2)
        peu = ["> q", "", "a", "", "b", "", "", "", ""] + pied
        assert_k(peu, peu[2:] + ["", ""], 2)


class TestModele(unittest.TestCase):

    def test_inversion_coute_un_cran(self):
        m = ModeleDefilement()
        m.envoyes(10, 1)
        m.envoyes(4, -1)
        self.assertEqual((m.d, m.inversions), (7, 1))

    def test_un_cran_perdu_ne_compte_pas_comme_precedent(self):
        """haut, bas, haut : +1, 0, +1 (sonde --alternance, lignes 7 a 9)."""
        m = ModeleDefilement()
        m.envoyes(1, 1)
        m.envoyes(1, -1)
        m.envoyes(1, 1)
        self.assertEqual(m.d, 2)


class TestBarre(unittest.TestCase):

    def monter(self, contenu=60, **options):
        claude = FauxClaude(contenu, **options)
        barre = BarreDefilementEmulee(claude)
        claude.sig_defilement_au_programme.emit(True)
        # gardes jusqu'a la fin : ramasses pendant qu'un autre se construit, PySide plante
        # (erreurs intermittentes dans QTimer() et eventFilter, 19/10/2026)
        GARDES.append((claude, barre))
        self.addCleanup(claude.sig_defilement_au_programme.emit, False)
        return claude, barre

    def test_la_molette_suit_la_vraie_position(self):
        claude, barre = self.monter()
        for cible in (3, 1, 12, 9, 10, 4, 15, 14, 20):
            barre.aller_a(cible)
            attendre(barre)
            self.assertEqual((barre.modele.d, claude.p), (cible, cible))

    def mesurer(self, barre, plafond=15):
        fini = []
        barre.mesurer(lambda: fini.append(time.monotonic()))
        limite = time.monotonic() + plafond
        while not fini and time.monotonic() < limite:
            QCoreApplication.processEvents()
            time.sleep(0.01)
        return fini

    def test_mesurer_trouve_le_haut_puis_revient_en_bas(self):
        """« barres rayees a l'ouverture d'anciennes sessions » (19/10/2026) : une mesure
        sous le voile, qui rend l'etendue exacte et laisse la vue en bas."""
        claude, barre = self.monter(60)
        barre.mesurer(lambda: None)                 # relectures resserrees le temps de la mesure
        self.assertEqual(barre._calme.interval(), barre.CALME_MESURE)
        barre.modele.haut_connu, barre._mesure = False, None
        barre._sonde.stop()
        self.assertTrue(self.mesurer(barre))
        self.assertEqual(barre._calme.interval(), barre.CALME)
        self.assertEqual((barre.modele.haut_connu, barre.modele.T), (True, claude.haut))
        self.assertEqual((barre.modele.d, claude.p), (0, 0))
        self.assertTrue(self.mesurer(barre))        # deja connu : rendu aussitot, rien d'envoye

    def test_mesurer_au_plafond_revient_en_bas_et_reste_hachure(self):
        """Une session trop longue pour MESURE : jamais une etendue fausse avec l'air exacte
        (Superviseur, 19/10/2026), et Ctrl+End part quand meme."""
        claude, barre = self.monter(3000)
        barre.MESURE = 400
        self.assertTrue(self.mesurer(barre))
        self.assertFalse(barre.modele.haut_connu)
        self.assertEqual((barre.modele.d, claude.p), (0, 0))

    def test_la_molette_va_plus_vite_quand_on_la_tourne_vite(self):
        """« le scroll ligne a ligne est beaucoup trop lent », mais « on ne pourra plus avancer
        ligne a ligne ? » (19/10/2026) : un cran isole vaut une ligne, les suivants d'une
        rafale QApplication.wheelScrollLines() (3 par defaut)."""
        claude, barre = self.monter()
        cran = QWheelEvent(QPointF(1, 1), QPointF(1, 1), QPoint(0, 0), QPoint(0, 120),
                           Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        barre.wheelEvent(cran)
        attendre(barre)
        self.assertEqual((barre.modele.d, claude.p), (1, 1))
        time.sleep(barre.ISOLE / 1000 + 0.05)
        barre.wheelEvent(cran)          # de nouveau isole
        barre.wheelEvent(cran)          # aussitot : rafale
        attendre(barre)
        attendu = 2 + QApplication.wheelScrollLines()
        self.assertEqual((barre.modele.d, claude.p), (attendu, attendu))

    def test_un_jet_de_crans_accelere(self):
        """Le faux Claude doit voir le defaut que l'espacement corrige, sinon il ne prouve rien."""
        claude = FauxClaude(60)
        claude.envoyer_molette(10)
        self.assertGreater(claude.p, 10)

    def test_retour_en_bas_par_ctrl_fin(self):
        claude, barre = self.monter()
        barre.aller_a(12)
        barre.aller_a(0)
        self.assertEqual((claude.p, barre.modele.d, claude.ctrl_fin), (0, 0, 1))

    def test_le_haut_se_detecte_exactement(self):
        claude, barre = self.monter(contenu=33)
        barre.aller_a(1000)
        attendre(barre, plafond=30)
        self.assertTrue(barre.modele.haut_connu)
        self.assertEqual((barre.modele.d, barre.modele.T, claude.p),
                         (claude.haut,) * 3)
        barre.aller_a(claude.haut - 5)    # et la suite repart juste, inversion comprise
        attendre(barre)
        self.assertEqual((barre.modele.d, claude.p), (claude.haut - 5,) * 2)

    def test_les_sauts_lointains_passent_par_les_pages(self):
        claude, barre = self.monter(contenu=300)
        for cible in (150, 140, 40, 205, 3, 1000, 100, 104):
            barre.aller_a(cible)
            attendre(barre, plafond=30)
            vise = min(cible, claude.haut)
            self.assertEqual((barre.modele.d, claude.p), (vise, vise), cible)
        self.assertTrue(barre.modele.haut_connu)
        self.assertEqual((barre._page_claude, barre.modele.T), (4, claude.haut))
        self.assertGreater(claude.pages, 100)

    def test_un_ecran_uniforme_ne_prouve_pas_le_haut(self):
        claude, barre = self.monter(contenu=200, uniforme=True)
        barre.aller_a(30)
        attendre(barre)
        self.assertFalse(barre.modele.haut_connu)

    def test_un_ecran_sans_preuve_ne_fait_pas_deriver(self):
        """Accueil d'une conversation neuve : rien ne bouge, rien ne prouve (sonde_suivi)."""
        claude, barre = self.monter(contenu=9, uniforme=True)
        barre.aller_a(1000)
        attendre(barre)
        self.assertEqual((claude.p, barre.modele.d, barre.modele.T), (0, 0, 0))

    def test_entree_redescend_avant_d_envoyer(self):
        from qtpy.QtCore import QEvent, Qt
        from qtpy.QtGui import QKeyEvent
        claude, barre = self.monter()
        barre.aller_a(8)
        QApplication.sendEvent(claude.terminal,
                               QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier))
        self.assertEqual((claude.p, barre.modele.d), (0, 0))

    def suivre_jusqu_au_calme(self, barre, duree=0.4):
        attendre(barre)
        fin = time.monotonic() + duree
        while time.monotonic() < fin:
            QCoreApplication.processEvents()
            time.sleep(0.01)

    def connaitre_le_haut(self, contenu=60):
        claude, barre = self.monter(contenu=contenu)
        barre.aller_a(1000)
        attendre(barre)
        barre.aller_a(0)
        self.suivre_jusqu_au_calme(barre)
        self.assertTrue(barre.modele.haut_connu)
        return claude, barre

    def test_la_sortie_en_bas_fait_grandir_le_haut_connu(self):
        claude, barre = self.connaitre_le_haut()
        for _ in range(5):
            claude.ecrire(3)
            self.suivre_jusqu_au_calme(barre, 0.08)
        self.suivre_jusqu_au_calme(barre)
        self.assertEqual(barre.modele.T, claude.haut)
        self.assertTrue(barre.modele.haut_connu)

    def test_la_sortie_vue_remontee_aussi(self):
        claude, barre = self.connaitre_le_haut()
        barre.aller_a(6)
        self.suivre_jusqu_au_calme(barre)
        claude.ecrire(4)
        self.suivre_jusqu_au_calme(barre)
        self.assertEqual((barre.modele.d, barre.modele.T), (claude.p, claude.haut))
        self.assertTrue(barre.modele.haut_connu)

    def test_nos_deplacements_ne_sont_pas_de_la_sortie(self):
        """Doit rester SILENCIEUX : remonter, redescendre, sans sortie, ne change pas T."""
        claude, barre = self.connaitre_le_haut()
        T = barre.modele.T
        for cible in (7, 2, 30, 0):
            barre.aller_a(cible)
            self.suivre_jusqu_au_calme(barre)
        claude.sig_sortie.emit()          # un rafraichissement du pied, sans contenu neuf
        self.suivre_jusqu_au_calme(barre)
        self.assertEqual((barre.modele.T, barre.modele.haut_connu), (T, True))

    def test_un_saut_illisible_rehachure(self):
        claude, barre = self.connaitre_le_haut()
        claude.ecrire(claude.page + 5)    # plus d'un ecran d'un seul rafraichissement
        self.suivre_jusqu_au_calme(barre)
        self.assertFalse(barre.modele.haut_connu)

    def test_une_selection_n_est_pas_effacee(self):
        claude, barre = self.connaitre_le_haut()
        claude.terminal.selection = "texte choisi"
        lus = []
        claude.texte_ecran, lire = (lambda: lus.append(1) or lire()), claude.texte_ecran
        claude.ecrire(2)
        self.suivre_jusqu_au_calme(barre)
        self.assertEqual(lus, [])
        self.assertFalse(barre.modele.haut_connu)

    def test_cachee_hors_du_plein_ecran(self):
        claude, barre = self.monter()
        claude.sig_defilement_au_programme.emit(False)
        self.assertFalse(barre.isVisible() or barre.isVisibleTo(claude))


if __name__ == "__main__":
    unittest.main()

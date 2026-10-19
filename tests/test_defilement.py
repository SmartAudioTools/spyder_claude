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

from qtpy.QtCore import QCoreApplication, Signal  # noqa: E402
from qtpy.QtWidgets import QApplication, QHBoxLayout, QWidget  # noqa: E402

from spyder_claude.defilement import (CTRL_FIN, PAGE_BAS, PAGE_HAUT,  # noqa: E402
                                      BarreDefilementEmulee, ModeleDefilement)

APPLICATION = QApplication.instance() or QApplication(sys.argv)
SGR = re.compile(r"\x1b\[<(64|65);\d+;\d+M")


class FauxClaude(QWidget):
    """Tient lieu de VueKonsole : une sortie de `contenu` lignes, vue par `page` lignes."""

    sig_sortie = Signal()
    sig_defilement_au_programme = Signal(bool)

    def __init__(self, contenu, page=10, uniforme=False, touche=4):
        super().__init__()
        self.touche = touche       # lignes par touche page (18 sur 44 lignes chez Claude)
        self.pages = 0
        QHBoxLayout(self)
        self.terminal = QWidget(self)
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
        return claude, barre

    def test_la_molette_suit_la_vraie_position(self):
        claude, barre = self.monter()
        for cible in (3, 1, 12, 9, 10, 4, 15, 14, 20):
            barre.aller_a(cible)
            attendre(barre)
            self.assertEqual((barre.modele.d, claude.p), (cible, cible))

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

    def test_entree_redescend_avant_d_envoyer(self):
        from qtpy.QtCore import QEvent, Qt
        from qtpy.QtGui import QKeyEvent
        claude, barre = self.monter()
        barre.aller_a(8)
        QApplication.sendEvent(claude.terminal,
                               QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier))
        self.assertEqual((claude.p, barre.modele.d), (0, 0))

    def test_cachee_hors_du_plein_ecran(self):
        claude, barre = self.monter()
        claude.sig_defilement_au_programme.emit(False)
        self.assertFalse(barre.isVisible() or barre.isVisibleTo(claude))


if __name__ == "__main__":
    unittest.main()

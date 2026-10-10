# -*- coding: utf-8 -*-
"""Tests de la mosaique — offscreen, sans Spyder et sans moteur de terminal.

CE QU'ILS PROUVENT : qu'aller en mosaique et en revenir ne DETRUIT aucune vue. C'est le
seul vrai danger de ce widget : Qt supprime les enfants avec leur parent, et une vue
detruite, c'est un pty ferme, donc une instance Claude tuee sous les doigts de
l'utilisateur. Le test le verifie a la dure — sous PySide6, toucher un widget dont l'objet
C++ a ete supprime leve RuntimeError, ce qui rend la disparition IMPOSSIBLE a manquer.

Des QWidget ordinaires tiennent lieu de sessions : la mosaique ne sait rien du terminal,
et le test n'a donc besoin ni du binding qtermwidget ni de Spyder.

Lancement :
    QT_QPA_PLATFORM=offscreen <python du venv Spyder> tests/test_mosaique.py
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from qtpy.QtCore import QEvent  # noqa: E402
from qtpy.QtWidgets import (QApplication, QVBoxLayout, QWidget)  # noqa: E402

from spyder_claude.mosaique import (Cellule, Mosaique, TAILLE_BOUTON,  # noqa: E402
                                    disposition)


APPLICATION = QApplication.instance() or QApplication(sys.argv)


class TestDisposition(unittest.TestCase):
    """La grille, calculee a part parce qu'elle se verifie sans un seul widget."""

    def test_aucune_session(self):
        self.assertEqual(disposition(0), [])

    def test_une_seule_rangee_pour_deux(self):
        self.assertEqual(disposition(2), [2])

    def test_trois_sessions_la_rangee_pleine_en_haut(self):
        """2 puis 1, jamais 1 puis 2 : une grande case au-dessus d'une petite se lit mal."""
        self.assertEqual(disposition(3), [2, 1])

    def test_quatre_sessions_carre(self):
        self.assertEqual(disposition(4), [2, 2])

    def test_cinq_sessions(self):
        self.assertEqual(disposition(5), [3, 2])

    def test_neuf_sessions_carre(self):
        self.assertEqual(disposition(9), [3, 3, 3])

    def test_toutes_les_cases_sont_placees(self):
        for nombre in range(1, 40):
            self.assertEqual(sum(disposition(nombre)), nombre,
                             "une session perdue pour %d" % nombre)


class BaseMosaique(unittest.TestCase):

    def setUp(self):
        self.hote = QWidget()
        self.mosaique = Mosaique(self.hote)
        self.vues = []

    def tearDown(self):
        self.mosaique.liberer()
        for vue in self.vues:
            vue.setParent(None)
        self.hote.deleteLater()
        APPLICATION.processEvents()

    def nouvelle_vue(self, nom):
        vue = QWidget()
        vue.setObjectName(nom)
        self.vues.append(vue)
        return vue

    def elements(self, combien):
        return [(self.nouvelle_vue("vue%d" % index), "session %d" % index)
                for index in range(combien)]


class TestMontage(BaseMosaique):

    def test_chaque_vue_recoit_une_cellule(self):
        self.mosaique.disposer(self.elements(5))
        self.assertEqual(len(self.mosaique.cellules()), 5)

    def test_le_titre_est_affiche(self):
        elements = self.elements(2)
        self.mosaique.disposer(elements)
        cellule = self.mosaique.cellule_de(elements[1][0])
        self.assertEqual(cellule.titre(), "session 1")

    def test_titre_modifiable_apres_coup(self):
        """C'est ce que fait claude-title.sh : le sujet change en cours de session."""
        elements = self.elements(2)
        self.mosaique.disposer(elements)
        self.mosaique.poser_titre(elements[0][0], "TODO : mosaique")
        self.assertEqual(self.mosaique.cellule_de(elements[0][0]).titre(),
                         "TODO : mosaique")

    def test_bandeau_compact_sous_la_premiere_rangee(self):
        """Sous la premiere rangee, le bandeau n'a plus a loger les boutons de 44 px :
        il ne doit pas separer deux terminaux d'autant de vide. Les terminaux d'une meme
        rangee restent alignes."""
        elements = self.elements(4)   # 2 rangees de 2
        self.mosaique.disposer(elements)
        self.hote.show()
        APPLICATION.processEvents()
        haut = [self.mosaique.cellule_de(vue) for vue, _ in elements[:2]]
        bas = [self.mosaique.cellule_de(vue) for vue, _ in elements[2:]]
        self.assertGreaterEqual(haut[0].vue.y(), TAILLE_BOUTON)
        self.assertLess(bas[0].vue.y(), TAILLE_BOUTON // 2 + 10)
        self.assertEqual(haut[0].vue.y(), haut[1].vue.y())
        self.assertEqual(bas[0].vue.y(), bas[1].vue.y())

    def test_un_titre_long_n_impose_pas_sa_largeur(self):
        """Un titre OSC complet ne doit pas elargir la mosaique : agrandie, elle poussait
        la fenetre hors de l'ecran, et la fenetre y restait apres la reduction."""
        elements = self.elements(1)
        self.mosaique.disposer(elements)
        cellule = self.mosaique.cellule_de(elements[0][0])
        self.hote.show()   # le layout ne se recalcule qu'affiche
        APPLICATION.processEvents()
        avant = cellule.minimumSizeHint().width()
        self.mosaique.poser_titre(elements[0][0], "titre de session tres long " * 20)
        APPLICATION.processEvents()
        self.assertEqual(cellule.minimumSizeHint().width(), avant)

    def test_couleur_posee_sur_le_bandeau(self):
        elements = self.elements(1)
        self.mosaique.disposer(elements)
        self.mosaique.poser_couleur(elements[0][0], "#3a1414", "#DFE1E2")
        feuille = self.mosaique.cellule_de(elements[0][0])._etiquette.styleSheet()
        self.assertIn("#3a1414", feuille)

    def test_redisposer_ne_perd_personne(self):
        """Ouvrir une session alors que la mosaique est deja affichee."""
        elements = self.elements(3)
        self.mosaique.disposer(elements[:2])
        self.mosaique.disposer(elements)
        self.assertEqual(len(self.mosaique.cellules()), 3)
        for vue, _titre in elements:
            self.assertIsNotNone(self.mosaique.cellule_de(vue))


class TestLesVuesSurvivent(BaseMosaique):
    """Le point dur : une vue ne doit JAMAIS etre detruite avec sa cellule."""

    @staticmethod
    def _est_vivant(widget):
        try:
            widget.objectName()
        except RuntimeError:      # objet C++ supprime (PySide6)
            return False
        return True

    def test_liberer_rend_les_vues_intactes(self):
        elements = self.elements(4)
        self.mosaique.disposer(elements)
        rendues = self.mosaique.liberer()
        APPLICATION.processEvents()          # laisse jouer les deleteLater des cellules
        self.assertEqual(len(rendues), 4)
        for vue, _titre in elements:
            self.assertTrue(self._est_vivant(vue), "une session a ete detruite")
            self.assertIsNone(vue.parent())

    def test_aller_et_revenir_dix_fois(self):
        """La bascule est declenchee par l'agrandissement du panneau : elle se repete."""
        elements = self.elements(3)
        for _ in range(10):
            self.mosaique.disposer(elements)
            self.mosaique.liberer()
            APPLICATION.processEvents()
        for vue, _titre in elements:
            self.assertTrue(self._est_vivant(vue))

    def test_cellule_liberee_rend_sa_vue(self):
        vue = self.nouvelle_vue("seule")
        cellule = Cellule(vue, "titre", self.hote)
        self.assertIs(cellule.liberer(), vue)
        cellule.deleteLater()
        APPLICATION.processEvents()
        self.assertTrue(self._est_vivant(vue))


class TestAffichage(unittest.TestCase):
    """La mosaique DESSINE-T-ELLE quelque chose ? Aucun test ci-dessus ne le demandait.

    CE TROU A COUTE UN ALLER-RETOUR COMPLET (27/07/2026). Les tests de montage passaient,
    le panneau repondait `en_mosaique() is True`, aucune session n'etait perdue au
    retour — et la capture du vrai Spyder ne montrait qu'un aplat de fond. La mesure des
    geometries a designe le maillon : la `Mosaique` occupait bien ses 677x331, mais le
    QSplitter racine etait `isVisible() == False` et mesurait 100x30, la taille d'un
    widget jamais mis en page.

    Pourquoi les autres tests ne pouvaient pas le voir : leur hote n'est jamais affiche.
    Tout y est invisible, donc la visibilite n'y veut rien dire. Il faut un hote MONTRE,
    et le montage doit copier celui de Spyder — disposition imbriquee, voisin cache, vue
    arrivant cachee de son onglet.

    ⚠ CE QUE CES TESTS N'ATTRAPENT PAS, ET IL FAUT LE SAVOIR AVANT DE S'Y FIER : ils ne
    reproduisent PAS le defaut du 27/07/2026. Joues avant le correctif, montage fidele
    compris, ils passaient tous — offscreen, Qt montre le splitter racine de lui-meme.
    Ils sont donc verts pour une raison qui n'a rien a voir avec le correctif, et un
    retour en arriere sur `racine.show()` ne les ferait pas rougir.

    Ce qu'ils attrapent VRAIMENT, verifie en le retirant : le `vue.show()` de `Cellule`.
    Sans lui, deux d'entre eux echouent — une vue arrive de son onglet explicitement
    cachee, et rien d'autre ne la remontre.

    Le garde-fou du racine, lui, est dans HGIGNORED/scenario_plugin_claude.json : une
    action y releve les geometries reelles dans un vrai Spyder, seul endroit ou le defaut
    existe. Regle du depot : un defaut d'affichage se mesure en COORDONNEES, et un test
    qui ne rougit pas sans le correctif ne prouve rien.
    """

    #: Taille par defaut d'un QWidget jamais mis en page. Une cellule qui la porte n'a
    #: pas ete disposee, quoi qu'en dise le reste.
    TAILLE_ORPHELINE = (100, 30)

    def setUp(self):
        self.hote = QWidget()
        self.hote.resize(800, 400)

        # ⚠ LE MONTAGE EST COPIE SUR CELUI DE SPYDER, ET CHAQUE DETAIL COMPTE.
        # `PluginMainWidget.setLayout` n'installe pas la disposition qu'on lui donne :
        # il fait `_main_layout.addLayout(...)`. Celle ou vit la mosaique est donc une
        # disposition IMBRIQUEE, et non celle du widget. Un test monte sur un layout
        # direct ne reproduit pas le meme calcul de taille.
        principale = QVBoxLayout(self.hote)
        principale.setContentsMargins(0, 0, 0, 0)
        self.disposition = QVBoxLayout()
        self.disposition.setContentsMargins(0, 0, 0, 0)
        principale.addLayout(self.disposition)

        # Le voisin que la mosaique remplace : le panneau cache ses onglets et montre la
        # mosaique. Sans lui, la disposition n'a qu'un seul enfant et se comporte
        # autrement.
        self.onglets = QWidget()
        self.disposition.addWidget(self.onglets)

        self.mosaique = Mosaique(self.hote)
        self.mosaique.hide()
        self.disposition.addWidget(self.mosaique)

        self.vues = []
        self.hote.show()
        APPLICATION.processEvents()

    def tearDown(self):
        self.mosaique.liberer()
        for vue in self.vues:
            vue.setParent(None)
        self.hote.hide()
        self.hote.deleteLater()
        APPLICATION.processEvents()

    def elements(self, combien):
        elements = []
        for index in range(combien):
            vue = QWidget()
            vue.setObjectName("vue%d" % index)
            # Une vue arrive d'un QTabWidget, qui l'a explicitement cachee en la
            # retirant : c'est l'etat de depart reel, et il compte.
            vue.hide()
            self.vues.append(vue)
            elements.append((vue, "session %d" % index))
        return elements

    def basculer(self, combien):
        """Reproduit `PanneauClaude._passer_en_mosaique`, dans son ordre exact."""
        elements = self.elements(combien)
        self.onglets.hide()
        self.mosaique.show()
        self.mosaique.disposer(elements)
        APPLICATION.processEvents()
        return elements

    def test_le_splitter_racine_est_visible(self):
        """LE test qui echoue sans le correctif : le maillon designe par la mesure."""
        self.basculer(2)
        racine = self.mosaique._racine
        self.assertIsNotNone(racine, "aucune racine construite")
        self.assertTrue(racine.isVisible(),
                        "le QSplitter racine n'est pas affiche : la mosaique reste un "
                        "aplat de fond, quoi que disent les compteurs de cellules")

    def test_les_cellules_sont_visibles_et_dimensionnees(self):
        self.basculer(2)
        for cellule in self.mosaique.cellules():
            self.assertTrue(cellule.isVisible(), "une cellule n'est pas affichee")
            self.assertNotEqual((cellule.width(), cellule.height()),
                                self.TAILLE_ORPHELINE,
                                "cellule jamais mise en page (taille par defaut)")

    def test_les_vues_sont_visibles(self):
        """Une vue arrive CACHEE de son onglet : la remontrer est indispensable."""
        elements = self.basculer(2)
        for vue, _titre in elements:
            self.assertTrue(vue.isVisible(),
                            "la session est dans une cellule mais reste invisible")

    def test_les_cellules_se_partagent_la_largeur(self):
        """Deux sessions cote a cote : chacune occupe une part reelle de l'hote.

        Ce test dit ce que « visible » ne dit pas — qu'on voit DEUX terminaux, et non
        l'un ecrase a quelques pixels.
        """
        self.basculer(2)
        largeurs = [cellule.width() for cellule in self.mosaique.cellules()]
        self.assertEqual(len(largeurs), 2)
        for largeur in largeurs:
            self.assertGreater(largeur, 100,
                               "cellule ecrasee : largeurs %s dans un hote de 800"
                               % largeurs)

    def test_redisposer_laisse_tout_visible(self):
        """Ouvrir une session alors que la mosaique est affichee la redispose."""
        self.basculer(2)
        elements = self.elements(3)
        self.mosaique.disposer(elements)
        APPLICATION.processEvents()
        self.assertTrue(self.mosaique._racine.isVisible())
        for vue, _titre in elements:
            self.assertTrue(vue.isVisible(), "vue invisible apres redisposition")

    def test_le_bouton_de_sortie_est_visible(self):
        """SANS LUI, LA MOSAIQUE EST UN CUL-DE-SAC.

        Passer en mosaique cache la barre d'onglets du panneau, donc le bouton
        « Agrandir le volet » qui y vit. Ce bouton-ci est le seul moyen d'en sortir a la
        souris — d'ou un test a lui, et non une ligne noyee dans un autre.
        """
        self.basculer(2)
        bouton = self.mosaique._bouton_reduire
        self.assertTrue(bouton.isVisible(), "aucun moyen de sortir de la mosaique")
        self.assertFalse(bouton.icon().isNull(), "bouton sans icone : invisible a l'oeil")

    def test_le_bouton_de_sortie_emet_la_demande(self):
        """Le clic ne replie rien lui-meme : il DEMANDE, et le panneau decide."""
        self.basculer(2)
        recu = []
        self.mosaique.sig_reduire_demande.connect(lambda: recu.append(True))
        self.mosaique._bouton_reduire.click()
        APPLICATION.processEvents()
        self.assertEqual(len(recu), 1, "le bouton n'a pas emis sig_reduire_demande")
        # Et il n'a rien defait de lui-meme : le panneau reste maitre de l'affichage.
        self.assertIsNotNone(self.mosaique._racine,
                             "la mosaique s'est repliee toute seule")

    def test_le_bouton_ne_coute_aucune_hauteur(self):
        """Le bouton de sortie ne doit RIEN couter : zero pixel, pas « peu ».

        Quatre versions ont ete mesurees le 27/07/2026, et c'est l'utilisateur qui a
        pousse a chaque fois : bandeau separe a 26 px (3 de marge + 23 de bouton pour une
        icone de 16), puis 19 marges et remplissage retires, puis 16 en fixant la taille du
        bouton — et enfin ZERO en le posant sur la ligne des titres, qui existe deja.
        « Le bouton de reduction ne peut pas etre sur la meme ligne que les titres de la
        premiere ligne de mosaique ? »

        Le critere est donc en COORDONNEES et sans tolerance : la premiere cellule commence
        au premier pixel de la mosaique. Tout autre resultat veut dire qu'un bandeau est
        revenu.
        """
        self.basculer(2)
        cellule = self.mosaique.cellules()[0]
        haut_mosaique = self.mosaique.mapToGlobal(
            self.mosaique.rect().topLeft()).y()
        haut_cellule = cellule.mapToGlobal(cellule.rect().topLeft()).y()
        self.assertEqual(
            haut_cellule, haut_mosaique,
            "%d px perdus au-dessus de la premiere cellule"
            % (haut_cellule - haut_mosaique))

    def test_les_cellules_ont_la_meme_largeur(self):
        """« La largeur des elements de la mosaique a l'air d'avoir une largeur random. »

        C'etait exact, et ce n'etait pas du hasard : un QSplitter repartit selon le
        sizeHint de ses enfants, et celui d'un terminal depend du texte qu'il affiche. Deux
        sessions cote a cote recevaient donc des largeurs differentes, variables d'un
        lancement a l'autre.

        Tolerance d'1 px : une largeur impaire ne se divise pas en deux parts egales.
        """
        self.basculer(2)
        largeurs = [c.width() for c in self.mosaique.cellules()]
        self.assertEqual(len(largeurs), 2)
        self.assertLessEqual(abs(largeurs[0] - largeurs[1]), 1,
                             "largeurs inegales : %s" % largeurs)

    def test_une_seule_session_est_une_mosaique_comme_une_autre(self):
        """L'affichage doit etre le MEME a une session qu'a deux.

        « Lorsqu'il n'y a qu'une seule session, elle apparait sous forme d'onglet dans la
        mosaique, ce n'est pas ce que je veux » (utilisateur, 27/07/2026). La cellule
        unique doit donc porter son titre et les trois boutons, exactement comme la
        derniere cellule du haut quand il y en a plusieurs.
        """
        self.basculer(1)
        cellules = self.mosaique.cellules()
        self.assertEqual(len(cellules), 1)
        self.assertTrue(cellules[0]._bouton_fermer.isVisible(), "pas de croix")
        self.assertIs(self.mosaique._bouton_nouveau.parentWidget(), cellules[0],
                      "le « + » n'est pas sur l'unique cellule")
        self.assertIs(self.mosaique._bouton_reduire.parentWidget(), cellules[0],
                      "la reduction n'est pas sur l'unique cellule")

    def test_les_terminaux_commencent_tous_a_la_meme_hauteur(self):
        """Les boutons ne sont poses que sur UNE cellule — les autres doivent suivre.

        Sans hauteur de ligne imposee a toutes, seule la cellule qui accueille les boutons
        voit sa ligne de titre grandir, et son terminal commence plus bas que celui de ses
        voisines : 27 px d'ecart avec des boutons de 44 (mesure du 27/07/2026). Un
        desalignement se voit bien plus qu'une ligne un peu haute, d'ou l'invariant.
        PAR RANGEE depuis le 10/10/2026 : les rangees du dessous ont un bandeau compact
        (cf. Cellule, `compacte`), et c'est entre voisines que l'ecart se voit.
        """
        self.basculer(4)
        departs = {}
        for cellule in self.mosaique.cellules():
            haut_cellule = cellule.mapToGlobal(cellule.rect().topLeft()).y()
            haut_vue = cellule.vue.mapToGlobal(cellule.vue.rect().topLeft()).y()
            departs.setdefault(id(cellule.parentWidget()), set()).add(
                haut_vue - haut_cellule)
        self.assertEqual(len(departs), 2)
        for rangee in departs.values():
            self.assertEqual(len(rangee), 1,
                             "les terminaux d'une rangee ne commencent pas au meme "
                             "endroit : %s" % rangee)

    def test_les_rangees_ont_la_meme_hauteur(self):
        """Meme chose verticalement, des qu'il y a plus d'une rangee."""
        self.basculer(4)          # 2 rangees de 2
        racine = self.mosaique._racine
        hauteurs = [racine.widget(i).height() for i in range(racine.count())]
        self.assertEqual(len(hauteurs), 2)
        self.assertLessEqual(abs(hauteurs[0] - hauteurs[1]), 1,
                             "hauteurs de rangees inegales : %s" % hauteurs)

    def test_le_bouton_est_sur_la_ligne_des_titres(self):
        """Et il est dans la DERNIERE cellule du HAUT : en haut a droite."""
        self.basculer(2)
        cellules = self.mosaique.cellules()
        bouton = self.mosaique._bouton_reduire
        self.assertIs(bouton.parentWidget(), cellules[1],
                      "le bouton n'est pas dans la derniere cellule du haut")
        # MEME LIGNE = leurs bandes verticales se CHEVAUCHENT. Comparer les centres au
        # pixel pres etait trop strict : 12 contre 13 au premier essai, simple arrondi
        # entre deux hauteurs de parites differentes. Le test etait faux, pas l'alignement.
        titre = cellules[1]._etiquette
        haut_b = bouton.mapToGlobal(bouton.rect().topLeft()).y()
        haut_t = titre.mapToGlobal(titre.rect().topLeft()).y()
        self.assertLess(haut_b, haut_t + titre.height(),
                        "le bouton commence sous le titre")
        self.assertLess(haut_t, haut_b + bouton.height(),
                        "le titre commence sous le bouton")

    def test_le_bouton_plus_est_la_et_demande_une_session(self):
        """En mosaique, la barre d'onglets est cachee — donc le « + » qui y vit aussi.

        Sans celui-ci, on ne pouvait plus ouvrir d'instance sans revenir d'abord aux
        onglets. Il ne fait qu'EMETTRE : c'est le panneau qui sait ouvrir une session.
        """
        self.basculer(2)
        bouton = self.mosaique._bouton_nouveau
        self.assertTrue(bouton.isVisible(), "pas de « + » en mosaique")
        self.assertFalse(bouton.icon().isNull(), "« + » sans icone : invisible a l'oeil")
        recu = []
        self.mosaique.sig_nouvelle_demande.connect(lambda: recu.append(True))
        bouton.click()
        APPLICATION.processEvents()
        self.assertEqual(len(recu), 1, "le « + » n'a pas emis sig_nouvelle_demande")

    def test_le_plus_est_a_gauche_du_bouton_de_reduction(self):
        """Meme ordre que dans le coin de la barre d'onglets : « + » puis reduction.

        Un meme geste doit se chercher au meme endroit, qu'on soit en onglets ou en
        mosaique.
        """
        self.basculer(2)
        plus = self.mosaique._bouton_nouveau
        reduire = self.mosaique._bouton_reduire
        self.assertLess(plus.mapToGlobal(plus.rect().topLeft()).x(),
                        reduire.mapToGlobal(reduire.rect().topLeft()).x(),
                        "le « + » n'est pas a gauche du bouton de reduction")

    def test_le_bloc_titre_croix_compteur_est_soude(self):
        """En mosaique il n'y a plus d'onglet, donc plus la croix que l'onglet portait.

        Elle va JUSTE A DROITE DU TITRE (consigne du 27/07/2026, apres un premier essai
        « tout a droite » que l'utilisateur a corrige) : le titre et sa croix formaient un
        bloc a gauche, et les boutons du panneau — « + », reduction — restaient a
        l'extreme droite.

        Le tachymetre s'est d'abord intercale entre les deux (31/07/2026), puis est passe
        APRES la croix (04/10/2026 : « la croix [...] a cote du titre, avant le
        tachymetre »). Le bloc reste soude, en trois pieces : titre -> croix -> compteur,
        chacune collee a la suivante, et les boutons du panneau restent apres le compteur.
        """
        self.basculer(2)
        for cellule in self.mosaique.cellules():
            titre = cellule._etiquette
            compteur = cellule._compteur
            croix = cellule._bouton_fermer
            self.assertTrue(croix.isVisible(), "cellule sans croix de fermeture")
            fin_du_titre = (titre.mapToGlobal(titre.rect().topLeft()).x()
                            + titre.width())
            debut_croix = croix.mapToGlobal(croix.rect().topLeft()).x()
            fin_de_la_croix = debut_croix + croix.width()
            debut_compteur = compteur.mapToGlobal(compteur.rect().topLeft()).x()
            self.assertGreaterEqual(debut_croix, fin_du_titre,
                                    "la croix chevauche le titre")
            self.assertLessEqual(
                debut_croix - fin_du_titre, cellule.MARGE + 1,
                "la croix est loin du titre (%d px)" % (debut_croix - fin_du_titre))
            self.assertGreaterEqual(debut_compteur, fin_de_la_croix,
                                    "le compteur chevauche la croix")
            self.assertLessEqual(
                debut_compteur - fin_de_la_croix, cellule.MARGE + 1,
                "le compteur est loin de la croix (%d px)"
                % (debut_compteur - fin_de_la_croix))
            for autre in (self.mosaique._bouton_nouveau,
                          self.mosaique._bouton_reduire):
                if autre.parentWidget() is cellule:
                    self.assertGreater(
                        autre.mapToGlobal(autre.rect().topLeft()).x(), debut_compteur,
                        "un bouton du panneau est passe devant le compteur")

    def test_l_icone_des_croix_survit_aux_redispositions(self):
        """LE piege de cette icone-ci : les croix appartiennent aux CELLULES.

        Les cellules sont detruites et refabriquees a chaque ouverture ou fermeture de
        session. Une icone posee une seule fois disparaitrait donc a la premiere
        redisposition, et les croix reviendraient a celle de Qt sans que rien ne le signale
        — c'est pourquoi la mosaique la MEMORISE au lieu de la transmettre une fois.
        """
        from qtpy.QtGui import QIcon, QPixmap
        pastille = QPixmap(16, 16)
        pastille.fill()
        icone = QIcon(pastille)
        self.basculer(2)
        self.mosaique.poser_icone_fermer(icone)
        for cellule in self.mosaique.cellules():
            self.assertEqual(cellule._bouton_fermer.icon().cacheKey(),
                             icone.cacheKey(), "icone pas posee sur une cellule")
        # Et sur des cellules NEUVES, creees apres coup.
        self.mosaique.disposer(self.elements(4))
        APPLICATION.processEvents()
        for cellule in self.mosaique.cellules():
            self.assertEqual(cellule._bouton_fermer.icon().cacheKey(),
                             icone.cacheKey(),
                             "l'icone n'a pas suivi sur une cellule neuve")

    def test_poser_vitesse_vise_la_bonne_cellule(self):
        self.basculer(3)
        cellules = self.mosaique.cellules()
        vue_ciblee = cellules[1].vue
        self.mosaique.poser_vitesse(vue_ciblee, 250)
        self.assertEqual(cellules[1]._compteur._valeur, 250)
        for autre in (cellules[0], cellules[2]):
            self.assertIsNone(autre._compteur._valeur,
                              "une autre cellule a recu la vitesse")

    def test_la_pleine_echelle_survit_aux_redispositions(self):
        """MEME piege que l'icone des croix : les cellules — donc leurs compteurs — sont
        detruites et refabriquees a chaque redisposition. Une echelle posee une seule
        fois disparaitrait a la premiere ouverture de session."""
        self.basculer(2)
        self.mosaique.poser_pleine_echelle(9.0)
        for cellule in self.mosaique.cellules():
            self.assertEqual(cellule._compteur._pleine_echelle, 900.0)
        self.mosaique.disposer(self.elements(4))
        APPLICATION.processEvents()
        for cellule in self.mosaique.cellules():
            self.assertEqual(cellule._compteur._pleine_echelle, 900.0,
                             "l'echelle n'a pas suivi sur une cellule neuve")

    def test_la_croix_prend_la_taille_de_celle_d_un_onglet(self):
        """La TAILLE se cale, la position non : le titre doit pouvoir pousser la croix.

        « Je veux que le titre puisse pousser la croix » (utilisateur, 27/07/2026), apres
        un premier essai a position fixe qui obligeait a figer la largeur du titre, donc a
        le tronquer.
        """
        self.basculer(2)
        self.mosaique.poser_geometrie_croix(18, 22)
        APPLICATION.processEvents()
        for cellule in self.mosaique.cellules():
            croix = cellule._bouton_fermer
            self.assertEqual((croix.width(), croix.height()), (18, 22))
            # Et elle SUIT le compteur : elle commence juste apres lui (le compteur,
            # lui, suit le titre — cf. test_le_bloc_titre_compteur_croix_est_soude).
            compteur = cellule._compteur
            fin_compteur = (compteur.mapToGlobal(compteur.rect().topLeft()).x()
                           + compteur.width())
            debut_croix = croix.mapToGlobal(croix.rect().topLeft()).x()
            self.assertLessEqual(debut_croix - fin_compteur, cellule.MARGE + 1,
                                 "la croix s'est detachee du compteur")

    def test_un_titre_long_pousse_la_croix(self):
        """LE point de la demande : la croix suit le texte, elle ne le borne pas."""
        self.basculer(2)
        self.mosaique.poser_geometrie_croix(18, 22)
        cellule = self.mosaique.cellules()[0]
        APPLICATION.processEvents()
        avant = cellule._bouton_fermer.mapToGlobal(
            cellule._bouton_fermer.rect().topLeft()).x()
        cellule.poser_titre("un titre nettement plus long que le precedent")
        APPLICATION.processEvents()
        apres = cellule._bouton_fermer.mapToGlobal(
            cellule._bouton_fermer.rect().topLeft()).x()
        self.assertGreater(apres, avant,
                           "la croix n'a pas suivi l'allongement du titre")

    def test_le_calage_de_la_croix_survit_aux_redispositions(self):
        """Meme piege que l'icone : les cellules sont refabriquees a chaque disposition."""
        self.basculer(2)
        self.mosaique.poser_geometrie_croix(18, 22)
        self.mosaique.disposer(self.elements(3))
        APPLICATION.processEvents()
        for cellule in self.mosaique.cellules():
            self.assertEqual(
                (cellule._bouton_fermer.width(), cellule._bouton_fermer.height()),
                (18, 22), "le calage n'a pas suivi sur une cellule neuve")

    def test_la_croix_nomme_la_session_a_fermer(self):
        """La cellule signale, la mosaique dit LAQUELLE : c'est elle qui tient le lien."""
        elements = self.basculer(3)
        recu = []
        self.mosaique.sig_fermeture_demandee.connect(lambda v: recu.append(v))
        cellule = self.mosaique.cellule_de(elements[1][0])
        cellule._bouton_fermer.click()
        APPLICATION.processEvents()
        self.assertEqual(recu, [elements[1][0]],
                         "ce n'est pas la vue de cette cellule qui a ete designee")

    def test_la_croix_ne_ferme_rien_elle_meme(self):
        """Elle DEMANDE. Arreter une session est l'affaire du panneau, qui sait ce qu'est
        un pty — une cellule qui detruirait sa vue tuerait l'instance sans prevenir."""
        elements = self.basculer(2)
        self.mosaique.cellule_de(elements[0][0])._bouton_fermer.click()
        APPLICATION.processEvents()
        self.assertEqual(len(self.mosaique.cellules()), 2,
                         "la mosaique s'est defaite toute seule")
        self.assertIsNotNone(elements[0][0].objectName(), "la vue a ete detruite")

    def test_le_bouton_survit_a_liberer_appelee_seule(self):
        """LE piege de ce montage, et le seul cas ou il mord vraiment.

        Qt detruit les enfants avec leur parent, et le bouton vit dans une cellule. Mais
        une REDISPOSITION ne le perd pas, meme sans precaution : `disposer` appelle
        `liberer` puis le repose aussitot dans une cellule neuve, ce qui le reparente avant
        que le `deleteLater` differe ne s'execute. Verifie en retirant la reprise : le test
        restait vert. Il ne prouvait donc rien.

        Le cas qui mord est `liberer()` appelee SEULE — ce que fait le panneau en revenant
        aux onglets (`_revenir_aux_onglets`). Rien ne reparente le bouton derriere, et il
        part avec sa cellule. Sous PySide6, y toucher ensuite leve RuntimeError, ce qui
        rend la disparition impossible a manquer.
        """
        self.basculer(2)
        bouton = self.mosaique._bouton_reduire
        self.mosaique.liberer()
        # ⚠ processEvents() NE SUFFIT PAS : il ne delivre pas les DeferredDelete, donc les
        # cellules restaient vivantes et le test passait meme sans la reprise — il ne
        # prouvait rien. Il faut poster explicitement ces evenements-la pour que la
        # destruction ait lieu pendant le test.
        APPLICATION.sendPostedEvents(None, QEvent.DeferredDelete)
        APPLICATION.processEvents()
        try:
            bouton.isVisible()
        except RuntimeError:
            self.fail("le bouton de sortie a ete detruit avec sa cellule")
        self.assertIsNot(bouton.parentWidget(), None,
                         "bouton orphelin : il flotterait hors de tout layout")

    def test_le_bouton_survit_aux_redispositions(self):
        """Et il reste utilisable apres plusieurs changements de nombre de sessions."""
        self.basculer(2)
        bouton = self.mosaique._bouton_reduire
        for combien in (3, 4, 2, 5):
            self.mosaique.disposer(self.elements(combien))
            APPLICATION.processEvents()
            self.assertTrue(bouton.isVisible(), "bouton perdu apres redisposition")
            self.assertFalse(bouton.icon().isNull(), "bouton vide apres redisposition")

    def test_le_bouton_de_sortie_survit_a_une_redisposition(self):
        """`disposer` refait la mosaique a chaque ouverture ou fermeture de session.

        Le bandeau ne doit pas partir avec elle : il est monte une fois pour toutes dans
        le constructeur, et `liberer` ne touche qu'au splitter.
        """
        self.basculer(2)
        self.mosaique.disposer(self.elements(4))
        APPLICATION.processEvents()
        self.assertTrue(self.mosaique._bouton_reduire.isVisible())


class TestTachymetreDeCellule(unittest.TestCase):

    def test_le_cadran_tombe_sur_le_titre(self):
        """Signale par l'utilisateur, 04/10/2026 : le tachymetre « n'est pas du tout aligne
        avec le titre des fenetres dans la mosaique ». Le titre est descendu par
        `RETRAIT_TEXTE_*` (feuille de style posee par `poser_couleur`), le cadran etait
        centre sur la ligne : 5 px trop haut. Mesure sur l'ENCRE, comme l'oeil."""
        cellule = Cellule(QWidget(), "Essai Claude titre")
        cellule.resize(400, 200)
        cellule.poser_couleur(None)
        cellule.show()
        cellule.poser_vitesse(2500)
        QApplication.processEvents()
        image = cellule.grab().toImage()
        titre = cellule._etiquette.geometry()
        cadran = cellule._compteur.geometry()

        def encre(x0, x1):
            fond = image.pixelColor(x0, 0).lightness()
            lignes = [y for y in range(0, titre.bottom())
                      if any(abs(image.pixelColor(x, y).lightness() - fond) > 40
                             for x in range(x0, x1))]
            return (min(lignes) + max(lignes)) / 2.0

        texte = encre(titre.left(), titre.right())
        self.assertAlmostEqual(texte, encre(cadran.left(), cadran.right()), delta=1.5)
        # La croix aussi, et l'ordre [titre][croix][cadran] (demande de l'utilisateur,
        # 04/10/2026 : « la croix [...] a cote du titre, avant le tachymetre »).
        croix = cellule._bouton_fermer.geometry()
        self.assertAlmostEqual(texte, encre(croix.left(), croix.right()), delta=1.5)
        self.assertLess(titre.right(), croix.left())
        self.assertLess(croix.right(), cadran.left())
        cellule.deleteLater()



class TestBandeauColoreDeLaPremiereRangee(unittest.TestCase):

    def test_la_couleur_nentoure_que_le_texte(self):
        """Signale par l'utilisateur, 10/10/2026 : en mosaique, la couleur d'etat du titre
        prenait « trop de hauteur sur les fenetres du haut » — les 44 px de la rangee,
        portes par l'etiquette elle-meme. La couleur doit avoir la hauteur de celle d'une
        rangee compacte, sans deplacer ni le texte (calage sur les onglets) ni le
        terminal."""
        mesures = {}
        for compacte in (False, True):
            vue = QWidget()
            cellule = Cellule(vue, "Essai Claude titre", compacte=compacte)
            cellule.poser_couleur("#3a1414")
            cellule.resize(400, 200)
            cellule.show()
            QApplication.processEvents()
            image = cellule.grab().toImage()
            x = cellule._etiquette.geometry().left() + 2   # dans le remplissage, hors texte
            colore = sum(1 for y in range(image.height())
                         if image.pixelColor(x, y).name() == "#3a1414")
            texte = cellule._etiquette.contentsRect()
            centre = cellule._etiquette.mapTo(cellule, texte.topLeft()).y() \
                + texte.height() / 2.0
            mesures[compacte] = (colore, centre, vue.y())
            cellule.deleteLater()
        haute, compacte = mesures[False], mesures[True]
        self.assertGreater(compacte[0], 0)
        self.assertEqual(haute[0], compacte[0])            # meme hauteur coloree
        self.assertAlmostEqual(haute[1], 27.5, delta=0.5)  # texte cale sur les onglets
        self.assertEqual(haute[2], TAILLE_BOUTON)          # terminal sous ses 44 px

if __name__ == "__main__":
    unittest.main(verbosity=2)

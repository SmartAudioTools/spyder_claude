# -*- coding: utf-8 -*-
"""Le tachymetre greffe sur un onglet, entre son titre et sa croix de fermeture.

CE FICHIER EST COUPLE AU CONTRAT IMPLICITE DE `spyder.widgets.tabs` (Spyder 6.1.5), pas
seulement a une API publique documentee — c'est le SEUL des nouveaux fichiers de ce
travail dans ce cas, d'ou son isolement ici plutot que dans compteurs.py ou mosaique.py.

CE QUE SPYDER FAIT DEJA, ET QUE CE GREFFON NE DOIT PAS CASSER (`TabBar`, tabs.py) :
  - `tabInserted(index)` installe sa PROPRE croix de fermeture (`CloseTabButton`) dans le
    slot `RightSide` de chaque onglet (`LeftSide` seulement sous macOS) ;
  - `_on_tab_changed` et `_on_tab_moved` retrouvent cette croix par
    `self.tabButton(i, self.close_btn_side)` et lui ecrivent `.index`, puis appellent
    `.set_selected_color()` / `.set_not_selected_color()` ;
  - `tabRemoved` fait de meme pour re-numeroter les croix restantes ;
  - `CloseTabButton.enterEvent`/`leaveEvent` appellent `self.parent().tabToolTip(...)` /
    `.setTabToolTip(...)` — sur SON PARENT, donc sur la barre d'onglets tant que rien ne
    la reparente.

CE QUE CE MODULE FAIT : remplace le widget `RightSide` par un petit conteneur
[croix d'origine][place du Compteur] — le cadran lui-meme est pose par-dessus la barre, a
cette place (cf. `CoinDOnglet.__init__`). La croix d'origine est REPARENTEE, pas recreee — sinon la
connexion `sig_clicked -> tabCloseRequested` posee par Spyder a l'insertion serait perdue.
Une fois reparentee, son `.parent()` devient CE conteneur, plus la barre : chaque appel
que Spyder fait sur « la croix » doit donc etre PROXIFIE ici vers la bonne cible — vers la
croix elle-meme pour `.index` et les couleurs, vers la VRAIE barre pour les info-bulles.

⚠ L'ORDRE DE GREFFE EST IMPERATIF, cf. `main_widget._greffer_le_compteur` : `setTabButton`
D'ABORD (Qt masque alors le widget PRECEDEMMENT installe dans ce slot — meme si on l'a
deja reparente ailleurs, Qt garde sa propre reference et le masque quand meme), PUIS
`adopter_la_croix` qui reparente et reaffiche. Dans l'autre ordre, la croix disparaitrait
a l'interieur d'un conteneur pas encore installe.

⚠ DIVERGENCE DELIBEREE D'AVEC LE PANNEAU JUMEAU `spyder_konsole` : lui n'a pas de
tachymetre, et son heuristique de reperage de la croix par GEOMETRIE
(`_relever_la_croix_dun_onglet`, dans main_widget.py) reste donc correcte pour lui. Un
defaut trouve ici n'a PAS a etre porte la-bas.
"""

from qtpy.QtCore import QSize, Qt
from qtpy.QtWidgets import QHBoxLayout, QWidget

from spyder_claude.compteurs import Compteur
from spyder_claude.mosaique import TAILLE_COMPTEUR, dimensionner_compteur


class CoinDOnglet(QWidget):
    """[croix][place du Compteur], installe a la place du widget RightSide d'un onglet.

    Construit SANS croix (cf. `adopter_la_croix`) : voir le commentaire d'ordre de greffe
    ci-dessus, dans le module.
    """

    def __init__(self, barre, croix_prevue):
        super().__init__(barre)
        #: La VRAIE barre d'onglets — cible des appels `tabToolTip`/`setTabToolTip` que
        #: la croix, une fois reparentee ICI, nous adresse a la place (cf.
        #: CloseTabButton.enterEvent/leaveEvent dans spyder/widgets/tabs.py).
        self._barre = barre
        self._croix = None

        #: ⚠ LE CADRAN N'EST PAS DANS CE CONTENEUR, IL EST POSE PAR-DESSUS LA BARRE.
        #: Pour tomber sur le TEXTE de l'onglet (cf. mosaique.dimensionner_compteur), il
        #: est plus haut que la croix ; dans le conteneur, cette hauteur passait a QTabBar,
        #: qui en deduit celle de l'onglet — 47 px au lieu de 40 (banc du 04/10/2026), et
        #: tout l'alignement onglets/mosaique de `Cellule.RETRAIT_TEXTE_*` avec. Le
        #: conteneur ne fait donc que lui RESERVER sa largeur ; `_suivre` le place, et
        #: `destroyed` l'emporte avec l'onglet.
        self._compteur = Compteur(barre)
        dimensionner_compteur(self._compteur)
        self.destroyed.connect(self._compteur.deleteLater)
        #: ⚠ LA PLACE DE LA CROIX SE RESERVE AVANT D'ELLE. QTabBar dimensionne le bouton
        #: d'apres son `sizeHint()` lu UNE fois, au `setTabButton` — donc avant
        #: `adopter_la_croix`. Sans cette reserve le coin restait large du seul cadran, et
        #: la croix venait le recouvrir (banc du 04/10/2026 : compteur x 162-180, croix
        #: x 172-180). `size()` et non `sizeHint()` : `CloseTabButton` se donne sa taille
        #: par `resize` (SIZE+2 x SIZE+6) ; son sizeHint de QToolButton (41x34 au banc)
        #: faisait grandir l'onglet.
        self._taille_croix = croix_prevue.size()

        self._disposition = QHBoxLayout(self)
        self._disposition.setContentsMargins(0, 0, 0, 0)
        self._disposition.setSpacing(2)
        self._disposition.addSpacing(TAILLE_COMPTEUR)

    def adopter_la_croix(self, croix):
        """Reparente la croix D'ORIGINE dans ce conteneur, et la reaffiche.

        A APPELER APRES que ce conteneur a ete pose par `setTabButton` — jamais avant,
        cf. le commentaire d'ordre en tete de module.
        """
        self._croix = croix
        croix.setFixedSize(self._taille_croix)  # sinon le layout l'etire a son sizeHint
        # EN TETE, avant la place du cadran : la croix colle au titre (demande de
        # l'utilisateur, 04/10/2026 : « a cote du titre, avant le tachymetre »).
        self._disposition.insertWidget(0, croix, 0, Qt.AlignVCenter)
        croix.show()

    def sizeHint(self):  # noqa: N802 - API Qt
        return QSize(TAILLE_COMPTEUR + self._disposition.spacing() + self._taille_croix.width(),
                     self._taille_croix.height())

    def _suivre(self):
        """Pose le cadran sur la place reservee, a la hauteur de celui de la mosaique.

        Centre sur le conteneur, PLUS 1 px : mesure au banc (04/10/2026), le texte d'un
        onglet et celui d'une cellule tombent a la meme ordonnee (y 19-32 dans les deux),
        et c'est avec ce pixel que les deux cadrans aussi (y 18-32). Le cadran de la
        cellule etant cale par construction, c'est lui la reference.
        """
        g = self.geometry()
        x = g.x() + self._taille_croix.width() + self._disposition.spacing()
        self._compteur.move(x, g.y() + (g.height() - self._compteur.height()) // 2 + 1)
        self._compteur.setVisible(self.isVisible())
        self._compteur.raise_()

    def moveEvent(self, event):  # noqa: N802 - API Qt
        super().moveEvent(event)
        self._suivre()

    def resizeEvent(self, event):  # noqa: N802 - API Qt
        super().resizeEvent(event)
        self._suivre()

    def showEvent(self, event):  # noqa: N802 - API Qt
        super().showEvent(event)
        self._suivre()

    def hideEvent(self, event):  # noqa: N802 - API Qt
        super().hideEvent(event)
        self._compteur.hide()

    def croix(self):
        """La croix de fermeture d'origine. Utile a `_relever_la_croix_dun_onglet`."""
        return self._croix

    def poser_vitesse(self, valeur):
        """`valeur` en centimes/heure, ou None si non mesurable. Delegue au cadran."""
        self._compteur.poser_valeur(valeur)

    def poser_pleine_echelle(self, dollars_par_heure):
        self._compteur.poser_pleine_echelle(dollars_par_heure)

    # ------------------------------------------------------------------------------
    # PROXY VERS LA CROIX D'ORIGINE : Spyder s'adresse a NOUS exactement comme il
    # s'adressait a elle, puisque c'est NOUS qu'il trouve desormais dans le slot
    # RightSide (cf. TabBar._on_tab_changed / _on_tab_moved / tabRemoved, tabs.py).
    # ------------------------------------------------------------------------------

    @property
    def index(self):
        return self._croix.index if self._croix is not None else -1

    @index.setter
    def index(self, valeur):
        # `_on_tab_changed`/`_on_tab_moved`/`tabRemoved` ecrivent CET attribut sur ce
        # qu'ils recuperent par `tabButton()` — donc sur NOUS. Sans ce relais vers la
        # croix, c'est ELLE qui resterait numerotee a l'ancien index, et un clic
        # fermerait le mauvais onglet apres un glisser-deposer (cf.
        # tests/test_panneau.py::test_la_croix_ferme_le_bon_onglet_apres_un_deplacement).
        if self._croix is not None:
            self._croix.index = valeur

    def set_selected_color(self):
        if self._croix is not None:
            self._croix.set_selected_color()

    def set_not_selected_color(self):
        if self._croix is not None:
            self._croix.set_not_selected_color()

    def tabToolTip(self, index):  # noqa: N802 - API attendue par CloseTabButton
        return self._barre.tabToolTip(index)

    def setTabToolTip(self, index, texte):  # noqa: N802 - idem
        self._barre.setTabToolTip(index, texte)

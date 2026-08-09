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
[Compteur][croix d'origine]. La croix d'origine est REPARENTEE, pas recreee — sinon la
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

from qtpy.QtCore import Qt
from qtpy.QtWidgets import QHBoxLayout, QWidget

from spyder_claude.compteurs import Compteur
from spyder_claude.mosaique import TAILLE_COMPTEUR


class CoinDOnglet(QWidget):
    """[Compteur][croix], installe a la place du widget RightSide d'un onglet.

    Construit SANS croix (cf. `adopter_la_croix`) : voir le commentaire d'ordre de greffe
    ci-dessus, dans le module.
    """

    def __init__(self, barre):
        super().__init__(barre)
        #: La VRAIE barre d'onglets — cible des appels `tabToolTip`/`setTabToolTip` que
        #: la croix, une fois reparentee ICI, nous adresse a la place (cf.
        #: CloseTabButton.enterEvent/leaveEvent dans spyder/widgets/tabs.py).
        self._barre = barre
        self._croix = None

        self._compteur = Compteur(self)
        self._compteur.setFixedSize(TAILLE_COMPTEUR, TAILLE_COMPTEUR)

        self._disposition = QHBoxLayout(self)
        self._disposition.setContentsMargins(0, 0, 0, 0)
        self._disposition.setSpacing(2)
        self._disposition.addWidget(self._compteur, 0, Qt.AlignVCenter)

    def adopter_la_croix(self, croix):
        """Reparente la croix D'ORIGINE dans ce conteneur, et la reaffiche.

        A APPELER APRES que ce conteneur a ete pose par `setTabButton` — jamais avant,
        cf. le commentaire d'ordre en tete de module.
        """
        self._croix = croix
        self._disposition.addWidget(croix, 0, Qt.AlignVCenter)
        croix.show()

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

# -*- coding: utf-8 -*-
"""La mosaique : toutes les sessions cote a cote quand le panneau est agrandi.

DEMANDE D'ORIGINE (TODO - Spyder - plugin Claude.txt) : « il faudrait qu'en mode agrandi
le panneau, separer les onglets en une mosaique de fenetres ». C'est la reponse au meme
besoin que la mosaique de fenetres Konsole : voir d'un coup d'oeil laquelle des instances
attend une reponse. En onglets, l'etat des sessions cachees ne se lit que sur la couleur
de leur onglet ; agrandi, le panneau a la place de les montrer toutes.

DEUX REGLES, ET ELLES EXPLIQUENT TOUTE LA FORME DU CODE.

  1. LES VUES NE SONT NI RECREEES NI DUPLIQUEES, elles sont REPARENTEES. Une session de
     terminal porte un pty et un processus : la detruire pour la reconstruire tuerait
     l'instance Claude qui tourne dedans. Passer des onglets a la mosaique et revenir ne
     doit donc RIEN faire d'autre que changer de parent.

  2. UNE CELLULE NE POSSEDE PAS SA VUE. Qt detruit les enfants avec leur parent : si l'on
     supprimait une cellule sans en avoir d'abord retire la vue, on tuerait la session
     avec. `liberer()` existe pour cela, et c'est la seule facon correcte de defaire une
     mosaique.

Des QSplitter imbriques plutot qu'un QGridLayout : l'utilisateur peut alors redimensionner
les cellules a la souris, ce qu'une mosaique de vraies fenetres permet aussi. Un
QGridLayout donnerait des cases figees.

Aucun import Spyder : le module se deroule dans un test offscreen ordinaire.
"""

import math

from qtpy.QtCore import QPointF, QRectF, Qt, Signal
from qtpy.QtGui import QColor, QPainter, QPainterPath, QPen
from qtpy.QtWidgets import (QFrame, QHBoxLayout, QLabel, QSizePolicy, QSpacerItem,
                            QSplitter, QStyle, QToolButton, QVBoxLayout, QWidget)

from spyder_konsole.konsole_view import eclaircir

from spyder_claude.compteurs import Compteur


#: Cote des boutons d'action de la mosaique, en pixels logiques. 44 est la taille des
#: boutons du coin de la barre d'onglets — demande de l'utilisateur du 27/07/2026, « passe
#: les boutons de la mosaique a 44 x 44 », pour que les deux modes se ressemblent.
#:
#: ⚠ CETTE VALEUR DIMENSIONNE AUSSI LA LIGNE DE TITRE DE CHAQUE CELLULE, y compris celles
#: qui ne portent aucun bouton. Sans cela, seule la cellule qui les accueille verrait sa
#: ligne grandir, et son terminal commencerait 27 px plus bas que celui des autres — mesure
#: du 27/07/2026. Un desalignement se voit bien plus qu'une ligne un peu haute.
TAILLE_BOUTON = 44

#: Cote du tachymetre par conversation, en pixels logiques. Nettement plus petit que
#: TAILLE_BOUTON : c'est un cadran dans la ligne de titre, pas un bouton — et rester en
#: dessous de la hauteur de la croix (cf. poser_geometrie_croix) garantit qu'il ne
#: dimensionne jamais la ligne a la place de TAILLE_BOUTON.
#: Ramene de 18 a 14 le 11/10/2026 : « le tachymetre doit etre plus petit ».
TAILLE_COMPTEUR = 14

#: Retrait entre la croix et le bord droit de l'onglet d'une cellule. D'abord pose apres le
#: cadran (11/10/2026 : « il faut prevoir une petite marge a droite du tachymetre », il
#: touchait le contour) ; la croix a pris sa place au bord le meme jour.
MARGE_DROITE_ONGLET = 5

#: Espace entre le cadran et la croix, en mosaique comme en onglets (onglet_compteur.py).
ESPACE_COMPTEUR_CROIX = 2

#: Double de l'ecart entre le texte d'un onglet de Spyder et son centre : cf.
#: `dimensionner_compteur`.
DESCENTE_CADRAN_ONGLET = 10


def dimensionner_compteur(compteur, aligne_sur_onglet=True):
    """Donne au tachymetre sa taille, cadran CENTRE SUR LE TEXTE du titre et non sur la ligne.

    Le titre ne tombe pas au milieu de sa ligne : en onglets, la feuille de style de Spyder
    le dessine 5 px sous le centre de l'onglet (banc du 04/10/2026 : texte y 18-31 dans un
    onglet de 40, cadran centre y 11-28). Signale par l'utilisateur, 04/10/2026 : « le
    tachymetre n'est pas du tout aligne avec le titre ». Une marge haute du double de
    l'ecart, dans un widget d'autant plus haut, garde ce widget centre sur la ligne (ou les
    layouts le posent) et descend le cadran de l'ecart, `Compteur.paintEvent` dessinant
    dans `contentsRect()`.

    `aligne_sur_onglet` a False : onglet de cellule de la mosaique, ou titre et cadran sont
    tous deux centres sur la meme rangee (cf. `Cellule._onglet`) — sans descente.
    """
    descente = DESCENTE_CADRAN_ONGLET if aligne_sur_onglet else 0
    compteur.setContentsMargins(0, descente, 0, 0)
    compteur.setFixedSize(TAILLE_COMPTEUR, TAILLE_COMPTEUR + descente)


def disposition(nombre):
    """Le nombre de cellules par rangee, pour `nombre` sessions.

    Carre autant que possible, rangees du haut d'abord plus remplies : 3 sessions donnent
    2 puis 1, jamais 1 puis 2 — une grande cellule en haut et une petite en bas se lit mal.
    """
    if nombre <= 0:
        return []
    colonnes = int(math.ceil(math.sqrt(nombre)))
    rangees = int(math.ceil(nombre / colonnes))
    tailles = [nombre // rangees] * rangees
    for index in range(nombre - sum(tailles)):
        tailles[index] += 1
    return tailles


class _Onglet(QFrame):
    """L'onglet de titre d'une cellule, avec le second pixel du trait bleu au focus.

    Meme dispositif que la vue (cf. VueKonsole.poser_liseret) : la feuille garde un trait
    de 1px, et le second est PEINT a l'interieur, en haut et sur les cotes, pas en bas.
    Demande de l'utilisateur (11/10/2026) : « le titre de l'onglet [doit avoir] un contour
    bleu vif, comme les fenetres, quand il est selectionne (sans ligne en bas) ». Ecarte :
    un `border: 2px` dans la feuille, qui decale d'1px le texte et la croix (le contenu
    suit l'epaisseur du bord) et casse leur calage sur les onglets.
    """

    _liseret = None

    def poser_liseret(self, couleur):
        if couleur != self._liseret:
            self._liseret = couleur
            self.update()

    def paintEvent(self, evenement):
        QFrame.paintEvent(self, evenement)
        if self._liseret is None:
            return
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, 0)
        rayon = 3
        chemin = QPainterPath(QPointF(r.left(), r.bottom()))
        chemin.lineTo(r.left(), r.top() + rayon)
        chemin.quadTo(r.topLeft(), r.topLeft() + QPointF(rayon, 0))
        chemin.lineTo(r.right() - rayon, r.top())
        chemin.quadTo(r.topRight(), r.topRight() + QPointF(0, rayon))
        chemin.lineTo(r.right(), r.bottom())
        peintre = QPainter(self)
        peintre.setRenderHint(QPainter.Antialiasing)
        peintre.setPen(QPen(QColor(self._liseret), 1))
        peintre.drawPath(chemin)
        peintre.end()


class _LigneSousOnglet(QHBoxLayout):
    """Ligne de la vue, remontee de `debord` pixels sous l'onglet de titre qui la precede.

    Une marge haute NEGATIVE aurait ete la voie directe : Qt la ramene a 0 (mesure du
    11/10/2026, `contentsMargins().top()` relu a 0 apres `setContentsMargins(1, -2, ...)`).
    """

    def __init__(self, debord):
        super().__init__()
        self._debord = debord

    def setGeometry(self, rect):
        super().setGeometry(rect.adjusted(0, -self._debord, 0, 0))


class Cellule(QFrame):
    """Une case de la mosaique : un bandeau de titre, et la vue en dessous.

    Le bandeau n'est pas decoratif. En mosaique, plus aucun onglet ne porte le titre ni la
    couleur d'etat de la session : c'est lui qui les reprend, sinon la mosaique montrerait
    quatre terminaux impossibles a distinguer.
    """

    #: Retrait interieur, aligne sur celui du cadre des vues (VueKonsole.MARGE_CADRE).
    MARGE = 3

    #: Retrait du TERMINAL dans sa cellule. 1 px, parce que c'est celui du terminal en mode
    #: onglets (mesure du 27/07/2026 : gauche=3 et droite=715 pour un conteneur de 2 a
    #: 716). Le cadre du terminal doit tomber au meme endroit dans les deux modes —
    #: demande de l'utilisateur, apres l'alignement des boutons.
    MARGE_TERMINAL = 1

    #: De combien l'onglet de titre DESCEND sur le cadre de la vue : l'epaisseur du cadre
    #: au focus (trait de la feuille + liseret, cf. VueKonsole.poser_liseret). Son fond
    #: couvre ces deux lignes, d'ou le « trou » qui l'ouvre sur la vue, comme l'onglet
    #: actif sur son volet (TABS_PATCH du fork, 11/10/2026).
    DEBORD_ONGLET = 2

    #: Retraits du TEXTE du titre, en pixels logiques, pour l'aligner sur le titre d'un
    #: onglet.
    #:
    #: ⚠ CES VALEURS VIENNENT DE LA CAPTURE, PAS DE `SE_TabBarTabText`. Le style dit ou il
    #: place le CHAMP de texte (14 px du bord pour un onglet, 11 pour l'etiquette) ; l'oeil
    #: voit le premier PIXEL ALLUME du glyphe, et un « C » ne remplit pas sa cellule de
    #: police. Sur capture, les deux modes commencaient deja au meme x=19 physique : cale
    #: sur le style, le titre de la mosaique est parti a 23 — j'ai casse un alignement qui
    #: existait. Le cote reste donc a 6, valeur d'origine.
    #:
    #: En HAUTEUR, le retrait donne a l'onglet de la cellule celle d'un onglet du mode
    #: onglets : 31 px logiques au-dessus du cadre, pour un texte de 17 (banc du
    #: 11/10/2026). TOUTES les rangees le prennent : un onglet bas (retrait 2) sous la
    #: premiere rangee y laissait moins d'espace entre titre et terminal qu'en haut
    #: (utilisateur, 11/10/2026 : « tout passer comme en haut »). Les rangees compactes ne
    #: gagnent plus que les 44 px du bandeau des boutons.
    RETRAIT_TEXTE_COTE = 6
    RETRAIT_TEXTE_VERTICAL = 7

    #: Emis quand l'utilisateur clique la croix de CETTE cellule. La mosaique le relaie
    #: avec la vue concernee ; c'est le panneau qui sait arreter une session.
    sig_fermeture_demandee = Signal()

    def __init__(self, vue, titre="", parent=None, compacte=False):
        """`compacte` : bandeau au plus bas, pour les rangees sous la premiere.

        Seule la PREMIERE rangee a besoin des 44 px du bandeau : c'est elle qui porte les
        boutons du panneau (TAILLE_BOUTON) et qui doit s'aligner sur les onglets. Sous
        elle, ces 44 px ne servaient qu'a separer deux terminaux — 49 px de vide entre
        eux, poignee et marge comprises (mesure du 10/10/2026 ; demande de l'utilisateur :
        « reduire un peu l'espace vide vertical entre deux fenetres dans la vue mosaique
        pour gagner de l'espace »). Toutes les cellules d'une rangee ont le meme reglage,
        donc leurs terminaux restent alignes.
        """
        super().__init__(parent)
        self.setObjectName("cellule_claude")
        self.setFrameShape(QFrame.NoFrame)
        self.vue = vue

        self._etiquette = QLabel(titre, self)
        self._etiquette.setObjectName("entete_cellule_claude")
        self._etiquette.setTextFormat(Qt.PlainText)
        # `Maximum` et non `Ignored` : l'etiquette ne prend pas plus que son texte, ce qui
        # colle la croix juste derriere lui (demande de l'utilisateur, 27/07/2026 : « pour
        # chaque session la croix doit etre juste a droite du titre »).
        # ⚠ `Maximum` NE SUFFIT PAS a la rendre retrecissable : un QLabel annonce la largeur
        # de tout son texte comme `minimumSizeHint`, et le layout la respecte. Un titre de
        # session long (titre OSC complet, 150 caracteres et plus) imposait ainsi 1400 px de
        # largeur minimale a la mosaique ; le panneau agrandi poussait la fenetre au-dela de
        # l'ecran, et elle y restait apres la reduction (10/10/2026 : « Reduire le panneau
        # Claude apres un plein ecran fait deborder la fenetre a droite »). Le minimum
        # explicite (1 et non 0 : 0 veut dire « pas de minimum » et rend la main au hint)
        # laisse le titre se tronquer ; l'infobulle le donne en entier.
        self._etiquette.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self._etiquette.setMinimumWidth(1)

        # LA LIGNE DE TITRE EST UNE LIGNE, pas seulement une etiquette : elle peut
        # accueillir un widget a sa droite. C'est ainsi que le bouton de sortie de la
        # mosaique ne coute AUCUNE hauteur — il partage la ligne des titres au lieu de
        # s'ajouter au-dessus. Demande de l'utilisateur (27/07/2026) : « le bouton de
        # reduction ne peut pas etre sur la meme ligne que les titres de la premiere ligne
        # de mosaique ? »
        self._ligne_titre = QHBoxLayout()
        self._ligne_titre.setContentsMargins(0, 0, 0, 0)
        self._ligne_titre.setSpacing(self.MARGE)
        # ⚠ LA HAUTEUR EST IMPOSEE A TOUTES LES CELLULES, meme a celles qui ne portent
        # aucun bouton. C'est ce qui garde les terminaux ALIGNES entre eux : sans cela,
        # seule la cellule qui accueille les boutons verrait sa ligne grandir, et son
        # terminal commencerait 27 px plus bas que celui de ses voisines (mesure du
        # 27/07/2026). On la pose sur l'etiquette plutot que sur le layout : c'est elle qui
        # dimensionne la ligne, et le titre s'y centre verticalement tout seul.
        if not compacte:
            # Les 44 px vont a la RANGEE, pas a l'etiquette : posees sur elle, sa couleur
            # d'etat remplissait toute la hauteur (« trop de hauteur sur les fenetres du
            # haut », utilisateur, 10/10/2026). Etiquette centree, et sa marge haute
            # (`poser_couleur`) garde le texte a la hauteur de celui des onglets.
            self._ligne_titre.addItem(QSpacerItem(
                0, TAILLE_BOUTON, QSizePolicy.Minimum, QSizePolicy.Fixed))
        # LE TITRE ET SA CROIX FORMENT UN ONGLET, ouvert sur la vue comme l'onglet actif
        # sur son volet. Demande de l'utilisateur (11/10/2026) : « il faut mettre en place
        # le meme dispositif avec le titre et les fenetres en mode mosaique ». Cale EN BAS
        # de la ligne de titre, et la vue remonte de DEBORD_ONGLET sous lui (cf.
        # `_LigneSousOnglet`) ; leve au-dessus d'elle a la fin du constructeur.
        self._onglet = _Onglet(self)
        self._onglet.setObjectName("onglet_cellule_claude")
        dans_onglet = QHBoxLayout(self._onglet)
        # A droite, la croix ne doit pas toucher le bord de l'onglet.
        dans_onglet.setContentsMargins(0, 0, MARGE_DROITE_ONGLET, self.DEBORD_ONGLET)
        # Sans espacement : le retrait droit de l'etiquette suffit, et la croix tombe a la
        # meme distance du texte qu'en mode onglets (banc du 11/10/2026).
        dans_onglet.setSpacing(0)
        dans_onglet.addWidget(self._etiquette, 0, Qt.AlignVCenter)
        #: Le tachymetre, entre le titre et la croix ; rempli plus bas (cf. self._compteur).
        place_compteur = dans_onglet.count()
        self._ligne_titre.addWidget(self._onglet, 0, Qt.AlignBottom)
        #: Couleurs de l'onglet : fond d'etat (`poser_couleur`), cadre et fond de la vue
        #: (`poser_cadre`). Gardees pour reconstruire la feuille quand l'une change.
        self._couleur_etat = None
        self._couleur_cadre = "transparent"
        self._fond_vue = "transparent"

        # LA CROIX DE FERMETURE, JUSTE A DROITE DU TITRE et sur sa ligne (demande de
        # l'utilisateur, 27/07/2026). Chaque cellule a la sienne : en mosaique il n'y a
        # plus d'onglet, donc plus la croix que l'onglet portait. C'est le SEUL bouton
        # propre a une cellule ; le « + » et la reduction, eux, valent pour tout le panneau,
        # ne sont poses que sur une cellule (cf. Mosaique.disposer) et vont a l'extreme
        # droite — d'ou l'espace elastique pose apres la croix et le tachymetre.
        self._bouton_fermer = QToolButton(self)
        self._bouton_fermer.setIcon(
            self.style().standardIcon(QStyle.SP_TitleBarCloseButton))
        self._bouton_fermer.setAutoRaise(True)
        self._bouton_fermer.setFocusPolicy(Qt.NoFocus)
        self._bouton_fermer.setStyleSheet(
            "QToolButton { padding: 0px; margin: 0px; border: none; }")
        self._bouton_fermer.setFixedSize(self._bouton_fermer.iconSize())
        self._bouton_fermer.setToolTip("Fermer cette instance Claude")
        self._bouton_fermer.clicked.connect(self.sig_fermeture_demandee)
        dans_onglet.addWidget(self._bouton_fermer, 0, Qt.AlignVCenter)

        # LE TACHYMETRE DE LA CONVERSATION, ENTRE LE TITRE ET LA CROIX (demande du
        # 31/07/2026 ; passe apres la croix le 04/10/2026 : « la croix de fermeture [doit]
        # etre a cote du titre, avant le tachymetre » ; revenu entre les deux le 11/10/2026 :
        # « le tachymetre [...] doit se trouver entre le titre et la croix de
        # fermeture »). Taille fixe et
        # petite : c'est un cadran dessine en fraction de son propre canevas (cf.
        # compteurs.Compteur), centre verticalement — pas une icone de bouton, qui se
        # calerait en haut comme `poser_widget_de_titre` le fait pour les boutons du
        # panneau (cf. AlignTop plus bas dans ce fichier).
        # ⚠ POSSEDEE PAR LA CELLULE, contrairement aux boutons du panneau qui sont PRETES
        # (poser_widget_de_titre / liberer) : ce cadran est propre a CETTE conversation, il
        # n'a pas a survivre a la destruction de sa cellule. `Mosaique.liberer()` n'a donc
        # rien de special a faire pour lui.
        # DANS l'onglet depuis le 11/10/2026, comme en mode onglets (onglet_compteur.py).
        self._compteur = Compteur(self)
        dimensionner_compteur(self._compteur, aligne_sur_onglet=False)
        dans_onglet.insertWidget(place_compteur, self._compteur, 0, Qt.AlignVCenter)
        dans_onglet.insertSpacing(place_compteur + 1, ESPACE_COMPTEUR_CROIX)
        self._ligne_titre.addStretch(1)

        # ⚠ LA LIGNE DE TITRE ET LE TERMINAL N'ONT PAS LES MEMES MARGES, ET C'EST VOULU.
        # Ils s'alignent sur deux choses differentes du mode onglets :
        #   - la ligne de titre sur le COIN de la barre d'onglets, qui touche le bord du
        #     panneau : elle ne peut donc porter aucune marge a droite, sinon les boutons
        #     ne tombent pas au meme endroit d'un mode a l'autre ;
        #   - le terminal sur le TERMINAL des onglets, qui lui garde 1 px de retrait
        #     (mesure du 27/07/2026 : gauche=3, droite=715, bas=311 dans un panneau dont
        #     le conteneur va de 2 a 716).
        # Une marge unique pour la cellule ne pouvait pas satisfaire les deux — d'ou le
        # sous-layout pour la vue.
        disposition_verticale = QVBoxLayout(self)
        disposition_verticale.setContentsMargins(0, 0, 0, 0)
        disposition_verticale.setSpacing(0)
        # L'onglet part du bord du terminal : son trait gauche prolonge celui du cadre.
        self._ligne_titre.setContentsMargins(self.MARGE_TERMINAL, 0, 0, 0)
        disposition_verticale.addLayout(self._ligne_titre)

        ligne_vue = _LigneSousOnglet(self.DEBORD_ONGLET)
        ligne_vue.setContentsMargins(self.MARGE_TERMINAL, 0,
                                     self.MARGE_TERMINAL, self.MARGE_TERMINAL)
        ligne_vue.setSpacing(0)
        ligne_vue.addWidget(vue)
        disposition_verticale.addLayout(ligne_vue, 1)
        #: Le layout qui tient la vue. Garde parce que `liberer` doit l'y retirer : depuis
        #: que la vue vit dans un SOUS-layout, `self.layout().removeWidget(vue)` ne la
        #: trouve plus. Le `setParent(None)` qui suit la detachait quand meme, donc les
        #: tests restaient verts — un retrait qui echoue en silence, exactement le genre
        #: de detail qui se paie plus tard.
        self._ligne_vue = ligne_vue
        vue.show()
        self._onglet.raise_()
        # Pose les retraits du texte, donc la hauteur de l'onglet, meme pour un panneau
        # qui ne colore jamais ses sessions (greffon Terminal).
        self.poser_couleur(None)

    def poser_widget_de_titre(self, widget):
        """Ajoute `widget` a L'EXTREME DROITE de la ligne de titre.

        La ligne est faite de [titre][croix][espace elastique] : ajouter en fin place donc
        le widget apres l'espace, colle au bord droit. Le titre et sa croix restent
        ensemble a gauche, quel que soit le nombre de boutons ajoutes ici.

        La cellule ne possede pas ce widget : `liberer` le rend, comme elle rend la vue.
        Sans cela, detruire la cellule emporterait un widget qui appartient a la mosaique
        et doit survivre a chaque redisposition.
        """
        # Cale EN HAUT : centre par defaut, un bouton plus court que la ligne se
        # recentrerait et son icone descendrait d'un pixel — c'est justement l'ecart qu'on
        # cherche a supprimer (cf. `poser_hauteur_des_boutons`).
        self._ligne_titre.addWidget(widget, 0, Qt.AlignTop)
        widget.show()

    def espacer_les_widgets_de_titre(self, ecarts):
        """Pose un blanc avant chaque widget ajoute, en partant du dernier.

        On travaille depuis la FIN parce que c'est la que sont les boutons : la ligne
        commence par le titre et sa croix, dont le nombre ne varie pas, et se termine par
        les widgets que la mosaique a poses. `setStretch` n'aiderait pas — ce sont des
        blancs fixes qu'on veut, pas un partage d'espace.
        """
        boite = self._ligne_titre
        # Les widgets de titre sont les derniers elements ; on remonte de la fin.
        indices = [i for i in range(boite.count())
                   if boite.itemAt(i).widget() is not None]
        poses = indices[-(len(ecarts) + 1):] if ecarts else []
        for rang, index in enumerate(poses[1:]):
            boite.setStretch(index, 0)
            # Un espacement se pose ENTRE deux elements : Qt n'offre pas de marge par
            # item, on insere donc un blanc fixe juste avant celui-ci.
            boite.insertSpacing(index + rang, max(0, ecarts[rang] - boite.spacing()))

    def retirer_widget_de_titre(self, widget):
        """Rend un widget pose par `poser_widget_de_titre`, sans le detruire."""
        self._ligne_titre.removeWidget(widget)
        widget.setParent(None)

    def poser_icone_fermer(self, icone):
        """L'icone de la croix. Ignoree si vide : la cellule garde celle du style."""
        if icone is not None and not icone.isNull():
            self._bouton_fermer.setIcon(icone)

    def poser_geometrie_croix(self, largeur, hauteur):
        """La TAILLE de la croix, reprise de celle d'un onglet. Rien d'autre.

        ⚠ ON NE FIXE PAS SA POSITION, ET C'EST DELIBERE. Une premiere version la posait a
        distance fixe du bord, comme dans un onglet — ce qui obligeait a figer la largeur
        du titre, donc a le tronquer. « Je veux que le titre puisse pousser la croix »
        (utilisateur, 27/07/2026) : elle reste collee au titre, qui garde sa largeur
        naturelle. Un titre long deplace donc la croix, contrairement a un onglet, et c'est
        voulu — une cellule est bien plus large qu'un onglet, y figer la croix la laisserait
        loin du texte.
        """
        self._bouton_fermer.setFixedSize(largeur, hauteur)

    def titre(self):
        return self._etiquette.text()

    def poser_titre(self, titre):
        self._etiquette.setText(titre)
        self._etiquette.setToolTip(titre)

    def poser_vitesse(self, valeur):
        """`valeur` en centimes/heure, ou None si non mesurable. Delegue au cadran."""
        self._compteur.poser_valeur(valeur)

    def poser_pleine_echelle(self, dollars_par_heure):
        self._compteur.poser_pleine_echelle(dollars_par_heure)

    def poser_couleur(self, couleur, couleur_texte=None):
        """Teinte l'onglet du titre. `couleur` a None lui rend le fond de la vue.

        Le remplissage de l'etiquette n'est pas decoratif : il aligne le texte sur celui
        des onglets, cf. `RETRAIT_TEXTE_*`.
        """
        # La couleur d'etat va au FOND DE L'ONGLET, comme la teinte d'un onglet en mode
        # onglets (`_teinter_les_onglets`) ; l'etiquette reste transparente.
        self._couleur_etat = couleur or None
        style = "background-color: transparent;"
        if couleur_texte:
            style += " color: %s;" % couleur_texte
        self._etiquette.setStyleSheet(
            "QLabel#entete_cellule_claude { %s padding: %dpx %dpx %dpx %dpx; }"
            % (style, self.RETRAIT_TEXTE_VERTICAL, self.RETRAIT_TEXTE_COTE,
               self.RETRAIT_TEXTE_VERTICAL, self.RETRAIT_TEXTE_COTE))
        self._habiller_onglet()

    def poser_cadre(self, couleur, fond, liseret=None):
        """Couleur du cadre de la vue, et son fond : l'onglet prolonge l'un et l'autre.

        `liseret` : couleur du second pixel au focus, None au repos (cf. `_Onglet`)."""
        self._couleur_cadre, self._fond_vue = couleur, fond
        self._onglet.poser_liseret(liseret)
        self._habiller_onglet()

    def _fond_onglet(self):
        """Fond de la vue, ou sa couleur d'etat ; eclairci au focus, comme le terminal."""
        fond = self._couleur_etat or self._fond_vue
        if self._onglet._liseret is not None and fond != "transparent":
            return eclaircir(fond)
        return fond

    def _habiller_onglet(self):
        feuille = (
            "QFrame#onglet_cellule_claude { background-color: %s;"
            " border: 1px solid %s; border-bottom: 0px;"
            # Rayon remis a 0 d'abord : la feuille de Spyder arrondit aussi le BAS des
            # QFrame, qui ecornait la jonction avec la vue (banc du 11/10/2026).
            " border-radius: 0px;"
            " border-top-left-radius: 4px; border-top-right-radius: 4px; }"
            % (self._fond_onglet(), self._couleur_cadre))
        if feuille != self._onglet.styleSheet():
            self._onglet.setStyleSheet(feuille)

    def liberer(self):
        """Detache la vue et la rend a l'appelant. La cellule devient jetable.

        Sans ce retrait explicite, `deleteLater()` sur la cellule emporterait la vue —
        donc le pty, donc l'instance Claude.
        """
        vue = self.vue
        self.vue = None
        if vue is not None:
            self._ligne_vue.removeWidget(vue)
            vue.setParent(None)
        return vue


class Mosaique(QWidget):
    """Le conteneur : des rangees de cellules, toutes redimensionnables.

    ELLE PORTE SON PROPRE BOUTON DE SORTIE, et ce n'est pas un luxe : passer en mosaique
    CACHE la barre d'onglets du panneau, et c'est elle qui porte le bouton « Agrandir le
    volet ». Sans bouton ici, la mosaique est un cul-de-sac — releve de l'utilisateur le
    27/07/2026 : « il n'y a pas de boutons pour reduire la mosaique et revenir a
    l'affichage normal ».

    DEUX EMPLACEMENTS ONT ETE ESSAYES AVANT, ET MESURES COMME IMPRATICABLES :
      - le coin de Spyder (`add_corner_widget`) : Spyder le pose LUI-MEME dans la barre
        d'onglets des qu'un panneau contient un `Tabs`. Il disparait donc avec elle, quoi
        qu'on demande. Mesure : bouton a 44x0, invisible, en mosaique ;
      - le bouton du patch, reutilise tel quel : il est DETRUIT a la maximisation
        (« Internal C++ object already deleted » au premier acces suivant). On ne batit
        pas dessus.
    D'ou un bouton a nous, dans un widget a nous, dont la duree de vie ne depend de
    personne.

    Le signal plutot qu'un appel direct : ce module n'importe RIEN de Spyder, c'est ce qui
    permet de le derouler offscreen sans IDE. Le panneau branche `sig_reduire_demande` sur
    `sig_unmaximize_plugin_requested`, l'API que Spyder prevoit exactement pour cela — on
    ne bricole pas un retour maison, on demande a la fenetre principale de defaire ce
    qu'elle a fait.
    """

    #: Emis quand l'utilisateur demande a quitter la mosaique. Le panneau decide de la
    #: suite : ici on ne sait meme pas qu'il existe un mode « agrandi ».
    sig_reduire_demande = Signal()

    #: Emis quand l'utilisateur demande une instance de plus. En mosaique, la barre
    #: d'onglets est cachee — donc le « + » qui y vit aussi, et il n'y avait plus aucun
    #: moyen d'ouvrir une session sans revenir en arriere (utilisateur, 27/07/2026).
    sig_nouvelle_demande = Signal()

    #: Emis avec la VUE dont la croix a ete cliquee. La mosaique ne ferme rien elle-meme :
    #: arreter une session est l'affaire du panneau, qui sait ce qu'est un pty.
    sig_fermeture_demandee = Signal(object)

    #: Emis quand l'utilisateur veut revoir ses instances en onglets SANS reduire le
    #: panneau. Le panneau tient la preference ; ici on ne fait que la demander.
    sig_disposition_demandee = Signal()

    #: Taille demandee a chaque cellule par `egaliser`. Volontairement bien plus grande que
    #: tout ecran : ce qui compte est que les parts soient EGALES et que la contrainte de
    #: taille minimale ne morde pas (cf. `egaliser`). Qt normalise a la place reelle.
    PART_EGALE = 1000000


    def __init__(self, parent=None):
        super().__init__(parent)
        self._cellules = []
        self._racine = None
        #: L'icone des croix, memorisee pour les cellules a venir (cf.
        #: `poser_icone_fermer`). None tant que le panneau ne l'a pas fournie : les
        #: cellules gardent alors celle du style.
        self._icone_fermer = None
        #: Les blancs entre boutons de titre, releves sur le coin de la barre d'onglets
        #: (cf. `poser_espacements`). Vide tant que le panneau ne les a pas mesures.
        self._espacements = []
        #: Taille et position de la croix, relevees sur celle d'un onglet (cf.
        #: `poser_geometrie_croix`). None tant que le panneau ne les a pas fournies.
        self._geometrie_croix = None
        #: Pleine echelle du tachymetre, en dollars/heure (cf. `poser_pleine_echelle`).
        #: None tant que le panneau ne l'a pas fournie : chaque cadran garde alors son
        #: propre repli (Compteur._pleine_echelle).
        self._pleine_echelle = None
        disposition_verticale = QVBoxLayout(self)
        disposition_verticale.setContentsMargins(0, 0, 0, 0)
        disposition_verticale.setSpacing(0)

        # LES BOUTONS NE COUTENT AUCUNE HAUTEUR : ils sont poses dans la LIGNE DE TITRE de
        # la derniere cellule du haut (cf. `disposer`), pas dans un bandeau a eux.
        #
        # Trois versions ont precede celle-ci, et leur mesure explique la forme actuelle :
        # un bandeau separe coutait 26 px (3 de marge + 23 de bouton pour une icone de 16),
        # puis 19 une fois marges et remplissage retires, puis 16 en fixant la taille du
        # bouton. Seize pixels perdus, c'etait encore seize de trop — « le bouton de
        # reduction ne peut pas etre sur la meme ligne que les titres de la premiere ligne
        # de mosaique ? » (utilisateur, 27/07/2026). Ils ne coutent plus rien du tout.
        #
        # Leur parent est la MOSAIQUE, pas une cellule : les cellules sont detruites et
        # refabriquees a chaque redisposition, et les boutons doivent leur survivre. Ils
        # leur sont pretes, jamais donnes (cf. `liberer`, qui les reprend avant de
        # detruire).
        self._bouton_nouveau = self._fabriquer_bouton(
            QStyle.SP_FileDialogNewFolder,
            "Ouvrir une instance Claude",
            self.sig_nouvelle_demande)
        self._bouton_disposition = self._fabriquer_bouton(
            QStyle.SP_FileDialogListView,
            "Afficher les instances en onglets",
            self.sig_disposition_demandee)
        self._bouton_reduire = self._fabriquer_bouton(
            QStyle.SP_TitleBarNormalButton,
            "Réduire le panneau et revenir aux onglets",
            self.sig_reduire_demande)
        #: Dans l'ordre d'affichage, de gauche a droite, et c'est le MEME que dans le coin
        #: de la barre d'onglets : disposition, « + », puis la sortie. Un geste doit se
        #: chercher au meme endroit, qu'on soit en onglets ou en mosaique.
        self._boutons_de_titre = (self._bouton_disposition, self._bouton_nouveau,
                                  self._bouton_reduire)

        self._disposition = disposition_verticale

    def _fabriquer_bouton(self, icone_de_repli, infobulle, signal):
        """Un bouton de ligne de titre : aussi petit que son icone, et rien autour.

        Les trois reglages qui suivent viennent chacun d'une mesure du 27/07/2026, et
        aucun n'est cosmetique :
          - `padding`/`margin`/`border` a zero : c'est le remplissage du QToolButton qui
            faisait 23 px de haut pour une icone de 16 ;
          - hauteur fixee a celle de l'icone : il restait sinon 3 px, une marge intrinseque
            que ni `padding` ni `margin` ne couvrent. « Si l'icone fait 16 pixels, on
            devrait pouvoir reduire a 16 pixels » — c'est exact, et c'est le seul moyen.
            ⚠ EN HAUTEUR SEULEMENT : la largeur garde `AIR_AUTOUR_DE_L_ICONE` de marge, qui
            ne coute rien puisque la ligne est dimensionnee par le titre ;
          - cache au depart : sans cellule pour l'accueillir, il flotterait a l'origine du
            widget, hors de tout layout — le piege des boutons orphelins, deja paye
            plusieurs fois sur ce depot.

        L'icone donnee ici est un REPLI, prise dans le style de Qt : pale et generique. Le
        panneau pose les vraies par `poser_icone_reduire` / `poser_icone_nouveau`, car ce
        module n'importe rien de Spyder — c'est le prix de le garder deroulable offscreen,
        et il est petit.
        """
        bouton = QToolButton(self)
        bouton.setIcon(self.style().standardIcon(icone_de_repli))
        bouton.setAutoRaise(True)
        bouton.setFocusPolicy(Qt.NoFocus)
        bouton.setStyleSheet(
            "QToolButton { padding: 0px; margin: 0px; border: none; }")
        bouton.setFixedSize(TAILLE_BOUTON, TAILLE_BOUTON)
        bouton.setToolTip(infobulle)
        bouton.clicked.connect(signal)
        bouton.hide()
        return bouton

    # ------------------------------------------------------------------ montage

    def disposer(self, elements):
        """Place `elements`, une liste de couples (vue, titre), en mosaique.

        Toute mosaique precedente est defaite d'abord — et ses vues rendues, pas
        detruites : `disposer` peut donc etre rappele a chaque ouverture ou fermeture de
        session sans rien casser.
        """
        self.liberer()
        if not elements:
            return

        racine = QSplitter(Qt.Vertical, self)
        racine.setObjectName("mosaique_claude")
        racine.setChildrenCollapsible(False)
        reste = list(elements)
        for numero, combien in enumerate(disposition(len(elements))):
            rangee = QSplitter(Qt.Horizontal, racine)
            rangee.setChildrenCollapsible(False)
            for vue, titre in reste[:combien]:
                cellule = Cellule(vue, titre, rangee, compacte=numero > 0)
                cellule.poser_icone_fermer(self._icone_fermer)
                if self._geometrie_croix:
                    cellule.poser_geometrie_croix(*self._geometrie_croix)
                if self._pleine_echelle is not None:
                    cellule.poser_pleine_echelle(self._pleine_echelle)
                # La cellule signale, la mosaique nomme QUI fermer : elle seule fait le
                # lien entre une cellule et sa vue, et ce lien change a chaque
                # redisposition.
                cellule.sig_fermeture_demandee.connect(
                    lambda _v=vue: self.sig_fermeture_demandee.emit(_v))
                rangee.addWidget(cellule)
                self._cellules.append(cellule)
            reste = reste[combien:]
            racine.addWidget(rangee)

        self._racine = racine
        self._disposition.addWidget(racine)
        # ⚠ CE show() N'EST PAS UNE PRECAUTION, IL EST LA SEULE CHOSE QUI FAIT APPARAITRE
        # LA MOSAIQUE. Un widget cree sous un parent DEJA VISIBLE nait avec l'attribut
        # WA_WState_Hidden et attend un show() explicite : l'ajouter a un layout ne
        # suffit pas. Mesure en vrai Spyder (27/07/2026) — le racine sortait de `disposer`
        # avec `hidden=True`, `WA_WState_Hidden=True`, `WA_ExplicitShowHide=False` (donc
        # cache par Qt, pas par nous) et la taille 100x30 d'un widget jamais mis en page.
        # La mosaique occupait pourtant bien ses 677x331 : elle affichait un aplat de fond.
        # Le seul show() du racine a suffi — les rangees et les cellules n'etaient
        # invisibles que par heritage (WA_WState_Hidden=False sur elles) et sont passees
        # a 336x331. Ne pas remplacer par un parcours des enfants : la mesure dit que ce
        # serait du code mort.
        #
        # ⚠ ET IL NE SE REPRODUIT PAS HORS SPYDER : le meme montage joue offscreen, layout
        # imbrique et voisin cache compris, montre le racine tout seul. Le garde-fou est
        # donc dans le scenario `--actions`, qui releve les geometries reelles, pas dans
        # les tests offscreen — cf. tests/test_mosaique.py, classe TestAffichage.
        racine.show()

        # Le bouton de sortie rejoint la ligne de titre de la DERNIERE cellule du HAUT,
        # donc en haut a droite de la mosaique — la ou l'oeil cherche ce bouton dans les
        # autres panneaux. Il ne coute aucune hauteur : la ligne existe deja pour le titre.
        # Les cellules sont rangees dans l'ordre d'affichage, donc la derniere de la
        # premiere rangee est a l'index « nombre de cellules de cette rangee, moins un ».
        derniere_du_haut = disposition(len(elements))[0] - 1
        for bouton in self._boutons_de_titre:
            self._cellules[derniere_du_haut].poser_widget_de_titre(bouton)
        self._appliquer_espacements()

        self.egaliser()

    def egaliser(self):
        """Donne la MEME taille a toutes les cellules d'une rangee, et a toutes les rangees.

        Sans cela, un QSplitter repartit la place selon le sizeHint de chaque enfant — et
        celui d'un terminal depend de son CONTENU (nombre de colonnes, longueur des lignes
        affichees). Deux sessions cote a cote recevaient donc des largeurs differentes, et
        qui changeaient d'un lancement a l'autre : « la largeur des elements de la mosaique
        a l'air d'avoir une largeur random » (utilisateur, 27/07/2026). C'etait exact, et ce
        n'etait pas du hasard — c'etait le texte affiche dans chaque terminal.

        ⚠ LES VALEURS DOIVENT ETRE GRANDES, PAS SEULEMENT EGALES. `setSizes([1, 1])` ne
        donne PAS deux moities : mesure du 27/07/2026, il rendait 154 et 642 px. Qt part
        des tailles demandees mais ne descend jamais sous le minimum de chaque widget, et
        des valeurs minuscules le laissent retomber sur sa propre repartition. Avec des
        valeurs tres superieures a la place disponible, la contrainte de minimum ne mord
        plus et la proportion demandee — egale — est respectee. La valeur absolue reste
        sans importance : Qt normalise.

        Publique, et rappelee apres chaque `disposer` : l'utilisateur reste libre de tirer
        les poignees ensuite, c'est tout l'interet d'un QSplitter — on ne fixe que le point
        de depart.
        """
        if self._racine is None:
            return
        for index in range(self._racine.count()):
            rangee = self._racine.widget(index)
            if isinstance(rangee, QSplitter) and rangee.count():
                rangee.setSizes([self.PART_EGALE] * rangee.count())
        if self._racine.count():
            self._racine.setSizes([self.PART_EGALE] * self._racine.count())

    def liberer(self):
        """Defait la mosaique et REND les vues (aucune n'est detruite).

        Retourne la liste des vues, dans l'ordre ou elles etaient affichees.

        ⚠ LES BOUTONS DE TITRE SONT REPRIS AVANT TOUTE DESTRUCTION, exactement pour la meme
        raison que les vues : Qt detruit les enfants avec leur parent, et ils vivent dans la
        ligne de titre d'une cellule. Sans cette reprise, la premiere redisposition les
        emporterait — et `disposer` les reposerait ensuite sur des objets C++ deja
        supprimes.
        """
        for bouton in self._boutons_de_titre:
            cellule = bouton.parentWidget()
            if cellule in self._cellules:
                cellule.retirer_widget_de_titre(bouton)
                bouton.setParent(self)
                bouton.hide()

        vues = [cellule.liberer() for cellule in self._cellules]
        for cellule in self._cellules:
            cellule.setParent(None)
            cellule.deleteLater()
        self._cellules = []
        if self._racine is not None:
            self._disposition.removeWidget(self._racine)
            self._racine.setParent(None)
            self._racine.deleteLater()
            self._racine = None
        return [vue for vue in vues if vue is not None]

    # ------------------------------------------------------------------ contenu

    def poser_icone_reduire(self, icone):
        """L'icone du bouton de sortie. Ignoree si elle est vide ou absente.

        Le repli sur l'icone du style n'est pas une politesse : une icone introuvable
        rendrait un QIcon VIDE, donc un bouton sans dessin — visible pour une sonde qui
        compte les widgets, invisible pour l'utilisateur. On garde alors celle de Qt,
        pale mais dessinee.
        """
        if icone is not None and not icone.isNull():
            self._bouton_reduire.setIcon(icone)

    def poser_icone_nouveau(self, icone):
        """L'icone du bouton « + ». Meme repli que ci-dessus si elle est vide."""
        if icone is not None and not icone.isNull():
            self._bouton_nouveau.setIcon(icone)

    def poser_hauteur_des_boutons(self, hauteur):
        """Aligne la hauteur des boutons de titre sur celle des boutons du coin.

        ⚠ CE N'EST PAS DU DETAIL : l'icone est CENTREE dans son bouton, donc un pixel de
        hauteur en plus la descend d'un demi-pixel, arrondi a un. Mesure du 27/07/2026 —
        boutons du coin 44x43, icones a y=13 ; boutons de la mosaique 44x44, icones a
        y=14. Les boutons etaient alignes au pixel pres et les DESSINS ne l'etaient pas.
        C'est l'utilisateur qui l'a vu, mes mesures portant sur les boutons.

        Les widgets sont cales EN HAUT de la ligne : centres, un bouton plus court que la
        ligne se recentrerait et reintroduirait le decalage qu'on vient de retirer.
        """
        if not hauteur or hauteur <= 0:
            return
        for bouton in self._boutons_de_titre:
            bouton.setFixedSize(bouton.width(), hauteur)

    def poser_espacements(self, ecarts):
        """Les blancs a laisser AVANT chaque bouton de titre, de gauche a droite.

        `ecarts` compte un element de moins que les boutons : c'est l'espace entre deux
        voisins. On les MESURE ailleurs plutot que de les fixer ici — le panneau les releve
        sur les boutons du coin de la barre d'onglets, pour que les deux modes tombent au
        meme endroit (demande de l'utilisateur, 27/07/2026). Les coder en dur reviendrait a
        figer un detail du style de QToolBar, qui espace ses boutons de 8 puis 4 px sans
        que rien ne le garantisse d'une version a l'autre.
        """
        self._espacements = list(ecarts or ())
        if self._racine is not None:
            self._appliquer_espacements()

    def _appliquer_espacements(self):
        """Repose les blancs sur la ligne de titre qui porte les boutons."""
        cellule = self._bouton_reduire.parentWidget()
        if cellule not in self._cellules or not self._espacements:
            return
        cellule.espacer_les_widgets_de_titre(self._espacements)

    def poser_icone_disposition(self, icone):
        """L'icone du bouton mosaique/onglets. Meme repli que ci-dessus si elle est vide."""
        if icone is not None and not icone.isNull():
            self._bouton_disposition.setIcon(icone)

    def poser_geometrie_croix(self, largeur, hauteur):
        """Cale la TAILLE des croix sur celle d'un onglet — pas leur position.

        La croix reste collee au titre, qui peut la pousser (demande de l'utilisateur,
        27/07/2026, apres un premier essai a position fixe qui obligeait a tronquer le
        titre). Seule la taille est reprise, pour que les deux modes se ressemblent.

        Comme l'icone, ces valeurs sont MEMORISEES : les cellules sont refabriquees a
        chaque redisposition, et un calage pose une seule fois disparaitrait a la premiere
        ouverture de session.
        """
        if not largeur or not hauteur:
            return
        self._geometrie_croix = (largeur, hauteur)
        for cellule in self._cellules:
            cellule.poser_geometrie_croix(largeur, hauteur)

    def poser_icone_fermer(self, icone):
        """L'icone des croix de fermeture — celle de Spyder, pas celle de Qt.

        ⚠ ELLE EST MEMORISEE, contrairement aux deux autres. Les croix appartiennent aux
        CELLULES, qui sont detruites et refabriquees a chaque redisposition : une icone
        posee une seule fois disparaitrait a la premiere ouverture de session. On la garde
        donc pour la reposer sur chaque cellule neuve (cf. `disposer`).

        L'utilisateur veut « le meme icone de croix que pour l'application Spyder »
        (27/07/2026) : c'est `fileclose`, celle que porte `CloseTabButton` sur les onglets.
        Le panneau la fournit, ce module n'important rien de Spyder.
        """
        if icone is not None and not icone.isNull():
            self._icone_fermer = icone
            for cellule in self._cellules:
                cellule.poser_icone_fermer(icone)

    def poser_couleur_poignees(self, couleur):
        """Teinte les poignees de redimensionnement, qui separent les cellules.

        Demande de l'utilisateur (27/07/2026) : « les poignees pour redimensionner les
        elements de la mosaique doivent avoir la couleur du fond ». Par defaut, Qt les
        dessine dans la couleur de fond du THEME de widgets, plus claire que celle des
        terminaux : deux barres pales traversaient la mosaique de part en part.

        On ne cible que `QSplitter::handle`, et par le style du splitter lui-meme plutot
        que par une feuille globale : une regle `QSplitter` nue redescendrait sur les
        cellules et sur les terminaux qu'elles contiennent, dont le fond est justement ce
        qui porte l'etat de chaque instance.
        """
        if self._racine is None:
            return
        style = ""
        if couleur:
            style = ("QSplitter::handle { background-color: %s; }" % couleur)
        self._racine.setStyleSheet(style)
        for index in range(self._racine.count()):
            rangee = self._racine.widget(index)
            if isinstance(rangee, QSplitter):
                rangee.setStyleSheet(style)

    def cellules(self):
        return list(self._cellules)

    def cellule_de(self, vue):
        for cellule in self._cellules:
            if cellule.vue is vue:
                return cellule
        return None

    def poser_titre(self, vue, titre):
        cellule = self.cellule_de(vue)
        if cellule is not None:
            cellule.poser_titre(titre)

    def poser_vitesse(self, vue, valeur):
        """`valeur` en centimes/heure, ou None si non mesurable — cf. usage.py."""
        cellule = self.cellule_de(vue)
        if cellule is not None:
            cellule.poser_vitesse(valeur)

    def poser_pleine_echelle(self, dollars_par_heure):
        """Memorisee comme l'icone de fermeture et la geometrie de la croix : les
        cellules sont detruites et refabriquees a chaque redisposition (cf. `disposer`),
        une echelle posee une seule fois disparaitrait a la premiere ouverture de
        session."""
        self._pleine_echelle = dollars_par_heure
        for cellule in self._cellules:
            cellule.poser_pleine_echelle(dollars_par_heure)

    def poser_couleur(self, vue, couleur, couleur_texte=None):
        cellule = self.cellule_de(vue)
        if cellule is not None:
            cellule.poser_couleur(couleur, couleur_texte)

    def poser_cadre(self, vue, couleur, fond, liseret=None):
        cellule = self.cellule_de(vue)
        if cellule is not None:
            cellule.poser_cadre(couleur, fond, liseret)

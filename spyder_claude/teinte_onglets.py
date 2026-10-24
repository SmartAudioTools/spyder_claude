"""La couleur d'etat de chaque session sur le FOND de son onglet : panneau et dock.

Demande de l'utilisateur, 10/10/2026 : « la coloration de la console ne se repercute pas
sur l'onglet en mode onglets, or il le faudrait » — la mosaique la portait deja sur le
titre de cellule. Puis, 24/10/2026 : « l'onglet doit etre legerement eclairci de la meme
maniere que la fenetre quand c'est l'onglet actif, quelle que soit la couleur de fond
(defaut, rouge, vert) », et « les arrondis exterieurs doivent suivre l'onglet pendant le
deplacement » ; et, survole, l'onglet s'eclaircit sans contour bleu.

Qt n'a pas de fond par onglet, et la feuille de style de Spyder (qdarkstyle) peint le
fond, l'arrondi et le soulignement de l'onglet actif sans exposer leur geometrie. D'ou :
la barre se peint normalement, puis, pour chaque onglet colore, sa FORME seule
(`CE_TabBarTabShape`) est rendue a part, les pixels de la couleur de son centre — le
fond — deviennent un masque, la couleur d'etat est peinte dans ce masque, et le libelle
(`CE_TabBarTabLabel`) est redessine par-dessus. Arrondis, bordure de survol et
soulignement bleu restent ceux du style. Ecarte : une feuille de style rendant les fonds
transparents pour peindre dessous — elle obligeait a recopier les couleurs de fond de
qdarkstyle et la geometrie de ses marges.

Deux raccords avec le conge du fork (patch_spyder_arrondi_onglet.py) :
  - la couleur de l'onglet actif, NON eclaircie, est posee dans la propriete
    'smartos_fond_onglet' de la barre avant qu'elle se peigne : le conge la prolonge, et
    l'eclaircit lui-meme au focus ;
  - pendant un glisser (`setMovable`), Qt ne peint PAS l'onglet actif dans la barre : il
    le peint une fois, a la pression, dans un widget enfant prive qui suit la souris. La
    teinte peinte a sa place d'origine y laissait un fantome colore, et l'onglet tire
    restait gris. Ce widget est donc repeint ici, onglet du style puis teinte.
"""

from qtpy import QT5
from qtpy.QtCore import QEvent, QObject, QRect, Qt
from qtpy.QtGui import QBitmap, QColor, QImage, QPainter, QRegion
from qtpy.QtWidgets import QStyle, QStyleOptionTab, QWidget

from spyder_konsole import konsole_view


def onglet_tire(barre):
    """Le widget ou Qt peint l'onglet tire pendant un glisser, ou None hors glisser.

    Meme critere que `_smartos_onglet_tire` du fork : un QMovableTabWidget n'a pas de
    meta-objet propre (classe 'QWidget') ; les boutons d'onglet ont leur classe."""
    for enfant in barre.children():
        if (isinstance(enfant, QWidget) and enfant.isVisible()
                and enfant.metaObject().className() == "QWidget"):
            return enfant
    return None


def _teindre(peintre, barre, option, couleur):
    """La couleur sur le fond de l'onglet decrit par `option`, puis son libelle."""
    cadre = option.rect
    forme = QImage(cadre.size(), QImage.Format_ARGB32_Premultiplied)
    forme.fill(Qt.transparent)
    peintre_forme = QPainter(forme)
    peintre_forme.translate(-cadre.topLeft())
    barre.style().drawControl(QStyle.CE_TabBarTabShape, option, peintre_forme, barre)
    peintre_forme.end()
    fond = forme.pixel(forme.width() // 2, forme.height() // 2)
    masque = QBitmap.fromImage(forme.createMaskFromColor(fond, Qt.MaskOutColor))
    peintre.save()
    peintre.setClipRegion(QRegion(masque).translated(cadre.topLeft()))
    peintre.fillRect(cadre, QColor(couleur))
    peintre.restore()
    barre.style().drawControl(QStyle.CE_TabBarTabLabel, option, peintre, barre)


class TeinteDesOnglets(QObject):
    """Filtre de la barre (et de son onglet tire) : teint chaque onglet de sa couleur.

    `couleur_de(index)` rend la couleur d'etat de l'onglet, ou None ; `au_focus()` dit si
    le volet a le clavier — l'onglet actif s'eclaircit alors comme son terminal."""

    def __init__(self, barre, couleur_de, au_focus):
        super().__init__(barre)
        self._barre = barre
        self._couleur_de = couleur_de
        self._au_focus = au_focus
        self._tire = None
        barre.installEventFilter(self)

    def _couleur_active(self, index):
        couleur = self._couleur_de(index)
        if couleur and self._au_focus():
            couleur = konsole_view.eclaircir(couleur)
        return couleur

    def eventFilter(self, objet, evenement):  # noqa: N802 - API Qt
        if evenement.type() != QEvent.Paint:
            return False
        barre = self._barre
        if objet is barre:
            barre.setProperty("smartos_fond_onglet",
                              self._couleur_de(barre.currentIndex()) or "")
            type(barre).paintEvent(barre, evenement)
            self._teinter_la_barre()
            return True
        if objet is self._tire:
            return self._peindre_l_onglet_tire(objet)
        return False

    def _teinter_la_barre(self):
        barre = self._barre
        tire = onglet_tire(barre)
        if tire is not None and tire is not self._tire:
            self._tire = tire
            tire.installEventFilter(self)
            tire.update()   # sa premiere image, celle de Qt, a pu partir avant le filtre
        peintre = None
        for index in range(barre.count()):
            couleur = self._couleur_active(index) if index == barre.currentIndex() \
                else self._couleur_de(index)
            # Pendant un glisser, l'onglet actif n'est pas peint dans la barre.
            if not couleur or (tire is not None and index == barre.currentIndex()):
                continue
            if peintre is None:
                peintre = QPainter(barre)
            option = QStyleOptionTab()
            barre.initStyleOption(option, index)
            # Survole : eclairci comme le fond gris du fork (patch_spyder_colors.py).
            if index != barre.currentIndex() and option.state & QStyle.State_MouseOver:
                couleur = konsole_view.eclaircir(couleur)
            _teindre(peintre, barre, option, couleur)
        if peintre is not None:
            peintre.end()

    def _peindre_l_onglet_tire(self, tire):
        """L'onglet actif comme Qt le peint dans ce widget (`setupMovableTab`), teint.

        Rend False sans couleur : Qt peint alors lui-meme l'image prise a la pression."""
        barre = self._barre
        couleur = self._couleur_active(barre.currentIndex())
        if not couleur:
            return False
        option = QStyleOptionTab()
        barre.initStyleOption(option, barre.currentIndex())
        # Qt le peint decale de PM_TabBarTabOverlap, en position « Moving » (Qt 6) ; Qt 5
        # n'a pas cette position et le peint en onglet seul (cf. le conge du fork).
        jeu = barre.style().pixelMetric(QStyle.PM_TabBarTabOverlap, None, barre)
        option.rect = QRect(jeu, 0, tire.width() - 2 * jeu, tire.height())
        option.position = (QStyleOptionTab.OnlyOneTab if QT5
                           else QStyleOptionTab.Moving)
        peintre = QPainter(tire)
        barre.style().drawControl(QStyle.CE_TabBarTab, option, peintre, barre)
        _teindre(peintre, barre, option, couleur)
        peintre.end()
        return True

# -*- coding: utf-8 -*-
"""Les widgets de consommation du panneau Claude.

Deux widgets, tous deux nourris depuis usage.py, aucun des deux ne devine ni n'estime :

  Compteur      le tachymetre d'une conversation — vitesse de depense en $/heure, cadran
                circulaire style compte-tours de voiture, le remplissage virant du vert
                au rouge avec la vitesse.
  BandeauUsage  la bande des deux jauges globales — fenetres de 5 h et de 7 jours, les
                VRAIS pourcentages du compte tels que Anthropic les calcule.

Aucun import Spyder obligatoire : seul un import protege de SpyderPalette, en repli sur
des couleurs fixes — meme discipline que mosaique.py, pour rester instanciable et
testable (grab()) sans Spyder installe.
"""

import math
import time
from datetime import datetime

from qtpy.QtCore import QPointF, QRectF, QSize, Qt
from qtpy.QtGui import QColor, QPainter, QPen
from qtpy.QtWidgets import QSizePolicy, QWidget

from spyder_claude import usage

#: Abreviations FRANCAISES explicites, jamais %a/%b : la locale du processus n'est pas
#: garantie (le script statusLine force meme LC_ALL=C), et un nom de jour dans la mauvaise
#: langue serait pire qu'aucun nom.
_JOURS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
_MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin",
         "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def _nombre(valeur, defaut):
    """« 4px », « 4 » ou 4 -> 4.0. Toute autre forme -> `defaut`.

    Copie de spyder_pyxel/.../widgets/screen.py : SpyderPalette.SIZE_BORDER_RADIUS vaut la
    CHAINE '4px', pas un nombre — la laisser fuiter dans un appel QPainter fait planter le
    peintre EN PLEIN paintEvent (etat desequilibre, puis segfault a la capture suivante).
    """
    if isinstance(valeur, (int, float)):
        return float(valeur)
    try:
        return float(str(valeur).strip().rstrip("px"))
    except (TypeError, ValueError):
        return defaut


def eclaircir(couleur, force=0.15):
    """Melange additif vers le blanc, `force` = part de blanc (0..1).

    Copie de spyder_line_profiler_targets/profile_results.py : QColor.lighter() est
    multiplicatif sur la valeur HSV et ne fait presque rien sur une teinte deja sombre —
    exactement le cas des couleurs de seuil sur un theme sombre.
    """
    force = max(0.0, min(1.0, force))
    return QColor(round(couleur.red() * (1 - force) + 255 * force),
                  round(couleur.green() * (1 - force) + 255 * force),
                  round(couleur.blue() * (1 - force) + 255 * force))


#: Echelle verte -> orange -> rouge du remplissage du tachymetre.
_ECHELLE = [
    (0.00, (76, 175, 80)),    # vert
    (0.67, (255, 152, 0)),    # orange
    (1.00, (211, 47, 47)),    # rouge
]


def couleur_echelle(position):
    """Couleur a `position` (0..1) sur l'echelle verte -> orange -> rouge.

    Meme principe que ECHELLE_THERMIQUE de profile_results.py (interpolation lineaire
    canal par canal), copie plutot qu'importe — les deux greffons ne se dependent pas
    l'un de l'autre pour douze lignes.
    """
    position = max(0.0, min(1.0, position))
    for (debut, (r1, v1, b1)), (fin, (r2, v2, b2)) in zip(_ECHELLE, _ECHELLE[1:]):
        if position <= fin:
            t = (position - debut) / (fin - debut)
            return QColor(int(r1 + (r2 - r1) * t), int(v1 + (v2 - v1) * t),
                          int(b1 + (b2 - b1) * t))
    return QColor(*_ECHELLE[-1][1])


def couleur_seuil(valeur, orange, rouge):
    """Trois paliers NETS, pas un degrade : vert en dessous de `orange`, orange entre
    `orange` et `rouge`, rouge au-dela.

    LE MEME MECANISME SERT A DEUX GRANDEURS DIFFERENTES dans ce depot — meme geste, pas
    les memes bornes ni la meme grandeur : la ligne de terminal de claude-statusline.sh
    compare un POURCENTAGE ABSOLU a `usage.SEUILS` ; la jauge du panneau (plus bas dans ce
    fichier) compare un ECART DE POINTS — l'avance sur l'allure ideale — a SEUILS_AVANCE.
    """
    if valeur >= rouge:
        return QColor(211, 47, 47)
    if valeur >= orange:
        return QColor(255, 152, 0)
    return QColor(76, 175, 80)


#: Seuils de couleur pour la jauge du panneau, en POINTS DE POURCENTAGE d'avance sur
#: l'allure ideale (cf. fraction_ecoulee et la barre bleue) — PAS de proximite au
#: blocage, contrairement a `usage.SEUILS`. A l'heure ou en retard (ecart <= 2), vert ;
#: un peu en avance, orange ; nettement en avance, rouge.
#: Demande de l'utilisateur (31/07/2026) : « je veux que la couleur de la barre de
#: progression de la jauge depende de l'avance/retard qu'on a par rapport a la barre
#: bleue ». PREMIER REGLAGE (5, 15) TROP TOLERANT : releve en direct le meme soir sur la
#: fenetre de 7 jours — 19 % consomme pour ~15 % d'allure ideale (~1 jour ecoule sur 7),
#: un ecart de seulement 3,8 points qui restait VERT alors que l'utilisateur le voyait
#: clairement en avance (rythme reel ~1,25x le rythme soutenable). Resserre a (2, 8).
SEUILS_AVANCE = (2, 8)


_rayon_cadre = None


def _rayon_cadre_defaut():
    """SpyderPalette.SIZE_BORDER_RADIUS, en repli protege et memoise (appele a chaque
    peinture de la bande — cf. spyder_pyxel/.../screen.py pour le meme idiome)."""
    global _rayon_cadre
    if _rayon_cadre is None:
        try:
            from spyder.utils.palette import SpyderPalette
            _rayon_cadre = SpyderPalette.SIZE_BORDER_RADIUS
        except Exception:
            _rayon_cadre = 4
    return _rayon_cadre


class Compteur(QWidget):
    """Le tachymetre d'une conversation : vitesse de depense en $/heure.

    Dessine en FRACTION DU CANEVAS (meme esprit que spyder_window_controls/spyder/
    widgets.py) : une seule geometrie, quelle que soit la taille posee par l'appelant —
    un onglet et une cellule de mosaique lui donnent chacun la leur.

    `None` (non mesurable — silence de plus de SILENCE_MAX, ou juste apres un /clear) ne
    dessine ni remplissage ni aiguille : un cadran ETEINT, jamais une vitesse nulle qui
    rassurerait a tort.
    """

    #: Angle de depart et etendue du cadran, en degres Qt (0° = 3 h, sens antihoraire
    #: positif). 225 -> -45 en balayant par le HAUT sur 270°, trou de 90° en bas : la
    #: forme d'un compte-tours de voiture.
    ANGLE_DEBUT = 225
    ETENDUE = -270

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        #: Centimes/heure, ou None = non mesurable.
        self._valeur = None
        #: Centimes/heure. 600 = 6,00 $/h, repli avant que le panneau ne pose la vraie
        #: valeur de get_conf("vitesse_maximale").
        self._pleine_echelle = 600.0

    def poser_valeur(self, valeur):
        """`valeur` en centimes/heure, ou None. Ne repeint que si la valeur a change."""
        if valeur != self._valeur:
            self._valeur = valeur
            self.update()

    def poser_pleine_echelle(self, dollars_par_heure):
        centimes = max(1.0, dollars_par_heure * 100.0)
        if centimes != self._pleine_echelle:
            self._pleine_echelle = centimes
            self.update()

    def sizeHint(self):
        return QSize(18, 18)

    @staticmethod
    def _couleur_piste():
        try:
            from spyder.utils.palette import SpyderPalette
            return QColor(SpyderPalette.COLOR_BACKGROUND_4)
        except Exception:
            return QColor(90, 90, 90)

    def paintEvent(self, event):  # noqa: N802 - API Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        cote = min(self.width(), self.height())
        if cote <= 0:
            return
        marge = cote * 0.10
        rect = QRectF(marge, marge, cote - 2 * marge, cote - 2 * marge)
        epaisseur = max(1.0, cote * 0.16)

        stylo = QPen(self._couleur_piste())
        stylo.setWidthF(epaisseur)
        stylo.setCapStyle(Qt.FlatCap)
        painter.setPen(stylo)
        painter.drawArc(rect, self.ANGLE_DEBUT * 16, self.ETENDUE * 16)

        # Plus de zone rouge permanente dans la piste (04/10/2026, « le rouge ne devrait
        # pas s'afficher par defaut ») : le rouge ne vient que du remplissage, a haut regime.

        if self._valeur is None:
            return  # cadran eteint : rien a mesurer, ni remplissage ni aiguille

        proportion = max(0.0, min(1.0, self._valeur / self._pleine_echelle))

        stylo.setColor(couleur_echelle(proportion))
        stylo.setWidthF(epaisseur)
        painter.setPen(stylo)
        painter.drawArc(rect, self.ANGLE_DEBUT * 16, round(self.ETENDUE * proportion * 16))

        angle = math.radians(self.ANGLE_DEBUT + self.ETENDUE * proportion)
        centre = rect.center()
        rayon = rect.width() / 2.0 - epaisseur / 2.0
        pointe = QPointF(centre.x() + rayon * math.cos(angle),
                         centre.y() - rayon * math.sin(angle))  # Qt : Y croit vers le bas
        stylo.setColor(self.palette().windowText().color())
        stylo.setWidthF(max(1.0, cote * 0.06))
        painter.setPen(stylo)
        painter.drawLine(centre, pointe)


def fraction_ecoulee(fenetre, duree_s, maintenant=None):
    """Part (0..1) de la fenetre deja ecoulee, ou None si non calculable.

    Deduite du temps RESTANT (`fenetre["fin"] - maintenant`) plutot que d'un instant de
    depart memorise : la fenetre a une duree FIXE et connue (5 h ou 7 jours), donc son
    debut se deduit de sa fin sans avoir besoin de le conserver nulle part — une seule
    donnee source, pas deux qui pourraient diverger. Bornee a [0, 1] : un `fin` deja
    depasse (fenetre en cours de reinitialisation) ne doit pas faire sortir la barre du
    cadre, et un `fin` tres eloigne (fraiche fenetre) ne doit pas la faire remonter avant
    le bord gauche.
    """
    if fenetre is None or duree_s is None or not fenetre.get("fin"):
        return None
    maintenant = maintenant if maintenant is not None else time.time()
    restant = fenetre["fin"] - maintenant
    return 1.0 - max(0.0, min(1.0, restant / duree_s))


def _heure(epoch):
    dt = datetime.fromtimestamp(epoch)
    return "%dh%02d" % (dt.hour, dt.minute)


def _jour_heure(epoch):
    dt = datetime.fromtimestamp(epoch)
    return "%s %d %s, %dh%02d" % (_JOURS[dt.weekday()], dt.day, _MOIS[dt.month - 1],
                                  dt.hour, dt.minute)


class BandeauUsage(QWidget):
    """La bande des deux jauges globales : fenetre de 5 h et fenetre de 7 jours.

    Ne se cache JAMAIS, meme sans session ouverte : une bande qui apparait et disparait
    ferait sauter la hauteur du terminal a chaque ouverture/fermeture d'onglet. Sans
    donnee, elle montre « — », jamais 0 % — un 0 % rassurerait a tort la ou l'on n'a rien
    mesure (rate_limits absent, ou toutes les sessions mortes).
    """

    HAUTEUR = 20
    #: Blanc entre les deux jauges.
    ECART = 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.HAUTEUR)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._fenetres = {"cinq_heures": None, "sept_jours": None}
        # Le texte affiche reste compact (largeur du panneau non garantie) ; l'explication
        # complete vit dans l'info-bulle plutot que dans le libelle.
        self.setToolTip(
            "Fenêtre de 5 heures : quota de messages remis à zéro toutes les 5 heures.\n"
            "Fenêtre de 7 jours : quota hebdomadaire, remis à zéro à un jour et une heure fixes.\n"
            "Le pourcentage est celui qu'Anthropic calcule ; « reset » donne l'heure du "
            "prochain retour à zéro de cette fenêtre.\n"
            "La barre bleue montre où on en serait à consommation parfaitement régulière.\n"
            "La couleur du remplissage suit l'écart avec cette barre bleue, pas le "
            "pourcentage : vert à l'heure ou en retard, orange puis rouge en avance.")

    def poser_fenetres(self, fenetres):
        """`fenetres` a la forme rendue par usage.fenetres(). Ne repeint que si ca change."""
        if fenetres != self._fenetres:
            self._fenetres = fenetres
            self.update()

    def sizeHint(self):
        return QSize(200, self.HAUTEUR)

    def _couleur_piste(self):
        return self.palette().base().color()  # relue a CHAQUE peinture : le theme peut changer

    def _couleur_texte(self):
        return self.palette().windowText().color()

    def paintEvent(self, event):  # noqa: N802 - API Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        largeur = (self.width() - self.ECART) / 2.0
        # DIVISIONS : chaque jauge est graduee en pointilles selon l'unite NATURELLE de sa
        # fenetre — 5 tirages pour les 5 heures (un par heure, tous les 20 %), 7 pour les
        # 7 jours (un par jour, tous les 100/7 ≈ 14,28 %). Demande de l'utilisateur
        # (31/07/2026) : « la consommation journaliere ne doit pas depasser 14,28 % » — les
        # graduations donnent une allure a suivre, pas seulement un pourcentage brut.
        self._dessiner_jauge(painter, QRectF(0, 0, largeur, self.HAUTEUR),
                             "cinq_heures", "5 h", _heure, divisions=5, duree_s=5 * 3600)
        self._dessiner_jauge(painter,
                             QRectF(largeur + self.ECART, 0, largeur, self.HAUTEUR),
                             "sept_jours", "7 j", _jour_heure, divisions=7,
                             duree_s=7 * 86400)

    #: Epaisseur du cadre, en pixels logiques. Trace en dernier, par-dessus le remplissage :
    #: c'est lui qui donne l'etendue 0-100 % de la jauge — sans lui, un remplissage presque
    #: aussi sombre que le fond du panneau se confond avec lui, et rien ne dit plus jusqu'ou
    #: la jauge peut monter (releve de l'utilisateur, 31/07/2026, sur la premiere version).
    EPAISSEUR_CADRE = 1

    def _couleur_cadre(self):
        # LA MEME COULEUR QUE LE CADRE DES PANNEAUX DE SPYDER AU REPOS (demande de
        # l'utilisateur, 31/07/2026 : « le contour des jauges de la meme couleur que le
        # contour des cadres de Spyder ») — celle que `main_widget._appliquer_cadre` pose
        # sur le panneau quand il n'a pas le clavier. Import protege + repli en dur : ce
        # module doit rester instanciable et testable hors Spyder (cf. mosaique.py).
        try:
            from spyder.utils.palette import SpyderPalette
            return QColor(SpyderPalette.COLOR_BACKGROUND_4)
        except Exception:
            return self.palette().mid().color()

    def _dessiner_jauge(self, painter, rect, cle, prefixe, formater_reset,
                        divisions=1, duree_s=None):
        rayon = _nombre(_rayon_cadre_defaut(), 4.0)
        # Le cadre est trace sur un rectangle RETRECI d'une demi-epaisseur : QPainter centre
        # le trait sur le contour, la moitie exterieure serait sinon rognee par les bords du
        # widget et le cadre paraitrait plus fin d'un cote que de l'autre.
        demi = self.EPAISSEUR_CADRE / 2.0
        rect_cadre = rect.adjusted(demi, demi, -demi, -demi)

        painter.setPen(Qt.NoPen)
        painter.setBrush(self._couleur_piste())
        painter.drawRoundedRect(rect, rayon, rayon)

        fenetre = self._fenetres.get(cle)
        if fenetre is None:
            painter.setPen(self._couleur_texte())
            painter.drawText(rect, Qt.AlignCenter, "%s : —" % prefixe)
            self._dessiner_graduations(painter, rect, divisions)
            self._dessiner_cadre(painter, rect_cadre, rayon)
            return

        pct = fenetre["pct"]
        # LA COULEUR DEPEND DE L'ALLURE, PAS DU POURCENTAGE ABSOLU (demande de
        # l'utilisateur, 31/07/2026) : ce que dit le remplissage (la hauteur) et ce que dit
        # sa couleur sont deux informations DIFFERENTES — combien j'ai consomme, et si je
        # consomme plus vite qu'une depense reguliere ne le voudrait. cf. SEUILS_AVANCE.
        # Sans allure calculable (fin absente), COULEUR NEUTRE — jamais verte par defaut,
        # qui rassurerait a tort la ou l'on n'a rien mesure.
        fraction = fraction_ecoulee(fenetre, duree_s)
        if fraction is None:
            couleur = self._couleur_cadre()
        else:
            ecart_points = pct - fraction * 100.0
            couleur = couleur_seuil(ecart_points, *SEUILS_AVANCE)
        if fenetre["age"] > usage.PEREMPTION:
            # Chiffre date : un plancher connu, pas une invalidation — on l'ESTOMPE plutot
            # que de le masquer.
            couleur = eclaircir(couleur, 0.35)
        rempli = QRectF(rect.x(), rect.y(), rect.width() * pct / 100.0, rect.height())
        if rempli.width() > 0:
            painter.setBrush(couleur)
            painter.drawRoundedRect(rempli, rayon, rayon)

        # « reset » ecrit en toutes lettres : une heure seule, en bout de ligne, ne dit pas
        # a quoi elle correspond (releve de l'utilisateur, 31/07/2026).
        reset = formater_reset(fenetre["fin"]) if fenetre["fin"] else ""
        texte = "%s : %d %%%s" % (prefixe, pct, (" (reset %s)" % reset) if reset else "")
        self._dessiner_texte(painter, rect, rempli, texte)
        self._dessiner_graduations(painter, rect, divisions)
        self._dessiner_cadre(painter, rect_cadre, rayon)
        self._dessiner_allure_ideale(painter, rect, fraction)

    #: Les graduations ne montent que sur ce quart de la hauteur, depuis le bas — des
    #: petits reperes au ras de la jauge, pas des traits qui coupent le texte en deux
    #: (demande de l'utilisateur, 31/07/2026, apres la premiere version en traits pleine
    #: hauteur).
    HAUTEUR_GRADUATION = 0.25

    def _dessiner_graduations(self, painter, rect, divisions):
        """Un petit trait pointille a chaque division INTERIEURE — jamais a 0 % ni 100 %,
        deja marques par le cadre — a l'unite NATURELLE de la fenetre : l'heure pour les
        5 h (tous les 20 %), le jour pour les 7 jours (tous les 100/7 ≈ 14,28 %).

        Demande de l'utilisateur (31/07/2026) : « la consommation journaliere ne doit pas
        depasser 14,28 % ». Les graduations donnent une ALLURE a suivre plutot qu'un
        pourcentage brut — au jour J, le remplissage ne devrait pas depasser la J-ieme
        graduation. Dessinees APRES le remplissage : elles doivent rester visibles par-
        dessus, sinon elles disparaitraient sous une couleur saturee.
        """
        if divisions <= 1:
            return
        stylo = QPen(self._couleur_cadre())
        stylo.setWidthF(1.0)
        stylo.setStyle(Qt.DotLine)
        painter.setPen(stylo)
        haut = rect.bottom() - rect.height() * self.HAUTEUR_GRADUATION
        for i in range(1, divisions):
            x = rect.x() + rect.width() * i / divisions
            painter.drawLine(QPointF(x, haut), QPointF(x, rect.bottom()))

    #: Bleu franc, choisi pour ne se confondre ni avec les trois couleurs de seuil
    #: (vert/orange/rouge du remplissage) ni avec le gris du cadre et des graduations —
    #: demande de l'utilisateur (31/07/2026) : « une barre bleue qui affiche ou on devrait
    #: en etre ... si on avait une consommation constante ».
    COULEUR_ALLURE_IDEALE = QColor(33, 150, 243)

    def _dessiner_allure_ideale(self, painter, rect, fraction):
        """Marque ou en serait le remplissage a une depense parfaitement REGULIERE.

        Le remplissage REEL dit « combien j'ai consomme » ; cette barre dit « combien
        j'aurais consomme a ce point de la fenetre si mon rythme etait constant » (cf.
        `fraction_ecoulee`, deja calculee par l'appelant — c'est aussi elle qui decide de
        la couleur du remplissage, les deux doivent s'accorder sur la MEME valeur). Les
        deux cote a cote repondent directement a la question qui a motive tout ce panneau :
        suis-je en avance ou en retard sur mon budget du jour ?
        """
        if fraction is None:
            return
        x = rect.x() + rect.width() * fraction
        stylo = QPen(self.COULEUR_ALLURE_IDEALE)
        stylo.setWidthF(2.0)
        painter.setPen(stylo)
        painter.drawLine(QPointF(x, rect.y()), QPointF(x, rect.bottom()))

    def _dessiner_cadre(self, painter, rect, rayon):
        painter.setPen(QPen(self._couleur_cadre(), self.EPAISSEUR_CADRE))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, rayon, rayon)

    def _dessiner_texte(self, painter, rect, rempli, texte):
        """Le texte est dessine DEUX FOIS, chacune avec un clip — une fois sur la partie
        remplie (texte clair, contraste sur une couleur saturee), une fois sur le reste
        (couleur de texte normale). Une bande a deux tons n'a pas de couleur de texte
        unique qui contraste avec les deux a la fois."""
        painter.save()
        painter.setClipRect(rempli)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(rect, Qt.AlignCenter, texte)
        painter.restore()

        reste = QRectF(rempli.right(), rect.y(), rect.right() - rempli.right(), rect.height())
        if reste.width() > 0:
            painter.save()
            painter.setClipRect(reste)
            painter.setPen(self._couleur_texte())
            painter.drawText(rect, Qt.AlignCenter, texte)
            painter.restore()

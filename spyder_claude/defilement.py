# -*- coding: utf-8 -*-
"""Barre de defilement EMULEE pour Claude Code en rendu plein ecran.

POURQUOI. En rendu « fullscreen », Claude Code vit sur l'ecran alternatif, suit la souris
et defile lui-meme : le clic place le curseur dans l'invite (demande de l'utilisateur,
19/10/2026), mais le terminal n'a plus d'historique et sa barre ne fait rien. Cette barre
parle au programme comme le ferait la molette : des crans SGR.

CE QU'ELLE SAIT, ET CE QU'ELLE NE SAIT PAS (« limiter le mensonge », demande de
l'utilisateur). Claude ne dit jamais ou il en est ; la position est donc MODELISEE, sur
la regle mesuree par deux sondes du 19/10/2026 (outils_smartos/sonde_molette.py) :

  - un cran = une ligne, A CONDITION que deux crans soient espaces d'au moins 50 ms : en
    deca (0 a 30 ms mesures), Claude ACCELERE — 12 crans d'un seul jet font 26 lignes
    (sonde --cadence). La barre envoie donc ses crans un par un, au rythme INTERVALLE ;
  - un cran de sens oppose au cran precedent est PERDU — si ce precedent a agi. Une
    sequence haut, bas, haut fait : +1, 0 (perdu), +1 (le bas n'ayant pas agi, il ne
    compte pas comme precedent agissant) ;
  - Ctrl+End ramene exactement en bas - mais il est IGNORE si un cran le suit aussitot
    (sonde_barre, 19/10/2026) : la barre attend INTERVALLE apres lui ;
  - Page precedente / suivante deplacent d'un nombre CONSTANT de lignes (18 sur 44, sans
    doute la moitie de la zone defilante), jamais perdues a l'inversion ni accelerees d'un
    seul jet (sonde --pages). Ni elles ni Ctrl+End ne changent le « precedent » de la
    molette : seul le dernier CRAN compte (Ctrl+End depuis une descente, PgUp, puis 2 crans
    vers le haut : +1 ; sonde_barre, 19/10/2026 - la sonde --pages, qui semblait dire
    l'inverse, faisait toujours preceder la touche d'un cran de sens oppose). Ce nombre
    n'est pas calcule, il est MESURE sur l'ecran a la premiere page (etalonnage), et
    remesure apres redimensionnement.

Un saut lointain se fait donc en un instant : Ctrl+End d'abord si la cible est plus pres du
bas, puis des pages d'un seul jet, puis la molette pour le reste (moins d'une page).

La derive est bornee par deux resynchronisations exactes : en bas (Ctrl+End, d = 0) et en
haut, detecte quand un paquet de crans ne change plus l'ecran (d = T). Entre les deux, une
regle devenue fausse dans une version future de Claude deriverait en silence : l'info-bulle
compte les inversions depuis la derniere resynchronisation, ce qui la rend visible.

Tant que le haut n'est pas connu, l'etendue T n'est qu'un minorant : le pouce est HACHURE
et la piste porte une page de marge au-dela de T.

CE QUE LA SORTIE AJOUTE se MESURE (« on ne peut vraiment pas mesurer le nombre de lignes
apporte par chaque nouvelle reponse ?? », 19/10/2026) : pendant que Claude ecrit, le texte de
l'ecran glisse d'autant, en bas comme vue remontee (Claude ne fige pas la vue). `suivre` lit
ce glissement entre deux ecrans ; la somme fait grandir T sans perdre le haut connu. Mesure
(outils_smartos/sonde_suivi.py) : exacte sur 4 reponses sur 5 ; la 5e, sur un ecran pas encore
plein, saute d'un coup au-dela de tout contenu commun - AMBIGU, et le pouce se rehachure.
"""

import time
from collections import Counter

from qtpy.QtCore import QEvent, QRectF, Qt, QTimer
from qtpy.QtGui import QBrush, QColor, QPainter
from qtpy.QtWidgets import QApplication, QWidget

#: Ctrl+End, « Jump to bottom » de Claude Code.
CTRL_FIN = "\x1b[1;5F"
PAGE_HAUT, PAGE_BAS = "\x1b[5~", "\x1b[6~"


PREUVES = 3     # lignes uniques concordantes pour croire un decalage (cf. suivre)
EPINGLEES = 8   # lignes distinctes qui ne bougent jamais : question en tete, pied (5 mesurees)


def varie(ecran):
    """L'ecran porte-t-il plus de lignes distinctes que l'epinglage ? Sinon il ne prouve rien."""
    return len({l for l in ecran if l.strip()}) > EPINGLEES


def decalage(avant, apres, attendu):
    """De combien de lignes (0 a `attendu`) le contenu est-il descendu entre deux ecrans ?

    La recherche est bornee au seul paquet qu'on vient d'envoyer : c'est ce qui la rend sure.
    Une ligne restee au MEME rang ne vote pas : c'est une ligne epinglee (question en tete,
    pied : 6 lignes dans la sonde du 19/10/2026) ou une ligne d'un contenu uniforme, et
    dans les deux cas elle ne dit rien du defilement. Parmi les autres, le decalage qui en
    superpose le plus de non vides DISTINCTES l'emporte, a egalite `attendu`.

    Ecran entierement inchange : arret net (butee) seulement s'il porte plus de lignes
    distinctes que n'en compte l'epinglage ; sinon le contenu est uniforme ou periodique et
    ne prouve rien, on garde `attendu` (reserve du Superviseur, 19/10/2026).
    """
    if avant == apres:
        return 0 if varie(avant) else attendu
    meilleur, score_max = attendu, -1
    for k in range(attendu, 0, -1):
        score = len({avant[i] for i in range(len(avant)) if i + k < len(apres)
                     and avant[i].strip() and avant[i] != apres[i] and avant[i] == apres[i + k]})
        if score > score_max:
            meilleur, score_max = k, score
    return meilleur


def suivre(avant, apres):
    """Decalage k du contenu entre deux ecrans (une ligne au rang i passe au rang i - k).

    Ne votent que les lignes non vides presentes UNE seule fois sur chacun des deux ecrans :
    une ligne vide, une barriere de code, un motif repete ne disent rien. Une ligne epinglee
    (question en tete, pied) vote 0 ; elle ne doit pas emporter un vrai defilement, d'ou :
    le meilleur k non nul gagne s'il a PREUVES votes et au moins le double du suivant non nul.
    Les lignes uniques DISPARUES trahissent un saut que les epinglees masqueraient (redessin,
    plus d'un ecran d'un coup) : un decalage k en fait sortir k par le haut, plus la ligne en
    cours d'ecriture ; au-dela de k + 2, rien n'est cru.
    Rend (k, votes), k None si l'ecran ne permet pas de conclure.
    """
    if avant == apres:
        return 0, {}
    uniques = [Counter(l for l in ecran if l.strip()) for ecran in (avant, apres)]
    rang = {l: i for i, l in enumerate(apres) if uniques[1][l] == 1}
    votes = Counter(i - rang[l] for i, l in enumerate(avant)
                    if uniques[0][l] == 1 and l in rang)
    disparues = sum(1 for l in avant if uniques[0][l] == 1 and l not in rang)
    non_nuls = sorted(((n, k) for k, n in votes.items() if k), reverse=True)
    k, n = (non_nuls[0][1], non_nuls[0][0]) if non_nuls else (0, votes[0])
    second = non_nuls[1][0] if len(non_nuls) > 1 else 0
    # deux voix suffisent sans concurrente : le debut d'une reponse n'a guere de lignes uniques
    # (accueil, question, indicateur) et c'est la que la 2e sonde perdait 10 lignes
    if (n >= PREUVES and n >= 2 * second or n >= 2 and not second) and disparues <= max(k, 0) + 2:
        return k, dict(votes)
    return None, dict(votes)


class ModeleDefilement:
    """La position supposee de Claude, sans Qt : d lignes au-dessus du bas, etendue T."""

    def __init__(self):
        self.reinitialiser()

    def reinitialiser(self):
        self.d = 0                  # lignes au-dessus du bas
        self.T = 0                  # etendue connue (minorant tant que haut_connu est faux)
        self.haut_connu = False
        self._precedent = 0         # sens du dernier cran QUI A AGI (+1, -1), 0 sinon
        self.inversions = 0         # depuis la derniere resynchronisation

    def envoyes(self, crans, sens):
        """Met le modele a jour apres l'envoi de `crans` crans dans `sens` (+1 = haut)."""
        if crans <= 0:
            return
        efficaces = crans
        if self._precedent == -sens:
            efficaces -= 1
            self.inversions += 1
        self._precedent = sens if efficaces else 0
        self._deplacer(sens * efficaces)

    def pages(self, lignes, sens):
        """Des touches page ont deplace de `lignes` : rien de perdu, precedent de la molette inchange."""
        self._deplacer(sens * lignes)

    def _deplacer(self, lignes):
        self.d = max(0, self.d + lignes)
        if self.haut_connu:
            self.d = min(self.d, self.T)
        self.T = max(self.T, self.d)

    def en_bas(self):
        """Ctrl+End vient d'etre envoye : resynchronisation exacte."""
        self.d = 0                  # le precedent de la molette, lui, reste (sonde_barre)
        self.inversions = 0

    def en_haut(self, d):
        """Le haut est atteint a `d` (un paquet n'a plus rien change) : resynchronisation."""
        self.d = self.T = d
        self.haut_connu = True      # le precedent reste celui des crans (une page n'y touche pas)
        self.inversions = 0

    def grandi(self, lignes):
        """La sortie a ajoute `lignes` lignes sous la vue (retire si < 0) ; d ne bouge pas."""
        self.T = max(self.T + lignes, self.d)


class BarreDefilementEmulee(QWidget):
    """La barre, posee a droite d'une VueKonsole ; visible quand Claude defile lui-meme."""

    LARGEUR = 12
    #: Au-dela de l'etendue connue, on avance par paquets et on regarde l'ecran apres
    #: chacun : c'est ce qui detecte le haut, a un paquet pres.
    PAQUET = 5
    #: Ecart entre deux crans (ms) : 50 mesure sans acceleration, 30 accelere deja.
    INTERVALLE = 50
    #: L'ecran est relu quand la sortie s'est tue CALME ms (plafond : PLAFOND ms).
    CALME = 120
    PLAFOND = 800
    #: Pendant la sortie, l'ecran est relu au plus toutes les SUIVI ms (0,1 ms la lecture).
    SUIVI = 40
    #: Un cran de molette a plus de ISOLE ms du precedent vaut une ligne ; plus pres, les
    #: lignes du systeme (3) : c'est la vitesse de l'utilisateur qui choisit, jamais un envoi
    #: plus serre (Claude accelererait selon la charge ; avis du Superviseur, 19/10/2026).
    ISOLE = 150
    #: Plafond de `mesurer`, en ms : sous le voile de lancement (PLAFOND_VOILE, 10 s).
    MESURE = 8000
    #: CALME pendant `mesurer` : sonde du 19/10/2026, 576 lignes trouvees exactement de 120 a
    #: 25 ms (128 a 410 lignes/s) ; 40 garde une marge pour une machine chargee.
    CALME_MESURE = 40

    def __init__(self, vue):
        super().__init__(vue)
        self._vue = vue
        self.modele = ModeleDefilement()
        self._cible = 0
        self._verification = None       # (d avant, ecran avant, etalonnage) en attente
        self._page_claude = None        # lignes par touche page, mesurees (cf. _verifier)
        self._paquet = None             # (d avant, ecran avant, crans restants) en cours
        self._glisse = None             # (y de depart, d de depart) pendant un glisser
        self._reste_molette = 0         # huitiemes de degre pas encore convertis en crans
        self._derniere_molette = 0.0    # instant du dernier evenement de molette, cf. ISOLE
        self._actif = False             # Claude defile-t-il lui-meme ? cf. _sur_mode
        self._ecran = None              # (ecran, d) de reference du suivi, cf. _suivre
        self._mesure = None             # (rappel, echeance) de `mesurer` en cours
        self.setFixedWidth(self.LARGEUR)
        self.setCursor(Qt.ArrowCursor)
        self.hide()
        self._calme = QTimer(self, singleShot=True, interval=self.CALME)
        self._calme.timeout.connect(self._verifier)
        self._plafond = QTimer(self, singleShot=True, interval=self.PLAFOND)
        self._plafond.timeout.connect(self._verifier)
        self._cadence = QTimer(self, singleShot=True, interval=self.INTERVALLE)
        self._cadence.setTimerType(Qt.PreciseTimer)
        self._cadence.timeout.connect(self._avancer)
        self._suivi = QTimer(self, singleShot=True, interval=self.SUIVI)
        self._suivi.timeout.connect(self._suivre)
        # Nos envois font glisser l'ecran eux aussi : on ne relit qu'une fois Claude repeint.
        self._occupe = QTimer(self, singleShot=True, interval=self.CALME)
        self._occupe.timeout.connect(self._suivre)
        self._sonde = QTimer(self, interval=self.CALME)
        self._sonde.timeout.connect(self._suivre_mesure)
        vue.sig_sortie.connect(self._sur_sortie)
        vue.sig_defilement_au_programme.connect(self._sur_mode)
        vue.ajouter_a_droite(self)
        widgets = vue.widgets_du_terminal()
        self._terminal = widgets[0]
        for widget in widgets:
            widget.installEventFilter(self)

    # ------------------------------------------------------------------ evenements

    def _sur_mode(self, actif):
        self.modele.reinitialiser()
        self._cible = 0
        self._verification = self._paquet = self._page_claude = self._ecran = None
        self._actif = actif
        self.setVisible(actif)

    def eventFilter(self, objet, evenement):  # noqa: N802 - API Qt
        if not self._actif:
            return False
        genre = evenement.type()
        if genre == QEvent.Wheel:
            self.wheelEvent(evenement)
            return True
        if genre == QEvent.KeyPress:
            touche, mods = evenement.key(), evenement.modifiers()
            if touche in (Qt.Key_Return, Qt.Key_Enter) and not mods & Qt.ShiftModifier:
                # Une question part : on la suit EN BAS, de facon exacte, plutot que de
                # supposer ce que Claude fait de la vue a l'envoi. Son echo arrive pendant ce
                # saut, que le suivi ne mesure pas (cf. _suivre) : le haut n'est plus connu.
                if self.modele.d:
                    self._en_bas()
                    self.modele.haut_connu = False
            elif touche == Qt.Key_O and mods & Qt.ControlModifier:
                # Ctrl+O bascule la transcription : autre contenu, autre etendue.
                self.modele.reinitialiser()
                self._cible = 0
                self._ecran = None
                self._occupe.start()
                self.update()
        elif genre == QEvent.Resize and objet is self._terminal:
            if evenement.size().width() == evenement.oldSize().width() and not self.modele.d:
                # Hauteur seule, en bas : Claude ne recoupe rien, T + lignes visibles reste
                # constant (sonde_suivi) ; le suivi le lit sur l'ecran une fois repeint.
                self._page_claude = None
                self._occupe.start()
            else:               # les lignes se recoupent : rien ne tient. Retour en bas.
                self.modele.reinitialiser()
                self._page_claude = self._ecran = None
                self._en_bas()
        return False

    def _sur_sortie(self):
        if self._verification is not None:
            self._calme.start()
        if not self._suivi.isActive():
            self._suivi.start()

    def _suivre(self):
        """Fait grandir T de ce que la sortie a ajoute : g = k + (d - d de reference).

        Le glissement k de l'ecran melange la sortie (le texte monte de g) et nos propres
        deplacements (il descend quand on remonte), que le modele connait. Pendant un envoi
        de la barre, rien n'est relu : la reference reste celle d'avant, et la comparaison se
        fait sur l'ecran repeint. Ecran illisible (ambigu) : le haut n'est plus connu - sauf
        si c'est notre propre saut qui l'a rendu illisible (plus d'un ecran, Ctrl+End depuis
        loin) : la sortie de ces quelques ms est perdue, c'est la limite connue.
        """
        if not self._actif or self._occupe.isActive() or self._verification is not None:
            return
        if self._terminal.selectedText(False).strip():
            self._ecran = None          # lire l'ecran passe par la selection et l'effacerait
            self.modele.haut_connu = False
            self.update()
            return
        ecran, d = self._vue.texte_ecran(), self.modele.d
        reference, self._ecran = self._ecran, (ecran, d)
        if reference is None or reference[0] == ecran:
            return                      # ecran immobile : aucune preuve de croissance
        k = suivre(reference[0], ecran)[0]
        if k is not None:
            self.modele.grandi(k + d - reference[1])
        elif d == reference[1]:
            self.modele.haut_connu = False
        self.update()

    # ------------------------------------------------------------------ mouvement

    def aller_a(self, cible):
        """Vise `cible` lignes au-dessus du bas ; la file avance tant qu'elle peut."""
        self._cible = max(0, cible)
        if self.modele.haut_connu:
            self._cible = min(self._cible, self.modele.T)
        self._avancer()

    def mesurer(self, fini):
        """Une fois, sous le voile de lancement : jusqu'en haut (T exact), retour en bas, `fini()`.

        « j'ai toujours des barres rayees a l'ouverture d'anciennes sessions » ; l'aller-retour
        apres chaque reponse est refuse (« 1 a 2 s c'est beaucoup trop long »), cache sous le
        voile il ne coute rien. Au plafond MESURE, retour en bas quand meme : T reste un
        minorant, haut_connu faux, et la barre hachuree le dit (jamais une etendue inventee).
        """
        if not self._actif or self.modele.haut_connu:
            fini()
            return
        self._mesure = (fini, time.monotonic() + self.MESURE / 1000)
        self._cadencer(self.CALME_MESURE)
        self._sonde.start()
        self.aller_a(10 ** 6)

    def _suivre_mesure(self):
        fini, echeance = self._mesure
        arrive = (self._cible == self.modele.d and self._verification is None
                  and self._paquet is None)
        if not arrive and time.monotonic() < echeance:
            return
        self._sonde.stop()
        self._mesure = None
        self._cadencer(self.CALME)
        self.aller_a(0)                 # Ctrl+End, meme si une page attend sa relecture
        QTimer.singleShot(self.CALME, fini)     # le temps que Claude repeigne le bas

    def _cadencer(self, calme):
        for minuteur in (self._calme, self._occupe, self._sonde):
            minuteur.setInterval(calme)

    def _envoyer(self, texte):
        self._occupe.start()
        self._vue.envoyer(texte)

    def _en_bas(self, cible=0):
        self._envoyer(CTRL_FIN)
        self.modele.en_bas()
        self._cible = cible
        self._cadence.start()           # suivi AUSSITOT d'un cran, Ctrl+End est ignore (sonde_barre)
        self._verification = self._paquet = None
        self.update()

    def _avancer(self):
        """Un cran au plus par appel ; le suivant attend INTERVALLE ms (sinon Claude accelere)."""
        modele = self.modele
        if self._cible == 0 and (modele.d or self._verification):
            self._en_bas()              # exact, meme si un paquet ou une page etait en cours
            return
        if self._verification is not None or self._cadence.isActive():
            return                      # un paquet attend sa relecture, ou un cran vient de partir
        if self._paquet and self._cible <= modele.d:
            self._paquet = None         # la cible a recule : ce paquet ne servira pas
        if self._paquet:
            d_avant, avant, restants = self._paquet
            if restants:
                self._paquet = (d_avant, avant, restants - 1)
                self._cran(1)
            else:                       # paquet parti : relire l'ecran une fois la sortie tue
                self._paquet = None
                self._verifier_plus_tard(d_avant, avant)
            return
        ecart = self._cible - modele.d
        if 0 < self._cible < -ecart:    # plus pres du bas que d'ici : Ctrl+End, exact
            self._en_bas(self._cible)
            return                      # la suite au prochain tour de cadence
        page, sens = self._page_claude, 1 if ecart > 0 else -1
        if ecart > 0 and not modele.haut_connu and modele.d >= modele.T:
            # Zone inconnue : une page ou un paquet de crans, l'ecran relu apres chacun.
            avant = self._vue.texte_ecran()
            if not varie(avant):        # rien ne prouverait la butee : supposer, c'est deriver
                self._cible = modele.d  # (accueil d'une conversation neuve : 1551 lignes
                return                  # inventees, sonde_suivi du 19/10/2026)
            if page and ecart >= page:
                self._envoyer(PAGE_HAUT)
                modele.pages(page, 1)
                self._verifier_plus_tard(modele.d - page, avant)
            elif not page and ecart >= self._vue.lignes_ecran() and varie(avant):
                self._envoyer(PAGE_HAUT)     # la page d'etalonnage : sa taille est lue apres
                self._verifier_plus_tard(modele.d, avant, etalonnage=True)
            else:
                self._paquet = (modele.d, avant, min(ecart, self.PAQUET))
                self._avancer()
            return
        pages = abs(ecart) // page if page else 0
        if pages and ecart > 0 and not modele.haut_connu:
            pages = min(pages, (modele.T - modele.d) // page)    # au-dela, zone inconnue
        if pages:                       # d'un seul jet : les pages n'accelerent pas
            self._envoyer((PAGE_HAUT if sens > 0 else PAGE_BAS) * pages)
            modele.pages(pages * page, sens)
            self._cadence.start()
            self.update()
        elif ecart:
            self._cran(sens)

    def _verifier_plus_tard(self, d_avant, avant, etalonnage=False):
        self._verification = (d_avant, avant, etalonnage)
        self._calme.start()
        self._plafond.start()
        self.update()

    def _cran(self, sens):
        self._occupe.start()
        self._vue.envoyer_molette(sens)
        self.modele.envoyes(1, sens)
        self._cadence.start()
        self.update()

    def _verifier(self):
        if self._verification is None:
            return
        self._calme.stop()
        self._plafond.stop()
        d_avant, avant, etalonnage = self._verification
        self._verification = None
        attendu = self._vue.lignes_ecran() if etalonnage else self.modele.d - d_avant
        bouge = decalage(avant, self._vue.texte_ecran(), attendu)
        if etalonnage:                  # une page qui a bouge donne sa taille ; sinon, le haut
            self._page_claude = bouge or None
            self.modele.pages(bouge, 1)
            haut = not bouge
        else:
            haut = bouge < attendu
        if haut:                        # la butee est dans ce paquet
            self.modele.en_haut(d_avant + bouge)
            self._cible = min(self._cible, self.modele.d)
        self.update()
        self._suivi.start()             # la relecture que _suivre a laissee passer
        self._avancer()

    # ------------------------------------------------------------------ dessin

    def _geometrie(self):
        """(hauteur de la piste en lignes, page) : une page de marge si le haut est inconnu."""
        page = max(1, self._vue.lignes_ecran())
        etendue = self.modele.T + (0 if self.modele.haut_connu else page)
        return etendue + page, page

    def _pouce(self):
        total, page = self._geometrie()
        h = self.height()
        hauteur = max(16.0, h * page / total)
        haut = (total - page - self.modele.d) / max(1, total - page) * (h - hauteur)
        return QRectF(1, haut, self.width() - 2, hauteur)

    def paintEvent(self, _evenement):  # noqa: N802 - API Qt
        peintre = QPainter(self)
        peintre.setRenderHint(QPainter.Antialiasing)
        texte = self.palette().color(self.foregroundRole())
        pouce = QColor(texte)
        pouce.setAlpha(110)
        rect = self._pouce()
        if self.modele.haut_connu:
            peintre.setBrush(pouce)
        else:
            peintre.setBrush(QBrush(pouce, Qt.BDiagPattern))
        peintre.setPen(pouce)
        peintre.drawRoundedRect(rect, 3, 3)

    def event(self, evenement):
        if evenement.type() == QEvent.ToolTip:
            m = self.modele
            self.setToolTip(
                "Position estimée : %d lignes au-dessus du bas\n"
                "Haut %s (%d lignes connues)\n"
                "%d inversion(s) depuis la dernière resynchronisation"
                % (m.d, "atteint" if m.haut_connu else "encore inconnu", m.T, m.inversions))
        return super().event(evenement)

    def mousePressEvent(self, evenement):  # noqa: N802 - API Qt
        y = evenement.position().y()
        rect = self._pouce()
        if rect.top() <= y <= rect.bottom():
            self._glisse = (y, self.modele.d)
        else:                           # clic sur la piste : une page dans ce sens
            page = self._geometrie()[1]
            self.aller_a(self._cible + (page if y < rect.top() else -page))

    def mouseMoveEvent(self, evenement):  # noqa: N802 - API Qt
        if self._glisse is None:
            return
        y0, d0 = self._glisse
        total, page = self._geometrie()
        lignes_par_pixel = (total - page) / max(1.0, self.height() - self._pouce().height())
        self.aller_a(round(d0 - (evenement.position().y() - y0) * lignes_par_pixel))

    def mouseReleaseEvent(self, _evenement):  # noqa: N802 - API Qt
        self._glisse = None

    def wheelEvent(self, evenement):  # noqa: N802 - API Qt
        # Un pave tactile envoie des fractions de cran : on les cumule.
        self._reste_molette += evenement.angleDelta().y()
        crans = int(self._reste_molette / 120)
        self._reste_molette -= crans * 120
        maintenant = time.monotonic()
        rapide = maintenant - self._derniere_molette < self.ISOLE / 1000
        self._derniere_molette = maintenant
        if crans:   # « ligne a ligne beaucoup trop lent », sans perdre le ligne a ligne
            self.aller_a(self._cible + crans * (QApplication.wheelScrollLines() if rapide else 1))

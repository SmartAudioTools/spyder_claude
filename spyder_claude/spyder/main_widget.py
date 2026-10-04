# -*- coding: utf-8 -*-
"""Le panneau « Claude » : une instance de Claude Code par onglet, dans Spyder.

GREFFON INDEPENDANT DU GREFFON TERMINAL, ET DELIBEREMENT. Les deux panneaux se
ressemblent aujourd'hui — meme moteur de terminal, meme mosaique, memes boutons — et une
premiere version faisait donc heriter celui-ci de celui-la. L'utilisateur l'a refuse le
31/07/2026, dans ces termes : « si le panneau Claude est pour l'instant similaire a celui
de Terminal, il va pouvoir s'en eloigner par la suite. Je veux 2 greffons independants. »
L'heritage rendait chaque divergence future couteuse — surcharger, puis surcharger la
surcharge — et faisait qu'une correction du Terminal changeait Claude sans qu'on le
demande. Les deux arbres sont donc jumeaux et separes.

⚠ CE QUI EST JUMEAU, ET CE QUI NE L'EST PAS. Ce fichier et
spyder_konsole/spyder/main_widget.py sont jumeaux : un defaut trouve ici est
probablement la-bas, et tant qu'ils n'ont pas diverge un correctif se porte des deux cotes.
C'est le prix assume de l'independance, pas un oubli. Le MOTEUR de terminal, lui, echappe a
cette regle : sorti des deux greffons le 31/07/2026 (paquet smartos_konsole), puis rapatrie
dans spyder_konsole (konsole_view.py) le 09/08/2026 sur decision de l'utilisateur —
ce greffon-ci le tire en dependance pip. Il n'en existe qu'un exemplaire, le corriger suffit. La
frontiere est nette : ici l'AFFICHAGE, qui a vocation a diverger ; la-bas le TERMINAL, qui
n'en a aucune.

CE QUE CE PANNEAU AJOUTE A UN PANNEAU DE TERMINAUX ORDINAIRE :

  1. LA COMMANDE. Chaque onglet ouvre le shell du profil Konsole, puis y tape `claude -r`.
     On passe par le SHELL plutot que d'executer le binaire directement : c'est ce que
     fait l'utilisateur dans une Konsole, donc son environnement (PATH, rc, pyenv) est
     exactement celui qu'il connait — et quand Claude sort, il reste un shell, pas un
     onglet mort.

  2. L'IDENTITE DE SESSION. Deux variables d'environnement marquent la session
     (cf. etat_instances.variables_de_session). Elles sont le SEUL signe auquel
     `claude-window.sh` reconnait une instance hebergee par un panneau ; sans elles, le
     hook la traiterait comme une fenetre Konsole introuvable et son arbitrage la
     sauterait en silence.

  3. LE COMPORTEMENT DES INSTANCES, REPORTE DE LA FENETRE A L'ONGLET. C'est la demande de
     depart — « en gardant tout le travail que j'avais fait sur le comportement des
     instances de Claude dans la Konsole ». Le travail en question est celui de
     claude-window.sh : fond rouge sombre quand une instance attend une reponse, vert
     sombre quand elle a fini, et un arbitre unique qui decide laquelle doit recevoir le
     clavier. Rien de tout cela n'est reimplemente ici :

       - le FOND est le meme, aux memes couleurs, mais pose par le jeu de couleurs du
         moteur (`VueKonsole.appliquer_schema`) et non par une sequence OSC sur le pty ;
       - le TITRE arrive tout seul : claude-title.sh, ne trouvant pas KONSOLE_DBUS_SERVICE
         (le panneau le retire de l'environnement), retombe sur OSC 2, que le moteur de
         Konsole traduit en `titleChanged`, donc en titre d'onglet. Il n'y avait rien a
         ecrire ;
       - le FOCUS reste decide par l'arbitre. Une fenetre Konsole se remonte ; un onglet
         ne le peut pas, alors le hook depose une demande que le panneau relit. Le panneau
         ne se donne JAMAIS le focus de lui-meme — sinon deux instances qui finissent en
         meme temps se le disputeraient, ce que la file d'attente existe pour empecher.

POURQUOI SONDER PLUTOT QU'ECOUTER. Le registre est un dossier de petits fichiers reecrits
par `mv`, depuis des processus qui ne nous connaissent pas. Un QFileSystemWatcher sur un
dossier signale les creations et les suppressions, mais pas de facon fiable la reecriture
d'un fichier deja surveille — et il faut de toute facon relire tout le dossier a chaque
signal. Un minuteur d'une demi-seconde fait le meme travail, sans cas particulier, et se
deroule dans un test sans boucle d'evenements.
"""

import os
import uuid

import qtawesome as qta

from qtpy.QtCore import QEvent, Qt, QTimer, Signal
from qtpy.QtGui import QIcon
from qtpy.QtWidgets import QApplication, QLabel, QPushButton, QTabBar, QVBoxLayout

from spyder.widgets.tabs import Tabs

from spyder.api.widgets.main_widget import PluginMainWidget
from spyder.utils.icon_manager import ima

from spyder_claude import etat_instances, usage
from spyder_konsole import konsole_view
from spyder_konsole.konsole_view import VueKonsole
from spyder_claude.compteurs import BandeauUsage
from spyder_claude.mosaique import Mosaique
from spyder_claude.spyder.onglet_compteur import CoinDOnglet
from spyder_claude.spyder.translations import _


#: Couleur de la pastille d'etat sur l'onglet. PAS celle du fond : un rond de 12 pixels
#: en #3a1414 sur une barre d'onglets sombre est invisible. Ce sont les memes teintes,
#: eclaircies jusqu'a se voir — le fond du terminal, lui, garde les couleurs d'origine.
PASTILLES = {"waiting": "#e05252", "idle": "#4caf70"}


class PanneauClaude(PluginMainWidget):
    """Conteneur a onglets d'instances Claude Code."""

    #: Ce qui est tape dans le shell a l'ouverture d'un onglet. Reglable par l'option
    #: `commande` de la section de configuration du greffon.
    COMMANDE_DEFAUT = "claude -r"

    #: Dollars/heure a partir desquels le tachymetre d'une conversation est a fond.
    #: Reglable par l'option `vitesse_maximale` de la section de configuration du
    #: greffon. PROVISOIRE : pose avant d'avoir ete mesuree sur un vrai poste (a corriger
    #: une fois une session reelle donnee — cout_total_usd / heures ecoulees — cf.
    #: l'entree DONE de ce travail).
    VITESSE_MAXIMALE_DEFAUT = 6.0

    #: Periode de relecture du registre d'etat, en millisecondes. Une demi-seconde : le
    #: hook, lui, ecrit puis arbitre en ~0,5 s (appels D-Bus + journalctl), donc sonder
    #: plus vite ne rendrait rien de plus recent.
    PERIODE_SONDAGE = 500

    #: Le greffon repond en appelant `ouvrir_terminal(repertoire)` : le panneau demande,
    #: il ne va pas chercher.
    sig_repertoire_demande = Signal()

    #: Nom de l'action « Agrandir le volet courant » du greffon Layout
    #: (`LayoutContainerActions.MaximizeCurrentDockwidget`). Ecrit ici plutot qu'importe :
    #: l'import viserait `spyder.plugins.layout.container`, un module interne, et le
    #: greffon ne demarrerait plus du tout s'il changeait de place — alors qu'avec la
    #: chaine, seul le bouton de sortie perd son chemin prefere et retombe sur son repli.
    ACTION_AGRANDIR = "Maximize pane"

    def __init__(self, name=None, plugin=None, parent=None):
        # AVANT super().__init__ : la classe de base construit les onglets et peut, par
        # ses propres appels, atteindre nos methodes (_rouvrir_si_vide, _appliquer_cadre).
        # Elles doivent trouver des attributs existants, meme vides.
        self._vues = []
        self._titres = {}
        #: identifiant de session, par vue — la cle que partage claude-window.sh.
        self._identifiants = {}
        #: dernier etat connu de chaque session (waiting / idle / busy / None).
        self._etats = {}
        #: derniere vitesse de depense appliquee, par vue (centimes/heure, ou None) —
        #: garde de changement, comme `_etats`, pour ne repeindre le tachymetre que
        #: lorsque la valeur a reellement bouge.
        self._dernieres_vitesses = {}
        #: dernieres fenetres globales appliquees au bandeau (cf. usage.fenetres()).
        #: None tant qu'aucun battement n'a encore rien lu.
        self._dernieres_fenetres = None
        #: le CoinDOnglet greffe sur chaque onglet, par vue — cf. _greffer_le_compteur.
        self._coins = {}
        #: le bouton « Nouvelle session » pose au-dessus du selecteur `claude -r`,
        #: par vue — retire des qu'une session reelle existe (cf. _poser_bandeau).
        self._bandeaux = {}
        #: la surveillance « le selecteur est-il referme ? » armee par un clic sur ce
        #: bouton, par vue : [minuteur, duree ecoulee en ms].
        self._relances = {}
        self._minuteur = None
        self._en_mosaique = False
        self._agrandi = False
        #: Ce que l'utilisateur VEUT voir quand le panneau est agrandi. Distinct de
        #: `_agrandi`, qui dit seulement l'etat du panneau : sans cette preference, un
        #: retour aux onglets serait aussitot annule par le prochain `_ajuster_affichage`,
        #: qui remettrait la mosaique puisque le panneau est toujours agrandi.
        self._mosaique_voulue = True

        super().__init__(name, plugin, parent)

        # `Tabs` de Spyder, et NON un QTabWidget ordinaire : c'est la classe que
        # PluginMainWidget._setup() cherche parmi ses enfants (findChildren(Tabs)). Quand
        # il en trouve une, il pose le coin du panneau — donc le menu burger — DANS la
        # barre d'onglets ; sinon le burger reste sur une ligne au-dessus. C'est ce qui
        # explique que la console IPython ait ses onglets et son burger sur la meme
        # ligne, et pas nous : rien a forcer, il suffit d'utiliser la bonne classe
        # (constate le 26/07/2026, apres mesure des coordonnees ecran).
        # MEME CONFIGURATION QUE LA CONSOLE IPYTHON, a l'identique (demande de
        # l'utilisateur, 26/07/2026 : « aligne le rendu du Terminal sur celui du panneau
        # Console IPython » — onglets plus hauts, croix de fermeture ailleurs).
        # Ce qui faisait la difference, c'est `setDocumentMode(True)` : sans lui les
        # onglets sont dessines en relief, plus hauts, et la croix ne tombe pas au meme
        # endroit. La console l'active (sauf sous macOS, ou il fait planter le detachement
        # du panneau — spyder-ide/spyder#561) ; on fait pareil.
        self._onglets = Tabs(self, rename_tabs=True, split_char="/", split_index=0)
        self._onglets.setDocumentMode(True)
        self._onglets.setMovable(True)
        # set_close_function : l'API de Spyder, celle qu'utilise la console. Elle fait
        # setTabsClosable(True) et branche tabCloseRequested — un seul appel au lieu de
        # deux, et surtout le meme chemin que le panneau de reference.
        self._onglets.set_close_function(self._fermer_onglet)
        self._appliquer_cadre(focus=False)

        # Des maintenant, avant toute session : le jeu de couleurs aux teintes de l'IDE
        # doit exister et son dossier etre declare avant la premiere lecture de la liste
        # par qtermwidget, qui la met en cache definitivement.
        self._habillage_cache = self._habillage()
        if konsole_view.DISPONIBLE:
            konsole_view.preparer_schema(
                konsole_view.profil_konsole(),
                self._habillage_cache.get("couleur_fond"),
                self._habillage_cache.get("couleur_texte"),
                self._habillage_cache.get("couleur_fond_intense"))

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._onglets)
        # Garde une reference sur CETTE disposition-ci : `self.layout()` renvoie celle de
        # PluginMainWidget, qui l'englobe (setLayout fait _main_layout.addLayout). La
        # mosaique s'ajoute a cote des onglets et n'a pas d'autre moyen de la retrouver.
        self._disposition = layout

        # ⚠ LES MARGES DU PANNEAU, AVANT setLayout. PluginMainWidget.setLayout ecrase les
        # marges qu'on vient de poser par les siennes (_margin_left/right/bottom) : les
        # regler ici est le SEUL moment ou cela tient.
        #
        # On reprend au pixel pres ce que fait la console IPython, qui retire un pixel a
        # gauche et a droite avec ce commentaire dans le code de Spyder : « Manually
        # adjust pane margins, don't know why this is necessary ». Sans cela notre cadre
        # tombait un pixel a droite du sien et un pixel plus haut — mesure en coordonnees
        # ECRAN, en basculant d'un panneau a l'autre (26/07/2026). Comparer les retraits
        # relatifs ne le montrait pas : ils etaient identiques de chaque cote.
        # UN PIXEL DE MOINS QUE LE DEFAUT, sur les trois cotes qui portent une marge.
        # La marge gauche fait exception en onglets verticaux : la classe de base la met
        # alors a zero, et il n'y a rien a en retirer.
        from spyder.utils.stylesheet import AppStyle
        self._margin_right = self._margin_bottom = AppStyle.MarginSize - 1
        if not self.get_conf("vertical_tabs", section="main"):
            self._margin_left = AppStyle.MarginSize - 1
        self.setLayout(layout)

        # LA MOSAIQUE, APRES `self._disposition` : elle s'y ajoute a cote des onglets, et
        # cette disposition-la n'existe que depuis quelques lignes.
        self._mosaique = Mosaique(self)
        self._mosaique.hide()
        self._disposition.addWidget(self._mosaique)
        self._mosaique.sig_reduire_demande.connect(self._quitter_la_mosaique)

        # LE BANDEAU DES DEUX JAUGES GLOBALES, TROISIEME ENFANT DE `_disposition` — ET NON
        # UN ENFANT DE L'UN OU L'AUTRE DES DEUX MODES. `_passer_en_mosaique` et
        # `_revenir_aux_onglets` ne font que masquer/afficher `_onglets` et `_mosaique` ;
        # un widget qui vit a cote d'eux, plutot que dans l'un des deux, est donc visible
        # A L'IDENTIQUE dans les deux modes SANS AUCUN CAS PARTICULIER a ecrire pour ca.
        # Demande de l'utilisateur (31/07/2026) : « on les ajoutera sur une ligne en
        # dessous des onglets ou de la mosaique du panneau Claude ».
        #
        # ⚠ `addSpacing`, PAS une marge posee sur `_bandeau` ou sur `_disposition` :
        # `PluginMainWidget.setLayout()` ecrase l'espacement du layout qu'on lui donne
        # (regle deja mesuree sur ce depot, cf. CLAUDE_spyder.md) — seul un espacement
        # EXPLICITE, insere comme un element du layout au lieu d'un reglage dessus, survit.
        # Meme constante que la marge du panneau (`AppStyle.MarginSize`, posee plus haut) :
        # un seul reglage d'espacement Spyder a suivre, pas deux qui pourraient diverger.
        self._disposition.addSpacing(AppStyle.MarginSize)
        self._bandeau = BandeauUsage(self)
        self._disposition.addWidget(self._bandeau)
        # La MEME icone que celle de l'action d'agrandissement quand le volet est deja
        # agrandi : `patch_spyder_maximize_icons.py` fait deja basculer cette action sur
        # `window_collapse`, et deux dessins differents pour un seul geste se lisent comme
        # deux gestes differents.
        self._mosaique.poser_icone_reduire(self.create_icon("window_collapse"))
        # Le « + » et la croix de la mosaique rebranchent sur ce qui EXISTE : le signal que
        # la classe utilise deja pour son propre « + », et l'arret de la vue, exactement ce
        # que fait la croix d'un onglet. Rien de neuf a cabler, donc un seul comportement a
        # maintenir par geste.
        self._mosaique.sig_nouvelle_demande.connect(self.sig_repertoire_demande)
        self._mosaique.sig_fermeture_demandee.connect(self._fermer_session)

        # Les jeux de couleurs des etats, ECRITS MAINTENANT — avant qu'une seule session
        # n'existe. qtermwidget met la liste des jeux en cache a sa premiere lecture, qui
        # a lieu au premier setColorScheme : un jeu ecrit apres coup ne serait jamais vu
        # (mesure du 26/07/2026, cf. konsole_view._dossier_declare).
        self._preparer_schemas_detat()

        # L'echelle du tachymetre, posee des maintenant : la mosaique la memorise et la
        # reapplique a chaque cellule creee (cf. Mosaique.poser_pleine_echelle) — poser une
        # constante avant la premiere session evite le meme piege que les jeux de couleur
        # ci-dessus, une valeur donnee apres coup a une seule cellule deja ouverte.
        self._mosaique.poser_pleine_echelle(self.vitesse_maximale())

    def _preparer_schemas_detat(self):
        """Un jeu de couleurs par etat d'instance, derive de celui de l'IDE."""
        if not konsole_view.DISPONIBLE:
            return
        profil = konsole_view.profil_konsole()
        texte = self._habillage_cache.get("couleur_texte")
        for etat, nom in etat_instances.SCHEMAS.items():
            couleur = etat_instances.COULEURS.get(etat)
            if nom and couleur:
                konsole_view.preparer_schema(profil, couleur, texte, couleur,
                                             nom_derive=nom)

    def _appliquer_cadre(self, focus):
        """Le cadre du panneau : gris au repos, BLEU VIF quand il a le clavier.

        C'est la convention de Spyder, et elle n'est POSEE NULLE PART dans une feuille de
        style : elle est ecrite en code, a chaque changement de focus (on la retrouve
        telle quelle dans spyder/widgets/emptymessage.py et browser.py, et le greffon
        Pyxel la reprend deja). Sans elle, le terminal n'a pas de contour et flotte dans
        le panneau — defaut signale par l'utilisateur le 26/07/2026.

        Le `padding` nous est propre : le terminal est OPAQUE et peindrait par-dessus les
        coins arrondis, comme l'ecran de jeu de Pyxel.
        """
        try:
            from spyder.utils.palette import SpyderPalette
        except ImportError:                     # hors Spyder (tests)
            return
        couleur = (SpyderPalette.COLOR_ACCENT_3 if focus
                   else SpyderPalette.COLOR_BACKGROUND_4)
        # Le cadre est porte par la VUE, pas par le conteneur d'onglets : avec
        # documentMode(True) — celui de la console IPython — le conteneur ne dessine plus
        # de cadre du tout. Et c'est de toute facon la que la console porte le sien : son
        # cadre est celui de son QTextEdit, pose par la feuille de style globale.
        # Posee sur LE PANNEAU, pas sur chaque vue : une feuille de style descend aux
        # enfants, donc les sessions ouvertes ensuite prennent le cadre sans qu'on ait a
        # y penser. C'est ce qui remplace la boucle sur les onglets et l'appel a rejouer
        # a chaque ouverture.
        self.setStyleSheet(
            "QFrame#terminal_smartos {"
            f" border: 1px solid {couleur};"
            f" border-radius: {SpyderPalette.SIZE_BORDER_RADIUS}; }}")
        # ⚠ EN MOSAIQUE, CETTE FEUILLE NE SUFFIT PLUS. Elle descend a TOUTES les vues, et
        # elles sont alors toutes affichees : le panneau annoncerait autant de sessions
        # actives qu'il a de cellules. On reprend donc la main vue par vue. En onglets, le
        # defaut ne se voyait pas — une seule vue est affichee a la fois.
        # `getattr` : cette methode est appelee depuis `__init__`, avant que la mosaique
        # n'existe.
        if getattr(self, "_en_mosaique", False):
            self._repartir_les_cadres()

    def _suivre_le_focus(self, _ancien, nouveau):
        """Bleu seulement si le clavier est DANS le panneau, gris des qu'il en sort."""
        dedans = bool(nouveau is not None
                      and (nouveau is self or self.isAncestorOf(nouveau)))
        self._appliquer_cadre(dedans)

    # ------------------------------------------------------- API PluginMainWidget

    def get_title(self):
        return _("Claude")

    def get_focus_widget(self):
        # Ce qui doit recevoir le clavier quand le dock est active : la session visible,
        # sinon chaque changement d'onglet obligerait a cliquer dans le terminal. En
        # mosaique il n'y a plus d'onglet courant — on prend la premiere cellule.
        if self._en_mosaique:
            return self._vues[0] if self._vues else self
        return self._onglets.currentWidget() or self._onglets

    def setup(self):
        # Copier, Coller et « Fermer la session » ont ete RETIRES de la barre le
        # 26/07/2026 a la demande de l'utilisateur : « ces boutons sont inutiles ».
        # Ils le sont en effet — le copier/coller se fait par Ctrl+Maj+C / Ctrl+Maj+V
        # (poses par le moteur, comme dans Konsole) ou par le menu contextuel, et une
        # session se ferme en tapant `exit` ou par la croix de son onglet.
        # Ce sont des ACTIONS, pas des widgets : les retirer ne laisse rien derriere
        # elles (un QToolButton ajoute comme WIDGET, lui, resterait dessine a l'origine
        # du panneau — piege deja paye sur ce depot).
        # Le bouton prend LA PLACE DU MENU BURGER (demande de l'utilisateur, 26/07/2026 :
        # « le menu burger est vide pour le panneau terminal, tu peux mettre le bouton
        # pour creer un nouveau terminal a la place »). C'est le coin de Spyder — celui
        # que PluginMainWidget pose dans la barre d'onglets des qu'il y trouve un `Tabs`.
        #
        # On y arrive par add_corner_widget, l'API prevue pour cela : le widget est
        # REPARENTE dans le coin, donc rien ne flotte hors layout. Ce qui remplace le
        # placement a la main essaye juste avant — position calculee sur tabRect, filtre
        # d'evenements pour suivre la barre — soit une trentaine de lignes en moins.
        #
        # ⚠ Le bouton doit venir de create_toolbutton, PAS d'un QToolButton nu : le coin
        # de Spyder exige un widget qui porte un `name`, et un QToolButton ordinaire n'en
        # a pas. L'erreur est une SpyderAPIError levee dans setup() — donc AVALEE, et le
        # greffon disparait purement et simplement de Spyder (constate le 26/07/2026 :
        # get_plugin('native_terminal') renvoyait None, sans un mot dans l'interface).
        # LE « + » EST FIXE, DANS LE COIN HAUT-DROIT, juste a gauche du bouton
        # d'agrandissement. Demande de l'utilisateur du 27/07/2026, qui revient sur celle
        # du 26 (« je prefere le voir suivre les onglets ») : « pour le "+" en mode onglet
        # normal, je prefere finalement l'avoir fixe juste a gauche de l'icone
        # d'agrandissement ».
        #
        # CE QUE CE CHOIX SUPPRIME, et c'est l'essentiel : le suivi demandait de calculer
        # la position sur `tabRect`, un filtre d'evenements pour la refaire a chaque
        # redimensionnement, une garde contre la re-entrance (chaque placement produisant
        # les evenements qu'on ecoute), et — decouvert le 27/07/2026 — une bascule vers ce
        # meme coin des que la barre debordait, faute de quoi le bouton se posait SUR les
        # fleches de defilement. Une soixantaine de lignes, et deux emplacements a tenir
        # d'accord. Le coin, lui, est gere par Qt : il lui reserve la place et retrecit la
        # barre d'autant, quel que soit le nombre d'onglets.
        #
        # ⚠ Le bouton doit venir de create_toolbutton, PAS d'un QToolButton nu : le coin
        # de Spyder exige un widget qui porte un `name`, et un QToolButton ordinaire n'en
        # a pas. L'erreur est une SpyderAPIError levee dans setup() — donc AVALEE, et le
        # greffon disparait purement et simplement de Spyder (constate le 26/07/2026 :
        # get_plugin('native_terminal') renvoyait None, sans un mot dans l'interface).
        self._bouton_nouveau = self.create_toolbutton(
            "claude_pane_new_button",
            text=_("Nouvelle instance Claude"),
            icon=qta.icon("mdi.plus", color=ima.MAIN_FG_COLOR),
            tip=_("Ouvre une instance Claude dans le repertoire courant de Spyder."),
            triggered=self.sig_repertoire_demande,
        )
        self._bouton_nouveau.setFocusPolicy(Qt.NoFocus)
        self._poser_bouton_nouveau_dans_le_coin()

        # La croix de Spyder, pas celle de Qt : `fileclose` est l'icone que porte
        # `CloseTabButton` sur les onglets (spyder/widgets/tabs.py).
        self._mosaique.poser_icone_fermer(self.create_icon("fileclose"))
        self._mosaique.poser_icone_nouveau(self._bouton_nouveau.icon())

        # LE BOUTON DE DISPOSITION : mosaique ou onglets, dans le panneau agrandi.
        # DEUX BOUTONS ET NON UN SEUL DEPLACE : la mosaique cache la barre d'onglets, donc
        # un bouton unique devrait faire l'aller-retour entre le coin et la ligne de titre
        # a chaque bascule. Chaque mode porte le sien, et tous deux appellent
        # `_basculer_disposition`.
        self._bouton_disposition = self.create_toolbutton(
            "claude_pane_layout_button",
            text=_("Disposition"),
            icon=qta.icon("mdi.view-grid", color=ima.MAIN_FG_COLOR),
            tip=_("Étaler les instances en mosaïque"),
            triggered=self._basculer_disposition,
        )
        self._bouton_disposition.setFocusPolicy(Qt.NoFocus)
        self._poser_bouton_disposition_dans_le_coin()
        # ⚠ RETOURNEE HORIZONTALEMENT (`hflip`), demande de l'utilisateur du 31/07/2026.
        # `mdi.tab` dessine un onglet decale a GAUCHE ; le bouton vit dans le coin haut-DROIT
        # de la mosaique, et l'onglet pointait donc vers l'exterieur du panneau. Retournee,
        # la forme rentre dans le panneau, dans le sens du geste qu'elle declenche.
        # `hflip` est une option de qtawesome, pas une seconde icone a trouver : la forme
        # reste exactement la meme, et suivra une eventuelle mise a jour de la fonte.
        self._mosaique.poser_icone_disposition(
            qta.icon("mdi.tab", color=ima.MAIN_FG_COLOR, hflip=True))
        self._mosaique.sig_disposition_demandee.connect(self._basculer_disposition)
        self._ajuster_bouton_disposition()
        # Et le burger disparait : son menu est VIDE pour ce panneau (mesure du
        # 26/07/2026 : zero entree hors separateurs), donc il n'ouvre rien. Le filet
        # general de patch_spyder_dock_actions.py masque bien les burgers vides, mais il
        # passe AVANT que notre coin ne soit peuple ; on refait donc le test une fois la
        # boucle d'evenements rendue, quand le menu a sa forme definitive.
        QTimer.singleShot(0, self._masquer_burger_vide)
        # Le focus se suit au niveau de l'application : le terminal donne le clavier a
        # un widget interne de QTermWidget, dont on n'a pas d'evenement direct ici.
        QApplication.instance().focusChanged.connect(self._suivre_le_focus)

        # LE BATTEMENT DU REGISTRE. Demarre ici plutot que dans __init__ : un minuteur
        # lance avant que le panneau ne soit monte battrait dans le vide pendant tout le
        # demarrage de Spyder.
        self._minuteur = QTimer(self)
        self._minuteur.setInterval(self.PERIODE_SONDAGE)
        self._minuteur.timeout.connect(self.relire_le_registre)
        self._minuteur.start()
        self.update_actions()

    def showEvent(self, evenement):  # noqa: N802 - API Qt
        """Le burger vide est re-masque a chaque affichage du panneau.

        Une seule passe ne tient pas : Spyder rend son coin a plusieurs moments de
        l'enregistrement des greffons, et la derniere ecriture gagne. Mesure du
        26/07/2026 : appelee a la main, la methode masque bien le bouton ; appelee
        seulement au `setup()`, elle etait defaite ensuite.
        """
        super().showEvent(evenement)
        self._masquer_burger_vide()

    def _masquer_burger_vide(self):
        """Masque le bouton d'options, et le REMASQUE si Spyder le rallume.

        Le simple setVisible(False) ne tient pas : mesure du 26/07/2026 — appele a la
        main il masque bien, mais quelque chose dans le montage de Spyder rallume le
        bouton apres coup, quel que soit le moment ou l'on s'y prend (setup, showEvent,
        fenetre principale visible). Plutot que de courir apres le bon instant, on pose
        un garde-fou : un filtre d'evenements qui remasque a chaque tentative
        d'affichage. Deterministe, et sans minuterie a calibrer.
        """
        bouton = getattr(self, "_options_button", None)
        if bouton is None:
            return
        if not getattr(self, "_garde_burger", False):
            bouton.installEventFilter(self)
            self._garde_burger = True
        bouton.setVisible(False)

    #: De combien le coin d'un QTabWidget deborde a droite de son conteneur, en pixels
    #: logiques. MESURE le 27/07/2026 (conteneur jusqu'a 716, coin jusqu'a 717), pas
    #: devine : c'est une constante de placement de Qt, pas un reglage esthetique. Si une
    #: version future cessait de deborder, ce nombre deviendrait un retrait injustifie —
    #: le scenario d'alignement le dirait aussitot, en montrant l'ecart passer a -1.
    DEBORDEMENT_DU_COIN = 1

    def eventFilter(self, objet, evenement):  # noqa: N802 - API Qt
        """Un seul garde-fou : le burger vide reste masque.

        Il en gardait un second — replacer le « + » a chaque redimensionnement de la barre
        d'onglets — devenu inutile le jour ou ce bouton est passe dans le coin : Qt l'y
        dispose lui-meme. Le filtre n'est donc plus installe QUE sur le burger (les deux
        poses sur les onglets ont ete retirees le 31/07/2026, sans effet mesurable).
        """
        if (objet is getattr(self, "_options_button", None)
                and evenement.type() == QEvent.Show):
            objet.setVisible(False)
            return True
        return super().eventFilter(objet, evenement)

    def _coin_des_onglets(self):
        """Le widget de coin haut-droit de la barre d'onglets, ou None."""
        return self._onglets.cornerWidget(Qt.TopRightCorner)

    def _poser_bouton_nouveau_dans_le_coin(self, reessaye=False):
        """Pose le « + » dans le coin, a gauche du bouton d'agrandissement.

        L'ORDRE VIENT SEUL, et c'est pourquoi il n'y a rien a calculer : notre bouton est
        pose au `setup()` du panneau, le bouton d'agrandissement l'est plus tard par
        patch_spyder_pane_maximize_button.py (differe d'un tour de boucle apres
        l'affichage de la fenetre). Ajouter chacun en fin de barre les met donc dans cet
        ordre-la — « + » puis agrandissement — qui est celui demande.

        ⚠ LE COIN PEUT NE PAS ENCORE EXISTER a cet instant : Spyder le cree au fil du
        montage du panneau. On rejoue alors UNE fois, un tour de boucle plus tard. Une
        seule, et non une boucle : si le coin n'est jamais venu, mieux vaut un bouton
        absent qu'un panneau qui se rappelle indefiniment.
        """
        coin = self._coin_des_onglets()
        if coin is None or not hasattr(coin, "addWidget"):
            if not reessaye:
                        QTimer.singleShot(
                    0, lambda: self._poser_bouton_nouveau_dans_le_coin(True))
            return
        coin.addWidget(self._bouton_nouveau)
        self._bouton_nouveau.show()
        self._rentrer_le_coin_dans_son_conteneur(coin)

    def _rentrer_le_coin_dans_son_conteneur(self, coin):
        """Le coin d'un QTabWidget DEBORDE d'un pixel a droite ; on le rentre.

        Mesure du 27/07/2026 : le conteneur d'onglets s'arrete a x=716, son coin va
        jusqu'a 717. Qt autorise ce debordement, et rien ne s'en plaignait — jusqu'a ce
        qu'on veuille aligner sur ces boutons ceux de la mosaique, qui, eux, respectent
        leurs bornes. Le decalage d'un pixel etait donc du cote des onglets.

        On avait d'abord cherche a faire DEBORDER la mosaique d'autant ; c'est
        l'utilisateur qui a retourne la question — « on ne peut pas faire en sorte que
        cornerWidget ne deborde pas ? ». C'est plus simple, et surtout ca corrige la cause
        au lieu de la copier : la voie inverse aurait demande de sortir des boutons de leur
        layout, c'est-a-dire le piege des boutons orphelins que ce depot paye depuis des
        mois.
        """
        marges = coin.contentsMargins()
        coin.setContentsMargins(marges.left(), marges.top(),
                                marges.right() + self.DEBORDEMENT_DU_COIN,
                                marges.bottom())


    # =========================================================================
    # MOSAIQUE : etaler les sessions quand le panneau est agrandi
    # =========================================================================
    # Ecrite d'abord pour le panneau Claude, RECOPIEE ici le 31/07/2026 — recopiee et non
    # partagee, a la demande explicite de l'utilisateur : « si le panneau Claude est pour
    # l'instant similaire a celui de Terminal, il va pouvoir s'en eloigner par la suite. Je
    # veux 2 greffons independants. » Les deux fichiers sont donc jumeaux AUJOURD'HUI et
    # libres de diverger demain, sans qu'un changement ici n'aille surprendre l'autre.
    #
    # ⚠ CE QUE CELA COUTE, ET QU'IL FAUT SAVOIR AVANT DE CORRIGER UN DEFAUT ICI : le meme
    # defaut est probablement dans spyder_claude/spyder/main_widget.py. Tant que les deux
    # n'ont pas diverge, un correctif se porte des deux cotes — c'est le prix assume de
    # l'independance, pas un oubli.

    def _rafraichir_letat_affiche(self):
        """Repose sur l'affichage courant ce qui depend du mode.

        Appelee apres tout changement de mode : les onglets et les cellules sont deux
        supports differents, et celui qui vient d'apparaitre ne porte encore rien.

        Les poignees se teintent ICI, et non aux trois endroits qui appellent `disposer` :
        cette methode suit chacun d'eux, et un meme reglage ecrit trois fois devient faux a
        deux d'entre eux le jour ou il change.

        MEME RAISON POUR LA VITESSE : `_appliquer_vitesse` n'est normalement rappelee que
        lorsque `usage.vitesses_par_onglet()` rend une valeur DIFFERENTE de la derniere —
        un garde de changement necessaire pour ne pas repeindre en pure perte a chaque
        battement (cf. `_rafraichir_la_consommation`). Mais juste apres une bascule de
        mode, la cellule de mosaique qui vient de naitre n'a JAMAIS recu la vitesse en
        cours : si l'echantillon est encore frais (age <= FENETRE_MIN, cf. usage.py), la
        valeur decrue reste EXACTEMENT la meme d'un battement a l'autre, et le garde
        supprimerait alors toute reapplication pendant jusqu'a une minute — le cadran
        resterait eteint alors qu'une vitesse est bel et bien connue.
        """
        self._mosaique.poser_couleur_poignees(
            self._habillage_cache.get("couleur_fond"))
        for vue in self._vues:
            self._appliquer_etat(vue, self._etats.get(vue))
            self._appliquer_vitesse(vue, self._dernieres_vitesses.get(vue))

    def set_maximized_state(self, state):
        """Agrandir le panneau etale les onglets en mosaique ; le reduire les rassemble.

        C'est le seul point d'accroche : le greffon Layout appelle cette methode a chaque
        bascule (spyder/plugins/layout/plugin.py). Il n'existe aucun signal public pour
        cela.
        """
        super().set_maximized_state(state)
        self._agrandi = bool(state)
        self._ajuster_affichage()

    def sessions(self):
        """Les vues ouvertes, dans l'ordre d'affichage."""
        return list(self._vues)

    def _oublier(self, vue):
        """Tout ce qui est indexe par la vue se purge ICI, en un seul endroit.

        Des dictionnaires plutot qu'un objet de session : ils sont lus a des rythmes
        differents (les titres a chaque OSC, les etats et la vitesse a chaque battement du
        registre) et aucun code n'a besoin de tous a la fois. Ce qui compte est qu'ils se
        vident ensemble — une vue oubliee d'un seul cote laisserait un identifiant fantome
        dans le registre, donc une couleur ou une vitesse posee sur un onglet detruit.
        """
        if vue in self._vues:
            self._vues.remove(vue)
        self._titres.pop(vue, None)
        self._identifiants.pop(vue, None)
        self._etats.pop(vue, None)
        self._dernieres_vitesses.pop(vue, None)
        # Le bouton « Nouvelle session » est enfant de la vue, detruit avec elle : seul
        # le dictionnaire se purge. Le minuteur de relance, lui, a le panneau pour
        # parent — on l'arrete explicitement.
        self._bandeaux.pop(vue, None)
        self._arreter_relance(vue)
        # ⚠ `deleteLater()`, PAS SEULEMENT `pop` : fermer un onglet ne detruit QUE son
        # widget de page. `TabBar.tabRemoved` (spyder/widgets/tabs.py) renumerote les
        # boutons des onglets restants mais ne detruit jamais celui de l'onglet ferme —
        # sans cet appel, le CoinDOnglet (et le Compteur, et la croix Spyder reparentee
        # dedans) restait un enfant orphelin de la barre d'onglets a chaque fermeture,
        # en mode onglets. `_rafraichir_les_compteurs` le fait deja symetriquement quand
        # un glisser-deposer remplace un CoinDOnglet par un autre.
        coin = self._coins.pop(vue, None)
        if coin is not None:
            coin.deleteLater()



    def _elements(self):
        return [(vue, self._titres.get(vue, "")) for vue in self._vues]

    def _ajuster_affichage(self):
        """Mosaique des que le panneau est agrandi, quel que soit le nombre de sessions.

        ⚠ IL Y AVAIT UN SEUIL A DEUX SESSIONS, ET IL A ETE RETIRE (27/07/2026). Sa raison
        d'etre : « a une seule session, la mosaique n'apporte rien qu'un bandeau de titre
        en plus ». Cette raison a disparu avec le bandeau — les boutons vivent maintenant
        dans la ligne de titre des cellules et ne coutent aucune hauteur. Le seuil ne
        produisait plus qu'une incoherence, que l'utilisateur a relevee : « lorsqu'il n'y a
        qu'une seule session, elle apparait sous forme d'onglet dans la mosaique, ce n'est
        pas ce que je veux, je veux un affichage consistant ». Agrandi, on est en mosaique.

        Le test est refait a chaque ouverture et a chaque fermeture, et pas seulement a la
        bascule d'agrandissement — sinon ouvrir une instance dans un panneau deja agrandi
        ne changerait rien a l'affichage.

        `_mosaique_voulue` est la preference de l'utilisateur, que le bouton de disposition
        renverse : agrandi, on lui montre ce qu'il a demande, mosaique par defaut.
        """
        self.basculer_mosaique(
            self._agrandi and self._mosaique_voulue and bool(self._vues))
        self._ajuster_bouton_disposition()

    def en_mosaique(self):
        return self._en_mosaique

    def basculer_mosaique(self, actif=None):
        """Passe en mosaique ou revient aux onglets. Publique : pilotable par --gui-exec."""
        if actif is None:
            actif = not self._en_mosaique
        actif = bool(actif)
        if actif == self._en_mosaique:
            if actif:
                # Deja en mosaique, mais le nombre de sessions a change : on redispose.
                self._mosaique.disposer(self._elements())
                self._rafraichir_letat_affiche()
            return
        if actif:
            self._passer_en_mosaique()
        else:
            self._revenir_aux_onglets()

    def _action_agrandissement(self):
        """L'action « Agrandir le volet courant » du greffon Layout, ou None.

        Retrouvee a la demande et jamais mise en cache : les actions de Spyder sont
        enregistrees au fil du montage des greffons, et une reference prise dans notre
        constructeur pourrait etre anterieure a la sienne.
        """
        try:
            return self.get_action(self.ACTION_AGRANDIR, plugin="layout")
        except Exception:
            # Nom d'action disparu a une montee de version : on le saura par le repli
            # ci-dessous, qui replie quand meme la mosaique.
            return None

    def _repartir_les_cadres(self):
        """Bleu sur la vue qui a le clavier, gris sur les autres.

        ⚠ `self.focusWidget()` ET NON `QApplication.focusWidget()`. Le second vaut None des
        que la FENETRE n'est pas activee par le gestionnaire de fenetres : toutes les vues
        etaient alors grises, y compris celle qui avait bel et bien le clavier dans le
        panneau (mesure du 27/07/2026 — zero cadre bleu la ou on en attendait un).
        La question utile n'est pas « l'application a-t-elle le focus », c'est « quelle vue
        DE CE PANNEAU l'a » : le focus interne d'un sous-arbre survit a la desactivation de
        la fenetre, et c'est bien ce qu'on veut montrer.
        """
        try:
            from spyder.utils.palette import SpyderPalette
        except ImportError:                     # hors Spyder (tests)
            return
        actif = self.focusWidget()
        for vue in self._vues:
            a_le_clavier = bool(actif is not None
                                and (vue is actif or vue.isAncestorOf(actif)))
            couleur = (SpyderPalette.COLOR_ACCENT_3 if a_le_clavier
                       else SpyderPalette.COLOR_BACKGROUND_4)
            vue.setStyleSheet(
                "QFrame#terminal_smartos {"
                f" border: 1px solid {couleur};"
                f" border-radius: {SpyderPalette.SIZE_BORDER_RADIUS}; }}")

    def _rendre_les_cadres_au_panneau(self):
        """Efface les feuilles par vue, pour que celle du panneau reprenne la main.

        ⚠ INDISPENSABLE AU RETOUR AUX ONGLETS : une feuille posee sur la vue l'emporte sur
        celle du panneau, donc les vues garderaient le gris qu'on leur a mis en mosaique et
        l'onglet actif n'aurait plus jamais son cadre bleu.
        """
        for vue in self._vues:
            vue.setStyleSheet("")

    def _fermer_session(self, vue):
        """La croix d'une cellule : on ARRETE la session, et le reste suit tout seul.

        Rien d'autre a faire ici, et c'est voulu : `arreter()` fait sortir le shell, la vue
        emet `sig_termine`, et `_session_terminee` — deja ecrit pour le cas ou une instance
        se termine d'elle-meme — defait la cellule, jette la vue et redispose la mosaique.
        Refermer la cellule ici en plus, ce serait ecrire une seconde fois un chemin qui
        existe, avec le risque qu'ils divergent.

        C'est aussi ce que fait la croix d'un ONGLET dans la classe de base : meme geste,
        meme suite.
        """
        if vue is not None and hasattr(vue, "arreter"):
            vue.arreter()

    def _poser_bouton_disposition_dans_le_coin(self, reessaye=False):
        """A gauche du « + », donc a gauche aussi du bouton d'agrandissement.

        Meme mecanique que le « + » de la classe de base — y compris la seule seconde
        tentative si le coin n'existe pas encore, Spyder le creant au fil du montage.
        L'ordre vient de l'ordre des poses : disposition, puis « + » (deja pose par
        `super().setup()`), puis agrandissement (pose plus tard par le patch). On insere
        donc en tete plutot qu'en fin.
        """
        coin = self._coin_des_onglets()
        if coin is None or not hasattr(coin, "insertWidget"):
            if not reessaye:
                QTimer.singleShot(
                    0, lambda: self._poser_bouton_disposition_dans_le_coin(True))
            return
        actions = coin.actions()
        if actions:
            self._action_disposition = coin.insertWidget(
                actions[0], self._bouton_disposition)
        else:
            self._action_disposition = coin.addWidget(self._bouton_disposition)
        # ⚠ APRES LA POSE, ET PAS AVANT : `insertWidget` REAFFICHE le widget qu'on lui
        # donne. Regle une seule fois a la fin de `setup()`, la visibilite etait defaite un
        # tour de boucle plus tard, quand la pose differee s'executait — le bouton
        # apparaissait dans un panneau non agrandi (mesure du 27/07/2026).
        self._ajuster_bouton_disposition()

    def _basculer_disposition(self):
        """Le bouton mosaique/onglets : renverse la preference, puis reaffiche.

        On ne touche PAS a l'agrandissement : c'est un choix de disposition DANS le
        panneau agrandi, pas un moyen d'en sortir — celui-la, c'est le bouton de
        reduction.
        """
        self._mosaique_voulue = not self._mosaique_voulue
        self._ajuster_affichage()

    def _ajuster_bouton_disposition(self):
        """Le bouton du coin ne sert QU'EN ONGLETS, et dans un panneau agrandi.

        Deux conditions, chacune pour sa raison :
          - AGRANDI, parce que sans agrandissement il n'y a qu'une disposition possible :
            le bouton proposerait un etat inatteignable ;
          - PAS EN MOSAIQUE, parce que la mosaique cache la barre d'onglets, donc le coin
            et ce bouton avec. C'est le bouton de la mosaique qui prend alors le relais.
            Le masquer explicitement ne change rien a l'ecran — Qt s'en charge — mais dit
            l'intention, et evite qu'une sonde le croie disponible.

        SON ICONE NE BASCULE PAS. Chacun des deux boutons a un seul role : celui-ci mene a
        la mosaique, celui de la mosaique mene aux onglets. Une premiere version faisait
        alterner l'icone de celui-ci selon l'etat ; c'etait du code sans emploi, puisqu'il
        n'est jamais affiche en mosaique.
        """
        bouton = getattr(self, "_bouton_disposition", None)
        if bouton is None:
            return
        visible = self._agrandi and not self._en_mosaique
        bouton.setVisible(visible)
        # ⚠ DANS UNE BARRE D'OUTILS, C'EST L'ACTION QUI PORTE LA VISIBILITE. Masquer le
        # seul widget ne tient pas : la barre le reaffiche en se remettant en page, et le
        # bouton restait visible dans un panneau non agrandi (mesure du 27/07/2026, apres
        # une premiere correction qui ne touchait que le widget).
        action = getattr(self, "_action_disposition", None)
        if action is not None:
            action.setVisible(visible)

    def _quitter_la_mosaique(self):
        """Le bouton de la mosaique : le MEME geste que le bouton d'agrandissement.

        ⚠ CE N'EST PAS `sig_unmaximize_plugin_requested`, ESSAYE ET MESURE INOPERANT ICI
        (27/07/2026). Le signal existe bien sur PluginMainWidget et la fenetre principale
        le relaie vers `layouts.unmaximize_dockwidget()`, mais emis depuis ce panneau il
        n'a rien produit. Le defaut se voyait a l'ecran, et l'utilisateur l'a decrit
        exactement : « la reduction passe par un etat intermediaire, qui est le plein
        ecran mais avec des onglets au lieu de la mosaique ; on est oblige de reduire deux
        fois ». Ce qu'on voyait, c'etait le REPLI qui s'executait — la mosaique se refermait
        pendant que le panneau restait agrandi.

        Le geste correct est celui du bouton d'agrandissement : l'action
        `LayoutContainerActions.MaximizeCurrentDockwidget` est COCHABLE, et la declencher
        quand elle est cochee restaure la disposition. Le retour aux onglets nous revient
        alors par `set_maximized_state(False)`, notre point d'accroche habituel : un seul
        chemin, quel que soit le bouton clique, donc un seul comportement a maintenir.

        LE REPLI RESTE, et il a un cas reel : `basculer_mosaique(True)` est une API
        PUBLIQUE, faite pour etre pilotee par les scenarios `--actions`. Elle etale les
        sessions sans rien dire a la fenetre principale — l'action n'est alors pas cochee,
        il n'y a rien a restaurer, et sans ce repli le bouton ne repondrait pas.
        """
        action = self._action_agrandissement()
        if action is not None and action.isChecked():
            action.trigger()
            return
        self.basculer_mosaique(False)

    def _relever_les_espacements_du_coin(self):
        """Mesure les blancs entre les boutons du coin, et les donne a la mosaique.

        POURQUOI MESURER PLUTOT QUE FIXER : l'utilisateur veut que les trois boutons de
        droite tombent au meme endroit dans les deux modes (27/07/2026). Or QToolBar
        n'espace pas ses boutons regulierement — 8 px puis 4 au releve du 27/07/2026 — et
        rien ne garantit ces valeurs d'une version de Qt a l'autre. On lit donc la
        geometrie sur les objets reels, comme le veut la regle du depot : une formule
        recalculee se trompe des que l'amont bouge, une lecture suit.

        A APPELER TANT QUE LA BARRE D'ONGLETS EST ENCORE AFFICHEE : en mosaique elle est
        cachee, et les positions relevees seraient celles du dernier affichage — justes par
        chance tant que rien n'a change, fausses des que la largeur du panneau bouge.
        """
        boutons = [b for b in (getattr(self, "_bouton_disposition", None),
                               getattr(self, "_bouton_nouveau", None),
                               getattr(self, "_smartos_bouton_agrandir", None))
                   if b is not None and b.isVisible()]
        if len(boutons) < 2:
            return
        gauches = [b.mapToGlobal(b.rect().topLeft()).x() for b in boutons]
        ecarts = [gauches[i + 1] - (gauches[i] + boutons[i].width())
                  for i in range(len(boutons) - 1)]
        self._mosaique.poser_espacements(ecarts)
        # ⚠ LA HAUTEUR AUSSI, et pour une raison qui ne se voit pas sur les boutons :
        # l'icone est CENTREE, donc un pixel de hauteur en plus la descend d'un pixel.
        # Les boutons du coin font 43 de haut la ou les notres en faisaient 44 — boutons
        # alignes, dessins decales (releve du 27/07/2026, signale par l'utilisateur alors
        # que ma mesure disait dx=0 dy=0).
        self._mosaique.poser_hauteur_des_boutons(boutons[0].height())

    def _relever_la_croix_dun_onglet(self):
        """Mesure la croix de fermeture d'un onglet, et la donne a la mosaique.

        Elle appartient a Spyder (`CloseTabButton`, spyder/widgets/tabs.py) : sa taille
        suit la police et le theme, et rien ne dit qu'elle restera celle d'aujourd'hui.
        On la LIT donc sur l'onglet, comme on lit deja l'espacement et la hauteur des
        boutons du coin — plutot que d'inscrire 18x22 quelque part et de le decouvrir faux
        un jour.

        A APPELER TANT QUE LES ONGLETS SONT AFFICHES : en mosaique la barre est cachee et
        ses boutons n'ont plus de geometrie a jour.

        ⚠ LECTURE DIRECTE PAR `tabButton`, PAS PAR GEOMETRIE — DIVERGENCE DELIBEREE d'avec
        le panneau jumeau spyder_konsole (qui n'a pas de tachymetre : SON
        heuristique par geometrie reste correcte, et n'a PAS a etre corrigee la-bas). Une
        premiere version cherchait la croix par geometrie
        (`rect.contains(bouton.geometry().center())`) : une fois la croix reparentee DANS
        un CoinDOnglet (cf. _greffer_le_compteur), sa geometrie devient relative a ce
        conteneur et non plus a la barre d'onglets — la recherche comparait alors deux
        reperes differents, ne trouvait plus rien, et la mosaique gardait en silence la
        taille de croix du style Qt.
        """
        barre = self._onglets.tabBar()
        if not barre.count():
            return
        widget = barre.tabButton(0, QTabBar.RightSide)
        if widget is None:
            return
        bouton = widget.croix() if isinstance(widget, CoinDOnglet) else widget
        if bouton is None:
            return
        self._mosaique.poser_geometrie_croix(bouton.width(), bouton.height())

    def _passer_en_mosaique(self):
        self._relever_les_espacements_du_coin()
        self._relever_la_croix_dun_onglet()
        for index in reversed(range(self._onglets.count())):
            widget = self._onglets.widget(index)
            self._onglets.removeTab(index)
            if widget not in self._vues:
                # L'onglet d'attente : rien a preserver, il se refabrique.
                widget.setParent(None)
                widget.deleteLater()
        self._onglets.hide()
        self._mosaique.show()
        self._mosaique.disposer(self._elements())
        self._en_mosaique = True
        self._rafraichir_letat_affiche()
        self._repartir_les_cadres()

    def _revenir_aux_onglets(self):
        self._rendre_les_cadres_au_panneau()
        self._mosaique.liberer()
        self._mosaique.hide()
        self._onglets.show()
        for vue in self._vues:
            titre = self._titres.get(vue, "")
            index = self._onglets.addTab(vue, self._titre_court(titre) or _("Claude"))
            self._onglets.setTabToolTip(index, titre)
        self._en_mosaique = False
        if self._onglets.count():
            self._onglets.setCurrentIndex(0)
        self._rafraichir_letat_affiche()

    def update_actions(self):
        # Rien a activer ou desactiver : le seul bouton du panneau est toujours
        # disponible. On en profite pour re-masquer le burger vide — Spyder rend son coin
        # a plusieurs moments, et une seule passe differee ne tenait pas.
        self._masquer_burger_vide()

    def on_close(self):
        """Termine TOUTES les instances lancees par le panneau, dans les deux modes.

        Sans cela, fermer Spyder laisse des shells orphelins rattaches a un pty dont
        plus personne ne lit la sortie — ils survivent a l'application et n'apparaissent
        nulle part.

        ⚠ ON PARCOURT LES SESSIONS, PAS LES ONGLETS : en mosaique la barre est vide par
        construction, et parcourir les onglets ne fermerait rien du tout.
        """
        if self._minuteur is not None:
            self._minuteur.stop()
        for vue in list(self._vues):
            if hasattr(vue, "arreter"):
                vue.arreter(force=True)

    # ------------------------------------------------------------------ sessions

    def commande_claude(self):
        """Ce qu'on tape dans le shell une fois ouvert."""
        return self.get_conf("commande", self.COMMANDE_DEFAUT) or self.COMMANDE_DEFAUT

    def vitesse_maximale(self):
        """Pleine echelle du tachymetre, en dollars/heure."""
        return (self.get_conf("vitesse_maximale", self.VITESSE_MAXIMALE_DEFAUT)
               or self.VITESSE_MAXIMALE_DEFAUT)

    def identifiant_de(self, vue):
        """L'identifiant de session d'une vue. Publique : sert aux tests et au diagnostic."""
        return self._identifiants.get(vue)

    def ouvrir_terminal(self, repertoire=None, commande=None, environnement=None):
        """Cree un onglet, y lance un shell, puis y tape la commande de Claude.

        Le nom est celui du panneau de terminaux dont ce greffon reprend la mecanique ; le
        greffon expose `ouvrir_claude`, qui se lit mieux dans un scenario de test.

        `environnement` ajoute des variables a celles du profil : c'est par la qu'un
        appelant marque ses sessions, seul moyen pour un outil exterieur de reconnaitre
        une session hebergee par un panneau plutot que par une fenetre.

        Un seul moteur depuis le 26/07/2026 : QTermWidget. L'emulateur VT en Python pur
        ecrit le matin meme a ete SUPPRIME sur demande de l'utilisateur — il ne servait
        plus qu'a RaspberryPi5, plateforme sans roue PySide6 et jamais testee, au prix de
        sept cents lignes et d'une couche de selection de moteur a maintenir. Quand le
        binding manque, le panneau le DIT (cf. _afficher_absence_du_binding).
        """
        if not konsole_view.DISPONIBLE:
            # Le binding manque : on le DIT dans le panneau plutot que d'echouer en
            # silence. Spyder avale les exceptions de greffon — sans ce message, le
            # panneau serait simplement vide et personne ne saurait pourquoi.
            self._afficher_absence_du_binding()
            return None
        self._retirer_etat_vide()
        # L'IDENTITE DE LA SESSION, POSEE AVANT LE DEMARRAGE : les variables doivent etre
        # dans l'environnement du shell des sa naissance, sinon les hooks lances par la
        # premiere commande ne verraient rien.
        identifiant = uuid.uuid4().hex[:12]
        variables = etat_instances.variables_de_session(identifiant, os.getpid())
        if environnement:
            variables.update(environnement)

        vue = VueKonsole(self._onglets, **self._habillage_cache)
        titre = _("Claude")
        if repertoire:
            titre = "%s : %s" % (_("Claude"),
                                 os.path.basename(repertoire.rstrip("/")) or "/")
        index = self._onglets.addTab(vue, self._titre_court(titre))
        self._onglets.setTabToolTip(index, titre)
        self._onglets.setCurrentIndex(index)
        # ⚠ LA LISTE DES SESSIONS SE TIENT ICI, ET ELLE EST LE SEUL ETAT VRAI DANS LES DEUX
        # MODES : en mosaique la barre d'onglets est vide, donc `self._onglets.count()` ne
        # dit plus rien. `_ajuster_affichage` et `_rouvrir_si_vide` la lisent tous les deux.
        self._vues.append(vue)
        self._titres[vue] = titre
        self._identifiants[vue] = identifiant

        vue.sig_titre.connect(lambda texte, v=vue: self._titre_change(v, texte))
        vue.sig_termine.connect(lambda code, v=vue: self._session_terminee(v, code))
        import time
        self._debut_derniere_session = time.monotonic()
        vue.demarrer(commande=commande, repertoire=repertoire,
                     environnement=variables)
        vue.envoyer(self.commande_claude() + "\n")
        self._poser_bandeau(vue)
        vue.setFocus()
        self._ajuster_affichage()
        self.update_actions()
        return vue

    #: Periode et plafond de la surveillance « le selecteur est-il referme ? », en ms.
    PERIODE_RELANCE = 100
    PLAFOND_RELANCE = 10000

    def _commande_est_le_selecteur(self):
        """Vrai si la commande tapee a l'ouverture est le selecteur de sessions."""
        return bool({"-r", "--resume"} & set(self.commande_claude().split()))

    def _commande_nouvelle_session(self):
        """La commande configuree, sans son option de reprise : une session neuve."""
        mots = [m for m in self.commande_claude().split()
                if m not in ("-r", "--resume")]
        return " ".join(mots) or "claude"

    def _poser_bandeau(self, vue):
        """Le bouton « Nouvelle session », en pleine largeur au-dessus du terminal.

        Demande de l'utilisateur (04/10/2026) : l'onglet s'ouvre sur `claude -r` pour
        montrer d'emblee les sessions reprenables, mais ce selecteur n'a aucune entree
        « nouvelle session » (verifie dans la doc officielle de Claude Code). Le bouton
        comble ce manque, et disparait des qu'une session existe — choisie dans le
        selecteur (le registre d'etat la revele, cf. relire_le_registre) ou ouverte par
        le bouton lui-meme.

        Insere DANS la vue (son layout vertical, au-dessus du terminal), pas dans le
        panneau : le terminal se reduit d'autant, et onglets comme mosaique deplacent la
        vue avec son bouton sans rien savoir de lui. Rien n'est pose si la commande
        configuree n'est pas le selecteur : Echap partirait alors dans une session en
        cours.
        """
        if not self._commande_est_le_selecteur():
            return
        bouton = QPushButton(_("Nouvelle session"), vue)
        bouton.clicked.connect(lambda checked=False, v=vue: self._nouvelle_session(v))
        vue.layout().insertWidget(0, bouton)
        self._bandeaux[vue] = bouton

    def _retirer_bandeau(self, vue):
        bouton = self._bandeaux.pop(vue, None)
        if bouton is not None:
            bouton.setParent(None)   # sort du layout (et cache) tout de suite
            bouton.deleteLater()

    def _nouvelle_session(self, vue):
        """Clic sur « Nouvelle session » : quitter le selecteur, puis lancer `claude`.

        Echap referme le selecteur et rend le shell ; on ne tape la commande qu'une fois
        le shell REELLEMENT revenu au premier plan du pty (etat reel, pas de delai fixe),
        sous un plafond au-dela duquel on n'insiste pas : taper « claude » dans un
        selecteur encore ouvert partirait dans son champ de recherche.
        """
        self._retirer_bandeau(vue)
        vue.envoyer("\x1b")
        minuteur = QTimer(self)
        minuteur.setInterval(self.PERIODE_RELANCE)
        minuteur.timeout.connect(lambda v=vue: self._relancer_si_prete(v))
        self._relances[vue] = [minuteur, 0]
        minuteur.start()

    def _relancer_si_prete(self, vue):
        """Un battement de la surveillance : le shell est-il revenu au premier plan ?

        Sans effet de bord cache, comme `relire_le_registre` : un banc l'appelle
        directement, sans faire tourner le minuteur.
        """
        suivi = self._relances.get(vue)
        if suivi is None:
            return
        pid_shell = vue.pid_shell()
        if pid_shell > 0 and vue.pid_premier_plan() == pid_shell:
            self._arreter_relance(vue)
            vue.envoyer(self._commande_nouvelle_session() + "\n")
            vue.setFocus()
            return
        suivi[1] += self.PERIODE_RELANCE
        if suivi[1] >= self.PLAFOND_RELANCE:
            self._arreter_relance(vue)

    def _arreter_relance(self, vue):
        suivi = self._relances.pop(vue, None)
        if suivi is not None:
            suivi[0].stop()
            suivi[0].deleteLater()

    #: Titre de l'onglet d'attente, quand il n'y a aucune session.
    TITRE_VIDE = "—"

    def _etat_vide(self, texte, titre=None):
        """Affiche un onglet d'attente portant `texte`.

        POURQUOI UN ONGLET, ET PAS UN PANNEAU VIDE. Le bouton « Nouveau terminal » vit
        dans le coin de la BARRE D'ONGLETS, et Qt masque cette barre des qu'il n'y a plus
        aucun onglet : fermer la derniere session faisait donc disparaitre le seul moyen
        d'en rouvrir une (signale par l'utilisateur le 26/07/2026). Garder un onglet
        d'attente garde la barre, donc le bouton.
        """
        if self._onglets.count():
            return
        message = QLabel(texte, self)
        message.setAlignment(Qt.AlignCenter)
        message.setWordWrap(True)
        message.setObjectName("etat_vide")
        index = self._onglets.addTab(message, titre or _(self.TITRE_VIDE))
        # Pas de croix sur cet onglet-la : il n'y a rien a fermer, et la croix ferait
        # disparaitre la barre — donc le bouton — pour de bon.
        # ⚠ L'enumeration se lit sur la CLASSE, jamais sur l'instance : sous PySide6,
        # `barre.RightSide` leve une AttributeError (mesure du 26/07/2026), alors que
        # `QTabBar.RightSide` marche — qtpy retablit l'alias plat au niveau de la classe.
        # L'exception, levee ici, ouvrait le « Rapporteur d'erreur » de Spyder.
        barre = self._onglets.tabBar()
        for cote in (QTabBar.RightSide, QTabBar.LeftSide):
            barre.setTabButton(index, cote, None)

    #: En dessous de cette duree de vie, une session qui se termine n'est PAS relancee.
    DUREE_MINIMALE = 2.0

    def _rouvrir_si_vide(self):
        """Fermer le dernier onglet rouvre aussitot une session (demande du 26/07/2026).

        Le panneau n'a donc jamais zero onglet — ce qui reglait aussi, au passage, la
        disparition du bouton « + » : Qt masque la barre d'onglets des qu'elle est vide.

        ⚠ GARDE-FOU. Si la session qui vient de mourir a vecu moins de DUREE_MINIMALE,
        on ne relance rien : un shell qui echoue instantanement (binaire absent, profil
        casse) ferait sinon boucler l'ouverture sans fin. Dans ce cas on affiche l'etat
        vide, qui garde la barre — donc le bouton — et dit quoi faire.

        ⚠ ON COMPTE LES SESSIONS, PAS LES ONGLETS. En mosaique la barre d'onglets est vide
        par construction : s'en remettre a `self._onglets.count()` ferait rouvrir une
        session a chaque battement.
        """
        import time
        if self._vues:
            return
        if self._en_mosaique:
            self._revenir_aux_onglets()
        if self._onglets.count():
            return
        vecu = time.monotonic() - getattr(self, "_debut_derniere_session", 0.0)
        if vecu < self.DUREE_MINIMALE:
            self._etat_vide(_(
                "L'instance s'est terminee aussitot apres son ouverture.\n\n"
                "Le bouton + en ouvre une autre ; si le probleme persiste, verifier que "
                "la commande « %s » existe dans le shell du profil Konsole.")
                % self.commande_claude())
            return
        # Le panneau ne connait pas le repertoire courant : c'est le greffon qui le sait.
        QTimer.singleShot(0, self.sig_repertoire_demande.emit)

    def _est_etat_vide(self, index):
        widget = self._onglets.widget(index)
        return widget is not None and widget.objectName() == "etat_vide"

    def _retirer_etat_vide(self):
        for index in reversed(range(self._onglets.count())):
            if self._est_etat_vide(index):
                widget = self._onglets.widget(index)
                self._onglets.removeTab(index)
                widget.deleteLater()

    def _afficher_absence_du_binding(self):
        """Message d'attente quand le moteur de Konsole n'a pas ete construit."""
        if self._onglets.count():
            return
        self._etat_vide(
            _("Le moteur de Konsole n'est pas construit sur cette machine.\n\n"
              "Lancer le script qtermwidget_binding/build.sh du dépôt "
              "spyder_konsole, puis rouvrir Spyder."),
            titre=_("Claude indisponible"))

    def nombre_de_sessions(self):
        """Nombre de sessions vivantes (le greffon s'en sert pour n'en ouvrir qu'une).

        ⚠ ON COMPTE LES SESSIONS, PAS LES ONGLETS : la barre porte aussi l'onglet
        d'attente, qui n'est pas une session, et elle est vide en mosaique.
        """
        return len(self._vues)

    def _habillage(self):
        """Police et couleurs a donner au terminal, prises DANS Spyder.

        Le fond du terminal doit etre celui de l'IDE (demande du 26/07/2026) : un
        rectangle noir au milieu d'un theme sombre se lit comme un trou. On prend donc
        la palette de Spyder plutot que celle de Konsole, et la police est celle de
        l'editeur — meme oeil, meme taille, d'un panneau a l'autre.
        """
        habillage = {"police": self.get_conf("police", None),
                     "taille_police": self.get_conf("taille_police", 0) or None}
        try:
            from spyder.config.gui import get_font
            from spyder.utils.palette import SpyderPalette
        except ImportError:      # hors Spyder (tests) : le moteur prendra ses defauts
            return {k: v for k, v in habillage.items() if v}

        fonte = get_font()
        habillage["police"] = habillage["police"] or fonte.family()
        habillage["taille_police"] = habillage["taille_police"] or fonte.pointSize()
        habillage["couleur_fond"] = SpyderPalette.COLOR_BACKGROUND_1
        habillage["couleur_texte"] = SpyderPalette.COLOR_TEXT_1
        habillage["couleur_fond_intense"] = SpyderPalette.COLOR_BACKGROUND_2
        return habillage

    @staticmethod
    def _titre_court(texte):
        """Le titre tel qu'il tient dans un onglet : on garde la FIN.

        C'est elle qui change (dossier courant, commande en cours) ; le debut est
        souvent commun a toutes les sessions. Methode plutot qu'expression en ligne
        parce que les titres viennent de deux endroits — l'ouverture et l'OSC 2 — et que
        deux troncatures differentes dans la meme barre se verraient.
        """
        if not texte:
            return ""
        return texte if len(texte) <= 24 else "…" + texte[-23:]

    def _titre_change(self, vue, texte):
        """Le titre pose par claude-title.sh (OSC 2), vers l'onglet ET la cellule.

        Les deux supports le portent, parce qu'un seul est affiche a la fois et qu'on ne
        sait pas lequel au moment ou le titre arrive.
        """
        if not texte:
            return
        self._titres[vue] = texte
        index = self._onglets.indexOf(vue)
        if index >= 0:
            self._onglets.setTabText(index, self._titre_court(texte))
            self._onglets.setTabToolTip(index, texte)
        if self._en_mosaique:
            self._mosaique.poser_titre(vue, texte)

    def _session_terminee(self, vue, _code):
        """Une session est sortie : on la retire du mode d'affichage EN COURS.

        Les deux modes ne se defont pas de la meme facon, d'ou la separation : en onglets
        il suffit de retirer l'onglet, en mosaique la vue morte est dans une cellule et
        c'est toute la disposition qu'il faut refaire.
        """
        self._oublier(vue)
        if not self._en_mosaique:
            index = self._onglets.indexOf(vue)
            if index >= 0:
                self._onglets.removeTab(index)
            vue.deleteLater()
            self._rouvrir_si_vide()
            self._ajuster_affichage()
            self.update_actions()
            return
        # `liberer` rend TOUTES les vues sans en detruire aucune — c'est ce qui permet de
        # reconstruire la mosaique juste apres avec celles qui restent.
        self._mosaique.liberer()
        vue.setParent(None)
        vue.deleteLater()
        if self._vues:
            self._mosaique.disposer(self._elements())
            self._rafraichir_letat_affiche()
        else:
            self._revenir_aux_onglets()
            self._rouvrir_si_vide()
        self.update_actions()

    def _fermer_onglet(self, index):
        vue = self._onglets.widget(index)
        self._oublier(vue)
        if hasattr(vue, "arreter"):
            vue.arreter()
        self._onglets.removeTab(index)
        vue.deleteLater()
        # Fermer le dernier onglet ferait disparaitre la barre, donc le bouton qui vit
        # dans son coin : on remet aussitot l'onglet d'attente.
        self._rouvrir_si_vide()
        self._ajuster_affichage()
        self.update_actions()

    # =========================================================================
    # REGISTRE D'ETAT : ce que claude-window.sh sait, et que le panneau affiche
    # =========================================================================
    # Le panneau ne DECIDE rien ici : il lit. Les etats et l'arbitrage du clavier sont
    # calcules par les hooks de Claude Code, qui les deposent dans un dossier de petits
    # fichiers. Cf. spyder_claude/etat_instances.py, qui documente le protocole.

    def relire_le_registre(self):
        """Un battement : les etats d'abord, la demande de focus ensuite.

        Publique et sans effet de bord cache : un test l'appelle directement apres avoir
        ecrit dans un faux registre, sans avoir a faire tourner de minuteur.
        """
        etats = etat_instances.etats_par_onglet()
        for vue, identifiant in list(self._identifiants.items()):
            etat = etats.get(identifiant)
            if etat != self._etats.get(vue):
                self._etats[vue] = etat
                self._appliquer_etat(vue, etat)
                # Une instance declaree dans le registre = une session reelle a demarre
                # (choisie dans le selecteur `claude -r`, ou autrement) : le bouton
                # « Nouvelle session » n'a plus de raison d'etre.
                if etat is not None:
                    self._retirer_bandeau(vue)

        cible = etat_instances.demande_de_focus()
        if cible:
            self.activer_session(cible)

        self._rafraichir_la_consommation()

    def _rafraichir_la_consommation(self):
        """Les deux jauges globales, et la vitesse de chaque conversation.

        Sur le MEME battement que les etats — c'est la source (claude-statusline.sh) qui
        publie les deux registres (cf. usage.py), pas de raison d'en sonder un plus vite
        que l'autre.

        GARDE DE CHANGEMENT, comme `_appliquer_etat` en a deja un pour les etats : sans
        lui, ce battement de 500 ms redessinerait le bandeau et chaque tachymetre deux
        fois par seconde EN PERMANENCE, meme quand rien n'a change.
        """
        self._rafraichir_les_compteurs()

        fenetres = usage.fenetres()
        if fenetres != self._dernieres_fenetres:
            self._dernieres_fenetres = fenetres
            self._bandeau.poser_fenetres(fenetres)

        vitesses = usage.vitesses_par_onglet()
        for vue, identifiant in list(self._identifiants.items()):
            valeur = vitesses.get(identifiant)
            if valeur != self._dernieres_vitesses.get(vue):
                self._dernieres_vitesses[vue] = valeur
                self._appliquer_vitesse(vue, valeur)

    def _appliquer_vitesse(self, vue, valeur):
        """Le tachymetre de l'onglet ET celui de la cellule de mosaique.

        LES DEUX EXISTENT EN PERMANENCE — chaque cellule POSSEDE le sien (cf.
        mosaique.Cellule), et chaque onglet porte le sien des que `_greffer_le_compteur`
        est passe dessus — donc nourris ENSEMBLE, sans se soucier du mode d'affichage
        courant. `poser_vitesse` de la mosaique est un no-op si `vue` n'a pas de cellule.
        """
        self._mosaique.poser_vitesse(vue, valeur)
        coin = self._coins.get(vue)
        if coin is not None:
            coin.poser_vitesse(valeur)

    def _rafraichir_les_compteurs(self):
        """Greffe (ou regreffe) le tachymetre sur chaque onglet ouvert.

        IDEMPOTENT ET REJOUE A CHAQUE BATTEMENT, pas seulement a l'ouverture d'une
        session : Spyder installe une croix de fermeture TOUTE NEUVE des qu'un onglet est
        deplace a la souris (`setMovable(True)` sur `self._onglets` + `Tabs.move_tab` qui
        fait `removeTab` puis `insertTab`, ce qui redeclenche `TabBar.tabInserted`) — un
        greffon pose une seule fois a l'ouverture disparaitrait alors en silence au
        premier glisser-deposer.
        """
        for index in range(self._onglets.count()):
            vue = self._onglets.widget(index)
            if vue not in self._vues:
                continue  # l'onglet d'attente : rien a greffer
            coin = self._greffer_le_compteur(index)
            if coin is None:
                continue
            ancien = self._coins.get(vue)
            if ancien is not None and ancien is not coin:
                # Regreffe apres un glisser-deposer, ou apres un aller-retour par la
                # mosaique (onglets -> mosaique -> onglets repose une croix NEUVE sur
                # CHAQUE onglet) : l'ancien conteneur est orphelin.
                # ⚠ `try/except`, PAS un appel nu : mesure en direct (31/07/2026) — un
                # aller-retour mosaique peut deja avoir laisse Qt detruire l'ancien
                # conteneur par un autre chemin avant que ce battement ne s'execute,
                # auquel cas `deleteLater()` leve « Internal C++ object already deleted »
                # et, SANS CE GARDE, le battement suivant retombait sur le MEME
                # `ancien` perime (jamais remplace dans `self._coins`, l'exception ayant
                # coupe la methode avant la ligne suivante) : le panneau levait la meme
                # erreur EN BOUCLE, toutes les 500 ms, sans jamais s'en remettre.
                try:
                    ancien.deleteLater()
                except RuntimeError:
                    pass
            self._coins[vue] = coin
            coin.poser_pleine_echelle(self.vitesse_maximale())

    def _greffer_le_compteur(self, index):
        """Remplace le widget RightSide de l'onglet `index` par [Compteur][croix].

        Retourne le CoinDOnglet en place (existant ou tout juste cree), ou None si
        l'onglet n'a pas de croix a cet index (l'onglet d'attente : rien a greffer).

        ⚠ ORDRE IMPERATIF, cf. spyder_claude/spyder/onglet_compteur.py — `setTabButton`
        D'ABORD, `adopter_la_croix` APRES : dans l'autre ordre, Qt masquerait la croix
        d'origine a l'interieur d'un conteneur pas encore installe (Qt masque le widget
        precedemment assigne a ce slot des qu'on en installe un nouveau, quel que soit
        son parent au moment de l'appel).
        """
        barre = self._onglets.tabBar()
        actuel = barre.tabButton(index, QTabBar.RightSide)
        if isinstance(actuel, CoinDOnglet):
            return actuel
        if actuel is None:
            return None
        coin = CoinDOnglet(barre)
        barre.setTabButton(index, QTabBar.RightSide, coin)
        coin.adopter_la_croix(actuel)
        return coin

    def _appliquer_etat(self, vue, etat):
        """Fond du terminal, pastille de l'onglet, bandeau de la cellule."""
        if hasattr(vue, "appliquer_schema"):
            vue.appliquer_schema(etat_instances.SCHEMAS.get(etat))

        index = self._onglets.indexOf(vue)
        if index >= 0:
            self._onglets.setTabIcon(index, self._pastille(etat))

        if self._en_mosaique:
            self._mosaique.poser_couleur(
                vue, etat_instances.COULEURS.get(etat),
                self._habillage_cache.get("couleur_texte"))

    @staticmethod
    def _pastille(etat):
        couleur = PASTILLES.get(etat)
        if not couleur:
            # « busy » et « etat inconnu » ne portent aucune marque : une pastille grise
            # sur chaque onglet ne distinguerait plus rien.
            return QIcon()
        return qta.icon("mdi.circle-medium", color=couleur)

    def activer_session(self, identifiant):
        """Donne le clavier a la session designee. Retourne True si elle existe.

        Appelee UNIQUEMENT sur demande de l'arbitre (fichier `focus-pane`), jamais de la
        propre initiative du panneau : c'est claude-window.sh qui sait laquelle des
        instances de la machine — panneau ou fenetre — doit parler la premiere.
        """
        for vue, identifiant_vue in self._identifiants.items():
            if identifiant_vue != identifiant:
                continue
            plugin = getattr(self, "_plugin", None)
            if plugin is not None and hasattr(plugin, "switch_to_plugin"):
                try:
                    plugin.switch_to_plugin()
                except Exception:
                    pass
            if not self._en_mosaique:
                index = self._onglets.indexOf(vue)
                if index >= 0:
                    self._onglets.setCurrentIndex(index)
            vue.setFocus()
            return True
        return False

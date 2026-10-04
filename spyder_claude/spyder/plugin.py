# -*- coding: utf-8 -*-
"""Greffon « Claude » : les instances de Claude Code dans un dock de Spyder.

GREFFON INDEPENDANT DU GREFFON TERMINAL. Une premiere version le faisait heriter de
`TerminalNatif` — les deux greffons font en effet le meme geste : ouvrir une session dans
le repertoire courant de Spyder, et la fermer proprement a la sortie. L'utilisateur l'a
refuse le 31/07/2026 : « je veux 2 greffons independants », la ressemblance d'aujourd'hui
n'engageant en rien celle de demain. Ce fichier est donc jumeau de
spyder_konsole/spyder/plugin.py, et libre d'en diverger.

CE QU'IL FAUT SAVOIR AVANT DE LE MODIFIER : le comportement des instances Claude (fond
colore par etat, titre, arbitrage du clavier) n'est PAS implemente ici. Il vient des hooks
de Claude Code, `claude-window.sh` en tete, qui traitent une session de panneau comme une
session de fenetre. Le panneau ne fait que lire leur registre et obeir. Cf.
spyder_claude/etat_instances.py, qui documente le protocole.

Le greffon est le SEUL a parler aux autres greffons de Spyder : il fournit au panneau le
repertoire de travail courant. Le panneau, lui, n'a aucun acces au registre des greffons —
c'est ce qui le rend testable hors de Spyder.
"""

import os

import qtawesome as qta

from spyder.api.plugins import Plugins, SpyderDockablePlugin
from spyder.utils.icon_manager import ima

from spyder_claude.spyder.main_widget import PanneauClaude
from spyder_claude.spyder.translations import _


class GreffonClaude(SpyderDockablePlugin):
    """Panneau d'instances Claude Code."""

    NAME = "claude_pane"          # doit etre identique au nom du point d'entree
    REQUIRES = []
    OPTIONAL = [Plugins.WorkingDirectory]
    TABIFY = [Plugins.Console]
    WIDGET_CLASS = PanneauClaude
    CONF_SECTION = "claude_pane"
    CONF_FILE = False

    @staticmethod
    def get_name():
        return _("Claude")

    @staticmethod
    def get_description():
        return _("Instances de Claude Code dans un dock : un onglet par instance, "
                 "l'etat de chacune a l'oeil, et une mosaique quand le panneau est "
                 "agrandi.")

    @classmethod
    def get_icon(cls):
        # « mdi.robot-outline » plutot que le « mdi.console » du terminal : les deux
        # panneaux se ressemblent, leurs icones ne doivent pas.
        return qta.icon("mdi.robot-outline", color=ima.MAIN_FG_COLOR)

    # --- API SpyderDockablePlugin --------------------------------------------

    def on_initialize(self):
        self.get_widget().sig_repertoire_demande.connect(self.ouvrir_claude)

    def on_mainwindow_visible(self):
        """Ouvre une premiere instance des que Spyder est affiche.

        On attend que la fenetre soit VISIBLE plutot que de le faire dans
        `on_initialize` : le repertoire de travail n'est pas encore etabli a ce moment-la,
        et l'instance partirait dans le mauvais dossier.
        """
        widget = self.get_widget()
        # Apres tout le montage de Spyder : c'est le seul moment ou masquer le burger
        # vide tient (cf. PanneauClaude._masquer_burger_vide).
        widget._masquer_burger_vide()
        # Les conversations ouvertes a la derniere fermeture (ou au dernier plantage)
        # d'abord ; l'instance par defaut seulement s'il n'y en avait aucune.
        widget.rouvrir_les_sessions()
        if widget.nombre_de_sessions() == 0:
            self.ouvrir_claude()

    def on_close(self, cancelable=False):
        # Le framework n'appelle pas toujours widget.on_close : on le declenche ici,
        # sinon les shells survivent a la fermeture de Spyder.
        self.get_widget().on_close()
        return True

    # --- API publique, utilisable depuis --gui-exec --------------------------

    def ouvrir_claude(self, repertoire=None):
        """Ouvre une instance. Sans argument, dans le repertoire courant de Spyder.

        Methode PUBLIQUE et sans argument obligatoire a dessein : c'est elle qui permet
        de tester le greffon en autonomie, sans clic, par
        `spyder --gui-exec <script>` avec
        `main.get_plugin('claude_pane').ouvrir_claude()`.
        """
        return self.get_widget().ouvrir_terminal(
            repertoire or self._repertoire_defaut())

    def basculer_mosaique(self, actif=None):
        """Etale ou rassemble les instances, sans passer par l'agrandissement du panneau."""
        return self.get_widget().basculer_mosaique(actif)

    def _repertoire_defaut(self):
        """Le REPERTOIRE COURANT de Spyder — celui de la barre « Repertoire de travail ».

        Demande explicite de l'utilisateur (26/07/2026) : « la console ne doit pas
        s'ouvrir dans le dossier du fichier edite, mais dans le repertoire courant ».
        C'est le meme dossier que celui ou s'execute la console IPython, donc l'instance
        et la console parlent du meme endroit — ce qui est exactement ce qu'on attend en
        demandant a Claude de regarder le fichier ouvert.

        Le greffon `workingdir` est la seule reponse juste, et il existe toujours — les
        replis ne servent qu'a ne jamais echouer.
        """
        travail = self.get_plugin(Plugins.WorkingDirectory, error=False)
        if travail is not None:
            try:
                chemin = travail.get_workdir()
            except AttributeError:
                chemin = None
            if chemin and os.path.isdir(chemin):
                return chemin

        return os.getcwd()

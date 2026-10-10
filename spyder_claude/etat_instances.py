# -*- coding: utf-8 -*-
"""Le registre d'etat des instances Claude, vu depuis Spyder.

CE QUE CE MODULE NE FAIT PAS : il n'invente aucun etat. Tout ce qu'il lit est ecrit par
`claude-window.sh`, le hook qui arbitre deja les fenetres Konsole — un fichier par
instance dans `$XDG_RUNTIME_DIR/claude-windows/inst-<pid>`, format shell :

    CW_STATE=waiting|idle|busy      ce que fait l'instance
    CW_SINCE=<nanosecondes>         depuis quand (sert a ordonner la file d'attente)
    CW_KONSOLE=<pid de fenetre>     la fenetre a activer ; pour un panneau, le PID de Spyder
    CW_SVC=<service D-Bus>          « spyder » quand l'instance vit dans un panneau
    CW_SESSION=<numero>             l'onglet ; pour un panneau, son identifiant

POURQUOI LE MEME REGISTRE, ET PAS UN A NOUS. C'est la seule facon de garder « tout le
travail fait sur le comportement des instances de Claude » : l'arbitre compare les
instances ENTRE ELLES (qui attend depuis le plus longtemps, qui a la parole, qui a le
focus). Un panneau Spyder qui tiendrait son propre registre serait invisible de cet
arbitrage, et deux dispositifs concurrents se disputeraient le focus. Ici, un onglet du
panneau est une instance comme une autre : elle prend son rang dans les memes files.

CE QUI CHANGE POUR UN PANNEAU, ET C'EST TOUT : la fenetre a activer est celle de Spyder
(une seule pour toutes les sessions), donc « donner le focus » ne peut plus se resumer a
la remonter. Il faut aussi designer l'ONGLET. claude-window.sh sait le faire pour Konsole
(`Window.setCurrentSession` par D-Bus) ; un panneau n'a pas de service D-Bus, alors
l'arbitre depose une DEMANDE dans le fichier `focus-pane` et c'est le panneau qui s'active
lui-meme. Le sens de circulation est le meme, le transport seul differe.

Aucun import Qt ni Spyder ici : c'est ce qui permet de derouler tout le protocole dans un
test ordinaire, sans serveur graphique ni Spyder installe.
"""

import os


def dossier_etat():
    """Le repertoire ou claude-window.sh tient son registre.

    Lu a CHAQUE APPEL et non fige dans une constante de module : les tests le deplacent
    par XDG_RUNTIME_DIR, et une valeur calculee a l'import serait celle du processus de
    test, pas celle du cas.
    """
    return os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "claude-windows")


#: Nom du fichier par lequel l'arbitre demande l'activation d'un onglet du panneau.
FICHIER_FOCUS = "focus-pane"

#: Valeur de CW_SVC qui distingue une instance hebergee par un panneau Spyder d'une
#: instance en fenetre Konsole. Ecrite par claude-window.sh, relue ici.
SERVICE_SPYDER = "spyder"

#: Les couleurs de fond des trois etats. LES MEMES que celles de claude-window.sh, qui
#: les pose par sequence OSC sur le pty d'une fenetre Konsole — ici c'est le jeu de
#: couleurs du terminal embarque qui les porte, mais l'utilisateur doit voir exactement
#: la meme chose : rouge sombre « on t'attend », vert sombre « c'est fini ».
#: None = fond normal de l'IDE (etat « busy » : Claude travaille, rien a signaler).
COULEURS = {"waiting": "#3a1414", "idle": "#14351f", "busy": None}

#: Nom du jeu de couleurs derive, par etat (cf. konsole_view.preparer_schema).
SCHEMAS = {"waiting": "ClaudeAttente", "idle": "ClaudeDisponible", "busy": None}


def _lire_fichier_shell(chemin):
    """Lit un fichier `CLE=valeur` (format de claude-window.sh). {} si illisible.

    Ce n'est PAS un parseur shell : le hook n'ecrit que des affectations simples, sans
    guillemets ni substitution (cf. le bloc `printf` de claude-window.sh). Executer ce
    fichier serait donner les droits de Spyder a n'importe qui sachant ecrire dans
    $XDG_RUNTIME_DIR.
    """
    valeurs = {}
    try:
        with open(chemin, "r", encoding="utf-8", errors="replace") as fichier:
            for ligne in fichier:
                cle, separateur, valeur = ligne.partition("=")
                if separateur:
                    valeurs[cle.strip()] = valeur.strip()
    except OSError:
        return {}
    return valeurs


def _vivant(pid):
    """Le processus existe-t-il encore ?

    ⚠ `os.kill(pid, 0)` et non `pgrep` : depuis le bac a sable de Claude, l'espace de
    noms des PID est isole et `pgrep` est aveugle aux processus de la machine. Ici, on
    tourne DANS Spyder — donc hors bac a sable — mais la regle vaut pour les tests, qui
    eux peuvent y tourner. os.kill(0) interroge le noyau directement.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (OSError, OverflowError, ValueError):
        # PermissionError : le processus existe, il ne nous appartient pas.
        return True
    return True


def lire_instances(dossier=None):
    """Les instances Claude actuellement declarees, indexees par identifiant d'onglet.

    Ne retourne que les instances hebergees par un panneau Spyder (CW_SVC=spyder) : ce
    sont les seules que ce panneau-ci peut colorer ou activer. Les instances en fenetre
    Konsole appartiennent a l'arbitre, qui les traite par D-Bus.

    Les instances mortes sont ignorees mais PAS supprimees : la
    purge du registre appartient a claude-window.sh, qui la fait sous verrou. Deux
    processus qui nettoient le meme registre sans se coordonner, c'est exactement la
    course que l'arbitre unique evite.

    Retourne {identifiant: {"pid": int, "etat": str, "depuis": int, "fenetre": str}}.
    """
    dossier = dossier or dossier_etat()
    instances = {}
    try:
        noms = os.listdir(dossier)
    except OSError:
        return instances

    for nom in noms:
        if not nom.startswith("inst-"):
            continue
        try:
            pid = int(nom[5:])
        except ValueError:
            continue
        if not _vivant(pid):
            continue
        valeurs = _lire_fichier_shell(os.path.join(dossier, nom))
        if valeurs.get("CW_SVC") != SERVICE_SPYDER:
            continue
        identifiant = valeurs.get("CW_SESSION") or ""
        if not identifiant:
            continue
        try:
            depuis = int(valeurs.get("CW_SINCE") or 0)
        except ValueError:
            depuis = 0
        instances[identifiant] = {"pid": pid,
                                  "etat": valeurs.get("CW_STATE") or "",
                                  "depuis": depuis,
                                  "fenetre": valeurs.get("CW_KONSOLE") or ""}
    return instances


def etats_par_onglet(dossier=None):
    """{identifiant d'onglet: etat}. La forme dont le panneau a besoin, et rien de plus."""
    return {identifiant: donnees["etat"]
            for identifiant, donnees in lire_instances(dossier).items()}


def demande_de_focus(dossier=None, consommer=True):
    """L'onglet que l'arbitre demande d'activer, ou None. Le consomme au passage.

    UNE DEMANDE SE CONSOMME, elle ne se relit pas. Sans cela, le panneau reprendrait le
    focus a chaque battement de son minuteur — l'utilisateur ne pourrait plus changer
    d'onglet a la main, et le clavier lui serait repris en pleine frappe. C'est le meme
    principe que le garde-fou « arbitrer seulement sur un VRAI changement d'etat » de
    claude-window.sh.
    """
    dossier = dossier or dossier_etat()
    chemin = os.path.join(dossier, FICHIER_FOCUS)
    try:
        with open(chemin, "r", encoding="utf-8", errors="replace") as fichier:
            identifiant = fichier.read().strip()
    except OSError:
        return None
    if consommer:
        try:
            os.unlink(chemin)
        except OSError:
            pass
    return identifiant or None


def deposer_demande_de_focus(identifiant, dossier=None):
    """Ecrit une demande d'activation. N'existe que pour les tests et le diagnostic.

    En fonctionnement, c'est claude-window.sh qui ecrit ce fichier : le panneau ne se
    donne pas le focus tout seul, il obeit a l'arbitre — sinon deux instances qui
    finissent en meme temps se le disputeraient, ce que la file d'attente existe
    justement pour empecher.
    """
    dossier = dossier or dossier_etat()
    os.makedirs(dossier, exist_ok=True)
    provisoire = os.path.join(dossier, FICHIER_FOCUS + ".tmp")
    with open(provisoire, "w", encoding="utf-8") as fichier:
        fichier.write("%s\n" % identifiant)
    os.replace(provisoire, os.path.join(dossier, FICHIER_FOCUS))


def variables_de_session(identifiant, pid_fenetre):
    """Les variables d'environnement a donner a une session Claude d'un panneau.

    C'est par elles, et par elles seules, que claude-window.sh reconnait une instance
    hebergee : il lit `/proc/<pid>/environ` du processus claude. Rien d'autre ne le
    distingue — le pty, le shell et l'arbre des processus sont ceux d'un terminal
    ordinaire.

    S'y ajoute CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN : depuis la 2.1.29x, un interrupteur
    serveur (tengu_pewter_brook) bascule Claude Code en rendu « fullscreen », qui vit sur
    l'ecran alternatif et defile lui-meme. QTermWidget n'a alors plus aucun historique :
    sa barre de defilement reste pleine et ne fait rien (10/10/2026). Le binaire teste
    cette variable AVANT le reglage `tui` et l'interrupteur : rendu classique garanti.
    """
    return {"SPYDER_CLAUDE_PANE": str(identifiant),
            "SPYDER_CLAUDE_WINDOW": str(pid_fenetre),
            "CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN": "1"}

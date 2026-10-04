# -*- coding: utf-8 -*-
"""La consommation de quota Claude, vue depuis Spyder.

CE QUE CE MODULE NE FAIT PAS : il n'estime rien depuis les JSONL de conversation et ne
devine aucun mecanisme de reset. Tout ce qu'il lit vient de `claude-statusline.sh`, le
script statusLine qui recoit les VRAIS pourcentages calcules par Anthropic (Claude Code
les passe sur l'entree standard, cf. rate_limits.five_hour / rate_limits.seven_day) et les
recopie dans un fichier par session :

    $XDG_RUNTIME_DIR/claude-windows/usage-<pid_claude>

    CU_PANE=<SPYDER_CLAUDE_PANE, vide hors panneau>
    CU_HORODATAGE=<epoch s de cet echantillon>
    CU_5H_PCT / CU_7J_PCT       0..100 entier, -1 = non mesurable
    CU_5H_FIN / CU_7J_FIN       epoch s de reset, 0 = inconnu
    CU_CENTIMES                 cout cumule de CETTE session, en centimes
    CU_VITESSE                  centimes par heure, -1 = non mesurable
    CU_COUT_PREC / CU_INSTANT_PREC   ancrage interne au script, non relu ici
    CU_SESSION                  identifiant de la conversation (session_id), vide si inconnu
    CU_DOSSIER                  dossier de LANCEMENT de claude (workspace.project_dir)

MEME DOSSIER QUE LE REGISTRE D'ETAT, ET C'EST VOULU : un fichier par PID Claude, la meme
liveness que `etat_instances._vivant()` donne deja pour `inst-<pid>`, sans dupliquer cette
logique. Prefixe `usage-` distinct de `inst-` pour que les deux registres cohabitent sans
ambiguite dans le meme dossier.

FRAICHEUR, PAS GRANDEUR : `rate_limits` est un quota de COMPTE, donc toute session vivante
rapporte le meme chiffre — seul l'age de l'echantillon distingue une valeur d'une autre.
Entre plusieurs sessions, on garde la PLUS FRAICHE, jamais la plus grande : une session
inactive depuis ce matin garderait sinon un pourcentage d'avant le dernier reset, et une
alarme qui ment dans le sens rassurant est pire que pas d'alarme.

Aucun import Qt ni Spyder ici : c'est ce qui permet de derouler tout le protocole dans un
test ordinaire, sans serveur graphique ni Spyder installe — comme etat_instances.py.
"""

import os
import time

from spyder_claude import etat_instances

#: Prefixe des fichiers d'usage, distinct de "inst-" (etat_instances) dans le meme dossier.
PREFIXE = "usage-"

#: En dessous de cette duree (s) depuis le dernier calcul, on republie la vitesse
#: precedente plutot que de recalculer : c'est aussi la duree en dessous de laquelle la
#: vitesse affichee reste pleine (cf. vitesse_decrue). Doit rester EGALE a la constante du
#: meme nom dans claude-statusline.sh — c'est le meme calcul, ecrit dans deux langages.
FENETRE_MIN = 60

#: Au-dela de cette duree (s) sans nouvel echantillon, la vitesse affichee retombe a zero :
#: une conversation silencieuse ne doit pas garder eternellement l'aiguille de sa derniere
#: rafale. Interpolation lineaire entre FENETRE_MIN (vitesse pleine) et SILENCE_MAX (zero).
SILENCE_MAX = 300

#: Au-dela de cette duree (s) sans nouvel echantillon pour les jauges globales, la valeur
#: reste affichee mais ESTOMPEE plutot que masquee : un chiffre date est un plancher connu,
#: une absence n'en est pas un. C'est au widget de lire ce seuil sur le champ "age" retourne
#: par fenetres().
PEREMPTION = 15 * 60

#: Seuils de couleur (orange, rouge), par fenetre. LES MEMES que dans
#: claude-statusline.sh — recopies, pas importes (l'un est du bash, l'autre du python) —
#: pour que la ligne de terminal et les jauges du panneau s'alarment au meme moment.
#: cf. tests/test_usage.py::test_les_seuils_sont_ceux_du_script, qui les compare au script.
SEUILS = {"cinq_heures": (50, 80), "sept_jours": (60, 85)}


def _entier(valeur, defaut):
    """Convertit en int, ou rend `defaut` si absent/illisible. Jamais une exception."""
    try:
        return int(valeur)
    except (TypeError, ValueError):
        return defaut


def _lire_usages(dossier=None):
    """{pid: {cle: valeur}} pour chaque fichier usage-<pid> d'une session VIVANTE.

    Reutilise `etat_instances._vivant()` et `_lire_fichier_shell()` : meme liveness, meme
    parseur non executant que le registre d'etat — un fichier `usage-<pid>` vit dans le
    meme dossier world-writable-ish et merite la meme mefiance (cf.
    tests/test_usage.py::test_le_fichier_n_est_pas_execute).
    """
    dossier = dossier or etat_instances.dossier_etat()
    resultat = {}
    try:
        noms = os.listdir(dossier)
    except OSError:
        return resultat
    for nom in noms:
        if not nom.startswith(PREFIXE):
            continue
        try:
            pid = int(nom[len(PREFIXE):])
        except ValueError:
            continue
        if not etat_instances._vivant(pid):
            continue
        chemin = os.path.join(dossier, nom)
        resultat[pid] = etat_instances._lire_fichier_shell(chemin)
    return resultat


def fenetres(dossier=None, maintenant=None):
    """{"cinq_heures": .., "sept_jours": ..}, chacune un dict ou None si non mesurable.

    Chaque valeur presente est {"pct": 0..100, "fin": epoch ou None, "age": secondes}.
    JAMAIS 0 quand la donnee manque : une fenetre non mesurable (rate_limits absent, ou
    deja perimee) vaut None, distinct d'un vrai 0 % — afficher 0 % la ou l'on n'a rien
    mesure ferait passer une absence de mesure pour une mesure rassurante.

    Une fenetre dont FIN est deja passee est traitee comme perimee (le quota a tourne, le
    chiffre ne veut plus rien dire) MEME si c'est le plus recent echantillon disponible :
    on garde alors None jusqu'a ce qu'une session se resynchronise apres le vrai reset.
    """
    maintenant = maintenant if maintenant is not None else time.time()
    meilleur = {"cinq_heures": None, "sept_jours": None}
    prefixes = {"cinq_heures": "CU_5H", "sept_jours": "CU_7J"}
    for valeurs in _lire_usages(dossier).values():
        horodatage = _entier(valeurs.get("CU_HORODATAGE"), 0)
        for cle, prefixe in prefixes.items():
            pct = _entier(valeurs.get(prefixe + "_PCT"), -1)
            if pct < 0:
                continue
            fin = _entier(valeurs.get(prefixe + "_FIN"), 0)
            if fin and fin <= maintenant:
                continue
            actuel = meilleur[cle]
            if actuel is not None and actuel["_horodatage"] >= horodatage:
                continue
            meilleur[cle] = {"pct": pct, "fin": fin or None,
                             "age": maintenant - horodatage,
                             "_horodatage": horodatage}
    for cle, valeur in meilleur.items():
        if valeur is not None:
            del valeur["_horodatage"]
    return meilleur


def vitesse_decrue(vitesse, age):
    """La vitesse a AFFICHER, compte tenu du silence depuis le dernier echantillon.

    `vitesse` en centimes/heure, ou None si non mesurable (session muette, ou juste apres
    un /clear) — None reste None quel que soit l'age, ce n'est pas une vitesse nulle.

    En dessous de FENETRE_MIN, la vitesse mesuree est encore fraiche : on la rend telle
    quelle. Au-dela, elle decroit lineairement jusqu'a 0 a SILENCE_MAX : une conversation
    qui s'est tue ne doit pas garder l'aiguille de sa derniere rafale indefiniment.
    """
    if vitesse is None:
        return None
    if age >= SILENCE_MAX:
        return 0.0
    if age <= FENETRE_MIN:
        return float(vitesse)
    portion = (SILENCE_MAX - age) / (SILENCE_MAX - FENETRE_MIN)
    return vitesse * portion


def vitesses_par_onglet(dossier=None, maintenant=None):
    """{identifiant d'onglet (CU_PANE): vitesse decrue en centimes/heure, ou None}.

    Ignore les sessions sans CU_PANE (hors panneau Spyder) : elles comptent pour les
    fenetres globales, mais n'ont pas d'onglet a colorer. C'est la meme forme que
    etat_instances.etats_par_onglet() : la cle est ce dont le panneau a besoin.
    """
    maintenant = maintenant if maintenant is not None else time.time()
    resultat = {}
    for valeurs in _lire_usages(dossier).values():
        pane = valeurs.get("CU_PANE") or ""
        if not pane:
            continue
        horodatage = _entier(valeurs.get("CU_HORODATAGE"), 0)
        brute = _entier(valeurs.get("CU_VITESSE"), -1)
        vitesse = None if brute < 0 else brute
        resultat[pane] = vitesse_decrue(vitesse, maintenant - horodatage)
    return resultat


def sessions_par_onglet(dossier=None):
    """{identifiant d'onglet (CU_PANE): (session_id, dossier de lancement)}.

    Ce qu'il faut pour rouvrir chaque conversation par `claude -r` au prochain demarrage
    de Spyder (cf. main_widget._memoriser_les_sessions). Le dossier est celui de
    LANCEMENT et non le dossier courant : `claude -r` cherche la conversation dans le
    projet du dossier ou il est lance. Un onglet sans CU_SESSION (statusline pas encore
    passee, ou ancienne version du script) est absent : rien a rouvrir.
    """
    resultat = {}
    for valeurs in _lire_usages(dossier).values():
        pane = valeurs.get("CU_PANE") or ""
        session = valeurs.get("CU_SESSION") or ""
        if pane and session:
            resultat[pane] = (session, valeurs.get("CU_DOSSIER") or "")
    return resultat


def deposer_usage(pid, valeurs, dossier=None):
    """Ecrit un fichier usage-<pid>. N'existe que pour les tests et le diagnostic.

    En fonctionnement, c'est claude-statusline.sh qui l'ecrit, par le meme idiome
    ecriture-temporaire-puis-mv (cf. etat_instances.deposer_demande_de_focus, meme
    principe : un lecteur ne doit jamais tomber sur un fichier a moitie ecrit).
    """
    dossier = dossier or etat_instances.dossier_etat()
    os.makedirs(dossier, exist_ok=True)
    chemin = os.path.join(dossier, "%s%s" % (PREFIXE, pid))
    provisoire = chemin + ".tmp"
    with open(provisoire, "w", encoding="utf-8") as fichier:
        for cle, valeur in valeurs.items():
            fichier.write("%s=%s\n" % (cle, valeur))
    os.replace(provisoire, chemin)

#!/bin/bash
# Test d'interoperabilite : claude-window.sh reconnait-il une session de PANNEAU ?
#
# C'EST LE SEUL TEST QUI TRAVERSE LA FRONTIERE entre les deux programmes. Les tests Python
# verifient que le panneau sait relire un registre ; celui-ci verifie que le hook sait
# l'ECRIRE dans la forme attendue. Sans lui, une faute dans le nom d'une variable
# d'environnement donnerait un panneau qui n'affiche jamais aucune couleur, sans le
# moindre message.
#
# TROIS PRECAUTIONS, sans lesquelles ce test serait dangereux :
#   1. XDG_RUNTIME_DIR est deplace : le registre ecrit est un faux, jamais celui des
#      instances de l'utilisateur ;
#   2. le hook est lance a travers `script`, qui lui donne un VRAI pty - sans quoi il
#      sortirait des la premiere etape (il remonte l'arbre des processus jusqu'a un
#      ancetre ayant un terminal, et il n'y en aurait aucun) ;
#   3. le pty est jetable et sa sortie est capturee : c'est ce qui permet de verifier
#      qu'AUCUNE sequence OSC de couleur n'est ecrite pour un panneau (elle s'afficherait
#      litteralement si le moteur ne la connait pas).
#
# Lancement :  bash tests/test_hook_panneau.sh

set -u

RACINE=$(dirname "$(dirname "$(dirname "$(dirname "$(realpath "${BASH_SOURCE[0]}")")")")")
# La version VERSIONNEE par defaut. `HOOK=...` permet de viser une autre copie - celle qui
# est deployee dans ~/.claude/hooks, pour verifier qu'elle est bien a jour, ou une version
# anterieure, pour verifier que ce test ECHOUE sans le correctif (il l'a ete : sans la
# reconnaissance des panneaux, les quatre premiers cas tombent).
HOOK="${HOOK:-$RACINE/config_files/Claude/claude-window.sh}"
[ -r "$HOOK" ] || { echo "ERREUR : $HOOK introuvable" >&2; exit 1; }

TEMP=$(mktemp -d "${TMPDIR:-/tmp}/test-hook-panneau.XXXXXX") || exit 1
trap 'rm -rf "$TEMP"' EXIT

echecs=0
verifier() {
	if [ "$2" = "$3" ]; then
		printf 'ok    %s\n' "$1"
	else
		printf 'ECHEC %s\n        attendu : %s\n        obtenu  : %s\n' "$1" "$3" "$2"
		echecs=$((echecs + 1))
	fi
}
verifier_contient() {
	case "$2" in
		*"$3"*) printf 'ok    %s\n' "$1" ;;
		*) printf 'ECHEC %s\n        « %s » absent de : %s\n' "$1" "$3" "$2"
		   echecs=$((echecs + 1)) ;;
	esac
}

# Le lanceur tient le role que joue Claude Code en vrai : c'est LUI qui possede le pty, et
# le hook est son enfant. Sans cet intermediaire, `script` exec-erait directement le hook,
# qui remonterait alors vers `script` lui-meme - un processus sans terminal de controle -
# et sortirait des sa premiere etape. Le `exit 0` final empeche bash d'optimiser l'appel en
# `exec`, ce qui supprimerait justement le niveau qu'on cherche a creer.
#
# Il RESTE EN VIE le temps que l'arbitre finisse. Ce n'est pas du confort : l'arbitrage
# tourne en tache de fond, et si le lanceur sortait aussitot, `script` fermerait le pty et
# le groupe de processus recevrait SIGHUP - l'arbitre serait tue avant d'avoir rien ecrit
# (constate : le registre etait bien la, la demande d'activation jamais). On attend
# l'ARTEFACT, jamais une duree fixe : la charge de cette machine rend tout delai calibre au
# repos faux, c'est ecrit noir sur blanc dans le CLAUDE.md du depot.
cat > "$TEMP/lanceur.sh" <<LANCEUR
#!/bin/bash
bash "$HOOK" "\$1"
n=0
while [ \$n -lt 80 ]; do
	if [ -n "\${ATTENDRE:-}" ]; then
		[ -e "\$ATTENDRE" ] && break
	else
		ls "\$XDG_RUNTIME_DIR"/claude-windows/inst-* >/dev/null 2>&1 && break
	fi
	sleep 0.1; n=\$((n + 1))
done
exit 0
LANCEUR

# Joue le hook dans un pty jetable, avec l'environnement d'une session de panneau.
jouer() {
	local etat="$1" pane="$2" fenetre="$3" sortie="$TEMP/sortie.txt"
	rm -rf "$TEMP/run"; mkdir -p "$TEMP/run"
	SPYDER_CLAUDE_PANE="$pane" SPYDER_CLAUDE_WINDOW="$fenetre" \
	XDG_RUNTIME_DIR="$TEMP/run" \
	ATTENDRE="$TEMP/run/claude-windows/focus-pane" \
		script -qec "bash '$TEMP/lanceur.sh' $etat" "$sortie" >/dev/null 2>&1
	# Le hook lance son arbitre en tache de fond : on attend que le registre soit ecrit
	# plutot que de dormir un temps fixe (la charge de cette machine rend tout delai faux).
	local attente=0
	while [ $attente -lt 50 ]; do
		[ -n "$(ls "$TEMP/run/claude-windows"/inst-* 2>/dev/null)" ] && break
		sleep 0.1; attente=$((attente + 1))
	done
	cat "$TEMP/run/claude-windows"/inst-* 2>/dev/null
}

echo "--- Session de panneau reconnue ---"
registre=$(jouer waiting "abc123" 4242)
verifier_contient "l'etat est enregistre"          "$registre" "CW_STATE=waiting"
verifier_contient "le service dit « spyder »"      "$registre" "CW_SVC=spyder"
verifier_contient "la session est l'onglet"        "$registre" "CW_SESSION=abc123"
verifier_contient "la fenetre est celle de Spyder" "$registre" "CW_KONSOLE=4242"

echo
echo "--- L'arbitre depose une demande d'activation d'onglet ---"
# Une seule instance, en attente : elle est donc tete de file, et l'arbitre lui donne le
# focus. Faute de service D-Bus, cela doit se traduire par le fichier `focus-pane`. C'est
# la moitie du dispositif que le greffon relit ; sans elle, une question posee dans un
# onglet cache ne ramenerait jamais l'utilisateur dessus.
attente=0
while [ $attente -lt 60 ]; do
	[ -f "$TEMP/run/claude-windows/focus-pane" ] && break
	sleep 0.1; attente=$((attente + 1))
done
demande=$(cat "$TEMP/run/claude-windows/focus-pane" 2>/dev/null)
verifier "la demande designe le bon onglet" "$demande" "abc123"
# Et aucun fichier temporaire ne doit trainer : le depot se fait par mv, pour qu'un lecteur
# ne tombe jamais sur un fichier a moitie ecrit.
restes=$(ls "$TEMP/run/claude-windows"/focus-pane.* 2>/dev/null | wc -l)
verifier "aucun fichier temporaire laisse derriere" "$restes" "0"

echo
echo "--- Aucune sequence de couleur ecrite sur le pty d'un panneau ---"
# La sequence de fond est OSC 11 (« \033]11;#3a1414\007 ») : elle ne doit PAS apparaitre,
# c'est le greffon qui pose la couleur, par le jeu de couleurs du moteur.
if grep -q ']11;' "$TEMP/sortie.txt" 2>/dev/null; then
	echo "ECHEC le hook a ecrit une sequence de couleur dans un panneau"
	echecs=$((echecs + 1))
else
	echo "ok    aucune sequence OSC 11 sur le pty"
fi

echo
echo "--- Sans les variables, rien ne change pour une session ordinaire ---"
# Le meme hook, sans marquage : il ne doit surtout pas se croire dans un panneau.
rm -rf "$TEMP/run"; mkdir -p "$TEMP/run"
XDG_RUNTIME_DIR="$TEMP/run" script -qec "bash '$TEMP/lanceur.sh' idle" \
	"$TEMP/sortie2.txt" >/dev/null 2>&1
attente=0
while [ $attente -lt 50 ]; do
	[ -n "$(ls "$TEMP/run/claude-windows"/inst-* 2>/dev/null)" ] && break
	sleep 0.1; attente=$((attente + 1))
done
ordinaire=$(cat "$TEMP/run/claude-windows"/inst-* 2>/dev/null)
case "$ordinaire" in
	*"CW_SVC=spyder"*) echo "ECHEC une session ordinaire a ete prise pour un panneau"
	                   echecs=$((echecs + 1)) ;;
	*) echo "ok    session ordinaire : CW_SVC n'est pas « spyder »" ;;
esac
# Et la couleur, elle, est bien ecrite dans ce cas-la : c'est ce qui prouve que la
# condition ajoutee porte sur le panneau, et pas sur autre chose.
if grep -q ']11;' "$TEMP/sortie2.txt" 2>/dev/null; then
	echo "ok    session ordinaire : la couleur est toujours posee par OSC"
else
	echo "ECHEC la couleur n'est plus posee pour une session ordinaire"
	echecs=$((echecs + 1))
fi

echo
if [ "$echecs" -eq 0 ]; then
	echo "Tous les tests passent."
	exit 0
fi
echo "$echecs test(s) en echec."
exit 1

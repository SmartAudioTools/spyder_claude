#!/bin/bash
# Test d'interoperabilite : claude-statusline.sh, contre un JSON stdin capture a la main.
#
# C'EST LE SEUL TEST QUI TRAVERSE LA FRONTIERE entre le script bash et spyder_claude/usage.py.
# Les tests Python verifient que le panneau sait relire un fichier usage-<pid> ; celui-ci
# verifie que le script sait l'ECRIRE dans la forme attendue, avec le meme protocole que
# claude-window.sh pour identifier le process appelant (marche des ancetres jusqu'au premier
# avec un pty reel) et pour l'onglet Spyder (SPYDER_CLAUDE_PANE lu dans /proc).
#
# MEMES PRECAUTIONS que tests/test_hook_panneau.sh :
#   1. XDG_RUNTIME_DIR est deplace : le fichier ecrit est un faux, jamais celui de
#      l'utilisateur ;
#   2. le script est lance a travers `script`, qui lui donne un VRAI pty - sans quoi la
#      marche des ancetres echouerait des la premiere etape et rien ne serait ecrit ;
#   3. deux appels qui doivent partager la MEME ancre (le calcul de vitesse) sont lances
#      dans la MEME session `script`, pas dans deux invocations separees - sinon chacune
#      obtiendrait un ancetre de pid different, donc un fichier usage-<pid> different, et
#      la persistance de l'ancre entre deux appels ne serait jamais exercee.
#
# Lancement :  bash tests/test_statusline.sh

set -u

RACINE=$(dirname "$(dirname "$(dirname "$(dirname "$(realpath "${BASH_SOURCE[0]}")")")")")
SCRIPT="${SCRIPT:-$RACINE/config_files/Claude/claude-statusline.sh}"
[ -r "$SCRIPT" ] || { echo "ERREUR : $SCRIPT introuvable" >&2; exit 1; }

TEMP=$(mktemp -d "${TMPDIR:-/tmp}/test-statusline.XXXXXX") || exit 1
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
verifier_absent() {
	case "$2" in
		*"$3"*) printf 'ECHEC %s\n        « %s » ne devrait pas etre dans : %s\n' "$1" "$3" "$2"
		        echecs=$((echecs + 1)) ;;
		*) printf 'ok    %s\n' "$1" ;;
	esac
}
lire_cle() {
	# lire_cle FICHIER CLE : la valeur, ou vide si absente.
	awk -F= -v c="$2" '$1==c { print substr($0, length(c)+2) }' "$1" 2>/dev/null
}

MAINTENANT=$(date +%s)

# Charges JSON, chacune un cas nomme. `resets_at` a +2h et +2j de MAINTENANT pour eviter
# qu'un test lent a l'execution ne les fasse paraitre deja perimes.
cat > "$TEMP/complet.json" <<JSON
{"model":{"display_name":"claude-opus-4-8"},
 "context_window":{"used_percentage":42,
   "current_usage":{"cache_read_input_tokens":9000,"cache_creation_input_tokens":100,
                     "input_tokens":2}},
 "rate_limits":{"five_hour":{"used_percentage":55,"resets_at":$((MAINTENANT + 7200))},
                "seven_day":{"used_percentage":61,"resets_at":$((MAINTENANT + 172800))}},
 "cost":{"total_cost_usd":0.42}}
JSON

cat > "$TEMP/sans_rate_limits.json" <<JSON
{"model":{"display_name":"claude-sonnet-5"},
 "context_window":{"used_percentage":10,
   "current_usage":{"cache_read_input_tokens":0,"cache_creation_input_tokens":0,
                     "input_tokens":2}},
 "cost":{"total_cost_usd":0}}
JSON

# Lance $SCRIPT (une ou plusieurs fois, meme session `script` pour partager l'ancetre) avec
# stdin redirige depuis chaque fichier donne, chaque sortie et l'etat du registre apres
# chaque appel captures separement.
jouer() {
	local pane="$1"; shift
	rm -rf "$TEMP/run"; mkdir -p "$TEMP/run"
	local commande="" i=1 payload
	for payload in "$@"; do
		commande+="bash '$SCRIPT' < '$payload' > '$TEMP/sortie$i.txt' 2>&1; "
		commande+="cp \"\$XDG_RUNTIME_DIR/claude-windows\"/usage-* '$TEMP/apres$i.env' 2>/dev/null; "
		i=$((i + 1))
	done
	SPYDER_CLAUDE_PANE="$pane" XDG_RUNTIME_DIR="$TEMP/run" \
		script -qec "$commande" "$TEMP/script.log" >/dev/null 2>&1
}

echo "--- JSON complet : ligne de terminal et fichier usage-<pid> ---"
jouer "abc123" "$TEMP/complet.json"
sortie=$(cat "$TEMP/sortie1.txt" 2>/dev/null)
verifier_contient "contexte affiche"      "$sortie" "ctx 42%"
verifier_contient "fenetre 5h affichee"   "$sortie" "5 h 55%"
verifier_contient "reset 5h en heure"     "$sortie" "→"
verifier_contient "fenetre 7j affichee"   "$sortie" "7 j 61%"
verifier_contient "cout affiche"          "$sortie" "0.42 \$"

fichier="$TEMP/apres1.env"
verifier "CU_PANE est le bon onglet"    "$(lire_cle "$fichier" CU_PANE)"     "abc123"
verifier "CU_5H_PCT est relu"           "$(lire_cle "$fichier" CU_5H_PCT)"   "55"
verifier "CU_7J_PCT est relu"           "$(lire_cle "$fichier" CU_7J_PCT)"   "61"
verifier "CU_CENTIMES est en centimes" "$(lire_cle "$fichier" CU_CENTIMES)" "42"
verifier "premier echantillon : vitesse non mesurable" \
	"$(lire_cle "$fichier" CU_VITESSE)" "-1"
restes=$(ls "$TEMP/run/claude-windows"/usage-*.[0-9]* 2>/dev/null | wc -l)
verifier "aucun fichier temporaire laisse derriere" "$restes" "0"

echo
echo "--- rate_limits absent : sentinelles -1, segments omis de la ligne ---"
jouer "" "$TEMP/sans_rate_limits.json"
sortie=$(cat "$TEMP/sortie1.txt" 2>/dev/null)
verifier_absent "pas de segment 5h"  "$sortie" "5 h"
verifier_absent "pas de segment 7j"  "$sortie" "7 j"
verifier "CU_5H_PCT vaut -1 (absent)" "$(lire_cle "$TEMP/apres1.env" CU_5H_PCT)" "-1"
verifier "CU_7J_PCT vaut -1 (absent)" "$(lire_cle "$TEMP/apres1.env" CU_7J_PCT)" "-1"

echo
echo "--- Piege fr_FR : le montant ne doit jamais contenir de virgule ---"
# Le script force LC_ALL=C en interne ; on verifie que ca tient meme appele depuis un
# environnement ambiant en fr_FR - exactement le piege documente en tete du script.
rm -rf "$TEMP/run"; mkdir -p "$TEMP/run"
LC_ALL=fr_FR.UTF-8 XDG_RUNTIME_DIR="$TEMP/run" \
	bash "$SCRIPT" < "$TEMP/complet.json" > "$TEMP/sortie_locale.txt" 2>/dev/null
sortie=$(cat "$TEMP/sortie_locale.txt")
verifier_contient "le montant garde un point" "$sortie" "0.42 \$"
verifier_absent   "le montant n'a pas de virgule" "$sortie" "0,42"

echo
echo "--- Intervalle trop court : vitesse republiee, ancre NON deplacee ---"
cat > "$TEMP/petit_cout.json" <<JSON
$(sed 's/"total_cost_usd":0.42/"total_cost_usd":0.10/' "$TEMP/complet.json")
JSON
cat > "$TEMP/cout_plus_haut.json" <<JSON
$(sed 's/"total_cost_usd":0.42/"total_cost_usd":0.15/' "$TEMP/complet.json")
JSON
jouer "abc123" "$TEMP/petit_cout.json" "$TEMP/cout_plus_haut.json"
verifier "1er appel : premier echantillon, vitesse -1" \
	"$(lire_cle "$TEMP/apres1.env" CU_VITESSE)" "-1"
verifier "2eme appel, ecart trop court : vitesse toujours -1" \
	"$(lire_cle "$TEMP/apres2.env" CU_VITESSE)" "-1"
verifier "l'ancre du cout n'a PAS bouge (toujours 10, pas 15)" \
	"$(lire_cle "$TEMP/apres2.env" CU_COUT_PREC)" "10"

echo
echo "--- Cout qui redescend (/clear, /compact) : re-ancrage, pas de mensonge ---"
cat > "$TEMP/cout_haut.json" <<JSON
$(sed 's/"total_cost_usd":0.42/"total_cost_usd":0.90/' "$TEMP/complet.json")
JSON
cat > "$TEMP/cout_redescendu.json" <<JSON
$(sed 's/"total_cost_usd":0.42/"total_cost_usd":0.05/' "$TEMP/complet.json")
JSON
jouer "abc123" "$TEMP/cout_haut.json" "$TEMP/cout_redescendu.json"
verifier "cout redescendu : vitesse non mesurable, pas 0" \
	"$(lire_cle "$TEMP/apres2.env" CU_VITESSE)" "-1"
verifier "l'ancre a suivi le nouveau cout (5, pas 90)" \
	"$(lire_cle "$TEMP/apres2.env" CU_COUT_PREC)" "5"

echo
if [ "$echecs" -eq 0 ]; then
	echo "Tous les tests passent."
	exit 0
fi
echo "$echecs test(s) en echec."
exit 1

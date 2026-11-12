# -*- coding: utf-8 -*-
"""Echantillonneur de la boucle d'evenements du Claude Dock, declenche par un fichier.

SONDE TEMPORAIRE : a retirer, avec son appel dans main() de fenetre.py, une fois la frappe
jugee fluide - entree « CLAUDE DOCK - SONDES TEMPORAIRES A RETIRER » de TODO - Spyder.txt.

POURQUOI (12/11/2026, « taper au clavier reste tres saccade avec les 18 sessions ») : ni
py-spy ni ptrace depuis le compte claude, et relancer le dock avec un profileur coute la
restauration de toutes les sessions. Une fois cette sonde chargee, une mesure se demande
SANS relance :

    echo 20 > $XDG_RUNTIME_DIR/claude-windows/dock-echantillonner     (duree en secondes)

Pendant la duree, deux mesures, ecrites ensuite dans <dossier>/echantillons-<heure>.txt :
  - RETARD de la boucle : un QTimer de 10 ms note de combien chaque tic arrive en retard.
    C'est ce que sent le clavier, que le temps soit pris en Python OU en C++ (peinture Qt) ;
  - PILE Python du fil principal, relevee toutes les 5 ms par un fil a part
    (sys._current_frames) : fonctions en propre et cumulees. Une pile reduite a l'appel de
    exec() veut dire « Qt seul » : repos, ou travail C++ que le retard dira. Biais connu :
    le fil releveur attend le GIL, il sous-compte donc le Python qui tourne sans rendre la
    main (essai : 50 % de boucle Python vue a 32 %). Les PROPORTIONS entre fonctions Python
    restent justes, et le retard, lui, n'a pas ce biais.
"""
import collections
import os
import sys
import threading
import time

from qtpy.QtCore import QTimer

from spyder_claude.etat_instances import dossier_etat

DOSSIER_DEFAUT = "/DATA/Python/FORKS/SmartPythonEditor_generator_essais/dock_perf"
PAS_PILE = 0.005
PAS_RETARD_MS = 10


class Echantillonneur:
    def __init__(self, dossier=None):
        self._dossier = dossier or os.environ.get("CLAUDE_DOCK_ECHANTILLONS") or DOSSIER_DEFAUT
        self._fil_principal = threading.main_thread().ident
        self._veille = QTimer()
        self._veille.timeout.connect(self._regarder)
        self._veille.start(1000)
        self._tic = QTimer()
        self._tic.setInterval(PAS_RETARD_MS)
        self._tic.timeout.connect(self._noter_tic)
        self._en_cours = False

    def _regarder(self):
        declencheur = os.path.join(dossier_etat(), "dock-echantillonner")
        if self._en_cours or not os.path.exists(declencheur):
            return
        try:
            with open(declencheur, encoding="utf-8") as f:
                duree = float(f.read().strip() or 20)
            os.remove(declencheur)
        except (OSError, ValueError):
            duree = 20.0
        self._demarrer(max(1.0, min(duree, 300.0)))

    def _demarrer(self, duree):
        self._en_cours = True
        self._retards = []
        self._propre = collections.Counter()
        self._cumul = collections.Counter()
        self._piles = 0
        self._debut = time.perf_counter()
        self._cpu_debut = time.process_time()
        self._dernier_tic = self._debut
        self._tic.start()
        threading.Thread(target=self._relever_piles, args=(duree,), daemon=True).start()
        QTimer.singleShot(int(duree * 1000), self._finir)

    def _noter_tic(self):
        maintenant = time.perf_counter()
        self._retards.append((maintenant - self._dernier_tic) * 1000 - PAS_RETARD_MS)
        self._dernier_tic = maintenant

    def _relever_piles(self, duree):
        fin = time.perf_counter() + duree
        while time.perf_counter() < fin:
            cadre = sys._current_frames().get(self._fil_principal)
            vues = set()
            premier = True
            while cadre is not None:
                code = cadre.f_code
                nom = "%s:%d %s" % (os.path.basename(code.co_filename), code.co_firstlineno,
                                    code.co_name)
                if premier:
                    self._propre[nom] += 1
                    premier = False
                if nom not in vues:
                    self._cumul[nom] += 1
                    vues.add(nom)
                cadre = cadre.f_back
            self._piles += 1
            time.sleep(PAS_PILE)

    def _finir(self):
        self._tic.stop()
        mur = time.perf_counter() - self._debut
        cpu = time.process_time() - self._cpu_debut
        retards = sorted(self._retards) or [0.0]
        bloque = sum(r for r in retards if r > 20)
        lignes = [
            "duree %.1f s, CPU du processus %.1f s (%.0f %% d'un coeur), %d piles relevees"
            % (mur, cpu, 100 * cpu / mur, self._piles),
            "retard de la boucle (tic de %d ms, %d tics) : median %.1f ms, p90 %.1f, p99 %.1f, "
            "max %.1f ; temps perdu en blocages > 20 ms : %.1f s (%.0f %%)"
            % (PAS_RETARD_MS, len(retards), retards[len(retards) // 2],
               retards[int(len(retards) * 0.9)], retards[int(len(retards) * 0.99)],
               retards[-1], bloque / 1000, 100 * bloque / 1000 / mur),
            "", "EN PROPRE (haut de pile ; exec seul = Qt / C++ ou repos) :"]
        total = max(self._piles, 1)
        lignes += ["  %5.1f %%  %s" % (100 * n / total, nom)
                   for nom, n in self._propre.most_common(30)]
        lignes += ["", "CUMULE (present dans la pile) :"]
        lignes += ["  %5.1f %%  %s" % (100 * n / total, nom)
                   for nom, n in self._cumul.most_common(40)]
        try:
            os.makedirs(self._dossier, exist_ok=True)
            with open(os.path.join(self._dossier, time.strftime("echantillons-%H-%M-%S.txt")),
                      "w", encoding="utf-8") as f:
                f.write("\n".join(lignes) + "\n")
        except OSError:
            pass
        self._en_cours = False


def installer(parent=None):
    """La seule ligne a ajouter au demarrage du dock : `echantillonneur.installer()`.
    Garde une reference sur l'objet (sinon ses QTimer seraient detruits)."""
    global _INSTANCE
    _INSTANCE = Echantillonneur()
    return _INSTANCE


_INSTANCE = None

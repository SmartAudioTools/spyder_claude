# -*- coding: utf-8 -*-
"""Tests du protocole de consommation partage avec claude-statusline.sh.

CE QU'ILS PROUVENT : que le format ecrit par le script statusLine est bien celui que le
panneau relit, et que les regles de fraicheur/peremption/decroissance (cf. usage.py) font
ce qu'elles disent — y compris dans le sens ou un garde-fou doit rester SILENCIEUX (une
grandeur non mesurable ne doit jamais ressembler a une grandeur mesuree a zero).

Le registre est deplace par XDG_RUNTIME_DIR : aucun test n'ecrit dans le vrai dossier.

Lancement :
    python3 tests/test_usage.py
"""

import os
import re
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spyder_claude import usage  # noqa: E402

#: Le script statusLine, source des seuils recopies dans usage.SEUILS.
SCRIPT_STATUSLINE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))),
    "config_files", "Claude", "claude-statusline.sh")


class BaseUsage(unittest.TestCase):
    """Un registre jetable par test, dans un dossier temporaire."""

    def setUp(self):
        self.dossier_racine = tempfile.mkdtemp(prefix="claude-usage-")
        self._ancien = os.environ.get("XDG_RUNTIME_DIR")
        os.environ["XDG_RUNTIME_DIR"] = self.dossier_racine
        self.registre = usage.etat_instances.dossier_etat()
        os.makedirs(self.registre, exist_ok=True)

    def tearDown(self):
        if self._ancien is None:
            os.environ.pop("XDG_RUNTIME_DIR", None)
        else:
            os.environ["XDG_RUNTIME_DIR"] = self._ancien
        shutil.rmtree(self.dossier_racine, ignore_errors=True)

    def ecrire_usage(self, pid, **cles):
        """Ecrit un fichier usage-<pid> EXACTEMENT comme le fait claude-statusline.sh."""
        usage.deposer_usage(pid, cles, dossier=self.registre)


class TestLeFichierEstDuTexte(BaseUsage):

    def test_le_fichier_n_est_pas_execute(self):
        """Le fichier vit dans $XDG_RUNTIME_DIR : le sourcer donnerait a n'importe quel
        programme capable d'y ecrire les droits du processus qui le relit."""
        temoin = os.path.join(self.dossier_racine, "temoin")
        self.ecrire_usage(os.getpid(),
                          CU_5H_PCT="$(touch %s)74" % temoin,
                          CU_HORODATAGE=int(time.time()))
        usage.fenetres(dossier=self.registre)
        self.assertFalse(os.path.exists(temoin))

    def test_une_session_morte_est_ignoree(self):
        """Un PID libre ne doit rien alimenter — sinon une jauge reste figee pour toujours."""
        self.ecrire_usage(2 ** 31 - 1, CU_5H_PCT=74,
                          CU_HORODATAGE=int(time.time()))
        self.assertIsNone(usage.fenetres(dossier=self.registre)["cinq_heures"])


class TestFenetres(BaseUsage):

    def test_une_fenetre_absente_ne_rend_pas_zero(self):
        """Aucune session vivante : les deux fenetres sont None, jamais 0."""
        fenetres = usage.fenetres(dossier=self.registre)
        self.assertIsNone(fenetres["cinq_heures"])
        self.assertIsNone(fenetres["sept_jours"])
        self.assertIsNot(fenetres["cinq_heures"], 0)

    def test_la_valeur_la_plus_fraiche_gagne_pas_la_plus_grande(self):
        """Deux sessions vivantes : celle qui a l'echantillon le plus RECENT l'emporte,
        meme si son pourcentage est plus petit qu'une session plus ancienne — sinon une
        session inactive depuis ce matin garderait un pourcentage d'avant le reset."""
        maintenant = time.time()
        self.ecrire_usage(os.getpid(), CU_5H_PCT=90, CU_5H_FIN=0,
                          CU_HORODATAGE=int(maintenant - 3600))
        # Deuxieme fichier, PID different mais vivant lui aussi (le nôtre encore).
        pid2 = os.getpid()
        # Un seul pid vivant garanti dans le bac de test (le processus courant) : on
        # ecrit donc les deux echantillons sous deux noms differents en simulant deux
        # PIDs vivants via le meme pid n'est pas possible (un seul fichier par pid) —
        # on verifie donc le cas via _lire_usages avec deux pids reels du systeme.
        # Le pid du parent (init/systemd, pid 1) est garanti vivant sur toute machine Unix.
        self.ecrire_usage(1, CU_5H_PCT=40, CU_5H_FIN=0,
                          CU_HORODATAGE=int(maintenant - 10))
        resultat = usage.fenetres(dossier=self.registre, maintenant=maintenant)
        self.assertEqual(resultat["cinq_heures"]["pct"], 40)

    def test_une_fenetre_deja_reinitialisee_est_ignoree(self):
        """CU_5H_FIN deja passe : le quota a tourne, le chiffre ne veut plus rien dire."""
        maintenant = time.time()
        self.ecrire_usage(os.getpid(), CU_5H_PCT=74, CU_5H_FIN=int(maintenant - 60),
                          CU_HORODATAGE=int(maintenant - 30))
        self.assertIsNone(usage.fenetres(dossier=self.registre,
                                        maintenant=maintenant)["cinq_heures"])

    def test_une_fenetre_valide_porte_son_age(self):
        maintenant = time.time()
        self.ecrire_usage(os.getpid(), CU_7J_PCT=41, CU_7J_FIN=int(maintenant + 3600),
                          CU_HORODATAGE=int(maintenant - 120))
        fenetre = usage.fenetres(dossier=self.registre, maintenant=maintenant)["sept_jours"]
        self.assertEqual(fenetre["pct"], 41)
        self.assertAlmostEqual(fenetre["age"], 120, delta=1)


class TestVitesses(BaseUsage):

    def test_une_vitesse_non_mesurable_n_est_pas_une_vitesse_nulle(self):
        self.assertIsNone(usage.vitesse_decrue(None, 0))
        self.assertEqual(usage.vitesse_decrue(0, 0), 0.0)

    def test_la_vitesse_decroit_avec_le_silence(self):
        pleine = usage.vitesse_decrue(1200, usage.FENETRE_MIN)
        milieu = usage.vitesse_decrue(
            1200, (usage.FENETRE_MIN + usage.SILENCE_MAX) / 2)
        eteinte = usage.vitesse_decrue(1200, usage.SILENCE_MAX)
        self.assertEqual(pleine, 1200.0)
        self.assertAlmostEqual(milieu, 600.0, delta=1)
        self.assertEqual(eteinte, 0.0)

    def test_une_session_hors_spyder_ne_reclame_aucun_onglet(self):
        """CU_PANE vide : la session compte pour les fenetres globales, pas pour un
        onglet — une instance en fenetre Konsole n'a pas de tachymetre a colorer."""
        self.ecrire_usage(os.getpid(), CU_PANE="", CU_VITESSE=500,
                          CU_HORODATAGE=int(time.time()))
        self.assertEqual(usage.vitesses_par_onglet(dossier=self.registre), {})

    def test_une_session_de_panneau_est_indexee_par_onglet(self):
        maintenant = time.time()
        self.ecrire_usage(os.getpid(), CU_PANE="abc123", CU_VITESSE=500,
                          CU_HORODATAGE=int(maintenant))
        resultat = usage.vitesses_par_onglet(dossier=self.registre, maintenant=maintenant)
        self.assertEqual(resultat["abc123"], 500.0)



class TestSessions(BaseUsage):
    """Ce que le panneau memorise pour rouvrir les conversations au demarrage."""

    def test_une_session_de_panneau_donne_sa_conversation_et_son_dossier(self):
        self.ecrire_usage(os.getpid(), CU_PANE="abc123", CU_SESSION="5f0c-1d2e",
                          CU_DOSSIER="/chemin/avec espace")
        self.assertEqual(usage.sessions_par_onglet(dossier=self.registre),
                         {"abc123": ("5f0c-1d2e", "/chemin/avec espace")})

    def test_sans_conversation_connue_rien_a_rouvrir(self):
        """Ancienne statusline, ou pas encore passee : l'onglet est absent, pas
        associe a une conversation vide qu'un `claude -r` ne saurait pas rouvrir."""
        self.ecrire_usage(os.getpid(), CU_PANE="abc123", CU_VITESSE=500)
        self.assertEqual(usage.sessions_par_onglet(dossier=self.registre), {})

    def test_une_session_hors_spyder_n_est_pas_memorisee(self):
        self.ecrire_usage(os.getpid(), CU_PANE="", CU_SESSION="5f0c-1d2e")
        self.assertEqual(usage.sessions_par_onglet(dossier=self.registre), {})

class TestSeuils(unittest.TestCase):

    def test_les_seuils_sont_ceux_du_script(self):
        """Les seuils de couleur du panneau et de la ligne de terminal doivent s'accorder
        — sinon l'utilisateur voit deux alarmes differentes pour le meme chiffre."""
        if not os.path.exists(SCRIPT_STATUSLINE):
            self.skipTest("claude-statusline.sh pas encore ecrit")
        with open(SCRIPT_STATUSLINE, encoding="utf-8") as fichier:
            texte = fichier.read()
        cinq_heures = usage.SEUILS["cinq_heures"]
        sept_jours = usage.SEUILS["sept_jours"]
        self.assertIsNotNone(
            re.search(r'"%s\s+%s"' % cinq_heures, texte)
            or re.search(r"%s %s" % cinq_heures, texte),
            "seuils 5h introuvables tels quels dans le script")
        self.assertIsNotNone(
            re.search(r'"%s\s+%s"' % sept_jours, texte)
            or re.search(r"%s %s" % sept_jours, texte),
            "seuils 7j introuvables tels quels dans le script")


if __name__ == "__main__":
    unittest.main(verbosity=2)

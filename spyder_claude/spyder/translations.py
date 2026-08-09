# -*- coding: utf-8 -*-
"""Fonction de traduction du greffon.

Meme choix que spyder_konsole : `get_translation()` afficherait a chaque import
« Could not load translations for fr » tant qu'aucun catalogue .mo n'est fourni, soit du
bruit a chaque demarrage de Spyder. Les libelles sont ecrits en francais, la langue de
cette installation ; l'habillage `_(...)` reste pour pouvoir ajouter un catalogue plus
tard sans toucher au reste du code.
"""


def _(message):
    return message

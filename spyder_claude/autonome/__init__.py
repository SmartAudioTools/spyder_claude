# -*- coding: utf-8 -*-
"""Le dock Claude hors de Spyder : `claude-dock`, ou `python -m spyder_claude.autonome`.

QT_API, AVANT tout import de qtpy : le moteur Konsole (qtermwidget) est compile pour
PySide6, et qtpy prendrait PyQt5 par defaut — `QTermWidget(0, vue)` leve alors TypeError
(mesure du 11/10/2026). Meme regle que le lanceur de SmartPythonEditor (install.sh du
generator) : le binding reellement installe fait foi. Un QT_API deja pose est respecte.
"""

import importlib.util
import os

if "QT_API" not in os.environ and importlib.util.find_spec("PySide6") is not None:
    os.environ["QT_API"] = "pyside6"

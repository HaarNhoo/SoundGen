#!/usr/bin/env python3
# -*- coding: utf-8 -*-
R"""
compile l'ensemble de l'application avec toutes ses options;
Incrémente la version si ça réussit;
Version modifiée pour ce projet
----------------------------------------------------------------
Arnaud LAPIOS
Copyright (c) 2025 DALKIA. Tous droits réservés.
Ce code source est protégé par les lois sur le copyright.
Toute reproduction ou utilisation non autorisée est interdite.
----------------------------------------------------------------
"""

import subprocess
import sys
from SoundGen_winrt import __version__
# --- À CONFIGURER ---
# vérifier que la ligne de commande de nuitka convient aux besoins
NUIKTA_COMMAND = [
    "python",
    "-m",
    "nuitka",
    "--onefile",
    
    # "--standalone",
    # "--follow-imports",
    "--python-flag=isolated",
    "--python-flag=no_docstrings",
    "--python-flag=no_asserts",
    "--enable-plugin=tk-inter",
    "--remove-output",
    "--windows-console-mode=disable",
    "--output-dir=nuitka_dist",
    "--include-data-files=SoundGen.ico=SoundGen.ico",

    "--output-filename=SoundGen.exe",
    "--windows-icon-from-ico=SoundGen.ico",
    "--onefile-windows-splash-screen-image=SoundGen.png",
    "--product-name=SoundGen",
    f"--file-version={__version__}",
    f"--product-version={__version__}",
    "--copyright='Copyright 2025 Arnaud LAPIOS'",

    "SoundGen_winrt.py"
]

# --- LOGIQUE DU SCRIPT ---

def run_compilation():
    """Lance la commande Nuitka."""
    print(f"Lancement de la compilation Nuitka de la version {__version__} de SRP_gain...")
    print(f"Commande : {' '.join(NUIKTA_COMMAND)}\n")

    try:
        # Exécute la commande. check=True lèvera une exception si Nuitka échoue.
        subprocess.run(NUIKTA_COMMAND, check=True, text=True)
        print("\nCompilation Nuitka terminée avec succès.")
        return True
    except subprocess.CalledProcessError as e:
        print("\nERREUR: La compilation Nuitka a échoué.", file=sys.stderr)
        print(e, file=sys.stderr)
        return False
    except FileNotFoundError:
        print("\nERREUR: Commande 'python' ou 'nuitka' non trouvée.", file=sys.stderr)
        print("Assurez-vous que Nuitka est installé et que Python est dans votre PATH.", file=sys.stderr)
        return False

run_compilation()

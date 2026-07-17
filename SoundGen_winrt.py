#!/usr/bin/env python3
# -*- coding: utf-8 -*-
R"""
   ____                  _______       
  / __/__  __ _____  ___/ / ___/__ ___ 
 _\ \/ _ \/ // / _ \/ _  / (_ / -_) _ \
/___/\___/\_,_/_//_/\_,_/\___/\__/_//_/
Générateur de son 
Version WinRT/WinSDK (Windows 10/11+)
Neural Voices

Requirements :
    colorednoise==2.2.0
    numpy==2.3.4
    sounddevice==0.5.3
    winsdk==1.0.0b10

Arnaud LAPIOS
2025
"""
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import sys
import os
import io
import wave
import numpy as np
import sounddevice as sd
import colorednoise
import tempfile

# Importations pour WinSDK (TTS)
try:
    import asyncio
    # Importe les classes spécifiques de la nouvelle bibliothèque 'winsdk'
    from winsdk.windows.media.speechsynthesis import SpeechSynthesizer, VoiceInformation
    from winsdk.windows.storage.streams import DataReader, Buffer, InputStreamOptions
    # Garde une référence pour les Enums si nécessaire
    import winsdk.windows.media.speechsynthesis as wss
except ImportError:
    messagebox.showerror("Erreur d'importation",
                         "La bibliothèque 'winsdk' est requise.\n"
                         "Veuillez l'installer avec: pip install winsdk")
    sys.exit()

__version__ = "0.1.0.0"
__author__ = "Arnaud LAPIOS"
__contact__="haarnhoo@gmail.com"

# --- Enlève le splash screen ---
if "NUITKA_ONEFILE_PARENT" in os.environ:
    splash_filename = os.path.join(
        tempfile.gettempdir(),
        "onefile_%d_splash_feedback.tmp" % int(os.environ["NUITKA_ONEFILE_PARENT"]),
    )

    if os.path.exists(splash_filename):
        os.unlink(splash_filename)


class AudioGeneratorApp:
    """
    Classe principale de l'application du générateur de signaux audio.
    
    Gère l'interface graphique (Tkinter), le flux audio (sounddevice),
    la génération des signaux (numpy, colorednoise) et la synthèse vocale (winsdk).
    """

    def __init__(self, root):
        """
        Initialise l'application.
        
        Args:
            root (tk.Tk): La fenêtre racine de Tkinter.
        """
        self.root = root
        self.root.title("Générateur de Signaux Audio (WinSDK)")
        self.root.geometry("550x650") # Augmenté la hauteur pour le TTS

        # --- Icône ---
        try:
            self.root.iconbitmap(os.path.join(os.path.dirname(os.path.abspath(__file__)),"SoundGen.ico"))
        except tk.TclError:
            pass # Silencieux si l'icône n'est pas trouvée

        # --- Paramètres audio ---
        self.samplerate = 44100
        self.base_sweep_duration = 10

        # --- Variables d'état THREAD-SAFE ---
        # Ces variables sont partagées entre le thread GUI et le thread audio.
        # L'accès doit être protégé par self.lock.
        self.lock = threading.Lock()
        self.audio_mode = 'stop'
        self.audio_volume = 0.5
        self.audio_pan = 0.0
        self.audio_freq = 440.0
        self.audio_speed = 1.0
        self.audio_beta = 1 # Pour les bruits (1=rose)
        self.phase = 0.0
        self.current_sample_index = 0

        # Buffer TTS (partagé)
        self.tts_buffer = np.array([], dtype=np.float32)
        self.tts_buffer_index = 0
        # --- Fin des variables partagées ---

        self.stream = None # Le flux audio principal (sounddevice)

        # --- Références aux widgets ---
        self.btn_stop = None
        self.btn_speak = None
        self.tts_voice_combobox = None # Référence au widget ComboBox

        # --- Variables Tkinter (GUI-thread only) ---
        self.volume_var = tk.DoubleVar(value=self.audio_volume)
        self.pan_var = tk.DoubleVar(value=self.audio_pan)
        self.speed_var = tk.DoubleVar(value=self.audio_speed)

        # Pour la fréquence (MIDI)
        initial_freq = self.audio_freq
        self.freq_midi_note_var = tk.IntVar(value=self.freq_to_midi_note(initial_freq))
        self.freq_entry_var = tk.StringVar(value=f"{initial_freq:.2f}")

        # Pour le TTS
        self.tts_text_var = tk.StringVar(value="SoundGen ! Test, test. Test! One, two, tree.")
        self.tts_voice_var = tk.StringVar()
        self.tts_voices_map = {} # { "Nom Affiché": VoiceInformation }
        self.tts_is_speaking = False # Flag pour désactiver le bouton
        # --- Fin des variables Tkinter ---

        # --- Démarrage du Thread Asyncio ---
        # requis pour que winsdk fonctionne sans geler l'interface
        self.asyncio_loop = None
        self.async_thread = threading.Thread(target=self.start_asyncio_loop, daemon=True)
        self.async_thread.start()

        # --- Configuration de l'interface ---
        style = ttk.Style()
        style.configure("TButton", padding=6, relief="flat", font=('Helvetica', 10))
        style.configure("TLabel", padding=6, font=('Helvetica', 10))
        style.configure("TLabelFrame.Label", font=('Helvetica', 11, 'bold'))

        self.create_widgets()

        # Synchroniser les valeurs initiales des sliders vers les variables audio
        self.sync_params_to_audio_thread()

        # Initialiser la liste des voix (de manière asynchrone)
        self.init_tts_voice_list_async()

        # Démarrer le flux audio (après le lancement de mainloop)
        self.root.after(50, self.start_stream)

        # Démarrer la boucle de vérification de l'état des boutons
        self.update_button_states()

        # Gérer la fermeture propre de la fenêtre
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # --- Gestion de la boucle Asyncio (pour WinSDK) ---

    def start_asyncio_loop(self):
        """
        Démarre et maintient une boucle d'événements asyncio dans un thread séparé.
        C'est nécessaire pour tous les appels asynchrones de winsdk.
        """
        try:
            self.asyncio_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.asyncio_loop)
            self.asyncio_loop.run_forever()
        except Exception as e:
            print(f"Erreur fatale dans la boucle asyncio: {e}")

    def submit_async_task(self, coro):
        """
        Soumet une coroutine à la boucle asyncio (thread-safe).
        
        Args:
            coro: La coroutine (fonction async) à exécuter.
        """
        if not self.asyncio_loop:
            print("Erreur: Boucle Asyncio non démarrée.")
            return None
        # Exécute la coroutine dans le thread de la boucle asyncio
        return asyncio.run_coroutine_threadsafe(coro, self.asyncio_loop)

    # --- Initialisation des voix (Async) ---

    def init_tts_voice_list_async(self):
        """
        Lance la tâche asynchrone pour récupérer les voix TTS.
        S'auto-rappelle si la boucle asyncio n'est pas encore prête.
        """
        if not self.asyncio_loop:
            # Réessaye si la boucle n'est pas encore prête
            self.root.after(100, self.init_tts_voice_list_async)
            return
        self.submit_async_task(self._async_get_voices())

    async def _async_get_voices(self):
        """
        [Thread ASYNC] Récupère la liste de toutes les voix (neurales incluses)
        auprès de l'API WinSDK.
        """
        try:
            voices_map = {}

            # Récupère les voix via les propriétés statiques de l'API
            default_voice = SpeechSynthesizer.default_voice
            all_voices = SpeechSynthesizer.all_voices

            # Tente de trouver Zira par défaut
            default_name = default_voice.display_name
            zira_found = False

            for voice in all_voices:
                name = voice.display_name
                voices_map[name] = voice
                if "zira" in name.lower():
                    default_name = name
                    zira_found = True

            if not zira_found and default_name not in voices_map:
                 # Si Zira n'est pas trouvée ET que la voix système par défaut n'est pas listée (rare)
                 if default_voice:
                    voices_map[default_voice.display_name] = default_voice
                 else: # Si aucune voix n'est trouvée
                    default_name = "Aucune voix trouvée"

            if not voices_map:
                voices_map = {"Aucune voix trouvée": None}
                default_name = "Aucune voix trouvée"

            # Renvoie les données au thread GUI via self.root.after (thread-safe)
            self.root.after(0, self.populate_voice_list_gui, voices_map, default_name)

        except Exception as e:
            print(f"Erreur (async) lors de la récupération des voix: {e}")
            self.root.after(0, self.show_tts_error_message, e)

    def populate_voice_list_gui(self, voices_map, default_name):
        """
        [Thread GUI] Met à jour le ComboBox avec les voix récupérées.
        Appelé par _async_get_voices via self.root.after.
        
        Args:
            voices_map (dict): Dictionnaire {nom_voix: VoiceInformation}.
            default_name (str): Nom de la voix à sélectionner par défaut.
        """
        print("Mise à jour de la GUI avec la liste des voix.")
        self.tts_voices_map = voices_map
        voice_names = list(self.tts_voices_map.keys())

        if self.tts_voice_combobox:
            self.tts_voice_combobox['values'] = voice_names

        if default_name in self.tts_voices_map:
            self.tts_voice_var.set(default_name)
        elif voice_names:
            self.tts_voice_var.set(voice_names[0])

        # Active le bouton "Parler" si des voix sont disponibles
        if self.btn_speak and self.tts_voices_map.get(default_name) is not None:
            self.btn_speak.config(state='normal')

    def show_tts_error_message(self, e):
        """
        [Thread GUI] Affiche une boîte d'erreur si le TTS échoue à l'initialisation.
        """
        messagebox.showerror("Erreur TTS (WinSDK)",
                             f"Impossible d'initialiser ou de récupérer les voix.\nErreur: {e}\n"
                             "L'application va continuer sans TTS.")
        if self.btn_speak:
            self.btn_speak.config(state='disabled')

    # --- Fonctions de conversion (Fréquence/MIDI) ---

    def midi_note_to_freq(self, midi_note):
        """
        Convertit un numéro de note MIDI (ex: 69) en fréquence (ex: 440.0).
        Utilise la note A4 (69) comme référence (440 Hz).
        """
        return (440.0 / 32.0) * (2.0**((midi_note - 9.0) / 12.0))

    def freq_to_midi_note(self, freq):
        """
        Convertit une fréquence en numéro de note MIDI (le plus proche).
        
        Args:
            freq (float): Fréquence en Hz.
        
        Returns:
            int: Le numéro de note MIDI le plus proche.
        """
        if freq <= 0:
            return 0 # Évite l'erreur de log
        midi_note = 12 * np.log2((freq * 32.0) / 440.0) + 9
        return int(round(midi_note))

    # --- Callbacks de l'interface (Fréquence) ---

    def on_freq_slider_change(self, val_str):
        """
        [Callback GUI] Appelé quand le slider de fréquence (MIDI) bouge.
        
        Args:
            val_str (str): La nouvelle valeur du slider (une note MIDI).
        """
        self.update_freq_controls_from_slider(val_str)
        self.sync_params_to_audio_thread() # Met à jour la variable audio

    def on_freq_entry_update(self, event=None):
        """
        [Callback GUI] Appelé quand l'utilisateur valide l'entrée de fréquence (Entrée ou FocusOut).
        """
        self.update_freq_controls_from_entry()
        self.sync_params_to_audio_thread() # Met à jour la variable audio
        return "break" # Empêche le "ding"

    def update_freq_controls_from_slider(self, val_str):
        """
        [GUI] Met à jour le champ de saisie (Hz) lorsque le slider (MIDI) bouge.
        
        Args:
            val_str (str): La nouvelle valeur du slider (une note MIDI).
        """
        midi_note = int(round(float(val_str)))
        freq = self.midi_note_to_freq(midi_note)
        self.freq_entry_var.set(f"{freq:.2f}")

    def update_freq_controls_from_entry(self, event=None):
        """
        [GUI] Met à jour le slider (MIDI) lorsque l'utilisateur valide le champ (Hz).
        "Snap" la fréquence entrée à la note MIDI la plus proche.
        """
        try:
            freq = float(self.freq_entry_var.get())
            # "Snap" à la note MIDI la plus proche
            midi_note = self.freq_to_midi_note(freq)
            freq_snapped = self.midi_note_to_freq(midi_note)

            self.freq_midi_note_var.set(midi_note)
            self.freq_entry_var.set(f"{freq_snapped:.2f}")
        except ValueError:
            # Si l'entrée est invalide, réinitialiser au slider
            self.update_freq_controls_from_slider(str(self.freq_midi_note_var.get()))

    def sync_params_to_audio_thread(self, event=None):
        """
        [GUI] Met à jour les variables "miroirs" (thread-safe) pour le thread audio.
        Appelé par les sliders et les changements d'entrée.
        """
        # Récupère les valeurs depuis les widgets TK (thread-safe car GUI thread)
        volume = self.volume_var.get()
        pan = self.pan_var.get()
        speed = self.speed_var.get()
        midi_note = self.freq_midi_note_var.get()
        freq = self.midi_note_to_freq(midi_note)

        # Met à jour les variables partagées sous verrou
        with self.lock:
            self.audio_volume = volume
            self.audio_pan = pan
            self.audio_speed = speed
            self.audio_freq = freq

    # --- Création des Widgets ---

    def create_widgets(self):
        """
        [GUI] Crée et place tous les éléments de l'interface graphique.
        """
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Frame des contrôles (sliders) ---
        controls_frame = ttk.LabelFrame(main_frame, text="Contrôles", padding="10")
        controls_frame.pack(fill=tk.X, expand=True, pady=5)

        slider_length = 450 # Longueur uniforme

        # Volume
        ttk.Label(controls_frame, text="Volume:").grid(row=0, column=0, sticky="w", padx=5)
        tk.Scale(controls_frame, from_=0.0, to=1.0, orient=tk.HORIZONTAL,
                  variable=self.volume_var, length=slider_length,
                  tickinterval=0.2, resolution=0.01,
                  command=self.sync_params_to_audio_thread).grid(row=0, column=1, sticky="we")

        # Balance (Pan)
        ttk.Label(controls_frame, text="Balance (G/D):").grid(row=1, column=0, sticky="w", padx=5)
        tk.Scale(controls_frame, from_=-1.0, to=1.0, orient=tk.HORIZONTAL,
                  variable=self.pan_var, length=slider_length,
                  tickinterval=0.5, resolution=0.1,
                  command=self.sync_params_to_audio_thread).grid(row=1, column=1, sticky="we")

        # Fréquence Fixe (MIDI)
        min_midi = -9 # 5 Hz
        max_midi = 135 # 20865 Hz
        ttk.Label(controls_frame, text="Fréquence:").grid(row=2, column=0, sticky="w", padx=5)
        tk.Scale(controls_frame, from_=min_midi, to=max_midi, orient=tk.HORIZONTAL,
                  variable=self.freq_midi_note_var, command=self.on_freq_slider_change,
                  length=slider_length, tickinterval=12, resolution=1).grid(row=2, column=1, sticky="we")

        # Champ de saisie Fréquence
        freq_entry_frame = ttk.Frame(controls_frame)
        freq_entry_frame.grid(row=3, column=1, sticky="w", pady=5)

        entry = ttk.Entry(freq_entry_frame, textvariable=self.freq_entry_var, width=10)
        entry.pack(side=tk.LEFT)
        entry.bind("<Return>", self.on_freq_entry_update)
        entry.bind("<FocusOut>", self.on_freq_entry_update)
        ttk.Label(freq_entry_frame, text="Hz (Appuyez sur Entrée pour 'snapper')").pack(side=tk.LEFT, padx=5)


        # Vitesse du Sweep
        ttk.Label(controls_frame, text="Vitesse Balayage:").grid(row=4, column=0, sticky="w", padx=5)
        tk.Scale(controls_frame, from_=0.5, to=10.0, orient=tk.HORIZONTAL,
                  variable=self.speed_var, length=slider_length,
                  tickinterval=1.0, resolution=0.1,
                  command=self.sync_params_to_audio_thread).grid(row=4, column=1, sticky="we")

        # Fait en sorte que les sliders s'étendent sur la largeur
        controls_frame.columnconfigure(1, weight=1)

        # --- Frame TTS ---
        tts_frame = ttk.LabelFrame(main_frame, text="Text-to-Speech (WinSDK)", padding="10")
        tts_frame.pack(fill=tk.X, expand=True, pady=5)

        tts_entry = ttk.Entry(tts_frame, textvariable=self.tts_text_var)
        tts_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))

        # Sauvegarde la référence au ComboBox pour y ajouter les voix plus tard
        self.tts_voice_combobox = ttk.Combobox(tts_frame, textvariable=self.tts_voice_var, state='readonly', width=30)
        self.tts_voice_combobox.pack(side=tk.LEFT)

        # --- Frame des boutons ---
        buttons_frame = ttk.LabelFrame(main_frame, text="Générer", padding="10")
        buttons_frame.pack(fill=tk.BOTH, expand=True)
        buttons_frame.columnconfigure((0, 1, 2, 3), weight=1) # Poids pour tous

        # Ligne 1: Bruits (Grid)
        noise_buttons_frame = ttk.Frame(buttons_frame)
        noise_buttons_frame.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 5))

        btn_brown = ttk.Button(noise_buttons_frame, text="Bruit Brun", command=self.start_brown_noise)
        btn_pink = ttk.Button(noise_buttons_frame, text="Bruit Rose", command=self.start_pink_noise)
        btn_white = ttk.Button(noise_buttons_frame, text="Bruit Blanc", command=self.start_white_noise)
        btn_blue = ttk.Button(noise_buttons_frame, text="Bruit Bleu", command=self.start_blue_noise)
        btn_violet = ttk.Button(noise_buttons_frame, text="Bruit Violet", command=self.start_violet_noise)

        # Configuration Grid pour les largeurs relatives (Rose = 2x)
        noise_buttons_frame.columnconfigure(0, weight=1) # Brun
        noise_buttons_frame.columnconfigure(1, weight=2) # Rose (2x)
        noise_buttons_frame.columnconfigure(2, weight=1) # Blanc
        noise_buttons_frame.columnconfigure(3, weight=1) # Bleu
        noise_buttons_frame.columnconfigure(4, weight=1) # Violet

        btn_brown.grid(row=0, column=0, sticky="ew", padx=2)
        btn_pink.grid(row=0, column=1, sticky="ew", padx=2)
        btn_white.grid(row=0, column=2, sticky="ew", padx=2)
        btn_blue.grid(row=0, column=3, sticky="ew", padx=2)
        btn_violet.grid(row=0, column=4, sticky="ew", padx=2)

        # Ligne 2: Autres (Grid)
        btn_sweep = ttk.Button(buttons_frame, text="Balayage", command=self.start_sweep)
        btn_sweep.grid(row=1, column=0, sticky="ew", padx=5)

        btn_fixed = ttk.Button(buttons_frame, text="Fréquence", command=self.start_fixed_freq)
        btn_fixed.grid(row=1, column=1, sticky="ew", padx=5)

        self.btn_speak = ttk.Button(buttons_frame, text="Parler", command=self.start_tts_speak, state='disabled')
        self.btn_speak.grid(row=1, column=2, sticky="ew", padx=5)

        self.btn_stop = ttk.Button(buttons_frame, text="Stop", command=self.stop_audio, state='disabled')
        self.btn_stop.grid(row=1, column=3, sticky="ew", padx=5)

    # --- Fonctions de démarrage des signaux ---

    def start_pink_noise(self):
        """[GUI] Démarre la génération de bruit rose (beta=1)."""
        self.sync_params_to_audio_thread()
        with self.lock:
            self.audio_mode = 'noise'
            self.audio_beta = 1

    def start_white_noise(self):
        """[GUI] Démarre la génération de bruit blanc (beta=0)."""
        self.sync_params_to_audio_thread()
        with self.lock:
            self.audio_mode = 'noise'
            self.audio_beta = 0

    def start_brown_noise(self):
        """[GUI] Démarre la génération de bruit brun (beta=2)."""
        self.sync_params_to_audio_thread()
        with self.lock:
            self.audio_mode = 'noise'
            self.audio_beta = 2

    def start_blue_noise(self):
        """[GUI] Démarre la génération de bruit bleu (beta=-1)."""
        self.sync_params_to_audio_thread()
        with self.lock:
            self.audio_mode = 'noise'
            self.audio_beta = -1

    def start_violet_noise(self):
        """[GUI] Démarre la génération de bruit violet (beta=-2)."""
        self.sync_params_to_audio_thread()
        with self.lock:
            self.audio_mode = 'noise'
            self.audio_beta = -2

    def start_sweep(self):
        """[GUI] Démarre ou redémarre le balayage (sweep)."""
        self.sync_params_to_audio_thread()
        with self.lock:
            self.audio_mode = 'sweep'
            self.current_sample_index = 0 # Réinitialise le sweep

    def start_fixed_freq(self):
        """[GUI] Démarre la génération de fréquence fixe."""
        self.sync_params_to_audio_thread()
        with self.lock:
            self.audio_mode = 'fixed'
            self.phase = 0.0 # Réinitialise la phase

    def stop_audio(self):
        """
        [GUI] Arrête toute génération de son (y compris TTS) et réactive le bouton 'Parler'
        si le TTS a été interrompu.
        """
        was_speaking = self.tts_is_speaking
        with self.lock:
            self.audio_mode = 'stop'
            # Force la fin du buffer TTS, au cas où
            self.tts_buffer_index = len(self.tts_buffer)

        # Si on a interrompu le TTS (soit en génération, soit en lecture)
        # on réactive le bouton 'Parler' manuellement via le thread GUI.
        if was_speaking:
            self.root.after(0, self.on_tts_finished)

    # --- Fonctions TTS (WinSDK) ---

    def start_tts_speak(self):
        """
        [GUI] Démarre la tâche de synthèse vocale asynchrone.
        Appelé par le bouton "Parler".
        """
        # Vérifie si le TTS est déjà en cours ou si l'asyncio n'est pas prêt
        if self.tts_is_speaking or not self.asyncio_loop:
            return

        text = self.tts_text_var.get()
        voice_name = self.tts_voice_var.get()
        voice_object = self.tts_voices_map.get(voice_name)

        if not text.strip() or not voice_object:
            messagebox.showwarning("TTS", "Veuillez entrer du texte et sélectionner une voix.")
            return

        # Définit les flags pour l'interface
        self.tts_is_speaking = True
        self.btn_speak.config(state='disabled')
        self.stop_audio() # Arrête tout son en cours

        # Soumet la tâche de synthèse au thread asyncio
        self.submit_async_task(self._tts_task_run_async(text, voice_object))

    async def _tts_task_run_async(self, text, voice):
        """
        [Thread ASYNC] Tâche de synthèse: 
        1. Génère la parole via WinSDK (async).
        2. Lit le flux audio (WAV en mémoire).
        3. Le décode, le convertit en float32, le rééchantillonne.
        4. Place le résultat dans self.tts_buffer pour que l'audio_callback le joue.
        
        Args:
            text (str): Le texte à synthétiser.
            voice (VoiceInformation): L'objet voix WinSDK à utiliser.
        """
        print("Démarrage de la synthèse vocale (async)...")
        try:
            synthesizer = SpeechSynthesizer()
            synthesizer.voice = voice

            # 1. Synthétiser vers un flux en mémoire (format WAV par défaut)
            stream = await synthesizer.synthesize_text_to_stream_async(text)
            if not stream or stream.size == 0:
                raise Exception("La synthèse n'a retourné aucun flux.")

            # 2. Lire le flux en bytes (méthode robuste)
            stream_size = int(stream.size) # Convertit uint64 en int
            data_reader = DataReader(stream.get_input_stream_at(0))
            await data_reader.load_async(stream_size)

            # Créer un bytearray de la bonne taille
            data_bytes = bytearray(stream_size)
            # Demander au DataReader de remplir ce bytearray (méthode in-place)
            data_reader.read_bytes(data_bytes)

            data_reader.close()

            # 3. Utiliser 'io' et 'wave' pour lire le format des données WAV en mémoire
            pcm_data = np.array([], dtype=np.int16)
            source_rate = self.samplerate
            source_channels = 1

            try:
                with io.BytesIO(data_bytes) as in_memory_wav:
                    with wave.open(in_memory_wav, 'rb') as wav_file:
                        # Lire les métadonnées WAV
                        source_channels = wav_file.getnchannels()
                        source_bits = wav_file.getsampwidth() * 8
                        source_rate = wav_file.getframerate()
                        n_frames = wav_file.getnframes()

                        print(f"Format audio WAV (lu): {source_rate} Hz, {source_channels} canaux, {source_bits} bits")

                        if source_bits != 16:
                             raise Exception(f"Format de bits WAV non supporté: {source_bits}")

                        # Lire les données audio
                        frames_data = wav_file.readframes(n_frames)
                        pcm_data = np.frombuffer(frames_data, dtype=np.int16)

            except wave.Error as wave_err:
                print(f"Erreur lors de la lecture du WAV en mémoire: {wave_err}")
                print("Le flux WinSDK n'est peut-être pas un WAV. Tentative de décodage PCM brut...")
                # Fallback: Si ce n'est pas un WAV, suppose PCM 16-bit 22050Hz
                pcm_data = np.frombuffer(data_bytes, dtype=np.int16)
                source_rate = 22050 # Fréquence de fallback commune pour le TTS
                source_channels = 1

            # Si la source est stéréo, on la moyenne en mono
            if source_channels > 1:
                pcm_data_stereo = pcm_data.reshape(-1, source_channels)
                pcm_data = pcm_data_stereo.mean(axis=1).astype(np.int16)

            # 4. Convertir en float32 (normalisé entre -1.0 et 1.0)
            float_data = pcm_data.astype(np.float32) / 32768.0

            # 5. Rééchantillonner (Resample) de source_rate -> self.samplerate
            if source_rate != self.samplerate:
                num_source_samples = len(float_data)
                num_target_samples = int(num_source_samples * self.samplerate / source_rate)

                # Interpolation linéaire simple (efficace)
                source_time = np.linspace(0, 1, num_source_samples)
                target_time = np.linspace(0, 1, num_target_samples)

                resampled_data = np.interp(target_time, source_time, float_data)
            else:
                resampled_data = float_data # Pas besoin de rééchantillonner

            # 6. Publier le buffer pour le callback audio (thread-safe)
            with self.lock:
                self.tts_buffer = resampled_data
                self.tts_buffer_index = 0
                self.audio_mode = 'tts' # L'audio_callback va prendre le relais

        except Exception as e:
            print(f"Erreur (async) lors de la synthèse TTS: {e}")
            # Réactive le bouton même en cas d'erreur
            self.root.after(0, self.on_tts_finished)

    def on_tts_finished(self):
        """
        [Thread GUI] Réactive le bouton "Parler".
        Appelé depuis le callback audio (fin de lecture) ou stop_audio (interruption).
        Gère la concurrence pour n'être exécuté qu'une fois.
        """
        # S'assure que cela s'exécute sur le thread GUI
        if threading.current_thread() != threading.main_thread():
            self.root.after(0, self.on_tts_finished)
            return

        if self.tts_is_speaking: # Évite les appels multiples
            print("Lecture TTS terminée, réactivation du bouton.")
            self.tts_is_speaking = False
            if self.btn_speak: # S'assure que le bouton existe
                self.btn_speak.config(state='normal')

    # --- Boucle de mise à jour et Callback Audio ---

    def update_button_states(self):
        """
        [Thread GUI] Boucle périodique pour mettre à jour l'état du bouton "Stop".
        """

        with self.lock:
            # Le son est considéré comme "joué" si :
            # 1. Le mode n'est pas 'stop'
            # 2. OU le TTS est en cours de *génération* (avant que l'audio_callback ne démarre)
            is_playing = (self.audio_mode != 'stop') or self.tts_is_speaking

        if self.btn_stop: # S'assure que le bouton existe
            current_state = str(self.btn_stop.cget('state'))

            if is_playing and current_state == 'disabled':
                self.btn_stop.config(state='normal')
            elif not is_playing and current_state == 'normal':
                self.btn_stop.config(state='disabled')

        # Continue la boucle
        self.root.after(100, self.update_button_states)

    def audio_callback(self, outdata, frames, time_info, status):
        """
        [Thread AUDIO] La fonction principale de génération audio.
        S'exécute sur un thread audio haute priorité.
        NE DOIT PAS contenir d'appels à tkinter.
        
        Args:
            outdata (np.ndarray): Le buffer de sortie à remplir (frames x 2 canaux).
            frames (int): Le nombre d'échantillons (frames) à générer.
            time_info: Informations de temps (non utilisé).
            status (sounddevice.CallbackFlags): Flags de statut (ex: underflow).
        """
        if status:
            print(status, flush=True)

        # 1. Copie thread-safe des paramètres (rapide)
        with self.lock:
            mode = self.audio_mode
            volume = self.audio_volume
            pan = self.audio_pan
            freq = self.audio_freq
            speed = self.audio_speed
            beta = self.audio_beta
            phase = self.phase
            index = self.current_sample_index

            # Spécifique au TTS
            tts_data = self.tts_buffer
            tts_index = self.tts_buffer_index

        # 2. Génération du signal (mono)
        try:
            if mode == 'noise':
                # Génère un bruit coloré basé sur l'exposant beta
                data = colorednoise.powerlaw_psd_gaussian(beta, frames).astype(np.float32)
                data *= 0.2 # Normalisation du volume

            elif mode == 'fixed':
                # Fréquence fixe (sinus)
                phase_increment = (2 * np.pi * freq) / self.samplerate
                t = (phase + np.arange(frames) * phase_increment)
                data = 0.5 * np.sin(t).astype(np.float32)
                phase = (phase + frames * phase_increment) % (2 * np.pi) # Garde la phase

            elif mode == 'sweep':
                # Balayage (Sweep) logarithmique
                duration_sec = self.base_sweep_duration / speed
                total_samples = int(duration_sec * self.samplerate)

                if index >= total_samples:
                    # Le sweep est terminé
                    data = np.zeros(frames, dtype=np.float32)
                    mode = 'stop' # Signal pour arrêter
                else:
                    # Calcule le temps normalisé pour ce bloc
                    t_norm = (index + np.arange(frames)) / total_samples

                    # Gère la fin du sweep au milieu d'un bloc
                    if t_norm.max() >= 1.0:
                        end_point = np.argmax(t_norm >= 1.0)
                        t_norm[end_point:] = 0.0
                        data = np.zeros(frames, dtype=np.float32)
                    else:
                        data = np.empty(frames, dtype=np.float32)

                    # Fréquence instantanée (logarithmique)
                    f_start, f_end = 5.0, 20000.0
                    f_inst = f_start * (f_end / f_start)**t_norm
                    phase_increment = (2 * np.pi * f_inst) / self.samplerate
                    # Intègre la phase (cumsum)
                    t = phase + np.cumsum(phase_increment)
                    data = 0.5 * np.sin(t).astype(np.float32)

                    if 'end_point' in locals():
                        data[end_point:] = 0.0 # Met le reste du buffer à zéro
                    phase = t[-1] % (2 * np.pi) # Garde la phase
                index += frames

            elif mode == 'tts':
                # Lit depuis le buffer TTS
                samples_needed = frames
                samples_available = len(tts_data) - tts_index

                if samples_available >= samples_needed:
                    # Assez de données dans le buffer
                    data = tts_data[tts_index : tts_index + samples_needed]
                    tts_index += samples_needed
                else:
                    # Pas assez de données, fin du buffer
                    data = np.zeros(frames, dtype=np.float32)
                    if samples_available > 0:
                        # Joue les derniers échantillons restants
                        data[:samples_available] = tts_data[tts_index:]
                    tts_index = len(tts_data) # Marque comme terminé
                    mode = 'stop' # Signal pour arrêter
                    # Informe le GUI (thread-safe) que le TTS est terminé
                    self.root.after(0, self.on_tts_finished)

            else: # mode == 'stop'
                data = np.zeros(frames, dtype=np.float32)

            # 3. Application du volume et de la balance (stéréo)
            # Panoramique à puissance constante pour éviter une baisse de volume au centre
            pan_rad = (pan + 1.0) * 0.5 * (np.pi / 2.0)
            gain_left = np.cos(pan_rad)
            gain_right = np.sin(pan_rad)

            left_channel = data * volume * gain_left
            right_channel = data * volume * gain_right

            # Remplit le buffer de sortie
            outdata[:, 0] = left_channel
            outdata[:, 1] = right_channel

            # 4. Mise à jour thread-safe de l'état (rapide)
            with self.lock:
                self.phase = phase
                self.current_sample_index = index
                self.tts_buffer_index = tts_index
                if mode == 'stop':
                    self.audio_mode = 'stop'

        except Exception as e:
            print(f"Erreur dans le callback audio: {e}", flush=True)
            outdata.fill(0) # Remplit de silence en cas d'erreur

    # --- Gestion du flux SoundDevice ---

    def start_stream(self):
        """
        [GUI] Initialise et démarre le flux audio stéréo (sounddevice).
        Utilise le périphérique de sortie par défaut du système.
        """
        try:
            self.stream = sd.OutputStream(
                samplerate=self.samplerate,
                channels=2, # Stéréo
                callback=self.audio_callback,
                dtype='float32'
            )
            self.stream.start()
            print("Démarrage du flux audio (sounddevice)...")

        except Exception as e:
            print(f"Erreur critique au démarrage du flux audio: {e}", flush=True)
            messagebox.showerror("Erreur Audio",
                                 f"Impossible de démarrer le flux audio.\nErreur: {e}\n\n"
                                 "Vérifiez vos périphériques de sortie audio."
                                 )
            self.root.destroy()

    def stop_stream_safely(self):
        """
        [GUI] Arrête et ferme le flux audio. (Non utilisé dans l'architecture WinSDK).
        """
        print("Arrêt du flux audio (sounddevice)...")
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception as e:
                print(f"Erreur lors de l'arrêt du flux: {e}")
            self.stream = None

    def on_close(self):
        """
        [GUI] Gère la fermeture propre de la fenêtre.
        Arrête le flux audio et le thread asyncio.
        """
        print("Fermeture de l'application...")
        if self.stream:
            self.stream.stop()
            self.stream.close()

        # Arrête la boucle asyncio proprement
        if self.asyncio_loop:
            self.asyncio_loop.call_soon_threadsafe(self.asyncio_loop.stop)
            self.async_thread.join(timeout=1.0) # Attend que le thread se termine

        self.root.destroy()
        sys.exit()

# --- Point d'entrée de l'application ---
if __name__ == "__main__":
    try:
        root = tk.Tk()
        app = AudioGeneratorApp(root)
        root.mainloop()
    except Exception as e:
        print(f"Erreur fatale au démarrage: {e}")
        messagebox.showerror("Erreur Fatale", f"Une erreur critique est survenue: {e}")
        sys.exit(1)
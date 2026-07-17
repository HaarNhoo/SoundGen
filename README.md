**SoundGen** is a robust Python-based desktop application designed to generate high-quality audio signals, colored noises, and perform Text-to-Speech (TTS) synthesis natively on Windows.

## 🚀 Features

*   **Colored Noise Generation**: Generate various noise profiles based on power-law dynamics, including White, Pink, Brown, Blue, and Violet noise.
*   **Tone & Sweep Generator**:
    *   **Fixed Frequency**: Sine wave generator with a slider linked to MIDI note values (snaps to exact musical frequencies).
    *   **Logarithmic Sweep**: Configurable frequency sweep (5 Hz to 20,000 Hz) with adjustable speed.
*   **Native Windows Text-to-Speech (TTS)**: Leverages `winsdk` to access native Windows 10/11 voices, including high-quality Neural Voices, synthesized directly into the application's audio stream.
*   **Real-time Audio Control**: Instantly adjust Master Volume and Pan (Left/Right stereo balance) without interrupting the audio stream.
*   **Thread-Safe Architecture**: Uses a dedicated high-priority audio thread (`sounddevice`) alongside an asynchronous event loop for UI responsiveness and stutter-free audio processing.

## 📋 Requirements

This application requires **Windows 10 or Windows 11** due to the `winsdk` dependency used for the native speech synthesis API.

The following Python packages are required:

```txt
colorednoise==2.2.0
numpy==2.3.4
sounddevice==0.5.3
winsdk==1.0.0b10

```

## 🛠️ Installation

1. Clone or download the repository to your local machine.
2. (Optional but recommended) Create a virtual environment:
```bash
python -m venv venv
source venv/Scripts/activate  # On Windows

```


3. Install the dependencies:
```bash
pip install colorednoise==2.2.0 numpy==2.3.4 sounddevice==0.5.3 winsdk==1.0.0b10

```



## 💻 Usage

Run the main script via Python:

```bash
python main.py

```

### Interface Guide:

* **Contrôles (Controls)**: Adjust the main volume, stereo pan, frequency (in Hz or MIDI notes), and sweep speed. You can type an exact frequency and press `Enter` to snap it to the nearest MIDI note.
* **Text-to-Speech**: Type your text in the input field, select a voice from the dropdown (automatically populated with system voices), and click **Parler**.
* **Générer (Generate)**: Use the dedicated buttons to start generating different colored noises, fixed frequencies, or frequency sweeps. Click **Stop** to halt all audio output.

## ⚙️ Technical Details

* **GUI Framework**: `tkinter` / `ttk`
* **Audio Engine**: `sounddevice` (OutputStream with real-time callbacks).
* **Signal Processing**: `numpy` for arrays and wave generation, `colorednoise` for power-law noise generation.
* **TTS Integration**: `winsdk.windows.media.speechsynthesis`. The app extracts the synthesized WAV stream from Windows in-memory, decodes it, resamples it to 44.1kHz, and pipes it into the `sounddevice` playback buffer.

## 👤 Author & Credits

* **Author**: Arnaud LAPIOS
* **Contact**: haarnhoo@gmail.com
* **Copyright**: (c) 2025
* *Note on deployment*: Contains embedded handling to clear splash screens when compiled as a one-file executable via Nuitka.
""")

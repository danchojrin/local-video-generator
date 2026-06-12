# Local Video Generator

Interfaz visual para generar vídeos cortos (LinkedIn, Reels, YouTube Shorts) directamente en tu ordenador, sin editores de vídeo ni suscripciones de terceros.

---

## ⚠️ Aviso importante

**Nada del software que usa esta herramienta es mío.**
Yo solo estoy compartiendo la interfaz visual que construí para uso personal, iterando con IA.

Las herramientas que utiliza este proyecto son proyectos independientes de terceros:

| Herramienta | Qué hace | Enlace |
|---|---|---|
| [Streamlit](https://streamlit.io) | Interfaz visual en el navegador | streamlit.io |
| [FFmpeg](https://ffmpeg.org) | Encoding de vídeo | ffmpeg.org |
| [Pillow](https://python-pillow.org) | Dibuja los frames | python-pillow.org |
| [edge-tts](https://github.com/rany2/edge-tts) | Voces neuronales (Microsoft, gratis) | github.com/rany2/edge-tts |
| [ElevenLabs](https://elevenlabs.io) | Voces premium (requiere API key propia) | elevenlabs.io |

---

## 💻 Compatibilidad por sistema

El rendimiento varía mucho según tu máquina:

| Sistema | Qué esperar |
|---|---|
| **Mac con Apple Silicon (M1/M2/M3/M4/M5)** | Experiencia completa. Encoding H.265 por hardware (VideoToolbox), render paralelo sin throttling, voces nativas con `say` |
| **Mac Intel** | Funciona, encoding H.264 por software (más lento) |
| **Windows** | Funciona con FFmpeg instalado. Sin `say` de macOS — usa edge-tts o ElevenLabs |
| **Linux** | Funciona con FFmpeg instalado. Sin `say` de macOS |

> Si tu ordenador es lento, los vídeos tardarán más en generarse. La calidad del resultado es la misma.

---

## 🛠️ Requisitos previos

### 1. Python 3.10 o superior
Descarga desde [python.org](https://python.org) o con Homebrew en Mac:
```bash
brew install python
```

### 2. FFmpeg
**Mac:**
```bash
brew install ffmpeg
```
**Windows:** Descarga desde [ffmpeg.org](https://ffmpeg.org/download.html) y añádelo al PATH.

**Linux (Ubuntu/Debian):**
```bash
sudo apt install ffmpeg
```

---

## 🚀 Instalación

```bash
# 1. Clona el repositorio
git clone https://github.com/danchojrin/local-video-generator.git
cd local-video-generator

# 2. Crea un entorno virtual (recomendado)
python -m venv .venv

# Mac/Linux:
source .venv/bin/activate

# Windows:
.venv\Scripts\activate

# 3. Instala las dependencias
pip install -r requirements.txt

# 4. Arranca la app
streamlit run app.py
```

Se abrirá automáticamente en tu navegador en `http://localhost:8501`.

---

## 🎙️ Motores de voz disponibles

- **macOS `say`** — solo Mac, sin instalación, usa el Neural Engine del chip Apple
- **Edge TTS (Microsoft Neural)** — gratuito, sin API key, voces en español de España, México, Argentina, Colombia
- **ElevenLabs** — voces premium, requiere cuenta y API key propias en [elevenlabs.io](https://elevenlabs.io)

---

## 📁 ¿Dónde se guardan los vídeos?

Los vídeos generados se guardan en la carpeta `output_linkedin/` dentro del proyecto.
Las configuraciones guardadas se almacenan en `~/.pv_videogen/` (tu carpeta de usuario, no en el repositorio).

---

## ❓ Problemas comunes

**`ffmpeg: command not found`** → FFmpeg no está instalado o no está en el PATH.

**La voz `say` no funciona en Windows/Linux** → Normal, es exclusiva de macOS. Usa Edge TTS.

**El vídeo tarda mucho** → Es normal en ordenadores sin Apple Silicon. El render en paralelo ayuda, pero depende de los cores disponibles.

**`pip install` falla con `elevenlabs`** → Prueba `pip install elevenlabs --upgrade`. Si no usas ElevenLabs, no es necesario instalarlo.

---

## 📄 Licencia

MIT — úsalo, modifícalo, compártelo.

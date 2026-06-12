"""
Motor de generación de video — separado de la UI para compatibilidad
con multiprocessing (los workers importan este módulo, no app.py).
"""

import io
import math
import subprocess
import platform
import multiprocessing
import time
import textwrap
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont, ImageFilter


# ─── Fases de animación ────────────────────────────────────────────────────────

PHASE_GLITCH = 0.08
PHASE_TYPE   = 0.55
PHASE_HOLD   = 0.85


# ─── Globals de worker ────────────────────────────────────────────────────────

_FONT_PATH: Optional[str]  = None
_FONTS:     Optional[tuple] = None
_CFG:       dict             = {}
_SLIDES:    list             = []
_VIGNETTE:  Optional[object] = None   # cacheada por worker


def _init_worker(font_path, cfg, slides):
    global _FONT_PATH, _FONTS, _CFG, _SLIDES, _VIGNETTE, _LAYOUT_CACHE
    _FONT_PATH    = font_path
    _CFG          = cfg
    _SLIDES       = slides
    _FONTS        = None
    _VIGNETTE     = None
    _LAYOUT_CACHE = {}


# ─── Sistema ──────────────────────────────────────────────────────────────────

def detect_system() -> dict:
    machine  = platform.machine()
    encoders = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True
    ).stdout
    if "hevc_videotoolbox" in encoders:
        codec, label = "hevc_videotoolbox", "H.265 HEVC + VideoToolbox"
    elif "h264_videotoolbox" in encoders:
        codec, label = "h264_videotoolbox", "H.264 AVC + VideoToolbox"
    else:
        codec, label = "libx264", "H.264 software"
    return {"machine": machine, "is_arm": machine == "arm64",
            "codec": codec, "label": label, "cores": multiprocessing.cpu_count()}


# ─── Voces ────────────────────────────────────────────────────────────────────

def get_say_voices() -> list:
    out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    voices = [l.split()[0] for l in out.splitlines()
              if len(l.split()) >= 2 and ("es_" in l.split()[1] or "es-" in l.split()[1])]
    return voices or ["Samantha"]


def get_edge_voices() -> list:
    return [
        {"id": "es-ES-AlvaroNeural",  "label": "Álvaro (España, M)"},
        {"id": "es-ES-ElviraNeural",  "label": "Elvira (España, F)"},
        {"id": "es-MX-JorgeNeural",   "label": "Jorge (México, M)"},
        {"id": "es-MX-DaliaNeural",   "label": "Dalia (México, F)"},
        {"id": "es-AR-TomasNeural",   "label": "Tomás (Argentina, M)"},
        {"id": "es-CO-GonzaloNeural", "label": "Gonzalo (Colombia, M)"},
    ]


# ─── Audio ────────────────────────────────────────────────────────────────────

def generate_audio_say(text, path, voice, rate=105):
    path.parent.mkdir(parents=True, exist_ok=True)
    txt = path.parent / "_tmp.txt"
    txt.write_text(text, encoding="utf-8")
    subprocess.run(["say", "-v", voice, "-r", str(rate), "-o", str(path), "-f", str(txt)], check=True)
    txt.unlink(missing_ok=True)


def generate_audio_edge(text, path, voice):
    import asyncio
    try:
        import edge_tts
    except ImportError:
        raise ImportError("Instala edge-tts: pip install edge-tts")
    mp3 = path.with_suffix(".mp3")

    async def _gen():
        await edge_tts.Communicate(text, voice).save(str(mp3))

    asyncio.run(_gen())
    subprocess.run(["ffmpeg", "-y", "-i", str(mp3), str(path)], capture_output=True, check=True)
    mp3.unlink(missing_ok=True)


def generate_audio_elevenlabs(text, path, api_key, voice_id):
    try:
        from elevenlabs.client import ElevenLabs
        from elevenlabs import save
    except ImportError:
        raise ImportError("pip install elevenlabs")
    client = ElevenLabs(api_key=api_key)
    audio  = client.text_to_speech.convert(voice_id=voice_id, text=text, model_id="eleven_multilingual_v2")
    mp3    = path.with_suffix(".mp3")
    save(audio, str(mp3))
    subprocess.run(["ffmpeg", "-y", "-i", str(mp3), str(path)], capture_output=True, check=True)
    mp3.unlink(missing_ok=True)


def transcribe_audio(audio_path: Path) -> list:
    """Auto-subtítulos con Whisper (pip install openai-whisper). Retorna [] si no está instalado."""
    try:
        import whisper
        model  = whisper.load_model("base")
        result = model.transcribe(str(audio_path), language="es")
        return [{"start": s["start"], "end": s["end"], "text": s["text"].strip()}
                for s in result["segments"]]
    except ImportError:
        return []
    except Exception:
        return []


def mix_music(video_path: Path, music_path: Path, output_path: Path, volume: float = 0.12) -> None:
    """Mezcla música de fondo con el audio de voz."""
    subprocess.run([
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(music_path),
        "-filter_complex",
        f"[1:a]volume={volume},aloop=loop=-1:size=2e+09[music];"
        f"[0:a][music]amix=inputs=2:duration=first:dropout_transition=3[a]",
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        str(output_path),
    ], check=True, capture_output=True)


def extract_thumbnail(video_path: Path, output_path: Path, at_seconds: int = 8) -> None:
    subprocess.run([
        "ffmpeg", "-y", "-ss", str(at_seconds),
        "-i", str(video_path), "-vframes", "1", "-q:v", "2",
        str(output_path),
    ], check=True, capture_output=True)


# ─── Parseo del guión ─────────────────────────────────────────────────────────

def parse_script(text: str, total_duration: int = 60) -> list:
    import re

    paragraphs = [b.strip() for b in text.strip().split("\n\n") if b.strip()]

    # Sin bloques separados: intentar separar por frases
    if len(paragraphs) == 1 and "\n" not in paragraphs[0]:
        frases = re.split(r"(?<=[.!?])\s+", paragraphs[0])
        frases = [f.strip() for f in frases if f.strip()]
        paragraphs = [" ".join(frases[i:i+2]) for i in range(0, len(frases), 2)]

    # Guardar las líneas ORIGINALES del usuario sin procesar.
    # El render hará word-wrap en píxeles real — sin adivinar anchos por chars.
    # Líneas cortas (≤40 chars) se emparejan de 2 en 2; largas van solas.
    chunks: list[list[str]] = []
    for para in paragraphs:
        orig: list[str] = [l.strip() for l in para.split("\n") if l.strip()]
        i = 0
        while i < len(orig):
            line = orig[i]
            if len(line) <= 40 and i + 1 < len(orig) and len(orig[i + 1]) <= 40:
                chunks.append([line, orig[i + 1]])
                i += 2
            else:
                chunks.append([line])
                i += 1

    if not chunks:
        chunks = [[text.strip()]]

    tags = ["HOOK", "PROBLEMA", "HISTORIA", "CLAVE", "PROMESA", "ACCION", "CIERRE"]
    wcs  = [max(1, sum(len(l.split()) for l in c if l)) for c in chunks]
    total_words = max(1, sum(wcs))

    # Timing proporcional; el último slide absorbe el ajuste para sumar exactamente total_duration
    slides, t = [], 0
    for i, (big, wc) in enumerate(zip(chunks, wcs)):
        if i == len(chunks) - 1:
            dur = max(1, total_duration - t)
        else:
            dur = max(1, round(total_duration * wc / total_words))
        slides.append({"t0": t, "t1": t + dur, "tag": f"// {tags[i % len(tags)]}",
                        "big": big, "small": ""})
        t += dur
    return slides


_LAYOUT_CACHE: dict = {}


def _pixel_layout(raw_lines: list, max_width: int) -> tuple:
    """
    Word-wrap + font-size usando medición real en píxeles.
    Devuelve (display_lines: list[str], font).
    Sin contar chars — garantizado que no se recorta visualmente.
    """
    key = (tuple(raw_lines), max_width)
    if key in _LAYOUT_CACHE:
        return _LAYOUT_CACHE[key]

    fp = _FONT_PATH
    orig = [l for l in raw_lines if l and l.strip()]
    if not fp or not orig:
        result = (orig or [""], _get_fonts()[1])
        _LAYOUT_CACHE[key] = result
        return result

    for size in range(68, 16, -2):
        try:
            f = ImageFont.truetype(fp, size)
        except Exception:
            continue

        display: list[str] = []
        for raw in orig:
            words = raw.split()
            cur: list[str] = []
            for word in words:
                test = " ".join(cur + [word])
                if f.getlength(test) <= max_width:
                    cur.append(word)
                else:
                    if cur:
                        display.append(" ".join(cur))
                    cur = [word]
            if cur:
                display.append(" ".join(cur))

        if len(display) <= 4 and all(f.getlength(l) <= max_width for l in display):
            _LAYOUT_CACHE[key] = (display, f)
            return display, f

    fallback = (orig[:3], _get_fonts()[1])
    _LAYOUT_CACHE[key] = fallback
    return fallback


# ─── Fuentes ──────────────────────────────────────────────────────────────────

def find_font() -> Optional[str]:
    for p in ["/Library/Fonts/Courier New.ttf",
              "/System/Library/Fonts/Supplemental/Courier New.ttf",
              "/System/Library/Fonts/Helvetica.ttc",
              "/Library/Fonts/Arial.ttf",
              "/System/Library/Fonts/Supplemental/Arial.ttf"]:
        if Path(p).exists():
            return p
    return None


def _get_fonts():
    global _FONTS
    if _FONTS:
        return _FONTS
    fp = _FONT_PATH
    if fp:
        for idx in (1, 0):
            try:
                _FONTS = (ImageFont.truetype(fp, 20),
                          ImageFont.truetype(fp, 68, index=idx),
                          ImageFont.truetype(fp, 30))
                return _FONTS
            except Exception:
                continue
    d = ImageFont.load_default()
    _FONTS = (d, d, d)
    return _FONTS


def _font_fit_lines(lines: list, max_width: int, base_size: int = 68) -> ImageFont.FreeTypeFont:
    """Devuelve la fuente más grande donde TODAS las líneas caben en max_width px."""
    fp = _FONT_PATH
    non_empty = [l for l in lines if l and l.strip()]
    if not fp or not non_empty:
        return _get_fonts()[1]
    for size in range(base_size, 22, -4):
        for idx in (1, 0):
            try:
                f = ImageFont.truetype(fp, size, index=idx)
                if all(f.getlength(l) <= max_width for l in non_empty):
                    return f
            except Exception:
                continue
    return _get_fonts()[1]


# ─── Helpers visuales ─────────────────────────────────────────────────────────

def _ease(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def _ease_out(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def _dim(color, a):
    return tuple(max(0, min(255, int(c * a))) for c in color)


def _get_slide(t, slides):
    for s in slides:
        if s["t0"] <= t < s["t1"]:
            return s
    return slides[-1]


def _draw_gradient_bg(img, bg, accent, frame_idx):
    W, H = img.size
    draw = ImageDraw.Draw(img)
    t    = frame_idx / 30
    step = 6
    for y in range(0, H, step):
        frac  = y / H
        pulse = math.sin(t * 0.25 + frac * math.pi) * 0.07
        am    = (1 - frac) * 0.05
        r = max(0, min(255, int(bg[0] * (1 + pulse) + accent[0] * am)))
        g = max(0, min(255, int(bg[1] * (1 + pulse) + accent[1] * am)))
        b = max(0, min(255, int(bg[2] * (1 + pulse) + accent[2] * am)))
        draw.rectangle([(0, y), (W, min(y + step, H))], fill=(r, g, b))


def _make_glow(img, text, pos, font, glow_color, radius=12):
    """Aplica glow gaussiano al texto y retorna imagen RGB resultante."""
    bbox    = font.getbbox(text)
    pad     = radius + 4
    gw, gh  = bbox[2] - bbox[0] + pad * 2, bbox[3] - bbox[1] + pad * 2
    layer   = Image.new("RGBA", (gw, gh), (0, 0, 0, 0))
    ld      = ImageDraw.Draw(layer)
    ld.text((pad, pad), text, font=font, fill=(*glow_color[:3], 200))
    layer   = layer.filter(ImageFilter.GaussianBlur(radius))
    base    = img.convert("RGBA")
    base.paste(layer, (pos[0] - pad, pos[1] - pad), layer)
    return base.convert("RGB")


def _draw_grid(draw, frame_idx, W, H, grid_c):
    pulse = 0.65 + 0.35 * math.sin(frame_idx / 30 * math.pi * 0.45)
    gc    = _dim(grid_c, pulse)
    for x in range(0, W + 1, 108):
        draw.line([(x, 0), (x, H)], fill=gc)
    for y in range(0, H + 1, 108):
        draw.line([(0, y), (W, y)], fill=gc)


def _draw_particles(draw, frame_idx, W, H, accent, master_a):
    t = frame_idx / 30
    for i in range(30):
        px = int(((i * 337) % W + t * math.sin(i * 2.399) * 18) % W)
        py = int(((i * 97)  % H + t * (-(abs(math.cos(i * 1.618)) * 12 + 4))) % H)
        br = 0.25 + 0.25 * math.sin(t * 2.1 + i)
        r  = 1 + (i % 2)
        draw.ellipse([(px - r, py - r), (px + r, py + r)],
                     fill=_dim(accent, master_a * br * 0.55))


def _draw_scanline(draw, frame_idx, W, H, white, accent):
    y = int((frame_idx / 30 * 180) % H)
    draw.rectangle([(0, y),     (W, y + 2)], fill=_dim(white,  0.04))
    draw.rectangle([(0, y + 3), (W, y + 4)], fill=_dim(accent, 0.02))


def _draw_glitch(draw, strength, frame_idx, W, H, blue, accent, white):
    if strength <= 0.01:
        return
    draw.rectangle([(0, 0), (W, H)], fill=_dim(accent, strength * 0.20))
    for i in range(int(10 * strength)):
        yp = (frame_idx * 1013 + i * 397 + 7) % H
        hb = (frame_idx * 53   + i * 113 + 3) % 8 + 2
        draw.rectangle([(0, yp), (W, yp + hb)], fill=_dim(blue if i % 2 == 0 else accent, strength * 0.65))
    sy = (frame_idx * 79 + 11) % H
    draw.rectangle([(0, sy), (W, sy + 1)], fill=_dim(white, strength * 0.55))


def _draw_ekg(draw, frame_idx, W, H, accent, master_a):
    yb              = int(H * 0.88)
    xs, xe          = int(W * 0.055), int(W * 0.945)
    width           = xe - xs
    cycle           = (frame_idx % 90) / 90
    px_head         = xs + int(width * cycle)

    draw.line([(xs, yb), (xe, yb)], fill=_dim(accent, master_a * 0.22), width=1)

    pts = []
    for px in range(xs, xe, 2):
        rel  = (px - xs) / width
        dist = abs(rel - cycle)
        if   dist < 0.006: py = yb - int(68 * master_a)
        elif dist < 0.012: py = yb + int(22 * master_a)
        else:              py = yb
        pts.append((px, py))

    for i in range(len(pts) - 1):
        la = min(master_a * (1.25 if abs(pts[i][0] - px_head) < 45 else 0.45), 1.0)
        draw.line([pts[i], pts[i + 1]], fill=_dim(accent, la), width=2)

    draw.ellipse([(px_head - 5, yb - 5), (px_head + 5, yb + 5)],      fill=_dim(accent, master_a))
    draw.ellipse([(px_head - 10, yb - 10), (px_head + 10, yb + 10)],  outline=_dim(accent, master_a * 0.3), width=1)


def _draw_subtitle(draw, text, W, H, accent, white, font):
    if not text:
        return
    bbox    = font.getbbox(text)
    tw      = bbox[2] - bbox[0]
    th      = bbox[3] - bbox[1]
    pad     = 16
    y_box   = int(H * 0.80)
    x_box   = (W - tw) // 2 - pad
    draw.rectangle([(x_box, y_box - pad), (x_box + tw + pad * 2, y_box + th + pad)],
                   fill=_dim((0, 0, 0), 0.65))
    draw.text((x_box + pad, y_box), text, font=font, fill=white)


def _draw_logo(img, logo_path: str, position: str, size_px: int, opacity: float):
    try:
        logo   = Image.open(logo_path).convert("RGBA")
        ratio  = logo.width / logo.height
        logo   = logo.resize((int(size_px * ratio), size_px), Image.LANCZOS)
        if opacity < 1.0:
            alpha = logo.split()[3].point(lambda x: int(x * opacity))
            logo.putalpha(alpha)
        W, H   = img.size
        lw, lh = logo.size
        margin = 30
        pos_map = {
            "Arriba izquierda":  (margin, margin),
            "Arriba derecha":    (W - lw - margin, margin),
            "Abajo izquierda":   (margin, H - lh - margin),
            "Abajo derecha":     (W - lw - margin, H - lh - margin),
        }
        x, y   = pos_map.get(position, (margin, margin))
        base   = img.convert("RGBA")
        base.paste(logo, (x, y), logo)
        return base.convert("RGB")
    except Exception:
        return img


def _typewriter(text, progress):
    n = int(len(text) * min(progress, 1.0))
    return text[:n], n < len(text)


# ─── Transiciones ─────────────────────────────────────────────────────────────

def _apply_transition(img: Image.Image, lt: float, cfg: dict) -> Image.Image:
    """Aplica la transición elegida durante la fase de glitch (lt 0→PHASE_GLITCH)."""
    if lt >= PHASE_GLITCH:
        return img
    t_type   = cfg.get("transition_type", "Glitch")
    progress = _ease(lt / PHASE_GLITCH)   # 0→1 conforme avanza la entrada
    W, H     = img.size
    bg       = cfg["bg"]
    accent   = cfg["accent"]

    if t_type == "Wipe":
        # Nueva slide se revela de izquierda a derecha
        reveal_x = int(W * progress)
        mask     = Image.new("RGB", (W, H), bg)
        composite = img.copy()
        composite.paste(mask.crop((reveal_x, 0, W, H)), (reveal_x, 0))
        # Línea de barrido
        draw = ImageDraw.Draw(composite)
        if reveal_x < W:
            draw.rectangle([(reveal_x, 0), (reveal_x + 4, H)], fill=accent)
        return composite

    elif t_type == "Zoom":
        # Zoom-in: contenido entra desde grande a tamaño normal
        scale   = 1.35 - 0.35 * progress          # 1.35 → 1.0
        new_w   = int(W * scale)
        new_h   = int(H * scale)
        big     = img.resize((new_w, new_h), Image.LANCZOS)
        x_off   = (new_w - W) // 2
        y_off   = (new_h - H) // 2
        return big.crop((x_off, y_off, x_off + W, y_off + H))

    elif t_type == "Push":
        # Slide entra deslizándose desde la derecha
        offset  = int(W * (1 - progress))
        canvas  = Image.new("RGB", (W, H), bg)
        canvas.paste(img, (-offset, 0))
        return canvas

    elif t_type == "Flash":
        # Destello blanco que se disipa
        flash_a = max(0.0, 1.0 - progress * 2)
        overlay = Image.new("RGB", (W, H), (255, 255, 255))
        return Image.blend(img, overlay, flash_a * 0.85)

    elif t_type == "Dissolve":
        # Fundido desde negro
        black   = Image.new("RGB", (W, H), (0, 0, 0))
        return Image.blend(black, img, progress)

    # Glitch (default) — ya lo maneja _draw_glitch en el render
    return img


# ─── Cinematográfico ──────────────────────────────────────────────────────────

def _lcg(seed: int) -> int:
    """LCG determinista para grain por frame sin módulo random."""
    return (seed * 1664525 + 1013904223) & 0xFFFFFFFF


def _get_vignette(W: int, H: int, strength: float = 0.72) -> Image.Image:
    """Crea la capa de viñeta una vez por worker y la reutiliza."""
    global _VIGNETTE
    if _VIGNETTE is not None:
        return _VIGNETTE
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw  = ImageDraw.Draw(layer)
    steps = 35
    for i in range(steps):
        alpha = int(255 * strength * ((steps - i) / steps) ** 2.0)
        px    = int(W * 0.48 * i / steps)
        py    = int(H * 0.48 * i / steps)
        draw.rectangle([(0,   0),   (W,       py)],      fill=(0, 0, 0, alpha))
        draw.rectangle([(0,   H-py),(W,       H)],       fill=(0, 0, 0, alpha))
        draw.rectangle([(0,   0),   (px,      H)],       fill=(0, 0, 0, alpha))
        draw.rectangle([(W-px,0),   (W,       H)],       fill=(0, 0, 0, alpha))
    _VIGNETTE = layer
    return _VIGNETTE


def _apply_vignette(img: Image.Image) -> Image.Image:
    W, H    = img.size
    vignette = _get_vignette(W, H)
    base     = img.convert("RGBA")
    base     = Image.alpha_composite(base, vignette)
    return base.convert("RGB")


def _apply_film_grain(img: Image.Image, frame_idx: int, intensity: float = 0.032) -> Image.Image:
    """Grain determinista que cambia cada frame — estética película 35mm."""
    W, H = img.size
    n    = int(W * H * intensity / 7)
    draw = ImageDraw.Draw(img)
    seed = frame_idx * 98317 + 7
    for _ in range(n):
        seed = _lcg(seed)
        x    = seed % W
        seed = _lcg(seed)
        y    = seed % H
        seed = _lcg(seed)
        v    = 130 + (seed % 110)
        a    = 30  + (seed % 50)
        # Mezcla aditiva suave: solo pixeles claros añaden textura
        px   = img.getpixel((x, y))
        blended = tuple(min(255, int(c * 0.92 + v * 0.08)) for c in px)
        draw.point([(x, y)], fill=blended)
    return img


def _apply_ken_burns(img: Image.Image, lt: float, phase_start: float) -> Image.Image:
    """Zoom-in lento durante la fase de hold — efecto documental."""
    if lt < phase_start:
        return img
    W, H      = img.size
    progress  = (lt - phase_start) / max(1 - phase_start, 0.01)  # 0→1
    scale     = 1.0 + 0.03 * progress                             # hasta +3%
    new_w     = int(W * scale)
    new_h     = int(H * scale)
    big       = img.resize((new_w, new_h), Image.BILINEAR)        # BILINEAR: más rápido que LANCZOS
    x_off     = (new_w - W) // 2
    y_off     = (new_h - H) // 2
    return big.crop((x_off, y_off, x_off + W, y_off + H))


# ─── Render frames ────────────────────────────────────────────────────────────

def _render_base(frame_idx, cfg, slides, frames_dir_key, get_lt_func):
    """Lógica compartida entre main, intro y outro frames."""
    W, H      = cfg["W"], cfg["H"]
    bg        = cfg["bg"]
    accent    = cfg["accent"]
    white     = cfg["white"]
    muted     = cfg["muted"]
    grid_c    = cfg["grid"]
    blue      = cfg["blue"]

    lt, master_a, build_prog, glitch_str = get_lt_func(frame_idx, cfg)

    if cfg.get("feat_gradient"):
        img = Image.new("RGB", (W, H), bg)
        _draw_gradient_bg(img, bg, accent, frame_idx)
    else:
        img = Image.new("RGB", (W, H), bg)

    draw = ImageDraw.Draw(img)

    if cfg.get("anim_grid",     True): _draw_grid(draw, frame_idx, W, H, grid_c)
    if cfg.get("anim_particles", True): _draw_particles(draw, frame_idx, W, H, accent, master_a * 0.7)
    if cfg.get("anim_glitch",   True): _draw_glitch(draw, glitch_str, frame_idx, W, H, blue, accent, white)

    return img, draw, lt, master_a, build_prog


def render_frame(frame_idx: int) -> None:
    cfg    = _CFG
    slides = _SLIDES
    W, H   = cfg["W"], cfg["H"]
    FPS    = cfg["FPS"]
    TOTAL  = cfg["TOTAL_FRAMES"]
    accent = cfg["accent"]
    white  = cfg["white"]
    muted  = cfg["muted"]

    t   = frame_idx / FPS
    sl  = _get_slide(t, slides)
    dur = max(sl["t1"] - sl["t0"], 1)
    lt  = (t - sl["t0"]) / dur

    glitch_str = max(0.0, _ease_out(1.0 - lt / PHASE_GLITCH)) if lt < PHASE_GLITCH else 0.0
    build_prog = max(0.0, min((lt - PHASE_GLITCH) / max(PHASE_TYPE - PHASE_GLITCH, 0.01), 1.0))
    fade_out   = _ease(1.0 - (lt - PHASE_HOLD) / max(1.0 - PHASE_HOLD, 0.01)) if lt >= PHASE_HOLD else 1.0
    master_a   = fade_out

    def _lt_fn(fi, c): return lt, master_a, build_prog, glitch_str

    img, draw, *_ = _render_base(frame_idx, cfg, slides, "frames_dir", _lt_fn)
    f_tag, f_big, f_small = _get_fonts()

    margin = int(W * 0.055)

    # Accent bar
    bar_a = _ease(min(build_prog * 3, 1.0)) * master_a
    draw.rectangle([(margin, int(H * 0.10)), (margin + int(140 * bar_a), int(H * 0.10) + 7)],
                   fill=_dim(accent, bar_a))

    # Tag + HUD
    draw.text((margin, int(H * 0.125)), sl["tag"],
              font=f_tag, fill=_dim(muted, bar_a * 0.9))
    draw.text((W - margin - 80, int(H * 0.125)), f"{slides.index(sl)+1:02d}/{len(slides)}",
              font=f_tag, fill=_dim(muted, bar_a * 0.5))

    # Texto principal — layout en píxeles reales
    max_text_w = W - margin * 2
    render_lines, f_text = _pixel_layout(sl["big"], max_text_w)
    n_render = len(render_lines)

    if cfg.get("anim_typewriter", True):
        step = 1.0 / max(n_render, 1)
        shows = []
        prev_complete = False
        for idx, rl in enumerate(render_lines):
            p_start = idx * step * 1.5
            p_end   = p_start + step * 1.5
            p = min(max(0.0, (build_prog * 1.7 - p_start) / max(p_end - p_start, 0.01)), 1.0)
            v, complete = _typewriter(rl, p)
            cur = (frame_idx // 8) % 2 == 0
            shows.append(v + ("|" if complete and not prev_complete and cur else ""))
            prev_complete = complete or prev_complete
    else:
        shows = list(render_lines)

    dy    = int((1.0 - _ease(min(build_prog * 2, 1.0))) * 20)
    y_big = int(H * 0.22) + dy
    lh    = int(H * 0.085)

    if cfg.get("feat_glow"):
        for i, show in enumerate(shows):
            img = _make_glow(img, show, (margin, y_big + i * lh), f_text, accent)
        draw = ImageDraw.Draw(img)

    for i, show in enumerate(shows):
        draw.text((margin, y_big + i * lh), show, font=f_text, fill=_dim(white, master_a))

    # Subtítulo del guión
    if sl["small"]:
        sub_a = _ease(max(0.0, build_prog - 0.75) / 0.25) * master_a
        y_s   = y_big + n_render * lh + int(H * 0.03)
        for line in sl["small"].split("\n"):
            draw.text((margin, y_s), line, font=f_small, fill=_dim(muted, sub_a * 0.9))
            y_s += int(H * 0.05)

    # Subtítulos automáticos (whisper)
    if cfg.get("feat_subtitles") and cfg.get("subtitle_segments"):
        seg = next((s for s in cfg["subtitle_segments"] if s["start"] <= t <= s["end"]), None)
        if seg:
            _draw_subtitle(draw, seg["text"], W, H, accent, white, f_small)

    # Logo
    if cfg.get("feat_logo") and cfg.get("logo_path"):
        img = _draw_logo(img, cfg["logo_path"], cfg.get("logo_position", "Arriba derecha"),
                         cfg.get("logo_size", 80), cfg.get("logo_opacity", 0.85))
        draw = ImageDraw.Draw(img)

    if cfg.get("anim_ekg",      True): _draw_ekg(draw, frame_idx, W, H, accent, master_a * 0.9)
    if cfg.get("anim_scanline", True): _draw_scanline(draw, frame_idx, W, H, white, accent)

    # Barra de progreso
    progress = frame_idx / TOTAL
    draw.rectangle([(0, H - 4), (W, H)],                 fill=cfg["grid"])
    draw.rectangle([(0, H - 4), (int(W * progress), H)], fill=accent)

    # ── Post-proceso cinematográfico ──────────────────────────────────────────
    # Transición (reemplaza al glitch si no es tipo Glitch)
    if cfg.get("transition_type", "Glitch") != "Glitch":
        img = _apply_transition(img, lt, cfg)
        draw = ImageDraw.Draw(img)

    # Ken Burns — zoom lento durante hold para romper la estaticidad
    if cfg.get("feat_cinematic"):
        img = _apply_ken_burns(img, lt, PHASE_TYPE)

    # Viñeta — enmarca como plano cinematográfico
    if cfg.get("feat_vignette", False) or cfg.get("feat_cinematic"):
        img = _apply_vignette(img)

    # Film grain — textura analógica
    if cfg.get("feat_grain", False) or cfg.get("feat_cinematic"):
        grain_intensity = float(cfg.get("grain_intensity", 0.032))
        img = _apply_film_grain(img, frame_idx, grain_intensity)

    _save_frame(img, Path(cfg["frames_dir"]), frame_idx)


def render_intro_frame(frame_idx: int) -> None:
    cfg    = _CFG
    W, H   = cfg["W"], cfg["H"]
    total  = cfg.get("intro_total", 75)
    lt     = frame_idx / total
    master_a = _ease(min(lt * 5, 1.0)) * (1.0 if lt < 0.80 else _ease(1.0 - (lt - 0.80) / 0.20))
    accent = cfg["accent"]
    white  = cfg["white"]
    muted  = cfg["muted"]

    img = Image.new("RGB", (W, H), cfg["bg"])
    if cfg.get("feat_gradient"): _draw_gradient_bg(img, cfg["bg"], accent, frame_idx)
    draw = ImageDraw.Draw(img)

    if cfg.get("anim_grid",     True): _draw_grid(draw, frame_idx, W, H, cfg["grid"])
    if cfg.get("anim_particles", True): _draw_particles(draw, frame_idx, W, H, accent, master_a * 0.6)

    f_tag, f_big, f_small = _get_fonts()
    margin = int(W * 0.055)
    yc     = H // 2 - int(H * 0.08)

    bar_a = _ease(min(lt * 5, 1.0)) * master_a
    draw.rectangle([(margin, yc - 30), (margin + int(160 * bar_a), yc - 22)], fill=_dim(accent, bar_a))

    brand = cfg.get("brand_name", "TU MARCA")
    sub   = cfg.get("brand_sub",  "Tu nombre")

    if cfg.get("feat_glow"):
        img  = _make_glow(img, brand, (margin, yc), f_big, accent)
        draw = ImageDraw.Draw(img)
    draw.text((margin, yc),                    brand, font=f_big,   fill=_dim(white, master_a))
    draw.text((margin, yc + int(H * 0.10)),    sub,   font=f_small, fill=_dim(muted, master_a * 0.8))

    if cfg.get("anim_ekg",      True): _draw_ekg(draw, frame_idx, W, H, accent, master_a * 0.9)
    if cfg.get("anim_scanline", True): _draw_scanline(draw, frame_idx, W, H, white, accent)

    _save_frame(img, Path(cfg["intro_dir"]), frame_idx)


def render_outro_frame(frame_idx: int) -> None:
    cfg    = _CFG
    W, H   = cfg["W"], cfg["H"]
    total  = cfg.get("outro_total", 90)
    lt     = frame_idx / total
    master_a = _ease(min(lt * 4, 1.0)) * (1.0 if lt < 0.75 else _ease(1.0 - (lt - 0.75) / 0.25))
    accent = cfg["accent"]
    white  = cfg["white"]
    muted  = cfg["muted"]

    img = Image.new("RGB", (W, H), cfg["bg"])
    if cfg.get("feat_gradient"): _draw_gradient_bg(img, cfg["bg"], accent, frame_idx)
    draw = ImageDraw.Draw(img)

    if cfg.get("anim_grid",     True): _draw_grid(draw, frame_idx, W, H, cfg["grid"])
    if cfg.get("anim_particles", True): _draw_particles(draw, frame_idx, W, H, accent, master_a * 0.6)

    f_tag, f_big, f_small = _get_fonts()
    margin = int(W * 0.055)
    yc     = H // 2 - int(H * 0.08)

    cta    = cfg.get("outro_cta",    "Sígueme")
    handle = cfg.get("outro_handle", "@tu_handle")

    if cfg.get("feat_glow"):
        img  = _make_glow(img, cta, (margin, yc), f_big, accent)
        draw = ImageDraw.Draw(img)
    draw.text((margin, yc),                  cta,    font=f_big,   fill=_dim(white, master_a))
    draw.text((margin, yc + int(H * 0.10)),  handle, font=f_small, fill=_dim(accent, master_a))
    draw.text((margin, yc + int(H * 0.16)),  cfg.get("outro_sub", "El cambio empieza aquí."),
              font=f_small, fill=_dim(muted, master_a * 0.8))

    if cfg.get("anim_ekg",      True): _draw_ekg(draw, frame_idx, W, H, accent, master_a * 0.9)
    if cfg.get("anim_scanline", True): _draw_scanline(draw, frame_idx, W, H, white, accent)

    _save_frame(img, Path(cfg["outro_dir"]), frame_idx)


def _save_frame(img, directory: Path, frame_idx: int) -> None:
    buf = io.BytesIO()
    img.save(buf, "PNG", compress_level=1)
    (directory / f"frame_{frame_idx:06d}.png").write_bytes(buf.getvalue())


# ─── Pipeline paralelo ────────────────────────────────────────────────────────

def render_frames_parallel(cfg, slides, progress_cb=None):
    font_path  = find_font()
    total      = cfg["TOTAL_FRAMES"]
    cores      = multiprocessing.cpu_count()
    frames_dir = Path(cfg["frames_dir"])
    frames_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    with multiprocessing.Pool(cores, initializer=_init_worker, initargs=(font_path, cfg, slides)) as pool:
        for done, _ in enumerate(pool.imap_unordered(render_frame, range(total), chunksize=60), 1):
            if progress_cb:
                progress_cb(done, total, time.perf_counter() - t0)
    return time.perf_counter() - t0


def render_intro_parallel(cfg, slides):
    font_path = find_font()
    total     = cfg.get("intro_total", 75)
    Path(cfg["intro_dir"]).mkdir(parents=True, exist_ok=True)
    with multiprocessing.Pool(multiprocessing.cpu_count(),
                              initializer=_init_worker, initargs=(font_path, cfg, slides)) as pool:
        pool.map(render_intro_frame, range(total))


def render_outro_parallel(cfg, slides):
    font_path = find_font()
    total     = cfg.get("outro_total", 90)
    Path(cfg["outro_dir"]).mkdir(parents=True, exist_ok=True)
    with multiprocessing.Pool(multiprocessing.cpu_count(),
                              initializer=_init_worker, initargs=(font_path, cfg, slides)) as pool:
        pool.map(render_outro_frame, range(total))


# ─── Encoding ─────────────────────────────────────────────────────────────────

def encode_video(cfg: dict, with_intro_outro: bool = False) -> None:
    codec  = cfg["codec"]
    W, H   = cfg["W"], cfg["H"]
    FPS    = cfg["FPS"]
    DUR    = cfg["DURATION"]
    audio  = Path(cfg["audio_file"])
    output = Path(cfg["video_file"])
    output.parent.mkdir(parents=True, exist_ok=True)

    if "hevc_videotoolbox" in codec:
        quality = ["-b:v", "8000k", "-tag:v", "hvc1"]
    elif "h264_videotoolbox" in codec:
        quality = ["-b:v", "8000k"]
    else:
        quality = ["-crf", "18", "-preset", "fast"]

    if with_intro_outro and cfg.get("feat_intro_outro"):
        # Crear lista de archivos para concat
        concat_file = output.parent / "concat.txt"
        lines = []
        for d in [cfg["intro_dir"], cfg["frames_dir"], cfg["outro_dir"]]:
            # Crear video temporal de cada sección
            pass
        # Simplificado: concat con ffmpeg filter
        intro_pat  = str(Path(cfg["intro_dir"])  / "frame_%06d.png")
        main_pat   = str(Path(cfg["frames_dir"]) / "frame_%06d.png")
        outro_pat  = str(Path(cfg["outro_dir"])  / "frame_%06d.png")
        intro_n    = cfg.get("intro_total", 75)
        main_n     = cfg["TOTAL_FRAMES"]
        outro_n    = cfg.get("outro_total", 90)

        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(FPS), "-i", intro_pat,
            "-framerate", str(FPS), "-i", main_pat,
            "-framerate", str(FPS), "-i", outro_pat,
            "-i", str(audio),
            "-filter_complex",
            f"[0:v][1:v][2:v]concat=n=3:v=1:a=0[v];"
            f"[3:a]apad=whole_dur={(intro_n+main_n+outro_n)//FPS+2}[a]",
            "-map", "[v]", "-map", "[a]",
            "-c:v", codec, *quality,
            "-vf", f"scale={W}:{H}", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            str(output),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(FPS),
            "-i", str(Path(cfg["frames_dir"]) / "frame_%06d.png"),
            "-i", str(audio),
            "-c:v", codec, *quality,
            "-vf", f"scale={W}:{H}", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-af", f"apad=whole_dur={DUR}",
            "-t", str(DUR),
            "-movflags", "+faststart",
            str(output),
        ]

    subprocess.run(cmd, check=True, capture_output=True)


# ─── Builder de configuración ─────────────────────────────────────────────────

def build_cfg(output_dir, W, H, duration, codec, colors=None):
    fps = 30
    c   = colors or {
        "bg": (4, 44, 83), "accent": (0, 194, 168), "white": (230, 241, 251),
        "muted": (138, 155, 176), "grid": (8, 58, 100), "blue": (55, 138, 221),
    }
    return {
        "W": W, "H": H, "FPS": fps, "DURATION": duration,
        "TOTAL_FRAMES": fps * duration,
        "frames_dir":  str(output_dir / "frames"),
        "intro_dir":   str(output_dir / "intro"),
        "outro_dir":   str(output_dir / "outro"),
        "audio_file":  str(output_dir / "narration.aiff"),
        "video_file":  str(output_dir / "output.mp4"),
        "codec":       codec,
        "intro_total": 75,   # 2.5s
        "outro_total": 90,   # 3.0s
        **c,
    }

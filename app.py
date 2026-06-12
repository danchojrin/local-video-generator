"""
Interfaz Streamlit para generar videos de LinkedIn/Reels/YouTube.
Ejecutar: streamlit run app.py
"""

import shutil, tempfile, json
from pathlib import Path
import streamlit as st
import video_engine as ve
import config_manager as cm

# ─── Página ───────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Local Video Generator",
                   page_icon="🎬", layout="wide")

# ─── Presets de color ─────────────────────────────────────────────────────────

PRESETS = {
    "Medianoche":      {"bg":"#0A0A0F","accent":"#6C63FF","white":"#E8E8FF","muted":"#7A7A9A","grid":"#12121A","blue":"#4A90D9"},
    "Oscuro puro":     {"bg":"#080808","accent":"#FFFFFF","white":"#FFFFFF","muted":"#666666","grid":"#141414","blue":"#AAAAAA"},
    "Urgencias":       {"bg":"#0D0505","accent":"#D73232","white":"#F5F0F0","muted":"#8A7070","grid":"#1A0A0A","blue":"#C05050"},
    "Bosque":          {"bg":"#0D1A0F","accent":"#4CAF7D","white":"#E8F5EC","muted":"#7A9A82","grid":"#132018","blue":"#2E86AB"},
    "Cyberpunk":       {"bg":"#0D0221","accent":"#00FF9F","white":"#E0F0FF","muted":"#5A6A8A","grid":"#130330","blue":"#0080FF"},
    "Personalizado":   None,
}

def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

# ─── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("⚙️ Ajustes")

    # ── Cargar configuración guardada ────────────────────────────────────────
    saved = cm.list_configs()
    if saved:
        with st.expander("📂 Cargar configuración guardada"):
            names = [c["name"] for c in saved]
            sel   = st.selectbox("Configuración", ["— Ninguna —"] + names, key="load_sel")
            col1, col2 = st.columns(2)
            if col1.button("Cargar", use_container_width=True) and sel != "— Ninguna —":
                st.session_state["loaded_cfg"] = cm.load_config(sel)
                st.rerun()
            if col2.button("Borrar", use_container_width=True) and sel != "— Ninguna —":
                cm.delete_config(sel)
                st.rerun()

    loaded = st.session_state.get("loaded_cfg", {})

    # ── Formato y duración ───────────────────────────────────────────────────
    st.subheader("📐 Formato")
    FMTS = {"LinkedIn (1:1)": (1080,1080), "Reels / TikTok / Shorts (9:16)": (1080,1920), "YouTube (16:9)": (1920,1080)}
    formato  = st.selectbox("Formato", list(FMTS.keys()), index=list(FMTS.keys()).index(loaded.get("formato", "LinkedIn (1:1)")))
    W, H     = FMTS[formato]
    duracion = st.slider("Duración (s)", 15, 90, int(loaded.get("duracion", 60)), 15)
    batch    = st.checkbox("Exportar en todos los formatos a la vez", value=bool(loaded.get("batch", False)))

    st.divider()

    # ── Voz ──────────────────────────────────────────────────────────────────
    st.subheader("🎙️ Voz")
    TTS_OPTIONS = ["macOS say", "edge-tts (Microsoft Neural)", "ElevenLabs (premium)"]
    tts = st.radio("Motor", TTS_OPTIONS, index=TTS_OPTIONS.index(loaded.get("tts", "edge-tts (Microsoft Neural)")))

    voice_say, voice_rate, voice_edge, el_key, el_voice_id = None, 105, None, None, None

    if tts == "macOS say":
        say_v    = ve.get_say_voices()
        voice_say  = st.selectbox("Voz", say_v, index=min(say_v.index(loaded["voice_say"]) if loaded.get("voice_say") in say_v else 0, len(say_v)-1))
        voice_rate = st.slider("Velocidad (wpm)", 80, 160, int(loaded.get("voice_rate", 105)))
    elif tts == "edge-tts (Microsoft Neural)":
        ev    = ve.get_edge_voices()
        elabs = [v["label"] for v in ev]
        idx   = next((i for i,v in enumerate(ev) if v["label"] == loaded.get("voice_edge_label")), 0)
        voice_sel  = st.selectbox("Voz", elabs, index=idx)
        voice_edge = next(v["id"] for v in ev if v["label"] == voice_sel)
    else:
        el_key      = st.text_input("API Key", type="password", value=loaded.get("el_key",""))
        el_voice_id = st.text_input("Voice ID", value=loaded.get("el_voice_id",""))

    st.divider()

    # ── Estética ─────────────────────────────────────────────────────────────
    st.subheader("🎨 Estética")
    preset_name = st.selectbox("Preset", list(PRESETS.keys()),
                               index=list(PRESETS.keys()).index(loaded.get("preset_name","Medianoche") if loaded.get("preset_name","Medianoche") in PRESETS else "Medianoche"))
    preset      = PRESETS[preset_name]
    defaults    = preset or PRESETS["Medianoche"]

    edit_colors = st.checkbox("Editar colores manualmente", value=bool(loaded.get("edit_colors", preset_name=="Personalizado")))
    if edit_colors:
        c1, c2 = st.columns(2)
        with c1:
            c_bg     = st.color_picker("Fondo",    loaded.get("c_bg",    defaults["bg"]))
            c_accent = st.color_picker("Acento",   loaded.get("c_accent", defaults["accent"]))
            c_white  = st.color_picker("Texto",    loaded.get("c_white",  defaults["white"]))
        with c2:
            c_muted  = st.color_picker("Muted",    loaded.get("c_muted",  defaults["muted"]))
            c_grid   = st.color_picker("Cuadrícula", loaded.get("c_grid", defaults["grid"]))
            c_blue   = st.color_picker("Blue",     loaded.get("c_blue",   defaults["blue"]))
        colors_hex = {"bg":c_bg,"accent":c_accent,"white":c_white,"muted":c_muted,"grid":c_grid,"blue":c_blue}
    else:
        colors_hex = defaults

    colors = {k: hex2rgb(v) for k,v in colors_hex.items()}

    st.divider()

    # ── Animaciones ───────────────────────────────────────────────────────────
    st.subheader("✨ Animaciones")
    ca, cb = st.columns(2)
    with ca:
        anim_grid       = st.toggle("Cuadrícula",  value=bool(loaded.get("anim_grid",  True)))
        anim_particles  = st.toggle("Partículas",  value=bool(loaded.get("anim_particles", True)))
        anim_ekg        = st.toggle("EKG",         value=bool(loaded.get("anim_ekg",   True)))
    with cb:
        anim_glitch     = st.toggle("Glitch",      value=bool(loaded.get("anim_glitch", True)))
        anim_scanline   = st.toggle("Scanline",    value=bool(loaded.get("anim_scanline", True)))
        anim_typewriter = st.toggle("Typewriter",  value=bool(loaded.get("anim_typewriter", True)))

    st.divider()

    # ── Transiciones ──────────────────────────────────────────────────────────
    st.subheader("🎬 Transición entre slides")
    TRANSITIONS = {
        "Glitch":   "Digital / código — el original",
        "Wipe":     "Barrido horizontal — profesional TV",
        "Zoom":     "Zoom-in de entrada — dinámico",
        "Push":     "Deslizamiento desde la derecha — moderno",
        "Flash":    "Destello blanco — impactante",
        "Dissolve": "Fundido desde negro — cinematográfico",
    }
    t_sel = st.selectbox(
        "Tipo",
        list(TRANSITIONS.keys()),
        index=list(TRANSITIONS.keys()).index(loaded.get("transition_type", "Glitch")),
        format_func=lambda k: f"{k} — {TRANSITIONS[k]}",
    )
    transition_type = t_sel

    st.divider()

    # ── Modo cinematográfico ───────────────────────────────────────────────────
    st.subheader("🎞️ Modo Cinematográfico")
    st.caption("Viñeta + film grain + Ken Burns. Rompe el look digital.")
    feat_cinematic = st.toggle("Activar modo cine", value=bool(loaded.get("feat_cinematic", False)))

    if not feat_cinematic:
        col_cin1, col_cin2 = st.columns(2)
        with col_cin1:
            feat_vignette = st.toggle("Viñeta", value=bool(loaded.get("feat_vignette", False)))
        with col_cin2:
            feat_grain    = st.toggle("Film grain", value=bool(loaded.get("feat_grain", False)))
        grain_intensity = st.slider("Intensidad grain", 0.01, 0.08,
                                    float(loaded.get("grain_intensity", 0.032)), 0.005) if feat_grain else 0.032
    else:
        feat_vignette   = False
        feat_grain      = False
        grain_intensity = 0.032

    st.divider()

    # ── Extras ────────────────────────────────────────────────────────────────
    st.subheader("🚀 Extras")

    with st.expander("✦ Glow en texto"):
        feat_glow = st.toggle("Activar glow", value=bool(loaded.get("feat_glow", True)), key="fg")

    with st.expander("✦ Gradiente animado de fondo"):
        feat_gradient = st.toggle("Activar gradiente", value=bool(loaded.get("feat_gradient", False)), key="fgr")

    with st.expander("✦ Logo / marca de agua"):
        feat_logo   = st.toggle("Añadir logo", value=bool(loaded.get("feat_logo", False)), key="fl")
        logo_file   = None
        logo_pos    = "Arriba derecha"
        logo_size   = 80
        logo_opacity= 0.85
        if feat_logo:
            logo_file    = st.file_uploader("Logo (PNG con transparencia)", type=["png","jpg","jpeg"], key="logo_up")
            logo_pos     = st.selectbox("Posición", ["Arriba derecha","Arriba izquierda","Abajo derecha","Abajo izquierda"],
                                        index=["Arriba derecha","Arriba izquierda","Abajo derecha","Abajo izquierda"].index(loaded.get("logo_pos","Arriba derecha")))
            logo_size    = st.slider("Tamaño (px)", 40, 200, int(loaded.get("logo_size", 80)))
            logo_opacity = st.slider("Opacidad", 0.1, 1.0, float(loaded.get("logo_opacity", 0.85)), 0.05)

    with st.expander("✦ Intro + Outro"):
        feat_intro_outro = st.toggle("Añadir intro/outro", value=bool(loaded.get("feat_intro_outro", False)), key="fio")
        brand_name  = st.text_input("Nombre de marca (intro)", value=loaded.get("brand_name","TU MARCA"))
        brand_sub   = st.text_input("Subtítulo (intro)", value=loaded.get("brand_sub","Tu nombre"))
        outro_cta   = st.text_input("CTA (outro)", value=loaded.get("outro_cta","Sígueme"))
        outro_handle= st.text_input("Handle (outro)", value=loaded.get("outro_handle","@tu_handle"))
        outro_sub   = st.text_input("Frase cierre", value=loaded.get("outro_sub","El cambio empieza aquí."))

    with st.expander("✦ Subtítulos automáticos (Whisper)"):
        feat_subtitles = st.toggle("Generar subtítulos", value=bool(loaded.get("feat_subtitles", False)), key="fs")
        if feat_subtitles:
            st.caption("Requiere: `pip install openai-whisper`")

    with st.expander("✦ Música de fondo"):
        feat_music  = st.toggle("Añadir música", value=bool(loaded.get("feat_music", False)), key="fm")
        music_file  = None
        music_vol   = 0.12
        if feat_music:
            music_file = st.file_uploader("Pista musical (MP3/WAV)", type=["mp3","wav","m4a"], key="music_up")
            music_vol  = st.slider("Volumen música", 0.05, 0.40, float(loaded.get("music_vol", 0.12)), 0.01)

    st.divider()

    # ── Guardar configuración ─────────────────────────────────────────────────
    st.subheader("💾 Guardar configuración")
    cfg_name = st.text_input("Nombre", value="Mi configuración", key="cfg_save_name")
    if st.button("Guardar ajustes actuales", use_container_width=True):
        settings = dict(
            formato=formato, duracion=duracion, batch=batch,
            tts=tts, voice_say=voice_say, voice_rate=voice_rate,
            voice_edge_label=voice_sel if tts=="edge-tts (Microsoft Neural)" else None,
            preset_name=preset_name, edit_colors=edit_colors,
            c_bg=colors_hex["bg"], c_accent=colors_hex["accent"], c_white=colors_hex["white"],
            c_muted=colors_hex["muted"], c_grid=colors_hex["grid"], c_blue=colors_hex["blue"],
            anim_grid=anim_grid, anim_particles=anim_particles, anim_ekg=anim_ekg,
            anim_glitch=anim_glitch, anim_scanline=anim_scanline, anim_typewriter=anim_typewriter,
            feat_glow=feat_glow, feat_gradient=feat_gradient, feat_logo=feat_logo,
            logo_pos=logo_pos, logo_size=logo_size, logo_opacity=logo_opacity,
            feat_intro_outro=feat_intro_outro, brand_name=brand_name, brand_sub=brand_sub,
            outro_cta=outro_cta, outro_handle=outro_handle, outro_sub=outro_sub,
            feat_subtitles=feat_subtitles, feat_music=feat_music, music_vol=music_vol,
        )
        cm.save_config(cfg_name, settings)
        st.success(f"Guardado: {cfg_name}")

    st.divider()

    # ── Sistema ───────────────────────────────────────────────────────────────
    sysinfo = ve.detect_system()
    st.caption(f"**{sysinfo['machine']}** · {sysinfo['label']} · {sysinfo['cores']} cores")


# ─── Tabs principales ─────────────────────────────────────────────────────────

tab_crear, tab_historial, tab_configs = st.tabs(["🎬 Crear", "🗂️ Historial", "⚙️ Configuraciones guardadas"])


# ════════════════════════════════════════════════════════════════════════════════
# TAB CREAR
# ════════════════════════════════════════════════════════════════════════════════

with tab_crear:
    col_left, col_right = st.columns([1, 1], gap="large")

    with col_left:
        st.subheader("Guión")
        guion = st.text_area(
            "guion",
            placeholder="Pega tu guión aquí.\n\nSepara con doble salto de línea para crear slides distintos.",
            height=320, label_visibility="collapsed",
        )

        MAX_RECOMENDADO = 90  # segundos — límite de atención en social media

        if guion.strip():
            preview_slides = ve.parse_script(guion, duracion)
            n_slides = len(preview_slides)

            # Mínimo cómodo: 3s/slide. Máximo recomendado: 90s.
            min_dur = n_slides * 3
            sug_dur = min(MAX_RECOMENDADO, max(duracion, min_dur))

            if min_dur > duracion:
                st.warning(
                    f"Tu guión genera **{n_slides} slides**. "
                    f"Con {duracion}s quedan **{duracion/n_slides:.1f}s/slide** — muy rápido. "
                    f"Se recomiendan al menos **{sug_dur}s** (máx. recomendado: {MAX_RECOMENDADO}s)."
                )
            elif n_slides > 0:
                st.caption(f"{n_slides} slides · {duracion/n_slides:.1f}s por slide")

            with st.expander(f"Vista previa — {n_slides} slides"):
                for i, s in enumerate(preview_slides, 1):
                    lines_preview = " / ".join(f"*{l}*" for l in s["big"] if l)
                    st.markdown(f"**{i}.** `{s['t0']}s→{s['t1']}s` — {lines_preview}")

        generar = st.button("▶ Generar video", type="primary",
                            disabled=not guion.strip(), use_container_width=True)

    with col_right:
        st.subheader("Resultado")
        placeholder_video   = st.empty()
        placeholder_status  = st.empty()
        placeholder_bar     = st.empty()
        placeholder_log     = st.empty()

    # ── Generación ────────────────────────────────────────────────────────────

    if generar and guion.strip():
        formats_to_render = list(FMTS.items()) if batch else [(formato, (W, H))]
        result_bytes      = {}

        for fmt_name, (fw, fh) in formats_to_render:
            placeholder_status.info(f"{'[BATCH] ' if batch else ''}Generando: {fmt_name} ({fw}×{fh})")
            output_dir = Path(tempfile.mkdtemp(prefix="pv_"))
            slides     = ve.parse_script(guion, duracion)
            sys_info   = ve.detect_system()
            cfg        = ve.build_cfg(output_dir, fw, fh, duracion, sys_info["codec"], colors)

            # Flags de animaciones y features
            cfg.update({
                "anim_grid": anim_grid, "anim_particles": anim_particles,
                "anim_ekg": anim_ekg, "anim_glitch": anim_glitch,
                "anim_scanline": anim_scanline, "anim_typewriter": anim_typewriter,
                "feat_glow": feat_glow, "feat_gradient": feat_gradient,
                "feat_logo": feat_logo, "feat_intro_outro": feat_intro_outro,
                "feat_subtitles": feat_subtitles, "feat_music": feat_music,
                "brand_name": brand_name, "brand_sub": brand_sub,
                "outro_cta": outro_cta, "outro_handle": outro_handle, "outro_sub": outro_sub,
                "logo_position": logo_pos, "logo_size": logo_size, "logo_opacity": logo_opacity,
                # Transición y cinematográfico
                "transition_type": transition_type,
                "feat_cinematic":  feat_cinematic,
                "feat_vignette":   feat_vignette,
                "feat_grain":      feat_grain,
                "grain_intensity": grain_intensity,
            })

            # Logo → archivo temporal
            if feat_logo and logo_file:
                logo_tmp = output_dir / f"logo{Path(logo_file.name).suffix}"
                logo_tmp.write_bytes(logo_file.getvalue())
                cfg["logo_path"] = str(logo_tmp)

            # ── Audio ─────────────────────────────────────────────────────────
            placeholder_status.info(f"[{fmt_name}] Generando audio...")
            try:
                ap = Path(cfg["audio_file"])
                if tts == "macOS say":
                    ve.generate_audio_say(guion, ap, voice_say, voice_rate)
                elif tts == "edge-tts (Microsoft Neural)":
                    ve.generate_audio_edge(guion, ap, voice_edge)
                else:
                    if not el_key or not el_voice_id:
                        st.error("Falta API Key o Voice ID de ElevenLabs.")
                        st.stop()
                    ve.generate_audio_elevenlabs(guion, ap, el_key, el_voice_id)
            except Exception as e:
                st.error(f"Error de audio: {e}")
                st.stop()

            # ── Subtítulos ─────────────────────────────────────────────────────
            if feat_subtitles:
                placeholder_status.info(f"[{fmt_name}] Transcribiendo con Whisper...")
                segs = ve.transcribe_audio(Path(cfg["audio_file"]))
                cfg["subtitle_segments"] = segs
                if not segs:
                    st.warning("Whisper no está instalado (`pip install openai-whisper`). Subtítulos omitidos.")

            # ── Intro/Outro ────────────────────────────────────────────────────
            if feat_intro_outro:
                placeholder_status.info(f"[{fmt_name}] Renderizando intro/outro...")
                ve.render_intro_parallel(cfg, slides)
                ve.render_outro_parallel(cfg, slides)

            # ── Frames principales ─────────────────────────────────────────────
            placeholder_status.info(f"[{fmt_name}] Renderizando frames...")
            bar = placeholder_bar.progress(0.0)

            def on_progress(done, total, elapsed):
                bar.progress(done / total)
                fps_r = done / max(elapsed, 0.01)
                placeholder_log.caption(f"{done/total*100:.0f}%  ·  {fps_r:.0f} frames/s  ·  {elapsed:.1f}s")

            try:
                ve.render_frames_parallel(cfg, slides, progress_cb=on_progress)
            except Exception as e:
                st.error(f"Error render: {e}")
                st.stop()

            # ── Encoding ──────────────────────────────────────────────────────
            placeholder_status.info(f"[{fmt_name}] Encodando...")
            try:
                ve.encode_video(cfg, with_intro_outro=feat_intro_outro)
            except Exception as e:
                st.error(f"Error encoding: {e}")
                st.stop()

            # ── Música ────────────────────────────────────────────────────────
            video_path = Path(cfg["video_file"])
            if feat_music and music_file:
                music_tmp = output_dir / f"music{Path(music_file.name).suffix}"
                music_tmp.write_bytes(music_file.getvalue())
                mixed     = output_dir / "output_music.mp4"
                try:
                    ve.mix_music(video_path, music_tmp, mixed, volume=music_vol)
                    video_path = mixed
                except Exception as e:
                    st.warning(f"No se pudo mezclar música: {e}")

            # ── Thumbnail ─────────────────────────────────────────────────────
            thumb_path = output_dir / "thumbnail.jpg"
            try:
                ve.extract_thumbnail(video_path, thumb_path, at_seconds=8)
            except Exception:
                thumb_path = None

            result_bytes[fmt_name] = {
                "video": video_path.read_bytes(),
                "thumb": thumb_path.read_bytes() if thumb_path and thumb_path.exists() else None,
                "size":  video_path.stat().st_size / 1_048_576,
                "W": fw, "H": fh,
            }

            # Guardar en historial
            cm.add_to_history({
                "guion_preview": guion[:120],
                "formato": fmt_name,
                "duracion": duracion,
                "tts": tts,
                "preset": preset_name,
            })

            shutil.rmtree(output_dir, ignore_errors=True)

        # ── Mostrar resultados ─────────────────────────────────────────────────
        placeholder_bar.empty()
        placeholder_log.empty()

        if batch and len(result_bytes) > 1:
            placeholder_status.success(f"Batch listo — {len(result_bytes)} formatos generados")
            for fmt_n, data in result_bytes.items():
                slug = fmt_n.split("(")[0].strip().lower().replace(" ","_").replace("/","")
                st.download_button(
                    f"⬇ Descargar {fmt_n} ({data['size']:.1f} MB)",
                    data=data["video"],
                    file_name=f"video_{slug}_{data['W']}x{data['H']}.mp4",
                    mime="video/mp4",
                    use_container_width=True,
                    key=f"dl_{fmt_n}",
                )
        else:
            data = list(result_bytes.values())[0]
            fmt_n = list(result_bytes.keys())[0]
            placeholder_status.success(f"Listo · {data['size']:.1f} MB · {data['W']}×{data['H']} · {duracion}s")

            if data["thumb"]:
                col_vid, col_thumb = st.columns([2, 1])
                with col_vid:
                    placeholder_video.video(data["video"])
                with col_thumb:
                    st.image(data["thumb"], caption="Thumbnail", use_container_width=True)
                    st.download_button("⬇ Descargar thumbnail", data["thumb"],
                                       file_name="thumbnail.jpg", mime="image/jpeg",
                                       use_container_width=True)
            else:
                placeholder_video.video(data["video"])

            slug = fmt_n.split("(")[0].strip().lower().replace(" ","_").replace("/","")
            st.download_button(f"⬇ Descargar video ({data['size']:.1f} MB)", data["video"],
                               file_name=f"video_{slug}_{data['W']}x{data['H']}.mp4",
                               mime="video/mp4", use_container_width=True)


# ════════════════════════════════════════════════════════════════════════════════
# TAB HISTORIAL
# ════════════════════════════════════════════════════════════════════════════════

with tab_historial:
    history = cm.load_history()
    if not history:
        st.info("Aún no has generado ningún video.")
    else:
        st.subheader(f"Últimos {len(history)} videos generados")
        for entry in history:
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
                c1.markdown(f"*{entry.get('guion_preview','')[:80]}…*")
                c2.caption(entry.get("formato",""))
                c3.caption(f"{entry.get('duracion','')}s · {entry.get('tts','')}")
                c4.caption(entry.get("timestamp","")[:16].replace("T"," "))


# ════════════════════════════════════════════════════════════════════════════════
# TAB CONFIGURACIONES
# ════════════════════════════════════════════════════════════════════════════════

with tab_configs:
    saved_list = cm.list_configs()
    if not saved_list:
        st.info("No tienes configuraciones guardadas todavía.")
    else:
        st.subheader("Configuraciones guardadas")
        for cfg_entry in saved_list:
            with st.container(border=True):
                c1, c2, c3 = st.columns([3, 2, 1])
                c1.markdown(f"**{cfg_entry['name']}**")
                c2.caption(cfg_entry.get("saved_at","")[:16].replace("T"," "))
                if c3.button("Cargar", key=f"load_{cfg_entry['stem']}", use_container_width=True):
                    st.session_state["loaded_cfg"] = cm.load_config(cfg_entry["stem"])
                    st.rerun()

st.divider()
st.caption("Hecho por [Dan Chojrin](https://github.com/danchojrin/local-video-generator)")

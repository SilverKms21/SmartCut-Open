#!/usr/bin/env python3
"""
SmartCut - Corte Automático de Silêncios + FCPXML / EDL + Renderização (PT-BR / EN-US | Dark / Light)
- Detecção de silêncio via FFmpeg (silencedetect)
- Interface bilíngue (Português BR / English US) com temas Claro e Escuro
- Escopo selecionável: Apenas 30s (prévia rápida) ou Vídeo todo
- Seleção explícita de Entrada Original e Saída do Arquivo
- Exportação e Importação de FCPXML (.fcpxml), EDL CMX 3600 (.edl) e JSONL
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse


# ==============================================================================
# INTERNACIONALIZAÇÃO (PT-BR / EN-US) E TEMAS (DARK / LIGHT)
# ==============================================================================

LANG_LABELS = {
    "pt_BR": "Português (BR)",
    "en_US": "English (US)",
}
LABEL_TO_LANG = {v: k for k, v in LANG_LABELS.items()}

TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "pt_BR": {
        "window_title": "SmartCut — Corte Inteligente de Silêncios",
        "subtitle": "Remoção automática de silêncios, intercâmbio FCPXML / EDL e renderização",
        "lbl_lang": "Idioma:",
        "theme_dark": "Escuro",
        "theme_light": "Claro",
        "card_io": "1. Entrada Original & Saída do Arquivo",
        "no_file": "Nenhum arquivo selecionado",
        "audio_badge": "Áudio • {dur}",
        "lbl_input": "Entrada Original:",
        "btn_browse_in": "Escolher Entrada...",
        "lbl_output": "Saída do Arquivo:",
        "btn_save_as": "Salvar Como...",
        "btn_folder": "Pasta...",
        "lbl_timeline": "Timeline (Opc.):",
        "btn_import_tl": "Importar FCPXML / EDL...",
        "btn_clear": "Limpar",
        "card_params": "2. Parâmetros de Corte Automático",
        "preset_dynamic": "Preset: Dinâmico",
        "preset_narration": "Preset: Narração",
        "slider_threshold": "Limiar de Silêncio (dB):",
        "slider_min_silence": "Silêncio Mínimo (s):",
        "slider_padding": "Margem / Padding (s):",
        "slider_merge_gap": "Fusão de Cortes (s):",
        "card_export": "3. Duração & Formatos Exportados",
        "lbl_scope": "Escopo:",
        "radio_30s": "Apenas 30s (Prévia rápida)",
        "radio_full": "Vídeo todo",
        "chk_mp4": "Renderizar MP4 (.mp4)",
        "chk_fcpxml": "Timeline FCPXML (.fcpxml)",
        "chk_edl": "Timeline EDL (.edl)",
        "chk_jsonl": "Lista JSONL (.jsonl)",
        "btn_run_30s": "Executar Prévia (Primeiros 30s)",
        "btn_run_full": "Executar no Vídeo Todo",
        "btn_run_tl": "Processar Timeline Importada",
        "btn_open_dir": "Abrir Pasta de Saída",
        "card_log": "Log de Execução",
        "status_ready": "Pronto para processar",
        "status_running": "Processando...",
        "status_done": "Concluído com sucesso",
        "status_error": "Erro durante a execução",
        "log_preset_dynamic": "Preset 'Dinâmico' aplicado (cortes rápidos e secos).",
        "log_preset_narration": "Preset 'Narração' aplicado (margem de respiro natural).",
        "log_tl_loaded": "Timeline carregada: {name} (mídia: {media})",
        "log_tl_loaded_no_media": "Timeline carregada: {name} (selecione a entrada original acima).",
        "log_tl_warn": "Aviso ao inspecionar timeline: {err}",
        "log_tl_cleared": "Timeline importada removida; modo automático reativado.",
        "log_no_out_dir": "Nenhuma pasta de saída existente para abrir ainda.",
        "dlg_warn_title": "Aviso",
        "dlg_err_title": "Erro",
        "dlg_warn_no_input": "Selecione uma Entrada Original ou importe uma timeline FCPXML/EDL.",
        "dlg_err_in_not_found": "Arquivo de entrada não encontrado:\n{path}",
        "dlg_err_tl_not_found": "Arquivo de timeline não encontrado:\n{path}",
        "dlg_in_title": "Selecione o arquivo de entrada original",
        "dlg_out_file_title": "Definir arquivo e pasta de saída",
        "dlg_out_dir_title": "Escolher pasta de saída",
        "dlg_tl_title": "Importar timeline FCPXML ou EDL",
        "ft_media": "Vídeos e Áudios",
        "ft_all": "Todos os arquivos",
        "ft_mp4": "Vídeo MP4",
        "ft_fcpxml": "Timeline FCPXML",
        "ft_edl": "Timeline EDL",
        "ft_timelines": "Timelines (FCPXML / EDL)",
        "pipe_import": "1/3 Importando cortes de {name}...",
        "pipe_imported_info": "    Mídia: {media} | Clipes importados: {count} | Duração cortada: {dur}",
        "pipe_scope_preview": "primeiros {sec}s",
        "pipe_scope_full": "vídeo completo",
        "pipe_scope_tl": "timeline importada ({count} clipes)",
        "pipe_analyzing": "1/3 Analisando silêncios ({scope}) em: {name}...",
        "pipe_no_speech": "Nenhum trecho com fala detectado nesse intervalo. Tente diminuir o limiar de dB (ex.: -38 dB).",
        "pipe_analyzed_info": "    Analisado: {orig} -> Cortado: {cut} (-{saved:.2f}s removidos | {count} clipes)",
        "pipe_dest": "    Destino: {dest}.*",
        "pipe_fcpxml_saved": "2/3 FCPXML salvo: {name}",
        "pipe_edl_saved": "2/3 EDL salvo: {name}",
        "pipe_jsonl_saved": "2/3 JSONL salvo: {name}",
        "pipe_tl_disabled": "2/3 Exportação de timelines desativada.",
        "pipe_rendering": "3/3 Renderizando arquivo ({scope}) -> {name}...",
        "pipe_done": "    Concluído: {path}",
        "pipe_render_disabled": "3/3 Renderização direta de MP4 desativada.",
    },
    "en_US": {
        "window_title": "SmartCut — Intelligent Silence Remover",
        "subtitle": "Automated silence removal, FCPXML / EDL interchange, and rendering",
        "lbl_lang": "Language:",
        "theme_dark": "Dark",
        "theme_light": "Light",
        "card_io": "1. Original Input & Output File",
        "no_file": "No file selected",
        "audio_badge": "Audio • {dur}",
        "lbl_input": "Original Input:",
        "btn_browse_in": "Browse Input...",
        "lbl_output": "Output File:",
        "btn_save_as": "Save As...",
        "btn_folder": "Folder...",
        "lbl_timeline": "Timeline (Opt.):",
        "btn_import_tl": "Import FCPXML / EDL...",
        "btn_clear": "Clear",
        "card_params": "2. Auto-Cut Parameters",
        "preset_dynamic": "Preset: Dynamic",
        "preset_narration": "Preset: Narration",
        "slider_threshold": "Silence Threshold (dB):",
        "slider_min_silence": "Min Silence Duration (s):",
        "slider_padding": "Speech Padding (s):",
        "slider_merge_gap": "Merge Gap (s):",
        "card_export": "3. Scope & Export Formats",
        "lbl_scope": "Scope:",
        "radio_30s": "First 30s (Quick preview)",
        "radio_full": "Full video",
        "chk_mp4": "Render MP4 (.mp4)",
        "chk_fcpxml": "FCPXML Timeline (.fcpxml)",
        "chk_edl": "EDL Timeline (.edl)",
        "chk_jsonl": "JSONL List (.jsonl)",
        "btn_run_30s": "Run Preview (First 30s)",
        "btn_run_full": "Run on Full Video",
        "btn_run_tl": "Process Imported Timeline",
        "btn_open_dir": "Open Output Folder",
        "card_log": "Execution Log",
        "status_ready": "Ready to process",
        "status_running": "Processing...",
        "status_done": "Completed successfully",
        "status_error": "Error during execution",
        "log_preset_dynamic": "Preset 'Dynamic' applied (tight, snappy cuts).",
        "log_preset_narration": "Preset 'Narration' applied (natural breathing room).",
        "log_tl_loaded": "Timeline loaded: {name} (media: {media})",
        "log_tl_loaded_no_media": "Timeline loaded: {name} (select original input above).",
        "log_tl_warn": "Warning inspecting timeline: {err}",
        "log_tl_cleared": "Imported timeline cleared; auto-detection re-enabled.",
        "log_no_out_dir": "No existing output folder to open yet.",
        "dlg_warn_title": "Warning",
        "dlg_err_title": "Error",
        "dlg_warn_no_input": "Select an Original Input or import an FCPXML/EDL timeline.",
        "dlg_err_in_not_found": "Input file not found:\n{path}",
        "dlg_err_tl_not_found": "Timeline file not found:\n{path}",
        "dlg_in_title": "Select original input file",
        "dlg_out_file_title": "Set output file and folder",
        "dlg_out_dir_title": "Choose output folder",
        "dlg_tl_title": "Import FCPXML or EDL timeline",
        "ft_media": "Videos & Audio",
        "ft_all": "All files",
        "ft_mp4": "MP4 Video",
        "ft_fcpxml": "FCPXML Timeline",
        "ft_edl": "EDL Timeline",
        "ft_timelines": "Timelines (FCPXML / EDL)",
        "pipe_import": "1/3 Importing cuts from {name}...",
        "pipe_imported_info": "    Media: {media} | Imported clips: {count} | Cut duration: {dur}",
        "pipe_scope_preview": "first {sec}s",
        "pipe_scope_full": "full video",
        "pipe_scope_tl": "imported timeline ({count} clips)",
        "pipe_analyzing": "1/3 Analyzing silences ({scope}) in: {name}...",
        "pipe_no_speech": "No speech segments detected in this range. Try lowering the dB threshold (e.g., -38 dB).",
        "pipe_analyzed_info": "    Analyzed: {orig} -> Cut: {cut} (-{saved:.2f}s removed | {count} clips)",
        "pipe_dest": "    Destination: {dest}.*",
        "pipe_fcpxml_saved": "2/3 FCPXML saved: {name}",
        "pipe_edl_saved": "2/3 EDL saved: {name}",
        "pipe_jsonl_saved": "2/3 JSONL saved: {name}",
        "pipe_tl_disabled": "2/3 Timeline export disabled.",
        "pipe_rendering": "3/3 Rendering file ({scope}) -> {name}...",
        "pipe_done": "    Completed: {path}",
        "pipe_render_disabled": "3/3 Direct MP4 rendering disabled.",
    },
}

THEMES: Dict[str, Dict[str, str]] = {
    "dark": {
        "bg": "#0f1115",
        "card_bg": "#161920",
        "card_border": "#262c3a",
        "input_bg": "#0b0d11",
        "btn_bg": "#222733",
        "btn_hover": "#2e3546",
        "fg": "#f1f5f9",
        "muted": "#94a3b8",
        "accent": "#3b82f6",
        "accent_hover": "#2563eb",
        "title_accent": "#60a5fa",
        "badge_bg": "#1e2533",
        "badge_fg": "#93c5fd",
        "out_fg": "#6ee7b7",
        "tl_fg": "#93c5fd",
        "log_fg": "#cbd5e1",
        "disabled_bg": "#1e293b",
        "disabled_fg": "#64748b",
    },
    "light": {
        "bg": "#f1f5f9",
        "card_bg": "#ffffff",
        "card_border": "#cbd5e1",
        "input_bg": "#f8fafc",
        "btn_bg": "#e2e8f0",
        "btn_hover": "#cbd5e1",
        "fg": "#0f172a",
        "muted": "#475569",
        "accent": "#2563eb",
        "accent_hover": "#1d4ed8",
        "title_accent": "#2563eb",
        "badge_bg": "#dbeafe",
        "badge_fg": "#1e40af",
        "out_fg": "#047857",
        "tl_fg": "#1d4ed8",
        "log_fg": "#1e293b",
        "disabled_bg": "#e2e8f0",
        "disabled_fg": "#94a3b8",
    },
}

SETTINGS_FILE = Path.home() / ".config" / "smartcut" / "settings.json"


def load_settings() -> Dict[str, str]:
    try:
        if SETTINGS_FILE.is_file():
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            lang = data.get("lang", "pt_BR")
            theme = data.get("theme", "dark")
            return {
                "lang": lang if lang in TRANSLATIONS else "pt_BR",
                "theme": theme if theme in THEMES else "dark",
            }
    except Exception:
        pass
    return {"lang": "pt_BR", "theme": "dark"}


def save_settings(lang: str, theme: str) -> None:
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(
            json.dumps({"lang": lang, "theme": theme}, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def translate(lang: str, key: str, **kwargs) -> str:
    catalog = TRANSLATIONS.get(lang, TRANSLATIONS["pt_BR"])
    template = catalog.get(key, TRANSLATIONS["pt_BR"].get(key, key))
    return template.format(**kwargs) if kwargs else template


# ==============================================================================
# NÚCLEO DE ANÁLISE E CORTE (FFMPEG / FFPROBE)
# ==============================================================================

@dataclass
class Segment:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class MediaInfo:
    duration: float
    has_video: bool
    width: int
    height: int
    fps_num: int
    fps_den: int

    @property
    def fps(self) -> float:
        return self.fps_num / self.fps_den if self.fps_den else 30.0


def probe_media_info(media_path: Path) -> MediaInfo:
    """Obtém duração, resolução e taxa de quadros exata via ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration:stream=codec_type,width,height,r_frame_rate",
        "-of", "json",
        str(media_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)

    duration = float(data.get("format", {}).get("duration", 0.0))
    has_video = False
    width = 1920
    height = 1080
    fps_num = 30
    fps_den = 1

    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            has_video = True
            width = int(stream.get("width") or 1920)
            height = int(stream.get("height") or 1080)
            rate_str = stream.get("r_frame_rate", "30/1")
            if "/" in rate_str:
                n_s, d_s = rate_str.split("/", 1)
                n_i, d_i = int(n_s), int(d_s)
                if n_i > 0 and d_i > 0:
                    fps_num, fps_den = n_i, d_i
            break

    return MediaInfo(
        duration=duration,
        has_video=has_video,
        width=width,
        height=height,
        fps_num=fps_num,
        fps_den=fps_den,
    )


def detect_silences(
    media_path: Path,
    threshold_db: float = -32.0,
    min_silence: float = 0.45,
    max_duration: Optional[float] = None,
) -> List[Segment]:
    cmd = ["ffmpeg", "-hide_banner"]
    if max_duration is not None:
        cmd.extend(["-t", f"{max_duration:.3f}"])
    cmd.extend([
        "-i", str(media_path),
        "-af", f"silencedetect=noise={threshold_db}dB:d={min_silence}",
        "-f", "null",
        "-",
    ])
    result = subprocess.run(cmd, capture_output=True, text=True)
    stderr = result.stderr

    starts = [float(m) for m in re.findall(r"silence_start:\s*([0-9.]+)", stderr)]
    ends = [float(m) for m in re.findall(r"silence_end:\s*([0-9.]+)", stderr)]

    info = probe_media_info(media_path)
    effective_dur = min(info.duration, max_duration) if max_duration is not None else info.duration

    silences: List[Segment] = []
    for idx, s_start in enumerate(starts):
        if s_start >= effective_dur:
            break
        s_end = ends[idx] if idx < len(ends) else effective_dur
        silences.append(Segment(start=s_start, end=min(s_end, effective_dur)))

    return silences


def compute_speech_segments(
    silences: List[Segment],
    total_duration: float,
    padding: float = 0.12,
    min_clip: float = 0.25,
    merge_gap: float = 0.15,
) -> List[Segment]:
    if total_duration <= 0.0:
        return []

    if not silences:
        return [Segment(0.0, total_duration)]

    raw_keep: List[Segment] = []
    cursor = 0.0

    for silence in silences:
        if silence.start > cursor:
            seg_start = max(0.0, cursor - padding)
            seg_end = min(total_duration, silence.start + padding)
            if (seg_end - seg_start) >= min_clip:
                raw_keep.append(Segment(seg_start, seg_end))
        cursor = silence.end

    if cursor < total_duration:
        seg_start = max(0.0, cursor - padding)
        seg_end = total_duration
        if (seg_end - seg_start) >= min_clip:
            raw_keep.append(Segment(seg_start, seg_end))

    merged: List[Segment] = []
    for seg in raw_keep:
        if not merged:
            merged.append(seg)
            continue
        prev = merged[-1]
        if seg.start <= (prev.end + merge_gap):
            prev.end = max(prev.end, seg.end)
        else:
            merged.append(seg)

    return merged


# ==============================================================================
# EXPORTAÇÃO E IMPORTAÇÃO: FCPXML, EDL (CMX 3600) E JSONL
# ==============================================================================

def _seconds_to_smpte(seconds: float, fps: float) -> str:
    """Converte segundos para timecode SMPTE HH:MM:SS:FF."""
    fps_int = max(1, int(round(fps)))
    total_frames = int(round(max(0.0, seconds) * fps_int))
    frames = total_frames % fps_int
    total_secs = total_frames // fps_int
    secs = total_secs % 60
    total_mins = total_secs // 60
    mins = total_mins % 60
    hours = total_mins // 60
    return f"{hours:02d}:{mins:02d}:{secs:02d}:{frames:02d}"


def _smpte_to_seconds(tc: str, fps: float) -> float:
    """Converte timecode SMPTE HH:MM:SS:FF (ou ;FF) para segundos."""
    parts = [int(x) for x in re.split(r"[:;]", tc.strip())]
    if len(parts) != 4:
        raise ValueError(f"Invalid SMPTE timecode: {tc}")
    hours, mins, secs, frames = parts
    fps_int = max(1, int(round(fps)))
    total_frames = ((hours * 3600 + mins * 60 + secs) * fps_int) + frames
    return total_frames / float(fps_int)


def export_edl(
    media_path: Path,
    segments: List[Segment],
    edl_path: Path,
    info: MediaInfo,
) -> None:
    """Exporta a timeline cortada no formato padrão CMX 3600 (.edl)."""
    fps = info.fps
    track_code = "AA/V" if info.has_video else "AA"
    lines: List[str] = [
        f"TITLE: {media_path.stem.upper()[:40]}",
        "FCM: NON-DROP FRAME",
        "",
    ]

    rec_cursor = 0.0
    for idx, seg in enumerate(segments, start=1):
        src_in = _seconds_to_smpte(seg.start, fps)
        src_out = _seconds_to_smpte(seg.end, fps)
        rec_in = _seconds_to_smpte(rec_cursor, fps)
        rec_out = _seconds_to_smpte(rec_cursor + seg.duration, fps)

        lines.append(
            f"{idx:03d}  AX       {track_code:<4}  C        {src_in} {src_out} {rec_in} {rec_out}"
        )
        lines.append(f"* FROM CLIP NAME: {media_path.name}")
        lines.append(f"* SOURCE FILE: {media_path.resolve()}")
        lines.append("")
        rec_cursor += seg.duration

    edl_path.write_text("\n".join(lines), encoding="utf-8")


def import_edl(
    edl_path: Path, fallback_media: Optional[Path] = None, fps: Optional[float] = None
) -> Tuple[List[Segment], Optional[Path]]:
    """Lê um arquivo EDL CMX 3600 e retorna os segmentos de corte e o caminho da mídia."""
    text = edl_path.read_text(encoding="utf-8", errors="replace")
    resolved_media: Optional[Path] = fallback_media

    for line in text.splitlines():
        m_src = re.match(r"^\*\s*SOURCE FILE:\s*(.+)$", line.strip(), re.IGNORECASE)
        if m_src:
            candidate = Path(m_src.group(1).strip())
            if candidate.exists():
                resolved_media = candidate
                break
        m_clip = re.match(r"^\*\s*FROM CLIP NAME:\s*(.+)$", line.strip(), re.IGNORECASE)
        if m_clip and resolved_media is None:
            candidate = edl_path.parent / m_clip.group(1).strip()
            if candidate.exists():
                resolved_media = candidate

    effective_fps = fps
    if effective_fps is None:
        if resolved_media and resolved_media.exists():
            effective_fps = probe_media_info(resolved_media).fps
        else:
            effective_fps = 30.0

    event_re = re.compile(
        r"^\d+\s+\S+\s+\S+\s+C\s+"
        r"(\d{2}:\d{2}:\d{2}[:;]\d{2})\s+"
        r"(\d{2}:\d{2}:\d{2}[:;]\d{2})\s+"
        r"(\d{2}:\d{2}:\d{2}[:;]\d{2})\s+"
        r"(\d{2}:\d{2}:\d{2}[:;]\d{2})"
    )

    segments: List[Segment] = []
    for line in text.splitlines():
        m = event_re.match(line.strip())
        if not m:
            continue
        src_in = _smpte_to_seconds(m.group(1), effective_fps)
        src_out = _smpte_to_seconds(m.group(2), effective_fps)
        if src_out > src_in:
            segments.append(Segment(start=src_in, end=src_out))

    if not segments:
        raise ValueError(f"No valid cuts found in EDL: {edl_path.name}")

    return segments, resolved_media


def _sec_to_fcpxml_time(seconds: float, fps_num: int, fps_den: int) -> str:
    """Formata segundos como tempo racional alinhado a frames para FCPXML."""
    if seconds <= 0.0:
        return "0s"
    frame_dur = Fraction(fps_den, fps_num)
    frames = int(round(Fraction(seconds) / frame_dur))
    rational = frames * frame_dur
    if rational.denominator == 1:
        return f"{rational.numerator}s"
    return f"{rational.numerator}/{rational.denominator}s"


def _fcpxml_time_to_sec(val: Optional[str]) -> float:
    """Converte tempo racional FCPXML para float."""
    if not val:
        return 0.0
    clean = val.strip().rstrip("s")
    if not clean:
        return 0.0
    return float(Fraction(clean))


def export_fcpxml(
    media_path: Path,
    segments: List[Segment],
    fcpxml_path: Path,
    info: MediaInfo,
) -> None:
    """Exporta a timeline cortada no formato FCPXML 1.9."""
    fcpxml = ET.Element("fcpxml", version="1.9")
    resources = ET.SubElement(fcpxml, "resources")

    frame_dur_str = f"{info.fps_den}/{info.fps_num}s"
    ET.SubElement(
        resources,
        "format",
        id="r1",
        name=f"VideoFormat{info.height}p{int(round(info.fps))}",
        frameDuration=frame_dur_str,
        width=str(info.width),
        height=str(info.height),
    )

    asset_dur_str = _sec_to_fcpxml_time(info.duration, info.fps_num, info.fps_den)
    asset = ET.SubElement(
        resources,
        "asset",
        id="r2",
        name=media_path.name,
        start="0s",
        duration=asset_dur_str,
        hasVideo="1" if info.has_video else "0",
        hasAudio="1",
        format="r1",
    )
    ET.SubElement(asset, "media-rep", kind="original-media", src=media_path.resolve().as_uri())

    library = ET.SubElement(fcpxml, "library")
    event = ET.SubElement(library, "event", name="SmartCut")
    project = ET.SubElement(event, "project", name=f"{media_path.stem}_smartcut")

    total_cut_dur = sum(s.duration for s in segments)
    sequence = ET.SubElement(
        project,
        "sequence",
        format="r1",
        duration=_sec_to_fcpxml_time(total_cut_dur, info.fps_num, info.fps_den),
        tcStart="0s",
        tcFormat="NDF",
    )
    spine = ET.SubElement(sequence, "spine")

    timeline_cursor = 0.0
    for idx, seg in enumerate(segments, start=1):
        clip_offset = _sec_to_fcpxml_time(timeline_cursor, info.fps_num, info.fps_den)
        clip_start = _sec_to_fcpxml_time(seg.start, info.fps_num, info.fps_den)
        clip_dur = _sec_to_fcpxml_time(seg.duration, info.fps_num, info.fps_den)

        ET.SubElement(
            spine,
            "asset-clip",
            name=f"{media_path.stem}_cut_{idx:03d}",
            ref="r2",
            offset=clip_offset,
            start=clip_start,
            duration=clip_dur,
            format="r1",
            tcFormat="NDF",
        )
        timeline_cursor += seg.duration

    ET.indent(fcpxml, space="  ")
    tree = ET.ElementTree(fcpxml)
    tree.write(fcpxml_path, encoding="utf-8", xml_declaration=True)


def import_fcpxml(
    fcpxml_path: Path, fallback_media: Optional[Path] = None
) -> Tuple[List[Segment], Optional[Path]]:
    """Lê um arquivo FCPXML e extrai os segmentos de corte e a mídia referenciada."""
    tree = ET.parse(fcpxml_path)
    root = tree.getroot()

    asset_paths: dict[str, Path] = {}
    for asset in root.findall(".//resources/asset"):
        aid = asset.get("id", "")
        src_uri = asset.get("src")
        if not src_uri:
            rep = asset.find("media-rep")
            if rep is not None:
                src_uri = rep.get("src")
        if src_uri:
            parsed = urlparse(src_uri)
            if parsed.scheme == "file":
                local_path = Path(unquote(parsed.path))
                asset_paths[aid] = local_path
            else:
                asset_paths[aid] = Path(src_uri)

    resolved_media: Optional[Path] = fallback_media
    for candidate in asset_paths.values():
        if candidate.exists():
            resolved_media = candidate
            break

    spine = root.find(".//sequence/spine")
    if spine is None:
        raise ValueError(f"No <sequence><spine> found in: {fcpxml_path.name}")

    segments: List[Segment] = []
    for node in spine:
        if node.tag not in ("asset-clip", "clip", "video"):
            continue

        ref_id = node.get("ref", "")
        if resolved_media is None and ref_id in asset_paths and asset_paths[ref_id].exists():
            resolved_media = asset_paths[ref_id]

        clip_in = _fcpxml_time_to_sec(node.get("start"))
        clip_dur = _fcpxml_time_to_sec(node.get("duration"))
        if clip_dur <= 0.0:
            continue

        segments.append(Segment(start=clip_in, end=clip_in + clip_dur))

    if not segments:
        raise ValueError(f"No valid clips found in FCPXML: {fcpxml_path.name}")

    return segments, resolved_media


def export_jsonl(media_path: Path, segments: List[Segment], output_path: Path) -> None:
    """Exporta a lista de cortes em formato JSON Lines (.jsonl)."""
    timeline_cursor = 0.0
    with output_path.open("w", encoding="utf-8") as f:
        for idx, seg in enumerate(segments, start=1):
            record = {
                "index": idx,
                "source": str(media_path.resolve()),
                "in_point": round(seg.start, 4),
                "out_point": round(seg.end, 4),
                "duration": round(seg.duration, 4),
                "timeline_start": round(timeline_cursor, 4),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            timeline_cursor += seg.duration


# ==============================================================================
# RENDERIZAÇÃO FFMPEG
# ==============================================================================

def render_cut_video(
    media_path: Path,
    keep_segments: List[Segment],
    output_path: Path,
    info: MediaInfo,
) -> Path:
    if not keep_segments:
        raise ValueError("No speech segments to render.")

    filter_lines: List[str] = []
    concat_inputs: List[str] = []

    for i, seg in enumerate(keep_segments):
        s_str = f"{seg.start:.4f}"
        e_str = f"{seg.end:.4f}"
        if info.has_video:
            filter_lines.append(f"[0:v]trim=start={s_str}:end={e_str},setpts=PTS-STARTPTS[v{i}];")
            filter_lines.append(f"[0:a]atrim=start={s_str}:end={e_str},asetpts=PTS-STARTPTS[a{i}];")
            concat_inputs.append(f"[v{i}][a{i}]")
        else:
            filter_lines.append(f"[0:a]atrim=start={s_str}:end={e_str},asetpts=PTS-STARTPTS[a{i}];")
            concat_inputs.append(f"[a{i}]")

    n_segs = len(keep_segments)
    if info.has_video:
        filter_lines.append(f"{''.join(concat_inputs)}concat=n={n_segs}:v=1:a=1[vcat][acat]")
    else:
        filter_lines.append(f"{''.join(concat_inputs)}concat=n={n_segs}:v=0:a=1[acat]")

    fd, script_name = tempfile.mkstemp(prefix="smartcut_filter_", suffix=".txt")
    os.close(fd)
    filter_script_path = Path(script_name)

    final_output = output_path if info.has_video else output_path.with_suffix(".m4a")
    final_output.parent.mkdir(parents=True, exist_ok=True)

    try:
        filter_script_path.write_text("\n".join(filter_lines), encoding="utf-8")
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(media_path),
            "-filter_complex_script", str(filter_script_path),
        ]
        if info.has_video:
            cmd.extend([
                "-map", "[vcat]",
                "-map", "[acat]",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "192k",
                "-movflags", "+faststart",
                str(final_output),
            ])
        else:
            cmd.extend([
                "-map", "[acat]",
                "-c:a", "aac",
                "-b:a", "192k",
                str(final_output),
            ])

        subprocess.run(cmd, check=True)
        return final_output
    finally:
        filter_script_path.unlink(missing_ok=True)


def format_ts(seconds: float) -> str:
    mins = int(seconds // 60)
    secs = seconds % 60
    return f"{mins:02d}:{secs:05.2f}"


def resolve_output_base(
    media_path: Path,
    suffix_tag: str,
    output_target: Optional[Path] = None,
) -> Tuple[Path, str]:
    """Resolve a pasta de destino e o nome base (stem) para todos os arquivos gerados."""
    if output_target is None:
        return media_path.parent, f"{media_path.stem}{suffix_tag}"

    target = output_target.expanduser()
    if target.exists() and target.is_dir():
        return target, f"{media_path.stem}{suffix_tag}"

    if str(output_target).endswith(("/", "\\")):
        target.mkdir(parents=True, exist_ok=True)
        return target, f"{media_path.stem}{suffix_tag}"

    target.parent.mkdir(parents=True, exist_ok=True)
    stem = target.stem if target.suffix else target.name
    if not stem:
        stem = f"{media_path.stem}{suffix_tag}"
    return target.parent, stem


def run_pipeline(
    media_path: Optional[Path] = None,
    output_target: Optional[Path] = None,
    import_timeline: Optional[Path] = None,
    threshold_db: float = -32.0,
    min_silence: float = 0.45,
    padding: float = 0.12,
    min_clip: float = 0.25,
    merge_gap: float = 0.15,
    max_duration: Optional[float] = None,
    do_export_fcpxml: bool = True,
    fcpxml_out: Optional[Path] = None,
    do_export_edl: bool = True,
    edl_out: Optional[Path] = None,
    render_mp4: bool = False,
    mp4_out: Optional[Path] = None,
    do_export_jsonl: bool = False,
    jsonl_out: Optional[Path] = None,
    lang: str = "pt_BR",
    log: Callable[[str], None] = print,
) -> Optional[Path]:
    tr = lambda k, **kw: translate(lang, k, **kw)
    keep_segments: List[Segment] = []

    if import_timeline is not None:
        if not import_timeline.exists():
            raise FileNotFoundError(f"Timeline not found: {import_timeline}")

        ext = import_timeline.suffix.lower()
        log(tr("pipe_import", name=import_timeline.name))
        if ext in (".fcpxml", ".xml"):
            keep_segments, resolved_media = import_fcpxml(
                import_timeline, fallback_media=media_path
            )
        elif ext == ".edl":
            keep_segments, resolved_media = import_edl(
                import_timeline, fallback_media=media_path
            )
        else:
            raise ValueError(f"Unsupported timeline format: {ext} (use .fcpxml or .edl)")

        if media_path is None or not media_path.exists():
            media_path = resolved_media

        if media_path is None or not media_path.exists():
            raise FileNotFoundError(
                "Could not locate the media file referenced by the timeline."
            )

        info = probe_media_info(media_path)
        suffix_tag = "_imported"
        scope_tag = tr("pipe_scope_tl", count=len(keep_segments))
        final_dur = sum(s.duration for s in keep_segments)
        log(
            tr(
                "pipe_imported_info",
                media=media_path.name,
                count=len(keep_segments),
                dur=format_ts(final_dur),
            )
        )
    else:
        if media_path is None or not media_path.exists():
            raise FileNotFoundError(f"Input file not found: {media_path}")

        info = probe_media_info(media_path)
        effective_dur = min(info.duration, max_duration) if max_duration is not None else info.duration
        scope_tag = (
            tr("pipe_scope_preview", sec=int(effective_dur))
            if max_duration is not None
            else tr("pipe_scope_full")
        )
        suffix_tag = f"_preview{int(max_duration)}s" if max_duration is not None else "_smartcut"

        log(tr("pipe_analyzing", scope=scope_tag, name=media_path.name))
        silences = detect_silences(media_path, threshold_db, min_silence, max_duration=max_duration)
        keep_segments = compute_speech_segments(
            silences, effective_dur, padding, min_clip, merge_gap
        )

        if not keep_segments:
            log(tr("pipe_no_speech"))
            return None

        final_dur = sum(s.duration for s in keep_segments)
        saved = effective_dur - final_dur
        log(
            tr(
                "pipe_analyzed_info",
                orig=format_ts(effective_dur),
                cut=format_ts(final_dur),
                saved=saved,
                count=len(keep_segments),
            )
        )

    out_dir, out_stem = resolve_output_base(media_path, suffix_tag, output_target)
    out_dir.mkdir(parents=True, exist_ok=True)
    log(tr("pipe_dest", dest=out_dir / out_stem))

    if do_export_fcpxml:
        out_fcpxml = fcpxml_out or (out_dir / f"{out_stem}.fcpxml")
        export_fcpxml(media_path, keep_segments, out_fcpxml, info)
        log(tr("pipe_fcpxml_saved", name=out_fcpxml.name))

    if do_export_edl:
        out_edl = edl_out or (out_dir / f"{out_stem}.edl")
        export_edl(media_path, keep_segments, out_edl, info)
        log(tr("pipe_edl_saved", name=out_edl.name))

    if do_export_jsonl or jsonl_out:
        out_jsonl = jsonl_out or (out_dir / f"{out_stem}.jsonl")
        export_jsonl(media_path, keep_segments, out_jsonl)
        log(tr("pipe_jsonl_saved", name=out_jsonl.name))

    if not (do_export_fcpxml or do_export_edl or do_export_jsonl or jsonl_out):
        log(tr("pipe_tl_disabled"))

    if render_mp4:
        out_video = mp4_out or (out_dir / f"{out_stem}.mp4")
        log(tr("pipe_rendering", scope=scope_tag, name=out_video.name))
        final_media = render_cut_video(
            media_path=media_path,
            keep_segments=keep_segments,
            output_path=out_video,
            info=info,
        )
        log(tr("pipe_done", path=final_media))
    else:
        log(tr("pipe_render_disabled"))

    return out_dir


# ==============================================================================
# INTERFACE GRÁFICA (TKINTER - PT-BR / EN-US & TEMAS CLARO / ESCURO)
# ==============================================================================

def launch_gui() -> None:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, scrolledtext, ttk
    except ImportError:
        print(
            "Erro / Error: Tkinter não está instalado / Tkinter is not installed.\n"
            "Debian/Ubuntu/Mint: sudo apt install python3-tk\n"
            "Arch/Manjaro/BigLinux: sudo pacman -S tk"
        )
        sys.exit(1)

    class SmartCutApp:
        def __init__(self, root: tk.Tk):
            self.root = root
            prefs = load_settings()
            self.lang: str = prefs["lang"]
            self.theme_name: str = prefs["theme"]

            self._i18n_bindings: List[Tuple[str, tk.StringVar]] = []
            self._card_frames: List[tk.Frame] = []
            self._card_headers: List[tk.Frame] = []
            self._card_titles: List[tk.Label] = []
            self._row_frames: List[tk.Frame] = []
            self._bold_labels: List[tk.Label] = []
            self._muted_labels: List[tk.Label] = []
            self._slider_val_labels: List[ttk.Label] = []
            self._entry_wrappers: List[tk.Frame] = []
            self._entries_default: List[tk.Entry] = []

            self._last_media_info: Optional[MediaInfo] = None
            self._last_media_name: Optional[str] = None
            self._status_key: str = "status_ready"

            self.root.title(self.tr("window_title"))
            self.root.geometry("800x770")
            self.root.minsize(710, 690)

            self.style = ttk.Style()
            if "clam" in self.style.theme_names():
                self.style.theme_use("clam")

            # Variáveis de controle
            self.lang_display_var = tk.StringVar(value=LANG_LABELS[self.lang])
            self.media_var = tk.StringVar()
            self.output_var = tk.StringVar()
            self.import_tl_var = tk.StringVar()
            self.media_badge_var = tk.StringVar(value=self.tr("no_file"))
            self.status_var = tk.StringVar(value=self.tr(self._status_key))
            self._output_manually_edited = False
            self._last_output_dir: Optional[Path] = None

            self.threshold_var = tk.DoubleVar(value=-32.0)
            self.min_silence_var = tk.DoubleVar(value=0.45)
            self.padding_var = tk.DoubleVar(value=0.12)
            self.merge_gap_var = tk.DoubleVar(value=0.15)

            self.scope_var = tk.StringVar(value="30s")
            self.export_fcpxml_var = tk.BooleanVar(value=True)
            self.export_edl_var = tk.BooleanVar(value=True)
            self.render_mp4_var = tk.BooleanVar(value=True)
            self.export_jsonl_var = tk.BooleanVar(value=False)

            self._build_ui(tk, ttk, scrolledtext)
            self.apply_theme(self.theme_name)

        def tr(self, key: str, **kwargs) -> str:
            return translate(self.lang, key, **kwargs)

        def _tvar(self, tk, key: str) -> tk.StringVar:
            var = tk.StringVar(value=self.tr(key))
            self._i18n_bindings.append((key, var))
            return var

        def _make_card(self, tk, parent, title_key: str, right_widget_fn=None) -> tk.Frame:
            outer = tk.Frame(parent, highlightthickness=1, padx=14, pady=11)
            outer.pack(fill=tk.X, pady=(0, 10))
            self._card_frames.append(outer)

            header = tk.Frame(outer)
            header.pack(fill=tk.X, pady=(0, 8))
            self._card_headers.append(header)

            title_lbl = tk.Label(
                header,
                textvariable=self._tvar(tk, title_key),
                font=("sans-serif", 9, "bold"),
            )
            title_lbl.pack(side=tk.LEFT)
            self._card_titles.append(title_lbl)

            if right_widget_fn:
                right_widget_fn(header)

            return outer

        def _make_entry(self, tk, parent, textvariable, role: str = "default") -> tk.Entry:
            wrapper = tk.Frame(parent, highlightthickness=1)
            wrapper.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
            self._entry_wrappers.append(wrapper)

            entry = tk.Entry(
                wrapper,
                textvariable=textvariable,
                relief=tk.FLAT,
                font=("sans-serif", 9),
            )
            entry.pack(fill=tk.X, padx=8, pady=5)

            if role == "output":
                self.output_entry = entry
            elif role == "timeline":
                self.tl_entry = entry
            else:
                self._entries_default.append(entry)

            return entry

        def _build_ui(self, tk, ttk, scrolledtext) -> None:
            self.main_frame = ttk.Frame(self.root, padding=16)
            self.main_frame.pack(fill=tk.BOTH, expand=True)

            # ------------------------------------------------------------------
            # Barra Superior: Título + Seletor de Idioma + Alternador de Tema
            # ------------------------------------------------------------------
            top_bar = ttk.Frame(self.main_frame)
            top_bar.pack(fill=tk.X, pady=(0, 12))

            title_box = ttk.Frame(top_bar)
            title_box.pack(side=tk.LEFT)
            ttk.Label(title_box, text="SmartCut", style="Header.TLabel").pack(anchor=tk.W)
            ttk.Label(
                title_box,
                textvariable=self._tvar(tk, "subtitle"),
                style="Sub.TLabel",
            ).pack(anchor=tk.W)

            controls_box = ttk.Frame(top_bar)
            controls_box.pack(side=tk.RIGHT, anchor=tk.CENTER)

            # Idioma
            ttk.Label(
                controls_box,
                textvariable=self._tvar(tk, "lbl_lang"),
                style="Sub.TLabel",
            ).pack(side=tk.LEFT, padx=(0, 5))

            self.lang_combo = ttk.Combobox(
                controls_box,
                textvariable=self.lang_display_var,
                values=list(LANG_LABELS.values()),
                state="readonly",
                width=15,
                font=("sans-serif", 9),
            )
            self.lang_combo.pack(side=tk.LEFT, padx=(0, 12))
            self.lang_combo.bind("<<ComboboxSelected>>", self._on_language_selected)

            # Seletor de Tema (Escuro / Claro)
            self.dark_btn = ttk.Button(
                controls_box,
                textvariable=self._tvar(tk, "theme_dark"),
                command=lambda: self.set_theme("dark"),
            )
            self.dark_btn.pack(side=tk.LEFT, padx=(0, 3))

            self.light_btn = ttk.Button(
                controls_box,
                textvariable=self._tvar(tk, "theme_light"),
                command=lambda: self.set_theme("light"),
            )
            self.light_btn.pack(side=tk.LEFT)

            # ------------------------------------------------------------------
            # 1. Cartão: Entrada Original & Saída do Arquivo
            # ------------------------------------------------------------------
            def add_media_badge(hdr):
                self.badge_label = tk.Label(
                    hdr,
                    textvariable=self.media_badge_var,
                    font=("sans-serif", 8, "bold"),
                    padx=9,
                    pady=2,
                )
                self.badge_label.pack(side=tk.RIGHT)

            io_card = self._make_card(tk, self.main_frame, "card_io", add_media_badge)

            # Entrada Original
            in_row = tk.Frame(io_card)
            in_row.pack(fill=tk.X, pady=(0, 8))
            self._row_frames.append(in_row)

            lbl_in = tk.Label(
                in_row,
                textvariable=self._tvar(tk, "lbl_input"),
                width=15,
                anchor=tk.W,
                font=("sans-serif", 9, "bold"),
            )
            lbl_in.pack(side=tk.LEFT)
            self._bold_labels.append(lbl_in)

            self._make_entry(tk, in_row, self.media_var, role="default")
            ttk.Button(
                in_row,
                textvariable=self._tvar(tk, "btn_browse_in"),
                style="Secondary.TButton",
                command=self.browse_input,
            ).pack(side=tk.RIGHT)

            # Saída do Arquivo
            out_row = tk.Frame(io_card)
            out_row.pack(fill=tk.X, pady=(0, 8))
            self._row_frames.append(out_row)

            lbl_out = tk.Label(
                out_row,
                textvariable=self._tvar(tk, "lbl_output"),
                width=15,
                anchor=tk.W,
                font=("sans-serif", 9, "bold"),
            )
            lbl_out.pack(side=tk.LEFT)
            self._bold_labels.append(lbl_out)

            out_entry = self._make_entry(tk, out_row, self.output_var, role="output")
            out_entry.bind("<KeyRelease>", self._on_manual_output_edit)

            ttk.Button(
                out_row,
                textvariable=self._tvar(tk, "btn_folder"),
                style="Secondary.TButton",
                command=self.browse_output_dir,
            ).pack(side=tk.RIGHT, padx=(4, 0))
            ttk.Button(
                out_row,
                textvariable=self._tvar(tk, "btn_save_as"),
                style="Secondary.TButton",
                command=self.browse_output_file,
            ).pack(side=tk.RIGHT)

            # Timeline Opcional
            tl_row = tk.Frame(io_card)
            tl_row.pack(fill=tk.X)
            self._row_frames.append(tl_row)

            lbl_tl = tk.Label(
                tl_row,
                textvariable=self._tvar(tk, "lbl_timeline"),
                width=15,
                anchor=tk.W,
                font=("sans-serif", 9),
            )
            lbl_tl.pack(side=tk.LEFT)
            self._muted_labels.append(lbl_tl)

            self._make_entry(tk, tl_row, self.import_tl_var, role="timeline")
            ttk.Button(
                tl_row,
                textvariable=self._tvar(tk, "btn_clear"),
                style="Secondary.TButton",
                command=self.clear_timeline,
            ).pack(side=tk.RIGHT, padx=(4, 0))
            ttk.Button(
                tl_row,
                textvariable=self._tvar(tk, "btn_import_tl"),
                style="Secondary.TButton",
                command=self.browse_timeline,
            ).pack(side=tk.RIGHT)

            # ------------------------------------------------------------------
            # 2. Cartão: Parâmetros de Corte Automático + Presets
            # ------------------------------------------------------------------
            def add_presets(hdr):
                p_box = tk.Frame(hdr)
                p_box.pack(side=tk.RIGHT)
                self._card_headers.append(p_box)

                ttk.Button(
                    p_box,
                    textvariable=self._tvar(tk, "preset_dynamic"),
                    style="Mini.TButton",
                    command=lambda: self.apply_preset("dynamic"),
                ).pack(side=tk.LEFT, padx=(0, 6))
                ttk.Button(
                    p_box,
                    textvariable=self._tvar(tk, "preset_narration"),
                    style="Mini.TButton",
                    command=lambda: self.apply_preset("narration"),
                ).pack(side=tk.LEFT)

            cut_card = self._make_card(tk, self.main_frame, "card_params", add_presets)
            grid_box = tk.Frame(cut_card)
            grid_box.pack(fill=tk.X)
            grid_box.columnconfigure(0, weight=1)
            grid_box.columnconfigure(1, weight=1)
            self._row_frames.append(grid_box)

            c00 = tk.Frame(grid_box)
            c00.grid(row=0, column=0, sticky="ew", padx=(0, 12), pady=(0, 6))
            self._row_frames.append(c00)
            self._add_slider(tk, c00, ttk, "slider_threshold", self.threshold_var, -60.0, -10.0, "{:.1f} dB")

            c01 = tk.Frame(grid_box)
            c01.grid(row=0, column=1, sticky="ew", padx=(12, 0), pady=(0, 6))
            self._row_frames.append(c01)
            self._add_slider(tk, c01, ttk, "slider_min_silence", self.min_silence_var, 0.15, 2.00, "{:.2f} s")

            c10 = tk.Frame(grid_box)
            c10.grid(row=1, column=0, sticky="ew", padx=(0, 12))
            self._row_frames.append(c10)
            self._add_slider(tk, c10, ttk, "slider_padding", self.padding_var, 0.00, 0.50, "{:.2f} s")

            c11 = tk.Frame(grid_box)
            c11.grid(row=1, column=1, sticky="ew", padx=(12, 0))
            self._row_frames.append(c11)
            self._add_slider(tk, c11, ttk, "slider_merge_gap", self.merge_gap_var, 0.00, 0.50, "{:.2f} s")

            # ------------------------------------------------------------------
            # 3. Cartão: Duração & Formatos Exportados
            # ------------------------------------------------------------------
            out_card = self._make_card(tk, self.main_frame, "card_export")

            scope_row = tk.Frame(out_card)
            scope_row.pack(fill=tk.X, pady=(0, 8))
            self._row_frames.append(scope_row)

            lbl_scope = tk.Label(
                scope_row,
                textvariable=self._tvar(tk, "lbl_scope"),
                font=("sans-serif", 9),
            )
            lbl_scope.pack(side=tk.LEFT, padx=(0, 12))
            self._muted_labels.append(lbl_scope)

            ttk.Radiobutton(
                scope_row,
                textvariable=self._tvar(tk, "radio_30s"),
                value="30s",
                variable=self.scope_var,
                command=self._on_scope_changed,
            ).pack(side=tk.LEFT, padx=(0, 18))

            ttk.Radiobutton(
                scope_row,
                textvariable=self._tvar(tk, "radio_full"),
                value="full",
                variable=self.scope_var,
                command=self._on_scope_changed,
            ).pack(side=tk.LEFT)

            formats_row = tk.Frame(out_card)
            formats_row.pack(fill=tk.X)
            self._row_frames.append(formats_row)

            ttk.Checkbutton(
                formats_row,
                textvariable=self._tvar(tk, "chk_mp4"),
                variable=self.render_mp4_var,
            ).pack(side=tk.LEFT, padx=(0, 14))

            ttk.Checkbutton(
                formats_row,
                textvariable=self._tvar(tk, "chk_fcpxml"),
                variable=self.export_fcpxml_var,
            ).pack(side=tk.LEFT, padx=(0, 14))

            ttk.Checkbutton(
                formats_row,
                textvariable=self._tvar(tk, "chk_edl"),
                variable=self.export_edl_var,
            ).pack(side=tk.LEFT, padx=(0, 14))

            ttk.Checkbutton(
                formats_row,
                textvariable=self._tvar(tk, "chk_jsonl"),
                variable=self.export_jsonl_var,
            ).pack(side=tk.LEFT)

            # ------------------------------------------------------------------
            # Barra de Ação Principal
            # ------------------------------------------------------------------
            action_row = ttk.Frame(self.main_frame)
            action_row.pack(fill=tk.X, pady=(2, 8))

            self.run_btn = ttk.Button(
                action_row,
                text=self.tr("btn_run_30s"),
                style="Accent.TButton",
                command=self.start_processing,
            )
            self.run_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

            self.open_dir_btn = ttk.Button(
                action_row,
                textvariable=self._tvar(tk, "btn_open_dir"),
                style="Secondary.TButton",
                command=self.open_output_folder,
            )
            self.open_dir_btn.pack(side=tk.RIGHT, fill=tk.Y)

            self.progress = ttk.Progressbar(self.main_frame, mode="indeterminate")
            self.progress.pack(fill=tk.X, pady=(0, 8))

            # ------------------------------------------------------------------
            # Console de Log
            # ------------------------------------------------------------------
            self.log_card = tk.Frame(self.main_frame, highlightthickness=1, padx=10, pady=8)
            self.log_card.pack(fill=tk.BOTH, expand=True)
            self._card_frames.append(self.log_card)

            log_hdr = tk.Frame(self.log_card)
            log_hdr.pack(fill=tk.X, pady=(0, 4))
            self._card_headers.append(log_hdr)

            log_title = tk.Label(
                log_hdr,
                textvariable=self._tvar(tk, "card_log"),
                font=("sans-serif", 9, "bold"),
            )
            log_title.pack(side=tk.LEFT)
            self._card_titles.append(log_title)

            self.status_lbl = tk.Label(
                log_hdr,
                textvariable=self.status_var,
                font=("sans-serif", 8),
            )
            self.status_lbl.pack(side=tk.RIGHT)
            self._muted_labels.append(self.status_lbl)

            self.log_box = scrolledtext.ScrolledText(
                self.log_card,
                height=7,
                font=("monospace", 9),
                relief=tk.FLAT,
                state=tk.DISABLED,
            )
            self.log_box.pack(fill=tk.BOTH, expand=True)

        def _add_slider(
            self, tk, parent, ttk, label_key: str, variable, from_: float, to: float, fmt: str
        ) -> None:
            top = ttk.Frame(parent, style="Card.TFrame")
            top.pack(fill=tk.X)
            ttk.Label(top, textvariable=self._tvar(tk, label_key)).pack(side=tk.LEFT)

            val_label = ttk.Label(top, text=fmt.format(variable.get()), style="SliderVal.TLabel")
            val_label.pack(side=tk.RIGHT)
            self._slider_val_labels.append(val_label)

            def on_slide(raw_val: str) -> None:
                rv = round(float(raw_val), 2)
                variable.set(rv)
                val_label.config(text=fmt.format(rv))

            scale = ttk.Scale(parent, from_=from_, to=to, variable=variable, command=on_slide)
            scale.pack(fill=tk.X, pady=(2, 0))

            variable.trace_add("write", lambda *_: val_label.config(text=fmt.format(variable.get())))

        # ----------------------------------------------------------------------
        # Controle de Tema e Idioma
        # ----------------------------------------------------------------------

        def set_theme(self, theme_name: str) -> None:
            if theme_name not in THEMES:
                return
            self.theme_name = theme_name
            self.apply_theme(theme_name)
            save_settings(self.lang, self.theme_name)

        def apply_theme(self, theme_name: str) -> None:
            t = THEMES[theme_name]
            self.root.configure(bg=t["bg"])

            self.style.configure("TFrame", background=t["bg"])
            self.style.configure("Card.TFrame", background=t["card_bg"])
            self.style.configure("TLabel", background=t["card_bg"], foreground=t["fg"], font=("sans-serif", 9))
            self.style.configure("SliderVal.TLabel", background=t["card_bg"], foreground=t["title_accent"], font=("sans-serif", 9, "bold"))
            self.style.configure("Header.TLabel", background=t["bg"], foreground=t["fg"], font=("sans-serif", 15, "bold"))
            self.style.configure("Sub.TLabel", background=t["bg"], foreground=t["muted"], font=("sans-serif", 9))

            self.style.configure(
                "TCheckbutton",
                background=t["card_bg"],
                foreground=t["fg"],
                font=("sans-serif", 9),
                focuscolor=t["card_bg"],
            )
            self.style.map("TCheckbutton", background=[("active", t["card_bg"])])

            self.style.configure(
                "TRadiobutton",
                background=t["card_bg"],
                foreground=t["fg"],
                font=("sans-serif", 9, "bold"),
                focuscolor=t["card_bg"],
            )
            self.style.map("TRadiobutton", background=[("active", t["card_bg"])])

            self.style.configure(
                "Horizontal.TScale",
                background=t["card_bg"],
                troughcolor=t["input_bg"],
            )

            self.style.configure(
                "Horizontal.TProgressbar",
                troughcolor=t["input_bg"],
                background=t["accent"],
                bordercolor=t["card_border"],
                lightcolor=t["accent"],
                darkcolor=t["accent"],
            )

            self.style.configure(
                "Accent.TButton",
                background=t["accent"],
                foreground="#ffffff",
                font=("sans-serif", 10, "bold"),
                borderwidth=0,
                padding=(16, 10),
            )
            self.style.map(
                "Accent.TButton",
                background=[("active", t["accent_hover"]), ("disabled", t["disabled_bg"])],
                foreground=[("disabled", t["disabled_fg"])],
            )

            self.style.configure(
                "Secondary.TButton",
                background=t["btn_bg"],
                foreground=t["fg"],
                font=("sans-serif", 9),
                borderwidth=0,
                padding=(12, 6),
            )
            self.style.map(
                "Secondary.TButton",
                background=[("active", t["btn_hover"]), ("disabled", t["disabled_bg"])],
                foreground=[("disabled", t["disabled_fg"])],
            )

            self.style.configure(
                "Mini.TButton",
                background=t["btn_bg"],
                foreground=t["fg"],
                font=("sans-serif", 8, "bold"),
                borderwidth=0,
                padding=(10, 4),
            )
            self.style.map(
                "Mini.TButton",
                background=[("active", t["btn_hover"])],
            )

            self.style.configure(
                "ThemeActive.TButton",
                background=t["accent"],
                foreground="#ffffff",
                font=("sans-serif", 8, "bold"),
                borderwidth=0,
                padding=(10, 5),
            )
            self.style.map(
                "ThemeActive.TButton",
                background=[("active", t["accent_hover"])],
            )

            self.style.configure(
                "ThemeInactive.TButton",
                background=t["btn_bg"],
                foreground=t["muted"],
                font=("sans-serif", 8),
                borderwidth=0,
                padding=(10, 5),
            )
            self.style.map(
                "ThemeInactive.TButton",
                background=[("active", t["btn_hover"])],
                foreground=[("active", t["fg"])],
            )

            self.style.configure(
                "TCombobox",
                fieldbackground=t["btn_bg"],
                background=t["btn_bg"],
                foreground=t["fg"],
                arrowcolor=t["fg"],
                bordercolor=t["card_border"],
                padding=(6, 4),
            )
            self.style.map(
                "TCombobox",
                fieldbackground=[("readonly", t["btn_bg"])],
                foreground=[("readonly", t["fg"])],
                selectbackground=[("readonly", t["btn_bg"])],
                selectforeground=[("readonly", t["fg"])],
            )

            self.dark_btn.configure(
                style="ThemeActive.TButton" if theme_name == "dark" else "ThemeInactive.TButton"
            )
            self.light_btn.configure(
                style="ThemeActive.TButton" if theme_name == "light" else "ThemeInactive.TButton"
            )

            for card in self._card_frames:
                card.configure(bg=t["card_bg"], highlightbackground=t["card_border"])
            for hdr in self._card_headers:
                hdr.configure(bg=t["card_bg"])
            for title in self._card_titles:
                title.configure(bg=t["card_bg"], fg=t["title_accent"])
            for row in self._row_frames:
                row.configure(bg=t["card_bg"])
            for lbl in self._bold_labels:
                lbl.configure(bg=t["card_bg"], fg=t["fg"])
            for lbl in self._muted_labels:
                lbl.configure(bg=t["card_bg"], fg=t["muted"])

            self.badge_label.configure(bg=t["badge_bg"], fg=t["badge_fg"])

            for wrap in self._entry_wrappers:
                wrap.configure(bg=t["input_bg"], highlightbackground=t["card_border"])
            for ent in self._entries_default:
                ent.configure(bg=t["input_bg"], fg=t["fg"], insertbackground=t["fg"])

            self.output_entry.configure(bg=t["input_bg"], fg=t["out_fg"], insertbackground=t["fg"])
            self.tl_entry.configure(bg=t["input_bg"], fg=t["tl_fg"], insertbackground=t["fg"])
            self.log_box.configure(bg=t["input_bg"], fg=t["log_fg"], insertbackground=t["fg"])

        def _on_language_selected(self, _event=None) -> None:
            chosen_label = self.lang_display_var.get()
            new_lang = LABEL_TO_LANG.get(chosen_label, "pt_BR")
            if new_lang == self.lang:
                return
            self.lang = new_lang
            self.root.title(self.tr("window_title"))

            for key, var in self._i18n_bindings:
                var.set(self.tr(key))

            self.status_var.set(self.tr(self._status_key))
            self._update_run_label()
            self._refresh_media_badge()
            save_settings(self.lang, self.theme_name)

        def _set_status(self, status_key: str) -> None:
            self._status_key = status_key
            self.status_var.set(self.tr(status_key))

        def _refresh_media_badge(self) -> None:
            if self._last_media_info is not None:
                info = self._last_media_info
                if info.has_video:
                    self.media_badge_var.set(
                        f"{info.width}x{info.height} • {info.fps:.2f} fps • {format_ts(info.duration)}"
                    )
                else:
                    self.media_badge_var.set(self.tr("audio_badge", dur=format_ts(info.duration)))
            elif self._last_media_name:
                self.media_badge_var.set(self._last_media_name)
            else:
                self.media_badge_var.set(self.tr("no_file"))

        # ----------------------------------------------------------------------
        # Ações de Entrada, Saída e Execução
        # ----------------------------------------------------------------------

        def _default_suffix(self) -> str:
            if self.import_tl_var.get().strip():
                return "_imported"
            return "_preview30s" if self.scope_var.get() == "30s" else "_smartcut"

        def _sync_default_output(self, force: bool = False) -> None:
            raw_in = self.media_var.get().strip()
            if not raw_in:
                return
            in_path = Path(raw_in)
            suffix = self._default_suffix()

            if force or not self._output_manually_edited or not self.output_var.get().strip():
                suggested = in_path.with_name(f"{in_path.stem}{suffix}.mp4")
                self.output_var.set(str(suggested))
                self._output_manually_edited = False

        def _on_manual_output_edit(self, _event=None) -> None:
            self._output_manually_edited = True

        def _on_scope_changed(self) -> None:
            self._update_run_label()
            self._sync_default_output(force=False)

        def _update_run_label(self) -> None:
            if self.import_tl_var.get().strip():
                self.run_btn.configure(text=self.tr("btn_run_tl"))
            elif self.scope_var.get() == "30s":
                self.run_btn.configure(text=self.tr("btn_run_30s"))
            else:
                self.run_btn.configure(text=self.tr("btn_run_full"))

        def _probe_and_update_badge(self, media_path: Path) -> None:
            def worker() -> None:
                try:
                    info = probe_media_info(media_path)
                    self._last_media_info = info
                    self._last_media_name = media_path.name
                    self.root.after(0, self._refresh_media_badge)
                except Exception:
                    self._last_media_info = None
                    self._last_media_name = media_path.name
                    self.root.after(0, self._refresh_media_badge)

            threading.Thread(target=worker, daemon=True).start()

        def apply_preset(self, mode: str) -> None:
            if mode == "dynamic":
                self.threshold_var.set(-30.0)
                self.min_silence_var.set(0.35)
                self.padding_var.set(0.08)
                self.merge_gap_var.set(0.10)
                self.append_log(self.tr("log_preset_dynamic"))
            elif mode == "narration":
                self.threshold_var.set(-32.0)
                self.min_silence_var.set(0.45)
                self.padding_var.set(0.12)
                self.merge_gap_var.set(0.15)
                self.append_log(self.tr("log_preset_narration"))

        def browse_input(self) -> None:
            from tkinter import filedialog
            path = filedialog.askopenfilename(
                title=self.tr("dlg_in_title"),
                filetypes=[
                    (self.tr("ft_media"), "*.mp4 *.mkv *.mov *.webm *.avi *.wav *.mp3 *.flac *.m4a"),
                    (self.tr("ft_all"), "*.*"),
                ],
            )
            if path:
                p = Path(path)
                self.media_var.set(str(p))
                self._output_manually_edited = False
                self._sync_default_output(force=True)
                self._probe_and_update_badge(p)

        def browse_output_file(self) -> None:
            from tkinter import filedialog
            current = self.output_var.get().strip()
            init_dir = str(Path(current).parent) if current else str(Path.home())
            init_name = Path(current).name if current else "output_smartcut.mp4"

            path = filedialog.asksaveasfilename(
                title=self.tr("dlg_out_file_title"),
                initialdir=init_dir,
                initialfile=init_name,
                defaultextension=".mp4",
                filetypes=[
                    (self.tr("ft_mp4"), "*.mp4"),
                    (self.tr("ft_fcpxml"), "*.fcpxml"),
                    (self.tr("ft_edl"), "*.edl"),
                    (self.tr("ft_all"), "*.*"),
                ],
            )
            if path:
                self.output_var.set(path)
                self._output_manually_edited = True

        def browse_output_dir(self) -> None:
            from tkinter import filedialog
            current = self.output_var.get().strip()
            init_dir = str(Path(current).parent) if current else str(Path.home())
            folder = filedialog.askdirectory(title=self.tr("dlg_out_dir_title"), initialdir=init_dir)
            if folder:
                stem = Path(current).stem if current else (
                    f"{Path(self.media_var.get().strip()).stem}{self._default_suffix()}"
                    if self.media_var.get().strip()
                    else "output_smartcut"
                )
                self.output_var.set(str(Path(folder) / f"{stem}.mp4"))
                self._output_manually_edited = True

        def open_output_folder(self) -> None:
            target_dir = self._last_output_dir
            if target_dir is None:
                raw_out = self.output_var.get().strip()
                if raw_out:
                    p = Path(raw_out)
                    target_dir = p if p.is_dir() else p.parent
            if target_dir and target_dir.exists():
                subprocess.Popen(["xdg-open", str(target_dir)])
            else:
                self.append_log(self.tr("log_no_out_dir"))

        def browse_timeline(self) -> None:
            from tkinter import filedialog
            path = filedialog.askopenfilename(
                title=self.tr("dlg_tl_title"),
                filetypes=[
                    (self.tr("ft_timelines"), "*.fcpxml *.xml *.edl"),
                    (self.tr("ft_all"), "*.*"),
                ],
            )
            if path:
                tl_path = Path(path)
                self.import_tl_var.set(str(tl_path))
                self._update_run_label()
                try:
                    if tl_path.suffix.lower() in (".fcpxml", ".xml"):
                        _, media_ref = import_fcpxml(tl_path)
                    else:
                        _, media_ref = import_edl(tl_path)
                    if media_ref and media_ref.exists():
                        self.media_var.set(str(media_ref))
                        self._probe_and_update_badge(media_ref)
                        self._sync_default_output(force=False)
                        self.append_log(self.tr("log_tl_loaded", name=tl_path.name, media=media_ref.name))
                    else:
                        self.append_log(self.tr("log_tl_loaded_no_media", name=tl_path.name))
                except Exception as exc:
                    self.append_log(self.tr("log_tl_warn", err=exc))

        def clear_timeline(self) -> None:
            self.import_tl_var.set("")
            self._update_run_label()
            self._sync_default_output(force=False)
            self.append_log(self.tr("log_tl_cleared"))

        def append_log(self, text: str) -> None:
            def _write() -> None:
                self.log_box.configure(state=tk.NORMAL)
                self.log_box.insert(tk.END, text + "\n")
                self.log_box.see(tk.END)
                self.log_box.configure(state=tk.DISABLED)

            self.root.after(0, _write)

        def start_processing(self) -> None:
            from tkinter import messagebox
            raw_media = self.media_var.get().strip()
            raw_tl = self.import_tl_var.get().strip()
            raw_out = self.output_var.get().strip()

            if not raw_media and not raw_tl:
                messagebox.showwarning(self.tr("dlg_warn_title"), self.tr("dlg_warn_no_input"))
                return

            media_path = Path(raw_media) if raw_media else None
            tl_path = Path(raw_tl) if raw_tl else None
            out_target = Path(raw_out) if raw_out else None

            if media_path and not media_path.exists():
                messagebox.showerror(
                    self.tr("dlg_err_title"),
                    self.tr("dlg_err_in_not_found", path=media_path),
                )
                return

            if tl_path and not tl_path.exists():
                messagebox.showerror(
                    self.tr("dlg_err_title"),
                    self.tr("dlg_err_tl_not_found", path=tl_path),
                )
                return

            self.log_box.configure(state=tk.NORMAL)
            self.log_box.delete("1.0", tk.END)
            self.log_box.configure(state=tk.DISABLED)

            self.run_btn.configure(state=tk.DISABLED)
            self._set_status("status_running")
            self.progress.start(12)

            max_dur = 30.0 if (self.scope_var.get() == "30s" and tl_path is None) else None

            params = dict(
                media_path=media_path,
                output_target=out_target,
                import_timeline=tl_path,
                threshold_db=float(self.threshold_var.get()),
                min_silence=float(self.min_silence_var.get()),
                padding=float(self.padding_var.get()),
                merge_gap=float(self.merge_gap_var.get()),
                max_duration=max_dur,
                do_export_fcpxml=bool(self.export_fcpxml_var.get()),
                do_export_edl=bool(self.export_edl_var.get()),
                render_mp4=bool(self.render_mp4_var.get()),
                do_export_jsonl=bool(self.export_jsonl_var.get()),
                lang=self.lang,
                log=self.append_log,
            )

            def worker() -> None:
                try:
                    saved_dir = run_pipeline(**params)
                    self._last_output_dir = saved_dir
                    self.root.after(0, lambda: self._set_status("status_done"))
                except Exception as exc:
                    self.append_log(f"\n[ERROR] {exc}")
                    self.root.after(0, lambda: self._set_status("status_error"))
                finally:
                    self.root.after(0, self._on_finished)

            threading.Thread(target=worker, daemon=True).start()

        def _on_finished(self) -> None:
            self.progress.stop()
            self.run_btn.configure(state=tk.NORMAL)

    root = tk.Tk()
    SmartCutApp(root)
    root.mainloop()


def main() -> None:
    if len(sys.argv) == 1 or "--gui" in sys.argv:
        launch_gui()
        return

    parser = argparse.ArgumentParser(description="SmartCut - Auto Silence Remover + FCPXML/EDL + Render")
    parser.add_argument("media", nargs="?", type=Path, help="Path to original input video or audio")
    parser.add_argument("-o", "--output", type=Path, help="Output folder or base file path")
    parser.add_argument("--gui", action="store_true", help="Launch graphical interface")
    parser.add_argument("--lang", choices=["pt", "en"], default="pt", help="CLI log language (pt or en)")
    parser.add_argument("--import-timeline", type=Path, help="Import cuts from .fcpxml or .edl file")
    parser.add_argument("--preview-30s", action="store_true", help="Process only first 30 seconds")
    parser.add_argument("--max-duration", type=float, default=None, help="Limit processing to first N seconds")
    parser.add_argument("--threshold", type=float, default=-32.0, help="Silence threshold in dB")
    parser.add_argument("--min-silence", type=float, default=0.45, help="Minimum silence duration in s")
    parser.add_argument("--padding", type=float, default=0.12, help="Padding before/after speech in s")
    parser.add_argument("--min-clip", type=float, default=0.25, help="Minimum kept speech segment in s")
    parser.add_argument("--merge-gap", type=float, default=0.15, help="Merge cuts closer than N seconds")
    parser.add_argument("--no-fcpxml", action="store_true", help="Disable .fcpxml export")
    parser.add_argument("--fcpxml-out", type=Path, help="Custom output path for .fcpxml")
    parser.add_argument("--no-edl", action="store_true", help="Disable .edl export")
    parser.add_argument("--edl-out", type=Path, help="Custom output path for .edl")
    parser.add_argument("--render-mp4", action="store_true", help="Render cut MP4 via FFmpeg")
    parser.add_argument("--mp4-out", type=Path, help="Custom output path for rendered MP4")
    parser.add_argument("--jsonl", type=Path, help="Export cut list to .jsonl file")
    args = parser.parse_args()

    if not args.media and not args.import_timeline:
        parser.error("Provide an input media path or use --import-timeline <file.fcpxml|file.edl>.")

    max_dur = 30.0 if args.preview_30s else args.max_duration
    lang_code = "en_US" if args.lang == "en" else "pt_BR"

    run_pipeline(
        media_path=args.media,
        output_target=args.output,
        import_timeline=args.import_timeline,
        threshold_db=args.threshold,
        min_silence=args.min_silence,
        padding=args.padding,
        min_clip=args.min_clip,
        merge_gap=args.merge_gap,
        max_duration=max_dur,
        do_export_fcpxml=not args.no_fcpxml,
        fcpxml_out=args.fcpxml_out,
        do_export_edl=not args.no_edl,
        edl_out=args.edl_out,
        render_mp4=args.render_mp4,
        mp4_out=args.mp4_out,
        do_export_jsonl=bool(args.jsonl),
        jsonl_out=args.jsonl,
        lang=lang_code,
    )


if __name__ == "__main__":
    main()

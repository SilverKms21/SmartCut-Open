#!/usr/bin/env python3
"""
SmartCut - Corte Automático de Silêncios + FCPXML / EDL + Renderização (GUI + CLI)
- Detecção de silêncio via FFmpeg (silencedetect)
- Escopo selecionável: Apenas 30s (prévia rápida) ou Vídeo todo
- Seleção explícita de Entrada Original e Saída do Arquivo
- Exportação e Importação de FCPXML (.fcpxml) e EDL CMX 3600 (.edl)
- Renderização direta de MP4 cortado e exportação de lista de cortes em JSONL
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
from typing import Callable, List, Optional, Tuple
from urllib.parse import unquote, urlparse


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
        raise ValueError(f"Timecode SMPTE inválido: {tc}")
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
        raise ValueError(f"Nenhum corte válido encontrado no EDL: {edl_path.name}")

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
        raise ValueError(f"Nenhuma <sequence><spine> encontrada em: {fcpxml_path.name}")

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
        raise ValueError(f"Nenhum clipe válido encontrado no FCPXML: {fcpxml_path.name}")

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
        raise ValueError("Nenhum segmento com fala para renderizar.")

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
    """
    Resolve a pasta de destino e o nome base (stem) para todos os arquivos gerados.
    Aceita tanto um diretório quanto um caminho de arquivo com ou sem extensão.
    """
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
    log: Callable[[str], None] = print,
) -> Optional[Path]:
    keep_segments: List[Segment] = []

    # 1. Obter cortes (via importação FCPXML/EDL ou detecção automática de silêncio)
    if import_timeline is not None:
        if not import_timeline.exists():
            raise FileNotFoundError(f"Timeline não encontrada: {import_timeline}")

        ext = import_timeline.suffix.lower()
        log(f"1/3 Importando cortes de {import_timeline.name}...")
        if ext in (".fcpxml", ".xml"):
            keep_segments, resolved_media = import_fcpxml(
                import_timeline, fallback_media=media_path
            )
        elif ext == ".edl":
            keep_segments, resolved_media = import_edl(
                import_timeline, fallback_media=media_path
            )
        else:
            raise ValueError(f"Formato de timeline não suportado: {ext} (use .fcpxml ou .edl)")

        if media_path is None or not media_path.exists():
            media_path = resolved_media

        if media_path is None or not media_path.exists():
            raise FileNotFoundError(
                "Não foi possível localizar o arquivo de vídeo/áudio referenciado pela timeline. "
                "Selecione a mídia manualmente no campo 'Entrada Original'."
            )

        info = probe_media_info(media_path)
        suffix_tag = "_imported"
        scope_tag = f"timeline importada ({len(keep_segments)} clipes)"
        final_dur = sum(s.duration for s in keep_segments)
        log(
            f"    Mídia: {media_path.name} | Clipes importados: {len(keep_segments)} "
            f"| Duração cortada: {format_ts(final_dur)}"
        )
    else:
        if media_path is None or not media_path.exists():
            raise FileNotFoundError(f"Arquivo de entrada não encontrado: {media_path}")

        info = probe_media_info(media_path)
        effective_dur = min(info.duration, max_duration) if max_duration is not None else info.duration
        scope_tag = f"primeiros {int(effective_dur)}s" if max_duration is not None else "vídeo completo"
        suffix_tag = f"_preview{int(max_duration)}s" if max_duration is not None else "_smartcut"

        log(f"1/3 Analisando silêncios ({scope_tag}) em: {media_path.name}...")
        silences = detect_silences(media_path, threshold_db, min_silence, max_duration=max_duration)
        keep_segments = compute_speech_segments(
            silences, effective_dur, padding, min_clip, merge_gap
        )

        if not keep_segments:
            log("Nenhum trecho com fala detectado nesse intervalo. Tente diminuir o limiar de dB (ex.: -38 dB).")
            return None

        final_dur = sum(s.duration for s in keep_segments)
        saved = effective_dur - final_dur
        log(
            f"    Analisado: {format_ts(effective_dur)} -> Cortado: {format_ts(final_dur)} "
            f"(-{saved:.2f}s removidos | {len(keep_segments)} clipes)"
        )

    out_dir, out_stem = resolve_output_base(media_path, suffix_tag, output_target)
    out_dir.mkdir(parents=True, exist_ok=True)
    log(f"    Destino: {out_dir / out_stem}.*")

    # 2. Exportação de timelines FCPXML / EDL / JSONL
    if do_export_fcpxml:
        out_fcpxml = fcpxml_out or (out_dir / f"{out_stem}.fcpxml")
        export_fcpxml(media_path, keep_segments, out_fcpxml, info)
        log(f"2/3 FCPXML salvo: {out_fcpxml.name}")

    if do_export_edl:
        out_edl = edl_out or (out_dir / f"{out_stem}.edl")
        export_edl(media_path, keep_segments, out_edl, info)
        log(f"2/3 EDL salvo: {out_edl.name}")

    if do_export_jsonl or jsonl_out:
        out_jsonl = jsonl_out or (out_dir / f"{out_stem}.jsonl")
        export_jsonl(media_path, keep_segments, out_jsonl)
        log(f"2/3 JSONL salvo: {out_jsonl.name}")

    if not (do_export_fcpxml or do_export_edl or do_export_jsonl or jsonl_out):
        log("2/3 Exportação de timelines desativada.")

    # 3. Renderização MP4
    if render_mp4:
        out_video = mp4_out or (out_dir / f"{out_stem}.mp4")
        log(f"3/3 Renderizando arquivo ({scope_tag}) -> {out_video.name}...")
        final_media = render_cut_video(
            media_path=media_path,
            keep_segments=keep_segments,
            output_path=out_video,
            info=info,
        )
        log(f"    Concluído: {final_media}")
    else:
        log("3/3 Renderização direta de MP4 desativada.")

    return out_dir


# ==============================================================================
# INTERFACE GRÁFICA MODERNIZADA (TKINTER)
# ==============================================================================

def launch_gui() -> None:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, scrolledtext, ttk
    except ImportError:
        print(
            "Erro: Tkinter não está instalado neste Python.\n"
            "No Debian/Ubuntu/Linux Mint: sudo apt install python3-tk\n"
            "No Arch/Manjaro/BigLinux:     sudo pacman -S tk"
        )
        sys.exit(1)

    class SmartCutApp:
        def __init__(self, root: tk.Tk):
            self.root = root
            self.root.title("SmartCut — Corte Inteligente de Silêncios")
            self.root.geometry("760x760")
            self.root.minsize(680, 680)

            # Paleta moderna escura (Slate / Obsidian)
            self.bg = "#0f1115"
            self.card_bg = "#161920"
            self.card_border = "#252a36"
            self.input_bg = "#0b0d11"
            self.btn_bg = "#222733"
            self.btn_hover = "#2d3444"
            self.fg = "#f1f5f9"
            self.muted = "#94a3b8"
            self.accent = "#3b82f6"
            self.accent_hover = "#2563eb"
            self.success = "#10b981"

            self.root.configure(bg=self.bg)
            self._setup_styles(ttk)

            # Estado da interface
            self.media_var = tk.StringVar()
            self.output_var = tk.StringVar()
            self.import_tl_var = tk.StringVar()
            self.media_badge_var = tk.StringVar(value="Nenhum arquivo selecionado")
            self.status_var = tk.StringVar(value="Pronto para processar")
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

        def _setup_styles(self, ttk) -> None:
            style = ttk.Style()
            if "clam" in style.theme_names():
                style.theme_use("clam")

            style.configure("TFrame", background=self.bg)
            style.configure("Card.TFrame", background=self.card_bg)
            style.configure("TLabel", background=self.card_bg, foreground=self.fg, font=("sans-serif", 9))
            style.configure("Muted.TLabel", background=self.card_bg, foreground=self.muted, font=("sans-serif", 8))
            style.configure("Header.TLabel", background=self.bg, foreground=self.fg, font=("sans-serif", 15, "bold"))
            style.configure("Sub.TLabel", background=self.bg, foreground=self.muted, font=("sans-serif", 9))

            style.configure(
                "TCheckbutton",
                background=self.card_bg,
                foreground=self.fg,
                font=("sans-serif", 9),
                focuscolor=self.card_bg,
            )
            style.map("TCheckbutton", background=[("active", self.card_bg)])

            style.configure(
                "TRadiobutton",
                background=self.card_bg,
                foreground=self.fg,
                font=("sans-serif", 9, "bold"),
                focuscolor=self.card_bg,
            )
            style.map("TRadiobutton", background=[("active", self.card_bg)])

            style.configure(
                "Horizontal.TScale",
                background=self.card_bg,
                troughcolor=self.input_bg,
            )

            style.configure(
                "Horizontal.TProgressbar",
                troughcolor=self.input_bg,
                background=self.accent,
                bordercolor=self.card_border,
                lightcolor=self.accent,
                darkcolor=self.accent,
            )

            style.configure(
                "Accent.TButton",
                background=self.accent,
                foreground="#ffffff",
                font=("sans-serif", 10, "bold"),
                borderwidth=0,
                padding=(16, 10),
            )
            style.map(
                "Accent.TButton",
                background=[("active", self.accent_hover), ("disabled", "#1e293b")],
                foreground=[("disabled", "#64748b")],
            )

            style.configure(
                "Secondary.TButton",
                background=self.btn_bg,
                foreground=self.fg,
                font=("sans-serif", 9),
                borderwidth=0,
                padding=(12, 6),
            )
            style.map(
                "Secondary.TButton",
                background=[("active", self.btn_hover), ("disabled", "#181b22")],
                foreground=[("disabled", "#475569")],
            )

        def _make_card(self, tk, parent, title: str, right_widget_fn=None):
            outer = tk.Frame(
                parent,
                bg=self.card_bg,
                highlightbackground=self.card_border,
                highlightthickness=1,
                padx=14,
                pady=11,
            )
            outer.pack(fill=tk.X, pady=(0, 10))

            header = tk.Frame(outer, bg=self.card_bg)
            header.pack(fill=tk.X, pady=(0, 8))

            tk.Label(
                header,
                text=title.upper(),
                bg=self.card_bg,
                fg="#60a5fa",
                font=("sans-serif", 8, "bold"),
            ).pack(side=tk.LEFT)

            if right_widget_fn:
                right_widget_fn(header)

            return outer

        def _make_entry(self, tk, parent, textvariable, fg_color=None) -> tk.Entry:
            wrapper = tk.Frame(
                parent,
                bg=self.input_bg,
                highlightbackground=self.card_border,
                highlightthickness=1,
            )
            wrapper.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

            entry = tk.Entry(
                wrapper,
                textvariable=textvariable,
                bg=self.input_bg,
                fg=fg_color or self.fg,
                insertbackground=self.fg,
                relief=tk.FLAT,
                font=("sans-serif", 9),
            )
            entry.pack(fill=tk.X, padx=8, pady=5)
            return entry

        def _build_ui(self, tk, ttk, scrolledtext) -> None:
            main = ttk.Frame(self.root, padding=16)
            main.pack(fill=tk.BOTH, expand=True)

            # Cabeçalho Superior
            top_bar = ttk.Frame(main)
            top_bar.pack(fill=tk.X, pady=(0, 12))

            title_box = ttk.Frame(top_bar)
            title_box.pack(side=tk.LEFT)
            ttk.Label(title_box, text="SmartCut", style="Header.TLabel").pack(anchor=tk.W)
            ttk.Label(
                title_box,
                text="Remoção inteligente de silêncios, intercâmbio FCPXML / EDL e renderização",
                style="Sub.TLabel",
            ).pack(anchor=tk.W)

            preset_box = ttk.Frame(top_bar)
            preset_box.pack(side=tk.RIGHT, anchor=tk.CENTER)
            ttk.Button(
                preset_box,
                text="Preset: Dinâmico",
                style="Secondary.TButton",
                command=lambda: self.apply_preset("dynamic"),
            ).pack(side=tk.LEFT, padx=(0, 6))
            ttk.Button(
                preset_box,
                text="Preset: Narração",
                style="Secondary.TButton",
                command=lambda: self.apply_preset("narration"),
            ).pack(side=tk.LEFT)

            # 1. Cartão: Entrada Original e Saída do Arquivo
            def add_media_badge(hdr):
                tk.Label(
                    hdr,
                    textvariable=self.media_badge_var,
                    bg="#1e2430",
                    fg="#93c5fd",
                    font=("sans-serif", 8),
                    padx=8,
                    pady=2,
                ).pack(side=tk.RIGHT)

            io_card = self._make_card(tk, main, "1. Entrada Original & Saída do Arquivo", add_media_badge)

            # Linha Entrada Original
            in_row = tk.Frame(io_card, bg=self.card_bg)
            in_row.pack(fill=tk.X, pady=(0, 8))
            tk.Label(
                in_row, text="Entrada Original:", width=14, anchor=tk.W,
                bg=self.card_bg, fg=self.fg, font=("sans-serif", 9, "bold"),
            ).pack(side=tk.LEFT)
            self._make_entry(tk, in_row, self.media_var)
            ttk.Button(
                in_row, text="Escolher Entrada...", style="Secondary.TButton", command=self.browse_input
            ).pack(side=tk.RIGHT)

            # Linha Saída do Arquivo
            out_row = tk.Frame(io_card, bg=self.card_bg)
            out_row.pack(fill=tk.X, pady=(0, 8))
            tk.Label(
                out_row, text="Saída do Arquivo:", width=14, anchor=tk.W,
                bg=self.card_bg, fg=self.fg, font=("sans-serif", 9, "bold"),
            ).pack(side=tk.LEFT)
            out_entry = self._make_entry(tk, out_row, self.output_var, fg_color="#6ee7b7")
            out_entry.bind("<KeyRelease>", self._on_manual_output_edit)

            ttk.Button(
                out_row, text="Pasta...", style="Secondary.TButton", command=self.browse_output_dir
            ).pack(side=tk.RIGHT, padx=(4, 0))
            ttk.Button(
                out_row, text="Salvar Como...", style="Secondary.TButton", command=self.browse_output_file
            ).pack(side=tk.RIGHT)

            # Linha Opcional: Importar Timeline Existente (FCPXML / EDL)
            tl_row = tk.Frame(io_card, bg=self.card_bg)
            tl_row.pack(fill=tk.X)
            tk.Label(
                tl_row, text="Timeline (Opc.):", width=14, anchor=tk.W,
                bg=self.card_bg, fg=self.muted, font=("sans-serif", 9),
            ).pack(side=tk.LEFT)
            self._make_entry(tk, tl_row, self.import_tl_var, fg_color="#93c5fd")
            ttk.Button(
                tl_row, text="Limpar", style="Secondary.TButton", command=self.clear_timeline
            ).pack(side=tk.RIGHT, padx=(4, 0))
            ttk.Button(
                tl_row, text="Importar FCPXML / EDL...", style="Secondary.TButton", command=self.browse_timeline
            ).pack(side=tk.RIGHT)

            # 2. Cartão: Parâmetros de Detecção de Silêncio (em grid 2x2)
            cut_card = self._make_card(tk, main, "2. Parâmetros de Corte Automático")
            grid_box = tk.Frame(cut_card, bg=self.card_bg)
            grid_box.pack(fill=tk.X)
            grid_box.columnconfigure(0, weight=1)
            grid_box.columnconfigure(1, weight=1)

            c00 = tk.Frame(grid_box, bg=self.card_bg)
            c00.grid(row=0, column=0, sticky="ew", padx=(0, 12), pady=(0, 6))
            self._add_slider(c00, ttk, "Limiar de Silêncio (dB):", self.threshold_var, -60.0, -10.0, "{:.1f} dB")

            c01 = tk.Frame(grid_box, bg=self.card_bg)
            c01.grid(row=0, column=1, sticky="ew", padx=(12, 0), pady=(0, 6))
            self._add_slider(c01, ttk, "Silêncio Mínimo (s):", self.min_silence_var, 0.15, 2.00, "{:.2f} s")

            c10 = tk.Frame(grid_box, bg=self.card_bg)
            c10.grid(row=1, column=0, sticky="ew", padx=(0, 12))
            self._add_slider(c10, ttk, "Margem / Padding (s):", self.padding_var, 0.00, 0.50, "{:.2f} s")

            c11 = tk.Frame(grid_box, bg=self.card_bg)
            c11.grid(row=1, column=1, sticky="ew", padx=(12, 0))
            self._add_slider(c11, ttk, "Fusão de Cortes (s):", self.merge_gap_var, 0.00, 0.50, "{:.2f} s")

            # 3. Cartão: Escopo e Formatos de Saída
            out_card = self._make_card(tk, main, "3. Duração & Formatos Exportados")

            scope_row = tk.Frame(out_card, bg=self.card_bg)
            scope_row.pack(fill=tk.X, pady=(0, 8))

            tk.Label(
                scope_row, text="Escopo:", bg=self.card_bg, fg=self.muted, font=("sans-serif", 9)
            ).pack(side=tk.LEFT, padx=(0, 12))

            ttk.Radiobutton(
                scope_row,
                text="Apenas 30s (Prévia rápida)",
                value="30s",
                variable=self.scope_var,
                command=self._on_scope_changed,
            ).pack(side=tk.LEFT, padx=(0, 18))

            ttk.Radiobutton(
                scope_row,
                text="Vídeo todo",
                value="full",
                variable=self.scope_var,
                command=self._on_scope_changed,
            ).pack(side=tk.LEFT)

            formats_row = tk.Frame(out_card, bg=self.card_bg)
            formats_row.pack(fill=tk.X)

            ttk.Checkbutton(
                formats_row, text="Renderizar MP4 (.mp4)", variable=self.render_mp4_var
            ).pack(side=tk.LEFT, padx=(0, 14))

            ttk.Checkbutton(
                formats_row, text="Timeline FCPXML (.fcpxml)", variable=self.export_fcpxml_var
            ).pack(side=tk.LEFT, padx=(0, 14))

            ttk.Checkbutton(
                formats_row, text="Timeline EDL (.edl)", variable=self.export_edl_var
            ).pack(side=tk.LEFT, padx=(0, 14))

            ttk.Checkbutton(
                formats_row, text="Lista JSONL (.jsonl)", variable=self.export_jsonl_var
            ).pack(side=tk.LEFT)

            # Barra de Ação Principal
            action_row = ttk.Frame(main)
            action_row.pack(fill=tk.X, pady=(2, 8))

            self.run_btn = ttk.Button(
                action_row,
                text="Executar Prévia (Primeiros 30s)",
                style="Accent.TButton",
                command=self.start_processing,
            )
            self.run_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

            self.open_dir_btn = ttk.Button(
                action_row,
                text="Abrir Pasta de Saída",
                style="Secondary.TButton",
                command=self.open_output_folder,
            )
            self.open_dir_btn.pack(side=tk.RIGHT, fill=tk.Y)

            self.progress = ttk.Progressbar(main, mode="indeterminate")
            self.progress.pack(fill=tk.X, pady=(0, 8))

            # Console de Saída
            log_card = tk.Frame(
                main,
                bg=self.card_bg,
                highlightbackground=self.card_border,
                highlightthickness=1,
                padx=10,
                pady=8,
            )
            log_card.pack(fill=tk.BOTH, expand=True)

            log_hdr = tk.Frame(log_card, bg=self.card_bg)
            log_hdr.pack(fill=tk.X, pady=(0, 4))
            tk.Label(
                log_hdr, text="LOG DE EXECUÇÃO", bg=self.card_bg, fg="#60a5fa", font=("sans-serif", 8, "bold")
            ).pack(side=tk.LEFT)
            tk.Label(
                log_hdr, textvariable=self.status_var, bg=self.card_bg, fg=self.muted, font=("sans-serif", 8)
            ).pack(side=tk.RIGHT)

            self.log_box = scrolledtext.ScrolledText(
                log_card,
                height=7,
                bg=self.input_bg,
                fg="#cbd5e1",
                font=("monospace", 9),
                relief=tk.FLAT,
                state=tk.DISABLED,
            )
            self.log_box.pack(fill=tk.BOTH, expand=True)

        def _add_slider(
            self, parent, ttk, label_text: str, variable, from_: float, to: float, fmt: str
        ) -> None:
            top = ttk.Frame(parent, style="Card.TFrame")
            top.pack(fill=tk.X)
            ttk.Label(top, text=label_text).pack(side=tk.LEFT)

            val_label = ttk.Label(top, text=fmt.format(variable.get()), foreground="#60a5fa")
            val_label.pack(side=tk.RIGHT)

            def on_slide(raw_val: str) -> None:
                rv = round(float(raw_val), 2)
                variable.set(rv)
                val_label.config(text=fmt.format(rv))

            scale = ttk.Scale(parent, from_=from_, to=to, variable=variable, command=on_slide)
            scale.pack(fill=tk.X, pady=(2, 0))

            variable.trace_add("write", lambda *_: val_label.config(text=fmt.format(variable.get())))

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
                self.run_btn.configure(text="Processar Timeline Importada")
            elif self.scope_var.get() == "30s":
                self.run_btn.configure(text="Executar Prévia (Primeiros 30s)")
            else:
                self.run_btn.configure(text="Executar no Vídeo Todo")

        def _probe_and_update_badge(self, media_path: Path) -> None:
            def worker() -> None:
                try:
                    info = probe_media_info(media_path)
                    if info.has_video:
                        badge = f"{info.width}x{info.height} • {info.fps:.2f} fps • {format_ts(info.duration)}"
                    else:
                        badge = f"Áudio • {format_ts(info.duration)}"
                    self.root.after(0, lambda: self.media_badge_var.set(badge))
                except Exception:
                    self.root.after(0, lambda: self.media_badge_var.set(media_path.name))

            threading.Thread(target=worker, daemon=True).start()

        def apply_preset(self, mode: str) -> None:
            if mode == "dynamic":
                self.threshold_var.set(-30.0)
                self.min_silence_var.set(0.35)
                self.padding_var.set(0.08)
                self.merge_gap_var.set(0.10)
                self.append_log("Preset 'Dinâmico' aplicado (cortes rápidos e secos).")
            elif mode == "narration":
                self.threshold_var.set(-32.0)
                self.min_silence_var.set(0.45)
                self.padding_var.set(0.12)
                self.merge_gap_var.set(0.15)
                self.append_log("Preset 'Narração' aplicado (margem de respiro natural).")

        def browse_input(self) -> None:
            from tkinter import filedialog
            path = filedialog.askopenfilename(
                title="Selecione o arquivo de entrada original",
                filetypes=[
                    ("Vídeos e Áudios", "*.mp4 *.mkv *.mov *.webm *.avi *.wav *.mp3 *.flac *.m4a"),
                    ("Todos os arquivos", "*.*"),
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
            init_name = Path(current).name if current else "saida_smartcut.mp4"

            path = filedialog.asksaveasfilename(
                title="Definir arquivo e pasta de saída",
                initialdir=init_dir,
                initialfile=init_name,
                defaultextension=".mp4",
                filetypes=[
                    ("Vídeo MP4", "*.mp4"),
                    ("Timeline FCPXML", "*.fcpxml"),
                    ("Timeline EDL", "*.edl"),
                    ("Todos os arquivos", "*.*"),
                ],
            )
            if path:
                self.output_var.set(path)
                self._output_manually_edited = True

        def browse_output_dir(self) -> None:
            from tkinter import filedialog
            current = self.output_var.get().strip()
            init_dir = str(Path(current).parent) if current else str(Path.home())
            folder = filedialog.askdirectory(title="Escolher pasta de saída", initialdir=init_dir)
            if folder:
                stem = Path(current).stem if current else (
                    f"{Path(self.media_var.get().strip()).stem}{self._default_suffix()}"
                    if self.media_var.get().strip()
                    else "saida_smartcut"
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
                self.append_log("Nenhuma pasta de saída existente para abrir ainda.")

        def browse_timeline(self) -> None:
            from tkinter import filedialog
            path = filedialog.askopenfilename(
                title="Importar timeline FCPXML ou EDL",
                filetypes=[
                    ("Timelines (FCPXML / EDL)", "*.fcpxml *.xml *.edl"),
                    ("Todos os arquivos", "*.*"),
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
                        self.append_log(f"Timeline carregada: {tl_path.name} (mídia: {media_ref.name})")
                    else:
                        self.append_log(f"Timeline carregada: {tl_path.name} (selecione a entrada original acima).")
                except Exception as exc:
                    self.append_log(f"Aviso ao inspecionar timeline: {exc}")

        def clear_timeline(self) -> None:
            self.import_tl_var.set("")
            self._update_run_label()
            self._sync_default_output(force=False)
            self.append_log("Timeline importada removida; modo automático reativado.")

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
                messagebox.showwarning("Aviso", "Selecione uma Entrada Original ou importe uma timeline FCPXML/EDL.")
                return

            media_path = Path(raw_media) if raw_media else None
            tl_path = Path(raw_tl) if raw_tl else None
            out_target = Path(raw_out) if raw_out else None

            if media_path and not media_path.exists():
                messagebox.showerror("Erro", f"Arquivo de entrada não encontrado:\n{media_path}")
                return

            if tl_path and not tl_path.exists():
                messagebox.showerror("Erro", f"Arquivo de timeline não encontrado:\n{tl_path}")
                return

            self.log_box.configure(state=tk.NORMAL)
            self.log_box.delete("1.0", tk.END)
            self.log_box.configure(state=tk.DISABLED)

            self.run_btn.configure(state=tk.DISABLED)
            self.status_var.set("Processando...")
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
                log=self.append_log,
            )

            def worker() -> None:
                try:
                    saved_dir = run_pipeline(**params)
                    self._last_output_dir = saved_dir
                    self.root.after(0, lambda: self.status_var.set("Concluído com sucesso"))
                except Exception as exc:
                    self.append_log(f"\n[ERRO] {exc}")
                    self.root.after(0, lambda: self.status_var.set("Erro durante a execução"))
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

    parser = argparse.ArgumentParser(description="SmartCut - Corte Automático + FCPXML/EDL + Render")
    parser.add_argument("media", nargs="?", type=Path, help="Caminho do vídeo ou áudio de entrada original")
    parser.add_argument("-o", "--output", type=Path, help="Pasta ou caminho base de saída dos arquivos")
    parser.add_argument("--gui", action="store_true", help="Abre a interface gráfica")
    parser.add_argument("--import-timeline", type=Path, help="Importa cortes de um arquivo .fcpxml ou .edl")
    parser.add_argument("--preview-30s", action="store_true", help="Processa apenas os primeiros 30s")
    parser.add_argument("--max-duration", type=float, default=None, help="Limita aos primeiros N segundos")
    parser.add_argument("--threshold", type=float, default=-32.0, help="Limiar de silêncio em dB")
    parser.add_argument("--min-silence", type=float, default=0.45, help="Silêncio mínimo em s")
    parser.add_argument("--padding", type=float, default=0.12, help="Margem antes/depois da fala em s")
    parser.add_argument("--min-clip", type=float, default=0.25, help="Duração mínima de trecho falado em s")
    parser.add_argument("--merge-gap", type=float, default=0.15, help="Funde cortes próximos em s")
    parser.add_argument("--no-fcpxml", action="store_true", help="Desativa exportação .fcpxml")
    parser.add_argument("--fcpxml-out", type=Path, help="Caminho de saída do .fcpxml")
    parser.add_argument("--no-edl", action="store_true", help="Desativa exportação .edl")
    parser.add_argument("--edl-out", type=Path, help="Caminho de saída do .edl")
    parser.add_argument("--render-mp4", action="store_true", help="Renderiza o MP4 cortado via FFmpeg")
    parser.add_argument("--mp4-out", type=Path, help="Caminho de saída do MP4 renderizado")
    parser.add_argument("--jsonl", type=Path, help="Exporta lista de cortes para arquivo .jsonl")
    args = parser.parse_args()

    if not args.media and not args.import_timeline:
        parser.error("Informe o caminho da mídia ou use --import-timeline <arquivo.fcpxml|arquivo.edl>.")

    max_dur = 30.0 if args.preview_30s else args.max_duration

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
    )


if __name__ == "__main__":
    main()

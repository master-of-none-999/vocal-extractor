from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import streamlit as st

from vocal_extractor import (
    AIModelType,
    OutputFormat,
    SeparationError,
    SeparationJob,
    SeparationMode,
    SeparationResult,
    check_device_status,
    run_separation,
)

st.set_page_config(
    page_title="人聲分離工房 Vocal Extractor",
    page_icon=":material/mic:",
    layout="centered",
)


def format_duration(seconds: float) -> str:
    mins, secs = divmod(int(round(seconds)), 60)
    return f"{mins}:{secs:02d}"


def get_mime_type(fmt: str) -> str:
    return {
        "wav": "audio/wav",
        "mp3": "audio/mpeg",
        "flac": "audio/flac",
    }.get(fmt, "audio/wav")


def open_folder_in_explorer(folder: Path) -> None:
    if os.name == "nt" and folder.exists():
        subprocess.Popen(["explorer", str(folder.resolve())])


def install_cuda_pytorch() -> tuple[bool, str]:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--force-reinstall",
        "torch",
        "torchaudio",
        "--index-url",
        "https://download.pytorch.org/whl/cu128",
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
        check=False,
    )
    output = "\n".join(p for p in (proc.stdout, proc.stderr) if p)
    return (proc.returncode == 0), output


st.session_state.setdefault("separation_result", None)

st.title("🎤 人聲分離工房 Vocal Extractor")
st.caption(
    "純本機離線 AI 音訊分離工具 —— 精確將「純人聲 (Vocals)」與「純背景音樂 (Instrumental)」分離、即時對比試聽並匯出高音質音軌。"
)

with st.container(horizontal=True):
    st.badge("100% 本機運行", icon=":material/shield_lock:", color="green")
    st.badge("Demucs AI 深度分離", icon=":material/psychology:", color="violet")
    st.badge("人聲 + 伴奏雙軌輸出", icon=":material/graphic_eq:", color="blue")

device_status = check_device_status()

with st.sidebar:
    st.subheader("⚙️ 系統硬體與引擎狀態")
    if device_status.demucs_installed:
        st.badge("Demucs AI 已就緒", icon=":material/check_circle:", color="green")
    else:
        st.badge("Demucs AI 未安裝", icon=":material/warning:", color="orange")
        st.caption(
            "高精準 AI 模式需先雙擊 `install-ai.bat` 或執行 `.\\setup.ps1 -WithAI` 安裝。"
        )

    if device_status.cuda_available:
        st.badge(device_status.device_name, icon=":material/bolt:", color="blue")
        st.caption(f"PyTorch 版本：`{device_status.torch_version}`（已啟用 GPU 硬體加速）")
    else:
        st.badge("運算裝置：CPU 模式", icon=":material/memory:", color="orange")
        st.caption(f"目前 PyTorch 版本：`{device_status.torch_version}`")
        if device_status.nvidia_gpu_detected:
            st.warning(
                "偵測到本機配備 NVIDIA RTX 顯示卡，但目前 `.venv` 安裝的是 CPU 版 PyTorch (`+cpu`)。"
            )
            if st.button(
                "⚡ 一鍵安裝 CUDA 12.8 版 PyTorch (啟用 RTX 5060 Ti 加速)",
                type="primary",
                use_container_width=True,
            ):
                with st.spinner(
                    "正在下載並安裝 PyTorch CUDA 12.8 (約 2.5GB，需時數分鐘，請勿關閉視窗)…"
                ):
                    ok, log_text = install_cuda_pytorch()
                if ok:
                    st.success(
                        "✅ CUDA 12.8 版 PyTorch 安裝完成！請關閉終端機視窗並重新雙擊 `start.bat` 以載入 GPU 驅動。"
                    )
                else:
                    st.error(f"安裝失敗：\n{log_text[-600:]}")

    if device_status.ffmpeg_available:
        st.badge("FFmpeg 音訊引擎正常", icon=":material/check:", color="green")
    else:
        st.badge("FFmpeg 未就緒", icon=":material/error:", color="red")

    st.divider()
    st.markdown(
        """
        **💡 模型選擇建議**
        - **`htdemucs`（預設）**：Meta Hybrid Transformer 模型，兼具高人聲淨度與處理速度。
        - **`htdemucs_ft`（極致精確）**：4 倍微調集成模型，人聲邊緣最乾淨、樂器殘留最少（配合 RTX 5060 Ti 極快）。
        - **`mdx_extra_q`**：針對主唱人聲特別強化嘅 MDX-Net 模型。
        """
    )

with st.container(border=True):
    st.subheader("1. 選擇音訊或影片來源")
    source_choice = st.segmented_control(
        "輸入來源",
        ["本機音訊／影片檔", "YouTube 連結"],
        default="本機音訊／影片檔",
        required=True,
        width="stretch",
        key="source_choice",
    )

    uploaded_file = None
    youtube_url = ""

    if source_choice == "本機音訊／影片檔":
        uploaded_file = st.file_uploader(
            "上載音訊或影片檔案",
            type=[
                "mp3",
                "wav",
                "flac",
                "m4a",
                "aac",
                "ogg",
                "mp4",
                "mov",
                "mkv",
                "webm",
            ],
            help="支援常見無損/有損音訊 (WAV, FLAC, MP3, M4A) 及影片檔 (MP4, MKV, MOV)。",
        )
    else:
        youtube_url = st.text_input(
            "YouTube 影片或音樂連結",
            placeholder="https://www.youtube.com/watch?v=...",
            help="程式只會直接擷取最高音質音軌進行分離，唔會浪費時間下載影片畫面。",
        )

with st.container(border=True):
    st.subheader("2. 分離精度與輸出設定")

    col_mode, col_fmt = st.columns(2)
    with col_mode:
        mode_label = st.selectbox(
            "分離引擎模式",
            options=[
                "Demucs AI 精確分離（推薦）",
                "FFmpeg 快速相位提取（免 AI 極速預覽）",
            ],
            index=0 if device_status.demucs_installed else 1,
        )
        selected_mode: SeparationMode = (
            "ai" if mode_label.startswith("Demucs") else "fast_center"
        )

    with col_fmt:
        fmt_label = st.selectbox(
            "輸出音訊格式",
            options=[
                "WAV（無損 44.1kHz 16-bit）",
                "MP3（320kbps 高音質）",
                "FLAC（無損壓縮）",
            ],
            index=0,
        )
        if fmt_label.startswith("WAV"):
            selected_format: OutputFormat = "wav"
        elif fmt_label.startswith("MP3"):
            selected_format = "mp3"
        else:
            selected_format = "flac"

    selected_ai_model: AIModelType = "htdemucs"
    if selected_mode == "ai":
        model_option = st.selectbox(
            "AI 分離模型（精確度設定）",
            options=[
                "htdemucs — 標準高精準 Hybrid Transformer（推薦）",
                "htdemucs_ft — 極致精細微調版（最乾淨人聲，運算較慢）",
                "mdx_extra_q — MDX-Net 人聲強化模型",
            ],
            index=0,
        )
        if model_option.startswith("htdemucs_ft"):
            selected_ai_model = "htdemucs_ft"
        elif model_option.startswith("mdx_extra_q"):
            selected_ai_model = "mdx_extra_q"
        else:
            selected_ai_model = "htdemucs"

    with st.expander("🛠️ 進階人聲淨化與後製設定（可選）"):
        adv_col1, adv_col2, adv_col3 = st.columns(3)
        with adv_col1:
            highpass_hz = st.selectbox(
                "人聲低頻切除 (High-pass)",
                options=[0, 70, 90, 110],
                format_func=lambda x: "關閉 (0 Hz)" if x == 0 else f"{x} Hz（濾除低音鼓殘留）",
                index=0,
                help="切除人聲頻段以外嘅超低頻震動或大鼓殘留，令人聲更乾淨。",
            )
        with adv_col2:
            vocal_boost_db = st.slider(
                "人聲音量增益 (dB)",
                min_value=-6.0,
                max_value=6.0,
                value=0.0,
                step=0.5,
                help="調整輸出純人聲音軌嘅音量大小。",
            )
        with adv_col3:
            shifts = st.slider(
                "AI 隨機平移次數 (Shifts)",
                min_value=1,
                max_value=4,
                value=1,
                help="數值越高人聲分離越精準，但處理時間會按倍數增加（1 為標準速度）。",
                disabled=(selected_mode != "ai"),
            )

start_btn = st.button(
    "🚀 開始精確分離人聲與背景音樂",
    type="primary",
    use_container_width=True,
)

if start_btn:
    progress_bar = st.progress(0.0, text="準備啟動分離程序…")

    def on_progress(stage: str, value: float, message: str) -> None:
        progress_bar.progress(value, text=message)

    try:
        job = SeparationJob(
            source_type="youtube" if source_choice == "YouTube 連結" else "upload",
            youtube_url=youtube_url,
            upload_name=uploaded_file.name if uploaded_file else "",
            upload_bytes=uploaded_file.getvalue() if uploaded_file else None,
            mode=selected_mode,
            ai_model=selected_ai_model,
            output_format=selected_format,
            shifts=shifts,
            overlap=0.25,
            vocal_boost_db=vocal_boost_db,
            highpass_hz=highpass_hz,
        )
        result = run_separation(job, callback=on_progress)
        st.session_state["separation_result"] = result
        progress_bar.progress(1.0, text="✅ 分離完成！")
    except SeparationError as err:
        progress_bar.empty()
        st.error(str(err))
    except Exception as exc:
        progress_bar.empty()
        st.error(f"處理時發生未預期錯誤：{exc}")

saved_result: SeparationResult | None = st.session_state.get("separation_result")

if saved_result and saved_result.vocals_path.exists():
    st.divider()
    st.subheader(f"🎧 分離結果：{saved_result.title}")
    st.caption(
        f"來源：{saved_result.artist} ｜ 長度：{format_duration(saved_result.duration)} ｜ "
        f"引擎：{saved_result.model_used} ({saved_result.device_used}) ｜ "
        f"格式：{saved_result.output_format.upper()}"
    )

    mime = get_mime_type(saved_result.output_format)

    vocal_col, inst_col = st.columns(2)

    with vocal_col:
        with st.container(border=True):
            st.markdown("#### 🎤 純人聲 (Vocals)")
            st.caption("已分離移除背景樂器嘅獨立主唱／人聲音軌")
            vocal_bytes = saved_result.vocals_path.read_bytes()
            st.audio(vocal_bytes, format=mime)
            st.download_button(
                label=f"⬇️ 下載純人聲 (.{saved_result.output_format})",
                data=vocal_bytes,
                file_name=saved_result.vocals_path.name,
                mime=mime,
                type="primary",
                use_container_width=True,
                key="dl_vocals",
            )

    with inst_col:
        with st.container(border=True):
            st.markdown("#### 🎵 純背景音樂 (Instrumental)")
            st.caption("已消除人聲嘅純伴奏／背景音樂音軌")
            inst_bytes = saved_result.instrumental_path.read_bytes()
            st.audio(inst_bytes, format=mime)
            st.download_button(
                label=f"⬇️ 下載純背景音樂 (.{saved_result.output_format})",
                data=inst_bytes,
                file_name=saved_result.instrumental_path.name,
                mime=mime,
                use_container_width=True,
                key="dl_inst",
            )

    if saved_result.original_preview_path.exists():
        with st.expander("🔁 對比原始未分離音軌 (Original A/B 試聽)"):
            st.audio(
                saved_result.original_preview_path.read_bytes(),
                format="audio/mpeg",
            )

    info_col, action_col = st.columns([3, 2])
    with info_col:
        st.info(f"📁 檔案已自動儲存至本機：`{saved_result.output_folder}`")
    with action_col:
        if st.button("📂 在 Windows 檔案總管開啟", use_container_width=True):
            open_folder_in_explorer(saved_result.output_folder)

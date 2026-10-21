# Changelog

All notable changes to **Vocal Extractor (人聲分離工房)** will be documented in this file.

## [0.1.0] - 2026-10-20
### Added
- 參考 `wongsir1011/karaoke-factory` 本機架構，建立專注於精確分離純人聲 (`Vocals`) 與純背景音樂 (`Instrumental`) 的 Windows 本機應用程式。
- 新增 [`vocal_extractor/separator.py`](file:///C:/Users/user/Documents/MCP/vocal-extractor/vocal_extractor/separator.py) 核心分離引擎：
  - 支援 Demucs v4 AI 模型（`htdemucs`、`htdemucs_ft` 精細微調版、`mdx_extra_q`）雙軌分離 (`--two-stems=vocals`)。
  - 自動偵測 NVIDIA CUDA GPU 加速或 CPU 運算。
  - 支援 FFmpeg 中置聲道提取與相位抵消快速模式（免 AI 備援）。
  - 支援本機音訊/影片上載與 YouTube 最佳音軌直接擷取（`yt-dlp`）。
  - 支援輸出 `WAV`（無損 16-bit）、`MP3`（320kbps）、`FLAC`（無損壓縮）及人聲低頻切濾（High-pass Filter）與音量增益微調。
- 新增 [`streamlit_app.py`](file:///C:/Users/user/Documents/MCP/vocal-extractor/streamlit_app.py) 互動介面，提供純人聲、純背景音樂及原始音軌三軌即時試聽對比與獨立下載。
- 新增 Windows 一鍵安裝與啟動腳本（`setup.ps1`、`install-ai.bat`、`start.ps1`、`start.bat`）。

### Fixed
- 修正 Windows PowerShell 5.1 讀取無 BOM UTF-8 `.ps1` 腳本時的中文雙引號解析錯誤（改為純 ASCII 腳本輸出）。
- 修正首次執行 Streamlit 時因等待輸入 Email (`credentials.toml`) 而卡住、無法自動彈出瀏覽器的問題，並將預設 Port 設為 `8500`、就緒後自動呼叫 `Start-Process` 開啟預設瀏覽器。
- 強化 `setup.ps1` 搜尋系統 Python 路徑邏輯，避開 Windows Store 空白 `python.exe` stub。
- 修正 TorchAudio 2.6+/2.9+ 預設呼叫 `save_with_torchcodec` 導致 `ImportError: TorchCodec is required` 的問題：在 [`DEMUCS_SOUNDFILE_RUNNER`](file:///C:/Users/user/Documents/MCP/vocal-extractor/vocal_extractor/separator.py#L46-L75) 中改以 `soundfile` 接管 `torchaudio.load` 與 `torchaudio.save`。
- 針對 **NVIDIA GeForce RTX 5060 Ti (Blackwell 架構)** 支援：在 `setup.ps1 -WithAI` 與網頁側邊欄加入自動安裝 `CUDA 12.8 (cu128)` 版 PyTorch 的機制，取代 PyPI 預設的 `+cpu` 版本。

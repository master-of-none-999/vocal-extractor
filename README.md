# 🎤 人聲分離工房 (Vocal Extractor)

架構設計 **100% Windows 本機運行 AI 人聲與背景音樂分離工具**。

本專案 **Vocal Extractor** 則專注於**高精準度提取純人聲 (`Vocals`) 與純背景音樂 (`Instrumental`)**，提供三軌即時對比試聽與無損匯出。

---

## ✨ 核心功能

- **雙輸入來源**：
  - **本機音訊／影片檔**：支援 `MP3`, `WAV`, `FLAC`, `M4A`, `AAC`, `OGG`, `MP4`, `MOV`, `MKV`, `WEBM`。
  - **YouTube 連結**：使用 `yt-dlp` 直接擷取最佳音軌（免下載龐大視訊流，速度更快）。
- **雙重分離引擎**：
  - **Demucs AI 深度分離（推薦）**：採用 Meta 開源的 Demucs v4 (`--two-stems=vocals`)，支援切換三種模型：
    - `htdemucs`（預設：Hybrid Transformer，速度與人聲淨度最佳平衡）
    - `htdemucs_ft`（4 倍精細微調模型，人聲邊緣最乾淨、樂器殘留最少）
    - `mdx_extra_q`（MDX-Net 主唱強化模型）
  - **FFmpeg 快速相位提取**：免安裝 AI 套件即可即時提取中置人聲與消除伴奏。
- **人聲後製微調**：
  - 支援 **High-pass 低頻切除（70Hz / 90Hz / 110Hz）**，濾除低音大鼓或環境低頻殘留。
  - 支援 **人聲音量增益（-6dB 至 +6dB）** 與 **AI 隨機平移次數（Shifts）** 設定。
- **多格式雙軌匯出與即時 A/B 對比試聽**：
  - 同時輸出 **`Vocals (純人聲)`** 與 **`Instrumental (純伴奏)`**。
  - 支援選擇 **`WAV (無損 16-bit)`**、**`MP3 (320kbps)`** 或 **`FLAC (無損壓縮)`**。
  - 網頁介面內建三軌播放器（純人聲／純伴奏／原始音軌），並可一鍵打開 Windows 檔案總管檢視成品。

---

## 🚀 開始使用（Windows）

### 1. 安裝高精準 Demucs AI 模式（首次使用必做）
直接雙擊專案目錄下的 **`install-ai.bat`**，或在 PowerShell 執行：

```powershell
.\setup.ps1 -WithAI
```

> 💡 第一次進行 AI 分離時，Demucs 會自動下載對應的預訓練模型權重並快取於本機。

### 2. 啟動應用程式
直接雙擊 **`start.bat`**，或在 PowerShell 執行：

```powershell
.\start.ps1
```

瀏覽器會自動開啟 `http://127.0.0.1:8500`。

---

## 📁 輸出檔案位置
所有分離完成的純人聲與純背景音樂檔案，會自動保存在專案下的 **`outputs/`** 資料夾（按歌曲名稱建立獨立子資料夾），臨時工作檔則置於 `work/jobs/` 並在成功後自動清理。

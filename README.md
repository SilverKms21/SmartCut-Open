# SmartCut

Ferramenta de automação de edição de vídeo e áudio que analisa a faixa sonora via **FFmpeg** (`silencedetect`), remove pausas e silêncios automaticamente, exporta timelines padronizadas em **FCPXML** e **EDL**, e renderiza prévias ou vídeos completos em **MP4**.

---

## Recursos

- **Entrada Original e Saída Personalizável:** Selecione qualquer vídeo ou áudio de entrada (com leitura automática de resolução, FPS e duração) e defina livremente o nome e a pasta de destino dos arquivos exportados.
- **Detecção Automática de Silêncios:** Ajuste fino de limiar em decibéis (`dB`), duração mínima de silêncio, margem de respiro (*padding*) e fusão de cortes próximos (*merge gap*), além dos presets rápidos **Dinâmico** e **Narração**.
- **Prévia Rápida (30s) ou Vídeo Completo:** Teste o ritmo dos cortes nos primeiros 30 segundos antes de processar o arquivo inteiro.
- **Intercâmbio FCPXML 1.9, EDL CMX 3600 e JSONL:**
  - **Exportação:** Gera `.fcpxml` (tempos racionais alinhados a quadros), `.edl` (timecodes SMPTE `HH:MM:SS:FF` baseados no FPS real do vídeo) e `.jsonl`.
  - **Importação:** Carrega timelines `.fcpxml` ou `.edl` existentes para converter formatos entre si ou renderizar o vídeo cortado diretamente.
- **Renderização Direta via FFmpeg:** Exporta vídeo cortado em `H.264 / AAC` (`libx264`, `-crf 20`) ou áudio em `.m4a`.
- **Interface Gráfica (Tkinter) + CLI:** Funciona tanto em modo visual quanto via linha de comando para automação em lote.

---

## Pré-requisitos

O projeto utiliza exclusivamente a **biblioteca padrão do Python 3.9+** (sem pacotes externos via `pip`), exigindo apenas os utilitários do sistema:

- **Python 3.9 ou superior**
- **FFmpeg e FFprobe** disponíveis no `PATH`
- **Tkinter** (necessário apenas para a interface gráfica)

### Instalação das dependências no Linux

- **Ubuntu / Debian / Linux Mint:**
  ```bash
  sudo apt update && sudo apt install -y python3 python3-tk ffmpeg
  ```
- **Arch Linux / Manjaro:**
  ```bash
  sudo pacman -S --needed python tk ffmpeg
  ```

---

## Instalação

1. Clone o repositório e dê permissão de execução ao script:
   ```bash
   git clone [https://github.com/oudim/smartcut.git](https://github.com/oudim/smartcut.git)
   cd smartcut
   chmod +x smartcut.py
   ```

2. *(Opcional)* Compile um executável único para Linux com PyInstaller:
   ```bash
   python3 -m venv .venv-build
   .venv-build/bin/pip install --upgrade pip pyinstaller
   .venv-build/bin/pyinstaller --onefile --windowed --name smartcut --hidden-import tkinter smartcut.py
   mkdir -p ~/.local/bin && cp dist/smartcut ~/.local/bin/smartcut
   rm -rf build dist smartcut.spec .venv-build
   ```

---

## Como Usar

### 1. Interface Gráfica (GUI)

Execute sem argumentos para abrir a janela principal:

```bash
./smartcut.py
```

1. **Entrada Original & Saída do Arquivo:** Clique em **Escolher Entrada...** para carregar o vídeo/áudio bruto e ajuste o destino em **Salvar Como...** ou **Pasta...** (ou importe uma timeline pronta em **Importar FCPXML / EDL...**).
2. **Parâmetros de Corte Automático:** Ajuste os controles deslizantes ou aplique **Preset: Dinâmico** / **Preset: Narração**.
3. **Duração & Formatos Exportados:** Selecione **Apenas 30s (Prévia rápida)** ou **Vídeo todo**, marque os formatos desejados (`.mp4`, `.fcpxml`, `.edl`, `.jsonl`) e clique em **Executar**.

---

### 2. Linha de Comando (CLI)

Ao informar o arquivo de mídia ou timeline pelo terminal, o processamento ocorre sem abrir janela gráfica:

- **Gerar prévia de 30s com MP4, FCPXML e EDL:**
  ```bash
  ./smartcut.py entrada.mp4 --preview-30s --render-mp4
  ```

- **Processar o vídeo completo definindo pasta/arquivo de saída:**
  ```bash
  ./smartcut.py entrada.mp4 \
    -o ~/Videos/editados/video_final.mp4 \
    --threshold -34 \
    --min-silence 0.40 \
    --padding 0.12 \
    --merge-gap 0.15 \
    --render-mp4
  ```

- **Importar um `.edl` e exportar `.fcpxml` + MP4 cortado:**
  ```bash
  ./smartcut.py --import-timeline corte.edl -o ~/Videos/editados/ --render-mp4
  ```

### Opções da CLI

| Flag | Padrão | Descrição |
| :--- | :--- | :--- |
| `-o`, `--output CAMINHO` | Pasta da entrada | Define a pasta ou o nome base dos arquivos de saída |
| `--gui` | — | Força a abertura da interface gráfica |
| `--preview-30s` | `False` | Limita a análise e renderização aos primeiros 30 segundos |
| `--max-duration N` | `None` | Limita o processamento aos primeiros `N` segundos |
| `--import-timeline ARQ` | `None` | Importa cortes de um arquivo `.fcpxml` ou `.edl` |
| `--threshold DB` | `-32.0` | Limiar de volume abaixo do qual o trecho é considerado silêncio |
| `--min-silence SEG` | `0.45` | Duração mínima de silêncio para efetuar o corte |
| `--padding SEG` | `0.12` | Margem de segurança mantida antes e depois da fala |
| `--min-clip SEG` | `0.25` | Duração mínima de um segmento falado mantido |
| `--merge-gap SEG` | `0.15` | Funde segmentos separados por pausas menores que `SEG` |
| `--render-mp4` | `False` | Renderiza o arquivo `.mp4` (ou `.m4a`) já cortado via FFmpeg |
| `--no-fcpxml` / `--no-edl` | `False` | Desativa a exportação do respectivo formato de timeline |
| `--jsonl ARQ` | `None` | Exporta a lista de cortes em arquivo `.jsonl` |

---

## Arquivos Gerados

Quando `-o` / `--output` não é especificado, os arquivos são gravados na mesma pasta da mídia original com sufixos automáticos:

- **Prévia (30s):** `<nome>_preview30s.mp4`, `<nome>_preview30s.fcpxml`, `<nome>_preview30s.edl`
- **Vídeo Completo:** `<nome>_smartcut.mp4`, `<nome>_smartcut.fcpxml`, `<nome>_smartcut.edl`
- **Timeline Importada:** `<nome>_imported.mp4`, `<nome>_imported.fcpxml`, `<nome>_imported.edl`

---

## Licença

Distribuído sob a licença **MIT**.

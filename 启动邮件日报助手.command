#!/bin/zsh
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_NAME="${EMAIL_DIGEST_CONDA_ENV:-email-digest}"

# Load Conda when the script is launched by double-clicking in Finder.
if ! command -v conda >/dev/null 2>&1; then
  for CONDA_SH in "$HOME/miniconda3/etc/profile.d/conda.sh" "$HOME/anaconda3/etc/profile.d/conda.sh" "/opt/anaconda3/etc/profile.d/conda.sh"; do
    if [ -f "$CONDA_SH" ]; then
      source "$CONDA_SH"
      break
    fi
  done
fi

if ! command -v conda >/dev/null 2>&1; then
  echo "Conda was not found. Install Miniconda/Anaconda, then try again."
  read -r "?Press Enter to close..."
  exit 1
fi

conda activate "$ENV_NAME" || {
  echo "Conda environment '$ENV_NAME' was not found."
  read -r "?Press Enter to close..."
  exit 1
}

cd "$PROJECT_DIR"
open "http://127.0.0.1:8501"
python -m streamlit run app.py --server.address 127.0.0.1

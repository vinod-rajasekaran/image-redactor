#!/usr/bin/env bash
# One-time environment setup for the Presidio image-redactor evaluation harness.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required (https://brew.sh) — install it first." >&2
  exit 1
fi

if ! brew list tesseract >/dev/null 2>&1; then
  echo "Installing tesseract (OCR engine)..."
  brew install tesseract
else
  echo "tesseract already installed."
fi

if ! brew list zbar >/dev/null 2>&1; then
  echo "Installing zbar (barcode decoding for --visual-pii)..."
  brew install zbar
else
  echo "zbar already installed."
fi

if ! command -v python3.12 >/dev/null 2>&1; then
  echo "Installing python@3.12 (spaCy/Presidio need <3.13 wheels)..."
  brew install python@3.12
else
  echo "python3.12 already installed."
fi

if [ ! -d venv ]; then
  echo "Creating virtual environment..."
  python3.12 -m venv venv
fi

# shellcheck disable=SC1091
source venv/bin/activate

echo "Installing Python dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo "Downloading spaCy language model (en_core_web_lg, ~400MB)..."
python -m spacy download en_core_web_lg

mkdir -p input_images runs

# Optional WeChat QR models (--wechat-qr). Small, and only a supplement to
# the stock detector — see README "Why the defaults are what they are".
echo "Downloading WeChat QR models (optional, ~1MB)..."
mkdir -p models
WECHAT_BASE=https://raw.githubusercontent.com/WeChatCV/opencv_3rdparty/master
for f in detect.prototxt detect.caffemodel sr.prototxt sr.caffemodel; do
  [ -f "models/$f" ] || curl -sfL -o "models/$f" "$WECHAT_BASE/$f" \
    || echo "  (skipped $f — --wechat-qr will be unavailable)"
done

echo ""
echo "Setup complete. Next steps:"
echo "  source venv/bin/activate"
echo "  python generate_test_images.py     # creates sample PII documents in input_images/"
echo "  python evaluate_redactor.py        # redacts input_images/ -> output_images/"

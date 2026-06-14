#!/bin/bash
# Report Generator Framework - Run Script
# Usage: ./run.sh [config.json] [--type practice_report|diploma]

set -e

CONFIG="${1:-config_practice.json}"
TYPE_FLAG="--type practice_report"
if [ -n "$2" ]; then
    TYPE_FLAG="--type $2"
fi

echo "============================================"
echo "  Report Generator Framework"
echo "============================================"
echo ""
echo "Configuration: $CONFIG"
echo ""

# Check if config exists
if [ ! -f "$CONFIG" ]; then
    echo "ERROR: Config file not found: $CONFIG"
    echo "Usage: ./run.sh [config.json] [--type practice_report|diploma]"
    exit 1
fi

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is not installed"
    echo "Please install Python 3.8+ from https://www.python.org/downloads/"
    exit 1
fi

# Check if virtual environment exists, create if not
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source .venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install -q python-docx lxml

# Run setup to create directories
echo ""
echo "Setting up directories..."
python setup.py

# Run the generator
echo ""
echo "Generating report..."
echo "============================================"
python utils/generate_report.py --config "$CONFIG" $TYPE_FLAG

# Verify GOST compliance
echo ""
echo "Verifying GOST compliance..."
echo "============================================"
OUTPUT_FILE=$(python -c "import json; config=json.load(open('$CONFIG')); print(config['paths']['output_docx'])")
if [ -f "$OUTPUT_FILE" ]; then
    python utils/verify_gost.py "$OUTPUT_FILE"
else
    echo "WARNING: Output file not found: $OUTPUT_FILE"
fi

echo ""
echo "============================================"
echo "  Done!"
echo "============================================"
echo ""
echo "Output: $OUTPUT_FILE"
echo ""
echo "Next steps:"
echo "1. Review the generated diploma"
echo "2. Add screenshots to project/screenshots/"
echo "3. Add diagrams to project/diagrams/"
echo "4. Re-run to include screenshots"

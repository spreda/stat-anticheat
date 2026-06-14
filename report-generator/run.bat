@echo off
REM Report Generator Framework - Windows Run Script
REM Usage: run.bat [config.json] [--type practice_report|diploma]

set CONFIG=%~1
if "%CONFIG%"=="" set CONFIG=config_practice.json

set TYPE_FLAG=--type practice_report
if not "%~2"=="" set TYPE_FLAG=--type %~2

echo ============================================
echo   Report Generator Framework
echo ============================================
echo.
echo Configuration: %CONFIG%
echo.

REM Check if config exists
if not exist "%CONFIG%" (
    echo ERROR: Config file not found: %CONFIG%
    echo Usage: run.bat [config.json] [--type practice_report|diploma]
    pause
    exit /b 1
)

REM Check if virtual environment exists, create if not
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)

REM Activate virtual environment
echo Activating virtual environment...
call .venv\Scripts\activate.bat

REM Install dependencies
echo Installing dependencies...
pip install -q python-docx lxml

REM Run setup to create directories
echo.
echo Setting up directories...
python setup.py

REM Run the generator
echo.
echo Generating report...
echo ============================================
python utils\generate_report.py --config "%CONFIG%" %TYPE_FLAG%

REM Get output file path
for /f "tokens=*" %%i in ('python -c "import json; config=json.load(open('%CONFIG%')); print(config['paths']['output_docx'])"') do set OUTPUT_FILE=%%i

REM Verify GOST compliance
echo.
echo Verifying GOST compliance...
echo ============================================
if exist "%OUTPUT_FILE%" (
    python utils\verify_gost.py "%OUTPUT_FILE%"
) else (
    echo WARNING: Output file not found: %OUTPUT_FILE%
)

echo.
echo ============================================
echo   Done!
echo ============================================
echo.
echo Output: %OUTPUT_FILE%
echo.
echo Next steps:
echo 1. Review the generated diploma
echo 2. Add screenshots to project/screenshots/
echo 3. Add diagrams to project/diagrams/
echo 4. Re-run to include screenshots
echo.
pause

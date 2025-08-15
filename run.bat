@echo off
setlocal

REM Go to the folder where this .bat file is located
cd /d "%~dp0"

REM Check if the virtual environment exists, if not, create it
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)

REM Activate the virtual environment
call .venv\Scripts\activate

REM Upgrade pip
python -m pip install --upgrade pip

REM Install dependencies if requirements.txt exists
if exist "requirements.txt" (
    echo Installing dependencies...
    pip install -r requirements.txt
)

REM Run the Streamlit app
streamlit run app.py

endlocal
pause

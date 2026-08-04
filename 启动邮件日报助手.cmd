@echo off
setlocal
cd /d "%~dp0"

where conda >nul 2>&1
if errorlevel 1 (
    echo Conda was not found in PATH.
    echo Open Anaconda Prompt and run: conda init cmd.exe
    echo Then reopen Windows and try again.
    pause
    exit /b 1
)

call conda activate email-digest
if errorlevel 1 (
    echo The Conda environment "email-digest" was not found.
    echo Create it in Anaconda Prompt, then install requirements.txt.
    pause
    exit /b 1
)

echo Starting Email Digest Assistant. Keep this window open while using the app.
start "Email Digest Assistant" http://127.0.0.1:8501
python -m streamlit run app.py --server.address 127.0.0.1

echo Web service stopped.
pause

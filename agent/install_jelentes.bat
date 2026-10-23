@echo off
REM ======================================================================
REM  install_jelentes.bat
REM  --------------------------------------------------------------------
REM  Utemezett feladat SYSTEM fiokkal:
REM
REM    PepperHouse-Jelentes   percenkent, ejjel-nappal   jelentes.py
REM
REM  A jelentes.py percenkent eletjelet kuld a Pepper Adminnak (mentes
REM  allapota, adatbazis-proba), es ha az adminban ki van jelolve egy
REM  ujabb, alairt kiadas, telepiti (frissito.py).
REM
REM  A kezdes a telepites pillanata (nem ejfel), es 24 oran at ismetel
REM  naponta - igy egy percen belul elindul, es megszakitas nelkul megy.
REM  (A novohost-cloud install_task.bat-janak tapasztalata.)
REM
REM  HASZNALAT (jobb klikk -> Futtatas rendszergazdakent):
REM    install_jelentes.bat
REM    install_jelentes.bat "C:\...\pythonw.exe"
REM    install_jelentes.bat /remove
REM ======================================================================

setlocal

set "TASK=PepperHouse-Jelentes"
set "SCRIPTDIR=%~dp0"
set "SCRIPT=%SCRIPTDIR%jelentes.py"
set "PYEXE="

echo.
echo ============================================================
echo  Pepper House - percenkenti jelentes a Pepper Adminnak
echo ============================================================
echo.

if /I "%~1"=="/remove" goto :remove

net session >nul 2>&1
if errorlevel 1 goto :notadmin

if not "%~1"=="" set "PYEXE=%~1"
if not exist "%SCRIPT%" goto :noscript
if not exist "%SCRIPTDIR%pepper_agent.ini" goto :noini
if defined PYEXE goto :havepython

REM --- Python keresese (a valodi exe, nem shim) ----------------------
for /f "delims=" %%d in ('dir /b /ad "%LOCALAPPDATA%\Python\pythoncore-*" 2^>nul') do if not defined PYEXE call :trypy "%LOCALAPPDATA%\Python\%%d\pythonw.exe"
if defined PYEXE goto :havepython
for /f "delims=" %%i in ('where pythonw.exe 2^>nul') do if not defined PYEXE call :trypy "%%i"
if defined PYEXE goto :havepython
for /f "delims=" %%i in ('where python.exe 2^>nul') do if not defined PYEXE call :trypy "%%i"
if defined PYEXE goto :havepython
for /f "delims=" %%i in ('dir /b /s "%LOCALAPPDATA%\Programs\Python\pythonw.exe" 2^>nul') do if not defined PYEXE call :trypy "%%i"
if defined PYEXE goto :havepython
for /f "delims=" %%d in ('dir /b /ad "C:\Program Files\Python*" 2^>nul') do if not defined PYEXE call :trypy "C:\Program Files\%%d\pythonw.exe"
if defined PYEXE goto :havepython
for /f "delims=" %%d in ('dir /b /ad "C:\Program Files (x86)\Python*" 2^>nul') do if not defined PYEXE call :trypy "C:\Program Files (x86)\%%d\pythonw.exe"
if defined PYEXE goto :havepython
for /f "delims=" %%d in ('dir /b /ad "C:\Python*" 2^>nul') do if not defined PYEXE call :trypy "C:\%%d\pythonw.exe"
if defined PYEXE goto :havepython

echo HIBA: nem talalom a Pythont. Add meg kezzel:
echo    install_jelentes.bat "C:\...\pythonw.exe"
goto :end

:havepython
echo "%PYEXE%"| findstr /I /C:"\WindowsApps\" >nul
if not errorlevel 1 goto :storepython

REM A kezdes MOST - a %TIME% "H:MM:SS,ss" alaku, egyjegyu oranal szokozzel.
for /f "tokens=1-2 delims=:" %%a in ("%TIME%") do set "NHH=%%a" & set "NMM=%%b"
set "NHH=%NHH: =%"
set "NHH=0%NHH%"
set "NHH=%NHH:~-2%"
set "NMM=0%NMM%"
set "NMM=%NMM:~-2%"
set "STARTTIME=%NHH%:%NMM%"

echo Python      : %PYEXE%
echo Script      : %SCRIPT%
echo Feladat     : %TASK%, percenkent, %STARTTIME%-tol folyamatosan
echo.

schtasks /Query /TN "%TASK%" >nul 2>&1
if not errorlevel 1 schtasks /Delete /TN "%TASK%" /F >nul 2>&1

schtasks /Create /TN "%TASK%" /TR "\"%PYEXE%\" \"%SCRIPT%\"" /SC DAILY /ST %STARTTIME% /RI 1 /DU 24:00 /K /RU SYSTEM /RL HIGHEST /F >nul
if errorlevel 1 goto :createfailed
call :harden "%TASK%"

echo.
echo ============================================================
echo  KESZ.
echo ============================================================
echo.
echo  Proba (kiirja, mit kuld es mit valaszol a szerver):
echo     python "%SCRIPT%" --proba
echo.
echo  A "Next Run Time" ne legyen N/A:
echo     schtasks /Query /TN "%TASK%" /V /FO LIST
echo.
echo  Naplo (csak hibak es valtozasok):
echo     type "%SCRIPTDIR%jelentes_log.txt"
echo.
goto :end

:remove
schtasks /Delete /TN "%TASK%" /F
goto :end

:noscript
echo HIBA: nem talalom: %SCRIPT%
goto :end

:noini
echo HIBA: nincs pepper_agent.ini a script mellett.
goto :end

:storepython
echo HIBA: ez a Microsoft Store alias, SYSTEM-kent nem indul el:
echo    %PYEXE%
echo Telepits Pythont a python.org-rol, es add meg a valodi utvonalat.
goto :end

:notadmin
echo HIBA: rendszergazdakent kell futtatni
echo    (jobb klikk -^> "Futtatas rendszergazdakent").
goto :end

:createfailed
echo HIBA a feladat letrehozasakor. Rendszergazdakent futtattad?
goto :end

:end
echo.
pause
endlocal
exit /b 0

REM ======================================================================
REM  :trypy - a Store-aliast es a ...\Python\bin\ shim-et atugorja
REM ======================================================================
:trypy
if not exist "%~1" goto :eof
echo "%~1"| findstr /I /C:"\WindowsApps\" >nul
if not errorlevel 1 goto :eof
echo "%~1"| findstr /I /C:"\Python\bin\" >nul
if not errorlevel 1 goto :eof
set "PYEXE=%~1"
goto :eof

REM ======================================================================
REM  :harden - StartWhenAvailable be, akkumulator-tiltasok ki.
REM  Parancssorbol nem allithato, csak a feladat XML-jen at. Ha elakad,
REM  az eredeti feladat marad - az utemezes attol meg jo.
REM ======================================================================
:harden
set "TMPXML=%TEMP%\ph_task_%RANDOM%.xml"
schtasks /Query /TN %1 /XML > "%TMPXML%" 2>nul
if errorlevel 1 goto :harden_skip
powershell -NoProfile -Command "$p='%TMPXML%'; $x=[IO.File]::ReadAllText($p); $x=$x -replace '<StartWhenAvailable>false</StartWhenAvailable>','<StartWhenAvailable>true</StartWhenAvailable>' -replace '<DisallowStartIfOnBatteries>true</DisallowStartIfOnBatteries>','<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>' -replace '<StopIfGoingOnBatteries>true</StopIfGoingOnBatteries>','<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>'; [IO.File]::WriteAllText($p,$x,[Text.Encoding]::Unicode)" >nul 2>&1
if errorlevel 1 goto :harden_skip
schtasks /Create /TN %1 /XML "%TMPXML%" /F >nul 2>&1
if errorlevel 1 goto :harden_skip
del "%TMPXML%" >nul 2>&1
echo   %~1: kimaradt inditas potlasa bekapcsolva.
goto :eof
:harden_skip
del "%TMPXML%" >nul 2>&1
echo   %~1: (a potlast nem sikerult bekapcsolni - nem kritikus)
goto :eof

@echo off
REM ======================================================================
REM  install_backup.bat
REM  --------------------------------------------------------------------
REM  Ket utemezett feladat a Windows Feladatutemezoben, SYSTEM fiokkal:
REM
REM    PepperHouse-Mentes             naponta, alapbol 04:15   backup.py
REM    PepperHouse-Mentes-Napkozbeni  naponta 06:00-16:00, ketorankent
REM                                   backup.py --napkozbeni
REM
REM  A napkozbeni mentes kimarad, ha az elozo mentes ota nem volt uj nyugta,
REM  igy zart napon nem keletkezik felesleges mentes. Az idoablak lent, a
REM  NAPSTART / NAPDUR / NAPRI valtozokban allithato.
REM
REM  A proba-visszaallitas SZANDEKOSAN nincs itt: az nem az eles POS gepre
REM  valo, hanem egy kulon teszt gepre (lasd README, "Mentes ellenorzese").
REM
REM  HASZNALAT (jobb klikk -> Futtatas rendszergazdakent):
REM    install_backup.bat
REM    install_backup.bat 03:40
REM    install_backup.bat 03:40 "C:\...\pythonw.exe"
REM    install_backup.bat /remove
REM
REM  Az idopont: zaras UTAN, a hajnali potlo sync (05:02) ELOTT. Hajnalig
REM  nyito helyen (RSR) a zaras utan valassz. A gbak futas kozben ment,
REM  a kassza nem all meg, de ejszaka kevesebb a terheles.
REM
REM  A novohost-cloud install_task.bat-janak megegetett tanulsagai itt is
REM  ervenyesek, ezert:
REM   - nincs tobbsoros zarojeles blokk: a "(x86)" utvonal zaro zarojele
REM     idejekoran lezarna (goto cimkek helyette)
REM   - /SC DAILY es /SC WEEKLY, NEM /SC MINUTE (az egyszeri trigger)
REM   - a Store-alias es a ...\Python\bin\ shim nem jo SYSTEM-kent
REM   - StartWhenAvailable bekapcsolva: ha a gep ki volt kapcsolva, potol
REM ======================================================================

setlocal

set "TASK=PepperHouse-Mentes"
set "TASKP=PepperHouse-Mentes-Proba"
set "TASKN=PepperHouse-Mentes-Napkozbeni"
REM 06:00-tol 10 ora 5 percen at 120 percenkent: 06,08,10,12,14,16. Az 5 perc
REM rahagyas azert kell, hogy a 16:00-s futas meg az ablakba essen.
set "NAPSTART=06:00"
set "NAPDUR=10:05"
set "NAPRI=120"
set "SCRIPTDIR=%~dp0"
set "SCRIPT=%SCRIPTDIR%backup.py"
set "STARTTIME=04:15"
set "PYEXE="

echo.
echo ============================================================
echo  Pepper House - NovoHost mentes utemezese
echo ============================================================
echo.

if /I "%~1"=="/remove" goto :remove

net session >nul 2>&1
if errorlevel 1 goto :notadmin

REM --- Argumentumok: [HH:MM] [python utvonal] ------------------------
echo %~1| findstr /R "^[0-2][0-9]:[0-5][0-9]$" >nul
if errorlevel 1 goto :arg_py1
set "STARTTIME=%~1"
if not "%~2"=="" set "PYEXE=%~2"
goto :argsdone
:arg_py1
if not "%~1"=="" set "PYEXE=%~1"
:argsdone

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
echo    install_backup.bat 04:15 "C:\...\pythonw.exe"
goto :end

:havepython
echo "%PYEXE%"| findstr /I /C:"\WindowsApps\" >nul
if not errorlevel 1 goto :storepython

echo Python      : %PYEXE%
echo Script      : %SCRIPT%
echo Napi mentes : %STARTTIME%
echo Napkozben   : %NAPSTART%-tol %NAPRI% percenkent, %NAPDUR% oran at
echo.

schtasks /Query /TN "%TASK%" >nul 2>&1
if not errorlevel 1 schtasks /Delete /TN "%TASK%" /F >nul 2>&1
REM Egy korabbi verzio a POS gepen proba-visszaallitast is utemezett -
REM ha megvan, toroljuk.
schtasks /Query /TN "%TASKP%" >nul 2>&1
if not errorlevel 1 schtasks /Delete /TN "%TASKP%" /F >nul 2>&1
schtasks /Query /TN "%TASKN%" >nul 2>&1
if not errorlevel 1 schtasks /Delete /TN "%TASKN%" /F >nul 2>&1

schtasks /Create /TN "%TASK%" /TR "\"%PYEXE%\" \"%SCRIPT%\"" /SC DAILY /ST %STARTTIME% /RU SYSTEM /RL HIGHEST /F >nul
if errorlevel 1 goto :createfailed
call :harden "%TASK%"

schtasks /Create /TN "%TASKN%" /TR "\"%PYEXE%\" \"%SCRIPT%\" --napkozbeni" /SC DAILY /ST %NAPSTART% /RI %NAPRI% /DU %NAPDUR% /K /RU SYSTEM /RL HIGHEST /F >nul
if errorlevel 1 goto :createfailed
call :harden "%TASKN%"

echo.
echo ============================================================
echo  KESZ.
echo ============================================================
echo.
echo  Most futtass le egy mentest kezzel, es nezd meg az eredmenyt:
echo     schtasks /Run /TN "%TASK%"
echo     (par perc mulva)  type "%SCRIPTDIR%mentes_log.txt"
echo.
echo  A napkozbeni mentes kezzel (kimarad, ha nincs uj adat):
echo     schtasks /Run /TN "%TASKN%"
echo.
echo  A "Next Run Time" ne legyen N/A (mindket feladatnal):
echo     schtasks /Query /TN "%TASK%" /V /FO LIST
echo     schtasks /Query /TN "%TASKN%" /V /FO LIST
echo.
goto :end

:remove
schtasks /Delete /TN "%TASK%" /F
schtasks /Delete /TN "%TASKN%" /F
schtasks /Delete /TN "%TASKP%" /F >nul 2>&1
goto :end

:noscript
echo HIBA: nem talalom: %SCRIPT%
goto :end

:noini
echo HIBA: nincs pepper_agent.ini a script mellett.
echo Masold a pepper_agent.ini.example-t pepper_agent.ini neven, es toltsd ki.
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

@echo off
rem Builds HaloLauncher.exe, with its icon, next to this file: one file to hand
rem out (a download link, a shared drive). Uses the C# compiler that is part of
rem Windows (.NET Framework 4). See README.md.
rem
rem   build-exe.cmd              the launcher, HaloLauncher.exe
rem   build-exe.cmd pre-update   the pre-update launcher, HaloLauncherPreUpdate.exe,
rem                              which builds bnunu/halo-ce-universal
setlocal
set "HERE=%~dp0"
set "CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC%" set "CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe"
set "NAME=HaloLauncher"
set "EDITION="
if /i "%~1"=="pre-update" (
	set "NAME=HaloLauncherPreUpdate"
	set "EDITION=/define:PRE_UPDATE"
) else if not "%~1"=="" (
	echo Usage: build-exe.cmd [pre-update]
	exit /b 1
)
set "WORK=%TEMP%\%NAME%-build"
set "FLAGS=/nologo /target:winexe /platform:anycpu /optimize+ %EDITION% /r:System.IO.Compression.dll /r:System.IO.Compression.FileSystem.dll"
if exist "%WORK%" rmdir /s /q "%WORK%"
mkdir "%WORK%"
rem the icon is drawn by the launcher itself: build it once to draw it
"%CSC%" %FLAGS% /out:"%WORK%\%NAME%.exe" "%HERE%HaloLauncher.cs"
if errorlevel 1 goto failed
"%WORK%\%NAME%.exe" --write-icon "%WORK%\%NAME%.ico"
if errorlevel 1 goto failed
"%CSC%" %FLAGS% /win32icon:"%WORK%\%NAME%.ico" /out:"%HERE%%NAME%.exe" "%HERE%HaloLauncher.cs"
if errorlevel 1 goto failed
rmdir /s /q "%WORK%"
echo Built %HERE%%NAME%.exe
exit /b 0
:failed
echo Building %NAME%.exe failed.
exit /b 1

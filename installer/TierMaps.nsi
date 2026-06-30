; TierMaps NSIS installer (Modern UI 2)
; Build with: installer\build_installer.bat

!include "MUI2.nsh"
!include "x64.nsh"
!include "LogicLib.nsh"

;-----------------------------------------------------------------------------
; Application metadata
;-----------------------------------------------------------------------------
!define APP_NAME        "TierMaps"
!define APP_PUBLISHER   "R. Bolisay"
!define APP_VERSION     "1.0"
!define APP_ICON        "TierMaps.ico"
!define APP_DESC        "Navigation PostMaps Viewer"
!define UNINST_KEY      "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"

!define REPO_ROOT "${__FILEDIR__}\.."

Name "${APP_NAME} ${APP_VERSION}"
OutFile "${REPO_ROOT}\dist\${APP_NAME}-${APP_VERSION}-Setup.exe"
InstallDir "$PROGRAMFILES64\${APP_NAME}"
InstallDirRegKey HKLM "${UNINST_KEY}" "InstallLocation"
RequestExecutionLevel admin
Unicode True
ManifestDPIAware true

SetCompressor /SOLID lzma
SetCompressorDictSize 64

VIProductVersion 1.0.0.0
VIAddVersionKey "ProductName" "${APP_NAME}"
VIAddVersionKey "CompanyName" "${APP_PUBLISHER}"
VIAddVersionKey "LegalCopyright" "Copyright (c) ${APP_PUBLISHER}"
VIAddVersionKey "FileDescription" "${APP_DESC} Setup"
VIAddVersionKey "FileVersion" "${APP_VERSION}.0"
VIAddVersionKey "ProductVersion" "${APP_VERSION}"

;-----------------------------------------------------------------------------
; Modern UI
;-----------------------------------------------------------------------------
!define MUI_ABORTWARNING
!define MUI_ICON "${__FILEDIR__}\${APP_ICON}"
!define MUI_UNICON "${__FILEDIR__}\${APP_ICON}"
!define MUI_WELCOMEPAGE_TITLE "${APP_NAME} ${APP_VERSION} Setup"
!define MUI_WELCOMEPAGE_TEXT "This wizard will install ${APP_NAME} ${APP_VERSION}, ${APP_DESC}.$\r$\n$\r$\nDeveloped by ${APP_PUBLISHER}.$\r$\n$\r$\nAll required libraries are bundled with this installer — no separate Python installation is needed.$\r$\n$\r$\nClick Next to continue."
!define MUI_LICENSEPAGE_CHECKBOX
!define MUI_LICENSEPAGE_CHECKBOX_TEXT "I &accept the terms of the License Agreement"
!define MUI_DIRECTORYPAGE_TEXT_TOP "Setup will install ${APP_NAME} in the following folder. To install in a different folder, click Browse and select another location."
!define MUI_FINISHPAGE_TITLE "Installation Complete"
!define MUI_FINISHPAGE_TEXT "${APP_NAME} ${APP_VERSION} has been installed on your computer.$\r$\n$\r$\nClick Finish to close this wizard."
!define MUI_FINISHPAGE_RUN "$INSTDIR\TierMaps.bat"
!define MUI_FINISHPAGE_RUN_TEXT "Launch ${APP_NAME}"
!define MUI_FINISHPAGE_SHOWREADME
!define MUI_FINISHPAGE_SHOWREADME_TEXT "Create a &desktop shortcut"
!define MUI_FINISHPAGE_SHOWREADME_FUNCTION CreateDesktopShortcut
!define MUI_UNWELCOMEPAGE_TITLE "${APP_NAME} ${APP_VERSION} Uninstall"
!define MUI_UNWELCOMEPAGE_TEXT "This will remove ${APP_NAME} ${APP_VERSION} from your computer.$\r$\n$\r$\nClick Next to continue, or Cancel to exit."

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "license.txt"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_WELCOME
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

!insertmacro MUI_LANGUAGE "English"

;-----------------------------------------------------------------------------
; Install application files
; Portable embedded Python runtime + all pip dependencies live under python\.
; TierMaps.ico is generated from TierMaps.png at build time for shortcuts.
;-----------------------------------------------------------------------------
Section "TierMaps Application" SecMain
  SectionIn RO

  SetOutPath "$INSTDIR"
  File "staging\TierMaps.bat"
  File "staging\TierMaps.ico"
  File "staging\TierMaps.png"
  File "staging\TierMaps_No_bg.png"
  File "staging\TierMaps_Logo.png"
  File "staging\TierMaps_Logo_grey.png"
  File "staging\run.py"
  File "staging\preflight.py"
  File "staging\requirements.txt"
  File "staging\license.txt"

  SetOutPath "$INSTDIR\data"
  File "staging\data\settings.json"

  SetOutPath "$INSTDIR\python"
  File /r /x "__pycache__" /x "*.pyc" /x "*.pyo" "staging\python\*"

  SetOutPath "$INSTDIR\xpostmaps"
  File /r /x "__pycache__" /x "*.pyc" /x "*.pyo" "staging\xpostmaps\*"

  ; Verify bundled runtime landed where TierMaps.bat expects it.
  IfFileExists "$INSTDIR\python\pythonw.exe" +3 0
    MessageBox MB_ICONSTOP "Install failed: the bundled Python runtime (pythonw.exe) was not placed in $INSTDIR\python.$\r$\n$\r$\nPlease contact support."
    Abort

  IfFileExists "$INSTDIR\TierMaps_No_bg.png" +3 0
    MessageBox MB_ICONSTOP "Install failed: application logo was not installed.$\r$\n$\r$\nPlease contact support."
    Abort

  IfFileExists "$INSTDIR\xpostmaps\assets\world_coastlines.json" +3 0
    MessageBox MB_ICONSTOP "Install failed: bundled map assets were not installed.$\r$\n$\r$\nPlease contact support."
    Abort

  IfFileExists "$INSTDIR\python\Lib\site-packages\PySide6\plugins\platforms\qwindows.dll" +3 0
    MessageBox MB_ICONSTOP "Install failed: bundled Qt libraries were not installed.$\r$\n$\r$\nPlease contact support."
    Abort

  WriteUninstaller "$INSTDIR\Uninstall.exe"

  SetShellVarContext all
  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" \
    "$INSTDIR\TierMaps.bat" "" \
    "$INSTDIR\${APP_ICON}" 0 SW_SHOWNORMAL "" "${APP_DESC}"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\Uninstall ${APP_NAME}.lnk" \
    "$INSTDIR\Uninstall.exe" "" "$INSTDIR\Uninstall.exe" 0

  WriteRegStr HKLM "${UNINST_KEY}" "DisplayName" "${APP_NAME} ${APP_VERSION}"
  WriteRegStr HKLM "${UNINST_KEY}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKLM "${UNINST_KEY}" "Publisher" "${APP_PUBLISHER}"
  WriteRegStr HKLM "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\${APP_ICON}"
  WriteRegStr HKLM "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "${UNINST_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKLM "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegStr HKLM "${UNINST_KEY}" "HelpLink" "https://github.com/rbolisay/xPostMaps"
  WriteRegStr HKLM "${UNINST_KEY}" "Comments" "${APP_DESC}"
  WriteRegDWORD HKLM "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINST_KEY}" "NoRepair" 1
  WriteRegDWORD HKLM "${UNINST_KEY}" "EstimatedSize" 650000

SectionEnd

Function CreateDesktopShortcut
  SetShellVarContext all
  CreateShortcut "$DESKTOP\${APP_NAME}.lnk" \
    "$INSTDIR\TierMaps.bat" "" \
    "$INSTDIR\${APP_ICON}" 0 SW_SHOWNORMAL "" "${APP_DESC}"
FunctionEnd

Section "Uninstall"
  SetShellVarContext all
  Delete "$DESKTOP\${APP_NAME}.lnk"
  RMDir /r "$SMPROGRAMS\${APP_NAME}"
  RMDir /r "$INSTDIR"
  DeleteRegKey HKLM "${UNINST_KEY}"
SectionEnd

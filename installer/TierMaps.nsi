; TierMaps NSIS installer (Modern UI 2)
; Build with: installer\build_installer.bat

!include "MUI2.nsh"
!include "x64.nsh"

;-----------------------------------------------------------------------------
; Application metadata
;-----------------------------------------------------------------------------
!define APP_NAME      "TierMaps"
!define APP_PUBLISHER   "R. Bolisay"
!define APP_VERSION     "0.1.2"
!define APP_ICON        "TierMaps.ico"
!define APP_DESC        "Navigation PostMaps Viewer"
!define UNINST_KEY      "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"

!define REPO_ROOT "${__FILEDIR__}\.."

Name "${APP_NAME}"
OutFile "${REPO_ROOT}\dist\${APP_NAME}-${APP_VERSION}-Setup.exe"
InstallDir "$PROGRAMFILES64\${APP_NAME}"
InstallDirRegKey HKLM "${UNINST_KEY}" "InstallLocation"
RequestExecutionLevel admin
Unicode True
ManifestDPIAware true

SetCompressor /SOLID lzma
SetCompressorDictSize 64

VIProductVersion 0.1.2.0
VIAddVersionKey "ProductName" "${APP_NAME}"
VIAddVersionKey "CompanyName" "${APP_PUBLISHER}"
VIAddVersionKey "LegalCopyright" "Copyright (c) ${APP_PUBLISHER}"
VIAddVersionKey "FileDescription" "${APP_DESC} Setup"
VIAddVersionKey "FileVersion" "${APP_VERSION}"
VIAddVersionKey "ProductVersion" "${APP_VERSION}"

;-----------------------------------------------------------------------------
; Modern UI
;-----------------------------------------------------------------------------
!define MUI_ABORTWARNING
!define MUI_ICON "${__FILEDIR__}\${APP_ICON}"
!define MUI_UNICON "${__FILEDIR__}\${APP_ICON}"
!define MUI_WELCOMEPAGE_TITLE "${APP_NAME} ${APP_VERSION} Setup"
!define MUI_WELCOMEPAGE_TEXT "This wizard will install ${APP_NAME}, ${APP_DESC}.$\r$\n$\r$\nDeveloped by ${APP_PUBLISHER}.$\r$\n$\r$\nClick Next to continue."
!define MUI_FINISHPAGE_TITLE "Installation Complete"
!define MUI_FINISHPAGE_TEXT "${APP_NAME} has been installed on your computer.$\r$\n$\r$\nClick Finish to close this wizard."
!define MUI_FINISHPAGE_RUN "$INSTDIR\TierMaps.bat"
!define MUI_FINISHPAGE_RUN_TEXT "Launch ${APP_NAME}"
!define MUI_FINISHPAGE_SHOWREADME
!define MUI_FINISHPAGE_SHOWREADME_TEXT "Create a &desktop shortcut"
!define MUI_FINISHPAGE_SHOWREADME_FUNCTION CreateDesktopShortcut

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "license.txt"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

;-----------------------------------------------------------------------------
; Install application files
; File /r on a directory name nests that folder — use dir\* to flatten.
;-----------------------------------------------------------------------------
Section "TierMaps" SecMain
  SectionIn RO

  SetOutPath "$INSTDIR"
  File "staging\TierMaps.bat"
  File "staging\TierMaps.ico"
  File "staging\TierMaps.png"
  File "staging\run.py"
  File "staging\requirements.txt"

  SetOutPath "$INSTDIR\data"
  File "staging\data\.gitkeep"

  SetOutPath "$INSTDIR\python"
  File /r /x "__pycache__" /x "*.pyc" /x "*.pyo" "staging\python\*"

  SetOutPath "$INSTDIR\xpostmaps"
  File /r /x "__pycache__" /x "*.pyc" /x "*.pyo" "staging\xpostmaps\*"

  ; Verify runtime landed where TierMaps.bat expects it.
  IfFileExists "$INSTDIR\python\pythonw.exe" +3 0
    MessageBox MB_ICONSTOP "Install failed: pythonw.exe was not placed in $INSTDIR\python. Please contact support."
    Abort

  WriteUninstaller "$INSTDIR\Uninstall.exe"

  SetShellVarContext all
  CreateDirectory "$SMPROGRAMS\${APP_NAME}"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" \
    "$INSTDIR\TierMaps.bat" "" \
    "$INSTDIR\${APP_ICON}" 0 SW_SHOWNORMAL "" "${APP_DESC}"
  CreateShortcut "$SMPROGRAMS\${APP_NAME}\Uninstall ${APP_NAME}.lnk" \
    "$INSTDIR\Uninstall.exe" "" "$INSTDIR\Uninstall.exe" 0

  WriteRegStr HKLM "${UNINST_KEY}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKLM "${UNINST_KEY}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKLM "${UNINST_KEY}" "Publisher" "${APP_PUBLISHER}"
  WriteRegStr HKLM "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\${APP_ICON}"
  WriteRegStr HKLM "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "${UNINST_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKLM "${UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegStr HKLM "${UNINST_KEY}" "HelpLink" "https://github.com/rbolisay/xPostMaps"
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

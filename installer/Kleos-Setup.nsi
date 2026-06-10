; Kleos Setup Script
; Built with NSIS

!include "MUI2.nsh"

; -------------------------------------------------------------------------
; Configuration
; -------------------------------------------------------------------------
!define PRODUCT_NAME        "Kleos"
!define PRODUCT_VERSION     "1.0.0"
!define PRODUCT_PUBLISHER   "ThoriaDevelopment"
!define PRODUCT_WEB_SITE    "https://github.com/ThoriaDevelopment/Kleos"
!define PRODUCT_DIR_REGKEY  "Software\Microsoft\Windows\CurrentVersion\App Paths\Kleos.exe"
!define PRODUCT_UNINST_KEY  "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}"
!define PRODUCT_UNINST_ROOT_KEY "HKLM"

Name    "${PRODUCT_NAME} ${PRODUCT_VERSION}"
OutFile "..\Kleos-Setup.exe"
InstallDir "$PROGRAMFILES64\${PRODUCT_NAME}"
InstallDirRegKey HKLM "${PRODUCT_DIR_REGKEY}" ""
RequestExecutionLevel admin

; -------------------------------------------------------------------------
; Interface
; -------------------------------------------------------------------------
!define MUI_ABORTWARNING
!define MUI_ICON "${NSISDIR}\Contrib\Graphics\Icons\modern-install.ico"
!define MUI_UNICON "${NSISDIR}\Contrib\Graphics\Icons\modern-uninstall.ico"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "..\LICENSE"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_WELCOME
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

!insertmacro MUI_LANGUAGE "English"

; -------------------------------------------------------------------------
; Installer Sections
; -------------------------------------------------------------------------
Section "MainSection" SEC01
  SetOutPath "$INSTDIR"
  SetOverwrite ifnewer

  ; Copy the application bundle built by PyInstaller
  File /r "..\dist\Kleos\*"

  ; Write uninstaller
  WriteUninstaller "$INSTDIR\uninst.exe"

  ; Register application path
  WriteRegStr HKLM "${PRODUCT_DIR_REGKEY}" "" "$INSTDIR\Kleos.exe"

  ; Start Menu shortcut
  CreateDirectory "$SMPROGRAMS\${PRODUCT_NAME}"
  CreateShortcut "$SMPROGRAMS\${PRODUCT_NAME}\${PRODUCT_NAME}.lnk" "$INSTDIR\Kleos.exe"
  CreateShortcut "$SMPROGRAMS\${PRODUCT_NAME}\Uninstall.lnk" "$INSTDIR\uninst.exe"

  ; Desktop shortcut
  CreateShortcut "$DESKTOP\${PRODUCT_NAME}.lnk" "$INSTDIR\Kleos.exe"

  ; Add/Remove Programs entry
  WriteRegStr   HKLM "${PRODUCT_UNINST_KEY}" "DisplayName"     "${PRODUCT_NAME}"
  WriteRegStr   HKLM "${PRODUCT_UNINST_KEY}" "UninstallString" "$INSTDIR\uninst.exe"
  WriteRegStr   HKLM "${PRODUCT_UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr   HKLM "${PRODUCT_UNINST_KEY}" "DisplayIcon"     "$INSTDIR\Kleos.exe"
  WriteRegStr   HKLM "${PRODUCT_UNINST_KEY}" "Publisher"       "${PRODUCT_PUBLISHER}"
  WriteRegStr   HKLM "${PRODUCT_UNINST_KEY}" "URLInfoAbout"    "${PRODUCT_WEB_SITE}"
  WriteRegStr   HKLM "${PRODUCT_UNINST_KEY}" "DisplayVersion"  "${PRODUCT_VERSION}"
  WriteRegDWORD HKLM "${PRODUCT_UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKLM "${PRODUCT_UNINST_KEY}" "NoRepair" 1
SectionEnd

; -------------------------------------------------------------------------
; Uninstaller Section
; -------------------------------------------------------------------------
Section Uninstall
  ; Remove installed files
  RMDir /r "$INSTDIR\_internal"
  Delete "$INSTDIR\Kleos.exe"
  Delete "$INSTDIR\uninst.exe"
  RMDir "$INSTDIR"

  ; Remove shortcuts
  Delete "$SMPROGRAMS\${PRODUCT_NAME}\${PRODUCT_NAME}.lnk"
  Delete "$SMPROGRAMS\${PRODUCT_NAME}\Uninstall.lnk"
  RMDir "$SMPROGRAMS\${PRODUCT_NAME}"
  Delete "$DESKTOP\${PRODUCT_NAME}.lnk"

  ; Remove registry entries
  DeleteRegKey HKLM "${PRODUCT_UNINST_KEY}"
  DeleteRegKey HKLM "${PRODUCT_DIR_REGKEY}"
SectionEnd
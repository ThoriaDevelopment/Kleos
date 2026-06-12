; Kleos Setup Script
; Built with NSIS

!include "MUI2.nsh"

; -------------------------------------------------------------------------
; Configuration
; -------------------------------------------------------------------------
!define PRODUCT_NAME        "Kleos"
!define PRODUCT_VERSION     "1.1.0"
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

; Check for running Kleos instance before installing
Section "" SEC_PRECHECK
  ; Try to find a running Kleos process and warn the user
  FindWindow $0 "Kleos — Media Dashboard" ""
  StrCmp $0 0 no_kleos_running
    MessageBox MB_OK|MB_ICONEXCLAMATION \
      "Kleos appears to be running.$\n$\nPlease close Kleos before installing the update." \
      /SD IDOK
  no_kleos_running:
SectionEnd

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
  ; Safety guard: only delete files if this directory actually contains Kleos.
  ; This prevents accidental deletion if the install directory was changed
  ; or if the registry points somewhere unexpected.
  IfFileExists "$INSTDIR\Kleos.exe" kleos_found
    DetailPrint "Kleos not found in $INSTDIR — skipping file removal."
    Goto kleos_files_done
  kleos_found:

  ; Remove installed files
  ; Only delete _internal if it actually looks like a PyInstaller bundle
  ; (base_library.zip is always present in PyInstaller one-dir builds).
  ; This prevents wiping an unrelated _internal folder the user may have.
  IfFileExists "$INSTDIR\_internal\base_library.zip" safe_internal
    DetailPrint "_internal does not look like a Kleos bundle — skipping."
    Goto skip_internal
  safe_internal:
    RMDir /r "$INSTDIR\_internal"
  skip_internal:

  Delete "$INSTDIR\Kleos.exe"
  Delete "$INSTDIR\uninst.exe"
  RMDir "$INSTDIR"

  kleos_files_done:

  ; Remove shortcuts
  Delete "$SMPROGRAMS\${PRODUCT_NAME}\${PRODUCT_NAME}.lnk"
  Delete "$SMPROGRAMS\${PRODUCT_NAME}\Uninstall.lnk"
  RMDir "$SMPROGRAMS\${PRODUCT_NAME}"
  Delete "$DESKTOP\${PRODUCT_NAME}.lnk"

  ; Ask user whether to keep their data
  MessageBox MB_YESNO "Do you want to keep your Kleos data (profiles, settings, thumbnails)?$\n$\nChoose Yes to keep your data for future reinstallations.$\nChoose No to delete all Kleos data permanently." IDYES keep_data

  ; Remove user data (databases, cache, thumbnails, backups) — only if user chose No
  IfFileExists "$APPDATA\.kleos" delete_data
    DetailPrint "No Kleos data directory found — skipping."
    Goto keep_data
  delete_data:
    RMDir /r "$APPDATA\.kleos"

  keep_data:

  ; Remove registry entries
  DeleteRegKey HKLM "${PRODUCT_UNINST_KEY}"
  DeleteRegKey HKLM "${PRODUCT_DIR_REGKEY}"
SectionEnd
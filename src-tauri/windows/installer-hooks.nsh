; The former currentUser-only installer did not write the CurrentUser marker
; used by Tauri's `both` mode. If that legacy HKCU registration still exists
; after mode selection/reinstall handling, remove only its installed binaries
; and registration. /UPDATE keeps all per-user application data.
!macro NSIS_HOOK_PREINSTALL
  ReadRegDWORD $R0 HKCU "${UNINSTKEY}" "CurrentUser"
  ${If} ${Errors}
    ClearErrors
    ReadRegStr $R1 HKCU "${UNINSTKEY}" "UninstallString"
    ReadRegStr $R2 HKCU "${MANUPRODUCTKEY}" ""
    ${If} $R1 != ""
    ${AndIf} $R2 != ""
      DetailPrint "Removing the legacy current-user installation"
      ExecWait '$R1 /S /UPDATE _?=$R2' $R3
      ${If} $R3 != 0
        MessageBox MB_ICONSTOP|MB_OK "以前の現在ユーザー用インストールを削除できませんでした。インストールを中止します。"
        Abort
      ${EndIf}
    ${EndIf}
  ${EndIf}

  ; The bundled runtime folders belong to the installer. Replace them as a whole: NSIS only
  ; overwrites, and its uninstaller removes only the files of its own build, so a file that a newer
  ; build dropped stays behind. In v26.11.24 a leftover websockets/speedups.pyd stopped the API.
  !insertmacro CheckIfAppIsRunning "${MAINBINARYNAME}.exe" "${PRODUCTNAME}"
  ${If} $INSTDIR != ""
    RMDir /r "$INSTDIR\scena-api-runtime"
    RMDir /r "$INSTDIR\environment-manager"
    ${If} ${FileExists} "$INSTDIR\scena-api-runtime\*.*"
    ${OrIf} ${FileExists} "$INSTDIR\environment-manager\*.*"
      MessageBox MB_ICONSTOP|MB_OK "以前のバージョンのファイルを削除できませんでした。irodori SCENA を終了してから、もう一度インストールしてください。"
      Abort
    ${EndIf}
  ${EndIf}
!macroend

; The marker survives an in-place update because the install directory is
; retained. A real uninstall removes it with that directory, so the next
; install receives a different identity. /UPDATE retains the marker.
!macro NSIS_HOOK_POSTINSTALL
  ${IfNot} ${FileExists} "$INSTDIR\.scena-install-id"
    ${GetTime} "" "L" $R0 $R1 $R2 $R3 $R4 $R5 $R6
    System::Call 'kernel32::GetTickCount()i.r7'
    FileOpen $R8 "$INSTDIR\.scena-install-id" w
    FileWrite $R8 "$R0$R1$R2-$R4$R5$R6-$R7$\r$\n"
    FileClose $R8
  ${EndIf}
!macroend

; The packaged API owns credential formats, so it removes credentials before
; either release AppData root. Failures stay visible and are retryable; Ignore
; is the user's explicit choice to leave the remaining data behind.
!macro NSIS_HOOK_PREUNINSTALL
  ${If} $UpdateMode <> 1
  ${AndIf} $DeleteManagedData = 1
    cleanup_retry:
    ExecWait '"$INSTDIR\scena-api-runtime\scena-api.exe" --cleanup-user-data --error-log "$TEMP\irodori-scena-uninstall-error.log"' $R0
    ${If} $R0 <> 0
      MessageBox MB_ICONEXCLAMATION|MB_ABORTRETRYIGNORE "SCENA 管理データの一部を削除できませんでした。詳細は $TEMP\irodori-scena-uninstall-error.log に記録しました。［再試行］で削除を再試行します。［無視］で残ったデータを保持してアンインストールを続けます。［中止］でアンインストールを中止します。" IDRETRY cleanup_retry IDIGNORE cleanup_keep
      Abort
      cleanup_keep:
      StrCpy $DeleteManagedData 0
    ${EndIf}
  ${EndIf}
!macroend

; Remove installer-owned identity and location metadata after every real
; uninstall. The running uninstaller itself may require deferred deletion.
!macro NSIS_HOOK_POSTUNINSTALL
  ${If} $UpdateMode <> 1
    Delete "$INSTDIR\.scena-install-id"
    DeleteRegKey HKCU "${MANUPRODUCTKEY}"
    DeleteRegKey HKLM "${MANUPRODUCTKEY}"
    DeleteRegKey /ifempty HKCU "${MANUKEY}"
    DeleteRegKey /ifempty HKLM "${MANUKEY}"
    RMDir /r "$INSTDIR\scena-api-runtime"
    RMDir /r "$INSTDIR\environment-manager"
    Delete /REBOOTOK "$INSTDIR\uninstall.exe"
    RMDir /REBOOTOK "$INSTDIR"
  ${EndIf}
!macroend

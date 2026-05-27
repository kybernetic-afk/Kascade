; Inno Setup script for Kascade.
;
; Builds a per-user installer (no admin / UAC) that installs the PyInstaller
; executable to %LocalAppData%\Programs\Kascade, adds Start Menu + optional
; Desktop shortcuts, and registers an uninstaller in Apps & features.
;
; The app version is supplied by the build:
;     ISCC /DAppVersion=0.1.5 installer.iss
; It falls back to 0.0.0 if not provided (e.g. ad-hoc local compiles).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "Kascade"
#define AppPublisher "Kascade"
#define AppExeName "Kascade.exe"

[Setup]
; Stable AppId so upgrades replace the previous install and uninstall works.
AppId={{C7A4E1B9-2D63-4F08-9E5A-1B7C3D9F62A4}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Per-user install: no administrator rights required.
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=Kascade-Setup
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#AppExeName}
WizardStyle=modern
Compression=lzma2
SolidCompression=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

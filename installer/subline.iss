; Inno Setup script for the Subline installer. Built by scripts/build.py
; --installer (and the release workflow) with the folder PyInstaller made:
;
;   ISCC /DAppVersion=0.2.0 /DSourceDir=..\dist\gametl /DOutputDir=..\dist /DIconFile=..\build\gametl.ico installer\subline.iss
;
; A per-user install (no administrator prompt) into %LOCALAPPDATA%\Programs\Subline,
; a Start menu entry, an optional desktop icon, and an uninstaller that
; removes the program files only: profiles, caches and keys stay in
; %APPDATA%\gametl and the Credential Manager, as with the portable zip.

#ifndef AppVersion
  #error Pass /DAppVersion=<version>
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\gametl"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif
#ifndef IconFile
  #define IconFile "..\build\gametl.ico"
#endif

#define AppName "Subline"
#define AppExe "gametl.exe"
#define AppPublisher "Mustafa Yurdakul"
#define AppContact "mustafa@yurdakul.dev"

[Setup]
AppId={{7E0C4B2A-5B8D-4C1E-9C3F-2A6D1F0B9E11}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppContact={#AppContact}
AppSupportURL=mailto:{#AppContact}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.18362
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
OutputDir={#OutputDir}
OutputBaseFilename={#AppName}-v{#AppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
ShowLanguageDialog=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

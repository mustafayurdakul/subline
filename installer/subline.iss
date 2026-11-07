; Inno Setup script for the Subline installer. Built by scripts/build.py
; --installer (and the release workflow) with the folder PyInstaller made:
;
;   ISCC /DAppVersion=0.2.0 /DSourceDir=..\dist\gametl /DOutputDir=..\dist /DIconFile=..\build\gametl.ico installer\subline.iss
;
; A per-user install (no administrator prompt) into %LOCALAPPDATA%\Programs\Subline,
; a Start menu entry, an optional desktop icon, and an uninstaller that
; removes the program files and offers to remove the user's data too:
; profiles, caches, models and the log in %APPDATA%\gametl and the API keys
; in the Credential Manager (gametl-cli --remove-all-data does that part).
; Installing over an older version replaces its runtime folder, so files a
; newer build dropped do not pile up.

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
#define AppCli "gametl-cli.exe"
#define AppPublisher "Mustafa Yurdakul"
#define AppContact "mustafa@yurdakul.dev"
#define AppSite "https://subline.yurdakul.dev"
#define AppRepo "https://github.com/mustafayurdakul/subline"

[Setup]
AppId={{7E0C4B2A-5B8D-4C1E-9C3F-2A6D1F0B9E11}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppContact={#AppContact}
AppPublisherURL={#AppSite}
AppSupportURL={#AppRepo}/issues
AppUpdatesURL={#AppRepo}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Per-user only: the data and the keys are per-user, so a machine-wide
; install adds nothing.
PrivilegesRequired=lowest
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

[InstallDelete]
; What an older build installed: the new build brings all of it again.
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\licenses"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
procedure RemoveUserData;
var
  ResultCode: Integer;
begin
  if not Exec(ExpandConstant('{app}\{#AppCli}'), '--remove-all-data', '', SW_HIDE, ewWaitUntilTerminated, ResultCode)
     or (ResultCode <> 0) then
    MsgBox('Some of your Subline data could not be removed. It is left in '
      + ExpandConstant('{userappdata}\gametl') + ', and saved API keys may be left in '
      + 'Windows Credential Manager (entries that start with gametl/).' + #13#10#13#10
      + 'Subline must not be running while its data is removed: quit it from its tray icon, '
      + 'then delete what is left by hand.',
      mbError, MB_OK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  // usUninstall comes before any file is deleted, so the CLI is still there.
  if (CurUninstallStep = usUninstall) and not UninstallSilent then
    if MsgBox('Also remove your Subline settings, translation caches, downloaded models and saved API keys?',
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      RemoveUserData;
end;

#define MyAppName "1SalemBOT"
#define MyAppPublisher "1SalemBOT"
#define MyAppExeName "1SalemBOT.exe"
#ifndef MyAppVersion
  #error MyAppVersion must be passed by build_shareable_release.ps1 from VERSION.
#endif
#ifndef MyAppVersionInfo
  #error MyAppVersionInfo must be passed by build_shareable_release.ps1 from VERSION.
#endif
#ifndef MyAppSource
  #error MyAppSource must be passed by build_shareable_release.ps1.
#endif
#ifndef MyInstallerOutput
  #define MyInstallerOutput "shareable"
#endif

[Setup]
AppId={{D1E62D79-7D6A-4D82-BD64-1A6F8E2C4C55}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} Setup v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={code:GetInstallDir}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=no
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={#MyInstallerOutput}
OutputBaseFilename=1SalemBOT_Setup_v{#MyAppVersion}
SetupIconFile={#MyAppSource}\_internal\assets\bot_icon.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
WizardResizable=no
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesInstallIn64BitMode=x64compatible
VersionInfoVersion={#MyAppVersionInfo}
VersionInfoDescription={#MyAppName} Setup v{#MyAppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional options:"
Name: "freshinstall"; Description: "Fresh install (clear old cache, logs, and settings)"; GroupDescription: "Additional options:"

[Files]
Source: "{#MyAppSource}\*"; DestDir: "{app}"; Excludes: "Launch 1SalemBOT Portable.bat,README.txt,user-data\*"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent unchecked

[Code]
function GetInstallDir(Param: string): string;
begin
  if IsAdminInstallMode then
    Result := ExpandConstant('{autopf}\{#MyAppName}')
  else
    Result := ExpandConstant('{localappdata}\Programs\{#MyAppName}');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssInstall) and WizardIsTaskSelected('freshinstall') then
  begin
    DelTree(ExpandConstant('{userappdata}\{#MyAppName}'), True, True, True);
    DelTree(ExpandConstant('{localappdata}\{#MyAppName}'), True, True, True);
    DelTree(ExpandConstant('{userappdata}\1SalemGPT'), True, True, True);
    DelTree(ExpandConstant('{localappdata}\1SalemGPT'), True, True, True);
    DelTree(ExpandConstant('{app}\user-data'), True, True, True);
  end;
end;

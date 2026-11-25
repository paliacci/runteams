[Setup]
AppId=RunTeams.Local
AppName=RunTeams Local
AppVersion={#AppVersion}
AppPublisher=RunTeams
DefaultDirName={localappdata}\Programs\RunTeams Local
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\RunTeamsLocal.exe
OutputDir={#Destination}
OutputBaseFilename=RunTeams-Local-{#AppVersion}-windows-x64-setup
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "{#Payload}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{userprograms}\RunTeams Local"; Filename: "{app}\RunTeamsLocal.exe"; AppUserModelID: "RunTeams.Local"

[Run]
Filename: "{app}\RunTeamsLocal.exe"; Description: "Open RunTeams Local"; Flags: postinstall nowait skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Command: String;
begin
  if (CurUninstallStep = usPostUninstall) and
     RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'RunTeams.Local', Command) and
     (CompareText(Command, '"' + ExpandConstant('{app}\RunTeamsLocal.exe') + '"') = 0) then
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'RunTeams.Local');
end;

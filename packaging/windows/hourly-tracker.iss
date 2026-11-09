#define AppName "Hourly Tracker"
#define AppVersion "2.0.0"
#define AppPublisher "Alex Pastel"
#define AppExeName "HourlyTracker.exe"
#define AppId "{{CC4C553E-C848-42CC-B4D5-55D315E89910}"
#define ProjectRoot AddBackslash(SourcePath) + "..\.."

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
OutputDir={#ProjectRoot}\dist
OutputBaseFilename=HourlyTracker-Setup
SetupIconFile={#ProjectRoot}\packaging\windows\hourly-tracker.ico
UninstallDisplayIcon={app}\{#AppExeName}
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "startup"; Description: "Start Hourly Tracker when I sign in to Windows"

[Files]
Source: "{#ProjectRoot}\dist\HourlyTracker.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autoprograms}\Uninstall {#AppName}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Start Hourly Tracker now"; Flags: postinstall nowait skipifsilent

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Hourly Tracker"; ValueData: """{app}\{#AppExeName}"""; Tasks: startup; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "Hourly Tracker"; Tasks: not startup; Flags: deletevalue uninsdeletevalue

[UninstallDelete]
Type: filesandordirs; Name: "{userappdata}\HourlyTrackerV2"

; Inno Setup script. Per-user install (no administrator rights): %LOCALAPPDATA%\Programs\WorldStudio
; Expects, relative to this file's folder (..\..\build\stage):  runtime\python (CPython 3.11 incl. tkinter), launcher\, app\
#define AppName "World Studio"
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{6F1B7C1E-5C0A-4C55-9E0B-3A57C2D4A111}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\WorldStudio
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=WorldStudio-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
UninstallDisplayName={#AppName}

[Files]
Source: "..\..\build\stage\runtime\*"; DestDir: "{app}\runtime"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\..\build\stage\launcher\*"; DestDir: "{app}\launcher"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\..\build\stage\app\*"; DestDir: "{app}\app"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\launcher\launcher.py"""; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\launcher\launcher.py"""; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\launcher\launcher.py"""; Description: "Launch {#AppName}"; Flags: postinstall nowait skipifsilent

; User data (environments, projects, logs) lives in %LOCALAPPDATA%\WorldStudio and is deliberately NOT removed on uninstall.

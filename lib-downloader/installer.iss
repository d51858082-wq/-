#ifndef AppVersion
#define AppVersion "1.0.0"
#endif

[Setup]
AppId={{B7C1E2A4-5D3F-4B8E-9A21-6F0C3D7E8A15}
AppName=Lib Downloader
AppVersion={#AppVersion}
DefaultDirName={autopf}\Lib Downloader
DisableProgramGroupPage=yes
OutputDir=installer_out
OutputBaseFilename=LibDownloader-Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
WizardStyle=modern
UninstallDisplayIcon={app}\LibDownloader.exe

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"

[Files]
Source: "dist\LibDownloader.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Lib Downloader"; Filename: "{app}\LibDownloader.exe"
Name: "{autodesktop}\Lib Downloader"; Filename: "{app}\LibDownloader.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LibDownloader.exe"; Description: "Запустить Lib Downloader"; Flags: nowait postinstall skipifsilent

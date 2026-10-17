; Inno Setup recipe for the Windows installer.
; Build after PyInstaller:  iscc /DAppVersion=0.10.0 packaging\installer.iss
; Installs for the current user only (no administrator prompt), into
; %LOCALAPPDATA%\Programs\Inventory Buddy Desktop, with a Start menu entry,
; an optional desktop shortcut, and an uninstaller.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F3B2A1E-6C0D-4C8E-9B6F-1D2E7A9C4B10}
AppName=Inventory Buddy Desktop
AppVersion={#AppVersion}
AppVerName=Inventory Buddy Desktop {#AppVersion}
AppPublisher=Inventory Buddy
DefaultDirName={localappdata}\Programs\Inventory Buddy Desktop
DefaultGroupName=Inventory Buddy Desktop
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename=Inventory-Buddy-Desktop-Setup-{#AppVersion}
SetupIconFile=app.ico
LicenseFile=..\LICENSE
UninstallDisplayIcon={app}\SLInventoryCleanup.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Put a shortcut on the desktop"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\SLInventoryCleanup\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[InstallDelete]
; Clear out files from an older version before copying the new ones in.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\Inventory Buddy Desktop"; Filename: "{app}\SLInventoryCleanup.exe"
Name: "{group}\Uninstall Inventory Buddy Desktop"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Inventory Buddy Desktop"; Filename: "{app}\SLInventoryCleanup.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\SLInventoryCleanup.exe"; Description: "Open Inventory Buddy Desktop now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM SLInventoryCleanup.exe"; Flags: runhidden; RunOnceId: "StopApp"

[Messages]
WelcomeLabel2=This will install [name/ver] on your computer.%n%nYour categories, sorting choices and run history are kept in your own settings folder, so they carry over from earlier versions and stay if you uninstall.

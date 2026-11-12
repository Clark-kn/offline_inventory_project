; Inno Setup script for Kaliwabo Inventory.
;
; Build with Inno Setup 7 (https://jrsoftware.org/isinfo.php):
;   1. Run:  pyinstaller inventory_manager.spec   (produces dist\InventoryManager\)
;   2. Open this file in Inno Setup, or run:  iscc installer.iss
;   3. The installer is written to installer_output\InventoryManagerSetup.exe
;
; Deliberately does NOT touch %ProgramData%\OfflineInventory or
; %AppData%\OfflineInventory on install or uninstall: that is where the
; database, backups, and location config live, kept outside the install
; directory precisely so upgrades and reinstalls never touch operational
; data (see app/config/paths.py and app/config/app_config.py).

#define MyAppName "Kaliwabo Inventory"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Kaliwabo Software Studio"
#define MyAppInstallDir "Offline Inventory Management System"
#define MyAppExeName "InventoryManager.exe"

[Setup]
AppId={{B6C6D9E1-6F2E-4B9A-9C7D-6B6F0B1B4A9E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppInstallDir}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Per-user installation only. This matches the application's HKCU
; uninstall registration and avoids admin elevation or machine-wide
; installation. The app is installed under the current user's LocalAppData.
PrivilegesRequired=lowest

OutputDir=installer_output
OutputBaseFilename=InventoryManagerSetup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
; Everything PyInstaller produced in the one-dir build.
Source: "dist\InventoryManager\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

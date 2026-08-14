; Commissioning and Maintenance Panel — Windows installer (Inno Setup 6.3+)
;
; Build (version and paths come from outside, so there stays one version
; source):
;   ISCC.exe /DMyAppVersion=0.9.0-dev ^
;            /DSourceDir=..\..\dist\dabp ^
;            /DOutputDir=..\..\release ^
;            dabp.iss
;
; Why an installer? Windows stamps files extracted from a ZIP as "downloaded
; from the internet" (Zone.Identifier) and .NET then rejects
; _internal\pythonnet\runtime\Python.Runtime.dll with 0x80131515. Files placed
; by an installer never get that stamp.

; Read by the person installing it — the setup wizard, the Start menu
; entry, the uninstall list. Fixed at build time, so unlike the name
; inside the app it cannot follow the chosen language.
#define MyAppName "Devreye Alma ve Bakım Paneli"
#define MyAppPublisher "Piton Technology"
#define MyAppExeName "dabp.exe"
#define MyAppUrl "https://github.com"

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\dabp"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\release"
#endif

[Setup]
; This GUID is fixed: it makes updates install over the same installation.
; It is SEPARATE from the Switch Management Panel's GUID — the two
; applications install side by side.
AppId={{1D33CE96-66C7-41A7-9A7F-4EEC36A3D8A0}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppUrl}
; VersionInfoVersion accepts numbers only; Inno Setup errors out on a
; pre-release suffix such as "0.9.0-dev", so it is not set here.
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} setup
VersionInfoProductName={#MyAppName}

; The folder name is deliberately ASCII: some tools and scripts trip over
; paths with non-ASCII characters. It matches the executable so the
; installed folder and the downloaded file carry the same name.
DefaultDirName={autopf}\dabp
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}

OutputDir={#OutputDir}
OutputBaseFilename=dabp-{#MyAppVersion}-windows-x64-Setup
; There is no icon yet; once added it is picked up automatically.
#if FileExists(AddBackslash(SourcePath) + "..\..\icons\app.ico")
SetupIconFile=..\..\icons\app.ico
#endif

; 64-bit Windows only
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

PrivilegesRequired=admin
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

; On an update, close the running application and do not reopen it afterwards
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The WHOLE PyInstaller onedir output — the _internal folder included.
; Copying only the exe does not work.
Source: "{#SourceDir}\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

; WebView2 Evergreen Bootstrapper — installed only when the runtime is
; missing. If the file is absent (redist was not downloaded) the setup still
; completes.
Source: "redist\MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; \
    Flags: deleteafterinstall skipifsourcedoesntexist; \
    Check: not IsWebView2Installed

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
    Tasks: desktopicon

[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; \
    Parameters: "/silent /install"; \
    StatusMsg: "Installing the Microsoft Edge WebView2 Runtime..."; \
    Flags: waituntilterminated skipifdoesntexist; \
    Check: not IsWebView2Installed

Filename: "{app}\{#MyAppExeName}"; \
    Description: "{cm:LaunchProgram,{#MyAppName}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Leftovers produced while PyInstaller runs. The user's saved configuration
; defaults are NOT touched — they live under
; %APPDATA%\dabp (see panel/settings.py:data_dir()).
Type: filesandordirs; Name: "{app}\_internal\__pycache__"

[Code]
const
  WEBVIEW2_KEY =
    'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

function IsWebView2Installed(): Boolean;
var
  Version: String;
begin
  { EdgeUpdate writes the version into the 32-bit view; both the machine and
    the user hive are checked. }
  Result := RegQueryStringValue(HKLM32, WEBVIEW2_KEY, 'pv', Version);
  if not Result then
    Result := RegQueryStringValue(HKCU32, WEBVIEW2_KEY, 'pv', Version);
  Result := Result and (Version <> '') and (Version <> '0.0.0.0');
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if IsWebView2Installed() then
    Log('WebView2 Runtime is installed — the bootstrapper will be skipped.')
  else
    Log('WebView2 Runtime not found — the bootstrapper will be run.');
end;

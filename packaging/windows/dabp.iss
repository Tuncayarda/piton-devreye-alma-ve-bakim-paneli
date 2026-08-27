; Commissioning and Maintenance Panel — Windows installer (Inno Setup 6.3+)
;
; Build. Every name comes from outside so there stays ONE source for the
; version (panel/settings.py) and ONE for the edition
; (panel/editions/catalogue.py, read by tools/edition_info.py):
;   ISCC.exe /DMyAppVersion=1.0.0 ^
;            /DMyAppSlug=dabp-gdm ^
;            /DMyAppName="Devreye Alma ve Bakım Paneli - GDM" ^
;            /DMyAppId="{BEA834CD-...}" ^
;            /DSourceDir=..\..\dist\dabp-gdm ^
;            /DOutputDir=..\..\release ^
;            dabp.iss
;
; Why an installer? Windows stamps files extracted from a ZIP as "downloaded
; from the internet" (Zone.Identifier) and .NET then rejects
; _internal\pythonnet\runtime\Python.Runtime.dll with 0x80131515. Files placed
; by an installer never get that stamp.

; EVERY NAME HERE COMES FROM THE EDITION TABLE, passed in with /D by the
; build. One program is packaged once per customer (see panel/editions), and
; two editions may sit on the same machine: they need different folders,
; different Start menu entries and — above all — different AppIds, or an
; update to one lands on the other.
;
; The defaults below are what a build run BY HAND with no /D gets. They are
; the single-edition names this installer had before, so the file still does
; something sensible on its own rather than producing "-.exe".
;
; Read by the person installing it — the setup wizard, the Start menu entry,
; the uninstall list. Fixed at build time, so unlike the name inside the app
; it cannot follow the chosen language.
#ifndef MyAppName
  #define MyAppName "Devreye Alma ve Bakım Paneli"
#endif
#ifndef MyAppSlug
  #define MyAppSlug "dabp"
#endif
#ifndef MyAppId
  ; Inherited by the edition that succeeds today's installations, so it
  ; updates over them instead of landing beside them. Every other edition is
  ; passed its own GUID from the table.
  #define MyAppId "{1D33CE96-66C7-41A7-9A7F-4EEC36A3D8A0}"
#endif
#define MyAppPublisher "Piton Technology"
#define MyAppExeName MyAppSlug + ".exe"
#define MyAppUrl "https://github.com"

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\" + MyAppSlug
#endif
#ifndef OutputDir
  #define OutputDir "..\..\release"
#endif

[Setup]
; Fixed PER EDITION: it makes an update install over the same installation,
; and it is what keeps two editions — and the Switch Management Panel —
; installed side by side instead of on top of each other.
;
; THE DOUBLED BRACE IS NOT A TYPO. "{" opens a constant in Inno Setup, so a
; GUID written plainly is read as one: the compiler stopped with
; `Unknown constant "1D33CE96-…"` and the release build died at the last
; step of the Windows package. "{{" is the escape for a literal brace; the
; preprocessor fills in the rest, braces included, from the edition table.
AppId={{#MyAppId}
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
DefaultDirName={autopf}\{#MyAppSlug}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}

OutputDir={#OutputDir}
OutputBaseFilename={#MyAppSlug}-{#MyAppVersion}-windows-x64-Setup
; The application's own icon, built from the logo by tools/make_icons.py.
; Kept conditional so a tree without it still compiles.
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
;
; `recursesubdirs` is also what carries the bundled Android tools
; (platform-tools\adb.exe, see dabp.spec): they need no line of their own,
; and no executable bit on Windows. Written down because the AppImage script
; DOES need a line for them, and the two packagings should not look
; inconsistent by accident.
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
; %APPDATA%\dabp\<edition> (see panel/settings.py:data_dir()).
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

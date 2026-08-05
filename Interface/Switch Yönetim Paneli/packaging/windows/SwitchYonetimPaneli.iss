; Switch Yönetim Paneli — Windows kurulum paketi (Inno Setup 6.3+)
;
; Derleme (sürüm ve yollar dışarıdan verilir, tek sürüm kaynağı korunur):
;   ISCC.exe /DMyAppVersion=1.0.3 ^
;            /DSourceDir=..\..\dist\SwitchYonetimPaneli ^
;            /DOutputDir=..\..\release ^
;            SwitchYonetimPaneli.iss
;
; Neden installer? ZIP'ten çıkarılan dosyalara Windows "internetten indirildi"
; damgası (Zone.Identifier) koyuyor ve .NET, _internal\pythonnet\runtime\
; Python.Runtime.dll dosyasını 0x80131515 ile reddediyor. Installer ile kurulan
; dosyalarda bu damga oluşmaz.

#define MyAppName "Switch Yönetim Paneli"
#define MyAppPublisher "Piton Technology"
#define MyAppExeName "SwitchYonetimPaneli.exe"
#define MyAppUrl "https://github.com"

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\SwitchYonetimPaneli"
#endif
#ifndef OutputDir
  #define OutputDir "..\..\release"
#endif

[Setup]
; Bu GUID sabittir: güncellemelerin aynı kurulumun üzerine gelmesini sağlar.
AppId={{47F52AC6-2C3C-478C-8AFD-471A9E3A3367}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppUrl}
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} kurulumu
VersionInfoProductName={#MyAppName}

; Klasör adı bilerek ASCII: bazı araçlar ve betikler Türkçe karakterli
; yollarda takılabiliyor. Görünen ad Türkçe kalıyor.
DefaultDirName={autopf}\Switch Yonetim Paneli
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}

OutputDir={#OutputDir}
OutputBaseFilename=SwitchYonetimPaneli-{#MyAppVersion}-windows-x64-Setup
SetupIconFile=..\..\icons\app.ico

; Yalnızca 64-bit Windows
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

PrivilegesRequired=admin
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

; Güncellemede çalışan uygulamayı kapat, kurulum sonrası tekrar açma
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=no

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; PyInstaller onedir çıktısının TAMAMI — _internal klasörü dahil.
; Yalnızca exe kopyalamak çalışmaz.
Source: "{#SourceDir}\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

; WebView2 Evergreen Bootstrapper — yalnızca runtime yoksa kurulur.
; Dosya yoksa (redist indirilmemişse) kurulum yine de tamamlanır.
Source: "redist\MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; \
    Flags: deleteafterinstall skipifsourcedoesntexist; \
    Check: not WebView2Kurulu

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
    Tasks: desktopicon

[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; \
    Parameters: "/silent /install"; \
    StatusMsg: "Microsoft Edge WebView2 Runtime kuruluyor..."; \
    Flags: waituntilterminated skipifdoesntexist; \
    Check: not WebView2Kurulu

Filename: "{app}\{#MyAppExeName}"; \
    Description: "{cm:LaunchProgram,{#MyAppName}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; PyInstaller çalışırken üretilen artıklar. Kullanıcının log ve ayar
; dosyalarına DOKUNULMAZ — onlar %LOCALAPPDATA%\SwitchYonetimPaneli altında.
Type: filesandordirs; Name: "{app}\_internal\__pycache__"

[Code]
const
  WEBVIEW2_ANAHTAR =
    'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

function WebView2Kurulu(): Boolean;
var
  Surum: String;
begin
  { EdgeUpdate sürümü 32-bit görünüme yazar; hem makine hem kullanıcı
    kovanına bakıyoruz. }
  Result := RegQueryStringValue(HKLM32, WEBVIEW2_ANAHTAR, 'pv', Surum);
  if not Result then
    Result := RegQueryStringValue(HKCU32, WEBVIEW2_ANAHTAR, 'pv', Surum);
  Result := Result and (Surum <> '') and (Surum <> '0.0.0.0');
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if WebView2Kurulu() then
    Log('WebView2 Runtime kurulu — bootstrapper atlanacak.')
  else
    Log('WebView2 Runtime bulunamadı — bootstrapper çalıştırılacak.');
end;

"use strict";
const $ = (s) => document.querySelector(s);
let current = null;   // seçili switch IP'si
let hamPorts = [];    // switch'ten okunan gerçek durum
let ports = [];       // ekranda gösterilen (ham + bekleyen değişiklikler)
let busy = false;     // işlem sürerken otomatik yenileme beklesin
let timer = null;
let lastOk = null;    // son başarılı yenileme zamanı
let lastErr = null;   // son yenileme hatası

// Gönderim modu:
//   "anlik" — her değişiklik anında switch'e gider, otomatik yenileme açık
//   "toplu" — değişiklikler biriktirilir, otomatik yenileme durur,
//             "Gönder" deyince hepsi tek istekte uygulanır
let mod = "anlik";
const bekleyenPoe = new Map();    // pid -> "0"|"1"|"2"
const bekleyenPort = new Map();   // pid -> true/false

// Switch'e uygulanmış ama flash'a yazılmamış değişiklik var mı?
// Kayıt artık kendiliğinden yapılmıyor; yalnızca "Kaydet" yazıyor.
// Yeniden başlatma bu değişiklikleri götürür, o yüzden takip ediyoruz.
let kayitBekliyor = false;

function kayitDurumu(varMi) {
  kayitBekliyor = varMi;
  const b = $("#save-cfg");
  b.classList.toggle("dirty", varMi);
  b.title = varMi
    ? "Kaydedilmemiş değişiklik var — switch yeniden başlarsa geri alınır"
    : "Çalışan yapılandırmayı kalıcı hale getir";
}

// Bildirim geçmişe de düşer. `gecmise` yalnızca toplu gönderimde kapatılır:
// orada geçmişe özet değil, değişikliklerin tek tek kendisi yazılır.
function toast(msg, kind = "", gecmise = true) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "show " + kind;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.className = ""), kind === "err" ? 6000 : 4000);
  if (gecmise) logEkle(msg, kind === "err");
}

// İstekte hangi switch'ten söz ediliyor? Sorgu dizesinden ya da gövdeden.
function istekIp(path, opts) {
  const q = path.match(/[?&]ip=([^&]+)/);
  if (q) return decodeURIComponent(q[1]);
  try {
    if (opts && opts.body) return JSON.parse(opts.body).ip || null;
  } catch (e) { /* gövde JSON değilse boş ver */ }
  return null;
}

// Switch kimlik isterse (401) kullanıcıdan alıp isteği bir kez daha dener.
// Bu tek nokta olduğu için hangi çağrı olursa olsun aynı davranış: port
// okuma, PoE değiştirme, kaydetme… hepsi gerektiğinde şifre sorar.
async function api(path, opts, tekrarHakki = true) {
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (r.ok) return data;

  const kimlikGerek = r.status === 401 || data.kimlik === true;
  if (kimlikGerek && tekrarHakki && !path.startsWith("/api/switch/login")) {
    const ip = istekIp(path, opts) || current;
    if (ip && await girisSor(ip)) {
      // Şifre girildikten sonra veriler gelene kadar ekran boş kalmasın.
      // Perde zaten açıksa (bir işlemin ortasındayız) ona dokunmayız —
      // kapatmak da o işleme kalır.
      const perdeVardi = busy;
      setBusy(true, "Kimlik doğrulandı, veriler alınıyor…");
      try {
        return await api(path, opts, false);
      } finally {
        if (!perdeVardi) setBusy(false);
      }
    }
  }
  const hata = new Error(data.error || r.statusText);
  hata.kimlik = kimlikGerek;
  throw hata;
}

// ─────────────────────────────────────────────────── onay penceresi ──────
// Yerel confirm()/prompt() her platformda başka türlü görünüyor (WebView2,
// WKWebView, QtWebEngine) ve pencerenin dilini işletim sistemi belirliyor.
// Kendi penceremizi kullanınca üç platformda da aynı görünüyor ve metinleri
// biz yazıyoruz.
//
//   await onay({ baslik, mesaj })                       -> true/false
//   await onay({ …, tehlike: true })                    -> kırmızı onay
//   await onay({ …, girisEtiketi, beklenenDeger })      -> yazarak onay
let onayBekleyen = null;

function onay(secenek) {
  const o = secenek || {};
  return new Promise((tamam) => {
    onayBekleyen = { tamam, beklenen: o.beklenenDeger || null };

    $("#dialog-title").textContent = o.baslik || "Onay";
    $("#dialog-body").textContent = o.mesaj || "";

    const dugme = $("#dialog-ok");
    dugme.textContent = o.onayMetni || "Onayla";
    dugme.classList.toggle("danger", Boolean(o.tehlike));

    const sarmal = $("#dialog-input-wrap");
    const giris = $("#dialog-input");
    const yazarak = Boolean(o.beklenenDeger);
    sarmal.classList.toggle("hidden", !yazarak);
    $("#dialog-input-label").textContent = o.girisEtiketi || "";
    giris.value = "";

    const hata = $("#dialog-err");
    hata.textContent = "";
    hata.classList.add("hidden");

    $("#dialog").classList.remove("hidden");
    setTimeout(() => (yazarak ? giris : dugme).focus(), 30);
  });
}

function onayKapat(sonuc) {
  const bekleyen = onayBekleyen;
  onayBekleyen = null;
  $("#dialog").classList.add("hidden");
  $("#dialog-input").value = "";
  if (bekleyen) bekleyen.tamam(sonuc);
}

function onayGonder(e) {
  if (e) e.preventDefault();
  if (!onayBekleyen) return;
  const { beklenen } = onayBekleyen;
  if (beklenen) {
    // Yazarak onay: yıkıcı işlemlerde yanlışlıkla tıklamayı engeller
    if ($("#dialog-input").value.trim() !== beklenen) {
      const hata = $("#dialog-err");
      hata.textContent = `Doğrulanmadı — tam olarak "${beklenen}" yazın.`;
      hata.classList.remove("hidden");
      $("#dialog-input").select();
      return;
    }
  }
  onayKapat(true);
}

// ------------------------------------------------ kimlik doğrulama -------
// Kullanıcı adı/şifre hiçbir yere kaydedilmez: buradan backend'e gider,
// orada yalnızca bellekte durur. Bu sayfa da onları saklamaz, alanlar
// gönderildikten hemen sonra temizlenir.
let girisBekleyen = null;         // { ip, tamam, sozu }
let kimlikIptal = false;          // kullanıcı vazgeçtiyse arka planda ısrar etme

function girisSor(ip, uyari) {
  // Aynı switch için pencere zaten açıksa ikincisini açma; birden çok
  // istek (örneğin otomatik yenileme) aynı cevabı beklesin.
  if (girisBekleyen && girisBekleyen.ip === ip) return girisBekleyen.sozu;

  const sozu = new Promise((tamam) => {
    girisBekleyen = { ip, tamam, sozu: null };
    $("#login-ip").textContent = ip;
    $("#login-pass").value = "";
    const hataKutu = $("#login-err");
    hataKutu.textContent = uyari || "";
    hataKutu.classList.toggle("hidden", !uyari);
    $("#login").classList.remove("hidden");
    const kul = $("#login-user");
    setTimeout(() => (kul.value ? $("#login-pass") : kul).focus(), 30);
  });
  girisBekleyen.sozu = sozu;
  return sozu;
}

function girisKapat() {
  $("#login").classList.add("hidden");
  $("#login-pass").value = "";      // şifre ekranda kalmasın
  girisBekleyen = null;
}

async function girisGonder(e) {
  if (e) e.preventDefault();
  if (!girisBekleyen) return;
  const { ip, tamam } = girisBekleyen;
  const kullanici = $("#login-user").value.trim();
  const sifre = $("#login-pass").value;
  const dugme = $("#login-ok");
  const dugmeYazi = dugme.textContent;
  dugme.disabled = true;
  dugme.innerHTML = '<span class="btn-spin"></span>Doğrulanıyor';
  try {
    await api("/api/switch/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ip, user: kullanici, pass: sifre }),
    });
    kimlikIptal = false;
    girisKapat();
    tamam(true);
  } catch (err) {
    const kutu = $("#login-err");
    kutu.textContent = err.kimlik
      ? "Kullanıcı adı ya da şifre hatalı."
      : "Bağlanılamadı: " + err.message;
    kutu.classList.remove("hidden");
    $("#login-pass").value = "";
    $("#login-pass").focus();
  } finally {
    dugme.disabled = false;
    dugme.textContent = dugmeYazi;
  }
}

function girisIptal() {
  const bekleyen = girisBekleyen;
  kimlikIptal = true;      // otomatik yenileme durup dururken tekrar sormasın
  girisKapat();
  if (bekleyen) bekleyen.tamam(false);
}

// ------------------------------------------------ işlem perdesi ----------
function setBusy(on, msg) {
  busy = on;
  const ov = $("#overlay");
  if (msg) ov.querySelector(".msg").textContent = msg;
  ov.classList.toggle("hidden", !on);
}

// Her değiştirme işlemi buradan geçer: perde açılır, istek atılır,
// switch'ten güncel durum tekrar okunur, sonra perde kalkar.
// Perde açıkken başka istek gönderilemez (otomatik yenileme dahil).
//
// `basariMsg` dizi verilirse (toplu gönderim) her satır işlem geçmişine
// ayrı ayrı yazılır; ekranda yalnızca kısa bir özet gösterilir. Tek bir
// "3 değişiklik uygulandı" satırı, neyin değiştiğini geçmişten okumayı
// imkânsız kılıyordu.
async function islem(bekletMsg, istek, basariMsg) {
  if (busy) { toast("Önceki işlem sürüyor, bekleyin", "err"); return; }
  setBusy(true, bekletMsg);
  try {
    const res = await istek();
    setBusy(true, "Durum doğrulanıyor…");
    await loadPorts();
    // Uygulandı ama flash'a yazılmadı; kalıcı olması için Kaydet gerekli
    kayitDurumu(true);
    if (Array.isArray(basariMsg)) {
      basariMsg.forEach((satir) => logEkle(satir));
      toast(`${basariMsg.length} değişiklik uygulandı`, "ok", false);
    } else {
      toast(basariMsg || "İşlem tamamlandı", "ok");
    }
    return res;
  } catch (e) {
    toast("Hata: " + e.message, "err");
    throw e;
  } finally {
    setBusy(false);
  }
}

// --------------------------------------------------------- keşif ----------
// Bir /24 taraması yüzlerce istek demek. Üst üste basılınca istekler
// yığılıp switch'in küçük web sunucusunu boğuyor ve arayüz donmuş gibi
// görünüyordu. Artık aynı düğme tarama sürerken "İptal"e dönüşüyor:
// yanlış aralık yazıldığında dakikalarca beklemek gerekmiyor.
let scanning = false;
let scanAbort = null;          // süren taramanın yerel iptal denetleyicisi
let scanIptalEdildi = false;   // iptali kullanıcı mı istedi, zaman aşımı mı
const SCAN_TIMEOUT = 120000;   // hiçbir koşulda kilitli kalmasın

function setScanning(on) {
  scanning = on;
  const b = $("#scan");
  b.disabled = false;          // tarama sürerken iptal için basılabilir olmalı
  b.classList.toggle("loading", on);
  b.classList.toggle("cancel", on);
  b.innerHTML = on ? '<span class="btn-spin"></span>İptal' : "Tara";
  b.title = on ? "Taramayı durdur" : "Ağı tara";
}

// Yalnızca fetch'i kesmek yetmiyor: sunucu tarafındaki tarama switch'lere
// istek atmaya devam eder ve kilidi bırakmaz, hemen ardından basılan
// "Tara" da "tarama zaten sürüyor" hatasına düşerdi. O yüzden önce
// sunucuya haber verip taramanın gerçekten durmasını bekliyoruz.
async function scanIptal() {
  if (!scanning || scanIptalEdildi) return;
  scanIptalEdildi = true;
  // Kesilecek denetleyiciyi şimdi yakalıyoruz: bekleme sırasında bu tarama
  // kendiliğinden bitip kullanıcı yenisini başlatmış olabilir, o zaman
  // aşağıdaki abort() yanlış taramayı keserdi.
  const kesilecek = scanAbort;
  const b = $("#scan");
  b.disabled = true;
  b.innerHTML = '<span class="btn-spin"></span>Duruyor';
  try {
    await fetch("/api/discover/cancel");
  } catch (e) { /* sunucu yanıt vermese de yerel isteği keseceğiz */ }
  if (kesilecek) kesilecek.abort();
}

async function scan() {
  if (scanning) return;
  const cidr = $("#cidr").value.trim();
  scanIptalEdildi = false;
  setScanning(true);
  $("#list").innerHTML = "";      // durum yalnızca butonda görünür

  scanAbort = new AbortController();
  const zaman = setTimeout(() => scanAbort.abort(), SCAN_TIMEOUT);
  try {
    const res = await api("/api/discover?cidr=" + encodeURIComponent(cidr),
                          { signal: scanAbort.signal });
    // Sunucu taramayı yarıda bıraktıysa sonuç eksiktir; "bulunamadı"
    // demek yanıltıcı olur.
    if (res.iptal || scanIptalEdildi) {
      $("#list").innerHTML = `<div class="muted">Tarama iptal edildi.</div>`;
      return;
    }
    const switches = res.switches || [];
    if (!switches.length) {
      $("#list").innerHTML =
        `<div class="muted">Switch bulunamadı.<br><br>` +
        `${res.queried} adres soruldu.<br>` +
        `Ağ aralığı ve port doğru mu?</div>`;
      return;
    }
    $("#list").innerHTML = "";
    switches.forEach((s) => {
      const el = document.createElement("div");
      el.className = "sw-item" + (s.kilit ? " kilit" : "");
      el.innerHTML = `<div class="ip">${s.ip}</div>` + (s.kilit
        ? `<div class="kilit-not">Kimlik doğrulama gerekli</div>`
        : `<div class="mdl">${s.model || "Switch"} / v${s.version || "?"}</div>`);
      el.onclick = () => select(s.ip, el);
      $("#list").appendChild(el);
    });
  } catch (e) {
    let msg;
    if (scanIptalEdildi) msg = "Tarama iptal edildi.";
    else if (e.name === "AbortError")
      msg = "Tarama çok uzun sürdü, iptal edildi. Tek IP ile deneyin.";
    else msg = "Hata: " + e.message;
    $("#list").innerHTML = `<div class="muted">${msg}</div>`;
  } finally {
    clearTimeout(zaman);
    scanAbort = null;
    scanIptalEdildi = false;
    setScanning(false);
  }
}

async function select(ip, el) {
  if (mod === "toplu" && bekleyenSayi() && ip !== current &&
      !(await onay({
        baslik: "Bekleyen değişiklikler",
        mesaj: `${bekleyenSayi()} değişiklik gönderilmedi. ` +
               "Başka switch'e geçersen iptal olur.",
        onayMetni: "Yine de geç", tehlike: true }))) return;
  current = ip;
  kimlikIptal = false;
  hamPorts = [];
  bekleyenPoe.clear();
  bekleyenPort.clear();
  menuKapat();
  secili.clear();            // seçim switch'e özgü, yenisine taşınmaz
  secimCapa = null;
  kayitDurumu(false);        // yeni switch, yeni kayıt durumu
  document.querySelectorAll(".sw-item").forEach((x) => x.classList.remove("active"));
  el?.classList.add("active");
  lastOk = null; lastErr = null;

  // Kimlik gerekiyorsa api() kendisi sorar. Kullanıcı vazgeçerse ya da
  // switch'e ulaşılamazsa detayı hiç açmıyoruz.
  try {
    await loadInfo();
    // Kimlik istendiyse perde zaten açıktı; port okuma da sürdüğü için
    // kapanmasın — kullanıcı boş ekrana bakmasın.
    setBusy(true, "Veriler alınıyor…");
    await loadPorts();
  } catch (e) {
    $("#detail").classList.add("hidden");
    current = null;
    el?.classList.remove("active");
    toast(e.kimlik ? "Kimlik doğrulanmadı, switch açılamadı"
                   : "Hata: " + e.message, "err");
    return;
  } finally {
    setBusy(false);
  }
  el?.classList.remove("kilit");
  const not = el?.querySelector(".kilit-not");
  if (not) not.remove();

  $("#detail").classList.remove("hidden");
  tickRefresh();
}

async function loadInfo() {
  const info = await api("/api/switch/info?ip=" + current);
  // Başlık büyük harfe çevriliyor; yedek metni de öyle yazıyoruz, yoksa
  // Türkçe büyütme kuralı "Switch" → "SWİTCH" yapıyor.
  $("#d-name").textContent = info.name || "SWITCH";
  // Boş alanlar için "/ ip / v?" gibi yarım satır çıkmasın: yalnızca
  // cihazın gerçekten bildirdiklerini yan yana diziyoruz.
  $("#d-sub").textContent = [
    info.model,
    info.ip || current,
    info.version ? "v" + info.version : "",
  ].filter(Boolean).join(" / ");
  const n = info.network || {};
  $("#n-addr").value = n.addr || info.ip;
  $("#n-prefix").value = n.netmaskLen || "8";
  $("#n-mtu").value = n.mtu || "1500";
}

// --------------------------------------------------------- portlar --------
// Portun iki temel niteliği. Hem tablodaki nokta rengi hem ön paneldeki
// konnektör rengi bunlardan türer, o yüzden tek yerde tanımlı.
//   açık     — PoE portunda güç veriliyor, uplinkte port etkin
//   besliyor — PoE portu gerçekten cihaz besliyor (watt çekiyor)
// Bir portun iki bağımsız anahtarı var ve karıştırılmamalı:
//   adminStat -> veri iletimi (portun kendisi açık mı)
//   poeMode   -> güç (yalnızca PoE portlarında)
// Gücü kapatmak veriyi kesmez: kendi elektriğiyle çalışan bir cihaz
// (bilgisayar, uplink) porttan haberleşmeye devam eder. İkisi ayrı
// yönetilir — arayüz birini değiştirirken diğerine dokunmaz; "yalnızca
// PoE'yi kapat" da geçerli bir işlemdir.
function portAcik(p) {
  return Boolean(p.adminStat);           // veri iletimi
}

function gucAcik(p) {
  return Boolean(p.poe) && p.poeMode !== "0";
}

function portBesliyor(p) {
  return Boolean(p.poe && p.linkStat === "up" && p.powerW);
}

// Bağlantı sütunundaki kare:
//   kırmızı — port kapalı (veri yok)
//   yeşil   — bağlı ve güç çekiyor
//   mavi    — bağlı, güç çekmiyor (PoE kapalı ya da cihaz kendi beslenir)
//   gri     — port açık ama karşısında cihaz yok
function nokta(p) {
  if (!portAcik(p)) return "off";
  if (portBesliyor(p)) return "up";
  if (p.linkStat === "up") return "data";
  return "down";
}

function uplinkPids() {
  // link'i up olan portları uplink adayı say (kapatma uyarısı için)
  return ports.filter((p) => p.linkStat === "up").map((p) => p.pid);
}

// Tablo satırı: haritadaki konnektörle aynı seçim ve sağ tık davranışı.
// Satırın içindeki düğme/açılır kutu kendi işini yapar, seçimi bozmaz.
function satirKur(p) {
  const tr = document.createElement("tr");
  tr.dataset.pid = p.pid;
  if (p.linkStat !== "up") tr.classList.add("down");
  if (p.bekliyor) tr.classList.add("pending");
  tr.onclick = (e) => {
    if (e.target.closest("button, select, input, a")) return;
    portTikla(p.pid, e);
  };
  tr.oncontextmenu = (e) => portSagTik(p.pid, e);
  return tr;
}

async function loadPorts() {
  let list;
  try {
    ({ ports: list } = await api("/api/switch/ports?ip=" + current));
    lastOk = Date.now();
    lastErr = null;
  } catch (e) {
    lastErr = e.message;
    tickRefresh();
    throw e;
  }
  hamPorts = list;
  renderPorts();
}

// Ekranda gösterilen liste = switch'ten okunan durum + bekleyen değişiklikler.
// Böylece toplu modda seçim yaptığın anda tabloda görünür ama switch'e
// gitmemiş olur; "Gönder"e kadar sadece burada durur.
function renderPorts() {
  ports = hamPorts.map((p) => ({
    ...p,
    poeMode: bekleyenPoe.has(p.pid) ? bekleyenPoe.get(p.pid) : p.poeMode,
    adminStat: bekleyenPort.has(p.pid) ? bekleyenPort.get(p.pid) : p.adminStat,
    bekliyor: bekleyenPoe.has(p.pid) || bekleyenPort.has(p.pid),
  }));
  // Listeden düşen portlar seçili kalmasın
  [...secili].forEach((pid) => {
    if (!ports.some((p) => p.pid === pid)) secili.delete(pid);
  });
  const up = ports.filter((p) => p.linkStat === "up").length;
  const feeding = ports.filter((p) => p.powerW).length;
  const poeOff = ports.filter((p) => p.poe && p.poeMode === "0").length;
  const geOff = ports.filter((p) => !p.poe && !p.adminStat).length;
  // Her sayaç kendi dikdörtgen bölmesinde: "·" ile ayrılan tek satır
  // uzadıkça hangi sayının neye ait olduğu okunmuyordu.
  const sayaclar = [
    [ports.length, "port", ""],
    [up, "bağlı", "link"],
    [feeding, "besleniyor", "feed"],
  ];
  if (poeOff) sayaclar.push([poeOff, "güç kapalı", "nopwr"]);
  if (geOff) sayaclar.push([geOff, "uplink kapalı", "off"]);
  $("#port-info").innerHTML = sayaclar.map(([n, ad, sinif]) =>
    `<span class="stat ${sinif}"><b>${n}</b>${ad}</span>`).join("");

  // "bekliyor" etiketi her satırda hep basılır, sadece görünürlüğü değişir.
  // Sonradan eklenirse sütun genişliği değişip tablo yana kayıyordu.
  const etiket = (acik) =>
    `<span class="tag-bekliyor${acik ? "" : " gizli"}">bekliyor</span>`;

  const linkCell = (p) =>
    `<span class="dot ${nokta(p)}"></span>` +
    (p.linkStat === "up" ? "up" : '<span class="muted">—</span>');

  // Hız ayrı sütunda: "100M / Full". Cihaz linktext veriyorsa onu
  // kullanırız (gerçek anlaşılan hız), yoksa ayarlardan kurarız.
  const hizCell = (p) => {
    if (p.linkStat !== "up") return '<span class="muted">—</span>';
    if (p.linktext) return p.linktext.trim().replace(/\s+/, " / ");
    return `${p.speed}M / ${p.duplex ? "Full" : "Half"}`;
  };

  // --- PoE portları: iki ayrı denetim — veri (Durum) ve güç (PoE)
  const fe = ports.filter((p) => p.poe);
  const feBody = $("#fe-ports tbody");
  feBody.innerHTML = "";
  $("#fe-cnt").textContent = `${fe.length} port`;
  fe.forEach((p) => {
    const sel = ["0", "1", "2"].map((m) =>
      `<option value="${m}" ${p.poeMode === m ? "selected" : ""}>${
        { 0: "Kapalı", 1: "PoE", 2: "PoE+" }[m]}</option>`).join("");
    const draw = p.powerW ? `${p.powerW} W` : '<span class="muted">—</span>';
    const tr = satirKur(p);
    tr.innerHTML = `
      <td>${p.pid}</td>
      <td>${linkCell(p)}</td>
      <td>${hizCell(p)}</td>
      <td><button class="pill ${p.adminStat ? "on" : "off"}"
                  data-admin="${p.pid}" data-on="${p.adminStat}"
                  title="${p.adminStat ? "Portu kapat" : "Portu aç"}">
            ${p.adminStat ? "Açık" : "Kapalı"}</button>${
        etiket(bekleyenPort.has(p.pid))}</td>
      <td><select class="poe ${p.poeMode === "0" ? "off" : "on"}"
                  data-poe="${p.pid}"
                  title="Portun gücü — veri durumundan bağımsız"
                  >${sel}</select>${etiket(bekleyenPoe.has(p.pid))}</td>
      <td>${draw}</td>`;
    feBody.appendChild(tr);
  });

  // --- Uplink portları: PoE yok, tek anahtar port durumu
  const ge = ports.filter((p) => !p.poe);
  const geBody = $("#ge-ports tbody");
  geBody.innerHTML = "";
  $("#ge-cnt").textContent = `${ge.length} port`;
  ge.forEach((p) => {
    const tr = satirKur(p);
    tr.innerHTML = `
      <td>${p.pid}</td>
      <td>${linkCell(p)}</td>
      <td>${hizCell(p)}</td>
      <td><button class="pill ${p.adminStat ? "on" : "off"}"
                  data-admin="${p.pid}" data-on="${p.adminStat}"
                  title="${p.adminStat ? "Portu kapat" : "Portu aç"}">
            ${p.adminStat ? "Açık" : "Kapalı"}</button>${
        etiket(bekleyenPort.has(p.pid))}</td>`;
    geBody.appendChild(tr);
  });

  document.querySelectorAll("[data-poe]").forEach((s) => {
    s.onchange = () => setPoe(+s.dataset.poe, s.value);
  });
  document.querySelectorAll("[data-admin]").forEach((b) => {
    b.onclick = () => togglePort(+b.dataset.admin, b.dataset.on !== "true");
  });
  panelHaritasi(fe, ge);      // ön panel de aynı veriden çizilir
  boyaSecim();
  batchBar();
  tickRefresh();
}

const POE_AD = { 0: "Kapalı", 1: "PoE", 2: "PoE+" };

function hamPort(pid) {
  return hamPorts.find((p) => p.pid === pid) || {};
}

// "1, 2, 3, 7, 9, 10" yerine "1–3, 7, 9–10". Yirmi dört portun yarısı
// seçiliyken tek tek yazmak şeride ve menü başlığına sığmıyor.
function kisaListe(pidler) {
  const s = [...pidler].sort((a, b) => a - b);
  const parca = [];
  let bas = null, son = null;
  s.forEach((n) => {
    if (bas === null) { bas = son = n; return; }
    if (n === son + 1) { son = n; return; }
    parca.push(bas === son ? `${bas}` : `${bas}–${son}`);
    bas = son = n;
  });
  if (bas !== null) parca.push(bas === son ? `${bas}` : `${bas}–${son}`);
  return parca.join(", ");
}

// Değişikliklerin insan diliyle listesi. Tek yerde duruyor çünkü üç ayrı
// yerde gösteriliyor: onay penceresi (yapılacak), işlem geçmişi (yapıldı)
// ve şeritteki özet.
function adimlariKur(portMap, poeMap) {
  const sirali = (m) => [...m].sort((a, b) => a[0] - b[0]);
  const adimlar = [];
  sirali(portMap).forEach(([pid, acik]) => adimlar.push({
    gelecek: `Port ${pid} ${acik ? "açılacak" : "kapatılacak"}`,
    suruyor: `Port ${pid} ${acik ? "açılıyor" : "kapatılıyor"}…`,
    gecmis: `Port ${pid} ${acik ? "açıldı" : "kapatıldı"}`,
    riskli: !acik && uplinkPids().includes(pid),
  }));
  sirali(poeMap).forEach(([pid, mode]) => adimlar.push({
    gelecek: mode === "0" ? `Port ${pid} gücü kesilecek`
                          : `Port ${pid} gücü ${POE_AD[mode]} olacak`,
    suruyor: mode === "0" ? `Port ${pid} gücü kesiliyor…`
                          : `Port ${pid} gücü ${POE_AD[mode]} yapılıyor…`,
    gecmis: mode === "0" ? `Port ${pid} gücü kesildi`
                         : `Port ${pid} gücü ${POE_AD[mode]} yapıldı`,
    riskli: mode === "0",
  }));
  return adimlar;
}

function onayMesaji(adimlar) {
  const n = adimlar.length;
  return (n === 1 ? "Şu değişiklik switch'e gönderilecek:\n\n"
                  : `${n} değişiklik switch'e tek seferde gönderilecek:\n\n`) +
    adimlar.map((a) => `• ${a.gelecek}`).join("\n") +
    (adimlar.some((a) => a.riskli)
      ? "\n\nDikkat: gücü kesilen porttaki cihaz kapanır, kapatılan bağlı " +
        "portun iletişimi durur. Yönetime bu portlardan birinden " +
        "bağlıysanız switch'e erişimi kaybedebilirsiniz."
      : "") +
    "\n\nDeğişiklikler switch'in çalışan yapılandırmasına yazılır; " +
    "kalıcı olması için sonrasında Kaydet'e basın.";
}

// ─────────────────────────────────────── portlara durum uygulama ──────────
// Portla ilgili her değişiklik buradan geçer: tablodaki tek düğme de,
// sağ tık menüsünden onlarca porta birden verilen komut da.
//
//   pidler — bir ya da çok port numarası
//   secim  — { poe: "0"|"1"|"2"|null, port: true|false|null }
//
// Güç (poe) ve veri (port) birbirinden bağımsız iki anahtar: null verilen
// bölüme hiç dokunulmaz. Böylece "yalnızca PoE'yi kapat", "yalnızca portu
// aç" ya da "ikisini birden ayarla" aynı yoldan yapılabiliyor.
async function uygulaSecim(pidler, secim) {
  const poeSec = secim.poe == null ? null : String(secim.poe);
  const portSec = secim.port == null ? null : Boolean(secim.port);
  if (poeSec === null && portSec === null) return;

  const poeDegis = new Map();    // pid -> mode   (gerçekten değişenler)
  const portDegis = new Map();   // pid -> açık mı
  let poesiz = 0;                // güç seçilemeyen uplink portları

  pidler.forEach((pid) => {
    const ham = hamPort(pid);
    if (ham.pid === undefined) return;      // liste bu arada değişmiş olabilir
    if (poeSec !== null) {
      if (!ham.poe) poesiz++;
      else if (String(ham.poeMode) === poeSec) bekleyenPoe.delete(pid);
      else poeDegis.set(pid, poeSec);
    }
    if (portSec !== null) {
      if (Boolean(ham.adminStat) === portSec) bekleyenPort.delete(pid);
      else portDegis.set(pid, portSec);
    }
  });

  // Uplink portlarında PoE yok. Seçim ikisini birden kapsıyorsa güç kısmı
  // sessizce atlanır; kullanıcı neden 8 porttan 6'sının değiştiğini
  // anlayabilsin diye bu her yerde söyleniyor.
  const atlandi = poesiz
    ? `${poesiz} uplink portunda PoE yok, güç seçimi atlandı.` : "";
  // Seçimin tamamı uplink ve istenen tek şey güçse "zaten istenen durumda"
  // demek yanlış olur: o portlarda güç diye bir ayar yok.
  const yokMesaji = poesiz === pidler.length && portSec === null
    ? atlandi
    : "Seçili portlar zaten istenen durumda." + (atlandi ? " " + atlandi : "");

  // Toplu mod: switch'e gitmez, kuyruğa yazılır. Asıl değerine dönen
  // portlar yukarıda kuyruktan çıkarıldı.
  if (mod === "toplu") {
    poeDegis.forEach((m, pid) => bekleyenPoe.set(pid, m));
    portDegis.forEach((a, pid) => bekleyenPort.set(pid, a));
    renderPorts();
    if (!poeDegis.size && !portDegis.size) toast(yokMesaji, "", false);
    else if (atlandi) toast(atlandi, "", false);
    return;
  }

  const adimlar = adimlariKur(portDegis, poeDegis);
  if (!adimlar.length) { toast(yokMesaji, "", false); return; }

  // Tek ve zararsız bir değişiklik (port açma, güç verme) soru sormadan
  // gider — tabloya basıp beklemek gerekmesin. Riskli olan ya da birden
  // çok portu ilgilendiren her şey önce tek pencerede listelenir.
  const riskli = adimlar.some((a) => a.riskli);
  if ((riskli || adimlar.length > 1) && !(await onay({
        baslik: adimlar.length > 1 ? "Seçili portlara uygula" : "Onay",
        mesaj: (atlandi ? atlandi + "\n\n" : "") + onayMesaji(adimlar),
        onayMetni: adimlar.length > 1 ? "Uygula" : "Onayla",
        tehlike: riskli }))) {
    renderPorts();     // yarım kalan açılır kutuları asıl durumuna döndür
    return;
  }

  await islem(
    adimlar.length > 1 ? `${adimlar.length} değişiklik gönderiliyor…`
                       : adimlar[0].suruyor,
    () => api("/api/switch/batch", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ip: current,
        poe: Object.fromEntries(poeDegis),
        ports: Object.fromEntries(portDegis),
      }),
    }),
    adimlar.length > 1 ? adimlar.map((a) => a.gecmis) : adimlar[0].gecmis
  ).catch(() => {});
}

const setPoe = (port, mode) => uygulaSecim([port], { poe: mode });
const togglePort = (port, enable) => uygulaSecim([port], { port: enable });

// ------------------------------------------------- toplu gönderim ---------
function bekleyenSayi() {
  return bekleyenPoe.size + bekleyenPort.size;
}

const bekleyenAdimlar = () => adimlariKur(bekleyenPort, bekleyenPoe);

function batchBar() {
  const bar = $("#batchbar");
  bar.classList.toggle("hidden", mod !== "toplu");
  if (mod !== "toplu") return;
  const n = bekleyenSayi();
  bar.classList.toggle("bos", n === 0);
  $("#batch-send").disabled = n === 0;
  $("#batch-clear").disabled = n === 0;
  const liste = (m, ad) => (m.size ? `${ad}: ${kisaListe([...m.keys()])}` : "");
  $("#batch-info").textContent = n === 0
    ? "Toplu mod açık. Değişiklikleri yapın, sonra Gönder'e basın; " +
      "otomatik yenileme duraklatıldı."
    : `${n} değişiklik bekliyor — ` +
      [liste(bekleyenPort, "port"), liste(bekleyenPoe, "güç")]
        .filter(Boolean).join(", ") + ".";
}

function batchClear() {
  bekleyenPoe.clear();
  bekleyenPort.clear();
  renderPorts();
}

async function batchSend() {
  const n = bekleyenSayi();
  if (!n) return;

  // Her satır için ayrı soru sormak toplu gönderimin amacını bozar; bunun
  // yerine gönderilecek her şeyi tek pencerede madde madde gösteriyoruz.
  // Eskiden yalnızca riskli değişiklikler yazılıyordu, geri kalanı
  // görülmeden gidiyordu.
  const adimlar = bekleyenAdimlar();
  const riskli = adimlar.some((a) => a.riskli);
  if (!(await onay({
        baslik: "Toplu gönderim",
        mesaj: onayMesaji(adimlar),
        onayMetni: "Gönder", tehlike: riskli }))) return;

  const govde = {
    ip: current,
    poe: Object.fromEntries(bekleyenPoe),
    ports: Object.fromEntries(bekleyenPort),
  };
  await islem(`${n} değişiklik gönderiliyor…`, async () => {
    const r = await api("/api/switch/batch", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(govde),
    });
    bekleyenPoe.clear();     // yalnızca başarılıysa temizlenir
    bekleyenPort.clear();
    return r;
  }, adimlar.map((a) => a.gecmis)).catch(() => {});
}

async function setMod(yeni) {
  if (yeni === mod) return;
  if (mod === "toplu" && bekleyenSayi() &&
      !(await onay({
        baslik: "Bekleyen değişiklikler",
        mesaj: `${bekleyenSayi()} değişiklik gönderilmedi. ` +
               "Anında moda geçersen iptal olur.",
        onayMetni: "Yine de geç", tehlike: true }))) return;
  mod = yeni;
  batchClear();            // kuyruğu boşalt + yeniden çiz
  document.querySelectorAll(".mbtn").forEach(
    (b) => b.classList.toggle("active", b.dataset.mode === mod));
  if (mod === "anlik" && current) loadPorts().catch(() => {});
}

async function saveConfig() {
  if (busy) { toast("Önceki işlem sürüyor, bekleyin", "err"); return; }
  setBusy(true, "Yapılandırma kaydediliyor");
  try {
    await api("/api/switch/config-save", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ip: current }),
    });
    kayitDurumu(false);
    toast("Yapılandırma kaydedildi", "ok");
  } catch (e) {
    toast("Kayıt başarısız: " + e.message, "err");
  } finally { setBusy(false); }
}

// --------------------------------------------------------- ağ / güç -------
async function saveNet() {
  const addr = $("#n-addr").value.trim();
  const prefix = $("#n-prefix").value;
  if (!(await onay({
        baslik: "Yönetim IP'si değişecek",
        mesaj: `Switch'in adresi ${addr}/${prefix} olacak. ` +
               "Bağlantı kopar; yeni adresten tekrar tara ve Kaydet'e bas.",
        onayMetni: "IP'yi değiştir", tehlike: true }))) return;
  if (busy) { toast("Önceki işlem sürüyor, bekleyin", "err"); return; }
  setBusy(true, `IP ${addr} olarak ayarlanıyor…`);
  try {
    await api("/api/switch/network", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ip: current, addr, prefix, mtu: $("#n-mtu").value }),
    });
    toast(`IP değiştirildi → ${addr}. Yeni adresten tarayıp Kaydet'e basın, ` +
          `yoksa yeniden başlatmada eski adrese döner.`, "ok");
  } catch (e) {
    toast("Hata: " + e.message, "err");
  } finally { setBusy(false); }
}

async function doReboot() {
  if (!(await onay({
        baslik: "Switch yeniden başlatılacak",
        mesaj: "Tüm portlar geçici olarak kesilir." +
          (kayitBekliyor
            ? "\nKaydedilmemiş değişiklikler geri alınır."
            : ""),
        onayMetni: "Yeniden başlat", tehlike: true }))) return;
  if (busy) { toast("Önceki işlem sürüyor, bekleyin", "err"); return; }
  setBusy(true, "Switch yeniden başlatılıyor…");
  try {
    await api("/api/switch/reboot", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ip: current }),
    });
    kayitDurumu(false);        // yeniden başladıktan sonra kayıtlı hali gelir
    toast("Switch yeniden başlatılıyor…", "ok");
  } catch (e) {
    toast("Hata: " + e.message, "err");
  } finally { setBusy(false); }
}

// Fabrika ayarları: geri alınamaz. IP dahil her şey silinir, switch
// varsayılan adresine döner. İki aşamalı onay ister; backend de gövdede
// switch IP'sini onay olarak görmezse isteği reddeder.
async function doFactoryReset() {
  const hedef = current;
  if (!(await onay({
        baslik: "Fabrika ayarlarına dön",
        mesaj: `${hedef} fabrika ayarlarına dönecek.\n` +
               "IP dahil tüm yapılandırma silinir, switch varsayılan " +
               "adresine döner.\nBu işlem geri alınamaz.",
        onayMetni: "Devam", tehlike: true }))) return;

  // İkinci aşama: IP'yi elle yazdırmak, yanlışlıkla onaylamayı engeller
  if (!(await onay({
        baslik: "Sıfırlamayı doğrula",
        mesaj: "Emin olmak için switch'in IP adresini yaz.",
        girisEtiketi: hedef,
        beklenenDeger: hedef,
        onayMetni: "Fabrika ayarlarına dön", tehlike: true }))) {
    toast("Sıfırlama iptal edildi", "err");
    return;
  }

  if (busy) { toast("Önceki işlem sürüyor, bekleyin", "err"); return; }
  setBusy(true, "Fabrika ayarlarına döndürülüyor…");
  try {
    await api("/api/switch/factory-reset", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ip: current, confirm: current }),
    });
    toast("Switch fabrika ayarlarına döndürülüyor. " +
          "Açıldıktan sonra varsayılan adresinden tarayın.", "ok");
    $("#detail").classList.add("hidden");   // artık bu adreste değil
    current = null;
  } catch (e) {
    toast("Hata: " + e.message, "err");
  } finally { setBusy(false); }
}

// ═══════════════════════════════════════════ ön panel M12 haritası ════════
// Cihazın ön yüzündeki konnektör dizilimi. Tablodan bağımsız değil —
// ikisi de renderPorts()'taki aynı `ports` dizisinden çizilir, o yüzden
// asla birbirinden ayrı düşmezler.
//
// Yerleşim: 4 satır. PoE portları sütun sütun, aşağıdan yukarı numaralı
// (1-2-3-4 | 5-6-7-8 …). Sağdaki uplink sütunu yukarıdan aşağı (28…25).
const SERVIS = ["Alarm", "USB", "CON", "EX-PWR"];

// ───────────────────────────────────────────────── port seçimi ────────────
// Dosya yöneticilerindeki seçim davranışının aynısı: düz tık tek portu
// seçer, ⌘/Ctrl + tık seçime ekler/çıkarır, Shift + tık aralık seçer.
// Seçim hem ön panel haritasında hem tablolarda aynı kümedir; sağ tık
// menüsü de seçili portların tamamına iş yapar.
const secili = new Set();
let secimCapa = null;        // Shift ile aralık seçerken çıpa alınan port

// macOS'ta Ctrl + tık işletim sistemi tarafından sağ tık sayılıyor; orada
// çoklu seçim tuşu Command. Diğer platformlarda Ctrl.
const MAC = /Mac|iPhone|iPad|iPod/.test(
  navigator.platform || navigator.userAgent || "");
const COKLAMA_ADI = MAC ? "⌘" : "Ctrl";
const coklamaTusu = (e) => (MAC ? e.metaKey : e.ctrlKey || e.metaKey);

// Aralık seçimi tablolardaki sırayı izler: önce PoE portları, sonra uplink.
function secimSirasi() {
  return ports.filter((p) => p.poe).map((p) => p.pid)
    .concat(ports.filter((p) => !p.poe).map((p) => p.pid));
}

function portTikla(pid, e) {
  const sira = secimSirasi();
  if (e.shiftKey && secimCapa !== null && sira.includes(secimCapa)) {
    const a = sira.indexOf(secimCapa);
    const b = sira.indexOf(pid);
    if (b >= 0) {
      if (!coklamaTusu(e)) secili.clear();
      sira.slice(Math.min(a, b), Math.max(a, b) + 1)
        .forEach((x) => secili.add(x));
    }
  } else if (coklamaTusu(e)) {
    if (secili.has(pid)) secili.delete(pid); else secili.add(pid);
    secimCapa = pid;
  } else {
    // Tek başına seçili porta tekrar tıklamak seçimi bırakır
    const tekBasina = secili.size === 1 && secili.has(pid);
    secili.clear();
    if (!tekBasina) secili.add(pid);
    secimCapa = tekBasina ? null : pid;
  }
  boyaSecim();
}

// Sağ tık: tıklanan port seçimin içindeyse menü tüm seçime uygulanır,
// dışındaysa seçim önce o porta iner.
function portSagTik(pid, e) {
  e.preventDefault();
  if (!secili.has(pid)) {
    secili.clear();
    secili.add(pid);
    secimCapa = pid;
    boyaSecim();
  }
  portMenusu([...secili].sort((a, b) => a - b), e);
}

function secimTemizle() {
  secili.clear();
  secimCapa = null;
  boyaSecim();
}

const pinHalka = (n, r) => Array.from({ length: n }, (_, i) => {
  const a = (i / n) * Math.PI * 2 - Math.PI / 2;
  return [20 + r * Math.cos(a), 20 + r * Math.sin(a)];
});

function durumSinifi(p) {
  if (p.bekliyor) return "pend";
  // Port kapalıysa (veri yok) kırmızı. PoE'nin kapalı olması portu
  // kapatmaz — o durum ayrıca "gucsuz" işaretiyle gösteriliyor.
  let sinif = !portAcik(p) ? "off"
    : portBesliyor(p) ? "feed"
      : p.linkStat === "up" ? "link" : "";
  if (p.poe && portAcik(p) && !gucAcik(p)) sinif += " gucsuz";
  return sinif.trim();
}

function portEtiketi(p) {
  return p.poe ? (POE_AD[p.poeMode] || "") : (p.adminStat ? "Açık" : "Kapalı");
}

// Konnektörün çizimi. Ayrı bir işlev çünkü gösterim kılavuzu da örnekleri
// buradan çiziyor: biçim ya da renk değişirse kılavuz kendiliğinden aynı
// değişir, elle güncellenmesi gereken ikinci bir çizim yok.
//   PoE portu    — 4 pin
//   Uplink portu — 8 pin + ortada çarpı
function konnektorSvg(p) {
  const pinler = p.poe ? pinHalka(4, 6.6) : pinHalka(8, 7.2);
  const r = p.poe ? 2.5 : 1.9;
  return `<svg viewBox="0 0 40 40" aria-hidden="true">` +
    `<circle class="shell" cx="20" cy="20" r="18.4"></circle>` +
    `<circle class="inner" cx="20" cy="20" r="12.2"></circle>` +
    (p.poe ? "" : `<path class="cross" d="M13 13 L27 27 M27 13 L13 27"></path>`) +
    `<rect class="key" x="18.6" y="1.6" width="2.8" height="4.2"></rect>` +
    pinler.map(([x, y]) =>
      `<circle class="pin" cx="${x.toFixed(2)}" cy="${y.toFixed(2)}" r="${r}"></circle>`)
      .join("") +
    `</svg>`;
}

function konnektor(p) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "m12 " + durumSinifi(p);
  b.dataset.pid = p.pid;
  b.title = `Port ${p.pid} / ${portEtiketi(p)} / ` +
            `${p.linkStat === "up" ? "bağlı" : "boş"}` +
            (p.powerW ? ` / ${p.powerW} W` : "");
  b.innerHTML = konnektorSvg(p) + `<span>${p.pid}</span>`;
  b.onclick = (e) => portTikla(p.pid, e);
  b.oncontextmenu = (e) => portSagTik(p.pid, e);
  return b;
}

function servisHucresi(ad) {
  const d = document.createElement("div");
  d.className = "pm-svc";
  d.innerHTML = `<svg viewBox="0 0 40 40" aria-hidden="true">` +
    `<circle cx="20" cy="20" r="16.5" stroke-width="1.2" stroke-dasharray="3 3"></circle>` +
    `<circle cx="20" cy="20" r="8" stroke-width="1"></circle></svg><span>${ad}</span>`;
  return d;
}

function bosHucre(sinif) {
  const d = document.createElement("div");
  if (sinif) d.className = sinif;
  return d;
}

function panelHaritasi(fe, ge) {
  const harita = $("#panelmap");
  if (!harita) return;
  harita.classList.toggle("hidden", fe.length + ge.length === 0);

  // Menü açıkken kapatmıyoruz: yeni veri geldiğinde içeriği yerinde
  // güncelleniyor. (Eskiden her yenileme menüyü elin altından kapatıyordu.)
  if (menuAcik && menuTazeleFn) {
    if (menuHedefler.some((pid) => ports.some((x) => x.pid === pid)))
      menuTazeleFn();
    else menuKapat();       // portlar listeden düştüyse menünün anlamı kalmaz
  }

  const grid = $("#pm-grid");
  grid.innerHTML = "";
  const sutun = Math.max(1, Math.ceil(fe.length / 4));
  grid.style.gridTemplateColumns =
    `66px repeat(${sutun}, minmax(0, 1fr)) 14px minmax(0, 1fr)`;

  const idIle = {};
  fe.concat(ge).forEach((p) => { idIle[p.pid] = p; });

  for (let satir = 4; satir >= 1; satir--) {
    grid.appendChild(servisHucresi(SERVIS[4 - satir]));
    for (let c = 0; c < sutun; c++) {
      const p = idIle[satir + c * 4];
      grid.appendChild(p ? konnektor(p) : bosHucre());
    }
    grid.appendChild(bosHucre("pm-div"));
    const u = ge[satir - 1];
    grid.appendChild(u ? konnektor(u) : bosHucre());
  }
}

function boyaSecim() {
  // Yalnızca haritadaki konnektörler: kılavuzdaki örnekler de ".m12"
  // sınıfını kullanıyor ama onların bir port numarası yok.
  document.querySelectorAll("#pm-grid .m12").forEach((el) =>
    el.classList.toggle("sel", secili.has(+el.dataset.pid)));
  document.querySelectorAll("#fe-ports tbody tr, #ge-ports tbody tr")
    .forEach((tr) => tr.classList.toggle("sel", secili.has(+tr.dataset.pid)));
  secimSeridi();
}

// Seçim şeridi: seçim yokken ne yapılabileceğini anlatır, seçim varken
// kaç portun seçili olduğunu ve toplu işlem düğmelerini gösterir. Sağ tık
// menüsü tek yol olsaydı özelliğin varlığı fark edilmezdi.
function secimSeridi() {
  const bar = $("#selbar");
  if (!bar) return;
  const n = secili.size;
  bar.classList.toggle("bos", n === 0);
  $("#sel-menu").disabled = n === 0;
  $("#sel-clear").disabled = n === 0;
  $("#sel-info").textContent = n === 0
    ? `Çoklu seçim: ${COKLAMA_ADI} + tık ile port ekle, Shift + tık ile ` +
      "aralık seç. Sağ tık seçili portların hepsine birden uygular."
    : `${n} port seçili — ${kisaListe(secili)}`;
}

// ───────────────────────────────────── ön panel gösterim kılavuzu ─────────
// Kullanıcının "bu kırmızı ne demekti?" sorusunun tek yanıt yeri.
//
// Örnekler uydurma resimler değil: her satırda gerçek bir port nesnesi var
// ve tıpkı haritadaki gibi durumSinifi() + konnektorSvg() ile çiziliyor.
// Yani kılavuz, kodun kendisinin ürettiği görüntüyü gösterir; renk kuralı
// değişirse buradaki örnek de değişir, ikisi asla ayrı düşmez.
//
// Bir portun iki bağımsız anahtarı olduğu için (veri = adminStat,
// güç = poeMode) PoE portunda altı ayrı görünüm çıkıyor; hepsi burada.
const KILAVUZ = [
  {
    baslik: "PoE portları",
    aciklama: "Dört pinli konnektör. Hem veri hem güç taşır; ikisi " +
              "birbirinden bağımsız açılıp kapatılır — yalnızca gücü " +
              "kesmek de, yalnızca veriyi kesmek de mümkün.",
    satirlar: [
      { ad: "Cihazı besliyor",
        not: "Port açık, güç açık, karşıdaki cihaz akım çekiyor. " +
             "Tüketim tabloda watt olarak görünür.",
        p: { poe: true, adminStat: true, linkStat: "up",
             poeMode: "2", powerW: 6.4 } },
      { ad: "Bağlı, güç çekmiyor",
        not: "Veri geçiyor ve güç verilmeye hazır, ama cihaz PoE " +
             "kullanmıyor — kendi elektriğiyle çalışıyor olabilir.",
        p: { poe: true, adminStat: true, linkStat: "up",
             poeMode: "2", powerW: null } },
      { ad: "Bağlı, PoE kapalı",
        not: "Kabuk bağlantıyı gösterir, kırmızı pinler gücün kapalı " +
             "olduğunu. Cihaz haberleşir ama beslenmez.",
        p: { poe: true, adminStat: true, linkStat: "up",
             poeMode: "0", powerW: null } },
      { ad: "Boş",
        not: "Port açık ve güç açık, ama karşısında cihaz yok.",
        p: { poe: true, adminStat: true, linkStat: "down",
             poeMode: "2", powerW: null } },
      { ad: "Boş, PoE kapalı",
        not: "Karşısında cihaz yok, ayrıca gücü de kapatılmış.",
        p: { poe: true, adminStat: true, linkStat: "down",
             poeMode: "0", powerW: null } },
      { ad: "Port kapalı",
        not: "Veri iletimi kapatılmış; konnektörün tamamı kırmızıdır. " +
             "Güç ayarı ayrı tutulur — portu açtığınızda PoE eskiden " +
             "neyse odur.",
        p: { poe: true, adminStat: false, linkStat: "down",
             poeMode: "0", powerW: null } },
      { ad: "Bekleyen değişiklik",
        not: "Yalnızca Toplu modda görülür: seçim yapıldı ama henüz " +
             "switch'e gönderilmedi. Gönder'e basınca gerçek rengine döner.",
        p: { poe: true, adminStat: true, linkStat: "up",
             poeMode: "2", powerW: 6.4, bekliyor: true } },
    ],
  },
  {
    baslik: "Uplink portları",
    aciklama: "Sekiz pinli, ortası çarpılı konnektör. Yalnızca veri taşır; " +
              "PoE beslemesi yoktur, bu yüzden güç durumu da gösterilmez.",
    satirlar: [
      { ad: "Bağlı",
        not: "Karşıda bir cihaz var ve veri geçiyor.",
        p: { poe: false, adminStat: true, linkStat: "up", powerW: null } },
      { ad: "Boş",
        not: "Port açık, ama karşısında cihaz yok.",
        p: { poe: false, adminStat: true, linkStat: "down", powerW: null } },
      { ad: "Port kapalı",
        not: "Veri iletimi kapatılmış. Yönetime bu porttan bağlıysanız " +
             "kapatmak switch'e erişimi keser.",
        p: { poe: false, adminStat: false, linkStat: "down", powerW: null } },
      { ad: "Bekleyen değişiklik",
        not: "Toplu modda gönderilmeyi bekleyen seçim.",
        p: { poe: false, adminStat: true, linkStat: "up", powerW: null,
             bekliyor: true } },
    ],
  },
];

function kilavuzCiz() {
  const govde = $("#legend-body");
  if (!govde || govde.dataset.hazir) return;   // içerik sabit, bir kez çizilir
  govde.innerHTML = "";
  KILAVUZ.forEach((grup) => {
    const bolum = document.createElement("div");
    bolum.className = "lg-grup";
    bolum.innerHTML = `<h4></h4><p class="lg-not"></p><div class="lg-liste"></div>`;
    bolum.querySelector("h4").textContent = grup.baslik;
    bolum.querySelector(".lg-not").textContent = grup.aciklama;
    const liste = bolum.querySelector(".lg-liste");
    grup.satirlar.forEach((s) => {
      const satir = document.createElement("div");
      satir.className = "lg-row";
      const ornek = document.createElement("div");
      // Haritadakiyle birebir aynı sınıf ve aynı çizim — "ornek" yalnızca
      // tıklanamaz/küçük olmasını sağlar.
      ornek.className = "m12 ornek " + durumSinifi(s.p);
      ornek.innerHTML = konnektorSvg(s.p);
      satir.appendChild(ornek);
      const metin = document.createElement("div");
      metin.className = "lg-metin";
      metin.innerHTML = `<b></b><span></span>`;
      metin.querySelector("b").textContent = s.ad;
      metin.querySelector("span").textContent = s.not;
      satir.appendChild(metin);
      liste.appendChild(satir);
    });
    govde.appendChild(bolum);
  });

  // Renkten bağımsız, ayrıca bilinmesi gereken tek işaret
  const ek = document.createElement("div");
  ek.className = "lg-grup";
  ek.innerHTML =
    `<h4>Seçim ve sağ tık</h4>` +
    `<p class="lg-not">Bir konnektöre (ya da tablo satırına) tıklayınca ` +
    `mavi çerçeveyle işaretlenir ve karşılık gelen tablo satırı da ` +
    `vurgulanır. <b>${COKLAMA_ADI} + tık</b> seçime port ekler ya da ` +
    `çıkarır, <b>Shift + tık</b> aralık seçer — dosya seçer gibi. ` +
    `<b>Sağ tık</b> açılan pencerede güç (PoE) ve port durumu ayrı ayrı ` +
    `seçilir; Uygula seçili portların hepsine birden gider.</p>`;
  govde.appendChild(ek);
  govde.dataset.hazir = "1";
}

function kilavuzAc() {
  kilavuzCiz();
  $("#legend").classList.remove("hidden");
  setTimeout(() => $("#legend-close").focus(), 30);
}

function kilavuzKapat() {
  $("#legend").classList.add("hidden");
}

// ------------------------------------------------ sağ tık işlem menüsü ----
// Menü tek bir porta değil, seçili portların tamamına iş yapar. İçinde iki
// bağımsız bölüm var:
//
//   Güç (PoE)          — Değiştirme / Kapalı / PoE / PoE+
//   Port durumu (veri) — Değiştirme / Port açık / Port kapalı
//
// İkisi ayrı seçilir: yalnızca gücü kapatmak, yalnızca portu açmak ya da
// ikisini birden ayarlamak mümkün. "Değiştirme" bırakılan bölüme hiç
// dokunulmaz. Uygula'ya basılınca hepsi tek istekten geçer (uygulaSecim),
// yani onay soruları, anında/toplu modu ve yenileme akışı tabloyla birebir
// aynı yoldur.
let menuEl = null;
let menuAcik = false;
let menuHedefler = [];     // menü hangi portlar için açık
let menuTazeleFn = null;   // yeni veri gelince menüyü yerinde günceller

function menuKapat() {
  menuAcik = false;
  menuHedefler = [];
  menuTazeleFn = null;
  if (menuEl) { menuEl.remove(); menuEl = null; }
  document.removeEventListener("mousedown", menuDisari, true);
  document.removeEventListener("keydown", menuTus, true);
}
function menuDisari(e) { if (menuEl && !menuEl.contains(e.target)) menuKapat(); }
function menuTus(e) {
  if (e.key !== "Escape" || !menuAcik) return;
  // Escape yalnızca menüyü kapatsın; seçimi bırakmak ikinci bir Escape.
  e.stopPropagation();
  menuKapat();
}

function menuSatiri(etiket) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "pm-item";
  b.innerHTML = `<i class="mark"></i><span class="lbl"></span>` +
                `<span class="now"></span>`;
  b.querySelector(".lbl").textContent = etiket;
  return b;
}

function portMenusu(pidler, e) {
  menuKapat();
  const hedefler = pidler.filter((pid) => ports.some((x) => x.pid === pid));
  if (!hedefler.length) return;
  const cok = hedefler.length > 1;

  const m = document.createElement("div");
  m.className = "pm-menu";

  const bas = document.createElement("div");
  bas.className = "pm-menu-head";
  bas.innerHTML = `<div class="t"></div><div class="s"></div>`;
  bas.querySelector(".t").textContent =
    cok ? `${hedefler.length} port seçili` : "Port " + hedefler[0];
  m.appendChild(bas);

  // Menü açıkken veriler yenilenebilir; her yerde canlı listeye bakıyoruz.
  const canli = () => hedefler.map((pid) => ports.find((x) => x.pid === pid))
    .filter(Boolean);

  const ozet = () => {
    const liste = canli();
    if (liste.length === 1) {
      const x = liste[0];
      return (x.poe ? "PoE / " : "Uplink / ") + portEtiketi(x) +
        " / " + (x.linkStat === "up" ? "bağlı" : "boş") +
        (x.powerW ? ` / ${x.powerW} W` : "");
    }
    const poeN = liste.filter((x) => x.poe).length;
    const bagli = liste.filter((x) => x.linkStat === "up").length;
    return `Port ${kisaListe(hedefler)}\n${poeN} PoE / ` +
           `${liste.length - poeN} uplink · ${bagli} bağlı`;
  };

  const baslik = (t) => {
    const d = document.createElement("div");
    d.className = "pm-kicker"; d.textContent = t; m.appendChild(d);
  };

  // Seçilen hedef durumlar. null = o bölüme dokunma.
  let poeSecim = null;
  let portSecim = null;
  const satirlar = [];   // { el, grup, deger, kapsam(x), durumda(x) }

  const ekle = (grup, deger, etiket, kapsam, durumda) => {
    const el = menuSatiri(etiket);
    el.onclick = () => {
      if (grup === "poe") poeSecim = deger; else portSecim = deger;
      secimiCiz();
    };
    satirlar.push({ el, grup, deger, kapsam, durumda });
    m.appendChild(el);
    return el;
  };

  // Güç bölümü yalnızca seçimde en az bir PoE portu varsa anlamlı
  if (canli().some((x) => x.poe)) {
    baslik("Güç (PoE)");
    ekle("poe", null, "Değiştirme", () => true, () => false);
    ["0", "1", "2"].forEach((mode) => ekle(
      "poe", mode, POE_AD[mode],
      (x) => Boolean(x.poe), (x) => String(x.poeMode) === mode));
  }

  baslik("Port durumu (veri)");
  ekle("port", null, "Değiştirme", () => true, () => false);
  ekle("port", true, "Port açık", () => true, (x) => Boolean(x.adminStat));
  ekle("port", false, "Port kapalı", () => true, (x) => !x.adminStat);

  const not = document.createElement("div");
  not.className = "pm-not";
  not.textContent = "Güç ve port durumu ayrı ayrı seçilir; " +
                    "dokunulmasını istemediğin bölümü Değiştirme'de bırak.";
  m.appendChild(not);

  const alt = document.createElement("div");
  alt.className = "pm-foot";
  const vazgec = document.createElement("button");
  vazgec.type = "button";
  vazgec.className = "ghost sm";
  vazgec.textContent = "Vazgeç";
  vazgec.onclick = menuKapat;
  const uygula = document.createElement("button");
  uygula.type = "button";
  uygula.className = "ok sm";
  uygula.textContent = cok ? `Uygula (${hedefler.length})` : "Uygula";
  uygula.onclick = () => {
    const secim = { poe: poeSecim, port: portSecim };
    menuKapat();
    uygulaSecim(hedefler, secim);
  };
  alt.appendChild(vazgec);
  alt.appendChild(uygula);
  m.appendChild(alt);

  // Hangi satırın seçildiği (uygulanacak olan) — sol işaretten okunur.
  function secimiCiz() {
    satirlar.forEach((s) => {
      const secildi = (s.grup === "poe" ? poeSecim : portSecim) === s.deger;
      s.el.classList.toggle("pick", secildi);
    });
    uygula.disabled = poeSecim === null && portSecim === null;
  }

  // Portların o anki durumu — sağdaki küçük yazıdan okunur. Çoklu seçimde
  // "şu an" yerine "3/8" gibi bir oran çıkar: seçimin bir kısmı zaten o
  // durumdaysa bu görünür olsun.
  function durumuCiz() {
    const liste = canli();
    bas.querySelector(".s").textContent = ozet();
    satirlar.forEach((s) => {
      const et = s.el.querySelector(".now");
      if (s.deger === null) { et.textContent = ""; return; }
      const ilgili = liste.filter(s.kapsam);
      const uyan = ilgili.filter(s.durumda).length;
      const tam = ilgili.length > 0 && uyan === ilgili.length;
      et.textContent = !uyan ? "" : tam ? "şu an" : `${uyan}/${ilgili.length}`;
      et.classList.toggle("tam", tam);
      // Zaten o durumda olmayan portlar varsa işlem yıkıcı olabilir
      s.el.classList.toggle("danger",
        (s.deger === "0" || s.deger === false) && uyan < ilgili.length);
    });
  }

  const tazele = () => { durumuCiz(); secimiCiz(); };
  tazele();

  document.body.appendChild(m);
  m.style.left =
    Math.max(8, Math.min(e.clientX, innerWidth - m.offsetWidth - 8)) + "px";
  m.style.top =
    Math.max(8, Math.min(e.clientY, innerHeight - m.offsetHeight - 8)) + "px";
  menuEl = m;
  menuAcik = true;
  menuHedefler = hedefler;
  menuTazeleFn = tazele;
  setTimeout(() => {
    document.addEventListener("mousedown", menuDisari, true);
    document.addEventListener("keydown", menuTus, true);
  }, 0);
}

// ═══════════════════════════════════════════════ işlem geçmişi ════════════
// Oturum boyunca tutulur, diske yazılmaz. Kaynağı toast(): kullanıcıya
// gösterilen her bildirim buraya da düşer.
const gecmis = [];
const TUR = [
  [/fabrika|sıfırla/i, "hata"],
  [/hata|başarısız|kaydedilemedi|iptal/i, "hata"],
  [/ip .*(değiştir|ayarla)/i, "ag"],
  [/gü[çc]|poe/i, "poe"],          // "güç" çekimlenince "gücü" oluyor
  [/port \d+ (açıldı|kapatıldı|açılıyor|kapatılıyor)/i, "port"],
  [/kaydedildi|yapılandırma/i, "kayit"],
  [/tara|bulundu/i, "tara"],
];

// Ekranda görünen etiketler. Sınıf adları ASCII (CSS'te kullanılıyor) ama
// etiket Türkçe yazılmalı: sayfa dili tr olduğu için text-transform büyütmeyi
// Türkçe kurallarına göre yapıyor ve "kayit" → "KAYİT" çıkıyordu.
// Doğru kelime "kayıt", büyüğü "KAYIT".
const TUR_ETIKET = { kayit: "kayıt", ag: "ağ" };

function turBul(msg, hatali) {
  if (hatali) return "hata";
  for (const [re, t] of TUR) if (re.test(msg)) return t;
  return "bilgi";
}

function saatMetni() {
  const d = new Date();
  return [d.getHours(), d.getMinutes(), d.getSeconds()]
    .map((x) => String(x).padStart(2, "0")).join(":");
}

function logEkle(msg, hatali) {
  if (!msg) return;
  gecmis.push({ t: saatMetni(), tur: turBul(msg, hatali), msg,
                ip: current || "—" });
  logCiz();
  // Alt barda saat:dakika yeter; saniye yalnızca işlem geçmişi listesinde.
  $("#last-log").textContent =
    `${gecmis[gecmis.length - 1].t.slice(0, 5)}  ${msg}`;
}

function logCiz() {
  const govde = $("#lp-body");
  if (!govde) return;
  $("#lp-count").textContent = `${gecmis.length} kayıt · oturum`;
  if (!gecmis.length) {
    govde.innerHTML = `<div class="logempty">Bu oturumda henüz işlem yok.</div>`;
    return;
  }
  govde.innerHTML = "";
  gecmis.slice().reverse().forEach((l) => {
    const r = document.createElement("div");
    r.className = "logrow";
    r.innerHTML = `<span class="t"></span><span class="k"></span>` +
                  `<span class="m"></span><span class="ip"></span>`;
    r.querySelector(".t").textContent = l.t;
    const k = r.querySelector(".k");
    k.className = "k " + l.tur;
    k.textContent = TUR_ETIKET[l.tur] || l.tur;
    r.querySelector(".m").textContent = l.msg;   // metin olarak, HTML değil
    r.querySelector(".ip").textContent = l.ip;
    govde.appendChild(r);
  });
}

// --------------------------------------------------------- bağlama --------
// Aynı düğme iki iş yapıyor: tarama yokken başlatır, sürerken iptal eder.
$("#scan").onclick = () => (scanning ? scanIptal() : scan());
$("#cidr").addEventListener("keydown", (e) => e.key === "Enter" && scan());
$("#save-net").onclick = saveNet;
$("#reboot").onclick = doReboot;
$("#save-cfg").onclick = saveConfig;
$("#factory").onclick = doFactoryReset;
$("#batch-send").onclick = batchSend;
$("#batch-clear").onclick = batchClear;
$("#sel-clear").onclick = secimTemizle;
// Sağ tıkla aynı menü. Faresi olmayan ya da sağ tıkı bilmeyen kullanıcı
// için ikinci yol; menü düğmenin altına açılır.
$("#sel-menu").onclick = () => {
  if (!secili.size) return;
  const r = $("#sel-menu").getBoundingClientRect();
  portMenusu([...secili].sort((a, b) => a - b),
             { clientX: r.left, clientY: r.bottom + 4 });
};
document.querySelectorAll(".mbtn").forEach((b) => {
  b.onclick = () => setMod(b.dataset.mode);
});
$("#login-form").onsubmit = girisGonder;
$("#login-cancel").onclick = girisIptal;
$("#dialog-form").onsubmit = onayGonder;
$("#dialog-cancel").onclick = () => onayKapat(false);
// Sağ üstteki çarpı: "Vazgeç" ile aynı sonuç, yalnızca daha kısa yol
$("#dialog-close").onclick = () => onayKapat(false);
$("#pm-info").onclick = kilavuzAc;
$("#legend-close").onclick = kilavuzKapat;
// Perdenin boşluğuna tıklamak da kapatsın — kılavuz yalnızca okunan bir
// pencere, kapatmak için kutunun içine nişan almak gerekmesin.
$("#legend").onclick = (e) => { if (e.target.id === "legend") kilavuzKapat(); };
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  // Üstteki pencere kapanır: onay, giriş penceresinin üstünde açılabiliyor
  if (onayBekleyen) onayKapat(false);
  else if (girisBekleyen) girisIptal();
  else if (!$("#legend").classList.contains("hidden")) kilavuzKapat();
  else if (secili.size) secimTemizle();
});

// ⌘/Ctrl + A — görünen portların hepsini seç (dosya listesindeki gibi).
// Yazı alanındayken tarayıcının kendi "tümünü seç"i çalışmaya devam eder.
document.addEventListener("keydown", (e) => {
  if (e.key !== "a" && e.key !== "A") return;
  if (!coklamaTusu(e) || e.shiftKey || e.altKey) return;
  if (onayBekleyen || girisBekleyen || !current) return;
  if ($("#detail").classList.contains("hidden")) return;
  if ($("#tab-ports").classList.contains("hidden")) return;
  const odak = document.activeElement;
  if (odak && /^(INPUT|TEXTAREA|SELECT)$/.test(odak.tagName)) return;
  e.preventDefault();
  secimSirasi().forEach((pid) => secili.add(pid));
  secimCapa = null;
  boyaSecim();
});
secimSeridi();     // şerit açılışta da ipucu metnini göstersin
$("#log-clear").onclick = () => { gecmis.length = 0; logCiz(); };
$("#log-toggle").onclick = () =>
  document.querySelector('.tab[data-tab="log"]').click();
logCiz();

// alt bardaki sürüm bilgisi (backend'den, tek kaynak)
api("/api/version")
  .then((v) => ($("#app-ver").textContent = "v" + v.version))
  .catch(() => ($("#app-ver").textContent = ""));

// sol panel gizle/göster
$("#side-toggle").onclick = () => {
  const kapali = $("#side").classList.toggle("collapsed");
  $("#side-toggle").classList.toggle("on", kapali);
};

// --------------------------------------------------- otomatik yenileme ----
const RING_C = 2 * Math.PI * 11;   // r=11 çevresi

function tickRefresh() {
  const svg = $("#ring");
  if (!svg) return;
  const arc = svg.querySelector(".rfg");
  const num = svg.querySelector(".rnum");

  if (mod === "toplu") {                 // yenileme duraklatıldı
    // Duraklatma işareti SVG'de çizili; "‖" karakteri yazı tipine göre
    // uzayıp halkanın dışına taşıyordu.
    svg.className.baseVal = "ring paused";
    num.textContent = "";
    arc.style.strokeDashoffset = RING_C;
    svg.setAttribute("title", "Toplu modda otomatik yenileme duraklatıldı");
    return;
  }
  if (lastErr) {
    svg.className.baseVal = "ring err";
    num.textContent = "!";
    arc.style.strokeDashoffset = 0;
    svg.setAttribute("title", "Yenilenemedi: " + lastErr);
    return;
  }
  if (!lastOk) {
    svg.className.baseVal = "ring";
    num.textContent = "–";
    arc.style.strokeDashoffset = RING_C;
    return;
  }

  const sn = Math.floor((Date.now() - lastOk) / 1000);
  num.textContent = sn < 100 ? sn : "99+";
  // halka 5 sn'lik yenileme aralığı boyunca dolar
  const oran = Math.min(sn / 5, 1);
  arc.style.strokeDasharray = RING_C;
  arc.style.strokeDashoffset = RING_C * (1 - oran);
  svg.className.baseVal = "ring" + (sn > 15 ? " stale" : "");
  svg.setAttribute("title", `${sn} saniye önce güncellendi`);
}
setInterval(tickRefresh, 1000);

// Otomatik yenileme yalnızca "Anında" modda çalışır. Toplu modda tablo
// bekleyen değişiklikleri gösterdiği için altından çekilmemeli.
function startAuto() {
  clearInterval(timer);
  timer = setInterval(async () => {
    if (!current || busy || mod !== "anlik") return;
    if (girisBekleyen || kimlikIptal) return;   // şifre sorulurken bekle
    if (document.querySelector("select.poe:focus")) return;  // menü açıkken bekle
    try { await loadPorts(); } catch (e) { /* gösterge zaten uyarıyor */ }
  }, 5000);
}
startAuto();

// Sekmeler: her ".tab" kendi "#tab-<ad>" panelini açar. Sekme eklemek için
// HTML'e bir düğme + bir panel koymak yeterli, buraya dokunmaya gerek yok.
document.querySelectorAll(".tab").forEach((t) => {
  t.onclick = () => {
    document.querySelectorAll(".tab").forEach(
      (x) => x.classList.toggle("active", x === t));
    document.querySelectorAll("#detail .panel").forEach(
      (p) => p.classList.toggle("hidden", p.id !== "tab-" + t.dataset.tab));
  };
});

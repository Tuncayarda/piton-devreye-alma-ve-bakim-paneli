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

function toast(msg, kind = "") {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "show " + kind;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.className = ""), kind === "err" ? 6000 : 4000);
  logEkle(msg, kind === "err");     // her bildirim geçmişe de düşer
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
async function islem(bekletMsg, istek, basariMsg) {
  if (busy) { toast("Önceki işlem sürüyor, bekleyin", "err"); return; }
  setBusy(true, bekletMsg);
  try {
    const res = await istek();
    setBusy(true, "Durum doğrulanıyor…");
    await loadPorts();
    // Uygulandı ama flash'a yazılmadı; kalıcı olması için Kaydet gerekli
    kayitDurumu(true);
    toast(basariMsg || "İşlem tamamlandı", "ok");
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
// görünüyordu. Artık tarama sürerken buton kilitli: içinde dönen bir
// gösterge var, bitince eski haline dönüyor.
let scanning = false;
const SCAN_TIMEOUT = 120000;   // hiçbir koşulda kilitli kalmasın

function setScanning(on) {
  scanning = on;
  const b = $("#scan");
  b.disabled = on;
  b.classList.toggle("loading", on);
  b.innerHTML = on ? '<span class="btn-spin"></span>Taranıyor' : "Tara";
}

async function scan() {
  if (scanning) return;
  const cidr = $("#cidr").value.trim();
  setScanning(true);
  $("#list").innerHTML = "";      // durum yalnızca butonda görünür

  const iptal = new AbortController();
  const zaman = setTimeout(() => iptal.abort(), SCAN_TIMEOUT);
  try {
    const res = await api("/api/discover?cidr=" + encodeURIComponent(cidr),
                          { signal: iptal.signal });
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
        : `<div class="mdl">${s.model || "Switch"} · v${s.version || "?"}</div>`);
      el.onclick = () => select(s.ip, el);
      $("#list").appendChild(el);
    });
  } catch (e) {
    const msg = e.name === "AbortError"
      ? "Tarama çok uzun sürdü, iptal edildi. Tek IP ile deneyin."
      : "Hata: " + e.message;
    $("#list").innerHTML = `<div class="muted">${msg}</div>`;
  } finally {
    clearTimeout(zaman);
    setScanning(false);
  }
}

async function select(ip, el) {
  if (mod === "toplu" && bekleyenSayi() && ip !== current &&
      !confirm(`${bekleyenSayi()} bekleyen değişiklik var. Başka switch'e ` +
               `geçersen gönderilmeden iptal olur. Devam?`)) return;
  current = ip;
  kimlikIptal = false;
  hamPorts = [];
  bekleyenPoe.clear();
  bekleyenPort.clear();
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
  $("#d-name").textContent = info.name || "Switch";
  // Boş alanlar için "· ip · v?" gibi yarım satır çıkmasın: yalnızca
  // cihazın gerçekten bildirdiklerini yan yana diziyoruz.
  $("#d-sub").textContent = [
    info.model,
    info.ip || current,
    info.version ? "v" + info.version : "",
  ].filter(Boolean).join(" · ");
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
function portAcik(p) {
  return p.poe ? p.poeMode !== "0" : Boolean(p.adminStat);
}

function portBesliyor(p) {
  return Boolean(p.poe && p.linkStat === "up" && p.powerW);
}

// Bağlantı sütunundaki kare:
//   yeşil — besliyor · mavi — bağlı ama güç çekmiyor
//   kırmızı — kapatılmış · gri — açık ama karşısında cihaz yok
function nokta(p) {
  if (portBesliyor(p)) return "up";
  if (p.linkStat === "up") return "data";
  if (!portAcik(p)) return "off";
  return "down";
}

function uplinkPids() {
  // link'i up olan portları uplink adayı say (kapatma uyarısı için)
  return ports.filter((p) => p.linkStat === "up").map((p) => p.pid);
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
  const up = ports.filter((p) => p.linkStat === "up").length;
  const feeding = ports.filter((p) => p.powerW).length;
  const poeOff = ports.filter((p) => p.poe && p.poeMode === "0").length;
  const geOff = ports.filter((p) => !p.poe && !p.adminStat).length;
  $("#port-info").textContent =
    `${ports.length} port · ${up} bağlı · ${feeding} besleniyor` +
    (poeOff ? ` · ${poeOff} güç kapalı` : "") +
    (geOff ? ` · ${geOff} uplink kapalı` : "");

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

  // --- PoE portları: kontrol yalnızca güç menüsünden
  const fe = ports.filter((p) => p.poe);
  const feBody = $("#fe-ports tbody");
  feBody.innerHTML = "";
  $("#fe-cnt").textContent = `${fe.length} port`;
  fe.forEach((p) => {
    const sel = ["0", "1", "2"].map((m) =>
      `<option value="${m}" ${p.poeMode === m ? "selected" : ""}>${
        { 0: "Kapalı", 1: "PoE", 2: "PoE+" }[m]}</option>`).join("");
    const draw = p.powerW ? `${p.powerW} W` : '<span class="muted">—</span>';
    const tr = document.createElement("tr");
    if (p.linkStat !== "up") tr.classList.add("down");
    if (p.bekliyor) tr.classList.add("pending");
    tr.innerHTML = `
      <td>${p.pid}</td>
      <td>${linkCell(p)}</td>
      <td>${hizCell(p)}</td>
      <td><select class="poe ${p.poeMode === "0" ? "off" : "on"}"
                  data-poe="${p.pid}">${sel}</select>${
        etiket(bekleyenPoe.has(p.pid))}</td>
      <td>${draw}</td>`;
    feBody.appendChild(tr);
  });

  // --- Uplink portları: PoE yok, tek anahtar port durumu
  const ge = ports.filter((p) => !p.poe);
  const geBody = $("#ge-ports tbody");
  geBody.innerHTML = "";
  $("#ge-cnt").textContent = `${ge.length} port`;
  ge.forEach((p) => {
    const tr = document.createElement("tr");
    if (p.linkStat !== "up") tr.classList.add("down");
    if (p.bekliyor) tr.classList.add("pending");
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

async function setPoe(port, mode) {
  const ad = POE_AD[mode];

  if (mod === "toplu") {
    // switch'e gitmez; kuyruğa yazılır. Asıl değerine dönerse kuyruktan çıkar.
    if (String(hamPort(port).poeMode) === String(mode)) bekleyenPoe.delete(port);
    else bekleyenPoe.set(port, String(mode));
    renderPorts();
    return;
  }

  if (mode === "0" && !confirm(
      `Port ${port} gücü kesilecek. Bağlı cihaz kapanır. Devam?`)) {
    loadPorts().catch(() => {});
    return;
  }
  await islem(`Port ${port} gücü ${ad} yapılıyor…`,
    () => api("/api/switch/poe", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ip: current, port, mode }),
    }),
    `Port ${port} gücü → ${ad}`).catch(() => {});
}

async function togglePort(port, enable) {
  if (mod === "toplu") {
    if (Boolean(hamPort(port).adminStat) === enable) bekleyenPort.delete(port);
    else bekleyenPort.set(port, enable);
    renderPorts();
    return;
  }

  if (!enable && uplinkPids().includes(port)) {
    if (!confirm(`Port ${port} şu an BAĞLI (uplink olabilir). ` +
      `Kapatırsan switch bağlantısını kaybedebilirsin. Devam?`)) return;
  }
  await islem(`Port ${port} ${enable ? "açılıyor" : "kapatılıyor"}…`,
    () => api("/api/switch/port", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ip: current, port, enabled: enable }),
    }),
    `Port ${port} ${enable ? "açıldı" : "kapatıldı"}`).catch(() => {});
}

// ------------------------------------------------- toplu gönderim ---------
function bekleyenSayi() {
  return bekleyenPoe.size + bekleyenPort.size;
}

function batchBar() {
  const bar = $("#batchbar");
  bar.classList.toggle("hidden", mod !== "toplu");
  if (mod !== "toplu") return;
  const n = bekleyenSayi();
  bar.classList.toggle("bos", n === 0);
  $("#batch-send").disabled = n === 0;
  $("#batch-clear").disabled = n === 0;
  $("#batch-info").textContent = n === 0
    ? "Değişiklik yapın, sonra Gönder'e basın. Otomatik yenileme duraklatıldı."
    : `${n} değişiklik bekliyor` +
      (bekleyenPoe.size ? ` · PoE: ${[...bekleyenPoe.keys()].sort((a, b) => a - b).join(", ")}` : "") +
      (bekleyenPort.size ? ` · Port: ${[...bekleyenPort.keys()].sort((a, b) => a - b).join(", ")}` : "");
}

function batchClear() {
  bekleyenPoe.clear();
  bekleyenPort.clear();
  renderPorts();
}

async function batchSend() {
  const n = bekleyenSayi();
  if (!n) return;

  // Riskli olanları özetleyip tek onay al — her satır için ayrı soru sormak
  // toplu gönderimin amacını bozar.
  const gucKesilen = [...bekleyenPoe].filter(([, v]) => v === "0")
    .map(([pid]) => pid);
  const uplinkKapanan = [...bekleyenPort]
    .filter(([pid, v]) => !v && uplinkPids().includes(pid)).map(([pid]) => pid);
  let uyari = "";
  if (gucKesilen.length)
    uyari += `\n• Güç kesilecek (cihaz kapanır): ${gucKesilen.join(", ")}`;
  if (uplinkKapanan.length)
    uyari += `\n• BAĞLI port kapanacak (uplink olabilir, erişimi ` +
             `kaybedebilirsin): ${uplinkKapanan.join(", ")}`;
  if (uyari && !confirm(`${n} değişiklik gönderilecek.${uyari}\n\nDevam?`))
    return;

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
  }, `${n} değişiklik uygulandı`).catch(() => {});
}

function setMod(yeni) {
  if (yeni === mod) return;
  if (mod === "toplu" && bekleyenSayi() &&
      !confirm(`${bekleyenSayi()} bekleyen değişiklik var. ` +
               `Anında moda geçersen bunlar iptal olur. Devam?`)) return;
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
  if (!confirm(`Switch IP'si ${addr}/${prefix} olacak. Bağlantı kopacak. Devam?`))
    return;
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
  if (!confirm("Switch yeniden başlatılsın mı? Tüm portlar geçici kesilir." +
    (kayitBekliyor
      ? "\n\nDİKKAT: Kaydedilmemiş değişiklikler var, yeniden başlayınca " +
        "GERİ ALINIR. Önce Kaydet'e basın."
      : ""))) return;
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
  if (!confirm(
    `DİKKAT — ${current} fabrika ayarlarına döndürülecek.\n\n` +
    `IP adresi, port ve PoE ayarları dahil TÜM yapılandırma silinir. ` +
    `Switch varsayılan adresine döner ve bu arayüzden bulunamayabilir. ` +
    `Geri alınamaz.\n\nDevam edilsin mi?`)) return;

  const yanit = prompt(
    `Onaylamak için switch IP'sini yazın:\n${current}`, "");
  if ((yanit || "").trim() !== current) {
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
let seciliPort = null;

const pinHalka = (n, r) => Array.from({ length: n }, (_, i) => {
  const a = (i / n) * Math.PI * 2 - Math.PI / 2;
  return [20 + r * Math.cos(a), 20 + r * Math.sin(a)];
});

function durumSinifi(p) {
  if (p.bekliyor) return "pend";
  if (!portAcik(p)) return "off";
  if (portBesliyor(p)) return "feed";
  if (p.linkStat === "up") return "link";
  return "";
}

function portEtiketi(p) {
  return p.poe ? (POE_AD[p.poeMode] || "") : (p.adminStat ? "Açık" : "Kapalı");
}

function konnektor(p) {
  const pinler = p.poe ? pinHalka(4, 6.6) : pinHalka(8, 7.2);
  const r = p.poe ? 2.5 : 1.9;
  const b = document.createElement("button");
  b.type = "button";
  b.className = "m12 " + durumSinifi(p);
  b.dataset.pid = p.pid;
  b.title = `Port ${p.pid} · ${portEtiketi(p)} · ` +
            `${p.linkStat === "up" ? "bağlı" : "boş"}` +
            (p.powerW ? ` · ${p.powerW} W` : "");
  b.innerHTML =
    `<svg viewBox="0 0 40 40" aria-hidden="true">` +
    `<circle class="shell" cx="20" cy="20" r="18.4"></circle>` +
    `<circle class="inner" cx="20" cy="20" r="12.2"></circle>` +
    (p.poe ? "" : `<path class="cross" d="M13 13 L27 27 M27 13 L13 27"></path>`) +
    `<rect class="key" x="18.6" y="1.6" width="2.8" height="4.2"></rect>` +
    pinler.map(([x, y]) =>
      `<circle class="pin" cx="${x.toFixed(2)}" cy="${y.toFixed(2)}" r="${r}"></circle>`)
      .join("") +
    `</svg><span>${p.pid}</span>`;
  b.onclick = () => {
    seciliPort = seciliPort === p.pid ? null : p.pid;
    boyaSecim();
  };
  b.oncontextmenu = (e) => { e.preventDefault(); portMenusu(p, e); };
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
  menuKapat();

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
  document.querySelectorAll(".m12").forEach((el) =>
    el.classList.toggle("sel", +el.dataset.pid === seciliPort));
  document.querySelectorAll("#fe-ports tbody tr, #ge-ports tbody tr")
    .forEach((tr) => tr.classList.toggle(
      "sel", +tr.children[0].textContent.trim() === seciliPort));
}

// ------------------------------------------------ sağ tık işlem menüsü ----
// Menü doğrudan setPoe/togglePort çağırır; onay soruları, anında/toplu
// modu ve yenileme akışı tabloyla birebir aynı yoldan geçer.
let menuEl = null;

function menuKapat() {
  if (menuEl) { menuEl.remove(); menuEl = null; }
  document.removeEventListener("mousedown", menuDisari, true);
  document.removeEventListener("keydown", menuEsc, true);
}
function menuDisari(e) { if (menuEl && !menuEl.contains(e.target)) menuKapat(); }
function menuEsc(e) { if (e.key === "Escape") menuKapat(); }

function menuSatiri(etiket, sag, secenek, fn) {
  const o = secenek || {};
  const b = document.createElement("button");
  b.type = "button";
  b.className = "pm-item" + (o.danger ? " danger" : "") + (o.dim ? " dim" : "");
  b.innerHTML = `<i class="mark${o.mark ? " " + o.mark : ""}"></i>` +
                `<span class="lbl"></span><span class="rt"></span>`;
  b.querySelector(".lbl").textContent = etiket;
  b.querySelector(".rt").textContent = sag || "";
  b.onclick = () => { menuKapat(); fn(); };
  return b;
}

function portMenusu(p, e) {
  menuKapat();
  seciliPort = p.pid;
  boyaSecim();

  const m = document.createElement("div");
  m.className = "pm-menu";

  const bas = document.createElement("div");
  bas.className = "pm-menu-head";
  bas.innerHTML = `<div class="t"></div><div class="s"></div>`;
  bas.querySelector(".t").textContent = "Port " + p.pid;
  bas.querySelector(".s").textContent =
    (p.poe ? "PoE · " : "Uplink · ") + portEtiketi(p) +
    " · " + (p.linkStat === "up" ? "bağlı" : "boş") +
    (p.powerW ? ` · ${p.powerW} W` : "");
  m.appendChild(bas);

  const baslik = (t) => {
    const d = document.createElement("div");
    d.className = "pm-kicker"; d.textContent = t; m.appendChild(d);
  };

  if (p.poe) {
    baslik("Güç (PoE)");
    ["0", "1", "2"].forEach((mode) => {
      const gecerli = p.poeMode === mode;
      m.appendChild(menuSatiri(POE_AD[mode], gecerli ? "geçerli" : "",
        { mark: gecerli ? (mode === "0" ? "red" : "green") : "",
          danger: mode === "0" && !gecerli },
        () => { if (!gecerli) setPoe(p.pid, mode); }));
    });
  } else {
    baslik("Port durumu");
    m.appendChild(menuSatiri("Portu aç", p.adminStat ? "geçerli" : "",
      { mark: p.adminStat ? "green" : "" },
      () => { if (!p.adminStat) togglePort(p.pid, true); }));
    m.appendChild(menuSatiri("Portu kapat", !p.adminStat ? "geçerli" : "",
      { mark: !p.adminStat ? "red" : "", danger: p.adminStat },
      () => { if (p.adminStat) togglePort(p.pid, false); }));
  }

  document.body.appendChild(m);
  m.style.left = Math.min(e.clientX, innerWidth - m.offsetWidth - 8) + "px";
  m.style.top = Math.min(e.clientY, innerHeight - m.offsetHeight - 8) + "px";
  menuEl = m;
  setTimeout(() => {
    document.addEventListener("mousedown", menuDisari, true);
    document.addEventListener("keydown", menuEsc, true);
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
  $("#last-log").textContent = `${gecmis[gecmis.length - 1].t}  ${msg}`;
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
    k.textContent = l.tur;
    r.querySelector(".m").textContent = l.msg;   // metin olarak, HTML değil
    r.querySelector(".ip").textContent = l.ip;
    govde.appendChild(r);
  });
}

// --------------------------------------------------------- bağlama --------
$("#scan").onclick = scan;
$("#cidr").addEventListener("keydown", (e) => e.key === "Enter" && scan());
$("#save-net").onclick = saveNet;
$("#reboot").onclick = doReboot;
$("#save-cfg").onclick = saveConfig;
$("#factory").onclick = doFactoryReset;
$("#batch-send").onclick = batchSend;
$("#batch-clear").onclick = batchClear;
document.querySelectorAll(".mbtn").forEach((b) => {
  b.onclick = () => setMod(b.dataset.mode);
});
$("#login-form").onsubmit = girisGonder;
$("#login-cancel").onclick = girisIptal;
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && girisBekleyen) girisIptal();
});
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
    svg.className.baseVal = "ring";
    num.textContent = "‖";
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

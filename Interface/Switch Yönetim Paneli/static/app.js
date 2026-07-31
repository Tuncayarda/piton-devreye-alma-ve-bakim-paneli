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

function toast(msg, kind = "") {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "show " + kind;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.className = ""), kind === "err" ? 6000 : 4000);
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
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
    if (res && res.saved === false) {
      toast((basariMsg || "Uygulandı") +
            " — ancak switch'e KAYDEDİLEMEDİ, yeniden başlatmada geri alınır",
            "err");
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
        `Adres ve şifre doğru mu? (.env)</div>`;
      return;
    }
    $("#list").innerHTML = "";
    switches.forEach((s) => {
      const el = document.createElement("div");
      el.className = "sw-item";
      el.innerHTML = `<div class="ip">${s.ip}</div>
        <div class="mdl">${s.model || "Switch"} · v${s.version || "?"}</div>`;
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
  hamPorts = [];
  bekleyenPoe.clear();
  bekleyenPort.clear();
  document.querySelectorAll(".sw-item").forEach((x) => x.classList.remove("active"));
  el?.classList.add("active");
  $("#detail").classList.remove("hidden");
  lastOk = null; lastErr = null; tickRefresh();
  await loadInfo();
  await loadPorts();
}

async function loadInfo() {
  const info = await api("/api/switch/info?ip=" + current);
  $("#d-name").textContent = info.name || "Switch";
  $("#d-model").textContent = info.model || "";
  $("#d-ip").textContent = info.ip;
  $("#d-ver").textContent = info.version || "?";
  const n = info.network || {};
  $("#n-addr").value = n.addr || info.ip;
  $("#n-prefix").value = n.netmaskLen || "8";
  $("#n-mtu").value = n.mtu || "1500";
}

// --------------------------------------------------------- portlar --------
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
    `<span class="dot ${p.linkStat === "up" ? "up" : "down"}"></span>` +
    (p.linktext || (p.linkStat === "up" ? "up" : "—"));

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
      <td>${p.speed || ""}</td>
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
      <td>${p.speed || ""}</td>
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
    const res = await api("/api/switch/network", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ip: current, addr, prefix, mtu: $("#n-mtu").value }),
    });
    if (res.saved === false) {
      toast(`IP ${addr} olarak ayarlandı ama kaydedilemedi — ` +
            `yeni adresten bağlanıp Kaydet'e basın`, "err");
    } else {
      toast(`IP değiştirildi → ${addr}. Yeni adresten tekrar tarayın.`, "ok");
    }
  } catch (e) {
    toast("Hata: " + e.message, "err");
  } finally { setBusy(false); }
}

async function doReboot() {
  if (!confirm("Switch yeniden başlatılsın mı? Tüm portlar geçici kesilir.\n" +
    "Kaydedilmemiş değişiklikler varsa önce kaydedilecek.")) return;
  if (busy) { toast("Önceki işlem sürüyor, bekleyin", "err"); return; }
  setBusy(true, "Switch yeniden başlatılıyor…");
  try {
    const res = await api("/api/switch/reboot", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ip: current }),
    });
    toast(res.saved === false
      ? "Yeniden başlatılıyor — ancak kayıt yapılamadı"
      : "Kaydedildi, switch yeniden başlatılıyor…", res.saved === false ? "err" : "ok");
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

// --------------------------------------------------------- bağlama --------
$("#scan").onclick = scan;
$("#cidr").addEventListener("keydown", (e) => e.key === "Enter" && scan());
$("#refresh").onclick = () => loadPorts().catch(() => {});
$("#save-net").onclick = saveNet;
$("#reboot").onclick = doReboot;
$("#save-cfg").onclick = saveConfig;
$("#factory").onclick = doFactoryReset;
$("#batch-send").onclick = batchSend;
$("#batch-clear").onclick = batchClear;
document.querySelectorAll(".mbtn").forEach((b) => {
  b.onclick = () => setMod(b.dataset.mode);
});

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
    if (document.querySelector("select.poe:focus")) return;  // menü açıkken bekle
    try { await loadPorts(); } catch (e) { /* gösterge zaten uyarıyor */ }
  }, 5000);
}
startAuto();

document.querySelectorAll(".tab").forEach((t) => {
  t.onclick = () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    t.classList.add("active");
    $("#tab-ports").classList.toggle("hidden", t.dataset.tab !== "ports");
    $("#tab-network").classList.toggle("hidden", t.dataset.tab !== "network");
  };
});

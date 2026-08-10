// Devreye Alma Paneli — arayüz başlangıcı ve döngüler.
//
// Zamanlama kuralları:
//   · setInterval kullanılmaz. Her tur, bir önceki istek BİTTİKTEN sonra
//     setTimeout ile kurulur; yavaş bir cihaz yüzünden istekler üst üste
//     binmez.
//   · Yenileme iki hızda çalışır ve durdurulamaz:
//       – Keşif (tam tarama) dakikada bir. DeviceMap'teki HER adrese
//         bakar, yani ulaşılamayan cihaz başına zaman aşımı kadar bekler;
//         pahalı olan bu. "Güncelle" düğmesi bu turu öne çeker.
//       – Hafif yenileme birkaç saniyede bir, YALNIZ son turda yeşile
//         düşmüş cihazlara. Ulaşılamayana dokunmaz, o yüzden hızlıdır.
//   · Tam tarama sürerken hafif yenileme çalışmaz.
//   · IP atama / konfigürasyon / yazılım yükleme koşusu sürerken
//     kendiliğinden tarama başlatılmaz; koşu cihazları yeniden başlatıyor.
//     Elle istenen tarama kuyruğa girer ve koşudan sonra çalışır.
//   · Her yanıtın bir "nesli" vardır; geç gelen eski yanıt yenisini ezmez.

import { $, kaydirmayiKoru } from './core/dom.js';
import { api } from './core/api.js';
import { durum, ata, abone } from './core/durum.js';
import * as kenar from './parts/kenar.js';
import * as kuyruk from './parts/kuyruk.js';
import * as kilit from './parts/kilit.js';
import * as detay from './parts/detay.js';
import * as diyalog from './parts/diyalog.js';
import { bildir, hata, basari } from './parts/bildirim.js';
import * as vGenel from './views/genel.js';
import * as vCihaz from './views/cihazlar.js';
import * as vIp from './views/ip.js';
import * as vCfg from './views/konfig.js';
import * as vFw from './views/firmware.js';
import * as vDog from './views/kontrol.js';
import * as vPiscu from './views/piscu.js';
import * as vMqtt from './views/mqtt.js';
import * as vAdmin from './views/admin.js';

// Turlar arasındaki BOŞLUK (sürelerine değil). Hafif tur yalnız yeşil
// cihazlara gittiği için kendi başına da hızlı biter; iki saniye, saha
// gözünün "canlı" saydığı aralık. Sunucu turu sırayla okuduğundan bunu
// kısaltmak istekleri üst üste bindirmez, yalnız cihazları daha sık yorar.
const HAFIF_ARALIK = 2000;
// Keşif turu: bu IP'de cihaz var mı? Ulaşılamayan her cihaz zaman aşımı
// kadar beklettiği için seyrek çalışır.
const TAM_TARAMA_ARALIK = 60000;
// Oturum açılışında ve set değişiminde ekran boş gelir; ilk keşif tam bir
// dakika beklemez. Kısa gecikme, ilk çizimle taramanın yarışmaması için.
const ILK_TARAMA_GECIKME = 1500;
// Tarama bir engel yüzünden atlandığında ne kadar sonra yeniden bakılır.
const ENGEL_BEKLEME = 3000;
const IS_ARALIK = 900;

// Cihaza YAZAN koşular. Sürerken kendiliğinden tarama başlatılmaz
// (sunucu tarafındaki karşılığı: panel_api.YAZAN_ISLER).
const KOSU_TURU = new Set(['ip', 'ipfab', 'cfg', 'fw']);

let durumNesli = 0;
let hafifZaman = null;
let isZaman = null;
let taramaZaman = null;

// ───────────────────────────────────────────────────────── veri çekme ────
async function durumuCek() {
  const nesil = ++durumNesli;
  const d = await api.durum(durum.setNo);
  if (nesil !== durumNesli) return null;      // daha yeni bir istek var
  kilit.uygulaDurum(d);
  await acikEkraniTazele();
  return d;
}

// Kontrol listesi cihaz okumalarından değil kendi ucundan besleniyor
// (/api/kontrol, şablon + o anki görüntü). Yalnız ekrana girerken
// çekildiği için tarama sürerken ya da hafif yenileme yeni değer
// getirdiğinde ekranda eski satırlar kalıyordu.
//
// İmza: cihaz sonuçlarının özeti. Aynıysa istek yapılmaz — 900 ms'lik iş
// döngüsünde her turda şablon önizlemesi çekmenin anlamı yok.
const TAZELE_ARALIK = 1500;
let sonImza = '';
let sonTazeleZamani = 0;

function cihazImzasi() {
  return (durum.cihazlar || [])
    .map(c => `${c.id}${c.sonuc.durum}${c.sonuc.okumaZamani || 0}`)
    .join('|');
}

async function acikEkraniTazele() {
  if (durum.gorunum !== 'dog') return;
  const imza = cihazImzasi();
  const simdi = Date.now();
  if (imza === sonImza || simdi - sonTazeleZamani < TAZELE_ARALIK) return;
  sonImza = imza;
  sonTazeleZamani = simdi;
  await vDog.tazele();
}

// İş listesi her turda yeni bir dizi olarak gelir; `ata` referansa baktığı
// için hiçbir şey değişmemiş olsa da bütün arayüz yeniden çiziliyordu.
// Kuyruk paneli açıkken bu, saniyede bir tam çizim demekti.
let sonIslerImzasi = null;

async function isleriCek() {
  try {
    const y = await api.isler();
    let isler = y.isler || [];
    if (durum.acikIs) {
      try {
        const tam = await api.is(durum.acikIs);
        isler = isler.map(j => (j.id === tam.id ? tam : j));
      } catch { /* iş silinmiş olabilir */ }
    }
    const imza = JSON.stringify(isler);
    if (imza === sonIslerImzasi) return;
    sonIslerImzasi = imza;
    ata({ isler });
  } catch { /* servis bir tur cevap vermediyse bir sonrakinde denenir */ }
}

// ───────────────────────────────────────────────────────── döngüler ──────
function isDongusu() {
  clearTimeout(isZaman);
  const surenVar = (durum.isler || []).some(
    j => j.durum === 'calisiyor' || j.durum === 'bekliyor');
  const gerek = surenVar || durum.kuyrukAcik;
  isZaman = setTimeout(async () => {
    if (durum.rol) {
      await isleriCek();
      if (surenVar) { try { await durumuCek(); } catch { /* yoksay */ } }
    }
    isDongusu();
  }, gerek ? IS_ARALIK : 4000);
}

// Hafif yenilemenin hedefi: YALNIZ son taramada yeşile düşen cihazlar.
// Ulaşılamayan cihaz her turda yeniden denenirse tur onun zaman aşımı
// kadar uzuyor ve çalışan cihazların verisi bayatlıyor. Ulaşılamayanı
// yeniden denemek dakikalık keşif turunun işi. Sunucu da aynı süzgeci
// uygular (panel_api._hafif_yenileme); burada listelemek isteği küçültür.
function yenilemeHedefi() {
  return (durum.cihazlar || [])
    .filter(c => c.sonuc && c.sonuc.durum === 'yesil')
    .map(c => c.id);
}

function surenKosuVar() {
  return (durum.isler || []).some(
    j => KOSU_TURU.has(j.tur)
      && (j.durum === 'calisiyor' || j.durum === 'bekliyor'));
}

// Süren tarama arayüzün kendi zamanlayıcısından mı geldi? Elle istenen
// tarama kullanıcıyı bekletmeye değer; dakikada bir kendiliğinden çıkan
// tur ise arayüzü kilitlememeli (bkz. setSeciciyiKur).
function otomatikTaramaIsi() {
  return (durum.isler || []).find(
    j => j.tur === 'tarama' && j.otomatik
      && (j.durum === 'calisiyor' || j.durum === 'bekliyor')) || null;
}

// Keşif turu. Ne kadar bekleneceği dışarıdan verilebiliyor: "Güncelle",
// oturum açılışı ve set değişimi sayacı kendi süresiyle sıfırlar.
function taramaDongusu(gecikme = TAM_TARAMA_ARALIK) {
  clearTimeout(taramaZaman);
  taramaZaman = setTimeout(async () => {
    // Tur atlanınca sayaç baştan kurulmaz, kısa aralıkla tekrar bakılır:
    // engel kalkar kalkmaz tarama çalışmalı, bir dakika daha beklememeli.
    // Uzun bir yazılım yükleme koşusundan sonra cihazların durumu tepeden
    // tırnağa değişmiş olur; oradaki gecikme en çok can sıkan yer. Denetim
    // yerel durumdan yapıldığı için sık bakmanın bir maliyeti yok.
    if (!durum.rol || durum.aktifTarama || surenKosuVar()) {
      taramaDongusu(ENGEL_BEKLEME);
      return;
    }
    try {
      await api.tarama(durum.setNo, true);
      await isleriCek();
    } catch { /* servis bir tur cevap vermediyse bir sonrakinde denenir */ }
    taramaDongusu();
  }, gecikme);
}

function hafifDongu() {
  clearTimeout(hafifZaman);
  hafifZaman = setTimeout(async () => {
    const uygun = durum.rol && !durum.aktifTarama
      && !(durum.isler || []).some(j => j.durum === 'calisiyor');
    if (uygun) {
      const hedef = yenilemeHedefi();
      if (hedef.length) {
        const nesil = ++durumNesli;
        try {
          const d = await api.yenile(durum.setNo, hedef);
          if (nesil === durumNesli) {
            kilit.uygulaDurum(d);
            await acikEkraniTazele();
          }
        } catch (e) {
          // 409 = tam tarama araya girdi; sessizce bir sonraki tura bırak
          if (e.kod && e.kod !== 409) console.warn('hafif yenileme:', e.message);
        }
      } else {
        // Yenilenecek yeşil cihaz yok — ama açık ekranın kendi ucu
        // (kontrol listesi) cihaz okumasına bağlı değil. Bu dal olmadan
        // hiçbir cihaz yeşil değilken liste ilk girişteki görüntüde
        // donuyordu. İmza denetimi zaten değişmemişse isteği yapmıyor.
        await acikEkraniTazele();
      }
    }
    hafifDongu();
  }, HAFIF_ARALIK);
}

// ───────────────────────────────────────────────────────── çizim ─────────
const EKRANLAR = {
  genel: ['#v-genel', (k) => vGenel.ciz(k, guncelle)],
  cihaz: ['#v-cihaz', (k) => vCihaz.ciz(k)],
  ip: ['#v-ip', (k) => vIp.ciz(k)],
  cfg: ['#v-cfg', (k) => vCfg.ciz(k)],
  fw: ['#v-fw', (k) => vFw.ciz(k)],
  dog: ['#v-dog', (k) => vDog.ciz(k, guncelle)],
  piscu: ['#v-piscu', (k) => vPiscu.ciz(k)],
  mqtt: ['#v-mqtt', (k) => vMqtt.ciz(k)],
  admin: ['#v-admin', (k) => vAdmin.ciz(k, setDegistir)],
};

let sonGorunum = null;

// Yalnız yan panelleri ilgilendiren anahtarlar. Kuyrukta bir işi açıp
// kapatmak ekranın geri kalanını (cihaz tablosu, kenar çubuğu, üst bar)
// baştan kurmayı gerektirmiyor; kurunca da gözle görülür şekilde takılıyordu.
const PANEL_ANAHTAR = new Set(['acikIs', 'kuyrukAcik', 'kilitAcik']);

function ciz(_d, degisen) {
  if (!durum.rol) return;

  if (Array.isArray(degisen) && degisen.length
      && degisen.every(k => PANEL_ANAHTAR.has(k))) {
    kuyruk.ciz();
    kilit.ciz();
    return;
  }

  // üst bar
  const meta = durum.meta;
  if (meta) {
    $('#proje-ad').textContent = meta.proje;
    setSeciciyiKur();
  }
  $('#rol-rozet').textContent = durum.rol === 'admin' ? 'Admin' : 'Kullanıcı';
  $('#rol-rozet').style.color = durum.rol === 'admin' ? 'var(--accent)' : '';
  $('#kenar-ac').setAttribute('aria-expanded', String(durum.kenarAcik));
  $('#alt-bilgi').textContent = kuyruk.ozetMetni(yenilemeHedefi().length);
  $('#alt-surum').textContent = `v${durum.surum}`;

  const guncelle = $('#guncelle-btn');
  guncelle.disabled = !!durum.aktifTarama;
  // Yalnız görünen etiket değişir; ölçü etiketi düğmenin genişliğini
  // sabit tutmak için yerinde durur (bkz. index.html).
  $('.etiket-oynak', guncelle).textContent = durum.aktifTarama
    ? 'Taranıyor…' : 'Güncelle';
  yanPaneliHizala();

  kenar.ciz();
  kuyruk.ciz();
  kilit.ciz();

  for (const [ad, [secici]] of Object.entries(EKRANLAR)) {
    $(secici).hidden = ad !== durum.gorunum;
  }
  const [secici, cizFn] = EKRANLAR[durum.gorunum] || EKRANLAR.genel;
  const ekranDegisti = sonGorunum !== durum.gorunum;

  // Aynı ekranda kalıyorsak kaydırma konumu korunur; ekran değiştiyse
  // baştan başlamak doğru davranış.
  //
  // Ekran yeniden kurulunca içindeki kutular da baştan yaratılır ve
  // yazılmakta olan değer kaybolur (alanlar onchange ile, yani odak
  // çıkınca kaydediyor). Yenileme turu artık saniyeler arayla geldiği
  // için bu, konfigürasyon alanına yazarken sürekli metin kaybı demekti.
  // Odak ekranın içindeki bir kutudayken o turun çizimi atlanır; ekran
  // değişimi kullanıcının kendi eylemidir, o atlanmaz.
  if (ekranDegisti || !odakEkranKutusunda()) {
    kaydirmayiKoru(ekranDegisti ? null : $('#icerik'), () => cizFn($(secici)));
  }

  if (ekranDegisti) {
    sonGorunum = durum.gorunum;
    $('#icerik').scrollTop = 0;
    ekranaGirildi(durum.gorunum);
  }
}

function odakEkranKutusunda() {
  const a = document.activeElement;
  if (!a || !$('#icerik').contains(a)) return false;
  return a.matches('input, textarea, select, [contenteditable="true"]');
}

// Ekran ilk açıldığında kendi verisini çeker (açılışta hepsi çekilmez).
function ekranaGirildi(ad) {
  if (ad === 'dog') vDog.tazele();
  else if (ad === 'ip') vIp.tazele();
  else if (ad === 'cfg') vCfg.tazele();
  else if (ad === 'fw') vFw.tazele();
  else if (ad === 'piscu') vPiscu.tazele();
  else if (ad === 'mqtt') vMqtt.tazele();
}

// ───────────────────────────────────────────────────────── eylemler ──────
// "Güncelle" artık tarama BAŞLATMAZ, sıradakini ÖNE ÇEKER: tarama zaten
// dakikada bir çalışıyor, düğme o turu şimdi kuyruğa alır ve sayacı
// baştan kurar. Bir koşu (IP atama, konfigürasyon, yazılım yükleme)
// sürüyorsa tarama kuyrukta bekler — kuyruk tek işçili olduğu için koşuyla
// asla çakışmaz; kullanıcıya da beklediği söylenir.
//
// Tarama başlatmak kuyruk panelini AÇMAZ. İş kuyruğa girdiğinde haber
// kuyruk düğmesinde belirir (rozet + kısa vurgu); paneli açmak isteyen
// düğmeye basar. Ekranı kaplayan panel, tarama sürerken cihaz listesini
// izlemek isteyen kullanıcıyı her seferinde kapatmaya zorluyordu.
async function guncelle() {
  const kosu = surenKosuVar();
  try {
    const y = await api.tarama(durum.setNo);
    ata({ acikIs: y.id, aktifTarama: true });
    if (y.yeni === false) {
      bildir('Tarama zaten kuyrukta');
    } else {
      kuyruk.isaretle();
      if (kosu) bildir('Tarama kuyrukta — süren koşu bitince çalışacak');
    }
    await isleriCek();
  } catch (e) {
    hata(e.message);
  } finally {
    // Elle tarandıktan sonra dakikalık sayaç sıfırdan başlar; yoksa
    // düğmeye basmak bir saniye sonra ikinci bir turu tetikleyebilirdi.
    taramaDongusu();
  }
}

// Sağdan açılan panellerin sol kenarını "Güncelle" düğmesinin sol
// kenarına oturtur: paneli açan düğmeler panelin üstünde kalır, panel de
// üst bara yapışık tek parça görünür. Genişlik sabit yazılamıyor, çünkü
// üst bardaki düğme yazıları değişiyor ("Taranıyor…", rol rozeti).
function yanPaneliHizala() {
  const btn = $('#guncelle-btn');
  const govde = $('.govde');
  if (!btn || !govde) return;
  const genislik = Math.round(
    govde.getBoundingClientRect().right - btn.getBoundingClientRect().left);
  if (genislik > 0) {
    document.documentElement.style.setProperty('--yan-panel', `${genislik}px`);
  }
}

// Set numarası üst barda elle yazılır; rolden bağımsız olarak herkes
// kullanabilir. Kullanıcı yazarken alana dokunulmaz — odak baştayken
// değeri geri yazmak yazılanı siliyordu.
function setSeciciyiKur(zorla = false) {
  const secici = $('#set-secici');
  if (!secici) return;
  const { min, max } = setSiniri();
  secici.min = String(min);
  secici.max = String(max);
  if ((zorla || document.activeElement !== secici)
      && secici.value !== String(durum.setNo)) {
    secici.value = String(durum.setNo);
  }
  // Yalnız ELLE başlatılan tarama alanı kilitler. Tarama dakikada bir
  // kendiliğinden çalıştığı için otomatik turu da saymak, set numarasını
  // değiştirmeyi her dakika birkaç saniyeliğine imkânsız kılardı; kilidin
  // ne zaman açılacağını kestiremeyen kullanıcı alana boşuna tıklıyordu.
  const kilitli = elleTaramaSuruyor();
  secici.disabled = kilitli;
  secici.title = kilitli
    ? 'Tarama sürerken tren seti değiştirilemez'
    : `Tren setini değiştir (${min}–${max})`;
}

function elleTaramaSuruyor() {
  return !!durum.aktifTarama && !otomatikTaramaIsi();
}

// Kabul edilen aralık sunucudan gelir; meta henüz yokken de bir sınır
// gerekiyor, o yüzden sunucudakiyle aynı varsayılan burada duruyor.
function setSiniri() {
  const m = durum.meta || {};
  return { min: m.setMin || 1, max: m.setMax || 254 };
}

async function setDegistir(n) {
  const { min, max } = setSiniri();
  const yeni = Number(String(n).trim());
  if (!Number.isInteger(yeni) || yeni < min || yeni > max) {
    bildir(`Set numarası ${min} ile ${max} arasında olmalı`);
    setSeciciyiKur(true);
    return;
  }
  if (yeni === durum.setNo) return;
  if (elleTaramaSuruyor()) {
    bildir('Tarama sürerken tren seti değiştirilemez');
    setSeciciyiKur(true);
    return;
  }
  // Otomatik tur eski setin cihazlarını okuyor; sonuçları yeni sette
  // işimize yaramıyor, bitmesini beklemenin de anlamı yok.
  const oto = otomatikTaramaIsi();
  if (oto) {
    try { await api.isIptal(oto.id); } catch { /* bitmiş olabilir */ }
  }
  // Görünüm seti başına tutulduğu için eski setin sonuçları taşınmaz.
  detay.kapat();
  ata({ setNo: yeni, cihazlar: [], kilit: [], sonTarama: null, ipDurum: null,
    cfgDurum: null, piscuDurum: null, kontrolDurum: null, detayId: null });
  try {
    await baslangicVerisi();
    ekranaGirildi(durum.gorunum);
    basari(`Tren seti ${yeni} yüklendi`);
  } catch (e) {
    hata(e.message);
  }
  // Yeni set boş gelir: keşif turu dakika beklemeden çalışsın.
  taramaDongusu(ILK_TARAMA_GECIKME);
}

async function baslangicVerisi() {
  const meta = await api.proje(durum.setNo);
  ata({ meta, piscuIp: meta.piscuIp, setNo: meta.setNo });
  await durumuCek();
  await isleriCek();
}

// ───────────────────────────────────────────────────────── rol ekranı ────
async function rolSec(rol) {
  ata({ rol });
  $('#rol-ekrani').hidden = true;
  $('#uygulama').hidden = false;
  try {
    await baslangicVerisi();
  } catch (e) {
    hata(e.message);
  }
  isDongusu();
  hafifDongu();
  // Oturum boş bir tabloyla açılıyordu ve ilk veri için kullanıcının
  // "Güncelle"ye basması gerekiyordu; yenileme sürekli olduğuna göre
  // ilk keşif de kendiliğinden çalışmalı.
  taramaDongusu(ILK_TARAMA_GECIKME);
  ciz();
  $('#icerik').focus();
}

function cikis() {
  // Oturumu kapatmak arayüzü sıfırlar. Bellekteki cihaz kimlikleri
  // sunucuda kalır (uygulama hâlâ açık); "Kimlikleri Unut" admin
  // ekranındadır. Uygulama kapanınca hepsi zaten silinir.
  clearTimeout(hafifZaman);
  clearTimeout(isZaman);
  clearTimeout(taramaZaman);
  detay.kapat();
  diyalog.kapat();
  ata({
    rol: null, gorunum: 'genel', kategori: 'tum', altTip: null,
    detayId: null, kuyrukAcik: false, kilitAcik: false, acikIs: null,
  });
  sonGorunum = null;
  $('#uygulama').hidden = true;
  $('#rol-ekrani').hidden = false;
  $('#admin-form').hidden = true;
  $('#admin-parola').value = '';
  $('#rol-hata').hidden = true;
  $('#rol-kullanici').focus();
}

// ───────────────────────────────────────────────────────── başlangıç ─────
async function basla() {
  try {
    const s = await api.surum();
    ata({ surum: s.surum });
    $('#rol-surum').textContent = `v${s.surum}`;
    $('#alt-surum').textContent = `v${s.surum}`;
    $('#rol-ekrani').dataset.parolaGerek = String(s.adminParolaGerekli);
  } catch {
    hata('Panel servisine ulaşılamadı');
  }

  $('#rol-kullanici').addEventListener('click', () => rolSec('saha'));

  $('#rol-admin').addEventListener('click', async () => {
    const gerek = $('#rol-ekrani').dataset.parolaGerek === 'true';
    if (!gerek) {
      try { await api.adminGiris(''); } catch { /* şifre yoksa açılır */ }
      rolSec('admin');
      return;
    }
    $('#admin-form').hidden = false;
    $('#admin-parola').focus();
  });

  $('#admin-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const alan = $('#admin-parola');
    const uyari = $('#rol-hata');
    try {
      await api.adminGiris(alan.value);
      alan.value = '';                      // parola arayüzde tutulmaz
      uyari.hidden = true;
      rolSec('admin');
    } catch (err) {
      alan.value = '';
      uyari.textContent = err.message || 'Şifre doğrulanamadı';
      uyari.hidden = false;
      alan.focus();
    }
  });

  $('#guncelle-btn').addEventListener('click', guncelle);
  $('#kuyruk-btn').addEventListener('click', kuyruk.acKapat);
  $('#kilit-btn').addEventListener('click', kilit.kilitAcKapat);
  $('#cikis-btn').addEventListener('click', cikis);
  $('#kenar-ac').addEventListener('click',
    () => ata({ kenarAcik: !durum.kenarAcik }));
  $('#proje-btn').addEventListener('click', () => {
    if (durum.rol === 'admin') ata({ gorunum: 'admin' });
    else bildir('Proje ayrıntıları admin rolünde görüntülenir');
  });
  globalThis.addEventListener('resize', yanPaneliHizala);

  // change alandan çıkınca da tetiklenir; Enter'ı beklemeye gerek yok.
  $('#set-secici').addEventListener('change',
    (e) => setDegistir(e.target.value));
  $('#set-secici').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      setDegistir(e.target.value);
    } else if (e.key === 'Escape') {
      setSeciciyiKur(true);
      e.target.blur();
    }
  });

  for (const b of document.querySelectorAll('[data-kapat]')) {
    b.addEventListener('click', () => ata(
      b.dataset.kapat === 'kuyruk' ? { kuyrukAcik: false } : { kilitAcik: false }));
  }

  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (diyalog.acikMi()) return;             // diyalog kendi Escape'ini yönetir
    if (durum.detayId) { detay.kapat(); return; }
    if (durum.kuyrukAcik || durum.kilitAcik) {
      ata({ kuyrukAcik: false, kilitAcik: false });
    }
  });

  // Kimlik doğrulandıktan sonra açık ekran da tazelenir: IP atama ekranı
  // switch kimliğine bakıp koşuyu kilitliyor, kullanıcı parolayı girince
  // özetin güncellenmesi için sayfadan çıkıp girmek zorunda kalıyordu.
  kilit.baglaYenile(() => {
    isleriCek();
    ekranaGirildi(durum.gorunum);
  });
  abone(ciz);
  $('#rol-kullanici').focus();
}

// Sekme/pencere kapanırken süren döngüleri durdur.
globalThis.addEventListener('pagehide', () => {
  clearTimeout(hafifZaman);
  clearTimeout(isZaman);
  clearTimeout(taramaZaman);
});

basla();

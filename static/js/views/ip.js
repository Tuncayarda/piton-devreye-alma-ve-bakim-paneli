// Otomatik IP atama ekranı.
//
// Plan sunucudan gelir (DeviceMap'ten çıkarılır); tarayıcı kendi başına
// bir hedef üretmez. Koşu ağa yazar; bu yüzden hedef ve koruma portları
// hem arayüzde hem sunucuda çalıştırmadan önce doğrulanır.
//
// Ön panel, switch'in gerçek yüzünü çizer: PoE portları sütun sütun
// aşağıdan yukarı (1-2-3-4 | 5-6-7-8 …), sağda kesik çizgiyle ayrılmış
// uplink sütunu. Dizilim kardeş projedeki Switch Yönetim Paneli ile
// aynıdır; iki panelde aynı switch'e bakan kişi aynı yerleşimi görür.
//
// Projede birden çok switch varsa hepsinin paneli gösterilir. Koşu tek
// switch üzerinde yürüdüğü için bir tanesi "etkin"dir; başka bir switch'in
// portuna tıklamak koşuyu o switch'e taşır.
//
// Bilgisayarın takılı olduğu port ELLE GİRİLMEZ: yerel ağ arayüzünün MAC
// adresi switch'in öğrenme tablosunda aranır (bkz. pcPortuBul ve
// core/ip_atama.bilgisayar_portu). Elle giriş yalnız arama sonuç
// vermediğinde ya da kullanıcı bulguyu açıkça geçersiz kıldığında açılır.

import { el, doldur } from '../core/dom.js';
import { api } from '../core/api.js';
import { durum, ata } from '../core/durum.js';
import * as islemSekmeleri from '../parts/islem_sekmeleri.js';
import * as diyalog from '../parts/diyalog.js';
import { kimlikDiyalogu } from '../parts/kilit.js';
import { hata, basari, bildir } from '../parts/bildirim.js';
import { deger, tazelik, YOK } from '../core/bicim.js';

const KOLON = '68px minmax(150px,1.25fr) minmax(104px,.85fr) 112px 112px '
  + 'minmax(150px,1fr)';
// IP atanacak cihaz türü. Motor bugün yalnız Intercom'u destekliyor
// (bkz. panel_api /api/ip/plan), o yüzden listede tek seçenek var. Seçim
// yine de ekranda duruyor: başka cihaz grupları ve "bütün cihazlar" için
// IP atama eklendiğinde buraya bir satır eklemek yetecek, ekranın
// yerleşimi değişmeyecek.
const IP_HEDEFLERI = [
  { id: 'Intercom', ad: 'Intercom', gruplar: ['Intercom'] },
];

const yerel = {
  hedefId: IP_HEDEFLERI[0].id,
  portMetni: null,         // null = plandaki varsayılan (grubun portları)
  fabrikaIp: null,         // null = plandaki varsayılan (10.1.1.12)
  aramaAcik: false,        // fabrika adresinde bulunamayanları ağda ara
  aramaAgi: null,
  aramaMaskesi: null,
  aramaBas: null,          // açık adres aralığı — verilirse ağ/maske yerine
  aramaSon: null,
  // Sonda güç çevirip ayarın cihazın flash'ına indiğini doğrula. Koşuyu
  // uzattığı ve cihazları yeniden karartığı için varsayılan kapalı.
  kalicilik: false,
  // Korunan portlar (bilgisayarın yeri + switch'ler arası bağlantılar)
  // elle girilmez, MAC tablolarından bulunur ve düzenli aralıkla yeniden
  // doğrulanır (bkz. korunanTuru). Ekranda ayrı bir form yok; bulgu ön
  // panelde turuncu port olarak ve koşu özetinde görünür.
  korunan: null,           // {zaman, bilgisayar, portlar[], denenen[], not}
  korunanAraniyor: false,
  switchId: null,          // null = planın kendi seçtiği switch
  hataMetni: '',
  acikBolumler: {
    kapsam: true,
    paneller: true,
    plan: null,
    teknik: false,
  },
};

let tazeleSurumu = 0;

// ── ön panel canlı yenileme ─────────────────────────────────────────────
// Switch Yönetim Paneli'ndeki gibi: portlar 5 saniyede bir yeniden okunur,
// başlıkta verinin kaç saniye önce alındığı yazar, yenileme duraklatılabilir.
// Yalnız panel alanı yeniden çizilir — bütün ekranı çizmek, kullanıcı forma
// yazarken odağı alandan koparıyordu.
const YENILEME_ARALIK = 5000;
const BAYAT_SN = 15;

const canli = {
  acik: true,
  zaman: null,          // yenileme turu zamanlayıcısı
  sayac: null,          // "kaç sn önce" yazısını tazeleyen saniyelik tik
  korunan: null,        // korunan portların yeniden doğrulama turu
  yigin: null,          // panel kartlarının kabı
};

function panelleriDurdur() {
  clearTimeout(canli.zaman);
  clearTimeout(canli.sayac);
  clearTimeout(canli.korunan);
  canli.zaman = canli.sayac = canli.korunan = null;
}

function ekrandaMi() {
  return durum.gorunum === 'ip' && !!durum.rol
    && !!(canli.yigin && canli.yigin.isConnected);
}

// Panelleri yeniden okur ve YALNIZ panel kartlarını yeniden çizer.
async function panelleriTazele() {
  const veri = durum.ipDurum;
  if (!veri || !ekrandaMi()) return;
  const setNo = durum.setNo;
  const yeni = await Promise.all((veri.plan.switchler || []).map(
    s => api.ipPanel(setNo, s.id).catch(() => null)));
  const gecerli = yeni.filter(Boolean);
  if (!gecerli.length || setNo !== durum.setNo || !ekrandaMi()) return;
  // Durum nesnesi yerinde güncellenir: `ata` çağırmak bütün ekranı
  // yeniden çizerdi (ve formdaki odağı düşürürdü).
  veri.paneller = gecerli;
  panelleriCiz(veri);
}

function panelleriCiz(veri) {
  if (!canli.yigin) return;
  doldur(canli.yigin, veri.paneller.length
    ? veri.paneller.map(p => panelKarti(p, veri.plan))
    : [el('div', { sinif: 'ip-panel-bos' }, [
        el('span', { sinif: 'ust-etiket', metin: 'Panel bilgisi yok' }),
        el('p', { metin: 'Switch ön paneli şu anda görüntülenemiyor.' }),
      ])]);
  tazelikYaz();
}

// Başlıktaki "x sn önce" yazısı saniyede bir tazelenir; bunun için ekranı
// yeniden çizmeye gerek yok, metin doğrudan yazılır.
function tazelikYaz() {
  if (!canli.yigin) return;
  for (const e of canli.yigin.querySelectorAll('[data-okuma]')) {
    const ts = Number(e.dataset.okuma);
    if (!ts) { e.textContent = 'okunamadı'; e.dataset.bayat = '1'; continue; }
    const sn = Math.max(0, Math.round(Date.now() / 1000 - ts));
    e.textContent = `${sn < 100 ? sn : '99+'} sn önce`;
    e.dataset.bayat = sn > BAYAT_SN ? '1' : '0';
  }
}

// Turlar zincirli setTimeout ile kurulur: bir okuma uzun sürerse bir
// sonraki tur onu beklemeden başlamaz, istekler üst üste binmez.
function tazelikTiki() {
  clearTimeout(canli.sayac);
  canli.sayac = null;
  if (!ekrandaMi()) return;
  tazelikYaz();
  canli.sayac = setTimeout(tazelikTiki, 1000);
}

async function yenilemeTuru() {
  clearTimeout(canli.zaman);
  canli.zaman = null;
  if (!ekrandaMi() || !canli.acik) return;
  try {
    await panelleriTazele();
  } catch { /* gösterge zaten "kaç sn önce" ile bayatlığı söylüyor */ }
  if (!ekrandaMi() || !canli.acik) return;
  canli.zaman = setTimeout(yenilemeTuru, YENILEME_ARALIK);
}

// Korunan portların yeniden doğrulanması. Ön panel turundan ayrı ve daha
// seyrek: bu tur switch'in MAC tablosunu okuyor, kablo da her beş
// saniyede bir yer değiştirmiyor. Ama bir kere bulup bırakmak da olmaz —
// koşu başlamadan önce kablo başka porta taşınmış olabilir.
async function korunanTuru() {
  clearTimeout(canli.korunan);
  canli.korunan = null;
  if (!ekrandaMi() || !canli.acik) return;
  try {
    await korunanTazele();
  } catch { /* bir sonraki turda denenir */ }
  if (!ekrandaMi() || !canli.acik) return;
  canli.korunan = setTimeout(korunanTuru, KORUNAN_ARALIK);
}

// Kurulmuş bir tur YERİNDE BIRAKILIR, yeniden kurulmaz.
//
// `ciz` her cihaz yenilemesinde çalışıyor — hafif yenileme birkaç
// saniyede bir bütün ekranı çiziyor. Zamanlayıcıları her çizimde yıkıp
// yeniden kurmak, hiçbirinin dolmaması demekti: ne 5 sn'lik panel turu
// ne 30 sn'lik doğrulama turu bir daha çalışıyordu. Turlar ekrandan
// çıkılınca kendileri duruyor (bkz. ekrandaMi), burada durdurmaya gerek
// yok.
function yenilemeyiKur() {
  if (!canli.sayac) tazelikTiki();
  if (!canli.acik) return;
  if (!canli.zaman) canli.zaman = setTimeout(yenilemeTuru, YENILEME_ARALIK);
  if (!canli.korunan) {
    canli.korunan = setTimeout(korunanTuru, KORUNAN_ARALIK);
  }
}

function gecerliHedef() {
  return IP_HEDEFLERI.find(h => h.id === yerel.hedefId) || IP_HEDEFLERI[0];
}

function seciliGruplar() {
  return gecerliHedef().gruplar;
}

// Hedef türü seçici. Tek seçenekliyken de görünür durur: kullanıcı IP
// atamanın hangi cihazlara gittiğini ekrandan okuyabilsin.
function hedefSecici() {
  const aktif = gecerliHedef();
  return el('label', { sinif: 'hedef-secici' }, [
    el('span', { sinif: 'etiket', metin: 'Cihaz türü' }),
    el('select', {
      sinif: 'alan', 'aria-label': 'IP atanacak cihaz türü',
      onchange: (e) => {
        if (e.target.value === yerel.hedefId) return;
        // Odaktaki liste çizimi bekletiyor (bkz. app.odakAcilirListede);
        // seçim bittiğine göre odak listeden çıkar.
        e.target.blur();
        yerel.hedefId = e.target.value;
        // Port seçimi eski hedefin cihazlarına göreydi; plan yeniden
        // kurulurken varsayılana (yeni hedefin portları) dönsün.
        yerel.portMetni = null;
        yerel.switchId = null;
        tazele();
      },
    }, IP_HEDEFLERI.map(h => el('option', {
      value: h.id, selected: h.id === aktif.id ? true : null, metin: h.ad,
    }))),
  ]);
}

// ── korunan portların keşfi ─────────────────────────────────────────────
// Koşunun dokunmaması gereken portlar (bilgisayarın takılı olduğu port ve
// switch'ler arası bağlantılar) elle giriliyordu. İkisi de switch'lerin
// MAC öğrenme tablosunda zaten yazılı; sormanın gereği yoktu ve yanlış
// girilen cevap iki kere zarar veriyordu — korunması gereken port
// korunmuyor, korunmaması gereken port koşudan düşüyordu.
//
// Bulgu bir kere alınıp bırakılmaz: kablo koşu başlamadan önce başka
// porta taşınmış olabilir. Ekran açıkken düzenli aralıkla yeniden
// doğrulanır; koşu başlarken sunucu da kendi tarafında yeniden bulur
// (bkz. panel_api /api/ip/kosu).
const KORUNAN_ARALIK = 30000;

let bulguSeti = null;         // bulgunun ait olduğu tren seti

// Elde işe yarar bir bulgu var mı? Cevabı gelmiş ama bilgisayarı
// bulamamış bir arama "yok" sayılır: koşu onsuz başlayamıyor.
function korunanBulundu() {
  const k = yerel.korunan;
  return !!(k && k.bilgisayar && k.bilgisayar.port);
}

async function korunanBul() {
  const setNo = durum.setNo;
  yerel.korunanAraniyor = true;
  try {
    const b = await api.ipKorunan(setNo);
    if (setNo !== durum.setNo) return;
    yerel.korunan = b;
  } catch (e) {
    if (setNo !== durum.setNo) return;
    yerel.korunan = {
      zaman: Date.now() / 1000, bilgisayar: { port: null, kaynak: 'yok' },
      portlar: [], denenen: [], not: e.message,
    };
  } finally {
    yerel.korunanAraniyor = false;
  }
}

// Aramayı yapar ve ekranı yeniden çizer. `ata` yeni bir nesne referansı
// ile çağrılır: durum içeriği değişmese de çizim tetiklensin.
async function korunanTazele() {
  await korunanBul();
  if (durum.gorunum === 'ip' && durum.ipDurum) {
    ata({ ipDurum: { ...durum.ipDurum } });
  }
}

// Hedef switch'te koşunun dokunmaması gereken portlar: [[no, sebep], …]
// Başka switch'e ait olanlar bu koşuyu bağlamaz.
function korumaliPortlar(plan) {
  const liste = (yerel.korunan && yerel.korunan.portlar) || [];
  return liste
    .filter(p => p.switchId === plan.switchId)
    .map(p => [Number(p.port), p.sebep])
    .sort((a, b) => a[0] - b[0]);
}

// ── port metni: "11-14, 18-19, 21" ──
// Sunucudaki ip_atama.metin_yap / portlar_ayristir ile aynı biçim. Metin
// burada da üretilip burada da çözülüyor, çünkü kullanıcı yazarken her
// tuşta sunucuya gitmek (ve hatalı metinde ekranı boşaltmak) doğru değil.
export function metinYap(portlar) {
  const p = [...new Set(portlar.map(Number))]
    .filter(Number.isInteger).sort((a, b) => a - b);
  if (!p.length) return '';
  const parca = [];
  let bas = p[0];
  let on = p[0];
  for (let i = 1; i <= p.length; i += 1) {
    const simdi = i < p.length ? p[i] : null;
    if (simdi === on + 1) { on = simdi; continue; }
    parca.push(bas === on ? String(bas) : `${bas}-${on}`);
    bas = simdi; on = simdi;
  }
  return parca.join(', ');
}

export function portlariAyristir(metin, izinli) {
  const cikan = [];
  for (const ham of String(metin || '').replace(/[;\s]+/g, ',').split(',')) {
    const parca = ham.trim();
    if (!parca) continue;
    if (parca.includes('-')) {
      const [a, b] = parca.split('-');
      const bas = Number(a);
      const son = Number(b);
      if (!Number.isInteger(bas) || !Number.isInteger(son) || son < bas
          || bas < 1 || a === '' || b === '') {
        return { portlar: [], hata: `Geçersiz port aralığı: ${parca}` };
      }
      for (let n = bas; n <= son; n += 1) cikan.push(n);
    } else {
      const n = Number(parca);
      if (!Number.isInteger(n) || n < 1) {
        return { portlar: [], hata: `Geçersiz port: ${parca}` };
      }
      cikan.push(n);
    }
  }
  if (izinli && izinli.length) {
    const küme = new Set(izinli);
    const disarida = [...new Set(cikan)].filter(n => !küme.has(n))
      .sort((a, b) => a - b);
    if (disarida.length) {
      return {
        portlar: [],
        hata: `Bu switch’te cihaz tanımlanmamış portlar: ${disarida.join(', ')}`,
      };
    }
  }
  return { portlar: [...new Set(cikan)].sort((a, b) => a - b), hata: '' };
}

// ── adresleme ───────────────────────────────────────────────────────────
// Cihazlar fabrikadan aynı adresle (10.1.1.12) geliyor; koşu portu açıp
// orada bulduğu cihaza DeviceMap'teki IP'yi yazıyor. Cihaz daha önce
// yapılandırılmışsa fabrika adresinde olmaz — o zaman verilen ağ taranır.
const IPV4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/;

function ipv4Mi(metin) {
  const m = IPV4.exec(String(metin || '').trim());
  return !!m && m.slice(1).every(p => Number(p) <= 255);
}

// Maske hem 255.255.255.0 hem de "24" biçiminde yazılabilir.
function maskeOnek(metin) {
  const ham = String(metin || '').trim();
  if (/^\d{1,2}$/.test(ham)) {
    const n = Number(ham);
    return n >= 0 && n <= 32 ? n : null;
  }
  if (!ipv4Mi(ham)) return null;
  const bit = ham.split('.').map(Number)
    .map(p => p.toString(2).padStart(8, '0')).join('');
  return /^1*0*$/.test(bit) ? bit.replace(/0/g, '').length : null;
}

const ARAMA_SINIRI = 512;      // core/ip_atama.ARAMA_SINIRI ile aynı

function ipSayi(metin) {
  return String(metin).trim().split('.')
    .reduce((t, p) => (t * 256) + Number(p), 0);
}

// Aranacak yer iki türlü verilebilir: ağ + maske ya da açık adres
// aralığı. Proje maskesi genişse (üst barda /8 gibi) ağı açmak milyonlarca
// adres demek; o kurulumda aranacak yeri daraltmanın tek yolu aralık.
// Aralık girilmişse ağ/maske hiç kullanılmaz (sunucuda da öyle).
function aramaDenetle(agMetni, maskeMetni, basMetni, sonMetni) {
  const bas = String(basMetni || '').trim();
  const son = String(sonMetni || '').trim();
  if (bas || son) {
    if (!bas || !son) {
      return 'Aralığın başlangıç ve bitiş adreslerini birlikte girin.';
    }
    if (!ipv4Mi(bas) || !ipv4Mi(son)) {
      return 'Aralıkta geçerli IPv4 adresleri kullanın.';
    }
    const adet = ipSayi(son) - ipSayi(bas) + 1;
    if (adet <= 0) return 'Bitiş adresi başlangıç adresinden önce olamaz.';
    if (adet > ARAMA_SINIRI) {
      return `Bu aralıkta ${adet} adres taranır; en fazla ${ARAMA_SINIRI} adres taranabilir.`;
    }
    return '';
  }
  const ag = String(agMetni || '').trim();
  const maske = String(maskeMetni || '').trim();
  if (!ag && !maske) return 'Arama ağı ile ağ maskesini girin.';
  if (!ipv4Mi(ag)) return 'Arama ağı geçerli bir IPv4 adresi olmalı';
  const onek = maskeOnek(maske);
  if (onek === null) return 'Maske 255.255.255.0 ya da 24 biçiminde olmalı';
  const adet = onek >= 31 ? 1 : (2 ** (32 - onek)) - 2;
  if (adet > ARAMA_SINIRI) {
    return `Bu ağ maskesiyle ${adet} adres taranır; en fazla ${ARAMA_SINIRI} `
      + 'adres taranabilir. Maskeyi daraltın veya bir adres aralığı girin.';
  }
  return '';
}

// Alandaki metnin tek denetim noktası: biçim + bu switch'te tanımlı olma
// + koşunun dokunmaması gereken portlar. Hata metni döner, yoksa ''.
function portDenetle(metin, izinli, plan) {
  const { portlar, hata: h } = portlariAyristir(metin, izinli);
  if (h) return h;
  const korumali = new Map(korumaliPortlar(plan));
  const carpisan = portlar.filter(p => korumali.has(p));
  if (carpisan.length) {
    const p = carpisan[0];
    return `Port ${p} IP atamaya dahil edilemez — ${korumali.get(p)}`;
  }
  return '';
}

// Ekrandaki bütün ayarların tek geçerlilik kaynağı. Üstteki durum metni,
// başlat düğmesi ve alan uyarıları aynı sonucu kullanır.
function kosuDenetle(veri) {
  const { plan, paneller = [] } = veri;
  const izinli = plan.izinliPortlar || [];
  const satirlar = plan.satirlar || [];
  const seciliMetin = yerel.portMetni ?? metinYap(
    satirlar.filter(s => s.uygulanabilir).map(s => s.port));
  const ayrisma = portlariAyristir(seciliMetin, izinli);
  const seciliPortSayisi = ayrisma.portlar.length;
  const planaDahil = satirlar.filter(s => s.uygulanabilir).length;
  const planDisi = satirlar.length - planaDahil;
  const panelIle = new Map(paneller.map(p => [p.switchId, p]));
  // Korunan portlar bulunmadan koşu başlatılmaz: hangi portun bizim
  // bağlantımızı taşıdığını bilmeden PoE kapatmak, kendi yolunu kesme
  // riski demek. Arama sürerken bu bir "hata" değil, bekleme durumu.
  const korunanHatasi = korunanBeklemeMetni();
  const portHatasi = ayrisma.hata || portDenetle(seciliMetin, izinli, plan);
  const hedef = gecerliHedef();
  const kapsamHatasi = !seciliPortSayisi
    ? 'IP atama için en az bir hedef port seçin'
    : !planaDahil ? `Seçili portlarda ${hedef.ad} bulunmuyor` : '';
  // Koşu switch'e kullanıcı adı/parola ile bağlanır. Kimlik yoksa iş
  // kuyruğa girip ilk adımda düşüyordu; başlamadan söylemek daha doğru.
  const aktifPanel = panelIle.get(plan.switchId);
  const kimlikHatasi = aktifPanel && aktifPanel.kimlikVar === false
    ? `${aktifPanel.switchAd} için kullanıcı adı ve parola girilmemiş.`
    : '';
  const grupHatasi = hedef.gruplar.some(g => !(plan.gruplar || []).includes(g))
    ? `${hedef.ad} hedefi bulunamadı` : '';
  const fabrika = yerel.fabrikaIp ?? plan.fabrikaIp ?? '';
  const fabrikaHatasi = ipv4Mi(fabrika)
    ? '' : 'Fabrika IP geçerli bir IPv4 adresi olmalı';
  const aramaHatasi = yerel.aramaAcik
    ? aramaDenetle(yerel.aramaAgi ?? plan.aramaAgi,
                   yerel.aramaMaskesi ?? plan.aramaMaskesi,
                   yerel.aramaBas, yerel.aramaSon)
    : '';
  const hataMetni = grupHatasi || fabrikaHatasi || aramaHatasi
    || korunanHatasi || portHatasi || kapsamHatasi || kimlikHatasi;
  return {
    grupHatasi,
    fabrika,
    fabrikaHatasi,
    aramaHatasi,
    kimlikHatasi,
    korunanHatasi,
    izinli,
    seciliMetin,
    seciliPortSayisi,
    planaDahil,
    planDisi,
    panelIle,
    portHatasi: portHatasi || (!seciliPortSayisi ? kapsamHatasi : ''),
    hata: hataMetni,
    hazir: !hataMetni,
  };
}

// Koşu özetindeki tek satırlık bilgisayar bilgisi: nerede bulundu ve
// bulgunun ne kadar tazelendiği. Ayrıntı (MAC, arayüz, hangi switch'e
// neden bakılamadığı) ipucu metninde durur — özet satırı kalabalıklaşmasın.
function pcOzeti() {
  const k = yerel.korunan;
  if (!k) {
    return { tamam: false, metin: yerel.korunanAraniyor ? 'aranıyor…' : '—',
      ipucu: 'Switch MAC tablolarından bulunuyor' };
  }
  const b = k.bilgisayar || {};
  if (!b.port) {
    const denenen = (k.denenen || []).map(d => `${d.ad}: ${d.durum}`).join(' · ');
    return { tamam: false, metin: 'bulunamadı',
      ipucu: [b.not || k.not, denenen].filter(Boolean).join(' — ') };
  }
  const yas = k.zaman ? ` · ${tazelik(k.zaman)} önce doğrulandı` : '';
  return {
    tamam: true,
    metin: `${b.switchAd} · p${b.port}`,
    ipucu: `MAC ${b.mac}${b.arayuz ? ` · ${b.arayuz}` : ''}${yas}`,
  };
}

// Korunan portlar henüz bilinmiyorsa koşu neden bekliyor?
//
// Hedef switch'te korunacak port bulunamamış olması tek başına hata
// değil: bilgisayar başka bir switch'te olabilir ve o switch'e giden
// bağlantı bu switch'in yüzünde görünmeyebilir. Asıl engel keşfin hiç
// çalışmamış olması — o zaman hangi portun bizim yolumuz olduğu
// bilinmiyor demektir.
function korunanBeklemeMetni() {
  if (yerel.korunanAraniyor && !yerel.korunan) {
    return 'Korunacak portlar switch MAC tablolarından bulunuyor…';
  }
  const k = yerel.korunan;
  if (!k) return 'Korunacak portlar henüz bulunmadı';
  const pcVar = !!(k.bilgisayar && k.bilgisayar.port);
  if (!pcVar) {
    return k.not || 'Bilgisayarın bağlı olduğu port bulunamadı — '
      + 'switch MAC tablosu okunamıyor';
  }
  return '';
}

export async function tazele() {
  const surum = ++tazeleSurumu;
  const setNo = durum.setNo;
  const secili = seciliGruplar();
  yerel.hataMetni = '';
  // Eski plan yeni seçimle karışmasın; istek boyunca başlatma kapalıdır.
  ata({ ipDurum: null });
  try {
    const plan = await api.ipPlan(
      setNo, secili.join(','), yerel.portMetni || '', yerel.switchId || '');
    // Her switch'in paneli ayrı uçtan gelir; biri okunamazsa (kimlik yok,
    // ulaşılamıyor) diğerleri yine çizilir.
    const paneller = await Promise.all(
      (plan.switchler || []).map(s => api.ipPanel(setNo, s.id)
        .catch(() => null)));
    if (surum !== tazeleSurumu || setNo !== durum.setNo) return;
    yerel.hataMetni = '';
    ata({ ipDurum: { plan, paneller: paneller.filter(Boolean) } });
    // Bulgu set başına geçerli: başka bir tren setinde bambaşka
    // switch'ler var.
    if (bulguSeti !== setNo) {
      bulguSeti = setNo;
      yerel.korunan = null;
    }
    // Arama switch'lere gider ve saniyeler sürebilir; ekran onu beklemesin
    // diye plan çizildikten SONRA başlatılır.
    //
    // BULUNAMAMIŞ bir bulgu da yeniden denenir. Sahadaki sıra şu: uygulama
    // açılıyor, tarama sürerken IP atama ekranına giriliyor, switch'in
    // kimliği henüz girilmediği için MAC tablosu okunamıyor. Kullanıcı
    // sonra şifreyi giriyor — `kilit.baglaYenile` bu ekranı tazeliyor ama
    // "bulgu zaten var" diye yeniden aranmıyor ve port hiç bulunamıyordu.
    // Başarılı bulgu yenilenmez; tazeliğinden KORUNAN_ARALIK turu sorumlu.
    if (!korunanBulundu()) korunanTazele();
  } catch (e) {
    if (surum !== tazeleSurumu || setNo !== durum.setNo) return;
    yerel.hataMetni = e.message;
    ata({ ipDurum: null });
  }
}

export function ciz(kok) {
  const veri = durum.ipDurum;
  const parcalar = [];
  const denetim = veri ? kosuDenetle(veri) : null;
  const ustDurum = veri
    ? denetim.hazir ? 'hazir' : 'hata'
    : yerel.hataMetni ? 'hata' : 'beklemede';
  const ustDurumMetni = veri
    ? denetim.hazir ? 'Plan hazır' : 'Ayarları kontrol edin'
    : yerel.hataMetni ? 'Plan kullanılamıyor' : 'Plan hazırlanıyor';
  const hazirlikYazisi = el('span', { metin: ustDurumMetni });
  const hazirlik = el('span', {
    sinif: 'ip-hazirlik', veri: { durum: ustDurum },
  }, [el('i', { 'aria-hidden': 'true' }), hazirlikYazisi]);
  const baslatDugmesi = el('button', {
    type: 'button', sinif: 'btn btn-birincil ip-baslat-btn',
    metin: 'IP atamayı başlat',
    disabled: !veri || !denetim.hazir,
    title: denetim && denetim.hata ? denetim.hata : 'IP atama işlemini başlat',
    onclick: baslat,
  });
  const ozetRozeti = veri ? el('span', {
    sinif: denetim.hazir ? 'rozet ip-hazir-rozet' : 'rozet ip-hata-rozet',
    metin: denetim.hazir ? 'Hazır' : 'Kontrol gerekli',
  }) : null;
  const kosuHataMetni = veri ? el('p', {
    sinif: 'ip-kosu-hatasi', role: 'alert', metin: denetim.hata,
    hidden: !denetim.hata,
  }) : null;

  // Alanlar yeniden çizilmeden doğrulanırken üst durum da anında güncellenir.
  function eylemDurumuGoster(d, bekleyenMetin = '') {
    const hazir = !!d.hazir && !bekleyenMetin;
    baslatDugmesi.disabled = !hazir;
    baslatDugmesi.title = d.hata || bekleyenMetin || 'IP atama işlemini başlat';
    hazirlik.dataset.durum = hazir ? 'hazir' : d.hata ? 'hata' : 'beklemede';
    hazirlikYazisi.textContent = hazir
      ? 'Plan hazır' : d.hata ? 'Ayarları kontrol edin' : bekleyenMetin;
    ozetRozeti.className = hazir
      ? 'rozet ip-hazir-rozet'
      : d.hata ? 'rozet ip-hata-rozet' : 'rozet ip-bekliyor-rozet';
    ozetRozeti.textContent = hazir
      ? 'Hazır' : d.hata ? 'Kontrol gerekli' : 'Veri bekleniyor';
    kosuHataMetni.textContent = d.hata || '';
    kosuHataMetni.hidden = !d.hata;
  }

  parcalar.push(el('div', { sinif: 'sayfa-basi ip-sayfa-basi' }, [
    // Başlık üç işlem ekranında da aynı: hangi ekranda olduğumuzu
    // altındaki sekme şeridi zaten söylüyor.
    el('h2', { metin: 'İşlemler' }),
    el('div', { sinif: 'ip-ust-eylem' }, [
      hazirlik,
      baslatDugmesi,
    ]),
  ]));

  parcalar.push(islemSekmeleri.ciz());
  parcalar.push(hedefSecici());
  if (kosuHataMetni) parcalar.push(kosuHataMetni);

  if (!veri) {
    parcalar.push(el('div', {
      sinif: yerel.hataMetni
        ? 'uyari ip-bos-durum' : 'bilgi ip-bos-durum ip-yukleniyor',
      role: yerel.hataMetni ? 'alert' : 'status',
      'aria-live': 'polite', 'aria-busy': String(!yerel.hataMetni),
    }, [
      yerel.hataMetni ? null : el('i', { 'aria-hidden': 'true' }),
      el('span', {
        metin: yerel.hataMetni || 'IP atama planı hazırlanıyor…',
      }),
    ]));
    doldur(kok, parcalar);
    return;
  }

  const { plan, paneller } = veri;
  const {
    izinli, seciliMetin, seciliPortSayisi, planaDahil, planDisi,
  } = denetim;

  // ── sol sütun: koşu ayarları ──
  const portUyari = el('p', {
    id: 'port-uyari', sinif: 'uyari', metin: denetim.portHatasi,
    role: 'alert', hidden: !denetim.portHatasi,
  });
  const portGiris = el('input', {
    id: 'ip-portlar', sinif: 'alan', value: seciliMetin,
    'aria-invalid': String(!!denetim.portHatasi),
    'aria-describedby': 'port-uyari',
    placeholder: '11-14, 18-19, 21', autocomplete: 'off', spellcheck: 'false',
    // Yazarken yalnız uyarı gösterilir; ekran yeniden çizilmez, yoksa
    // her tuşta odak alandan çıkardı.
    oninput: (e) => {
      const ayrisma = portlariAyristir(e.target.value, izinli);
      const h = portDenetle(e.target.value, izinli, plan)
        || (!ayrisma.portlar.length ? 'IP atama için en az bir hedef port seçin' : '');
      e.target.setAttribute('aria-invalid', String(!!h));
      portUyari.textContent = h;
      portUyari.hidden = !h;
      eylemDurumuGoster({ hazir: false, hata: h }, h ? '' : 'Planı güncelleyin');
    },
    onchange: (e) => {
      const { portlar, hata: ayristirmaHatasi } = portlariAyristir(
        e.target.value, izinli);
      if (ayristirmaHatasi || !portlar.length
          || portDenetle(e.target.value, izinli, plan)) return;
      yerel.portMetni = metinYap(portlar);
      tazele();
    },
  });

  function alanUyarisiGoster(giris, uyari, h) {
    giris.setAttribute('aria-invalid', String(!!h));
    uyari.textContent = h;
    uyari.hidden = !h;
  }

  // ── adresleme alanları ──
  // Fabrika IP: cihazların kutudan çıktığı adres (sahada hepsi aynı
  // adreste görünür — arp-scan'de 10.1.1.12'de beş cihaz birden).
  // Arama ağı: daha önce yapılandırılmış, yani fabrika adresinde
  // olmayan cihazlar için taranacak adresler.
  const fabrikaUyari = el('p', {
    id: 'ip-fabrika-hata', sinif: 'ip-alan-hata', role: 'alert',
    metin: denetim.fabrikaHatasi, hidden: !denetim.fabrikaHatasi,
  });
  const fabrikaGiris = el('input', {
    id: 'ip-fabrika', sinif: 'alan', value: denetim.fabrika,
    placeholder: plan.fabrikaIp || '10.1.1.12', autocomplete: 'off',
    spellcheck: 'false', inputmode: 'numeric',
    'aria-invalid': String(!!denetim.fabrikaHatasi),
    'aria-describedby': 'ip-fabrika-hata',
    oninput: (e) => {
      yerel.fabrikaIp = e.target.value.trim();
      const yeni = kosuDenetle(veri);
      alanUyarisiGoster(e.target, fabrikaUyari, yeni.fabrikaHatasi);
      eylemDurumuGoster(yeni);
    },
  });

  const aramaUyari = el('p', {
    id: 'ip-arama-hata', sinif: 'ip-alan-hata', role: 'alert',
    metin: denetim.aramaHatasi, hidden: !denetim.aramaHatasi,
  });
  const aramaAlani = (anahtar, id, etiket, varsayilan, ipucu) => el('label', {
    sinif: 'ayar-satir', for: id,
  }, [
    el('span', { sinif: 'etiket', metin: etiket }),
    el('input', {
      id, sinif: 'alan ip-orta-alan', value: yerel[anahtar] ?? varsayilan ?? '',
      placeholder: ipucu, autocomplete: 'off', spellcheck: 'false',
      'aria-describedby': 'ip-arama-hata',
      oninput: (e) => {
        yerel[anahtar] = e.target.value.trim();
        const yeni = kosuDenetle(veri);
        alanUyarisiGoster(e.target, aramaUyari, yeni.aramaHatasi);
        eylemDurumuGoster(yeni);
      },
    }),
  ]);

  const teknikAyrintilar = el('details', {
    sinif: 'kart kose ip-teknik-ayrintilar ip-acilir-bolum',
    open: yerel.acikBolumler.teknik,
    ontoggle: (e) => { yerel.acikBolumler.teknik = e.currentTarget.open; },
  }, [
    el('summary', { sinif: 'ip-teknik-ozet' }, [
      el('span', { metin: 'Teknik ayrıntılar' }),
      el('span', {
        sinif: 'soluk',
        metin: 'Plan kaynağı, ARP ve korunan bağlantılar',
      }),
    ]),
    el('div', { sinif: 'ip-teknik-icerik' }, [
      el('div', { sinif: 'satir' }, [
        el('span', { metin: 'Plan kaynağı' }),
        el('b', {
          title: 'Hedef IP ve port bilgileri DeviceMap dosyasından alınır',
          metin: 'Proje varsayılanı (DeviceMap)',
        }),
      ]),
      el('div', { sinif: 'ip-test-alani' }, [
        el('span', { sinif: 'ust-etiket', metin: 'Test aracı' }),
        // Tanı önce gelir: "ne oldu" sorusunun cevabı, cihazlara yazan
        // düğmeye basmadan önce alınabilmeli.
        el('button', {
          type: 'button', sinif: 'btn btn-kucuk',
          metin: 'Adres haritası',
          title: 'Aday adreslerde hangi cihaz var — cihazın kendi dahili '
            + 'numarasından okunur. Hiçbir şey yazılmaz.',
          onclick: adresHaritasi,
        }),
        el('button', {
          type: 'button', sinif: 'btn btn-kucuk btn-tehlike',
          metin: 'Fabrika IP’sine döndür',
          title: `Seçili cihazların IP adresini ${denetim.fabrika} olarak `
            + 'değiştirerek IP atamayı yeniden denemeye hazırlar',
          onclick: fabrikayaDondur,
        }),
      ]),
      // ARP önbelleğinin temizlenip temizlenemediği artık ekranda
      // yazmıyor: uygulama zaten yükseltilmiş yetkiyle açılıyor (bkz.
      // app.py) ve yetki uyarısının karşılığı her işletim sisteminde
      // başka bir cümleydi. Panel işletim sistemine göre konuşmaz.
      el('div', { sinif: 'satir' }, [
        el('span', { metin: 'Switch IP adresi' }),
        el('b', { metin: deger(plan.switchIp) }),
      ]),
      ...(plan.switchler || []).map(s => el('div', { sinif: 'satir' }, [
        el('span', { metin: s.ad }),
        el('b', {
          sinif: s.id === plan.switchId ? 'vurgu' : 'soluk',
          metin: s.id === plan.switchId
            ? plan.portMetni
            : (s.grupCihaz
              ? `${s.grupCihaz} cihaz · seçilmedi`
              : `${gecerliHedef().ad} yok`),
        }),
      ])),
      el('div', { sinif: 'satir' }, [
        el('span', { metin: 'Bilgisayar bağlantısı' }),
        el('b', {
          sinif: pcOzeti().tamam ? '' : 'soluk',
          title: pcOzeti().ipucu,
          metin: pcOzeti().metin,
        }),
      ]),
      ...korumaliPortlar(plan).map(([no, sebep]) => el('div', {
        sinif: 'satir korunan',
      }, [
        el('span', { metin: `Korunan port ${no}` }),
        el('b', { sinif: 'soluk', metin: sebep }),
      ])),
    ]),
  ]);

  const ayarKart = el('details', {
    sinif: 'kart kose ip-ayar-kart ip-acilir-bolum',
    open: yerel.acikBolumler.kapsam,
    ontoggle: (e) => { yerel.acikBolumler.kapsam = e.currentTarget.open; },
  }, [
    el('summary', { sinif: 'ip-kart-basi ip-acilir-ozet' }, [
      el('h3', { metin: 'IP ayarları' }),
      ozetRozeti,
    ]),
    el('fieldset', { sinif: 'ip-form-bolum ip-port-alani' }, [
      el('legend', { sinif: 'gizli-metin', metin: 'Hedef portlar' }),
      el('div', { sinif: 'ip-alan-baslik' }, [
        el('label', { sinif: 'etiket', for: 'ip-portlar', metin: 'Hedef portlar' }),
        el('span', {
          sinif: 'ip-alan-sayac', metin: `${seciliPortSayisi} port seçili`,
        }),
      ]),
      portGiris,
      portUyari,
      el('p', {
        sinif: 'ip-alan-yardim',
        metin: 'Aralık ve tek port birlikte yazılabilir: 11-14, 18-19, 21',
      }),
    ]),
    el('fieldset', { sinif: 'ayar-bolum' }, [
      el('legend', { sinif: 'gizli-metin', metin: 'Adresleme' }),
      el('div', { sinif: 'ip-alt-baslik' }, [
        el('span', { sinif: 'ust-etiket', metin: 'Adresleme' }),
      ]),
      el('label', { sinif: 'ayar-satir', for: 'ip-fabrika' }, [
        el('span', { sinif: 'etiket', metin: 'Fabrika IP adresi' }),
        fabrikaGiris,
      ]),
      fabrikaUyari,
      el('button', {
        type: 'button', sinif: 'onay', 'aria-pressed': String(yerel.aramaAcik),
        onclick: () => {
          yerel.aramaAcik = !yerel.aramaAcik;
          ata({ ipDurum: { ...veri } });
        },
      }, [
        el('span', { sinif: 'kutu', 'aria-hidden': 'true' }),
        el('span', { metin: 'Fabrika adresinde bulunamazsa ağda ara' }),
      ]),
      // "Yazıldı" ile "kalıcı yazıldı" aynı şey değil: cihaz ayarı yalnız
      // belleğine almış olabilir ve ilk güç kesintisinde eski adresine
      // döner. Kontrol koşuyu uzattığı için varsayılan kapalı.
      el('button', {
        type: 'button', sinif: 'onay', 'aria-pressed': String(yerel.kalicilik),
        title: 'Koşunun sonunda portların gücü bir kez kesilip açılır ve '
          + 'cihazların yeni adreslerinde döndüğü doğrulanır. Koşuyu uzatır.',
        onclick: () => {
          yerel.kalicilik = !yerel.kalicilik;
          ata({ ipDurum: { ...veri } });
        },
      }, [
        el('span', { sinif: 'kutu', 'aria-hidden': 'true' }),
        el('span', { metin: 'Kalıcılığı doğrula (sonda güç çevrimi)' }),
      ]),
      ...(yerel.aramaAcik ? [
        aramaAlani('aramaAgi', 'ip-arama-ag', 'Arama ağı',
          plan.aramaAgi, '10.1.1.0'),
        aramaAlani('aramaMaskesi', 'ip-arama-maske', 'Arama maskesi',
          plan.aramaMaskesi, '255.255.255.0'),
        // Açık aralık: proje maskesi geniş olduğunda (üst barda /8 gibi)
        // ağı açmak milyonlarca adres demek. Aralık girilirse yukarıdaki
        // ağ/maske ikilisi kullanılmaz.
        aramaAlani('aramaBas', 'ip-arama-bas', 'Aralık başlangıcı',
          '', '10.1.1.10'),
        aramaAlani('aramaSon', 'ip-arama-son', 'Aralık sonu',
          '', '10.1.1.60'),
        aramaUyari,
        el('p', {
          sinif: 'ip-alan-yardim',
          metin: 'Aralık girilirse ağ/maske yerine o taranır. Her iki '
            + `yolda da en fazla ${ARAMA_SINIRI} adres denenir; ağ maskesi `
            + 'bundan genişse aralık verin.',
        }),
      ] : []),
    ]),

    // ── özet: hangi switch'te ne yapılacak ──
    el('div', { sinif: 'ayar-ozet' }, [
      el('div', { sinif: 'ip-ozet-basi' }, [
        el('span', { sinif: 'ust-etiket', metin: 'İşlem özeti' }),
      ]),
      el('div', { sinif: 'satir' }, [
        el('span', { metin: 'Hedef' }),
        el('b', { metin: `${deger(plan.switch)} · ${plan.hedefSayi} cihaz` }),
      ]),
    ]),
  ]);

  // ── sağ sütun: switch başına bir ön panel ──
  const panelYigin = el('div', { sinif: 'panel-yigin' });
  canli.yigin = panelYigin;

  const yenilemeDugmesi = el('button', {
    type: 'button', sinif: 'btn btn-kucuk ip-yenile-btn',
    'aria-pressed': String(canli.acik),
    title: canli.acik
      ? 'Port durumlarının otomatik yenilenmesini duraklat'
      : 'Otomatik yenilemeyi sürdür',
    onclick: (e) => {
      canli.acik = !canli.acik;
      e.currentTarget.setAttribute('aria-pressed', String(canli.acik));
      e.currentTarget.textContent = canli.acik ? 'Yenileme açık' : 'Duraklatıldı';
      panelleriDurdur();
      tazelikTiki();
      if (canli.acik) {
        yenilemeTuru();                   // sürdürülünce hemen bir okuma
        korunanTuru();                    // korunan portlar da doğrulansın
      }
    },
    metin: canli.acik ? 'Yenileme açık' : 'Duraklatıldı',
  });

  const panelAlani = el('details', {
    sinif: 'ip-panel-alani ip-acilir-bolum',
    open: yerel.acikBolumler.paneller,
    ontoggle: (e) => { yerel.acikBolumler.paneller = e.currentTarget.open; },
  }, [
    el('summary', { sinif: 'ip-bolum-basi ip-acilir-ozet' }, [
      el('div', { sinif: 'ip-bolum-baslik' }, [
        el('div', {}, [
          el('h3', { metin: 'Switch ve portlar' }),
          el('p', {
            metin: 'Canlı port durumlarını inceleyin ve hedef portları seçin.',
          }),
        ]),
      ]),
      el('span', {
        sinif: 'ip-bolum-sayac', metin: `${paneller.length} panel`,
      }),
    ]),
    el('div', { sinif: 'ip-bolum-eylem ip-panel-araclari' }, [
      yenilemeDugmesi,
    ]),
    panelYigin,
    paneller.length ? lejant() : null,
  ]);
  panelleriCiz(veri);
  yenilemeyiKur();

  parcalar.push(el('div', { sinif: 'ip-izgara' }, [ayarKart, panelAlani]));
  parcalar.push(teknikAyrintilar);

  // ── altta plan tablosu ──
  parcalar.push(el('details', {
    sinif: 'ip-plan-bolum ip-acilir-bolum',
    open: yerel.acikBolumler.plan ?? planDisi > 0,
    ontoggle: (e) => { yerel.acikBolumler.plan = e.currentTarget.open; },
  }, [
    el('summary', { sinif: 'ip-bolum-basi ip-acilir-ozet' }, [
      el('div', { sinif: 'ip-bolum-baslik' }, [
        el('div', {}, [
          el('h3', { metin: 'Atama planı' }),
          el('p', {
            metin: 'Mevcut ve hedef IP adreslerini inceleyin.',
          }),
        ]),
      ]),
      el('div', { sinif: 'ip-plan-metrikler' }, [
        el('span', {}, [el('b', { metin: String(planaDahil) }), ' dahil']),
        planDisi ? el('span', {}, [el('b', { metin: String(planDisi) }), ' kapsam dışı']) : null,
      ]),
    ]),
    el('div', { sinif: 'tablo-sar ip-plan-tablo' }, [
      el('div', { sinif: 'tablo', stil: '--tablo-min:800px' }, [
        el('div', { sinif: 'tablo-basi', stil: `--tablo-kolon:${KOLON}` },
          ['Port', 'Hedef cihaz', 'Grup', 'Fabrika IP', 'Atanacak IP', 'Durum']
            .map(b => el('span', { metin: b }))),
        ...(plan.satirlar.length
          ? plan.satirlar.map(p => el('div', {
              sinif: 'tablo-satir ip-plan-satir',
              stil: `--tablo-kolon:${KOLON}`,
              veri: { uygun: p.uygulanabilir ? '1' : '0' },
            }, [
              el('span', { sinif: 'ip-port-rozet', metin: `p${p.port}` }),
              el('span', { sinif: 'mono kirp ip-cihaz-adi', metin: p.ad }),
              el('span', {
                sinif: 'mono kirp ip-grup-adi', metin: p.grup || YOK,
              }),
              // Fabrika adresi kullanıcı değiştirdiyse tabloda da o görünür.
              el('span', {
                sinif: 'mono orta ip-adres',
                metin: denetim.fabrika || p.fabrika,
              }),
              el('span', { sinif: 'mono ip-adres ip-hedef-ip', metin: p.hedefIp }),
              el('span', {
                sinif: p.uygulanabilir
                  ? 'ip-durum-rozet dahil' : 'ip-durum-rozet disarida',
              }, [
                el('i', { 'aria-hidden': 'true' }),
                p.uygulanabilir ? 'Plana dahil' : 'Hedef grup dışında',
              ]),
            ]))
          : [el('div', {
              sinif: 'tablo-bos', metin: 'Seçili portlarda hedef cihaz yok',
            })]),
      ]),
    ]),
  ]));

  doldur(kok, parcalar);
}

// ── ön panel ────────────────────────────────────────────────────────────
// Konnektör çizimi kardeş projedeki (Switch Yönetim Paneli) biçimin
// aynısı: PoE portu 4 pinli, uplink 8 pinli ve ortasında çarpı. Aynı
// switch'e bakan iki panelde port kutusunun aynı görünmesi, hangi porta
// baktığını saymadan bulmayı sağlıyor.
function pinHalka(n, r) {
  return Array.from({ length: n }, (_, i) => {
    const a = (i / n) * Math.PI * 2 - Math.PI / 2;
    return [20 + r * Math.cos(a), 20 + r * Math.sin(a)];
  });
}

function konnektorSvg(poe) {
  const pinler = pinHalka(poe ? 4 : 8, poe ? 6.6 : 7.2);
  const r = poe ? 2.5 : 1.9;
  const ns = 'http://www.w3.org/2000/svg';
  const s = document.createElementNS(ns, 'svg');
  s.setAttribute('viewBox', '0 0 40 40');
  s.setAttribute('aria-hidden', 'true');
  const ekle = (etiket, ozellik) => {
    const c = document.createElementNS(ns, etiket);
    for (const [k, v] of Object.entries(ozellik)) c.setAttribute(k, String(v));
    s.append(c);
  };
  ekle('circle', { class: 'shell', cx: 20, cy: 20, r: 18.4 });
  ekle('circle', { class: 'inner', cx: 20, cy: 20, r: 12.2 });
  if (!poe) ekle('path', { class: 'cross', d: 'M13 13 L27 27 M27 13 L13 27' });
  ekle('rect', { class: 'key', x: 18.6, y: 1.6, width: 2.8, height: 4.2 });
  for (const [x, y] of pinler) {
    ekle('circle', { class: 'pin', cx: x.toFixed(2), cy: y.toFixed(2), r });
  }
  return s;
}

function bosHucre(sinif) {
  return el('div', { sinif: sinif || 'pm-bos' });
}

// Portun CANLI durumu — konnektörün rengi. Sınıflar ve ayrım Switch
// Yönetim Paneli'ndeki durumSinifi() ile aynı: aynı switch'e iki
// uygulamadan bakan kişi aynı rengi görsün.
//   off     — port kapalı (veri yok)
//   feed    — PoE portu güç veriyor (bağlı + watt okunuyor)
//   link    — hat ayakta ama güç yok / PoE değil
//   (boş)   — bağlı değil
//   gucsuz  — port açık, PoE kapalı: hat çalışır, güç yok
function canliSinif(p) {
  if (p.acik === null) return '';          // canlı okuma yok (DeviceMap)
  if (!p.acik) return 'off';
  let sinif = (p.poeVar && p.link === 'up' && p.guc) ? 'feed'
    : p.link === 'up' ? 'link' : '';
  if (p.poeVar && p.poeMod === '0') sinif += ' gucsuz';
  return sinif.trim();
}

// Tek konnektör. Renk portun o anki durumunu, çerçeve ise koşudaki rolünü
// gösterir: hedef portlar mavi çerçeveyle işaretlenir. İkisini tek renge
// bindirmek "bu port açık mı, seçili mi" sorusunu birbirine karıştırıyordu.
function portDugmesi(p, ctx) {
  const roller = [canliSinif(p)];
  const koruma = ctx.koruma.get(p.no);
  if (p.no === ctx.pcPort) roller.push('pc');
  else if (koruma) roller.push('bag');
  else if (ctx.hedef.has(p.no)) roller.push('sec');
  if (!p.tanimli) roller.push('bos');

  const durumMetni = p.acik === null ? ''
    : !p.acik ? ' · port kapalı'
      : p.poeVar && p.poeMod === '0' ? ' · güç kapalı'
        : p.link === 'up' ? (p.guc ? ` · besliyor (${p.guc} W)` : ' · bağlı')
          : ' · boş';
  const kilitli = !!koruma || p.no === ctx.pcPort;
  const aciklama = kilitli
    ? `Port ${p.no} · ${koruma || 'bilgisayar bu portta'} · IP atamaya dahil edilmez`
    : (p.tanimli
      ? `Port ${p.no} · ${p.cihaz}${durumMetni}`
      : `Port ${p.no} · cihaz tanımlı değil${durumMetni}`)
      + (ctx.aktif ? '' : ` · ${ctx.switchAd} switch'ine geçer`);
  return el('button', {
    type: 'button', sinif: `pm-port ${roller.join(' ')}`.trim(),
    'aria-pressed': String(ctx.hedef.has(p.no)),
    'aria-label': aciklama,
    'aria-disabled': String(!p.tanimli || kilitli),
    disabled: !p.tanimli,
    title: aciklama,
    onclick: kilitli ? null : () => portTikla(p.no, ctx),
  }, [
    konnektorSvg(p.poe),
    el('span', { metin: String(p.no) }),
  ]);
}

function panelKarti(panel, plan) {
  const aktif = panel.switchId === plan.switchId;
  const bilgi = (plan.switchler || []).find(s => s.id === panel.switchId);
  const grupCihaz = bilgi ? bilgi.grupCihaz : null;
  const hedef = new Set(
    aktif ? plan.satirlar.filter(s => s.uygulanabilir).map(s => s.port) : []);
  // Korunan portlar keşiften gelir (bkz. korunanBul). Bilgisayarın portu
  // yalnız bağlı olduğu switch'te "bilgisayar" rengiyle işaretlenir;
  // diğer switch'lerde aynı MAC'in göründüğü port o switch'e giden
  // bağlantıdır ve o renkle çizilir. Ekranda ayrı bir form yok — bu
  // panel, keşfin ne bulduğunu gösteren tek yer.
  const koruma = new Map();
  for (const p of (yerel.korunan && yerel.korunan.portlar) || []) {
    if (p.switchId === panel.switchId && p.tur !== 'bilgisayar') {
      koruma.set(Number(p.port), p.sebep);
    }
  }
  const pcBilgi = (yerel.korunan && yerel.korunan.bilgisayar) || null;
  const ctx = {
    hedef,
    aktif,
    koruma,
    switchId: panel.switchId,
    switchAd: panel.switchAd,
    pcPort: (pcBilgi && pcBilgi.switchId === panel.switchId && pcBilgi.port)
      ? Number(pcBilgi.port) : null,
  };

  const idIle = {};
  for (const p of panel.portlar) idIle[p.no] = p;
  const poeN = panel.poeSayisi || 24;
  const uplinkN = panel.uplinkSayisi || 4;
  const sutun = Math.max(1, Math.ceil(poeN / 4));

  const izgara = el('div', {
    sinif: 'pm-izgara',
    stil: `--pm-sutun:${sutun}`,
  });
  // Fiziksel yerleşim: 4 satır, PoE sütunları aşağıdan yukarı numaralı,
  // en sağda uplink sütunu (yukarıdan aşağı).
  for (let satir = 4; satir >= 1; satir -= 1) {
    for (let c = 0; c < sutun; c += 1) {
      const p = idIle[satir + c * 4];
      izgara.append(p ? portDugmesi(p, ctx) : bosHucre());
    }
    izgara.append(bosHucre('pm-ayrac'));
    // Uplink sütunu yukarıdan aşağı numaralanır (28…25) — kardeş paneldeki
    // dizilimin aynısı.
    const u = satir <= uplinkN ? idIle[poeN + satir] : null;
    izgara.append(u ? portDugmesi(u, ctx) : bosHucre());
  }

  const panelYonergesi = grupCihaz === 0
    ? 'Seçili hedef grupta bu switch üzerinde cihaz bulunmuyor.'
    : 'Bu switch\'i etkinleştirmek için tanımlı bir porta tıklayın.';

  return el('article', {
    sinif: 'kart kose on-panel', veri: { aktif: aktif ? '1' : '0' },
  }, [
    el('header', { sinif: 'ip-switch-basi' }, [
      el('div', { sinif: 'ip-switch-kimlik' }, [
        el('div', { sinif: 'ip-switch-ad' }, [
          el('i', { 'aria-hidden': 'true' }),
          el('h4', { metin: panel.switchAd || 'Switch' }),
        ]),
        el('span', { sinif: 'mono', metin: panel.switchIp }),
      ]),
      el('div', { sinif: 'ip-switch-rozetler' }, [
        // Verinin tazeliği: canlı okuma varsa kaç saniye önce alındığı
        // saniyede bir tazelenir (bkz. tazelikYaz).
        panel.kaynak === 'switch' ? el('span', {
          sinif: 'ip-tazelik', veri: { okuma: panel.okumaZamani || 0 },
          title: 'Port durumlarının en son okunma zamanı',
          metin: '0 sn önce',
        }) : null,
        el('span', {
          sinif: panel.kaynak === 'switch'
            ? 'rozet ip-kaynak-rozet canli' : 'rozet ip-kaynak-rozet',
          metin: panel.kaynak === 'switch' ? 'Canlı veri' : 'Proje varsayılanı',
          title: panel.kaynak === 'switch'
            ? 'Port durumları switch\'ten okundu'
            : 'Port durumu okunamadı; yerleşim DeviceMap\'ten çizildi',
        }),
        // Kimlik yoksa koşu başlayamaz; girecek yer de burası olmalı.
        panel.kimlikVar === false ? el('button', {
          type: 'button', sinif: 'btn btn-kucuk ip-kimlik-btn',
          metin: 'Giriş bilgilerini gir',
          title: `${panel.switchAd} için kullanıcı adı ve parola girin.`,
          onclick: () => switchKimligi(panel),
        }) : null,
      ]),
    ]),
    aktif ? null : el('p', { sinif: 'ip-switch-yonerge', metin: panelYonergesi }),
    // Panelin okunamama sebebi tek satır olarak durur; her switch için
    // ayrı bir kutu, iki switch'te aynı cümleyi iki kez gösteriyordu.
    panel.not
      ? el('p', { sinif: 'ip-panel-not', metin: panel.not })
      : null,
    // Uyarı yalnız etkin switch'te: koşu orada yürüyecek. Diğer switch'te
    // kimlik eksikliği bir engel değil, "Kimlik gir" düğmesi yeterli.
    aktif && panel.kimlikVar === false
      ? el('p', {
          sinif: 'ip-panel-not uyari-ton',
          metin: 'Giriş bilgileri girilmediği için IP atama başlatılamaz.',
        })
      : null,
    el('div', { sinif: 'pm-kasa' }, [
      el('div', { sinif: 'pm-sar' }, [izgara]),
      el('div', { sinif: 'pm-alt' }, [
        el('span', { metin: `PoE 1-${poeN}` }),
        el('span', { stil: 'flex:1' }),
        el('span', { metin: `Uplink ${poeN + 1}-${poeN + uplinkN}` }),
      ]),
    ]),
  ]);
}

// Lejant bölümde bir kez durur. Her panel kartında tekrar edince iki
// switch'te altı madde iki kez yazılıyordu ve panelden çok yer kaplıyordu.
function lejant() {
  return el('div', { sinif: 'panel-lejant' }, [
    el('span', {}, [el('i', { sinif: 'pm-ornek sec' }), 'Hedef port']),
    el('span', {}, [el('i', { sinif: 'pm-ornek pc' }), 'Bilgisayar portu']),
    el('span', {}, [el('i', { sinif: 'pm-ornek bag' }), 'Switch bağlantısı']),
    el('span', {}, [el('i', { sinif: 'pm-ornek feed' }), 'Besliyor']),
    el('span', {}, [el('i', { sinif: 'pm-ornek link' }), 'Bağlı']),
    el('span', {}, [el('i', { sinif: 'pm-ornek off' }), 'Port kapalı']),
    el('span', {}, [el('i', { sinif: 'pm-ornek bos' }), 'Cihaz tanımlı değil']),
  ]);
}

// Switch'in kullanıcı adı/parolası bu ekrandan girilebilir. Eskiden tek
// yol kilit menüsüydü; oraya da ancak tam tarama yapılınca cihaz düşüyordu.
// Yani hiç tarama yapmadan IP atamaya gelen kullanıcının önü kapalıydı:
// koşu "kimlik girilmemiş" diye düşüyor, kimliği girecek yer görünmüyordu.
function switchKimligi(panel) {
  const cihaz = (durum.cihazlar || []).find(c => c.id === panel.switchId);
  if (!cihaz) {
    bildir('Switch kaydı yüklenmedi — sayfayı yenileyin');
    return;
  }
  kimlikDiyalogu(cihaz, () => tazele());
}

function portTikla(no, ctx) {
  const plan = durum.ipDurum && durum.ipDurum.plan;
  if (!plan) return;
  // Başka switch'in portuna tıklamak koşuyu o switch'e taşır; oradaki
  // seçim de o portla başlar.
  if (!ctx.aktif) {
    yerel.switchId = ctx.switchId;
    yerel.portMetni = String(no);
    tazele();
    return;
  }
  const mevcut = new Set(plan.satirlar.filter(s => s.uygulanabilir).map(s => s.port));
  if (mevcut.has(no)) mevcut.delete(no); else mevcut.add(no);
  yerel.portMetni = metinYap([...mevcut]);
  tazele();
}

// ── tanı: adres haritası ────────────────────────────────────────────────
// "Hangi adreste hangi cihaz var" sorusu sahada en çok sorulan şey ve
// cevabı şimdiye kadar yalnız dış araçlarla (arp-scan) ve o da MAC
// düzeyinde alınabiliyordu. Cihaz kendi dahilisini söylediği için panel
// bunu kesin biçimde yanıtlayabiliyor: "10.1.1.13'teki cihaz aslında port
// 22'nin cihazı".
const HARITA_DURUM = {
  bos: ['soluk', 'Boş'],
  yerinde: ['tamam', 'Yerinde'],
  yabanci: ['uyari', 'Başka cihaz'],
  cakisma: ['hata', 'Çakışma'],
  taninmiyor: ['uyari', 'Tanınmıyor'],
};

const HARITA_KOLON = '120px 1fr 1fr 90px';

function haritaSatiri(s) {
  const [sinif, etiket] = HARITA_DURUM[s.durum] || ['soluk', s.durum];
  const kim = s.bulunan.length
    ? s.bulunan.map(b => (b.port
      ? `${b.ad || b.dahili} · port ${b.port}`
      : `dahili ${b.dahili || '?'}`)).join(' + ')
    : '—';
  const beklenen = s.fabrikaMi
    ? 'fabrika adresi'
    : (s.beklenenPort ? `${s.beklenenAd} · port ${s.beklenenPort}` : '—');
  return el('div', {
    sinif: 'tablo-satir', stil: `--tablo-kolon:${HARITA_KOLON}`,
  }, [
    el('span', { sinif: 'mono', metin: s.ip }),
    el('span', { sinif: 'soluk', metin: beklenen }),
    el('span', { sinif: s.bulunan.length ? '' : 'soluk', metin: kim }),
    el('span', {}, [el('span', { sinif: `rozet ${sinif}`, metin: etiket })]),
  ]);
}

async function adresHaritasi() {
  const veri = durum.ipDurum;
  const plan = veri && veri.plan;
  if (!plan) return;
  const denetim = kosuDenetle(veri);
  const govde = el('div', {}, [
    el('p', { sinif: 'aciklama', metin: 'Adresler yoklanıyor…' }),
  ]);
  diyalog.ac({ baslik: 'Adres haritası', icerik: govde, eylemler: [
    el('button', {
      type: 'button', sinif: 'btn', metin: 'Kapat',
      onclick: () => diyalog.kapat(),
    }),
  ] });
  try {
    const h = await api.ipHarita(durum.setNo, plan.switchId,
                                (plan.gruplar || [])[0] || 'Intercom',
                                denetim.fabrika);
    const s = h.sayilar || {};
    govde.replaceChildren(
      el('p', { sinif: 'aciklama' }, [
        `${s.cihaz || 0} cihaz görüldü · ${s.yerinde || 0} yerinde · `
        + `${s.yabanci || 0} başka adreste · ${s.cakisma || 0} çakışma`,
      ]),
      el('div', { sinif: 'tablo-sar' }, [
        el('div', { sinif: 'tablo', stil: '--tablo-min:560px' }, [
          el('div', {
            sinif: 'tablo-basi', stil: `--tablo-kolon:${HARITA_KOLON}`,
          }, ['Adres', 'DeviceMap’te kimin', 'Şu an kim var', 'Durum']
            .map(b => el('span', { metin: b }))),
          ...(h.satirlar || []).map(haritaSatiri),
        ]),
      ]),
      // Çakışma tek yoklamayla görünmez; kaç tur bakıldığı ve ARP
      // temizliğinin çalışıp çalışmadığı sonucun güvenilirliğini belirler.
      el('p', {
        sinif: h.arpTemizlik ? 'bilgi' : 'uyari', stil: 'margin-top:10px',
        metin: h.arpTemizlik
          ? 'Aynı adreste birden çok cihaz, adres birkaç kez yoklanarak '
            + 'bulunur; "Çakışma" satırları bu şekilde ortaya çıkar.'
          : 'ARP önbelleği temizlenemiyor: aynı adresteki cihazların hepsi '
            + 'görünmemiş olabilir.',
      }),
    );
  } catch (e) {
    govde.replaceChildren(el('p', { sinif: 'uyari', metin: e.message }));
  }
}

// ── test akışı: cihazları fabrika adresinde topla ───────────────────────
// Koşuyu baştan denemek için gereken başlangıç durumunu kurar. Cihazlara
// yalnız "IP'ni şu adrese çevir" isteği gider; PoE'ye ve switch'e
// dokunulmaz. İşlem sonunda hepsi AYNI adreste olacağı için onay istenir.
function fabrikayaDondur() {
  const veri = durum.ipDurum;
  const plan = veri && veri.plan;
  if (!plan) return;
  const denetim = kosuDenetle(veri);
  const hedefler = plan.satirlar.filter(s => s.uygulanabilir);
  if (!hedefler.length) {
    hata(`Seçili portlarda ${gecerliHedef().ad} yok`);
    return;
  }
  diyalog.ac({
    baslik: 'Fabrika IP’sine döndür',
    icerik: el('div', {}, [
      el('p', { sinif: 'aciklama' }, [
        `${hedefler.length} cihazın IP adresi ${denetim.fabrika} olarak `
        + 'değiştirilecek. Cihazlar yeniden başlatılacağı ve aynı IP adresini '
        + 'kullanacağı için geçici adres çakışması oluşacaktır.',
      ]),
      el('p', {
        sinif: 'bilgi', stil: 'margin-top:10px',
        metin: 'Bu test aracı, IP atamayı yeniden denemek için başlangıç '
          + 'durumunu hazırlar. PoE portlarına dokunmaz. Cihazlar '
          + 'DeviceMap’teki adreslerinde değilse ya da iki cihaz aynı '
          + 'adreste kaldıysa, adresler boşalana kadar tur tekrarlanır.',
      }),
      // Aynı adresteki cihazlara sırayla ulaşmanın tek güvenilir yolu ARP
      // önbelleğini temizlemek. Yetki yoksa işlem yine çalışır ama
      // kaydın kendiliğinden dönmesini bekler ve sonuç eksik kalabilir;
      // kullanıcı bunu düğmeye basmadan önce bilmeli.
      plan.arpTemizlik === false
        ? el('p', {
            sinif: 'uyari', stil: 'margin-top:10px',
            metin: 'ARP önbelleği temizlenemiyor (yönetici/root yok). Aynı '
              + 'adreste birden çok cihaz varsa hepsine tek turda '
              + 'ulaşılamaz; işlem bekleyip tekrar dener ve sonuç eksik '
              + 'kalabilir. Kesin sonuç için uygulamayı yönetici/sudo ile '
              + 'başlatın.',
          })
        : null,
      // Fabrika adresi tren setine göre çözülmüyor (hep 10.1.1.12).
      // Bilgisayar başka bir ağdaysa cihazlar bu yazımdan sonra
      // görünmez olur ve koşu onları bulamaz — geri almanın yolu da
      // cihaza ulaşmaktan geçtiği için önce söylenmeli.
      el('p', {
        sinif: 'uyari', stil: 'margin-top:10px',
        metin: `Cihazların IP adresi ${denetim.fabrika} olarak değiştirilir. `
          + 'Bilgisayarınız bu ağa erişemiyorsa cihazlar işlemden sonra görünmez olur; '
          + 'setin kendi ağında kalsınlar istiyorsanız yukarıdaki '
          + '"Fabrika IP adresi" alanını değiştirin.',
      }),
    ]),
    eylemler: [
      el('button', {
        type: 'button', sinif: 'btn', metin: 'Vazgeç',
        onclick: () => diyalog.kapat(),
      }),
      el('button', {
        type: 'button', sinif: 'btn btn-tehlike', metin: 'Fabrika IP’sine döndür',
        onclick: async () => {
          diyalog.kapat();
          try {
            const y = await api.ipFabrika({
              set: durum.setNo,
              switch: plan.switchId,
              gruplar: plan.gruplar || [],
              portlar: yerel.portMetni ?? plan.portMetni,
              fabrikaIp: denetim.fabrika,
              // Cihaz DeviceMap'teki adresinde olmayabilir; koşuda olduğu
              // gibi burada da aranacak yer verilebilir.
              aramaAgi: yerel.aramaAcik ? (yerel.aramaAgi ?? plan.aramaAgi) : '',
              aramaMaskesi: yerel.aramaAcik
                ? (yerel.aramaMaskesi ?? plan.aramaMaskesi) : '',
              aramaBas: yerel.aramaAcik ? (yerel.aramaBas || '') : '',
              aramaSon: yerel.aramaAcik ? (yerel.aramaSon || '') : '',
            });
            ata({ kuyrukAcik: true, acikIs: y.id });
            if (y.yeni === false) bildir('Bu switch için zaten bir iş var');
            else basari('Fabrika adresine döndürme kuyruğa alındı');
          } catch (e) {
            hata(e.message);
          }
        },
      }),
    ],
  });
}

async function baslat() {
  const veri = durum.ipDurum;
  const plan = veri && veri.plan;
  if (!plan) return;
  const denetim = kosuDenetle(veri);
  if (!denetim.hazir) {
    hata(denetim.hata);
    return;
  }
  try {
    const y = await api.ipKosu({
      set: durum.setNo,
      switch: plan.switchId,
      gruplar: plan.gruplar || [],
      portlar: yerel.portMetni ?? plan.portMetni,
      fabrikaIp: denetim.fabrika,
      aramaAgi: yerel.aramaAcik ? (yerel.aramaAgi ?? plan.aramaAgi) : '',
      aramaMaskesi: yerel.aramaAcik
        ? (yerel.aramaMaskesi ?? plan.aramaMaskesi) : '',
      aramaBas: yerel.aramaAcik ? (yerel.aramaBas || '') : '',
      aramaSon: yerel.aramaAcik ? (yerel.aramaSon || '') : '',
      kalicilik: !!yerel.kalicilik,
      // Sunucu korunan portları koşu başlarken KENDİSİ bulur; bu liste
      // yalnız o an switch cevap vermezse kullanılacak son bilgidir.
      korunan: (yerel.korunan && yerel.korunan.portlar) || [],
    });
    ata({ kuyrukAcik: true, acikIs: y.id });
    if (y.yeni === false) bildir('Bu switch için bir IP atama işlemi zaten sürüyor');
    else basari('IP atama işlemi kuyruğa alındı');
  } catch (e) {
    hata(e.message);
  }
}

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

import { el, doldur } from '../core/dom.js';
import { api } from '../core/api.js';
import { durum, ata } from '../core/durum.js';
import * as serit from '../parts/serit.js';
import * as diyalog from '../parts/diyalog.js';
import { kimlikDiyalogu } from '../parts/kilit.js';
import { hata, basari, bildir } from '../parts/bildirim.js';
import { deger, YOK } from '../core/bicim.js';

const KOLON = '68px minmax(150px,1.25fr) minmax(104px,.85fr) 112px 112px '
  + 'minmax(150px,1fr)';

const yerel = {
  gruplar: null,           // null = şeritteki ilk grup; yoksa seçili adlar
  portMetni: null,         // null = plandaki varsayılan (grubun portları)
  fabrikaIp: null,         // null = plandaki varsayılan (10.1.1.12)
  aramaAcik: false,        // fabrika adresinde bulunamayanları ağda ara
  aramaAgi: null,
  aramaMaskesi: null,
  aramaBas: null,          // açık adres aralığı — verilirse ağ/maske yerine
  aramaSon: null,
  pcPort: '24',
  pcSwitchId: null,        // null = ilk switch
  baglanti: {},            // switchId -> diğer switch'e giden port (metin)
  switchId: null,          // null = planın kendi seçtiği switch
  hataMetni: '',
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
  yigin: null,          // panel kartlarının kabı
};

function panelleriDurdur() {
  clearTimeout(canli.zaman);
  clearTimeout(canli.sayac);
  canli.zaman = canli.sayac = null;
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
  if (!ekrandaMi()) return;
  tazelikYaz();
  canli.sayac = setTimeout(tazelikTiki, 1000);
}

async function yenilemeTuru() {
  clearTimeout(canli.zaman);
  if (!ekrandaMi() || !canli.acik) return;
  try {
    await panelleriTazele();
  } catch { /* gösterge zaten "kaç sn önce" ile bayatlığı söylüyor */ }
  if (!ekrandaMi() || !canli.acik) return;
  canli.zaman = setTimeout(yenilemeTuru, YENILEME_ARALIK);
}

function yenilemeyiKur() {
  panelleriDurdur();
  tazelikTiki();
  if (canli.acik) canli.zaman = setTimeout(yenilemeTuru, YENILEME_ARALIK);
}

// Birden çok cihaz grubu aynı koşuda seçilebilir; her grubun atama betiği
// ayrı olduğu için koşu grup grup yürür. "Tümü" tek başına anlamlı: onu
// seçmek diğerlerini bırakır, başka bir grubu seçmek de "Tümü"yü kaldırır.
const TUMU = 'Tümü';

function seciliGruplar() {
  const liste = serit.gruplar('ip').map(g => g.ad);
  const secili = (yerel.gruplar || []).filter(ad => liste.includes(ad));
  if (secili.length) return secili;
  const ilk = serit.gecerliGrup('ip');
  return ilk ? [ilk.ad] : [];
}

function grupSec(ad) {
  const simdiki = seciliGruplar();
  let yeni;
  if (ad === TUMU) {
    yeni = simdiki.includes(TUMU) ? [] : [TUMU];
  } else if (simdiki.includes(ad)) {
    yeni = simdiki.filter(x => x !== ad);
  } else {
    yeni = [...simdiki.filter(x => x !== TUMU), ad];
  }
  yerel.gruplar = yeni;
  // Grup değişince port seçimi de sıfırlanır: önceki grubun portları yeni
  // seçimde anlamsız, hatta başka bir switch'e ait olabilir.
  yerel.portMetni = null;
  yerel.switchId = null;
  tazele();
}

// Bilgisayarın bağlı olduğu switch. Seçilmediyse ilk switch varsayılır;
// tek switch'li projede zaten tek seçenek var.
function pcSwitchId(plan) {
  const liste = plan.switchler || [];
  if (yerel.pcSwitchId && liste.some(s => s.id === yerel.pcSwitchId)) {
    return yerel.pcSwitchId;
  }
  return liste.length ? liste[0].id : null;
}

// Hedef switch'te koşunun dokunmaması gereken portlar: [[no, sebep], …]
// Bilgisayar başka switch'teyse onun portu bu koşuyu bağlamaz.
function korumaliPortlar(plan) {
  const cikan = new Map();
  const pc = Number(yerel.pcPort);
  if (Number.isInteger(pc) && pcSwitchId(plan) === plan.switchId) {
    cikan.set(pc, 'bilgisayar bu portta');
  }
  const bag = Number(yerel.baglanti[plan.switchId]);
  if (Number.isInteger(bag)) cikan.set(bag, 'diğer switch bağlantısı');
  return [...cikan.entries()].sort((a, b) => a[0] - b[0]);
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
        hata: `Bu switch'te cihaz tanımlı olmayan port: ${disarida.join(', ')}`,
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
      return 'Arama aralığının başlangıcı ve sonu birlikte girilmeli';
    }
    if (!ipv4Mi(bas) || !ipv4Mi(son)) {
      return 'Arama aralığı geçerli IPv4 adresleri olmalı';
    }
    const adet = ipSayi(son) - ipSayi(bas) + 1;
    if (adet <= 0) return 'Aralığın sonu başlangıcından küçük olamaz';
    if (adet > ARAMA_SINIRI) {
      return `Bu aralık ${adet} adres tarar; en fazla ${ARAMA_SINIRI} olabilir`;
    }
    return '';
  }
  const ag = String(agMetni || '').trim();
  const maske = String(maskeMetni || '').trim();
  if (!ag && !maske) return 'Arama ağı ve maskesi gerekli';
  if (!ipv4Mi(ag)) return 'Arama ağı geçerli bir IPv4 adresi olmalı';
  const onek = maskeOnek(maske);
  if (onek === null) return 'Maske 255.255.255.0 ya da 24 biçiminde olmalı';
  const adet = onek >= 31 ? 1 : (2 ** (32 - onek)) - 2;
  if (adet > ARAMA_SINIRI) {
    return `Bu maske ${adet} adres tarar; en fazla ${ARAMA_SINIRI} olabilir `
      + '— ya maskeyi daraltın ya da aşağıya adres aralığı yazın';
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
    return `Port ${p} koşuya giremez — ${korumali.get(p)}`;
  }
  return '';
}

// Bilgisayar / switch bağlantısı için girilen fiziksel portu denetler.
// Panel okunabildiyse portun gerçekten o switch'in yüzünde olması da şarttır.
function fizikselPortDenetle(metin, panel, etiket, zorunlu = false) {
  const ham = String(metin || '').trim();
  if (!ham) return zorunlu ? `${etiket} gerekli` : '';
  const no = Number(ham);
  if (!/^\d+$/.test(ham) || !Number.isSafeInteger(no) || no < 1) {
    return `${etiket} pozitif bir port numarası olmalı`;
  }
  if (panel && !(panel.portlar || []).some(p => p.no === no)) {
    return `${etiket}: bu switch'te ${no} numaralı port yok`;
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
  const pcPanel = panelIle.get(pcSwitchId(plan));
  const pcPortHatasi = fizikselPortDenetle(
    yerel.pcPort, pcPanel, 'Bilgisayar portu', true);
  const baglantiHatalari = new Map();
  for (const s of plan.switchler || []) {
    const h = fizikselPortDenetle(
      yerel.baglanti[s.id], panelIle.get(s.id), `${s.ad} bağlantı portu`);
    if (h) baglantiHatalari.set(s.id, h);
  }
  const portHatasi = ayrisma.hata || portDenetle(seciliMetin, izinli, plan);
  const ilkBaglantiHatasi = baglantiHatalari.values().next().value || '';
  const kapsamHatasi = !seciliPortSayisi
    ? 'Koşu için en az bir hedef port seçin'
    : !planaDahil ? 'Seçili portlarda hedef gruptan cihaz bulunmuyor' : '';
  // Koşu switch'e kullanıcı adı/parola ile bağlanır. Kimlik yoksa iş
  // kuyruğa girip ilk adımda düşüyordu; başlamadan söylemek daha doğru.
  const aktifPanel = panelIle.get(plan.switchId);
  const kimlikHatasi = aktifPanel && aktifPanel.kimlikVar === false
    ? `${aktifPanel.switchAd} için kullanıcı adı/parola girilmemiş`
    : '';
  // Her cihaz grubunun atama betiği ayrı; betiği olmayan grup seçiliyse
  // koşu başlatılmaz. Sunucu da aynı denetimi yapıyor, burada olması
  // kullanıcının düğmeye basmadan görmesi için.
  const grupHatasi = !(plan.gruplar || []).length
    ? 'En az bir cihaz grubu seçin'
    : (plan.kosucusuz || []).length
      ? `IP atama betiği henüz yok: ${plan.kosucusuz.join(', ')}`
      : '';
  const fabrika = yerel.fabrikaIp ?? plan.fabrikaIp ?? '';
  const fabrikaHatasi = ipv4Mi(fabrika)
    ? '' : 'Fabrika IP geçerli bir IPv4 adresi olmalı';
  const aramaHatasi = yerel.aramaAcik
    ? aramaDenetle(yerel.aramaAgi ?? plan.aramaAgi,
                   yerel.aramaMaskesi ?? plan.aramaMaskesi,
                   yerel.aramaBas, yerel.aramaSon)
    : '';
  const hataMetni = grupHatasi || fabrikaHatasi || aramaHatasi || pcPortHatasi
    || ilkBaglantiHatasi || portHatasi || kapsamHatasi || kimlikHatasi;
  return {
    grupHatasi,
    fabrika,
    fabrikaHatasi,
    aramaHatasi,
    kimlikHatasi,
    izinli,
    seciliMetin,
    seciliPortSayisi,
    planaDahil,
    planDisi,
    panelIle,
    pcPortHatasi,
    baglantiHatalari,
    portHatasi: portHatasi || (!seciliPortSayisi ? kapsamHatasi : ''),
    hata: hataMetni,
    hazir: !hataMetni,
  };
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
  } catch (e) {
    if (surum !== tazeleSurumu || setNo !== durum.setNo) return;
    yerel.hataMetni = e.message;
    ata({ ipDurum: null });
  }
}

export function ciz(kok) {
  const veri = durum.ipDurum;
  const parcalar = [];
  const hazirPlan = veri && veri.plan;
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
    metin: 'Koşuyu Başlat',
    disabled: !veri || !denetim.hazir,
    title: denetim && denetim.hata ? denetim.hata : 'IP atama koşusunu başlat',
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
    baslatDugmesi.title = d.hata || bekleyenMetin || 'IP atama koşusunu başlat';
    hazirlik.dataset.durum = hazir ? 'hazir' : d.hata ? 'hata' : 'beklemede';
    hazirlikYazisi.textContent = hazir
      ? 'Plan hazır' : d.hata ? 'Ayarları kontrol edin' : bekleyenMetin;
    ozetRozeti.className = hazir
      ? 'rozet ip-hazir-rozet'
      : d.hata ? 'rozet ip-hata-rozet' : 'rozet ip-bekliyor-rozet';
    ozetRozeti.textContent = hazir
      ? 'Hazır' : d.hata ? 'Kontrol gerekli' : 'Güncelleme bekliyor';
    kosuHataMetni.textContent = d.hata || '';
    kosuHataMetni.hidden = !d.hata;
  }

  parcalar.push(el('div', { sinif: 'sayfa-basi ip-sayfa-basi' }, [
    el('div', { sinif: 'ip-baslik' }, [
      el('span', { sinif: 'ust-etiket', metin: 'Ağ yapılandırması' }),
      el('h2', { metin: 'Otomatik IP Atama' }),
      el('p', {
        sinif: 'ip-aciklama',
        metin: 'Hedef cihazları ve korunacak bağlantıları belirleyin; '
          + 'atama planını çalıştırmadan önce tek ekranda doğrulayın.',
      }),
      hazirPlan ? el('div', { sinif: 'ip-hizli-ozet' }, [
        el('span', {}, [
          el('b', { metin: String((hazirPlan.gruplar || []).length) }),
          ' grup',
        ]),
        el('span', {}, [
          el('b', { metin: String(hazirPlan.hedefSayi) }),
          ' hedef cihaz',
        ]),
        el('span', {}, [
          el('b', { metin: String((hazirPlan.switchler || []).length) }),
          ' switch',
        ]),
        el('span', {}, [
          el('b', { metin: deger(hazirPlan.switch) }),
          ' etkin',
        ]),
      ]) : null,
    ]),
    el('div', { sinif: 'ip-ust-eylem' }, [
      hazirlik,
      baslatDugmesi,
    ]),
  ]));

  const hedefSerit = serit.ciz('ip', (g) => grupSec(g.ad),
    { coklu: true, secili: seciliGruplar() });
  hedefSerit.classList.add('ip-serit');
  parcalar.push(hedefSerit);

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
        || (!ayrisma.portlar.length ? 'Koşu için en az bir hedef port seçin' : '');
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

  function enYuksekPort(panel) {
    const numaralar = (panel && panel.portlar || []).map(p => p.no);
    return numaralar.length ? Math.max(...numaralar) : null;
  }

  function alanUyarisiGoster(giris, uyari, h) {
    giris.setAttribute('aria-invalid', String(!!h));
    uyari.textContent = h;
    uyari.hidden = !h;
  }

  const pcPortUyari = el('p', {
    id: 'ip-pc-port-hata', sinif: 'ip-alan-hata', role: 'alert',
    metin: denetim.pcPortHatasi, hidden: !denetim.pcPortHatasi,
  });
  const pcPanel = denetim.panelIle.get(pcSwitchId(plan));
  const pcPortGiris = el('input', {
    id: 'ip-pc-port', type: 'number', min: '1', step: '1',
    max: enYuksekPort(pcPanel), required: true,
    sinif: 'alan ip-kisa-alan', value: yerel.pcPort,
    inputmode: 'numeric', placeholder: '24',
    'aria-invalid': String(!!denetim.pcPortHatasi),
    'aria-describedby': 'ip-pc-port-hata',
    oninput: (e) => {
      yerel.pcPort = e.target.value.trim();
      const yeniDenetim = kosuDenetle(veri);
      alanUyarisiGoster(e.target, pcPortUyari, yeniDenetim.pcPortHatasi);
      eylemDurumuGoster(
        yeniDenetim, yeniDenetim.hata ? '' : 'Değişikliği uygulayın');
    },
    onchange: () => {
      ata({ ipDurum: { ...veri } });  // panelde turuncu port taşınır
    },
  });

  const baglantiSatirlari = (plan.switchler || []).flatMap((s, i) => {
    const id = `ip-baglanti-port-${i}`;
    const uyariId = `${id}-hata`;
    const ilkHata = denetim.baglantiHatalari.get(s.id) || '';
    const uyari = el('p', {
      id: uyariId, sinif: 'ip-alan-hata', role: 'alert',
      metin: ilkHata, hidden: !ilkHata,
    });
    const panel = denetim.panelIle.get(s.id);
    const giris = el('input', {
      id, type: 'number', min: '1', step: '1', max: enYuksekPort(panel),
      sinif: 'alan ip-kisa-alan', value: yerel.baglanti[s.id] || '',
      // Alan dar; "örn. 25" kırpılıp "örn. 2" görünüyor ve 2. portu
      // öneriyormuş gibi okunuyordu.
      inputmode: 'numeric', placeholder: '25',
      'aria-invalid': String(!!ilkHata), 'aria-describedby': uyariId,
      oninput: (e) => {
        const v = e.target.value.trim();
        if (v) yerel.baglanti[s.id] = v;
        else delete yerel.baglanti[s.id];
        const yeniDenetim = kosuDenetle(veri);
        alanUyarisiGoster(
          e.target, uyari, yeniDenetim.baglantiHatalari.get(s.id) || '');
        eylemDurumuGoster(
          yeniDenetim, yeniDenetim.hata ? '' : 'Değişikliği uygulayın');
      },
      onchange: () => { ata({ ipDurum: { ...veri } }); },
    });
    return [
      el('label', { sinif: 'ayar-satir', for: id }, [
        el('span', { sinif: 'etiket', metin: `${s.ad} · bağlantı portu` }),
        giris,
      ]),
      uyari,
    ];
  });

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

  const ayarKart = el('section', { sinif: 'kart kose ip-ayar-kart' }, [
    el('div', { sinif: 'ip-kart-basi' }, [
      el('span', { sinif: 'ip-adim-no', metin: '01' }),
      el('div', {}, [
        el('h3', { metin: 'Koşu Ayarları' }),
        el('p', {
          metin: 'Atamanın kapsamını ve kesilmemesi gereken bağlantıları tanımlayın.',
        }),
      ]),
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
        el('p', {
          metin: 'Koşu portları sırayla açar; o an ayağa kalkan cihazı '
            + 'aşağıdaki adreslerde arar ve DeviceMap\'teki IP\'yi yazar.',
        }),
      ]),
      el('label', { sinif: 'ayar-satir', for: 'ip-fabrika' }, [
        el('span', { sinif: 'etiket', metin: 'Fabrika (varsayılan) IP' }),
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

    // ── kurulumun fiziksel gerçeği ──
    // İki switch birbirine bir portla bağlı, bilgisayar da birinin bir
    // portunda. Koşu PoE'yi sırayla kapatıp açtığı için bu portlara
    // dokunursa kendi yolunu keser; ikisi de burada bildirilir.
    el('fieldset', { sinif: 'ayar-bolum' }, [
      el('legend', { sinif: 'gizli-metin', metin: 'Korunan bağlantılar' }),
      el('div', { sinif: 'ip-alt-baslik' }, [
        el('span', { sinif: 'ust-etiket', metin: 'Korunan bağlantılar' }),
        el('p', {
          metin: 'Bilgisayar ve switch bağlantı portları koşu dışında tutulur.',
        }),
      ]),
      el('label', { sinif: 'ayar-satir' }, [
        el('span', { sinif: 'etiket', metin: 'Bilgisayarın switch\'i' }),
        el('select', {
          sinif: 'alan',
          onchange: (e) => {
            yerel.pcSwitchId = e.target.value;
            ata({ ipDurum: { ...veri } });
          },
        }, (plan.switchler || []).map(s => el('option', {
          value: s.id, metin: s.ad,
          selected: s.id === pcSwitchId(plan) ? '' : null,
        }))),
      ]),
      el('label', { sinif: 'ayar-satir', for: 'ip-pc-port' }, [
        el('span', { sinif: 'etiket', metin: 'Bilgisayarın portu' }),
        pcPortGiris,
      ]),
      pcPortUyari,
      ...baglantiSatirlari,
    ]),

    // ── özet: hangi switch'te ne yapılacak ──
    el('div', { sinif: 'ayar-ozet' }, [
      el('div', { sinif: 'ip-ozet-basi' }, [
        el('span', { sinif: 'ust-etiket', metin: 'Koşu özeti' }),
        ozetRozeti,
      ]),
      kosuHataMetni,
      el('div', { sinif: 'satir' }, [
        el('span', { metin: 'Koşu' }),
        el('b', { metin: `${deger(plan.switch)} · ${plan.hedefSayi} cihaz` }),
      ]),
      // Gruplar sırayla, her biri kendi betiğiyle yürüyecek; hangi
      // gruplarla çalışılacağı özetin ilk satırlarında dursun.
      el('div', { sinif: 'satir' }, [
        el('span', { metin: 'Gruplar' }),
        el('b', {
          sinif: (plan.kosucusuz || []).length ? 'soluk' : '',
          metin: (plan.gruplar || []).join(', ') || YOK,
        }),
      ]),
      ...(plan.kosucusuz || []).map(ad => el('div', { sinif: 'satir' }, [
        el('span', { metin: `${ad} betiği` }),
        el('b', { sinif: 'soluk', metin: 'henüz yazılmadı' }),
      ])),
      // Bütün cihazlar aynı fabrika adresiyle geldiği için koşu her port
      // değişiminde ARP kaydını tazelemek zorunda; yetki yoksa cihazlar
      // eski MAC'e yazılıp "bulunamadı" oluyor. Koşuyu engellemez —
      // sistem yetkisi bizim kararımız değil — ama sebebi baştan söyler.
      // Test aracı: koşuyu baştan denemek için cihazları fabrika
      // adresinde toplar. Koşu düğmesinin yanında değil, özetin altında —
      // yanlışlıkla basılacak bir yerde durmamalı.
      el('div', { sinif: 'ip-test-alani' }, [
        el('span', { sinif: 'ust-etiket', metin: 'Test' }),
        el('button', {
          type: 'button', sinif: 'btn btn-kucuk btn-tehlike',
          metin: 'Fabrika adresine döndür',
          title: `Seçili cihazlara "IP'ni ${denetim.fabrika} yap" isteği `
            + 'gönderir; koşuyu baştan denemek için',
          onclick: fabrikayaDondur,
        }),
      ]),
      plan.arpTemizlik === false ? el('div', { sinif: 'satir korunan' }, [
        el('span', { metin: 'ARP önbelleği' }),
        el('b', {
          sinif: 'soluk',
          title: 'Cihazlar aynı fabrika IP\'sinde geldiği için önbellekteki '
            + 'eski MAC koşuyu yanıltır',
          metin: 'temizlenemiyor · sudo -v',
        }),
      ]) : null,
      el('div', { sinif: 'satir' }, [
        el('span', { metin: 'Switch IP' }),
        el('b', { metin: deger(plan.switchIp) }),
      ]),
      ...(plan.switchler || []).map(s => el('div', { sinif: 'satir' }, [
        el('span', { metin: s.ad }),
        el('b', {
          sinif: s.id === plan.switchId ? 'vurgu' : 'soluk',
          metin: s.id === plan.switchId
            ? plan.portMetni
            : (s.grupCihaz ? `${s.grupCihaz} cihaz · seçilmedi` : 'bu grupta cihaz yok'),
        }),
      ])),
      ...korumaliPortlar(plan).map(([no, sebep]) => el('div', {
        sinif: 'satir korunan',
      }, [
        el('span', { metin: `Korunan p${no}` }),
        el('b', { sinif: 'soluk', metin: sebep }),
      ])),
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
      if (canli.acik) yenilemeTuru();     // sürdürülünce hemen bir okuma
    },
    metin: canli.acik ? 'Yenileme açık' : 'Duraklatıldı',
  });

  const panelAlani = el('section', { sinif: 'ip-panel-alani' }, [
    el('div', { sinif: 'ip-bolum-basi' }, [
      el('div', { sinif: 'ip-bolum-baslik' }, [
        el('span', { sinif: 'ip-adim-no', metin: '02' }),
        el('div', {}, [
          el('h3', { metin: 'Switch Ön Panelleri' }),
          el('p', {
            metin: 'Hedef portları seçin; switch değiştirmek için panelindeki '
              + 'tanımlı bir porta tıklayın.',
          }),
        ]),
      ]),
      el('div', { sinif: 'ip-bolum-eylem' }, [
        yenilemeDugmesi,
        el('span', {
          sinif: 'ip-bolum-sayac', metin: `${paneller.length} panel`,
        }),
      ]),
    ]),
    panelYigin,
    paneller.length ? lejant() : null,
  ]);
  panelleriCiz(veri);
  yenilemeyiKur();

  parcalar.push(el('div', { sinif: 'ip-izgara' }, [ayarKart, panelAlani]));

  // ── altta plan tablosu ──
  parcalar.push(el('section', { sinif: 'ip-plan-bolum' }, [
    el('div', { sinif: 'ip-bolum-basi' }, [
      el('div', { sinif: 'ip-bolum-baslik' }, [
        el('span', { sinif: 'ip-adim-no', metin: '03' }),
        el('div', {}, [
          el('h3', { metin: 'Atama Planı' }),
          el('p', {
            metin: 'Cihazların mevcut ve yeni IP adreslerini çalıştırmadan önce kontrol edin.',
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
          ['Port', 'Hedef Cihaz', 'Grup', 'Fabrika IP', 'Atanacak IP', 'Durum']
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
    ? `Port ${p.no} · ${koruma || 'bilgisayar bu portta'} · koşuya girmez`
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
  // Bilgisayarın portu yalnız bağlı olduğu switch'te işaretlenir; bağlantı
  // portu ise her switch'in kendi tarafında durur.
  const koruma = new Map();
  const bag = Number(yerel.baglanti[panel.switchId]);
  if (Number.isInteger(bag)) koruma.set(bag, 'diğer switch bağlantısı');
  const pc = Number(yerel.pcPort);
  const ctx = {
    hedef,
    aktif,
    koruma,
    switchId: panel.switchId,
    switchAd: panel.switchAd,
    pcPort: (pcSwitchId(plan) === panel.switchId && Number.isInteger(pc))
      ? pc : null,
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
          metin: panel.kaynak === 'switch' ? 'Canlı veri' : 'DeviceMap',
          title: panel.kaynak === 'switch'
            ? 'Port durumları switch\'ten okundu'
            : 'Port durumu okunamadı; yerleşim DeviceMap\'ten çizildi',
        }),
        // Kimlik yoksa koşu başlayamaz; girecek yer de burası olmalı.
        panel.kimlikVar === false ? el('button', {
          type: 'button', sinif: 'btn btn-kucuk ip-kimlik-btn',
          metin: 'Kimlik gir',
          title: `${panel.switchAd} kullanıcı adı/parolasını gir`,
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
          metin: 'Kullanıcı adı/parola girilmemiş — koşu başlayamaz.',
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
    hata('Seçili portlarda hedef gruptan cihaz yok');
    return;
  }
  diyalog.ac({
    baslik: 'Fabrika adresine döndür',
    icerik: el('div', {}, [
      el('p', { sinif: 'aciklama' }, [
        `${hedefler.length} cihaza "IP'ni ${denetim.fabrika} yap" isteği `
        + 'gönderilecek. Cihazlar reset atıp aynı adreste toplanacak; '
        + 'bundan sonra birbirleriyle çakışırlar.',
      ]),
      el('p', {
        sinif: 'bilgi', stil: 'margin-top:10px',
        metin: 'Bu bir test aracıdır: IP atama koşusunu baştan denemek '
          + 'için başlangıç durumunu kurar. PoE portlarına dokunmaz.',
      }),
      // Fabrika adresi tren setine göre çözülmüyor (hep 10.1.1.12).
      // Bilgisayar başka bir ağdaysa cihazlar bu yazımdan sonra
      // görünmez olur ve koşu onları bulamaz — geri almanın yolu da
      // cihaza ulaşmaktan geçtiği için önce söylenmeli.
      el('p', {
        sinif: 'uyari', stil: 'margin-top:10px',
        metin: `Cihazlar ${denetim.fabrika} ağına gider. Bilgisayarınız o `
          + 'ağa erişemiyorsa cihazlar bu işlemden sonra görünmez olur; '
          + 'setin kendi ağında kalsınlar istiyorsanız yukarıdaki '
          + '"Fabrika (varsayılan) IP" alanını değiştirin.',
      }),
    ]),
    eylemler: [
      el('button', {
        type: 'button', sinif: 'btn', metin: 'Vazgeç',
        onclick: () => diyalog.kapat(),
      }),
      el('button', {
        type: 'button', sinif: 'btn btn-tehlike', metin: 'Gönder',
        onclick: async () => {
          diyalog.kapat();
          try {
            const y = await api.ipFabrika({
              set: durum.setNo,
              switch: plan.switchId,
              gruplar: plan.gruplar || [],
              portlar: yerel.portMetni ?? plan.portMetni,
              fabrikaIp: denetim.fabrika,
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
      pcSwitch: pcSwitchId(plan),
      pcPort: yerel.pcPort,
      baglanti: yerel.baglanti,
    });
    ata({ kuyrukAcik: true, acikIs: y.id });
    if (y.yeni === false) bildir('Bu switch için zaten bir koşu var');
    else basari('Koşu kuyruğa alındı');
  } catch (e) {
    hata(e.message);
  }
}

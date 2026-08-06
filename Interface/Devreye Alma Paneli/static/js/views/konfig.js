// Konfigürasyon ekranı: cihazdaki değer ↔ hedef değer.
//
// Yalnız anons cihazları (Announcement ailesi) konfigüre edilir; şerit
// zaten yalnız o grupları listeler, cihazın okuma yöntemi de "http"dir.
//
// Alanlar cihaz tipine göre gelir: Handset'in mod alanları Amplifier'da
// yok, UIC'in gerilim eşikleri yalnız UIC'te var. Liste sunucudan alınır,
// bu dosya kendi alan tablosunu tutmaz (bkz. core/konfig.py ROTA).
//
// Hedef değer iki düzeyde girilir:
//   · Gruba  — aynı ayar bütün gruba gidecekse bir kez yazılır
//   · Cihaza — o cihazda farklı olacaksa; grubunkini ezer
//
// "Cihazdaki değer" sütunu okunmadıysa boş (—) kalır. Hedefler bellekte
// tutulur; hiçbir dosyaya yazılmaz. SIP parolası bu ekranda girilebilir
// ama GÖSTERİLMEZ: sunucu değerini hiç geri vermez, satırda yalnız
// uyuşup uyuşmadığı ve kaynağı görünür.

import { el, doldur } from '../core/dom.js';
import { api } from '../core/api.js';
import { durum, ata } from '../core/durum.js';
import * as serit from '../parts/serit.js';
import { hata, basari, bildir } from '../parts/bildirim.js';
import { deger } from '../core/bicim.js';

const KOLON = 'minmax(150px,1.05fr) minmax(120px,.95fr) minmax(150px,1fr) '
  + '86px 104px';

const SONUC_ETIKET = {
  uyuyor: ['Uyuşuyor', 'yesil'],
  farkli: ['Farklı', 'turuncu'],
  okunamadi: ['Okunamadı', 'kirmizi'],
  hedef_yok: ['Hedef yok', 'soluk'],
};

const KAYNAK_ETIKET = {
  cihaz: ['Cihaza özel', 'accent'],
  grup: ['Gruptan', 'orta'],
  proje: ['DeviceMap', 'soluk'],
};

// Bölüm başlıkları — sunucudaki `bolum` değerlerinin görünen adı.
const BOLUM_ETIKET = {
  SIP: 'SIP',
  Ses: 'Ses ve Gain',
  Mod: 'Çalışma Modları',
  Eşik: 'Gerilim Eşikleri',
  Yönlendirme: 'Çağrı Yönlendirme',
  Bilgi: 'Cihaz Bilgisi',
};

const yerel = { cihazId: null, hataMetni: '', kimlikGerek: false, nesil: 0 };

function grupAdi() {
  const g = serit.gecerliGrup('cfg');
  return g ? g.ad : '';
}

function hedefCihazlar() {
  const g = serit.gecerliGrup('cfg');
  return g ? serit.eslesen(g) : [];
}

// İki aşamalı yükleme. Alan listesi, hedefler ve DeviceMap değerleri
// cihaza gitmeyen uçtan gelir ve HEMEN çizilir; cihazdaki değerler arkadan
// yetişir. Tek istek beklendiğinde grup değiştirmek saniyelerce eski
// grubun alanlarını gösteriyordu (cihaz okuması yavaş, kapalıysa zaman
// aşımı kadar).
//
// `nesil`: kullanıcı beklerken başka bir gruba geçebilir. Geciken yanıtın
// yeni seçimin üstüne yazmaması için her tazelemeye sıra numarası verilir.
export async function tazele(hizli = true) {
  const liste = hedefCihazlar();
  if (!liste.length) { ata({ cfgDurum: null }); return; }
  if (!liste.some(c => c.id === yerel.cihazId)) yerel.cihazId = liste[0].id;
  const nesil = (yerel.nesil = (yerel.nesil || 0) + 1);
  const gecerli = () => nesil === yerel.nesil;
  const id = yerel.cihazId;
  const grup = grupAdi();

  if (hizli) {
    try {
      const on = await api.konfigAlanlar(durum.setNo, id, grup);
      if (!gecerli()) return;
      yerel.hataMetni = '';
      yerel.kimlikGerek = false;
      ata({ cfgDurum: on });
    } catch { /* hızlı uç başarısızsa asıl okuma zaten hata gösterir */ }
  }

  try {
    const y = await api.konfig(durum.setNo, id, grup);
    if (!gecerli()) return;
    yerel.hataMetni = y.hata || '';
    yerel.kimlikGerek = !!y.kimlik;
    ata({ cfgDurum: y });
  } catch (e) {
    if (!gecerli()) return;
    yerel.hataMetni = e.message;
    ata({ cfgDurum: { cihazId: id, satirlar: [] } });
  }
}

export function ciz(kok) {
  const liste = hedefCihazlar();
  const veri = durum.cfgDurum;
  const parcalar = [];

  parcalar.push(el('div', { sinif: 'sayfa-basi' }, [
    el('div', {}, [
      el('h2', { metin: 'Konfigürasyon' }),
      el('div', {
        sinif: 'sayfa-alt',
        metin: `Anons cihazları · ${liste.length} cihaz`
          + (grupAdi() ? ` · ${grupAdi()}` : ''),
      }),
    ]),
    el('div', { sinif: 'eylemler' }, [
      el('button', {
        type: 'button', sinif: 'btn', metin: 'Cihazdan Çek',
        disabled: !liste.length, onclick: tazele,
      }),
      el('button', {
        type: 'button', sinif: 'btn btn-birincil', metin: 'Gruba Uygula',
        disabled: !liste.length, onclick: uygula,
      }),
    ]),
  ]));

  parcalar.push(serit.ciz('cfg', () => { yerel.cihazId = null; tazele(); }));

  if (!liste.length) {
    parcalar.push(el('p', {
      sinif: 'bilgi', stil: 'margin-top:16px',
      metin: 'Bu grupta konfigüre edilebilir cihaz yok.',
    }));
    doldur(kok, parcalar);
    return;
  }

  const satirlar = (veri && veri.satirlar) || [];
  const grupHedef = (veri && veri.grupHedef) || {};
  const grupGizli = (veri && veri.grupGizli) || [];
  // DeviceMap'te tanımlı, gruptaki bütün cihazlarda aynı olan değerler:
  // kutulara hazır yazılır ki kullanıcı hiçbir şeye dokunmadan "Gruba
  // Uygula" dediğinde ne yazılacağı görünür olsun.
  const projeHedef = (veri && veri.projeHedef) || {};
  const projeFarkli = (veri && veri.projeFarkli) || [];
  // Alan listesi cihazdan bağımsız gelir: cihaza erişilemezken de gruba
  // yazılacak değerler girilebilmeli.
  const alanlar = (veri && veri.alanlar) || [];

  parcalar.push(el('div', { sinif: 'cfg-izgara' }, [
    grupKarti(alanlar, satirlar, {
      grupHedef, grupGizli, projeHedef, projeFarkli,
      varsayilan: (veri && veri.varsayilan) || {},
    }),
    el('div', { sinif: 'cfg-cihaz-alani' }, [
      el('div', {
        sinif: 'cfg-cihaz-basi',
      }, [
        el('label', { sinif: 'etiket', for: 'cfg-cihaz', metin: 'Cihaz' }),
        el('select', {
          id: 'cfg-cihaz', sinif: 'alan', stil: 'width:auto;min-width:230px',
          onchange: (e) => { yerel.cihazId = e.target.value; tazele(); },
        }, liste.map(c => el('option', {
          value: c.id, selected: c.id === yerel.cihazId ? true : null,
          metin: `${c.ad} · ${c.ip}`,
        }))),
      ]),
      yerel.hataMetni ? el('p', {
        sinif: yerel.kimlikGerek ? 'bilgi' : 'uyari',
        metin: yerel.hataMetni
          + (yerel.kimlikGerek
            ? ' — kilit menüsünden kullanıcı adı/parola girin.' : ''),
      }) : null,
      el('div', { sinif: 'tablo-sar' }, [
        el('div', { sinif: 'tablo', stil: '--tablo-min:660px' }, [
          el('div', { sinif: 'tablo-basi', stil: `--tablo-kolon:${KOLON}` },
            ['Alan', 'Cihazdaki değer', 'Bu cihaza özel', 'Kaynak', 'Sonuç']
              .map(b => el('span', { metin: b }))),
          ...(satirlar.length ? satirlar.map(satirCiz)
            : [el('div', {
                sinif: 'tablo-bos',
                // Okuma sürerken "okunamadı" yazmak yanlış: cihaz henüz
                // denenmedi bile.
                metin: (veri && veri.okunuyor) && !yerel.hataMetni
                  ? 'Cihaz okunuyor…'
                  : 'Cihazdan değer okunamadı — "Cihazdan Çek" ile deneyin',
              })]),
        ]),
      ]),
    ]),
  ]));

  doldur(kok, parcalar);
}

// Alanın türüne uygun giriş öğesi. Tür bilgisi cihazın kendi arayüzünden
// geliyor (açılır liste / 0–100 kaydırıcı / gerilim); serbest metin yerine
// aynı sınırların panelde de durması, cihazın reddedeceği bir değerin
// kuyruğa girmesini engelliyor.
function girdi(f, mevcutDeger, onDegis, ek = {}) {
  if (f.tur === 'secim') {
    return el('select', {
      sinif: `alan ${ek.sinif || ''}`, stil: ek.stil || null,
      'aria-label': `${f.etiket} · ${ek.aria || ''}`,
      title: ek.baslik || f.ipucu || null,
      onchange: (e) => onDegis(e.target.value),
    }, [
      el('option', { value: '', metin: ek.bosEtiket || '—' }),
      ...(f.secenekler || []).map(s => el('option', {
        value: s.deger, metin: s.etiket,
        selected: String(mevcutDeger) === String(s.deger) ? true : null,
      })),
    ]);
  }
  const sayisal = f.tur === 'tamsayi' || f.tur === 'ondalik';
  return el('input', {
    type: f.gizli ? 'password' : (sayisal ? 'number' : 'text'),
    sinif: `alan ${ek.sinif || ''}`, stil: ek.stil || null,
    value: mevcutDeger || '',
    min: sayisal && f.enAz !== null ? f.enAz : null,
    max: sayisal && f.enCok !== null ? f.enCok : null,
    step: sayisal ? (f.adim || 1) : null,
    placeholder: ek.yerTutucu || '—',
    autocomplete: f.gizli ? 'new-password' : 'off', spellcheck: 'false',
    'aria-label': `${f.etiket} · ${ek.aria || ''}`,
    title: ek.baslik || f.ipucu || null,
    onchange: (e) => onDegis(e.target.value),
  });
}

// Gruba bir kez girilen değerler: buradaki her alan, gruptaki bütün
// cihazlara yazılır (cihaza özel değer girilmediyse).
//
// Kutular DeviceMap'teki değerle hazır gelir; kullanıcı dokunmazsa cihaza
// yazılan da o değerdir. Dahili numara gibi cihaza göre DEĞİŞEN alanlarda
// kutu boş kalır (projeFarkli): tek bir numara gösterip kullanıcının bir
// harf değiştirmesi, bütün gruba aynı numarayı yazdırırdı.
function grupKarti(alanlar, satirlar, kaynaklar) {
  const { grupHedef, grupGizli, projeHedef, projeFarkli, varsayilan } = kaynaklar;
  const satirIle = new Map(satirlar.map(s => [s.alan, s]));
  const yazilabilir = alanlar.filter(f => f.duzenlenebilir)
    // Satır verisi (kaynak/hedef) alan tanımının üstüne değil altına
    // gelir: ortak anahtarlarda (etiket, tür) tanım geçerli olmalı.
    .map(f => ({ ...(satirIle.get(f.alan) || {}), ...f }));

  // Bölümler cihaz sayfasındaki panellere karşılık geliyor; 20'yi aşan
  // alan listesi (UIC) başlıksız tek yığın olarak okunmuyor.
  const bolumler = [];
  for (const f of yazilabilir) {
    const son = bolumler[bolumler.length - 1];
    if (son && son.ad === (f.bolum || '')) son.alanlar.push(f);
    else bolumler.push({ ad: f.bolum || '', alanlar: [f] });
  }

  return el('section', { sinif: 'kart kose cfg-grup-kart' }, [
    el('h3', { metin: 'Gruba Yazılacak Değerler' }),
    el('p', {
      sinif: 'cfg-aciklama',
      metin: 'Kutularda DeviceMap\'te tanımlı değerler hazır duruyor; '
        + 'dokunulmazsa cihazlara yazılan bunlar olur. Değiştirilen değer '
        + `${grupAdi() || 'gruptaki'} cihazlarının hepsine yazılır — bir `
        + 'cihazda farklı olması gerekiyorsa sağdaki tablodan o cihaza özel '
        + 'değer girin.',
    }),
    ...(bolumler.length
      ? bolumler.flatMap(b => [
        b.ad ? el('h4', {
          sinif: 'cfg-bolum', metin: BOLUM_ETIKET[b.ad] || b.ad,
        }) : null,
        ...b.alanlar.map(f => {
          const girilen = f.gizli ? '' : (grupHedef[f.alan] || '');
          const devralinan = !girilen && !f.gizli
            && !projeFarkli.includes(f.alan) ? (projeHedef[f.alan] || '') : '';
          return el('label', { sinif: 'ayar-satir' }, [
            el('span', { sinif: 'etiket', metin: f.etiket }),
            girdi(f, girilen || devralinan,
              (v) => hedefYaz(f.alan, v, 'grup'), {
                sinif: `cfg-alan${devralinan ? ' cfg-devralinan' : ''}`,
                aria: 'gruba yazılacak değer',
                yerTutucu: grupYerTutucu(f, grupGizli, projeFarkli),
                bosEtiket: devralinan ? '— DeviceMap —' : '— değiştirme —',
                baslik: devralinan
                  ? 'DeviceMap\'ten geldi — dokunulmazsa bu değer yazılır'
                  : (f.uyari || f.ipucu || ''),
              }),
          ]);
        }),
      ])
      : [el('p', {
          sinif: 'mono soluk', stil: 'font-size:10.5px',
          metin: 'Bu cihaz tipinde yazılabilir alan yok.',
        })]),
    varsayilanAyagi(varsayilan),
  ]);
}

// Girilen değerler dosyaya yazılır ve uygulama açılışında geri yüklenir.
// Kullanıcı bunu bilmezse "acaba kalıcı mı" diye her açılışta baştan
// giriyor. Parola dosyaya HİÇ yazılmaz, bu da burada söylenir.
function varsayilanAyagi(v) {
  const sayi = (v.grupDegeri || 0) + (v.cihazDegeri || 0);
  return el('div', { sinif: 'cfg-varsayilan' }, [
    el('p', {
      sinif: 'cfg-aciklama', stil: 'margin-top:0',
      metin: sayi
        ? `${sayi} değer kaydedildi — uygulama açılışında buradan yüklenir. `
          + 'SIP parolası kaydedilmez.'
        : 'Girilen değerler kaydedilir ve uygulama açılışında geri yüklenir. '
          + 'SIP parolası kaydedilmez.',
      title: v.dosya || '',
    }),
    sayi ? el('button', {
      type: 'button', sinif: 'btn btn-kucuk',
      metin: 'Kayıtlı Değerleri Sıfırla', onclick: sifirla,
    }) : null,
  ]);
}

async function sifirla() {
  try {
    const y = await api.konfigSifirla(durum.setNo, yerel.cihazId, grupAdi());
    ata({ cfgDurum: y });
    basari('Kayıtlı değerler silindi — DeviceMap değerlerine dönüldü');
  } catch (e) { hata(e.message); }
}

// Gizli alanın değeri hiç gelmediği için yer tutucu ne durumda olduğunu
// söylemek zorunda: girildi mi, DeviceMap'ten mi gelecek.
function grupYerTutucu(f, grupGizli, projeFarkli) {
  if (f.gizli) {
    if (grupGizli.includes(f.alan)) return 'gruba girildi (gizli)';
    return f.kaynak === 'proje' ? 'DeviceMap' : 'girilmedi';
  }
  // Cihaza göre değişen alanda kutu bilerek boş: her cihaz kendi
  // DeviceMap değerini alır.
  if (projeFarkli.includes(f.alan)) return 'cihaza göre (DeviceMap)';
  return '—';
}

async function hedefYaz(alan, value, kapsam) {
  try {
    const y = await api.konfigHedef(
      durum.setNo, yerel.cihazId, alan, value, grupAdi(), kapsam);
    ata({ cfgDurum: y });
  } catch (err) { hata(err.message); }
}

function satirCiz(f) {
  const [etiket, renk] = SONUC_ETIKET[f.sonuc] || ['—', 'soluk'];
  const [kaynakAd, kaynakRenk] = KAYNAK_ETIKET[f.kaynak] || ['—', 'soluk'];
  // Gizli alanın cihazdaki değeri gelmez; yalnız "var" bilgisi gelir.
  const mevcutMetin = f.gizli ? (f.mevcutVar ? '•••' : '—') : deger(f.mevcut);
  return el('div', { sinif: 'tablo-satir', stil: `--tablo-kolon:${KOLON}` }, [
    el('span', { sinif: 'mono', stil: 'font-size:12px', metin: f.etiket }),
    el('span', {
      sinif: 'mono orta kirp', stil: 'font-size:12px', metin: mevcutMetin,
    }),
    f.duzenlenebilir
      // Kutu, cihaza yazılacak DEĞERLE dolu gelir: cihaza özel bir değer
      // girilmemişse gruptan ya da DeviceMap'ten gelen hedef görünür ve
      // devralındığı soluk renkten anlaşılır. Kutuyu boşaltmak cihaza özel
      // değeri kaldırır, hedef yine devralınana döner.
      ? girdi(f, f.gizli ? '' : (f.ozel || f.hedef || ''),
        (v) => hedefYaz(f.alan, v, 'cihaz'), {
          stil: 'padding:5px 8px;font-size:12px',
          sinif: !f.ozel && f.hedef ? 'cfg-devralinan' : '',
          aria: 'bu cihaza özel değer',
          yerTutucu: f.gizli
            ? (f.ozelVar ? 'girildi (gizli)' : (f.hedefVar ? 'gizli' : '—'))
            : '—',
          baslik: f.uyari || (!f.ozel && f.hedef
            ? `${KAYNAK_ETIKET[f.kaynak] ? KAYNAK_ETIKET[f.kaynak][0] : ''}`
              + ' değeri — dokunulmazsa bu yazılır'
            : f.ipucu || ''),
          // Boş seçenek "bu cihaza özel değer yok" demek; hedefin nereye
          // döneceği etiketten anlaşılsın.
          bosEtiket: f.kaynak === 'proje' ? '— DeviceMap —'
            : (f.kaynak === 'grup' ? '— gruptan —' : '— boş —'),
        })
      : el('span', { sinif: 'mono soluk', stil: 'font-size:12px', metin: '—' }),
    // DeviceMap'teki değer geçersizse hedef sayılmadı; sebebi burada
    // görünür, yoksa alan sessizce boş kalmış gibi durur.
    el('span', {
      sinif: 'mono',
      stil: 'font-size:10.5px;color:var(--'
        + (f.uyari ? 'kirmizi' : kaynakRenk) + ')',
      title: f.uyari || null,
      metin: f.uyari ? 'DeviceMap ✕' : (f.duzenlenebilir ? kaynakAd : '—'),
    }),
    el('span', {
      stil: 'font-family:var(--f-baslik);font-weight:600;font-size:12.5px;'
        + `letter-spacing:.08em;text-transform:uppercase;color:var(--${renk})`,
      metin: etiket,
    }),
  ]);
}

async function uygula() {
  const g = serit.gecerliGrup('cfg');
  if (!g) return;
  try {
    const y = await api.konfigUygula(durum.setNo, g.ad, null);
    ata({ kuyrukAcik: true, acikIs: y.id });
    if (y.yeni === false) bildir('Konfigürasyon işi zaten kuyrukta');
    else basari('Konfigürasyon kuyruğa alındı');
  } catch (e) { hata(e.message); }
}

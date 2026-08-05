// İşlem kuyruğu paneli.
//
// İş satırlarında yalnızca sunucunun ürettiği güvenli metin gösterilir:
// parola, başlık ya da ham yığın izi buraya hiç gelmez.

import { el, doldur, ikon, $ } from '../core/dom.js';
import { api } from '../core/api.js';
import { durum, ata } from '../core/durum.js';
import { IS_DURUM_ETIKET, SATIR_DURUM_ETIKET, SATIR_RENK, saat } from '../core/bicim.js';
import { hata } from './bildirim.js';

const IS_RENK = {
  bekliyor: 'gri', calisiyor: 'mavi', tamam: 'yesil',
  iptal: 'turuncu', hata: 'kirmizi',
};

// Liste yalnız gerçekten değiştiğinde yeniden kurulur. Cihaz okuması her
// birkaç saniyede durumu tazeliyor; kuyruk o turlarda değişmemiş olsa da
// baştan çiziliyordu ve açık bir işin onlarca satırı her seferinde
// yeniden yaratılıyordu.
let sonImza = null;

export function ciz() {
  const liste = $('#kuyruk-liste');
  if (!liste) return;
  const isler = durum.isler || [];

  const calisan = isler.filter(j => j.durum === 'bekliyor' || j.durum === 'calisiyor');
  const sayac = $('#kuyruk-sayac');
  if (sayac) {
    sayac.textContent = String(calisan.length);
    sayac.hidden = calisan.length === 0;
  }
  const btn = $('#kuyruk-btn');
  if (btn) btn.setAttribute('aria-expanded', String(!!durum.kuyrukAcik));
  $('#kuyruk-panel').hidden = !durum.kuyrukAcik;

  // Panel kapalıyken liste hiç kurulmaz; açılınca kurulur.
  if (!durum.kuyrukAcik) { sonImza = null; return; }

  const imza = `${durum.acikIs || ''}|${JSON.stringify(isler)}`;
  if (imza === sonImza) return;
  sonImza = imza;

  doldur(liste, isler.slice().reverse().map(isKart));
}

function isKart(j) {
  const acik = durum.acikIs === j.id;
  const s = j.sayilar || {};
  const oran = Math.round((j.ilerleme || 0) * 100);
  const surüyor = j.durum === 'bekliyor' || j.durum === 'calisiyor';

  return el('div', { sinif: 'is-kart', veri: { durum: j.durum } }, [
    el('div', { stil: 'display:flex;align-items:stretch' }, [
      el('button', {
        type: 'button', sinif: 'is-basi',
        'aria-expanded': String(acik),
        onclick: () => ata({ acikIs: acik ? null : j.id }),
      }, [
        el('span', {
          sinif: 'nokta', veri: { durum: IS_RENK[j.durum] || 'gri' },
          'aria-hidden': 'true',
        }),
        el('span', { stil: 'min-width:0;flex:1' }, [
          el('span', { sinif: 'ad', metin: j.baslik }),
          el('span', {
            sinif: 'alt', veri: { durum: IS_RENK[j.durum] || 'gri' },
            stil: 'color:var(--durum-renk)',
            metin: `${IS_DURUM_ETIKET[j.durum] || j.durum} · %${oran}`,
          }),
        ]),
        el('span', {
          stil: 'display:flex;gap:7px;flex:none;font-family:var(--f-mono);font-size:10px',
        }, [
          el('span', { stil: 'color:var(--yesil)', metin: String(s.basarili ?? 0) }),
          el('span', { stil: 'color:var(--turuncu)', metin: String(s.erisimBekleyen ?? 0) }),
          el('span', { stil: 'color:var(--kirmizi)', metin: String(s.hatali ?? 0) }),
        ]),
      ]),
      surüyor
        ? el('button', {
            type: 'button', sinif: 'btn btn-x',
            stil: 'align-self:center;margin-right:9px',
            title: 'İşi iptal et', 'aria-label': `${j.baslik} işini iptal et`,
            onclick: async () => {
              try { await api.isIptal(j.id); } catch (e) { hata(e.message); }
            },
          }, ['⏹'])
        : el('button', {
            type: 'button', sinif: 'btn btn-x',
            stil: 'align-self:center;margin-right:9px',
            title: 'Kuyruktan kaldır',
            'aria-label': `${j.baslik} işini kuyruktan kaldır`,
            onclick: async () => {
              try { await api.isSil(j.id); } catch (e) { hata(e.message); }
            },
          }, ['×']),
    ]),

    j.hata ? el('div', {
      sinif: 'uyari', stil: 'margin:8px 11px', metin: j.hata,
    }) : null,

    acik ? el('div', { sinif: 'is-satirlar' },
      (j.satirlar || []).map(q => satirCiz(q, j.id))) : null,
  ]);
}

function satirCiz(q, isId) {
  const renk = SATIR_RENK[q.durum] || 'gri';
  // Alt satırda yalnız IP var. Hata sebebi ("zaman aşımı", "adb connect
  // reddedildi" gibi) kuyruğu okunmaz hale getiriyordu; ayrıntı cihaz
  // detayında ve satırın title'ında duruyor.
  //
  // Dosya satırında (üretilen Excel) alt satır IP değil, dosyayı açan iki
  // düğmedir: dosyayı üreten ekranda bırakıp kullanıcıyı Finder/Gezgin'de
  // dosya aramaya göndermenin bir gerekçesi yok.
  return el('div', {
    sinif: 'is-satir', veri: { islem: q.durum },
    title: q.not || '',
  }, [
    el('span', { sinif: 'nokta', veri: { durum: renk }, 'aria-hidden': 'true' }),
    el('span', { sinif: 'is-govde' }, [
      el('span', { sinif: 'ad', metin: q.ad }),
      q.dosya
        ? el('span', { sinif: 'dosya-eylem' }, [
            dosyaDugmesi('Dosyayı aç', isId, q.cihazId, false),
            dosyaDugmesi('Klasörde göster', isId, q.cihazId, true),
          ])
        : (q.ip ? el('span', { sinif: 'alt', metin: q.ip }) : null),
    ]),
    el('span', {
      sinif: 'durum', veri: { durum: renk }, stil: 'color:var(--durum-renk)',
      metin: SATIR_DURUM_ETIKET[q.durum] || q.durum,
    }),
  ]);
}

// Simgeler geometriden çizilir; yazı tipi karakteri ya da emoji üç
// işletim sisteminde üç ayrı şey gösterirdi.
const SIMGE = {
  ac: ['M4 10.5v4.5h12v-4.5', 'M10 3.5v8', 'M7 8.5l3 3 3-3'],
  klasor: ['M3 5.5h5l1.4 2H17v8H3z'],
};

function dosyaDugmesi(etiket, isId, satirId, klasor) {
  return el('button', {
    type: 'button', sinif: 'btn btn-kucuk dosya-btn',
    title: etiket, 'aria-label': etiket,
    onclick: async () => {
      try {
        await api.isDosya(isId, satirId, klasor);
      } catch (e) { hata(e.message); }
    },
  }, [
    ikon(klasor ? SIMGE.klasor : SIMGE.ac, 13),
    el('span', { metin: klasor ? 'Klasör' : 'Aç' }),
  ]);
}

export function acKapat() {
  ata({ kuyrukAcik: !durum.kuyrukAcik, kilitAcik: false });
}

// "Kuyruğa eklendi" haberi. Panel açılmadığı için haberin görüneceği tek
// yer düğmenin kendisi: rozet zaten sayıyı gösteriyor, bu da gözü oraya
// çeken kısa bir vurgu. Zamanlayıcı tek: arka arkaya basıldığında vurgu
// yeniden başlar, üst üste binmez.
let vurguZaman = null;

export function isaretle() {
  const btn = $('#kuyruk-btn');
  if (!btn) return;
  clearTimeout(vurguZaman);
  btn.removeAttribute('data-yeni');
  // Niteliği hemen geri koymak animasyonu yeniden başlatmaz; arada bir
  // yerleşim hesabı zorlamak gerekiyor. requestAnimationFrame de işi
  // görürdü ama pencere boyanmıyorken hiç çalışmıyor — geri bildirim
  // çizime bağlı kalmamalı.
  void btn.offsetWidth;
  btn.setAttribute('data-yeni', '1');
  vurguZaman = setTimeout(() => btn.removeAttribute('data-yeni'), 2600);
}

// `yenilenen`: hafif yenilemenin kaç cihaza gittiği. İş yokken alt barda
// yazılır — yenilemenin yalnız doğrulanmış cihazları okuduğu, sayıyı
// görünce belli olsun.
export function ozetMetni(yenilenen = 0) {
  const j = (durum.isler || []).find(
    x => x.durum === 'calisiyor' || x.durum === 'bekliyor');
  if (!j) {
    if (!durum.sonTarama) return 'Henüz tarama yapılmadı';
    const taze = `Son tarama ${saat(durum.sonTarama)}`;
    return yenilenen
      ? `${taze} · yenileme ${yenilenen} doğrulanmış cihazda`
      : `${taze} · yenilenecek doğrulanmış cihaz yok`;
  }
  return `${j.baslik} · %${Math.round((j.ilerleme || 0) * 100)}`;
}

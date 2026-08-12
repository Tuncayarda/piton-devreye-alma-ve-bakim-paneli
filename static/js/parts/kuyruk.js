// İşlem kuyruğu paneli.
//
// İş satırlarında yalnızca sunucunun ürettiği güvenli metin gösterilir:
// parola, başlık ya da ham yığın izi buraya hiç gelmez.

import { el, doldur, ikon, $ } from '../core/dom.js';
import { api } from '../core/api.js';
import { durum, ata } from '../core/durum.js';
import {
  IS_DURUM_ETIKET, IS_SONUC_ETIKET, IS_SONUC_RENK,
  SATIR_DURUM_ETIKET, SATIR_RENK, saat,
} from '../core/bicim.js';
import { bildir, hata } from './bildirim.js';

const IS_RENK = {
  bekliyor: 'gri', calisiyor: 'mavi', tamam: 'yesil',
  iptal: 'turuncu', hata: 'kirmizi',
};

// Liste yalnız gerçekten değiştiğinde yeniden kurulur. Cihaz okuması her
// birkaç saniyede durumu tazeliyor; kuyruk o turlarda değişmemiş olsa da
// baştan çiziliyordu ve açık bir işin onlarca satırı her seferinde
// yeniden yaratılıyordu.
let sonImza = null;

// Adımları açılmış satırlar — `${isId}:${satirId}`. VARSAYILAN KAPALI:
// IP atama koşusunda on iki port var, her birinin altında sekiz on adım;
// hepsi açık başlasa kuyruk yüz satırlık bir döküme dönerdi. Kullanıcı
// hangi portun nerede olduğunu merak ettiğinde o satıra basar.
const acikSatir = new Set();

function satirAcKapat(anahtar) {
  if (acikSatir.has(anahtar)) acikSatir.delete(anahtar);
  else acikSatir.add(anahtar);
  ciz();
  // Liste baştan kuruluyor: basılan düğme yok olup yerine yenisi geliyor
  // ve odak gövdeye düşüyordu. Klavyeyle gezen kişi bir satırı açtıktan
  // sonra Tab'a bastığında listenin başına dönüyordu.
  const yeni = $(`[data-anahtar="${CSS.escape(anahtar)}"]`);
  if (yeni) yeni.focus();
}

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

  const imza = `${durum.acikIs || ''}|${[...acikSatir].sort().join(',')}`
    + `|${JSON.stringify(isler)}`;
  if (imza === sonImza) return;
  sonImza = imza;

  doldur(liste, isler.slice().reverse().map(isKart));
}

function isKart(j) {
  const acik = durum.acikIs === j.id;
  const s = j.sayilar || {};
  const oran = Math.round((j.ilerleme || 0) * 100);
  const surüyor = j.durum === 'bekliyor' || j.durum === 'calisiyor';
  // Durdurma anında bitmez: worker o sırada bir cihazın zaman aşımını
  // bekliyor olabilir. Bu aralıkta durum "Durduruluyor…" yazar, düğme de
  // basılamaz olur — yoksa kullanıcı hiçbir şey olmadı sanıp tekrar basıyor.
  const duruyor = surüyor && j.iptalIstendi;
  const sonucRengi = IS_SONUC_RENK[j.sonuc];
  const renk = duruyor ? 'turuncu'
    : (!surüyor && sonucRengi ? sonucRengi : (IS_RENK[j.durum] || 'gri'));
  const etiket = duruyor
    ? 'Durduruluyor…'
    : (surüyor
      ? `${IS_DURUM_ETIKET[j.durum] || j.durum} · %${oran}`
      : (IS_SONUC_ETIKET[j.sonuc] || IS_DURUM_ETIKET[j.durum] || j.durum));

  return el('div', { sinif: 'is-kart', veri: { durum: j.durum } }, [
    el('div', { sinif: 'is-kart-basi' }, [
      el('button', {
        type: 'button', sinif: 'is-basi',
        'aria-expanded': String(acik),
        onclick: () => ata({ acikIs: acik ? null : j.id }),
      }, [
        el('span', {
          sinif: 'nokta', veri: { durum: renk },
          'aria-hidden': 'true',
        }),
        el('span', { stil: 'min-width:0;flex:1' }, [
          el('span', { sinif: 'ad', metin: j.baslik }),
          el('span', {
            sinif: 'alt', veri: { durum: renk },
            stil: 'color:var(--durum-renk)',
            metin: etiket,
          }),
          // Aşama: yüzde tek başına "neredeyim" sorusunu cevaplamıyor.
          // "Port 14 işleniyor (3/6)" ile "%50" bir arada okununca koşu
          // izlenebilir hale geliyor.
          surüyor && j.asama
            ? el('span', { sinif: 'is-asama', metin: j.asama })
            : null,
        ]),
        el('span', {
          sinif: 'is-sayac',
          'aria-label': `${s.basarili ?? 0} başarılı, `
            + `${s.erisimBekleyen ?? 0} giriş bilgisi gerekli, `
            + `${s.hatali ?? 0} başarısız`,
        }, [
          el('span', { stil: 'color:var(--yesil)', metin: String(s.basarili ?? 0) }),
          el('span', { stil: 'color:var(--turuncu)', metin: String(s.erisimBekleyen ?? 0) }),
          el('span', { stil: 'color:var(--kirmizi)', metin: String(s.hatali ?? 0) }),
        ]),
      ]),
      surüyor
        ? el('button', {
            type: 'button', sinif: 'btn btn-x',
            disabled: duruyor,
            title: duruyor ? 'Durduruluyor…' : 'İşlemi durdur',
            'aria-label': duruyor
              ? `${j.baslik} durduruluyor` : `${j.baslik} işlemini durdur`,
            onclick: async () => {
              try {
                await api.isIptal(j.id);
                bildir(`${j.baslik} durduruluyor…`);
              } catch (e) { hata(e.message); }
            },
          }, ['⏹'])
        : el('button', {
            type: 'button', sinif: 'btn btn-x',
            title: 'Kuyruktan kaldır',
            'aria-label': `${j.baslik} işlemini kuyruktan kaldır`,
            onclick: async () => {
              try { await api.isSil(j.id); } catch (e) { hata(e.message); }
            },
          }, ['×']),
    ]),

    // İlerleme çubuğu: sayı okumadan "ne kadar kaldı" görünsün.
    surüyor ? el('div', { sinif: 'is-cubuk' }, [
      el('i', { stil: `width:${oran}%`, veri: { durum: renk } }),
    ]) : null,

    j.hata ? el('div', {
      sinif: 'uyari', stil: 'margin:8px 11px', metin: j.hata,
    }) : null,

    acik ? el('div', { sinif: 'is-satirlar' },
      (j.satirlar || []).map(q => satirCiz(q, j.id))) : null,
  ]);
}

function satirCiz(q, isId) {
  const renk = SATIR_RENK[q.durum] || 'gri';
  const adimlar = q.adimlar || [];
  const anahtar = `${isId}:${q.cihazId}`;
  const acik = adimlar.length > 0 && acikSatir.has(anahtar);

  // Alt satırda yalnız IP var. Hata sebebi ("zaman aşımı", "adb connect
  // reddedildi" gibi) kuyruğu okunmaz hale getiriyordu; ayrıntı cihaz
  // detayında ve satırın title'ında duruyor.
  //
  // Dosya satırında (üretilen Excel) alt satır IP değil, dosyayı açan iki
  // düğmedir: dosyayı üreten ekranda bırakıp kullanıcıyı Finder/Gezgin'de
  // dosya aramaya göndermenin bir gerekçesi yok.
  const govde = [
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
  ];

  // Adımı olmayan satır (dosya satırı, cihaz taraması) eskisi gibi düz
  // kalır: içinde düğme olan bir satırı düğmeye çevirmek geçersiz HTML
  // üretirdi, hem de açacak bir şey yok.
  if (!adimlar.length) {
    return el('div', {
      sinif: 'is-satir', veri: { islem: q.durum }, title: q.not || '',
    }, govde);
  }

  return el('div', { sinif: 'is-satir-kutu' }, [
    el('button', {
      type: 'button', sinif: 'is-satir is-satir-btn',
      veri: { islem: q.durum, acik: String(acik), anahtar },
      title: q.not || '',
      'aria-expanded': String(acik),
      // Düğmenin kendi metnini ezdiği için durum da tekrarlanır: yoksa
      // ekran okuyucu satırı "Port 11 · 8 adım" diye okuyup satırın
      // hangi durumda olduğunu hiç söylemezdi.
      'aria-label': `${q.ad} · ${SATIR_DURUM_ETIKET[q.durum] || q.durum}`
        + ` — ${adimlar.length} adım`,
      onclick: () => satirAcKapat(anahtar),
    }, [...govde, el('span', { sinif: 'is-ok', 'aria-hidden': 'true' })]),
    acik
      ? el('div', { sinif: 'is-adimlar' }, adimlar.map(adimCiz))
      : null,
  ]);
}

// Satırın altındaki tek adım: "cihaz bulundu: 10.1.1.12", "IP yazılıyor".
// Saat de yazılır — bir portun nerede takıldığı çoğu zaman iki adım
// arasında geçen süreden anlaşılıyor.
function adimCiz(a) {
  return el('div', { sinif: 'is-adim', veri: { islem: a.durum || 'bilgi' } }, [
    el('span', {
      sinif: 'nokta', veri: { durum: SATIR_RENK[a.durum] || 'gri' },
      'aria-hidden': 'true',
    }),
    el('span', { sinif: 'is-adim-metin', metin: a.metin }),
    el('span', { sinif: 'is-adim-saat', metin: saat(a.zaman) }),
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
  if (j && j.iptalIstendi) return `${j.baslik} · durduruluyor…`;
  if (!j) {
    // "Henüz tarama yapılmadı" artık bir eksiklik değil, birkaç saniyelik
    // bir ara durum: tarama açılışta kendiliğinden başlıyor.
    if (!durum.sonTarama) return 'İlk tarama bekleniyor…';
    const taze = `Son tarama ${saat(durum.sonTarama)}`;
    return yenilenen
      ? `${taze} · ${yenilenen} cihaz yeniden okundu`
      : `${taze} · yeniden okunabilecek cihaz yok`;
  }
  return `${j.baslik} · %${Math.round((j.ilerleme || 0) * 100)}`;
}

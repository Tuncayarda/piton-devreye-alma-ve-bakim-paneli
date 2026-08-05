// Genel Bakış — KPI'lar, kategori durumu, sıradaki adımlar, son işlemler.
//
// Bütün sayılar o anki tarama görüntüsünden gelir. Hiç tarama yapılmadıysa
// sayılar sıfır değil, "okunmadı" olarak görünür: 0 aktif cihaz ile
// "henüz sormadık" farklı şeyler.
//
// Sayfada aynı bilgi iki kez durmaz. Eski "Sistem Özeti" kartı kategori
// listesinin aynısını başka adlarla tekrarlıyordu (Anons zinciri = Anons
// Ekipmanları, Video sistemi = Video Sistemi …); yerine ne yapılması
// gerektiğini söyleyen "Sıradaki Adımlar" geldi.
//
// Sayfadaki her sayı tıklanabilir: sayıyı görüp arkasındaki cihaz listesini
// elle bulmak fazladan bir adımdı.

import { el, doldur } from '../core/dom.js';
import { durum, ata } from '../core/durum.js';
import { yuzde, saat, tazelik, IS_DURUM_ETIKET, YOK } from '../core/bicim.js';

// Kutucuklar: büyük sayı + neyin içinde olduğu + doluluk çubuğu.
// Çubuğun altında açıklama yazısı yok; sayı ile çubuk zaten aynı şeyi
// söylüyordu, alt satır yalnız gürültü yapıyordu.
function kpi(ad, dgr, birim, renk, oran, git, ipucu) {
  return el('button', {
    type: 'button', sinif: 'kpi kose', title: ipucu || '', onclick: git,
  }, [
    el('div', { sinif: 'ad', metin: ad }),
    el('div', { sinif: 'deger-sar' }, [
      el('span', { sinif: 'deger', stil: `color:var(--${renk})`, metin: String(dgr) }),
      birim ? el('span', { sinif: 'birim', metin: birim }) : null,
    ]),
    el('div', { sinif: 'cubuk' }, [
      el('i', { stil: `width:${oran};background:var(--${renk})` }),
    ]),
  ]);
}

// Cihaz listesine belirli bir süzgeçle gider.
function listeye(filtre) {
  ata({ gorunum: 'cihaz', kategori: 'tum', altTip: null, filtre });
}

export function ciz(kok, guncelle) {
  const cihazlar = durum.cihazlar;
  const n = cihazlar.length;
  const s = durum.sayilar;
  const taramaVar = !!durum.sonTarama;
  const surumlu = cihazlar.filter(
    c => c.sonuc.alanlar && c.sonuc.alanlar.surum).length;

  const parcalar = [];

  // Başlıktaki tarama zamanı, sayfadaki bütün sayıların ne kadar taze
  // olduğunu söyler; sayılara bakmadan önce görülmesi gereken tek şey bu.
  parcalar.push(el('div', { sinif: 'sayfa-basi' }, [
    el('div', {}, [
      el('h2', { metin: 'Devreye Alma Durumu' }),
      el('div', {
        sinif: 'sayfa-alt',
        metin: taramaVar
          ? `Son tarama ${saat(durum.sonTarama)} · ${tazelik(durum.sonTarama)} önce`
          : 'Cihazlar henüz okunmadı',
      }),
    ]),
    el('div', { sinif: 'eylemler' }, [
      el('button', {
        type: 'button', sinif: 'btn', metin: 'Kontrol Listesi',
        onclick: () => ata({ gorunum: 'dog' }),
      }),
    ]),
  ]));

  parcalar.push(el('div', { sinif: 'kpi-izgara' }, [
    kpi('Toplam Cihaz', n, 'kayıt', 'accent', '100%',
      () => listeye('tumu'), 'Bütün cihazları listele'),
    kpi('Doğrulanan', taramaVar ? s.basarili : YOK, `/ ${n}`, 'yesil',
      yuzde(s.basarili, n),
      () => listeye('aktif'), 'Doğrulanan cihazları listele'),
    kpi('Erişim Bekleyen', taramaVar ? s.erisimBekleyen : YOK, `/ ${n}`,
      'turuncu', yuzde(s.erisimBekleyen, n),
      () => ata({ kilitAcik: true, kuyrukAcik: false }),
      'Kullanıcı adı / parola bekleyen cihazları aç'),
    kpi('Yanıt Vermeyen', taramaVar ? s.hatali : YOK, `/ ${n}`, 'kirmizi',
      yuzde(s.hatali, n),
      () => listeye('sorunlu'), 'Sorunlu cihazları listele'),
  ]));

  // ── kategori durumu + sağ sütun ──
  // Kategorinin hangi tipleri kapsadığı satırın ipucunda durur; ayrı bir
  // sütun olarak her satırda yazınca liste okunmuyordu.
  const katKart = el('div', { sinif: 'kart kose' }, [
    el('div', { sinif: 'kart-basi' }, [
      el('h3', { metin: 'Kategori Durumu' }),
      el('span', { stil: 'flex:1' }),
      el('span', { sinif: 'etiket', metin: 'Doğrulanan / Toplam' }),
    ]),
    ...(durum.meta ? durum.meta.kategoriler : []).map(k => {
      const ds = k.id === 'tum' ? cihazlar : cihazlar.filter(c => c.kategori === k.id);
      const aktif = ds.filter(c => c.sonuc.durum === 'yesil').length;
      const barRenk = !ds.length ? 'gri'
        : aktif === ds.length ? 'yesil' : aktif ? 'turuncu' : 'gri';
      return el('button', {
        type: 'button', sinif: 'kat-satir', title: `${k.ad} — ${k.tipler}`,
        onclick: () => ata({
          gorunum: 'cihaz', kategori: k.id, altTip: null, filtre: 'tumu',
        }),
      }, [
        el('span', { sinif: 'ad', metin: k.ad }),
        el('span', { sinif: 'bar' }, [
          el('i', {
            stil: `width:${yuzde(aktif, ds.length)};background:var(--${barRenk})`,
          }),
        ]),
        el('span', {
          sinif: 'mono acik', stil: 'font-size:11px;text-align:right',
          metin: `${aktif}/${ds.length}`,
        }),
      ]);
    }),
  ]);

  // ── sıradaki adımlar ──
  // Kart yalnız yapılacak iş varken satır gösterir; her satır o işi
  // yapacağı yere götürür.
  const adimSatir = (renk, ad, not, eylemAd, eylem) => el('div', {
    sinif: 'adim-satir',
  }, [
    el('span', { sinif: 'nokta', stil: `background:var(--${renk})`, 'aria-hidden': 'true' }),
    el('span', { sinif: 'metin' }, [
      el('span', { sinif: 'ad', metin: ad }),
      not ? el('span', { sinif: 'not', metin: not }) : null,
    ]),
    el('button', {
      type: 'button', sinif: 'btn btn-kucuk', metin: eylemAd, onclick: eylem,
    }),
  ]);

  const adimlar = [];
  if (!taramaVar) {
    adimlar.push(adimSatir('accent', 'Tarama yapılmadı',
      'Bu tren setindeki bütün cihazlar sırayla okunur.',
      'Güncelle', () => guncelle && guncelle()));
  } else {
    if (s.erisimBekleyen) {
      adimlar.push(adimSatir('turuncu',
        `${s.erisimBekleyen} cihaz kullanıcı adı / parola bekliyor`,
        'Girilen bilgiler yalnız bu oturumda bellekte tutulur.',
        'Kimlik gir', () => ata({ kilitAcik: true, kuyrukAcik: false })));
    }
    if (s.hatali) {
      adimlar.push(adimSatir('kirmizi', `${s.hatali} cihaz yanıt vermedi`,
        'Kablo, IP ve besleme kontrolü gerekir.',
        'Listeyi aç', () => listeye('sorunlu')));
    }
    if (!adimlar.length) {
      adimlar.push(adimSatir('yesil', 'Bütün cihazlar doğrulandı',
        'Kontrol listesi çıkarılabilir.',
        'Kontrol Listesi', () => ata({ gorunum: 'dog' })));
    }
  }

  const adimKart = el('div', { sinif: 'kart kose' }, [
    el('h3', { stil: 'margin-bottom:4px', metin: 'Sıradaki Adımlar' }),
    ...adimlar,
    // Sürüm okuma, doğrulamadan ayrı bir ölçü: cihaz yanıt verse de
    // sürümünü vermeyebiliyor.
    el('div', { sinif: 'adim-dip' }, [
      el('span', { metin: 'Sürümü okunan cihaz' }),
      el('span', {
        sinif: 'mono acik',
        metin: taramaVar ? `${surumlu}/${n}` : `${YOK}/${n}`,
      }),
    ]),
  ]);

  const gecmisKart = el('div', { sinif: 'kart kose' }, [
    el('h3', { stil: 'margin-bottom:11px', metin: 'Son İşlemler' }),
    ...(durum.isler.length
      ? durum.isler.slice(-6).reverse().map(j => el('div', {
          stil: 'display:flex;gap:10px;padding:6px 0;font-family:var(--f-mono);'
            + 'font-size:10.5px;line-height:1.5',
        }, [
          el('span', { sinif: 'soluk', stil: 'flex:none', metin: saat(j.olusturma) }),
          el('span', {
            sinif: 'nokta',
            veri: { durum: j.durum === 'hata' ? 'kirmizi' : j.durum === 'tamam' ? 'yesil' : 'turuncu' },
            stil: 'margin-top:5px',
            'aria-hidden': 'true',
          }),
          el('span', {
            sinif: 'acik',
            metin: `${j.baslik} — ${IS_DURUM_ETIKET[j.durum] || j.durum}`,
          }),
        ]))
      : [el('div', { sinif: 'mono soluk', stil: 'font-size:11px', metin: 'Kayıt yok' })]),
  ]);

  parcalar.push(el('div', { sinif: 'genel-izgara' }, [
    katKart,
    el('div', { stil: 'display:flex;flex-direction:column;gap:18px' },
      [adimKart, gecmisKart]),
  ]));

  doldur(kok, parcalar);
}

// Ana menü: içeriğin solunda duran dar ikon rayı.
//
// Menü önce 250 piksellik bir sütundu: beş satır için ekranın altıda birini
// sürekli kaplıyordu. Sonra köşeden açılan balon menü denendi; yer
// kaplamıyordu ama bulunması ve kullanılması zordu — alan değiştirmek
// düğmeyi bulmak, açmak ve dağılmayı beklemek demekti.
//
// Ray ikisinin ortası: 56 piksel, her zaman ekranda, tek tıklamada geçiş.
// Alan adları ikonun üstüne gelince yanda beliren balonda yazar; adları
// kalıcı görmek isteyen rayı alttaki düğmeyle genişletir (bu tercih
// `durum.kenarAcik` içinde tutulur, oturum boyunca korunur).
//
// Cihaz kategorileri burada ayrı hedefler değildir. Cihazlar ekranındaki
// süzgeçler aynı işi bağlamı kaybetmeden yapar. IP, cihaz ayarları ve yazılım
// ekranları da tek bir "İşlemler" alanının görünümleridir; menü süreç adımı
// gibi davranmaz ve kullanıcı bu ekranlar arasında istediği sırada geçebilir.

import { el, doldur, ikon, $ } from '../core/dom.js';
import { durum, ata } from '../core/durum.js';

const ISLEM_GORUNUMLERI = new Set(['ip', 'cfg', 'fw']);

const ANA_ALANLAR = [
  {
    ad: 'Genel bakış', gorunum: 'genel',
    aktif: g => g === 'genel',
    ikon: ['M3 10.5L10 4l7 6.5', 'M5.5 9.5V16h9V9.5'],
  },
  {
    ad: 'Cihazlar', gorunum: 'cihaz',
    aktif: g => g === 'cihaz',
    ikon: ['M4 4.5h12v4H4z', 'M4 11.5h12v4H4z', 'M6.5 6.5h.01M6.5 13.5h.01'],
    yama: { kategori: 'tum', altTip: null, filtre: 'tumu' },
  },
  {
    ad: 'İşlemler', gorunum: 'ip',
    aktif: g => ISLEM_GORUNUMLERI.has(g),
    ikon: ['M5 5h10v10H5z', 'M8 8h4M10 6v4'],
  },
  {
    ad: 'Doğrulama ve raporlar', gorunum: 'dog',
    aktif: g => g === 'dog',
    ikon: ['M6 3.5h8v13H6z', 'M8 7h4M8 10h4M8 13h2.5'],
  },
  {
    ad: 'Geçmiş', gorunum: 'gecmis',
    aktif: g => g === 'gecmis',
    ikon: ['M10 4a6 6 0 1 1-5.2 3', 'M3.5 4.5v3h3', 'M10 7v3.5l2.5 1.5'],
  },
];

const YONETIM_ALANLARI = [
  {
    ad: 'PISCU ve PBX', gorunum: 'piscu', yonetim: true,
    ikon: ['M4 6h12v8H4z', 'M7 9h6M7 11.5h3'],
  },
  {
    ad: 'MQTT izleme', gorunum: 'mqtt', yonetim: true,
    ikon: ['M4 14a6 6 0 0 1 6-6', 'M4 14a10 10 0 0 1 10-10', 'M4.5 14h.01'],
  },
  {
    ad: 'Proje ve cihaz listesi', gorunum: 'admin', yonetim: true,
    ikon: ['M5 4.5h10v11H5z', 'M7.5 8h5M7.5 11h5'],
  },
];

function alanlar() {
  return durum.rol === 'admin'
    ? [...ANA_ALANLAR, ...YONETIM_ALANLARI] : ANA_ALANLAR;
}

function seciliMi(o) {
  return o.aktif ? o.aktif(durum.gorunum) : durum.gorunum === o.gorunum;
}

// Ray her durum değişiminde baştan kurulmaz. Tarama sürerken çizim
// saniyede bir geliyor; düğmeleri her turda yeniden yaratmak, imlecin
// altındaki ad balonunu her seferinde sıfırdan açtırıyordu (titreme).
// Yapı bir kez kurulur, sonrasında yalnız seçili işareti güncellenir.
let kurulu = null;

function menuDugmesi(o) {
  return el('button', {
    type: 'button', sinif: 'kenar-oge',
    veri: { yonetim: o.yonetim ? '1' : '0' },
    // Ad daralmış rayda balon olarak görünür; ekran okuyucu için de
    // düğmenin kendi etiketi burada.
    'aria-label': o.ad,
    onclick: () => ata({
      gorunum: o.gorunum,
      ...(o.yama || {}),
    }),
  }, [
    el('span', { sinif: 'kenar-ikon' }, [ikon(o.ikon, 17)]),
    el('span', { sinif: 'kenar-ad', metin: o.ad }),
  ]);
}

function kur(kok) {
  const liste = alanlar();
  const dugmeler = liste.map(menuDugmesi);
  // Yönetim araçları saha akışının parçası değil; aradaki çizgi bunu
  // daralmış rayda da gösteriyor.
  const icerik = [];
  liste.forEach((o, i) => {
    if (o.yonetim && !liste[i - 1].yonetim) {
      icerik.push(el('span', { sinif: 'kenar-ayrac', 'aria-hidden': 'true' }));
    }
    icerik.push(dugmeler[i]);
  });

  const genisletIkon = el('span', { sinif: 'kenar-genislet-ikon' }, [
    ikon(['M7.5 5.5L12 10l-4.5 4.5'], 15),
  ]);
  const genislet = el('button', {
    type: 'button', sinif: 'kenar-genislet',
    onclick: () => ata({ kenarAcik: !durum.kenarAcik }),
  }, [genisletIkon]);

  doldur(kok, [
    el('nav', { sinif: 'kenar-liste', 'aria-label': 'Ana alanlar' }, icerik),
    genislet,
  ]);
  kurulu = { rol: durum.rol, liste, dugmeler, genislet };
}

export function ciz() {
  const kok = $('#kenar');
  if (!kok || !durum.meta) return;

  if (!kurulu || kurulu.rol !== durum.rol || !kok.firstChild) kur(kok);

  const genis = !!durum.kenarAcik;
  kok.dataset.genis = genis ? '1' : '0';
  kurulu.genislet.setAttribute('aria-expanded', String(genis));
  kurulu.genislet.setAttribute(
    'aria-label', genis ? 'Menüyü daralt' : 'Menüyü genişlet');
  kurulu.genislet.title = genis ? 'Menüyü daralt' : 'Alan adlarını göster';

  kurulu.liste.forEach((o, i) => {
    const d = kurulu.dugmeler[i];
    if (seciliMi(o)) d.setAttribute('aria-current', 'page');
    else d.removeAttribute('aria-current');
  });
}

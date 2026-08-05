// Sol menü: cihaz kategorileri, işlemler ve admin bölümü.
//
// Kategoriler yalnız başlık adlarıyla listelenir; alt tiplere inilmez.
// Alt tip kırılımı gerekince cihaz listesindeki filtre kullanılır — menüyü
// iki kademe derinleştirmek sahada okunurluğu düşürüyordu.

import { el, doldur, ikon, $ } from '../core/dom.js';
import { durum, ata } from '../core/durum.js';

// Sıra ekranda göründüğü gibidir: kontrol listesi en üstte, çünkü saha
// çalışmasında en sık açılan ekran o.
const ISLEMLER = [
  { id: 'dog', ad: 'Kontrol Listesi' },
  { id: 'ip', ad: 'IP Atama' },
  { id: 'cfg', ad: 'Konfigürasyon' },
  { id: 'fw', ad: 'Yazılım Yükleme' },
  { id: 'piscu', ad: 'PISCU & PBX', adminMi: true },
  { id: 'mqtt', ad: 'MQTT İzleme', adminMi: true },
];

export function ciz() {
  const kok = $('#kenar');
  if (!kok) return;
  const admin = durum.rol === 'admin';
  const meta = durum.meta;
  if (!meta) return;

  kok.dataset.acik = durum.kenarAcik ? '1' : '0';

  const parcalar = [];

  parcalar.push(el('button', {
    type: 'button', sinif: 'kenar-genel',
    'aria-current': durum.gorunum === 'genel' ? 'page' : null,
    onclick: () => ata({ gorunum: 'genel', kenarAcik: false }),
  }, [
    ikon(['M3 10.5L10 4l7 6.5', 'M5.5 9.5V16h9V9.5'], 15),
    'Genel Bakış',
  ]));

  parcalar.push(el('div', { sinif: 'baslik', metin: 'Cihaz Kategorileri' }));

  for (const k of meta.kategoriler) {
    const ds = k.id === 'tum'
      ? durum.cihazlar
      : durum.cihazlar.filter(c => c.kategori === k.id);
    const aktif = ds.filter(c => c.sonuc.durum === 'yesil').length;
    const secili = durum.gorunum === 'cihaz' && durum.kategori === k.id;

    parcalar.push(el('button', {
      type: 'button', sinif: 'kenar-oge',
      'aria-current': secili ? 'page' : null,
      title: k.tipler,
      onclick: () => ata({
        gorunum: 'cihaz', kategori: k.id, altTip: null, kenarAcik: false,
      }),
    }, [
      el('span', { stil: 'flex:1', metin: k.ad }),
      el('span', { sinif: 'n', stil: 'color:var(--yesil)', metin: String(aktif) }),
      el('span', { sinif: 'n soluk', metin: `/${ds.length}` }),
    ]));
  }

  parcalar.push(el('div', { sinif: 'baslik', metin: 'İşlemler' }));
  for (const o of ISLEMLER) {
    if (o.adminMi && !admin) continue;
    parcalar.push(el('button', {
      type: 'button', sinif: 'kenar-oge',
      'aria-current': durum.gorunum === o.id ? 'page' : null,
      onclick: () => ata({ gorunum: o.id, kenarAcik: false }),
    }, [el('span', { stil: 'flex:1', metin: o.ad })]));
  }

  if (admin) {
    parcalar.push(el('div', { sinif: 'baslik', metin: 'Admin' }));
    parcalar.push(el('button', {
      type: 'button', sinif: 'kenar-oge',
      'aria-current': durum.gorunum === 'admin' ? 'page' : null,
      onclick: () => ata({ gorunum: 'admin', kenarAcik: false }),
    }, [el('span', { stil: 'flex:1', metin: 'Proje & Cihaz Listesi' })]));
  }

  doldur(kok, parcalar);
}

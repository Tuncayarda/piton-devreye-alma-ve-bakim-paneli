// Cihaz listesi. Satıra tıklanınca detay çekmecesi açılır.
//
// Tarama ilerlemesi bu listede gösterilmez; canlı adım adım durum işlem
// kuyruğundadır. Liste her zaman cihazın son bilinen durumunu gösterir.

import { el, doldur } from '../core/dom.js';
import { durum, ata, gorunenCihazlar } from '../core/durum.js';
import {
  deger, DURUM_ETIKET, surumOf, calismaOf, tipEtiketi,
} from '../core/bicim.js';
import * as detay from '../parts/detay.js';

// "Switch · Port" sütunu switch adının tamamını taşıyor (Yataklı_1 · p11);
// dar bırakınca metin sığmıyordu.
const KOLON = 'minmax(180px,1.4fr) minmax(140px,1fr) minmax(150px,1fr) '
  + '120px 100px 120px 96px';

const FILTRELER = [
  { id: 'tumu', ad: 'Tümü' },
  { id: 'aktif', ad: 'Erişilebilir' },
  { id: 'sorunlu', ad: 'İncelenecek' },
];

export function ciz(kok) {
  const kategoriler = durum.meta ? durum.meta.kategoriler : [];
  const kat = kategoriler
    .find(k => k.id === durum.kategori);
  const liste = gorunenCihazlar();
  const kategoriToplami = durum.kategori === 'tum'
    ? durum.cihazlar.length
    : durum.cihazlar.filter(c => c.kategori === durum.kategori).length;

  const parcalar = [];

  parcalar.push(el('div', { sinif: 'sayfa-basi' }, [
    el('div', {}, [
      el('h2', { metin: 'Cihazlar' }),
      el('div', {
        sinif: 'sayfa-alt',
        metin: `${kat ? kat.ad : 'Tüm cihazlar'} · ${kategoriToplami} cihaz`,
      }),
    ]),
    el('div', {
      sinif: 'yerel-sekmeler',
      role: 'group', 'aria-label': 'Durum filtresi',
    }, FILTRELER.map(f => el('button', {
      type: 'button',
      sinif: 'yerel-sekme',
      'aria-pressed': String(durum.filtre === f.id),
      metin: f.ad,
      onclick: () => ata({ filtre: f.id }),
    }))),
  ]));

  // Kategoriler birer ana ekran değil, cihaz listesinin süzgecidir.
  parcalar.push(el('div', {
    sinif: 'serit cihaz-kategori-seridi', role: 'group',
    'aria-label': 'Cihaz kategorisi',
  }, [
    el('span', { sinif: 'etiket', metin: 'Kategori' }),
    ...kategoriler.map(k => {
      const sayi = k.id === 'tum'
        ? durum.cihazlar.length
        : durum.cihazlar.filter(c => c.kategori === k.id).length;
      return el('button', {
        type: 'button', sinif: 'cip', title: k.tipler,
        'aria-pressed': String(durum.kategori === k.id),
        onclick: () => ata({ kategori: k.id, altTip: null }),
      }, [
        el('span', { metin: k.ad }),
        el('span', { sinif: 'n', metin: String(sayi) }),
      ]);
    }),
  ]));

  const basliklar = ['Cihaz', 'Tür / Alt tür', 'Switch · Port', 'IP',
    'Sürüm', 'Erişim durumu', 'Çalışma süresi'];

  const satirlar = liste.map(c => {
    const s = c.sonuc || {};
    return el('button', {
      type: 'button', sinif: 'tablo-satir',
      stil: `--tablo-kolon:${KOLON}`,
      'aria-selected': String(durum.detayId === c.id),
      title: s.aciklama || '',
      onclick: () => detay.ac(c.id),
    }, [
      el('span', { stil: 'display:flex;align-items:center;gap:8px;min-width:0' }, [
        el('span', { sinif: 'nokta', veri: { durum: s.durum }, 'aria-hidden': 'true' }),
        el('span', { sinif: 'mono kirp', stil: 'font-size:12.5px', metin: c.ad }),
      ]),
      el('span', {
        sinif: 'acik kirp', stil: 'font-size:12.5px',
        metin: tipEtiketi(c.tipEtiket),
      }),
      el('span', {
        sinif: 'mono orta kirp', stil: 'font-size:11px',
        title: c.portEtiket, metin: c.portEtiket,
      }),
      el('span', { sinif: 'mono', stil: 'font-size:12px', metin: c.ip }),
      el('span', {
        sinif: 'mono kirp', stil: 'font-size:11.5px'
          + (surumOf(c) ? ';color:var(--yesil)' : ';color:var(--soluk)'),
        metin: deger(surumOf(c)),
      }),
      el('span', {
        sinif: 'durum-yazi', veri: { durum: s.durum },
        stil: 'font-family:var(--f-baslik);font-weight:600;font-size:13px;'
          + 'letter-spacing:.08em;text-transform:uppercase',
        metin: DURUM_ETIKET[s.durum] || '',
      }),
      el('span', { sinif: 'mono orta', stil: 'font-size:11px', metin: deger(calismaOf(c)) }),
    ]);
  });

  parcalar.push(el('div', { sinif: 'tablo-sar' }, [
    el('div', { sinif: 'tablo', stil: '--tablo-min:960px' }, [
      el('div', {
        sinif: 'tablo-basi', stil: `--tablo-kolon:${KOLON}`, role: 'row',
      }, basliklar.map(b => el('span', { metin: b }))),
      ...(satirlar.length ? satirlar
        : [el('div', {
          sinif: 'tablo-bos', metin: 'Bu ölçütlere uyan cihaz bulunamadı.',
        })]),
    ]),
  ]));

  doldur(kok, parcalar);
}

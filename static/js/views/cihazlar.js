// Cihaz listesi. Satıra tıklanınca detay çekmecesi açılır.
//
// Tarama ilerlemesi bu listede gösterilmez; canlı adım adım durum işlem
// kuyruğundadır. Liste her zaman cihazın son bilinen durumunu gösterir.

import { el, doldur } from '../core/dom.js';
import { durum, ata, gorunenCihazlar } from '../core/durum.js';
import { deger, DURUM_ETIKET, surumOf, calismaOf } from '../core/bicim.js';
import * as detay from '../parts/detay.js';

// "Switch · Port" sütunu switch adının tamamını taşıyor (Yataklı_1 · p11);
// dar bırakınca metin sığmıyordu.
const KOLON = 'minmax(180px,1.4fr) minmax(140px,1fr) minmax(150px,1fr) '
  + '120px 100px 120px 96px';

const FILTRELER = [
  { id: 'tumu', ad: 'Tümü' },
  { id: 'aktif', ad: 'Doğrulanan' },
  { id: 'sorunlu', ad: 'Sorunlu' },
];

export function ciz(kok) {
  const kat = (durum.meta ? durum.meta.kategoriler : [])
    .find(k => k.id === durum.kategori);
  const liste = gorunenCihazlar();

  const parcalar = [];

  parcalar.push(el('div', { sinif: 'sayfa-basi' }, [
    el('div', {}, [el('h2', { metin: kat ? kat.ad : 'Cihazlar' })]),
    el('div', {
      stil: 'display:flex;gap:2px;border:1px solid var(--cizgi-kuvvetli)',
      role: 'group', 'aria-label': 'Durum filtresi',
    }, FILTRELER.map(f => el('button', {
      type: 'button',
      sinif: 'btn btn-kucuk',
      stil: 'border:0;letter-spacing:.02em;text-transform:none;'
        + 'font-family:var(--f-govde);font-size:12.5px'
        + (durum.filtre === f.id
          ? ';background:var(--accent);color:var(--derin)' : ''),
      'aria-pressed': String(durum.filtre === f.id),
      metin: f.ad,
      onclick: () => ata({ filtre: f.id }),
    }))),
  ]));

  const basliklar = ['Cihaz', 'Tip / Alt Tip', 'Switch · Port', 'IP',
    'Versiyon', 'Durum', 'Çalışma'];

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
      el('span', { sinif: 'acik kirp', stil: 'font-size:12.5px', metin: c.tipEtiket }),
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
        : [el('div', { sinif: 'tablo-bos', metin: 'Bu filtreye uyan cihaz yok' })]),
    ]),
  ]));

  doldur(kok, parcalar);
}

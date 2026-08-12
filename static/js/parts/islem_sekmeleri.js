// İşlem ekranları arasındaki ortak yerel gezinme.
//
// Bu alan bir süreç göstergesi değildir: kullanıcı bakım sırasında ağ, cihaz
// ayarları ve yazılım ekranlarına istediği sırada geçebilir. Ekran seçimi
// uygulamanın mevcut `gorunum` durumuyla yönetilir.

import { el } from '../core/dom.js';
import { durum, ata } from '../core/durum.js';

const SEKMELER = [
  { id: 'ip', ad: 'Ağ ve IP' },
  { id: 'cfg', ad: 'Cihaz Ayarları' },
  { id: 'fw', ad: 'Yazılım' },
];

export function ciz() {
  return el('nav', {
    sinif: 'islem-sekmeleri',
    'aria-label': 'İşlem alanları',
  }, [
    el('div', { sinif: 'islem-sekme-listesi' }, SEKMELER.map(sekme => {
      const aktif = durum.gorunum === sekme.id;
      return el('button', {
        type: 'button',
        sinif: `islem-sekmesi${aktif ? ' aktif' : ''}`,
        veri: { aktif: aktif ? '1' : '0', gorunum: sekme.id },
        'aria-current': aktif ? 'page' : null,
        metin: sekme.ad,
        onclick: aktif ? null : () => ata({ gorunum: sekme.id }),
      });
    })),
  ]);
}

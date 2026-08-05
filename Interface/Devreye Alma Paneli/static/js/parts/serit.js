// "Hedef grup" şeridi — IP atama, konfigürasyon, firmware ve kontrol
// listesi ekranlarının tepesindeki ortak seçici.
import { el } from '../core/dom.js';
import { durum, ata } from '../core/durum.js';

export function gruplar(op) {
  const meta = durum.meta;
  if (!meta) return [];
  return meta.gruplar.filter(g => g.ops.split(' ').includes(op));
}

export function eslesen(g) {
  if (g.tip === '*') return durum.cihazlar.filter(c => c.type !== 'Switch');
  return durum.cihazlar.filter(
    c => c.type === g.tip && (!g.alt || (c.subtype || '') === g.alt));
}

// Seçili grup bu işlemde geçerli değilse ilk geçerli gruba düşer.
export function gecerliGrup(op) {
  const liste = gruplar(op);
  if (!liste.length) return null;
  return liste.find(g => g.ad === durum.hedefGrup) || liste[0];
}

export function ciz(op, secilenler = () => {}) {
  const liste = gruplar(op);
  const aktif = gecerliGrup(op);
  return el('div', {
    sinif: 'serit', role: 'group', 'aria-label': 'Hedef cihaz grubu',
  }, [
    el('span', { sinif: 'etiket', metin: 'Hedef grup' }),
    ...liste.map(g => el('button', {
      type: 'button', sinif: 'cip',
      'aria-pressed': String(!!aktif && aktif.ad === g.ad),
      onclick: () => { ata({ hedefGrup: g.ad }); secilenler(g); },
    }, [
      el('span', { metin: g.ad }),
      el('span', { sinif: 'n', metin: String(eslesen(g).length) }),
    ])),
  ]);
}

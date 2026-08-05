// Modal diyalog altyapısı: odak yönetimi, Escape, perdeye tıklayınca
// kapanma. Açılırken odak diyaloga girer, kapanınca çağıran düğmeye döner.
import { el, doldur, odakTuzagi, $ } from '../core/dom.js';

let acik = null;

export function kapat() {
  if (!acik) return;
  const { perde, coz, oncekiOdak } = acik;
  coz();
  perde.remove();
  acik = null;
  if (oncekiOdak && document.contains(oncekiOdak)) oncekiOdak.focus();
}

export function ac({ baslik, icerik, eylemler = [], genislik }) {
  kapat();
  const oncekiOdak = document.activeElement;

  const kutu = el('div', {
    sinif: 'diyalog', role: 'dialog', 'aria-modal': 'true',
    'aria-labelledby': 'diyalog-baslik',
    stil: genislik ? `width:min(${genislik},100%)` : null,
  }, [
    el('h3', { id: 'diyalog-baslik', metin: baslik }),
    icerik,
    eylemler.length ? el('div', { sinif: 'eylemler' }, eylemler) : null,
  ]);

  const perde = el('div', {
    sinif: 'perde',
    onclick: (e) => { if (e.target === perde) kapat(); },
  }, [kutu]);

  doldur($('#diyalog-yuva'), [perde]);
  const coz = odakTuzagi(perde, kapat);
  acik = { perde, coz, oncekiOdak };

  const ilk = kutu.querySelector('input, button, select, textarea');
  if (ilk) ilk.focus();
  return { kapat };
}

export function acikMi() { return acik !== null; }

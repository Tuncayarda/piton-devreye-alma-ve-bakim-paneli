// Alt bildirim şeridi. aria-live olduğu için ekran okuyucu da duyar.
import { $ } from '../core/dom.js';

let zaman = null;

export function bildir(metin, tur = 'bilgi', sure = 4200) {
  const kutu = $('#bildirim');
  if (!kutu) return;
  kutu.textContent = String(metin);
  kutu.dataset.tur = tur;
  kutu.hidden = false;
  clearTimeout(zaman);
  zaman = setTimeout(() => { kutu.hidden = true; }, sure);
}

export const hata = (m) => bildir(m, 'hata', 6000);
export const basari = (m) => bildir(m, 'basari');

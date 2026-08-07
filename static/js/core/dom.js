// DOM yardımcıları.
//
// Cihazdan gelen hiçbir metin innerHTML ile basılmaz. Bütün metinler
// textContent üzerinden yazılır; bu dosyadaki `el()` başka bir yol
// sunmaz. Bir cihazın adı "<img onerror=...>" olsa bile ekranda aynen
// o metin görünür, çalışmaz.

export function el(etiket, ozellik = {}, cocuklar = []) {
  const d = document.createElement(etiket);
  for (const [k, v] of Object.entries(ozellik)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'metin') { d.textContent = String(v); continue; }
    if (k === 'sinif') { d.className = String(v); continue; }
    if (k === 'stil') { d.setAttribute('style', String(v)); continue; }
    if (k === 'veri') {
      for (const [dk, dv] of Object.entries(v)) {
        if (dv !== null && dv !== undefined) d.dataset[dk] = String(dv);
      }
      continue;
    }
    if (k.startsWith('on') && typeof v === 'function') {
      d.addEventListener(k.slice(2), v);
      continue;
    }
    if (v === true) { d.setAttribute(k, ''); continue; }
    d.setAttribute(k, String(v));
  }
  for (const c of [].concat(cocuklar)) {
    if (c === null || c === undefined || c === false) continue;
    d.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return d;
}

export function temizle(kok) {
  while (kok.firstChild) kok.removeChild(kok.firstChild);
  return kok;
}

export function doldur(kok, cocuklar) {
  temizle(kok);
  for (const c of [].concat(cocuklar)) {
    if (c === null || c === undefined || c === false) continue;
    kok.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return kok;
}

export const $ = (secici, kok = document) => kok.querySelector(secici);

// Yeniden çizim sırasında kaydırma konumunu korur.
//
// Ekranlar her durum değişiminde baştan kuruluyor. `doldur()` kabı
// boşaltınca tarayıcı scrollTop'u sıfırlıyor ve içerik geri gelince o
// sıfır kalıyordu: 5 saniyelik hafif yenileme uzun listeyi her turda
// başa atıyordu. Konumu önce alıp sonra geri koyuyoruz.
export function kaydirmayiKoru(dis, ciz) {
  const disUst = dis ? dis.scrollTop : 0;
  const icler = dis
    ? [...dis.querySelectorAll('.tablo-sar')].map(
      e => [e.scrollLeft, e.scrollTop])
    : [];

  ciz();

  if (!dis) return;
  // Yerleşim yeni içerikle oturduktan sonra geri koy.
  const uygula = () => {
    if (disUst && dis.scrollHeight > dis.clientHeight) dis.scrollTop = disUst;
    const yeniler = dis.querySelectorAll('.tablo-sar');
    for (let i = 0; i < yeniler.length && i < icler.length; i += 1) {
      const [sol, ust] = icler[i];
      if (sol) yeniler[i].scrollLeft = sol;
      if (ust) yeniler[i].scrollTop = ust;
    }
  };
  uygula();
  requestAnimationFrame(uygula);
}

// SVG öğeleri ayrı bir ad alanında yaşıyor: createElement('svg') geçerli
// bir SVG üretmez, sayfada görünmez. Bu yüzden el() değil bu iki yardımcı.
const SVG_NS = 'http://www.w3.org/2000/svg';

export function svg(nitelik = {}, cocuklar = []) {
  const s = document.createElementNS(SVG_NS, 'svg');
  const varsayilan = {
    viewBox: '0 0 20 20', width: '15', height: '15',
    'aria-hidden': 'true', ...nitelik,
  };
  for (const [k, v] of Object.entries(varsayilan)) {
    if (v !== null && v !== undefined) s.setAttribute(k, String(v));
  }
  for (const [etiket, ozellik] of cocuklar) {
    const c = document.createElementNS(SVG_NS, etiket);
    for (const [k, v] of Object.entries(ozellik || {})) {
      if (v !== null && v !== undefined) c.setAttribute(k, String(v));
    }
    s.append(c);
  }
  return s;
}

// Çizgisel ikon — yol verileri sabittir, dışarıdan gelmez.
export function ikon(yollar, boyut = 15) {
  return svg({
    width: boyut, height: boyut, fill: 'none', stroke: 'currentColor',
    'stroke-width': '1.5', 'stroke-linecap': 'round',
  }, [].concat(yollar).map(d => ['path', { d }]));
}

// Odak tuzağı — diyalog açıkken Tab pencerenin dışına çıkmasın.
export function odakTuzagi(kap, kapat) {
  const secici = 'button, input, select, textarea, a[href], [tabindex]:not([tabindex="-1"])';
  function tus(e) {
    if (e.key === 'Escape') { e.preventDefault(); kapat(); return; }
    if (e.key !== 'Tab') return;
    const odaklanabilir = [...kap.querySelectorAll(secici)]
      .filter(x => !x.disabled && x.offsetParent !== null);
    if (!odaklanabilir.length) return;
    const ilk = odaklanabilir[0];
    const son = odaklanabilir[odaklanabilir.length - 1];
    if (e.shiftKey && document.activeElement === ilk) { e.preventDefault(); son.focus(); }
    else if (!e.shiftKey && document.activeElement === son) { e.preventDefault(); ilk.focus(); }
  }
  kap.addEventListener('keydown', tus);
  return () => kap.removeEventListener('keydown', tus);
}

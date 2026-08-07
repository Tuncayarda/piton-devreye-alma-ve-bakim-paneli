// PISCU & Asterisk PBX ekranı.
//
// SIP tablosu, PBX'e sorularak değil cihazların kendi bildirdiği
// değerlerden kurulur (ARI hesabı tanımlı değil). Bu, ekranda açıkça
// yazılır — "kayıtlı" gibi görünüp aslında doğrulanmamış bir bilgi
// göstermek sahte veridir.

import { el, doldur } from '../core/dom.js';
import { api } from '../core/api.js';
import { durum, ata } from '../core/durum.js';
import { deger, DURUM_ETIKET } from '../core/bicim.js';

export async function tazele() {
  try {
    ata({ piscuDurum: await api.piscu(durum.setNo) });
  } catch {
    ata({ piscuDurum: null });
  }
}

export function ciz(kok) {
  const v = durum.piscuDurum;
  const parcalar = [];

  parcalar.push(el('div', { sinif: 'sayfa-basi' }, [
    el('div', {}, [el('h2', { metin: 'PISCU & Asterisk PBX' })]),
    el('div', { sinif: 'eylemler' }, [
      el('button', { type: 'button', sinif: 'btn', metin: 'Yenile', onclick: tazele }),
    ]),
  ]));

  if (!v) {
    parcalar.push(el('p', { sinif: 'uyari', metin: 'PISCU bilgileri alınamadı' }));
    doldur(kok, parcalar);
    return;
  }

  parcalar.push(el('p', { sinif: 'bilgi', metin: v.not }));

  const kart = (baslik, satirlar, bosMetin) => el('div', { sinif: 'kart kose' }, [
    el('h3', { stil: 'margin-bottom:12px', metin: baslik }),
    ...(satirlar.length ? satirlar
      : [el('div', { sinif: 'mono soluk', stil: 'font-size:11px', metin: bosMetin })]),
  ]);

  const istemciler = v.istemciler.map(c => el('div', {
    stil: 'display:grid;grid-template-columns:minmax(0,1fr) 104px 96px;gap:10px;'
      + 'padding:7px 0;border-bottom:1px solid var(--cizgi-hafif);'
      + 'font-family:var(--f-mono);font-size:11px',
  }, [
    el('span', { sinif: 'kirp', metin: c.ad }),
    el('span', { sinif: 'orta', metin: c.ip }),
    el('span', {
      veri: { durum: c.durum }, stil: 'color:var(--durum-renk)',
      title: c.aciklama || '',
      metin: c.surum ? `v${c.surum}` : (DURUM_ETIKET[c.durum] || ''),
    }),
  ]));

  const sipler = v.sipler.map(s => el('div', {
    stil: 'display:grid;grid-template-columns:64px minmax(0,1fr) 96px 96px;gap:10px;'
      + 'padding:7px 0;border-bottom:1px solid var(--cizgi-hafif);'
      + 'font-family:var(--f-mono);font-size:11px',
  }, [
    el('span', { stil: 'color:var(--accent)', metin: s.no }),
    el('span', { sinif: 'kirp', metin: s.ad }),
    el('span', { sinif: 'orta', metin: deger(s.cihazinBildirdigi) }),
    el('span', {
      veri: { durum: s.durum }, stil: 'color:var(--durum-renk)',
      metin: DURUM_ETIKET[s.durum] || '',
    }),
  ]));

  parcalar.push(el('div', { sinif: 'genel-izgara' }, [
    kart('MQTT / Uygulama İstemcileri', istemciler,
      'PISCU ve HMI okunmadı'),
    kart('SIP Dahili Numaraları', [
      el('div', {
        sinif: 'etiket',
        stil: 'display:grid;grid-template-columns:64px minmax(0,1fr) 96px 96px;'
          + 'gap:10px;padding-bottom:6px',
      }, [
        el('span', { metin: 'Beklenen' }),
        el('span', { metin: 'Cihaz' }),
        el('span', { metin: 'Bildirilen' }),
        el('span', { metin: 'Durum' }),
      ]),
      ...sipler,
    ], 'SIP tanımlı cihaz yok'),
  ]));

  doldur(kok, parcalar);
}

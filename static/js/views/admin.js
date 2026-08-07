// Proje & Cihaz Listesi (admin).
//
// Bu ekranda cihaz kullanıcı adı/parolası KAYDEDİLEMEZ. Eski panellerdeki
// "kimlik bilgilerini dosyaya kaydet" / "parola kayıtlı" alanları
// bilinçli olarak yoktur; tek yapılabilen, bellekteki kimlikleri unutmaktır.

import { el, doldur } from '../core/dom.js';
import { api } from '../core/api.js';
import { durum } from '../core/durum.js';
import { basari, hata } from '../parts/bildirim.js';
import { deger } from '../core/bicim.js';

const KOLON = 'minmax(140px,1.3fr) minmax(120px,1fr) 76px 110px 96px';

// Set numarası sahada sabit bir listeden gelmiyor (49, 112 gibi numaralar
// da var); hazır düğme ızgarası yerine elle yazılan bir alan duruyor.
// Aralığı sunucu bildirir, çünkü doğrulamayı da o yapıyor.
function setKutusu(meta, setDegis) {
  const min = meta.setMin || 1;
  const max = meta.setMax || 254;

  const alan = el('input', {
    sinif: 'alan', type: 'number', inputmode: 'numeric',
    min: String(min), max: String(max), step: '1',
    autocomplete: 'off', stil: 'width:90px;text-align:center',
    value: String(durum.setNo), 'aria-label': 'Tren seti numarası',
  });

  const uygula = () => {
    const n = Number(alan.value.trim());
    if (!Number.isInteger(n) || n < min || n > max) {
      hata(`Set numarası ${min} ile ${max} arasında olmalı`);
      alan.value = String(durum.setNo);
      return;
    }
    if (n !== durum.setNo) setDegis(n);
  };
  alan.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); uygula(); }
  });

  return el('div', { stil: 'margin-top:12px' }, [
    el('div', { stil: 'display:flex;align-items:center;gap:8px' }, [
      alan,
      el('button', {
        type: 'button', sinif: 'btn', metin: 'Uygula', onclick: uygula,
      }),
    ]),
    el('p', {
      sinif: 'mono soluk',
      stil: 'margin-top:9px;font-size:10.5px;line-height:1.6',
      metin: `Geçerli aralık ${min}–${max}. Cihaz adresleri 10.n.1.x `
        + 'biçiminde çözülür.',
    }),
  ]);
}

export function ciz(kok, setDegis) {
  const meta = durum.meta;
  if (!meta) return;
  const parcalar = [];

  parcalar.push(el('div', { sinif: 'sayfa-basi' }, [
    el('div', {}, [el('h2', { metin: 'Proje & Cihaz Listesi' })]),
  ]));

  parcalar.push(el('div', { sinif: 'proje-izgara' }, [
    el('div', { sinif: 'kart kose' }, [
      el('div', { stil: 'display:flex;align-items:center;gap:9px' }, [
        el('span', { sinif: 'nokta', stil: 'background:var(--yesil)', 'aria-hidden': 'true' }),
        el('span', {
          stil: 'font-family:var(--f-baslik);font-weight:600;font-size:18px;'
            + 'letter-spacing:.06em;text-transform:uppercase',
          metin: meta.proje,
        }),
        el('span', { stil: 'margin-left:auto' , sinif: 'etiket', metin: 'Yüklü' }),
      ]),
      el('div', {
        sinif: 'mono orta',
        stil: 'margin-top:9px;font-size:10.5px;line-height:1.7',
      }, [
        el('div', { metin: meta.dosya }),
        el('div', { metin: `PISCU / broker: ${deger(meta.piscuIp)}` }),
      ]),
    ]),
    el('div', { sinif: 'kart kose' }, [
      el('h4', { metin: 'Kimlik Bilgileri' }),
      el('p', {
        sinif: 'mono orta',
        stil: 'margin-top:9px;font-size:10.5px;line-height:1.7',
        metin: 'Cihaz kullanıcı adı ve parolaları yalnızca bu uygulama '
          + 'açık kaldığı sürece bellekte tutulur. Dosyaya, .env\'e ya da '
          + 'tarayıcı deposuna hiçbir koşulda yazılmaz.',
      }),
      el('button', {
        type: 'button', sinif: 'btn btn-tehlike', stil: 'margin-top:12px',
        metin: 'Bellekteki Kimlikleri Unut',
        onclick: async () => {
          try {
            await api.kimlikHepsiniUnut();
            basari('Bellekteki bütün kimlikler unutuldu');
          } catch (e) { hata(e.message); }
        },
      }),
    ]),
    el('div', { sinif: 'kart kose' }, [
      el('h4', { metin: 'Tren Seti (n)' }),
      setKutusu(meta, setDegis),
    ]),
  ]));

  parcalar.push(el('div', { sinif: 'admin-izgara' }, [
    el('div', { sinif: 'kart' }, [
      el('div', { sinif: 'kart-basi' }, [
        el('h4', { metin: 'Cihaz–Port Eşleme' }),
        el('span', { sinif: 'etiket', metin: 'switch / port / IP şablonu' }),
      ]),
      el('div', { sinif: 'tablo-sar', stil: 'margin-top:0' }, [
        el('div', { sinif: 'tablo', stil: '--tablo-min:600px' }, [
          el('div', { sinif: 'tablo-basi', stil: `--tablo-kolon:${KOLON}` },
            ['Name', 'Type / SubType', 'Port', 'IP Şablonu', 'PBXExtension']
              .map(b => el('span', { metin: b }))),
          ...durum.cihazlar.map(c => el('div', {
            sinif: 'tablo-satir', stil: `--tablo-kolon:${KOLON}`,
          }, [
            el('span', { sinif: 'mono kirp', stil: 'font-size:11px', metin: c.ad }),
            el('span', { sinif: 'mono acik kirp', stil: 'font-size:11px', metin: c.tipEtiket }),
            el('span', {
              sinif: 'mono', stil: 'font-size:11px;color:var(--turuncu)',
              metin: c.port || '—',
            }),
            el('span', { sinif: 'mono orta', stil: 'font-size:11px', metin: c.ipSablonu }),
            el('span', {
              sinif: 'mono', stil: 'font-size:11px;color:var(--accent)',
              metin: c.pbxExtension || '—',
            }),
          ])),
        ]),
      ]),
    ]),

    el('div', { sinif: 'kart' }, [
      el('h4', { metin: 'Kategori Tanımı' }),
      el('div', { stil: 'margin-top:11px' }, meta.kategoriler.map(k => el('div', {
        stil: 'display:flex;gap:10px;padding:6px 0;'
          + 'border-bottom:1px solid var(--cizgi-hafif);'
          + 'font-family:var(--f-mono);font-size:11px',
      }, [
        el('span', { stil: 'width:82px;flex:none', metin: k.kod }),
        el('span', { sinif: 'orta', stil: 'flex:1', metin: k.tipler }),
      ]))),
    ]),
  ]));

  doldur(kok, parcalar);
}

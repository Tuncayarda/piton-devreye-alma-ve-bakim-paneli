// Otomatik IP atama ekranı.
//
// Plan sunucudan gelir (DeviceMap'ten çıkarılır); tarayıcı kendi başına
// bir hedef üretmez. Koşu varsayılan olarak DRY-RUN'dır: ağa yazmaz.
//
// Ön panel, switch'in gerçek yüzünü çizer: PoE portları sütun sütun
// aşağıdan yukarı (1-2-3-4 | 5-6-7-8 …), sağda kesik çizgiyle ayrılmış
// uplink sütunu. Dizilim kardeş projedeki Switch Yönetim Paneli ile
// aynıdır; iki panelde aynı switch'e bakan kişi aynı yerleşimi görür.
//
// Projede birden çok switch varsa hepsinin paneli alt alta çizilir. Koşu
// tek switch üzerinde yürüdüğü için bir tanesi "etkin"dir; başka bir
// switch'in portuna tıklamak koşuyu o switch'e taşır.

import { el, doldur } from '../core/dom.js';
import { api } from '../core/api.js';
import { durum, ata } from '../core/durum.js';
import * as serit from '../parts/serit.js';
import { hata, basari, bildir } from '../parts/bildirim.js';
import { deger } from '../core/bicim.js';

const KOLON = '70px minmax(160px,1.3fr) 118px 118px minmax(180px,1fr)';

const yerel = {
  portMetni: null,         // null = plandaki varsayılan (grubun portları)
  pcPort: '24',
  dryRun: true,
  switchId: null,          // null = planın kendi seçtiği switch
  hataMetni: '',
};

// ── port metni: "11-14, 18-19, 21" ──
// Sunucudaki ip_atama.metin_yap / portlar_ayristir ile aynı biçim. Metin
// burada da üretilip burada da çözülüyor, çünkü kullanıcı yazarken her
// tuşta sunucuya gitmek (ve hatalı metinde ekranı boşaltmak) doğru değil.
export function metinYap(portlar) {
  const p = [...new Set(portlar.map(Number))]
    .filter(Number.isInteger).sort((a, b) => a - b);
  if (!p.length) return '';
  const parca = [];
  let bas = p[0];
  let on = p[0];
  for (let i = 1; i <= p.length; i += 1) {
    const simdi = i < p.length ? p[i] : null;
    if (simdi === on + 1) { on = simdi; continue; }
    parca.push(bas === on ? String(bas) : `${bas}-${on}`);
    bas = simdi; on = simdi;
  }
  return parca.join(', ');
}

export function portlariAyristir(metin, izinli) {
  const cikan = [];
  for (const ham of String(metin || '').replace(/[;\s]+/g, ',').split(',')) {
    const parca = ham.trim();
    if (!parca) continue;
    if (parca.includes('-')) {
      const [a, b] = parca.split('-');
      const bas = Number(a);
      const son = Number(b);
      if (!Number.isInteger(bas) || !Number.isInteger(son) || son < bas
          || bas < 1 || a === '' || b === '') {
        return { portlar: [], hata: `Geçersiz port aralığı: ${parca}` };
      }
      for (let n = bas; n <= son; n += 1) cikan.push(n);
    } else {
      const n = Number(parca);
      if (!Number.isInteger(n) || n < 1) {
        return { portlar: [], hata: `Geçersiz port: ${parca}` };
      }
      cikan.push(n);
    }
  }
  if (izinli && izinli.length) {
    const küme = new Set(izinli);
    const disarida = [...new Set(cikan)].filter(n => !küme.has(n))
      .sort((a, b) => a - b);
    if (disarida.length) {
      return {
        portlar: [],
        hata: `Bu switch'te cihaz tanımlı olmayan port: ${disarida.join(', ')}`,
      };
    }
  }
  return { portlar: [...new Set(cikan)].sort((a, b) => a - b), hata: '' };
}

export async function tazele() {
  const g = serit.gecerliGrup('ip');
  try {
    const plan = await api.ipPlan(
      durum.setNo, g ? g.ad : '', yerel.portMetni || '', yerel.switchId || '');
    // Her switch'in paneli ayrı uçtan gelir; biri okunamazsa (kimlik yok,
    // ulaşılamıyor) diğerleri yine çizilir.
    const paneller = await Promise.all(
      (plan.switchler || []).map(s => api.ipPanel(durum.setNo, s.id)
        .catch(() => null)));
    yerel.hataMetni = '';
    ata({ ipDurum: { plan, paneller: paneller.filter(Boolean) } });
  } catch (e) {
    yerel.hataMetni = e.message;
    ata({ ipDurum: null });
  }
}

export function ciz(kok) {
  const veri = durum.ipDurum;
  const parcalar = [];

  parcalar.push(el('div', { sinif: 'sayfa-basi' }, [
    el('div', {}, [el('h2', { metin: 'Otomatik IP Atama' })]),
    el('div', { sinif: 'eylemler' }, [
      el('button', {
        type: 'button',
        sinif: yerel.dryRun ? 'btn' : 'btn btn-birincil',
        metin: yerel.dryRun ? 'Kuru Koşuyu Başlat' : 'Koşuyu Başlat',
        disabled: !veri,
        onclick: baslat,
      }),
    ]),
  ]));

  // Grup değişince seçim de sıfırlanır: önceki grubun portları yeni grupta
  // anlamsız, hatta başka bir switch'e ait olabilir.
  parcalar.push(serit.ciz('ip', () => {
    yerel.portMetni = null;
    yerel.switchId = null;
    tazele();
  }));

  if (!veri) {
    parcalar.push(el('p', {
      sinif: 'uyari', stil: 'margin-top:16px',
      metin: yerel.hataMetni || 'Plan yüklenemedi',
    }));
    doldur(kok, parcalar);
    return;
  }

  const { plan, paneller } = veri;
  const izinli = plan.izinliPortlar || [];
  const seciliMetin = yerel.portMetni ?? metinYap(
    plan.satirlar.filter(s => s.uygulanabilir).map(s => s.port));

  // ── sol sütun: koşu ayarları ──
  const portUyari = el('p', {
    id: 'port-uyari', sinif: 'uyari', stil: 'margin-top:7px',
    role: 'alert', hidden: true,
  });
  const portGiris = el('input', {
    sinif: 'alan', value: seciliMetin,
    'aria-invalid': 'false', 'aria-describedby': 'port-uyari',
    placeholder: '11-14, 18-19, 21',
    // Yazarken yalnız uyarı gösterilir; ekran yeniden çizilmez, yoksa
    // her tuşta odak alandan çıkardı.
    oninput: (e) => {
      const { hata: h } = portlariAyristir(e.target.value, izinli);
      e.target.setAttribute('aria-invalid', String(!!h));
      portUyari.textContent = h;
      portUyari.hidden = !h;
    },
    onchange: (e) => {
      const { portlar, hata: h } = portlariAyristir(e.target.value, izinli);
      if (h) return;                       // hatalı metinle plan istenmez
      yerel.portMetni = metinYap(portlar);
      tazele();
    },
  });

  const ayarKart = el('div', { sinif: 'kart kose' }, [
    el('h3', { stil: 'margin-bottom:14px', metin: 'Koşu Ayarları' }),
    el('label', { stil: 'display:block;margin-bottom:4px' }, [
      el('span', { sinif: 'etiket', metin: 'Portlar' }),
      portGiris,
    ]),
    portUyari,
    el('p', {
      sinif: 'mono soluk',
      stil: 'margin:6px 0 12px;font-size:10px;line-height:1.5',
      metin: 'Aralık ve tek port birlikte yazılabilir: 11-14, 18-19, 21',
    }),
    el('label', { stil: 'display:block;margin-bottom:12px' }, [
      el('span', { sinif: 'etiket', metin: 'Bilgisayarın bağlı olduğu port' }),
      el('input', {
        sinif: 'alan', value: yerel.pcPort, inputmode: 'numeric',
        onchange: (e) => {
          yerel.pcPort = e.target.value.trim();
          ata({ ipDurum: { ...veri } });   // panelde turuncu port yer değiştirir
        },
      }),
    ]),
    el('button', {
      type: 'button', sinif: 'onay', 'aria-pressed': String(yerel.dryRun),
      onclick: (e) => {
        yerel.dryRun = !yerel.dryRun;
        e.currentTarget.setAttribute('aria-pressed', String(yerel.dryRun));
        ata({ ipDurum: { ...veri } });
      },
    }, [
      el('span', { sinif: 'kutu', 'aria-hidden': 'true' }),
      el('span', { metin: 'Dry-run (ağa yazma)' }),
    ]),
    el('div', {
      stil: 'margin-top:14px;padding-top:12px;border-top:1px solid var(--cizgi);'
        + 'font-family:var(--f-mono);font-size:10.5px;color:var(--orta);line-height:1.7',
    }, [
      el('div', { metin: `Switch: ${deger(plan.switch)} · ${deger(plan.switchIp)}` }),
      el('div', { metin: `Hedef: ${plan.hedefSayi} cihaz` }),
      el('div', { metin: `Portlar: ${plan.portMetni}` }),
    ]),
  ]);

  // ── sağ sütun: switch başına bir ön panel ──
  const panelYigin = el('div', { sinif: 'panel-yigin' },
    (paneller.length ? paneller : []).map(p => panelKarti(p, plan)));

  parcalar.push(el('div', { sinif: 'ip-izgara' }, [ayarKart, panelYigin]));

  // ── altta plan tablosu ──
  parcalar.push(el('div', { sinif: 'tablo-sar', stil: 'margin-top:18px' }, [
    el('div', { sinif: 'tablo', stil: '--tablo-min:720px' }, [
      el('div', { sinif: 'tablo-basi', stil: `--tablo-kolon:${KOLON}` },
        ['Port', 'Hedef Cihaz', 'Fabrika IP', 'Atanacak IP', 'Durum']
          .map(b => el('span', { metin: b }))),
      ...(plan.satirlar.length
        ? plan.satirlar.map(p => el('div', {
            sinif: 'tablo-satir', stil: `--tablo-kolon:${KOLON}`
              + (p.uygulanabilir ? '' : ';opacity:.45'),
          }, [
            el('span', { sinif: 'mono', stil: 'font-size:11.5px', metin: `p${p.port}` }),
            el('span', { sinif: 'mono kirp', stil: 'font-size:12px', metin: p.ad }),
            el('span', { sinif: 'mono orta', stil: 'font-size:11.5px', metin: p.fabrika }),
            el('span', {
              sinif: 'mono', stil: 'font-size:11.5px;color:var(--accent)',
              metin: p.hedefIp,
            }),
            el('span', {
              sinif: 'orta', stil: 'font-size:11.5px',
              metin: p.uygulanabilir
                ? 'Plana dahil'
                : 'Bu portta hedef gruptan cihaz tanımlı değil',
            }),
          ]))
        : [el('div', { sinif: 'tablo-bos', metin: 'Seçili portlarda hedef cihaz yok' })]),
    ]),
  ]));

  doldur(kok, parcalar);
}

// ── ön panel ────────────────────────────────────────────────────────────
// Konnektör çizimi kardeş projedeki (Switch Yönetim Paneli) biçimin
// aynısı: PoE portu 4 pinli, uplink 8 pinli ve ortasında çarpı. Aynı
// switch'e bakan iki panelde port kutusunun aynı görünmesi, hangi porta
// baktığını saymadan bulmayı sağlıyor.
function pinHalka(n, r) {
  return Array.from({ length: n }, (_, i) => {
    const a = (i / n) * Math.PI * 2 - Math.PI / 2;
    return [20 + r * Math.cos(a), 20 + r * Math.sin(a)];
  });
}

function konnektorSvg(poe) {
  const pinler = pinHalka(poe ? 4 : 8, poe ? 6.6 : 7.2);
  const r = poe ? 2.5 : 1.9;
  const ns = 'http://www.w3.org/2000/svg';
  const s = document.createElementNS(ns, 'svg');
  s.setAttribute('viewBox', '0 0 40 40');
  s.setAttribute('aria-hidden', 'true');
  const ekle = (etiket, ozellik) => {
    const c = document.createElementNS(ns, etiket);
    for (const [k, v] of Object.entries(ozellik)) c.setAttribute(k, String(v));
    s.append(c);
  };
  ekle('circle', { class: 'shell', cx: 20, cy: 20, r: 18.4 });
  ekle('circle', { class: 'inner', cx: 20, cy: 20, r: 12.2 });
  if (!poe) ekle('path', { class: 'cross', d: 'M13 13 L27 27 M27 13 L13 27' });
  ekle('rect', { class: 'key', x: 18.6, y: 1.6, width: 2.8, height: 4.2 });
  for (const [x, y] of pinler) {
    ekle('circle', { class: 'pin', cx: x.toFixed(2), cy: y.toFixed(2), r });
  }
  return s;
}

function bosHucre(sinif) {
  return el('div', { sinif: sinif || 'pm-bos' });
}

// Tek konnektör. Durum sırası önemli: bilgisayar portu her şeyin üstünde
// görünür, çünkü o portu seçmek koşunun kendi bağlantısını kesmesi demek.
function portDugmesi(p, ctx) {
  const roller = [];
  if (p.no === ctx.pcPort) roller.push('pc');
  else if (ctx.hedef.has(p.no)) roller.push('sec');
  if (!p.tanimli) roller.push('bos');
  if (p.acik === false) roller.push('kapali');

  const durumMetni = p.acik === null ? '' : p.acik ? ' · açık' : ' · kapalı';
  return el('button', {
    type: 'button', sinif: `pm-port ${roller.join(' ')}`.trim(),
    'aria-pressed': String(ctx.hedef.has(p.no)),
    disabled: !p.tanimli,
    title: (p.tanimli
      ? `Port ${p.no} · ${p.cihaz}${durumMetni}`
      : `Port ${p.no} · cihaz tanımlı değil`)
      + (ctx.aktif ? '' : ` · ${ctx.switchAd} switch'ine geçer`),
    onclick: () => portTikla(p.no, ctx),
  }, [
    konnektorSvg(p.poe),
    el('span', { metin: String(p.no) }),
  ]);
}

function panelKarti(panel, plan) {
  const aktif = panel.switchId === plan.switchId;
  const bilgi = (plan.switchler || []).find(s => s.id === panel.switchId);
  const grupCihaz = bilgi ? bilgi.grupCihaz : null;
  const hedef = new Set(
    aktif ? plan.satirlar.filter(s => s.uygulanabilir).map(s => s.port) : []);
  const ctx = {
    hedef,
    aktif,
    switchId: panel.switchId,
    switchAd: panel.switchAd,
    pcPort: aktif ? Number(yerel.pcPort) : null,
  };

  const idIle = {};
  for (const p of panel.portlar) idIle[p.no] = p;
  const poeN = panel.poeSayisi || 24;
  const uplinkN = panel.uplinkSayisi || 4;
  const sutun = Math.max(1, Math.ceil(poeN / 4));

  const izgara = el('div', {
    sinif: 'pm-izgara',
    stil: `--pm-sutun:${sutun}`,
  });
  // Fiziksel yerleşim: 4 satır, PoE sütunları aşağıdan yukarı numaralı,
  // en sağda uplink sütunu (yukarıdan aşağı).
  for (let satir = 4; satir >= 1; satir -= 1) {
    for (let c = 0; c < sutun; c += 1) {
      const p = idIle[satir + c * 4];
      izgara.append(p ? portDugmesi(p, ctx) : bosHucre());
    }
    izgara.append(bosHucre('pm-ayrac'));
    // Uplink sütunu yukarıdan aşağı numaralanır (28…25) — kardeş paneldeki
    // dizilimin aynısı.
    const u = satir <= uplinkN ? idIle[poeN + satir] : null;
    izgara.append(u ? portDugmesi(u, ctx) : bosHucre());
  }

  return el('div', {
    sinif: 'kart kose on-panel', veri: { aktif: aktif ? '1' : '0' },
  }, [
    el('div', { sinif: 'kart-basi', stil: 'margin-bottom:10px' }, [
      el('h4', { metin: panel.switchAd || 'Switch' }),
      el('span', { sinif: 'mono soluk', stil: 'font-size:10.5px', metin: panel.switchIp }),
      el('span', { stil: 'flex:1' }),
      aktif
        ? el('span', { sinif: 'rozet', metin: 'Koşu bu switch\'te' })
        : el('span', {
            sinif: 'etiket',
            metin: grupCihaz === 0
              ? 'Bu gruptan cihaz yok' : 'Porta tıkla, koşu buraya geçsin',
          }),
      el('span', {
        sinif: 'etiket',
        metin: panel.kaynak === 'switch' ? 'Canlı' : 'DeviceMap',
      }),
    ]),
    panel.not
      ? el('p', { sinif: 'bilgi', stil: 'margin-bottom:10px', metin: panel.not })
      : null,
    el('div', { sinif: 'pm-sar' }, [izgara]),
    el('div', { sinif: 'pm-alt' }, [
      el('span', { metin: `PoE 1-${poeN}` }),
      el('span', { stil: 'flex:1' }),
      el('span', { metin: `Uplink ${poeN + 1}-${poeN + uplinkN}` }),
    ]),
    el('div', { sinif: 'panel-lejant' }, [
      el('span', {}, [el('i', { sinif: 'pm-ornek sec' }), 'Hedef port']),
      el('span', {}, [el('i', { sinif: 'pm-ornek pc' }), 'Bilgisayar portu']),
      el('span', {}, [el('i', { sinif: 'pm-ornek' }), 'Cihaz tanımlı']),
      el('span', {}, [el('i', { sinif: 'pm-ornek bos' }), 'Cihaz tanımlı değil']),
    ]),
  ]);
}

function portTikla(no, ctx) {
  const plan = durum.ipDurum && durum.ipDurum.plan;
  if (!plan) return;
  // Başka switch'in portuna tıklamak koşuyu o switch'e taşır; oradaki
  // seçim de o portla başlar.
  if (!ctx.aktif) {
    yerel.switchId = ctx.switchId;
    yerel.portMetni = String(no);
    tazele();
    return;
  }
  const mevcut = new Set(plan.satirlar.filter(s => s.uygulanabilir).map(s => s.port));
  if (mevcut.has(no)) mevcut.delete(no); else mevcut.add(no);
  yerel.portMetni = metinYap([...mevcut]);
  tazele();
}

async function baslat() {
  const plan = durum.ipDurum && durum.ipDurum.plan;
  if (!plan) return;
  try {
    const y = await api.ipKosu({
      set: durum.setNo,
      switch: plan.switchId,
      portlar: yerel.portMetni ?? plan.portMetni,
      dryRun: yerel.dryRun,
      pcPort: yerel.pcPort,
    });
    ata({ kuyrukAcik: true, acikIs: y.id });
    if (y.yeni === false) bildir('Bu switch için zaten bir koşu var');
    else basari(yerel.dryRun ? 'Kuru koşu kuyruğa alındı' : 'Koşu kuyruğa alındı');
  } catch (e) {
    hata(e.message);
  }
}

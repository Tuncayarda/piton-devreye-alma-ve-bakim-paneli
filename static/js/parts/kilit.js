// Kilit menüsü: kullanıcı adı/parola bekleyen cihazlar ve kimlik diyaloğu.
//
// Parola hiçbir zaman uygulama durumuna (durum.js) yazılmaz. Diyalogdaki
// input değeri doğrudan API çağrısına verilir; yanıt döner dönmez —
// başarılı da olsa başarısız da olsa — alan temizlenir.
//
// Doğrulama kararını sunucu verir: form doldurulmuş olması yetmez, cihaz
// gerçekten beklenen veriyi döndürmelidir.

import { el, doldur, $ } from '../core/dom.js';
import { api } from '../core/api.js';
import { durum, ata } from '../core/durum.js';
import { deger } from '../core/bicim.js';
import * as diyalog from './diyalog.js';
import { bildir, basari } from './bildirim.js';

let yenile = () => {};

export function baglaYenile(fn) { yenile = fn; }

// Kuyruk panelindeki ile aynı gerekçe: liste ancak değiştiğinde kurulur.
let sonImza = null;

export function ciz() {
  const liste = $('#kilit-liste');
  if (!liste) return;
  const kilit = durum.kilit || [];

  const sayac = $('#kilit-sayac');
  if (sayac) {
    sayac.textContent = String(kilit.length);
    sayac.hidden = kilit.length === 0;
  }
  const btn = $('#kilit-btn');
  if (btn) btn.setAttribute('aria-expanded', String(!!durum.kilitAcik));
  $('#kilit-panel').hidden = !durum.kilitAcik;
  if (!durum.kilitAcik) { sonImza = null; return; }

  const imza = JSON.stringify(kilit);
  if (imza === sonImza) return;
  sonImza = imza;

  doldur(liste, kilit.map(c => el('button', {
    type: 'button', sinif: 'kilit-satir',
    onclick: () => kimlikDiyalogu(c),
  }, [
    el('span', { sinif: 'ad', metin: c.ad }),
    el('span', { sinif: 'rozet', metin: yontemKodu(c) }),
    el('span', { sinif: 'alt' }, [
      `${c.ip} · ${c.tipEtiket}`,
      el('br'),
      c.kimlikGrubu ? `Kimlik grubu: ${c.kimlikGrubu}` : 'Cihaza özel kimlik',
      el('br'),
      aciklamaOf(c),
    ]),
  ])));
}

// Açıklama ve yöntem kodu, cihaz DTO'sunun içindeki okuma sonucundan
// gelir; kilit listesi ayrı bir uçtan beslenmediği için burada çözülür.
function aciklamaOf(c) {
  return (c.sonuc && c.sonuc.aciklama) || c.aciklama || '';
}

function yontemKodu(c) {
  if (c.yontemKod) return c.yontemKod;
  const y = durum.meta && durum.meta.yontemler && durum.meta.yontemler[c.yontem];
  return (y && y.kod) || String(c.yontem || '').toUpperCase();
}

// `bittiginde` doğrulama başarılı olduğunda çağrılır: diyaloğu açan ekran
// kendi verisini tazeleyebilsin (IP atama ekranı switch panelini yeniden
// okur). Verilmezse yalnız genel yenileme çalışır.
export function kimlikDiyalogu(cihaz, bittiginde = null) {
  const kullaniciAlan = el('input', {
    sinif: 'alan', type: 'text', id: 'kimlik-kullanici',
    autocomplete: 'off', autocapitalize: 'off', spellcheck: 'false',
    value: '',
  });
  const parolaAlan = el('input', {
    sinif: 'alan', type: 'password', id: 'kimlik-parola',
    autocomplete: 'new-password',
  });
  const uyariKutu = el('p', { sinif: 'uyari', role: 'alert', hidden: true });

  let grubaUygula = false;
  const grupBtn = cihaz.kimlikGrubu ? el('button', {
    type: 'button', sinif: 'onay', 'aria-pressed': 'false',
    onclick: (e) => {
      grubaUygula = !grubaUygula;
      e.currentTarget.setAttribute('aria-pressed', String(grubaUygula));
    },
  }, [
    el('span', { sinif: 'kutu', 'aria-hidden': 'true' }),
    el('span', {
      metin: `Aynı hesabı "${cihaz.kimlikGrubu}" grubundaki diğer cihazlarda da kullan`,
    }),
  ]) : null;

  const gonder = el('button', {
    type: 'submit', sinif: 'btn btn-birincil', metin: 'Doğrula',
  });

  const form = el('form', {
    onsubmit: async (e) => {
      e.preventDefault();
      uyariKutu.hidden = true;
      gonder.disabled = true;
      gonder.textContent = 'Deneniyor…';

      const kullanici = kullaniciAlan.value.trim();
      const parola = parolaAlan.value;
      try {
        const y = await api.kimlikDene(
          durum.setNo, cihaz.id, kullanici, parola, grubaUygula);
        // Başarılı da olsa alanı bellekte tutmuyoruz.
        parolaAlan.value = '';
        kullaniciAlan.value = '';
        uygulaDurum(y.durum);
        diyalog.kapat();
        basari(`${cihaz.ad} doğrulandı`
          + (y.grubaUygulandi ? ' · hesap gruba uygulandı' : ''));
        yenile();
        if (bittiginde) bittiginde();
      } catch (err) {
        // Yanlış parola bellekteki çalışan kimliği ezmez (sunucu tarafı).
        parolaAlan.value = '';
        uyariKutu.textContent = err.message || 'Doğrulanamadı';
        uyariKutu.hidden = false;
        parolaAlan.focus();
        if (err.govde && err.govde.durum) uygulaDurum(err.govde.durum);
      } finally {
        gonder.disabled = false;
        gonder.textContent = 'Doğrula';
      }
    },
  }, [
    el('p', { sinif: 'aciklama' }, [
      `${cihaz.ip} · ${cihaz.tipEtiket} · ${yontemKodu(cihaz)}`,
      el('br'),
      deger(aciklamaOf(cihaz)),
    ]),
    el('label', { stil: 'display:block;margin-bottom:10px' }, [
      el('span', { sinif: 'etiket', metin: 'Kullanıcı adı' }),
      kullaniciAlan,
    ]),
    el('label', { stil: 'display:block' }, [
      el('span', { sinif: 'etiket', metin: 'Parola' }),
      parolaAlan,
    ]),
    grupBtn ? el('div', { stil: 'margin-top:12px' }, [grupBtn]) : null,
    el('p', {
      sinif: 'bilgi', stil: 'margin-top:12px',
      metin: 'Girilen bilgiler yalnızca bu oturumda bellekte tutulur; '
        + 'hiçbir dosyaya yazılmaz. Uygulama kapanınca unutulur.',
    }),
    uyariKutu,
    el('div', { sinif: 'eylemler', stil: 'margin-top:14px' }, [
      el('button', {
        type: 'button', sinif: 'btn', metin: 'Vazgeç',
        onclick: () => diyalog.kapat(),
      }),
      gonder,
    ]),
  ]);

  diyalog.ac({ baslik: cihaz.ad, icerik: form });
}

// Sunucudan gelen tam durum görüntüsünü uygular (sayaçlar anında güncellenir).
export function uygulaDurum(d) {
  if (!d) return;
  ata({
    cihazlar: d.cihazlar || [],
    sayilar: d.sayilar || durum.sayilar,
    sonTarama: d.sonTarama ?? durum.sonTarama,
    aktifTarama: !!d.aktifTarama,
    kilit: (d.cihazlar || []).filter(
      c => c.sonuc.dogrulama === 'kimlik_bekliyor'),
  });
}

export function kilitAcKapat() {
  ata({ kilitAcik: !durum.kilitAcik, kuyrukAcik: false });
  if (durum.kilitAcik) {
    const ilk = $('#kilit-liste .kilit-satir');
    if (ilk) ilk.focus();
  }
}

export function bilgilendir(mesaj) { bildir(mesaj); }

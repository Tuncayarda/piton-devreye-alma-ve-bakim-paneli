// Biçimlendirme ve etiketleme.
//
// Veri yoksa her yerde aynı işaret kullanılır: —
// "Bu cihazda uygulanmıyor" ile "okunamadı" ayrı metinlerdir; ikisini
// birleştirmek kullanıcıya yanlış bilgi verir.

export const YOK = '—';

export function deger(v) {
  if (v === null || v === undefined || v === '') return YOK;
  return String(v);
}

export const DURUM_ETIKET = {
  yesil: 'Doğrulandı',
  turuncu: 'Erişim bekliyor',
  kirmizi: 'Hata',
  gri: 'Okunmadı',
};

export const DOGRULAMA_ETIKET = {
  dogrulandi: 'Doğrulandı',
  kimlik_bekliyor: 'Kullanıcı adı / parola gerekiyor',
  dogrulanamadi: 'Doğrulanamadı',
  okunmadi: 'Henüz okunmadı',
  uygulanmiyor: 'Bu cihazda uygulanmıyor',
};

export const IS_DURUM_ETIKET = {
  bekliyor: 'Bekliyor',
  calisiyor: 'Çalışıyor',
  tamam: 'Tamamlandı',
  iptal: 'İptal edildi',
  hata: 'Hata',
};

export const SATIR_DURUM_ETIKET = {
  bekliyor: 'Bekliyor',
  calisiyor: 'Çalışıyor',
  // IP atama koşusunda ara durum: cihaza yazıldı, cihaz reset attı ama
  // yeni adresinde cevap verdiği son doğrulama turunda anlaşılıyor.
  // "Tamam" demek yanlış olurdu (bkz. core/ip_atama.YAZILDI).
  yazildi: 'Yazıldı',
  tamam: 'Tamam',
  kimlik: 'Kimlik',
  // Betik çıktısındaki "[!]" satırları: koşu sürüyor ama bir şey ters
  // gitti. Hepsini yeşil "Tamam" göstermek, 200 satırlık çıktıda asıl
  // sebebi görünmez kılıyordu.
  uyari: 'Uyarı',
  hata: 'Hata',
  atlandi: 'Atlandı',
};

export const SATIR_RENK = {
  bekliyor: 'gri',
  calisiyor: 'mavi',
  // Çalışıyorla aynı renk ama nabız atmaz: iş o satırda bitti, teyidi
  // bekliyor. Turuncu kullanılmadı — turuncu bu panelde "bir şey ters
  // gitti" demek ve yazılmış bir port ters giden bir şey değil.
  yazildi: 'mavi',
  // Satır altındaki adımların çoğu ne başarı ne hata: ne yapıldığını
  // anlatan kayıtlar.
  bilgi: 'gri',
  tamam: 'yesil',
  kimlik: 'turuncu',
  uyari: 'turuncu',
  hata: 'kirmizi',
  atlandi: 'gri',
};

export function saat(ts) {
  if (!ts) return YOK;
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString('tr-TR', { hour12: false });
}

export function tazelik(ts) {
  if (!ts) return YOK;
  const fark = Math.max(0, Math.round(Date.now() / 1000 - ts));
  if (fark < 60) return `${fark} sn`;
  if (fark < 3600) return `${Math.floor(fark / 60)} dk`;
  return `${Math.floor(fark / 3600)} sa`;
}

export function yuzde(a, b) {
  if (!b) return '0%';
  return `${Math.round((a / b) * 100)}%`;
}

export function boyut(bayt) {
  if (!bayt) return YOK;
  if (bayt < 1024) return `${bayt} B`;
  if (bayt < 1024 * 1024) return `${(bayt / 1024).toFixed(1)} KB`;
  return `${(bayt / 1024 / 1024).toFixed(2)} MB`;
}

// Cihaz satırında gösterilecek "sürüm" değeri: okunmadıysa boş bırakılır,
// varsayılan bir sürüm uydurulmaz.
export function surumOf(cihaz) {
  const a = cihaz.sonuc && cihaz.sonuc.alanlar;
  return (a && (a.surum || a.model)) || '';
}

export function calismaOf(cihaz) {
  const a = cihaz.sonuc && cihaz.sonuc.alanlar;
  return (a && a.calisma) || '';
}

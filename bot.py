import os
import json
import re
import datetime
import logging
from dotenv import load_dotenv
from pytz import timezone
from datetime import time

import telegram
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# .env dosyasını yükle
load_dotenv()

# --- YAPILANDIRMA AYARLARI ---
try:
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    # --- YETKİLİ KULLANICI DEĞİŞİKLİĞİ BAŞLANGIÇ ---
    # Virgülle ayrılmış ID'leri string olarak al
    YETKILI_KULLANICI_IDS_STR = os.getenv('YETKILI_KULLANICI_IDS')
    if not YETKILI_KULLANICI_IDS_STR:
        raise ValueError("YETKILI_KULLANICI_IDS ortam değişkeni bulunamadı.")
    
    # String listeyi integer listeye çevir
    YETKILI_KULLANICI_IDS = [int(id.strip()) for id in YETKILI_KULLANICI_IDS_STR.split(',') if id.strip()]
    # --- YETKİLİ KULLANICI DEĞİŞİKLİĞİ BİTTİ ---
    
    USER_BOT_ID = int(os.getenv('USER_BOT_ID'))

    if not all([BOT_TOKEN, YETKILI_KULLANICI_IDS, USER_BOT_ID]):
        raise ValueError("Ortam değişkenlerinin hepsi tanımlanmalıdır (BOT_TOKEN, YETKILI_KULLANICI_IDS, USER_BOT_ID).")

except (TypeError, ValueError) as e:
    print(f"HATA: Ortam değişkenleri doğru yüklenemedi. Detay: {e}")
    exit(1) # Hata varsa botu durdur

# --- KULLANICIYA ÖZEL AYARLAR ---
# Gün sonu raporlarının gönderileceği ID
RAPOR_ALICISI_ID = 6672759317 # <<< Burası senin ID'n

# Kalıcı veri dosyası
VERI_DOSYASI = 'bot_data.json'
# Saat Dilimi Ayarı (Türkiye Saati)
TIMEZONE = timezone('Europe/Istanbul')

# Basit bir günlük tutma (logging) ayarı
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Kalıcı Veri Yapısı ---
beklenen_numaralar = {} # Anahtar: hedef_grup_id, Değer: set(numaralar)
sms_raporu = {}         # Anahtar: hedef_grup_id, Değer: {tel_no: count}

def veri_yukle():
    """Kayıtlı verileri dosyadan belleğe yükler."""
    global beklenen_numaralar, sms_raporu
    if os.path.exists(VERI_DOSYASI):
        with open(VERI_DOSYASI, 'r') as f:
            data = json.load(f)
            beklenen_numaralar = {int(k): set(v) for k, v in data.get('beklenen_numaralar', {}).items()}
            sms_raporu = {int(k): v for k, v in data.get('sms_raporu', {}).items()}
    logger.info("Veri başarıyla yüklendi.")

def veri_kaydet():
    """Bellekteki verileri dosyaya kaydeder."""
    data = {
        'beklenen_numaralar': {k: list(v) for k, v in beklenen_numaralar.items()},
        'sms_raporu': sms_raporu
    }
    with open(VERI_DOSYASI, 'w') as f:
        json.dump(data, f, indent=4)
    logger.info("Veri başarıyla kaydedildi.")

# --- Yardımcı Fonksiyonlar ---

def numaralari_ayikla(metin: str) -> set:
    """Metin içindeki alt alta yazılmış 10 haneli telefon numaralarını ayıklar."""
    numaralar = set()
    for satir in metin.split():
        if len(satir) == 10 and satir.isdigit():
            numaralar.add(satir)
    return numaralar

def mesajdan_tel_no_bul(mesaj_metni: str) -> str | None:
    """Mesaj metninden 'Tel No: XXXXXXXXXX' kısmını bulur."""
    eslesme = re.search(r'Tel No:\s*(\d{10})', mesaj_metni) 
    if eslesme:
        return eslesme.group(1)
    return None

def mesajdan_bilgi_al(mesaj_metni: str, anahtar: str) -> str | None:
    """Mesaj metninden belirli bir anahtara ait değeri bulur."""
    eslesme = re.search(rf'{anahtar}:\s*(.*?)(?:\n|$)', mesaj_metni, re.IGNORECASE)
    if eslesme:
        return eslesme.group(1).strip()
    return None

# Yetki kontrol decorator'ı
def yetkili_mi(func):
    """Sadece YETKILI_KULLANICI_IDS listesindekilerin komutları çalıştırmasına izin veren decorator."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        # --- YETKİLİ KULLANICI DEĞİŞİKLİĞİ ---
        if update.effective_user.id not in YETKILI_KULLANICI_IDS:
        # --- Değişiklik Bitti ---
            await update.message.reply_text(
                "❌ Yetkiniz yoktur."
            )
            return
        return await func(update, context)
    return wrapper

# --- Komut İşleyicileri ---

@yetkili_mi
async def ver_komutu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    hedef_grup_id = update.message.chat_id
    argumanlar = update.message.text.split('/ver', 1)[-1].strip()
    yeni_numaralar = numaralari_ayikla(argumanlar)

    if not yeni_numaralar:
        await update.message.reply_text("⚠️ Hata: yanlış komut yazdın.")
        return

    mevcut_numaralar = beklenen_numaralar.get(hedef_grup_id, set())
    mevcut_numaralar.update(yeni_numaralar)
    beklenen_numaralar[hedef_grup_id] = mevcut_numaralar

    veri_kaydet()

    await update.message.reply_text(
        f"✅ {len(yeni_numaralar)} numara bu gruba eklendi. Bu grupta toplamda {len(mevcut_numaralar)} numara aktif."
    )
    logger.info(f"Hedef Grup ID {hedef_grup_id} için {len(yeni_numaralar)} numara eklendi.")


@yetkili_mi
async def sil_komutu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    hedef_grup_id = update.message.chat_id
    argumanlar = update.message.text.split('/sil', 1)[-1].strip()
    silinecek_numaralar = numaralari_ayikla(argumanlar)

    if not silinecek_numaralar:
        await update.message.reply_text("⚠️ Hata: yanlış komut yazdın. Silinecek 10 haneli numaraları alt alta yazın.")
        return

    mevcut_numaralar = beklenen_numaralar.get(hedef_grup_id)
    if not mevcut_numaralar:
        await update.message.reply_text("⚠️ Hata: Bu grupta zaten izlenen kayıtlı numara bulunmuyor.")
        return

    silinen_sayisi = 0
    for numara in silinecek_numaralar:
        if numara in mevcut_numaralar:
            mevcut_numaralar.remove(numara)
            silinen_sayisi += 1

    beklenen_numaralar[hedef_grup_id] = mevcut_numaralar
    veri_kaydet()

    if silinen_sayisi > 0:
        await update.message.reply_text(
            f"✅ {silinen_sayisi} bu gruptan kaldırıldı."
        )
        logger.info(f"Hedef Grup ID {hedef_grup_id} için {silinen_sayisi} numara silindi.")
    else:
        await update.message.reply_text("Belirttiğiniz numaraların hiçbiri bu grupta yoktu.")


@yetkili_mi
async def sil_hepsi_komutu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    hedef_grup_id = update.message.chat_id
    if hedef_grup_id in beklenen_numaralar:
        silinen_sayisi = len(beklenen_numaralar[hedef_grup_id])
        del beklenen_numaralar[hedef_grup_id]
        veri_kaydet()

        await update.message.reply_text(
            f"✅ {silinen_sayisi} numaranın tamamı bu gruptan kaldırıldı."
        )
        logger.info(f"Hedef Grup ID {hedef_grup_id}'deki tüm numaralar silindi.")
    else:
        await update.message.reply_text("Bu grupta zaten kayıtlı numara bulunmuyor.")


@yetkili_mi
async def aktif_komutu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    grup_id = update.message.chat_id
    aktif_numaralar = beklenen_numaralar.get(grup_id)

    if not aktif_numaralar:
        await update.message.reply_text("Bu grupta aktif numara bulunmamaktadır.")
        return 

    mesaj = f"AKTİF NUMARALAR ({len(aktif_numaralar)} numara)\n\n"
    numara_listesi = sorted(list(aktif_numaralar))
    mesaj += '\n'.join([f"• `{numara}`" for numara in numara_listesi])
    mesaj += "\n\nBu numaralara gelen SMS'ler bu gruba yönlendirilir."

    await update.message.reply_text(
        text=mesaj,
        parse_mode=telegram.constants.ParseMode.MARKDOWN
    )
    logger.info(f"Grup ID {grup_id}'ye aktif numaralar listesi gönderildi.")


@yetkili_mi
async def rapor_komutu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    grup_id = update.message.chat_id
    rapor_data = sms_raporu.get(grup_id)

    if not rapor_data:
        await update.message.reply_text("Bu grupta henüz SMS kaydı bulunmamaktadır.")
        return

    mesaj = "ANLIK SMS DURUM RAPORU \n\n"
    toplam_sms = 0

    for tel_no, count in sorted(rapor_data.items(), key=lambda item: item[1], reverse=True):
        mesaj += f"• {tel_no}: {count} SMS\n"
        toplam_sms += count

    mesaj += f"\n--- \nToplam Gelen SMS: {toplam_sms}"

    await update.message.reply_text(
        text=mesaj,
        parse_mode=telegram.constants.ParseMode.MARKDOWN
    )
    logger.info(f"Grup ID {grup_id}'ye anlık durum raporu gönderildi.")


@yetkili_mi
async def id_komutu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id
    chat_title = update.effective_chat.title

    await update.message.reply_text(
        f"Bu sohbetin adı: **{chat_title}**\n"
        f"Bu sohbetin ID'si: `{chat_id}`",
        parse_mode=telegram.constants.ParseMode.MARKDOWN
    )
    logger.info(f"ID istendi: {chat_title} (ID: {chat_id})")


# --- SMS Yönlendirme İşleyicisi (User-bot'tan gelen SMS'ler için) ---
async def sms_isleyici_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    User-bot'tan gelen SMS mesajlarını işler.
    Sadece USER_BOT_ID'den gelen mesajları dinleyecek.
    """
    gelen_mesaj = update.message

    if not gelen_mesaj or not gelen_mesaj.text:
        return

    # Sadece User-bot'un ID'sinden gelen mesajları işle
    if gelen_mesaj.from_user.id != USER_BOT_ID:
        logger.warning(f"SMS işleyici: {gelen_mesaj.from_user.id} ID'li kullanıcıdan gelen mesaj yoksayıldı (beklenen {USER_BOT_ID}).")
        return

    logger.info(f"Ana bot user-bot'tan SMS aldı: {gelen_mesaj.text[:50]}...")

    mesaj_metni = gelen_mesaj.text
    tel_no = mesajdan_tel_no_bul(mesaj_metni)

    if not tel_no:
        logger.warning(f"User-bot'tan gelen mesajda telefon numarası bulunamadı: {mesaj_metni[:50]}")
        return

    # SMS metninden istenen bilgileri çek
    uygulama_adi = mesajdan_bilgi_al(mesaj_metni, "Uygulama Adı")
    mesaj_icerigi = mesajdan_bilgi_al(mesaj_metni, "Mesaj")
    kod = mesajdan_bilgi_al(mesaj_metni, "Kod")
    saat = mesajdan_bilgi_al(mesaj_metni, "Saat")

    # Yeni formatta mesaj oluştur
    # Kod varsa tıkla kopyala olarak ekle
    yeni_mesaj = "✅ YENİ SMS GELDİ\n\n"
    if uygulama_adi:
        yeni_mesaj += f"Uygulama Adı: {uygulama_adi}\n"
    if tel_no: # tel_no'yu zaten en başta bulduk
        yeni_mesaj += f"Tel No: {tel_no}\n"
    if mesaj_icerigi:
        yeni_mesaj += f"Mesaj: {mesaj_icerigi}\n"
    if kod:
        yeni_mesaj += f"Kod: `{kod}`\n" # Tıkla kopyala için ters tırnaklar arasına alındı
    if saat:
        yeni_mesaj += f"Saat: {saat}\n"


    yonlendirildi = False

    for hedef_grup_id, numaralar_seti in beklenen_numaralar.items():
        sms_raporu.setdefault(hedef_grup_id, {}).setdefault(tel_no, 0)
        sms_raporu[hedef_grup_id][tel_no] += 1

        if tel_no in numaralar_seti:
            try:
                await context.bot.send_message(
                    chat_id=hedef_grup_id,
                    text=yeni_mesaj, # Yeni oluşturulan mesaj gönderiliyor
                    parse_mode=telegram.constants.ParseMode.MARKDOWN
                )
                logger.info(f"Numara {tel_no} için SMS, hedef grup ID {hedef_grup_id}'ye yönlendirildi.")
                yonlendirildi = True
            except Exception as e:
                logger.error(f"SMS hedef grup ID {hedef_grup_id}'ye yönlendirilirken hata oluştu: {e}")

    if yonlendirildi:
        veri_kaydet()


async def rapor_gonder_job(context: ContextTypes.DEFAULT_TYPE):
    """APScheduler tarafından çağrılan rapor gönderme işi."""
    global sms_raporu
    
    if not sms_raporu:
        logger.info("Rapor gönderilecek veri yok.")
        return

    logger.info("Gün sonu raporu hazırlanıyor ve sadece belirlenen kullanıcıya gönderiliyor.")

    # Tüm raporlar tek bir kişiye yönlendirileceği için, hangi grubun raporu olduğunu belirtelim.
    for grup_id, rapor_data in sms_raporu.items():
        if not rapor_data:
            continue

        # Mesajın başına hangi gruba ait olduğunu ekliyoruz
        mesaj = f"GÜN SONU RAPOR (Sorgu Yapan Sohbet ID: {grup_id})\n\n"
        toplam_sms = 0
        for tel_no, count in rapor_data.items():
            mesaj += f"• {tel_no} : {count} SMS\n"
            toplam_sms += count
        mesaj += f"\n--- \nToplam Yönlendirilen SMS: {toplam_sms}"

        try:
            await context.bot.send_message(
                chat_id=RAPOR_ALICISI_ID, # <<< Sadece senin ID'ne gönderiliyor
                text=mesaj,
                parse_mode=telegram.constants.ParseMode.MARKDOWN
            )
            logger.info(f"Rapor grup ID {grup_id}'den alınıp kullanıcı ID {RAPOR_ALICISI_ID}'ye yönlendirildi.")
        except Exception as e:
            logger.error(f"Rapor kullanıcı ID {RAPOR_ALICISI_ID}'ye gönderilirken hata oluştu: {e}")

    sms_raporu = {}
    veri_kaydet()


async def hata_yoneticisi(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Hata oluştu:", exc_info=context.error)


def main() -> None:
    """Run the bot."""
    application = Application.builder().token(BOT_TOKEN).build()

    # Zamanlanmış görevler için APScheduler'ı başlat
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    report_time = datetime.time(hour=23, minute=55, tzinfo=TIMEZONE)
    scheduler.add_job(rapor_gonder_job, 'cron', hour=report_time.hour, minute=report_time.minute, args=(application,))
    
    # Scheduler'ı Application'ın event loop'una bağla
    application.job_queue.scheduler = scheduler
    
    # Komut İşleyicilerini Ekle (Sadece yetkili kullanıcı için)
    application.add_handler(CommandHandler("ver", ver_komutu))
    application.add_handler(CommandHandler("sil", sil_komutu))
    application.add_handler(CommandHandler("silhepsi", sil_hepsi_komutu))
    application.add_handler(CommandHandler("rapor", rapor_komutu)) 
    application.add_handler(CommandHandler("aktif", aktif_komutu))
    application.add_handler(CommandHandler("id", id_komutu))

    # SMS işleyiciyi ekle: Sadece User-bot'un ID'sinden (USER_BOT_ID) gelen mesajları dinle
    application.add_handler(MessageHandler(filters.User(USER_BOT_ID) & filters.TEXT & ~filters.COMMAND, sms_isleyici_bot))

    application.add_error_handler(hata_yoneticisi)

    logger.info("Ana Bot (CengizAtaySMSbot) başlatılıyor...")
    # Scheduler'ı Application ile birlikte başlat
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True, close_loop=False)

if __name__ == '__main__':
    veri_yukle() # Bot başlamadan önce verileri yükle
    main()

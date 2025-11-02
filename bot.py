import os
import asyncio
import logging
from dotenv import load_dotenv
from pyrogram import Client, filters
from pyrogram.errors import FloodWait
import re
import time

# .env dosyasını yükle
load_dotenv()

# --- YAPILANDIRMA AYARLARI ---
try:
    API_ID = int(os.getenv('API_ID'))
    API_HASH = os.getenv('API_HASH')
    KAYNAK_GRUP_ID = int(os.getenv('KAYNAK_GRUP_ID')) 
    SMS_BOT_ID = int(os.getenv('SMS_BOT_ID'))
    ANA_BOT_USERNAME = os.getenv('ANA_BOT_USERNAME', 'CengizAtaySMSbot')
    PYROGRAM_SESSION_STRING = os.getenv('PYROGRAM_SESSION_STRING')

    if not all([API_ID, API_HASH, KAYNAK_GRUP_ID, SMS_BOT_ID, ANA_BOT_USERNAME, PYROGRAM_SESSION_STRING]):
        raise ValueError("Tüm gerekli ortam değişkenleri tanımlanmalıdır (API_ID, API_HASH, KAYNAK_GRUP_ID, SMS_BOT_ID, ANA_BOT_USERNAME, PYROGRAM_SESSION_STRING).")

except (TypeError, ValueError) as e:
    print(f"HATA: Ortam değişkenleri doğru yüklenemedi. Detay: {e}")
    exit(1)

# Basit bir günlük tutma (logging) ayarı
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Pyrogram user-bot client'ını başlat
user_app = Client(
    name="user_bot_session",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=PYROGRAM_SESSION_STRING
)

# --- Yardımcı Fonksiyon ---
def mesajdan_tel_no_bul(mesaj_metni: str) -> str | None:
    """Mesaj metninden 'Tel No: XXXXXXXXXX' kısmını bulur."""
    eslesme = re.search(r'Tel No:\s*(\d{10})', mesaj_metni) 
    if eslesme:
        return eslesme.group(1)
    return None

# --- User-Bot Ana Polling Fonksiyonu ---
async def start_message_polling():
    """
    Belirli aralıklarla Kaynak Grup'taki yeni mesajları kontrol eder
    ve @smsbizdenbot'tan gelenleri Ana Bot'a iletir.
    """
    # last_checked_message_id'yi ilk çalıştığında grubun en son mesaj ID'si olarak ayarla
    # Bu, botun başlatıldığı anda geçmiş mesajları işlemesini engeller.
    try:
        async for message in user_app.get_chat_history(chat_id=KAYNAK_GRUP_ID, limit=1):
            initial_last_id = message.id
            logger.info(f"POLLING INIT: Kaynak Grup'un başlangıç en son mesaj ID'si alındı: {initial_last_id}")
            break # Sadece ilk mesajı alıp çık
        else: # Döngü hiç çalışmazsa (grup boşsa)
            initial_last_id = 0
            logger.warning("POLLING INIT: Kaynak Grup boş görünüyor, başlangıç mesaj ID'si 0 olarak ayarlandı.")
    except Exception as e:
        logger.error(f"POLLING INIT: Başlangıç mesaj ID'si alınırken hata: {e}. 0 olarak ayarlandı.")
        initial_last_id = 0

    last_checked_message_id = initial_last_id
    polling_interval = 5 # Her 5 saniyede bir kontrol et

    logger.info(f"User-bot mesaj polling'i başlatılıyor. Kaynak Grup ID: {KAYNAK_GRUP_ID}, SMS Bot ID: {SMS_BOT_ID}. Şu anki takip ID: {last_checked_message_id}")

    while True:
        try:
            current_polling_max_id = last_checked_message_id # Bu döngüdeki en yüksek mesaj ID'sini takip etmek için
            messages_found_in_this_poll = False

            logger.info(f"--- POLLING DEBUG: Yeni mesajlar için kontrol ediliyor. last_checked_message_id: {last_checked_message_id}")
            
            # Kaynak Grup'tan yeni mesajları çek
            # offset_id yerine min_id kullanmak daha tutarlı olabilir, ancak get_chat_history'de min_id yok.
            # Dolayısıyla offset_id ile devam edip kendi mantığımızı güçlendireceğiz.
            messages_to_process = []
            
            # Önce mesajları bir listeye çekip sonra işlememiz, asenkron iteratörden kaynaklanabilecek sorunları azaltabilir.
            # offset_id ile alındıktan sonra, hala kendi içimizde filtreleme yapıyoruz.
            async for message in user_app.get_chat_history(chat_id=KAYNAK_GRUP_ID, limit=100, offset_id=last_checked_message_id):
                if message.id > last_checked_message_id: # Sadece gerçekten yeni olanları ekle
                    messages_to_process.append(message)
                    messages_found_in_this_poll = True
                
                # Bu polling döngüsünde gördüğümüz en yüksek ID'yi takip et
                if message.id > current_polling_max_id:
                    current_polling_max_id = message.id

            # Mesajları ID'ye göre sırala (en eskiden en yeniye)
            messages_to_process.sort(key=lambda m: m.id)

            for message in messages_to_process:
                logger.info(f"--- POLLING AGGRESSIVE DEBUG: Yeni mesaj bulundu (ID: {message.id}).")
                logger.info(f"Chat ID: {message.chat.id}")
                logger.info(f"Gönderen ID: {message.from_user.id if message.from_user else 'Yok'}")
                logger.info(f"Mesaj Metni: {message.text[:100] if message.text else 'Yok'}...")

                # 1. SMS Botu'ndan mı geldi?
                if message.from_user and message.from_user.id == SMS_BOT_ID:
                    # 2. Metin mesajı mı?
                    if message.text:
                        logger.info(f"User-bot SMS'i yakaladı - Kaynak Grup ID: {message.chat.id}, Kimden: {message.from_user.username}, Metin: {message.text[:50]}...")
                        
                        mesaj_metni = message.text
                        try:
                            await user_app.send_message(
                                chat_id=f"@{ANA_BOT_USERNAME}", # Ana Bot'un kullanıcı adı
                                text=mesaj_metni
                            )
                            logger.info(f"User-bot, SMS'i Ana Bot ({ANA_BOT_USERNAME})'a başarıyla iletti.")
                        except FloodWait as e:
                            logger.warning(f"User-bot FloodWait hatası, {e.value} saniye bekleniyor...")
                            await asyncio.sleep(e.value)
                        except Exception as e:
                            logger.error(f"User-bot SMS'i Ana Bot'a iletirken hata oluştu: {e}")
                    else:
                        logger.warning(f"POLLING AGGRESSIVE DEBUG: SMS botundan gelen mesaj metin formatında değil (ID: {message.id}). Yoksayılıyor.")
                else:
                    logger.warning(f"POLLING AGGRESSIVE DEBUG: Mesaj SMS botundan gelmedi (Gönderen ID: {message.from_user.id if message.from_user else 'Yok'}). Yoksayılıyor.")
                
                # Her işlenen mesajdan sonra last_checked_message_id'yi güncelle
                # Bu, özellikle bir polling döngüsünde birden fazla yeni mesaj varsa önemlidir.
                if message.id > last_checked_message_id:
                    last_checked_message_id = message.id
            
            # Eğer bu polling döngüsünde hiç yeni mesaj gelmediyse,
            # ve initial_last_id hala 0 ise (yani grup boştu),
            # veya sadece tek bir mesaj gelip current_polling_max_id güncellendiyse
            # last_checked_message_id'yi en son görülen ID'ye eşitle.
            # Bu, mesaj gelmese bile botun ilerlemesini sağlar.
            if not messages_found_in_this_poll and current_polling_max_id > last_checked_message_id:
                 last_checked_message_id = current_polling_max_id


        except FloodWait as e:
            logger.warning(f"User-bot FloodWait hatası, {e.value} saniye bekleniyor...")
            await asyncio.sleep(e.value)
        except Exception as e:
            logger.error(f"Mesajları kontrol ederken veya işlerken beklenmedik bir hata oluştu: {e}")
        
        await asyncio.sleep(polling_interval)

# --- Ana Çalıştırma Fonksiyonu ---
async def main_user_bot() -> None:
    logger.info("User-bot (Pyrogram) başlatılıyor...")
    await user_app.start()
    logger.info("User-bot (Pyrogram) başarıyla bağlandı.")
    
    logger.info("Sohbet listesi (dialogs) yükleniyor... ('Peer id invalid' hatasını önlemek için)")
    try:
        dialog_count = 0
        async for dialog in user_app.get_dialogs(limit=10):
            logger.info(f"Dialog bulundu: {dialog.chat.title} (ID: {dialog.chat.id})")
            dialog_count += 1
        
        if dialog_count == 0:
            logger.warning("User-bot'un hiçbir sohbet listesi (dialog) bulunamadı. Lütfen hesabın en az bir gruba üye olduğundan emin olun.")
        
        logger.info("Sohbet listesi yüklendi. Polling başlatılıyor.")
    except Exception as e:
        logger.error(f"Sohbet listesi (dialogs) yüklenirken hata oluştu: {e}")
        # Hata olsa bile devam etmeyi deneyelim, belki cache dolmuştur.
    
    # User-bot çalıştıktan sonra polling fonksiyonunu başlat
    await start_message_polling()


if __name__ == '__main__':
    try:
        asyncio.run(main_user_bot()) # Asenkron ana fonksiyonu çalıştır
    except Exception as e:
        logger.error(f"User-bot çalışırken kritik bir hata oluştu: {e}")

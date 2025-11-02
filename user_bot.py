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
    API_HASH = os.getenv('API_HASH') # <<< HATA BURADAYDI, FAZLA PARANTEZ KALDIRILDI
    KAYNAK_GRUP_ID = int(os.getenv('KAYNAK_GRUP_ID')) # -3143296393 olarak kalmalı
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
    last_checked_message_id = 0 # En son kontrol edilen mesajın ID'si
    polling_interval = 5 # Her 5 saniyede bir kontrol et

    logger.info(f"User-bot mesaj polling'i başlatılıyor. Kaynak Grup ID: {KAYNAK_GRUP_ID}, SMS Bot ID: {SMS_BOT_ID}")

    while True:
        try:
            logger.info(f"--- POLLING DEBUG: Yeni mesajlar için kontrol ediliyor. last_checked_message_id: {last_checked_message_id}")
            
            # Kaynak Grup'tan yeni mesajları çek
            async for message in user_app.get_chat_history(chat_id=KAYNAK_GRUP_ID, limit=100, offset_id=last_checked_message_id):
                
                # Sadece mesaj ID'si bizim son kontrol ettiğimizden büyük olanları işle
                if message.id > last_checked_message_id:
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
                    
                    # En son kontrol edilen mesaj ID'sini güncelle
                    last_checked_message_id = max(last_checked_message_id, message.id)

            # Eğer hiç mesaj gelmediyse ve last_checked_message_id hala 0 ise,
            # bu, botun ilk başlatıldığında veya hiç yeni mesaj olmadığında
            # en son ID'yi alması için yardımcı olur.
            if last_checked_message_id == 0:
                 # Grubun son mesajını çekip ID'sini al
                async for message in user_app.get_chat_history(chat_id=KAYNAK_GRUP_ID, limit=1):
                    last_checked_message_id = message.id
                    logger.info(f"POLLING DEBUG: İlk kontrol için Kaynak Grup'un en son mesaj ID'si alındı: {last_checked_message_id}")

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
    
    # --- YENİ EKLENEN KISIM ---
    logger.info("Sohbet listesi (dialogs) yükleniyor... ('Peer id invalid' hatasını önlemek için)")
    try:
        # Botun üye olduğu sohbetleri çekiyoruz. limit=10 sadece cache'i doldurmak için.
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
    # --- YENİ EKLENEN KISIM BİTTİ ---
    
    # User-bot çalıştıktan sonra polling fonksiyonunu başlat
    await start_message_polling()


if __name__ == '__main__':
    try:
        asyncio.run(main_user_bot()) # Asenkron ana fonksiyonu çalıştır
    except Exception as e:
        logger.error(f"User-bot çalışırken kritik bir hata oluştu: {e}")

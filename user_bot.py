import os
import asyncio
import logging
from dotenv import load_dotenv
from pyrogram import Client, filters
from pyrogram.types import Message, Update
from pyrogram.errors import FloodWait
from pyrogram.raw.types import UpdateNewMessage, UpdateNewChannelMessage # Ham mesaj tiplerini almak için
import re

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

# --- User-Bot RAW Update Dinleyicisi ---
@user_app.on_raw_update()
async def raw_update_handler(client: Client, update: Update, users, chats):
    """
    Telegram'dan gelen tüm ham güncellemeleri yakalar ve loglar.
    Mesajları manuel olarak filtreler ve Ana Bot'a iletir.
    """
    logger.info(f"--- ÇOK AGRESİF RAW DEBUG: Ham Güncelleme Alındı: {type(update).__name__}")
    
    # Gelen güncellemenin bir mesaj içerip içermediğini kontrol et
    message = None
    if isinstance(update, (UpdateNewMessage, UpdateNewChannelMessage)):
        raw_message = update.message
        if hasattr(raw_message, 'chat') and hasattr(raw_message, 'message'):
            # Pyrogram mesaj objesine çevir
            message = await Message.parse(client, raw_message, users, chats)

    if message:
        # --- AGGRESSIVE DEBUG BAŞLANGIÇ (Mesaj objesi oluşturulabildiyse) ---
        logger.info(f"--- RAW AGGRESSIVE DEBUG: Pyrogram Message objesi oluşturuldu.")
        logger.info(f"Chat ID: {message.chat.id}")
        logger.info(f"Chat Type: {message.chat.type}")
        logger.info(f"Chat Title: {message.chat.title}")
        logger.info(f"Gönderen ID: {message.from_user.id if message.from_user else 'Yok'}")
        logger.info(f"Gönderen Username: {message.from_user.username if message.from_user else 'Yok'}")
        logger.info(f"Mesaj Metni: {message.text[:100] if message.text else 'Yok'}...")
        logger.info(f"Mesaj Tarihi: {message.date.isoformat()}")
        
        # Şimdi asıl filtreleri burada manuel olarak kontrol edelim
        # 1. Kaynak Grup'tan mı geldi?
        if message.chat.id != KAYNAK_GRUP_ID:
            logger.warning(f"RAW AGGRESSIVE DEBUG: Mesaj Kaynak Gruptan (Beklenen ID: {KAYNAK_GRUP_ID}) gelmedi. Geldiği yer: {message.chat.title} (ID: {message.chat.id}). Yoksayılıyor.")
            return # Kaynak Grup değilse hemen çık
        
        # 2. @smsbizdenbot'tan mı geldi?
        if (message.from_user is None) or (message.from_user.id != SMS_BOT_ID):
            logger.warning(f"RAW AGGRESSIVE DEBUG: Mesaj @smsbizdenbot'tan (Beklenen ID: {SMS_BOT_ID}) gelmedi. Gönderen ID: {message.from_user.id if message.from_user else 'Yok'}. Yoksayılıyor.")
            return # SMS botundan gelmediyse hemen çık
            
        # 3. Metin mesajı mı?
        if not message.text:
            logger.warning("RAW AGGRESSIVE DEBUG: Mesaj metin formatında değil. Yoksayılıyor.")
            return # Metin mesajı değilse hemen çık
        # --- AGGRESSIVE DEBUG BİTTİ ---

        # Eğer tüm filtreleri geçtiyse, Ana Bot'a ilet
        logger.info(f"User-bot mesajı yakaladı - Kaynak Grup ID: {message.chat.id}, Kimden: {message.from_user.username}, Metin: {message.text[:50]}...")

        mesaj_metni = message.text
        
        try:
            await client.send_message(
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
        logger.info(f"--- ÇOK AGRESİF RAW DEBUG: Güncelleme mesaj içermiyor veya Pyrogram Message objesine dönüştürülemedi.")

# --- Ana Çalıştırma Fonksiyonu ---
async def main_user_bot() -> None:
    logger.info("User-bot (Pyrogram) başlatılıyor...")
    await user_app.start()
    logger.info("User-bot (Pyrogram) başarıyla bağlandı ve dinlemede!")
    
    await asyncio.Event().wait() # Sonsuz bekleme, user-bot'un kapanmamasını sağlar


if __name__ == '__main__':
    try:
        asyncio.run(main_user_bot()) # Asenkron ana fonksiyonu çalıştır
    except Exception as e:
        
        logger.error(f"User-bot çalışırken kritik bir hata oluştu: {e}")
=======
        logger.error(f"User-bot çalışırken kritik bir hata oluştu: {e}")

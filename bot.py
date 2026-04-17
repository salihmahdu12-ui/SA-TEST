import logging
import os
import asyncio
import platform

from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage

from re import findall
from httpx import AsyncClient
from io import BytesIO
from PIL import Image

from settings import languages, API_TOKEN

# ================== إعداد البوت ==================
storage = MemoryStorage()
logging.basicConfig(level=logging.INFO)

API_TOKEN = os.getenv("BOT_TOKEN")
dp = Dispatcher(bot, storage=storage)

# ================== أدوات مساعدة ==================
def is_tool(name):
    from shutil import which
    return which(name) is not None


def get_user_lang(locale):
    user_lang = locale.language
    return user_lang if user_lang in languages else "en"


def divide_chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def convert_image(image, extention):
    byteImgIO = BytesIO()
    byteImg = Image.open(BytesIO(image)).convert("RGB")
    byteImg.save(byteImgIO, extention)
    byteImgIO.seek(0)
    return byteImgIO


def get_url_of_yt_dlp():
    download_url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"
    os_name = platform.system().lower()
    arch = platform.machine().lower()

    if os_name == "darwin":
        return f"{download_url}_macos"
    elif os_name == "windows":
        if arch in ["amd64", "x86_64"]:
            return f"{download_url}.exe"
        elif arch in ["i386", "i686"]:
            return f"{download_url}_x86.exe"
    elif os_name == "linux":
        if arch in ["aarch64"]:
            return f"{download_url}_linux_aarch64"
        elif arch in ["amd64", "x86_64"]:
            return f"{download_url}_linux"
    return None

# ================== تحميل باستخدام yt-dlp ==================
async def yt_dlp_download(url):
    proc = await asyncio.create_subprocess_exec(
        'yt-dlp', url,
        "--max-filesize", "50M",
        "--max-downloads", "1",
        "--restrict-filenames",
        stdout=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.PIPE,
    )

    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
    except asyncio.TimeoutError:
        proc.kill()
        raise Exception("timeout")

    for line in stdout.decode().splitlines():
        filename = findall(r"Destination: (.*?)$", line)
        if filename:
            return filename[0]

        filename = findall(r"(.*?) has already been downloaded$", line)
        if filename:
            return filename[0]

    raise Exception("file not found")

# ================== TikTok API ==================
async def tt_videos_or_images(url):
    video_id = findall('video/(\\d+)', url)
    user_agent = "Mozilla/5.0"

    if video_id:
        video_id = video_id[0]
    else:
        async with AsyncClient() as client:
            r = await client.get(url, headers={"User-Agent": user_agent})
            video_id = findall("video/(\\d+)", r.text)[0]

    api_url = f"https://api16-normal-useast5.us.tiktokv.com/aweme/v1/aweme/detail/?aweme_id={video_id}"

    async with AsyncClient() as client:
        r = await client.get(api_url, headers={"User-Agent": user_agent})

    data = r.json().get("aweme_detail")
    if not data:
        raise Exception("No video found")

    if data["video"]["bit_rate"]:
        urls = data["video"]["bit_rate"][0]["play_addr"]["url_list"]
        return {"type": "video", "urls": urls}
    else:
        images = [
            i["display_image"]["url_list"][0]
            for i in data["image_post_info"]["images"]
        ]
        return {"type": "images", "urls": images}

# ================== Handlers ==================
@dp.message_handler(commands=['start', 'help'])
async def send_welcome(message: types.Message):
    lang = get_user_lang(message.from_user.locale)
    await message.reply(languages[lang]["help"])


@dp.message_handler(regexp='https://')
async def downloader(message: types.Message):
    lang = get_user_lang(message.from_user.locale)
    await message.reply(languages[lang]["wait"])

    link = findall(r'https?://\\S+', message.text)[0]

    try:
        # حاول TikTok API أولاً
        if "tiktok.com" in link:
            data = await tt_videos_or_images(link)

            if data["type"] == "video":
                await message.reply_video(data["urls"][0])
            else:
                for img in data["urls"]:
                    await message.reply_photo(img)

        else:
            # fallback إلى yt-dlp
            file = await yt_dlp_download(link)

            if file.endswith(".mp3"):
                await message.reply_audio(open(file, 'rb'))
            else:
                await message.reply_video(open(file, 'rb'))

            os.remove(file)

    except Exception as e:
        logging.error(e)
        await message.reply(f"Error: {e}")


@dp.message_handler()
async def echo(message: types.Message):
    lang = get_user_lang(message.from_user.locale)
    await message.answer(languages[lang]["invalid_link"])

# ================== تشغيل ==================
if __name__ == '__main__':
    if is_tool("yt-dlp"):
        executor.start_polling(dp, skip_updates=True)
    else:
        print("yt-dlp not installed")

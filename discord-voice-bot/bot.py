import discord
from discord.ext import commands
import asyncio
import random
import os
import aiohttp
from datetime import datetime
import yt_dlp
from dotenv import load_dotenv

load_dotenv()  # Загружаем переменные из файла .env

TOKEN = os.getenv('TOKEN')
CHANNEL_ID = int(os.getenv('CHANNEL_ID'))
# Настройки для yt-dlp
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
}

ffmpeg_options = {
    'options': '-vn',
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        if 'entries' in data:
            data = data['entries'][0]
        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)


# ==================== НАСТРОЙКА БОТА ====================
intents = discord.Intents.default()
intents.voice_states = True
# intents.message_content = True   # ЗАКОММЕНТИРУЙТЕ ЭТУ СТРОКУ
# intents.members = True           # И ЭТУ

bot = commands.Bot(command_prefix='!', intents=intents)

# Глобальные переменные
queues = {}
anti_kick_active = True
afk_users = {}
warns = {}
leveling = {}
economy = {}


def get_queue(guild_id):
    if guild_id not in queues:
        queues[guild_id] = []
    return queues[guild_id]


# ==================== СОБЫТИЯ ====================
@bot.event
async def on_ready():
    print(f'✅ Бот {bot.user} запущен!')
    print(f'👤 Имя: {bot.user.name}')
    print(f'🆔 ID: {bot.user.id}')

    # Подключение к каналу
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        try:
            if not bot.voice_clients:
                await channel.connect()
                print(f'🎧 Бот зашёл в канал {channel.name}!')
        except Exception as e:
            print(f'❌ Ошибка подключения: {e}')
    else:
        print(f'❌ Канал с ID {CHANNEL_ID} не найден!')

    await bot.tree.sync()
    print('✅ Слеш-команды синхронизированы!')


@bot.event
async def on_voice_state_update(member, before, after):
    global anti_kick_active

    # Защита от AFK
    if member.id == bot.user.id:
        if after.afk and anti_kick_active:
            print(f'⚠️ Бота отправили в AFK! Возвращаю...')
            await asyncio.sleep(1)
            target_channel = bot.get_channel(CHANNEL_ID)
            if target_channel:
                try:
                    await member.move_to(target_channel)
                    print(f'✅ Бот возвращён в канал {target_channel.name}')
                except Exception as e:
                    print(f'❌ Ошибка возврата из AFK: {e}')

    # Система уровней за голосовой онлайн
    if not member.bot:
        if after.channel and not before.channel:
            if member.id not in leveling:
                leveling[member.id] = {'xp': 0, 'level': 1}
            leveling[member.id]['xp'] += 5
            if leveling[member.id]['xp'] >= leveling[member.id]['level'] * 100:
                leveling[member.id]['level'] += 1
                await member.send(f'🎉 Поздравляю! Ты достиг {leveling[member.id]["level"]} уровня!')


# ==================== МУЗЫКАЛЬНЫЕ КОМАНДЫ ====================
async def play_next(guild_id, voice_client, text_channel):
    queue = get_queue(guild_id)
    if queue:
        player = queue.pop(0)
        voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(
            play_next(guild_id, voice_client, text_channel), bot.loop))
        await text_channel.send(f'🎶 Сейчас играет: **{player.title}**')
    else:
        await text_channel.send('⏹️ Очередь пуста')


@bot.tree.command(name='play', description='Воспроизвести музыку из YouTube')
async def play(interaction: discord.Interaction, query: str):
    if not interaction.user.voice:
        await interaction.response.send_message('❌ Вы не в голосовом канале!', ephemeral=True)
        return

    await interaction.response.defer()

    channel = interaction.user.voice.channel
    queue = get_queue(interaction.guild_id)

    try:
        player = await YTDLSource.from_url(query, loop=bot.loop, stream=True)
        queue.append(player)

        if not interaction.guild.voice_client:
            await channel.connect()

        if not interaction.guild.voice_client.is_playing():
            await play_next(interaction.guild_id, interaction.guild.voice_client, interaction.channel)

        await interaction.followup.send(f'🎵 Добавлено в очередь: **{player.title}**')
    except Exception as e:
        await interaction.followup.send(f'❌ Ошибка: {e}')


@bot.tree.command(name='pause', description='Поставить музыку на паузу')
async def pause(interaction: discord.Interaction):
    voice = interaction.guild.voice_client
    if voice and voice.is_playing():
        voice.pause()
        await interaction.response.send_message('⏸️ Музыка на паузе')
    else:
        await interaction.response.send_message('ℹ️ Музыка не играет', ephemeral=True)


@bot.tree.command(name='resume', description='Продолжить музыку')
async def resume(interaction: discord.Interaction):
    voice = interaction.guild.voice_client
    if voice and voice.is_paused():
        voice.resume()
        await interaction.response.send_message('▶️ Музыка продолжена')
    else:
        await interaction.response.send_message('ℹ️ Музыка не на паузе', ephemeral=True)


@bot.tree.command(name='skip', description='Пропустить текущий трек')
async def skip(interaction: discord.Interaction):
    voice = interaction.guild.voice_client
    if voice and voice.is_playing():
        voice.stop()
        await interaction.response.send_message('⏭️ Трек пропущен')
    else:
        await interaction.response.send_message('ℹ️ Музыка не играет', ephemeral=True)


@bot.tree.command(name='stop', description='Остановить музыку и очистить очередь')
async def stop(interaction: discord.Interaction):
    voice = interaction.guild.voice_client
    if voice:
        queue = get_queue(interaction.guild_id)
        queue.clear()
        voice.stop()
        await voice.disconnect()
        await interaction.response.send_message('⏹️ Музыка остановлена, очередь очищена')
    else:
        await interaction.response.send_message('ℹ️ Бот не в голосовом канале', ephemeral=True)


@bot.tree.command(name='queue', description='Показать очередь треков')
async def show_queue(interaction: discord.Interaction):
    queue = get_queue(interaction.guild_id)
    if not queue:
        await interaction.response.send_message('📭 Очередь пуста')
        return

    queue_list = '\n'.join([f'{i + 1}. {track.title}' for i, track in enumerate(queue[:10])])
    await interaction.response.send_message(f'📋 Очередь (первые 10):\n{queue_list}')


@bot.tree.command(name='clearqueue', description='Очистить очередь')
async def clear_queue(interaction: discord.Interaction):
    queue = get_queue(interaction.guild_id)
    queue.clear()
    await interaction.response.send_message('🗑️ Очередь очищена')


@bot.tree.command(name='volume', description='Изменить громкость (0-100)')
async def volume(interaction: discord.Interaction, level: int):
    voice = interaction.guild.voice_client
    if voice and voice.source:
        if 0 <= level <= 100:
            voice.source.volume = level / 100
            await interaction.response.send_message(f'🔊 Громкость установлена на {level}%')
        else:
            await interaction.response.send_message('❌ Укажите число от 0 до 100', ephemeral=True)
    else:
        await interaction.response.send_message('ℹ️ Музыка не играет', ephemeral=True)


# ==================== МОДЕРАЦИЯ ====================
@bot.tree.command(name='kick', description='Выгнать пользователя с сервера')
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "Не указана"):
    if not interaction.user.guild_permissions.kick_members:
        await interaction.response.send_message('❌ У вас нет прав на кик', ephemeral=True)
        return

    await member.kick(reason=reason)
    await interaction.response.send_message(f'👢 {member.mention} был выгнан. Причина: {reason}')


@bot.tree.command(name='ban', description='Забанить пользователя')
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "Не указана"):
    if not interaction.user.guild_permissions.ban_members:
        await interaction.response.send_message('❌ У вас нет прав на бан', ephemeral=True)
        return

    await member.ban(reason=reason)
    await interaction.response.send_message(f'🔨 {member.mention} был забанен. Причина: {reason}')


@bot.tree.command(name='mute', description='Замутить пользователя (выдать роль Muted)')
async def mute(interaction: discord.Interaction, member: discord.Member, reason: str = "Не указана"):
    if not interaction.user.guild_permissions.moderate_members:
        await interaction.response.send_message('❌ У вас нет прав на мут', ephemeral=True)
        return

    mute_role = discord.utils.get(interaction.guild.roles, name="Muted")
    if not mute_role:
        mute_role = await interaction.guild.create_role(name="Muted")
        for channel in interaction.guild.channels:
            await channel.set_permissions(mute_role, send_messages=False, speak=False)

    await member.add_roles(mute_role, reason=reason)
    await interaction.response.send_message(f'🔇 {member.mention} замучен. Причина: {reason}')


@bot.tree.command(name='unmute', description='Размутить пользователя')
async def unmute(interaction: discord.Interaction, member: discord.Member):
    if not interaction.user.guild_permissions.moderate_members:
        await interaction.response.send_message('❌ У вас нет прав на размут', ephemeral=True)
        return

    mute_role = discord.utils.get(interaction.guild.roles, name="Muted")
    if mute_role and mute_role in member.roles:
        await member.remove_roles(mute_role)
        await interaction.response.send_message(f'🔊 {member.mention} размучен')
    else:
        await interaction.response.send_message('ℹ️ Пользователь не замучен')


@bot.tree.command(name='warn', description='Выдать предупреждение')
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str = "Не указана"):
    if not interaction.user.guild_permissions.moderate_members:
        await interaction.response.send_message('❌ У вас нет прав', ephemeral=True)
        return

    if interaction.guild_id not in warns:
        warns[interaction.guild_id] = {}
    if member.id not in warns[interaction.guild_id]:
        warns[interaction.guild_id][member.id] = []

    warns[interaction.guild_id][member.id].append(reason)
    await interaction.response.send_message(f'⚠️ {member.mention} получил предупреждение. Причина: {reason}')


@bot.tree.command(name='warns', description='Показать предупреждения пользователя')
async def show_warns(interaction: discord.Interaction, member: discord.Member):
    if not interaction.user.guild_permissions.moderate_members:
        await interaction.response.send_message('❌ У вас нет прав', ephemeral=True)
        return

    user_warns = warns.get(interaction.guild_id, {}).get(member.id, [])
    if not user_warns:
        await interaction.response.send_message(f'✅ У {member.mention} нет предупреждений')
    else:
        warn_list = '\n'.join([f'{i + 1}. {w}' for i, w in enumerate(user_warns)])
        await interaction.response.send_message(f'📋 Предупреждения {member.mention}:\n{warn_list}')


@bot.tree.command(name='clear', description='Очистить сообщения в канале (до 100)')
async def clear(interaction: discord.Interaction, amount: int):
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message('❌ У вас нет прав', ephemeral=True)
        return

    if amount <= 0 or amount > 100:
        await interaction.response.send_message('❌ Укажите число от 1 до 100', ephemeral=True)
        return

    await interaction.response.defer()
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f'🗑️ Удалено {len(deleted)} сообщений')


# ==================== РАЗВЛЕЧЕНИЯ ====================
@bot.tree.command(name='ping', description='Проверить задержку бота')
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f'🏓 Понг! Задержка: {latency}мс')


@bot.tree.command(name='8ball', description='Задай вопрос, получи ответ')
async def eightball(interaction: discord.Interaction, question: str):
    answers = [
        "Да", "Нет", "Возможно", "Определённо да", "Определённо нет",
        "Спроси позже", "Не могу сказать сейчас", "Вероятно",
        "Шансы хорошие", "Не рассчитывай на это"
    ]
    await interaction.response.send_message(f'🎱 {random.choice(answers)}')


@bot.tree.command(name='roll', description='Бросить кубик (1-100)')
async def roll(interaction: discord.Interaction, sides: int = 6):
    if sides < 2 or sides > 100:
        await interaction.response.send_message('❌ Укажите число от 2 до 100', ephemeral=True)
        return

    result = random.randint(1, sides)
    await interaction.response.send_message(f'🎲 {interaction.user.mention} выбросил {result} (кубик d{sides})')


@bot.tree.command(name='coin', description='Орёл или решка')
async def coin(interaction: discord.Interaction):
    result = random.choice(['Орёл', 'Решка'])
    await interaction.response.send_message(f'🪙 {result}!')


@bot.tree.command(name='cat', description='Случайный кот (API)')
async def cat(interaction: discord.Interaction):
    async with aiohttp.ClientSession() as session:
        async with session.get('https://api.thecatapi.com/v1/images/search') as resp:
            data = await resp.json()
            await interaction.response.send_message(data[0]['url'])


@bot.tree.command(name='dog', description='Случайная собака (API)')
async def dog(interaction: discord.Interaction):
    async with aiohttp.ClientSession() as session:
        async with session.get('https://dog.ceo/api/breeds/image/random') as resp:
            data = await resp.json()
            await interaction.response.send_message(data['message'])


@bot.tree.command(name='meme', description='Случайный мем (API)')
async def meme(interaction: discord.Interaction):
    async with aiohttp.ClientSession() as session:
        async with session.get('https://meme-api.com/gimme') as resp:
            data = await resp.json()
            await interaction.response.send_message(data['url'])


@bot.tree.command(name='rps', description='Камень-ножницы-бумага')
async def rps(interaction: discord.Interaction, choice: str):
    choices = ['камень', 'ножницы', 'бумага']
    if choice.lower() not in choices:
        await interaction.response.send_message('❌ Выберите: камень, ножницы или бумага', ephemeral=True)
        return

    bot_choice = random.choice(choices)
    if choice.lower() == bot_choice:
        result = 'Ничья!'
    elif (choice.lower() == 'камень' and bot_choice == 'ножницы') or \
            (choice.lower() == 'ножницы' and bot_choice == 'бумага') or \
            (choice.lower() == 'бумага' and bot_choice == 'камень'):
        result = 'Вы выиграли! 🎉'
    else:
        result = 'Я выиграл! 🤖'

    await interaction.response.send_message(f'🗿 Ваш выбор: {choice}\n🤖 Мой выбор: {bot_choice}\n**{result}**')


# ==================== ИНФОРМАЦИЯ ====================
@bot.tree.command(name='userinfo', description='Информация о пользователе')
async def userinfo(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    embed = discord.Embed(title=f'Информация о {member}', color=member.color)
    embed.add_field(name='ID', value=member.id, inline=True)
    embed.add_field(name='Присоединился', value=member.joined_at.strftime('%d.%m.%Y'), inline=True)
    embed.add_field(name='Зарегистрирован', value=member.created_at.strftime('%d.%m.%Y'), inline=True)
    embed.add_field(name='Роли', value=' '.join([r.mention for r in member.roles[1:]]) or 'Нет', inline=False)
    embed.set_thumbnail(url=member.display_avatar.url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name='serverinfo', description='Информация о сервере')
async def serverinfo(interaction: discord.Interaction):
    guild = interaction.guild
    embed = discord.Embed(title=guild.name, color=discord.Color.blue())
    embed.add_field(name='ID', value=guild.id, inline=True)
    embed.add_field(name='Участников', value=guild.member_count, inline=True)
    embed.add_field(name='Каналов', value=len(guild.channels), inline=True)
    embed.add_field(name='Ролей', value=len(guild.roles), inline=True)
    embed.add_field(name='Создан', value=guild.created_at.strftime('%d.%m.%Y'), inline=True)
    embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name='uptime', description='Время работы бота')
async def uptime(interaction: discord.Interaction):
    now = datetime.now()
    start_time = bot.start_time if hasattr(bot, 'start_time') else now
    delta = now - start_time
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    await interaction.response.send_message(f'⏱️ Бот работает: {days}д {hours}ч {minutes}м {seconds}с')


@bot.tree.command(name='avatar', description='Показать аватар пользователя')
async def avatar(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    await interaction.response.send_message(member.display_avatar.url)


# ==================== ФУНКЦИИ ДЛЯ АДМИНОВ ====================
@bot.tree.command(name='antikick', description='Включить/выключить анти-кик')
async def toggle_antikick(interaction: discord.Interaction):
    global anti_kick_active
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message('❌ Только для администраторов', ephemeral=True)
        return

    anti_kick_active = not anti_kick_active
    status = 'включён' if anti_kick_active else 'выключен'
    await interaction.response.send_message(f'🛡️ Анти-кик {status}')


@bot.tree.command(name='join', description='Завести бота в голосовой канал')
async def join(interaction: discord.Interaction):
    if not interaction.user.voice:
        await interaction.response.send_message('❌ Вы не в голосовом канале!', ephemeral=True)
        return

    channel = interaction.user.voice.channel
    if interaction.guild.voice_client:
        await interaction.response.send_message('ℹ️ Бот уже в голосовом канале', ephemeral=True)
        return

    try:
        await channel.connect()
        await interaction.response.send_message(f'🎧 Бот зашёл в канал {channel.name}!')
    except Exception as e:
        await interaction.response.send_message(f'❌ Ошибка: {e}', ephemeral=True)


@bot.tree.command(name='leave', description='Отключить бота от голосового канала')
async def leave(interaction: discord.Interaction):
    if not interaction.guild.voice_client:
        await interaction.response.send_message('ℹ️ Бот не в голосовом канале', ephemeral=True)
        return

    await interaction.guild.voice_client.disconnect()
    await interaction.response.send_message('🔇 Бот отключён от голосового канала!')


@bot.tree.command(name='status', description='Показать статус бота')
async def status(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_connected():
        channel = voice_client.channel
        await interaction.response.send_message(f'🎧 Бот в канале: {channel.name}')
    else:
        await interaction.response.send_message('ℹ️ Бот не в голосовом канале')


# ==================== ОБРАБОТЧИКИ ОШИБОК ====================
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, discord.app_commands.MissingPermissions):
        await interaction.response.send_message('❌ У вас нет прав для этой команды!', ephemeral=True)
    else:
        await interaction.response.send_message(f'❌ Ошибка: {error}', ephemeral=True)


# ==================== ЗАПУСК ====================
bot.start_time = datetime.now()
bot.run(TOKEN)

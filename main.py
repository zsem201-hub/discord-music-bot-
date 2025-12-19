import discord
from discord.ext import commands
import os
import asyncio
import logging

# Setup logging untuk debug
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger('MusicBot')

# Keep alive untuk Replit
from keep_alive import keep_alive

# Intents
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

# Bot
bot = commands.Bot(
    command_prefix=['!', '?', '.'],
    intents=intents,
    help_command=None
)

@bot.event
async def on_ready():
    logger.info(f'✅ {bot.user.name} Online!')
    logger.info(f'📡 Servers: {len(bot.guilds)}')
    
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.listening,
            name="!help | 🎵"
        )
    )

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    logger.error(f'Command error: {error}')
    await ctx.send(f"❌ Error: {str(error)[:100]}")

@bot.command(name='ping')
async def ping(ctx):
    """Test bot response"""
    await ctx.send(f'🏓 Pong! `{round(bot.latency * 1000)}ms`')

async def load_extensions():
    try:
        await bot.load_extension('music_cog')
        logger.info('✅ Music Cog loaded!')
    except Exception as e:
        logger.error(f'❌ Failed to load Music Cog: {e}')

async def main():
    async with bot:
        await load_extensions()
        keep_alive()
        
        token = os.environ.get('DISCORD_TOKEN')
        if not token:
            logger.error('❌ DISCORD_TOKEN not found!')
            return
        
        await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())

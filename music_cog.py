import discord
from discord.ext import commands
import asyncio
import re
import os
import logging
import subprocess
import sys
from collections import deque
from typing import Optional, Dict, Any
import urllib.parse

logger = logging.getLogger('MusicBot.Music')

# ═══════════════════════════════════════════════════════════════
# AUTO UPDATE YT-DLP SAAT STARTUP
# ═══════════════════════════════════════════════════════════════

def update_ytdlp():
    """Update yt-dlp ke versi terbaru"""
    try:
        logger.info("🔄 Updating yt-dlp...")
        subprocess.check_call([
            sys.executable, "-m", "pip", "install",
            "--upgrade", "--force-reinstall", "yt-dlp", "-q"
        ])
        logger.info("✅ yt-dlp updated successfully!")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to update yt-dlp: {e}")
        return False

# Update saat import
update_ytdlp()

# Import setelah update
import yt_dlp

# ═══════════════════════════════════════════════════════════════
# KONFIGURASI - SANGAT PENTING UNTUK BYPASS YOUTUBE BLOCKS
# ═══════════════════════════════════════════════════════════════

class YTDLSource:
    """YouTube Downloader dengan multiple fallback"""
    
    # User agents yang berbeda
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    ]
    
    # Base options
    BASE_OPTS = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'nocheckcertificate': True,
        'ignoreerrors': True,
        'no_warnings': True,
        'quiet': True,
        'extract_flat': False,
        'force_ipv4': True,
        'geo_bypass': True,
        'geo_bypass_country': 'US',
        'socket_timeout': 30,
        'retries': 10,
        'fragment_retries': 10,
        'skip_unavailable_fragments': True,
        'source_address': '0.0.0.0',
    }
    
    @classmethod
    def get_options(cls, method: int = 0) -> dict:
        """Get YT-DLP options dengan berbagai method"""
        opts = cls.BASE_OPTS.copy()
        
        # Rotate user agent
        opts['http_headers'] = {
            'User-Agent': cls.USER_AGENTS[method % len(cls.USER_AGENTS)],
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        }
        
        # Different extractor configurations
        if method == 0:
            # Method 1: Android client (most reliable)
            opts['extractor_args'] = {
                'youtube': {
                    'player_client': ['android_music', 'android', 'web'],
                    'player_skip': ['webpage', 'configs'],
                }
            }
        elif method == 1:
            # Method 2: iOS client
            opts['extractor_args'] = {
                'youtube': {
                    'player_client': ['ios', 'android'],
                    'player_skip': ['webpage'],
                }
            }
        elif method == 2:
            # Method 3: TV embedded
            opts['extractor_args'] = {
                'youtube': {
                    'player_client': ['tv_embedded', 'android'],
                }
            }
        elif method == 3:
            # Method 4: Web client dengan oauth
            opts['extractor_args'] = {
                'youtube': {
                    'player_client': ['web', 'android_music'],
                }
            }
        else:
            # Method 5: Mweb client
            opts['extractor_args'] = {
                'youtube': {
                    'player_client': ['mweb', 'android'],
                }
            }
        
        return opts


# FFMPEG Options
FFMPEG_OPTS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin',
    'options': '-vn -b:a 192k'
}


class Song:
    """Representasi sebuah lagu"""
    def __init__(self, data: dict, requester):
        self.data = data
        self.requester = requester
        self.title = data.get('title', 'Unknown Title')
        self.url = data.get('webpage_url') or data.get('original_url') or data.get('url', '')
        self.stream_url = data.get('url', '')
        self.thumbnail = data.get('thumbnail', '')
        self.duration = data.get('duration', 0)
        self.uploader = data.get('uploader') or data.get('channel', 'Unknown')
    
    @property
    def duration_str(self) -> str:
        if not self.duration:
            return "🔴 LIVE"
        m, s = divmod(int(self.duration), 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
    
    def create_source(self) -> discord.FFmpegOpusAudio:
        return discord.FFmpegOpusAudio(self.stream_url, **FFMPEG_OPTS)


class GuildMusicPlayer:
    """Player untuk setiap server"""
    def __init__(self):
        self.queue: deque = deque()
        self.current: Optional[Song] = None
        self.loop: bool = False
        self.loop_queue: bool = False
        self.text_channel = None


class Music(commands.Cog):
    """🎵 Music Commands"""
    
    def __init__(self, bot):
        self.bot = bot
        self.players: Dict[int, GuildMusicPlayer] = {}
        logger.info("🎵 Music Cog initialized")
    
    def get_player(self, guild_id: int) -> GuildMusicPlayer:
        if guild_id not in self.players:
            self.players[guild_id] = GuildMusicPlayer()
        return self.players[guild_id]
    
    # ═══════════════════════════════════════════════════════════
    # CORE: YouTube Search dengan Multiple Methods
    # ═══════════════════════════════════════════════════════════
    
    async def extract_info(self, query: str) -> Optional[dict]:
        """
        Extract info dari YouTube dengan multiple fallback methods
        """
        loop = asyncio.get_event_loop()
        
        # Normalize query
        query = query.strip()
        
        # Cek apakah URL atau search
        is_url = bool(re.match(r'https?://', query))
        
        # Jika bukan URL, tambahkan ytsearch
        if not is_url:
            search_query = f"ytsearch:{query}"
        else:
            search_query = query
            # Extract video ID jika YouTube URL
            video_id = self._extract_video_id(query)
            if video_id:
                # Gunakan format URL yang paling reliable
                search_query = f"https://www.youtube.com/watch?v={video_id}"
        
        logger.info(f"🔍 Searching: {search_query[:50]}...")
        
        # Coba berbagai method
        last_error = None
        for method in range(5):
            try:
                logger.info(f"  → Trying method {method + 1}/5...")
                
                opts = YTDLSource.get_options(method)
                ytdl = yt_dlp.YoutubeDL(opts)
                
                # Extract info
                data = await loop.run_in_executor(
                    None,
                    lambda: ytdl.extract_info(search_query, download=False)
                )
                
                if not data:
                    logger.warning(f"  → Method {method + 1}: No data returned")
                    continue
                
                # Handle search results / playlist
                if 'entries' in data:
                    entries = [e for e in data['entries'] if e is not None]
                    if not entries:
                        logger.warning(f"  → Method {method + 1}: Empty entries")
                        continue
                    data = entries[0]
                
                # Validasi: harus ada URL stream
                stream_url = data.get('url')
                if not stream_url:
                    # Coba ambil dari formats
                    formats = data.get('formats', [])
                    for f in formats:
                        if f.get('acodec') != 'none' and f.get('url'):
                            data['url'] = f['url']
                            stream_url = f['url']
                            break
                
                if not stream_url:
                    logger.warning(f"  → Method {method + 1}: No stream URL")
                    continue
                
                logger.info(f"  ✅ Method {method + 1} SUCCESS: {data.get('title', 'Unknown')[:40]}")
                return data
                
            except yt_dlp.utils.DownloadError as e:
                error_str = str(e).lower()
                last_error = str(e)
                
                if 'private' in error_str:
                    logger.error("  ❌ Video is private")
                    return None
                elif 'removed' in error_str or 'deleted' in error_str:
                    logger.error("  ❌ Video was removed")
                    return None
                elif 'copyright' in error_str:
                    logger.error("  ❌ Video blocked due to copyright")
                    return None
                else:
                    logger.warning(f"  → Method {method + 1} failed: {str(e)[:50]}")
                
            except Exception as e:
                last_error = str(e)
                logger.warning(f"  → Method {method + 1} error: {str(e)[:50]}")
            
            # Wait sebelum retry
            await asyncio.sleep(0.5)
        
        logger.error(f"❌ All methods failed. Last error: {last_error[:100] if last_error else 'Unknown'}")
        return None
    
    def _extract_video_id(self, url: str) -> Optional[str]:
        """Extract YouTube video ID dari URL"""
        patterns = [
            r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/|youtube\.com\/v\/|youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})',
            r'(?:music\.youtube\.com\/watch\?v=)([a-zA-Z0-9_-]{11})',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        # Fallback: cek query parameter
        try:
            parsed = urllib.parse.urlparse(url)
            params = urllib.parse.parse_qs(parsed.query)
            if 'v' in params:
                return params['v'][0]
        except:
            pass
        
        return None
    
    # ═══════════════════════════════════════════════════════════
    # PLAYBACK FUNCTIONS
    # ═══════════════════════════════════════════════════════════
    
    async def play_next(self, ctx_or_guild):
        """Play lagu berikutnya"""
        # Get guild
        if isinstance(ctx_or_guild, commands.Context):
            guild = ctx_or_guild.guild
        else:
            guild = ctx_or_guild
        
        player = self.get_player(guild.id)
        voice_client = guild.voice_client
        
        if not voice_client or not voice_client.is_connected():
            return
        
        # Get next song
        if player.loop and player.current:
            next_song = player.current
        elif player.queue:
            if player.loop_queue and player.current:
                player.queue.append(player.current)
            next_song = player.queue.popleft()
        else:
            player.current = None
            if player.text_channel:
                try:
                    await player.text_channel.send("📭 **Queue kosong.** Gunakan `!play` untuk menambah lagu.")
                except:
                    pass
            return
        
        # Re-fetch stream URL (karena bisa expire)
        logger.info(f"🎵 Playing: {next_song.title}")
        
        try:
            # Fetch fresh data
            fresh_data = await self.extract_info(next_song.url or next_song.title)
            
            if not fresh_data:
                if player.text_channel:
                    await player.text_channel.send(f"⚠️ **Skip:** Gagal memutar `{next_song.title}`")
                await self.play_next(guild)
                return
            
            # Update song dengan fresh data
            next_song = Song(fresh_data, next_song.requester)
            player.current = next_song
            
            # Create source dan play
            source = next_song.create_source()
            
            def after_playing(error):
                if error:
                    logger.error(f"Playback error: {error}")
                # Schedule next song
                asyncio.run_coroutine_threadsafe(
                    self.play_next(guild),
                    self.bot.loop
                )
            
            voice_client.play(source, after=after_playing)
            
            # Send now playing embed
            if player.text_channel:
                embed = discord.Embed(
                    title="🎵 Now Playing",
                    description=f"**[{next_song.title}]({next_song.url})**",
                    color=discord.Color.green()
                )
                embed.add_field(name="⏱️ Duration", value=next_song.duration_str, inline=True)
                embed.add_field(name="🎤 Channel", value=next_song.uploader[:20], inline=True)
                embed.add_field(name="👤 Requested by", value=next_song.requester.mention, inline=True)
                
                if next_song.thumbnail:
                    embed.set_thumbnail(url=next_song.thumbnail)
                
                if player.loop:
                    embed.set_footer(text="🔂 Loop: ON")
                elif player.loop_queue:
                    embed.set_footer(text="🔁 Loop Queue: ON")
                
                try:
                    await player.text_channel.send(embed=embed)
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"Error playing song: {e}")
            if player.text_channel:
                try:
                    await player.text_channel.send(f"❌ **Error:** {str(e)[:100]}")
                except:
                    pass
            await self.play_next(guild)
    
    # ═══════════════════════════════════════════════════════════
    # COMMANDS
    # ═══════════════════════════════════════════════════════════
    
    @commands.command(name='play', aliases=['p', 'putar'])
    async def play(self, ctx: commands.Context, *, query: str):
        """▶️ Putar lagu dari YouTube"""
        
        # Cek voice channel
        if not ctx.author.voice:
            return await ctx.send("❌ **Kamu harus di voice channel!**")
        
        voice_channel = ctx.author.voice.channel
        
        # Connect ke voice channel
        if not ctx.voice_client:
            try:
                await voice_channel.connect(self_deaf=True)
                logger.info(f"✅ Connected to {voice_channel.name}")
            except Exception as e:
                return await ctx.send(f"❌ **Gagal connect:** {e}")
        elif ctx.voice_client.channel != voice_channel:
            await ctx.voice_client.move_to(voice_channel)
        
        # Get player
        player = self.get_player(ctx.guild.id)
        player.text_channel = ctx.channel
        
        # Send searching message
        search_embed = discord.Embed(
            title="🔍 Mencari...",
            description=f"`{query[:100]}`",
            color=discord.Color.blue()
        )
        msg = await ctx.send(embed=search_embed)
        
        # Search
        try:
            data = await self.extract_info(query)
            
            if not data:
                error_embed = discord.Embed(
                    title="❌ Tidak Ditemukan",
                    description=f"Tidak dapat menemukan: `{query[:50]}`",
                    color=discord.Color.red()
                )
                error_embed.add_field(
                    name="💡 Coba:",
                    value=(
                        "• Ketik judul lagu lebih spesifik\n"
                        "• Pastikan video tidak private\n"
                        "• Gunakan `!test <url>` untuk debug"
                    ),
                    inline=False
                )
                await msg.edit(embed=error_embed)
                return
            
            # Create song
            song = Song(data, ctx.author)
            
            # Add to queue
            player.queue.append(song)
            
            # Update message
            if ctx.voice_client.is_playing() or player.current:
                queue_embed = discord.Embed(
                    title="📝 Ditambahkan ke Queue",
                    description=f"**[{song.title}]({song.url})**",
                    color=discord.Color.blue()
                )
                queue_embed.add_field(name="⏱️ Duration", value=song.duration_str, inline=True)
                queue_embed.add_field(name="📊 Position", value=f"#{len(player.queue)}", inline=True)
                if song.thumbnail:
                    queue_embed.set_thumbnail(url=song.thumbnail)
                await msg.edit(embed=queue_embed)
            else:
                await msg.delete()
                await self.play_next(ctx)
                
        except Exception as e:
            logger.error(f"Play command error: {e}")
            await msg.edit(embed=discord.Embed(
                title="❌ Error",
                description=str(e)[:200],
                color=discord.Color.red()
            ))
    
    @commands.command(name='test', aliases=['debug', 'check'])
    async def test_url(self, ctx: commands.Context, *, query: str):
        """🔧 Test apakah URL/query bisa diputar"""
        
        embed = discord.Embed(
            title="🔧 Testing...",
            description=f"`{query[:100]}`",
            color=discord.Color.blue()
        )
        msg = await ctx.send(embed=embed)
        
        results = []
        
        # Check if URL
        video_id = self._extract_video_id(query)
        if video_id:
            results.append(f"✅ YouTube URL detected")
            results.append(f"📎 Video ID: `{video_id}`")
        else:
            results.append(f"📝 Search query detected")
        
        results.append("\n**Testing extraction methods...**\n")
        
        # Test each method
        loop = asyncio.get_event_loop()
        success = False
        
        for method in range(5):
            try:
                opts = YTDLSource.get_options(method)
                ytdl = yt_dlp.YoutubeDL(opts)
                
                search_q = query if video_id else f"ytsearch:{query}"
                
                data = await loop.run_in_executor(
                    None,
                    lambda q=search_q: ytdl.extract_info(q, download=False)
                )
                
                if data:
                    if 'entries' in data:
                        data = data['entries'][0] if data['entries'] else None
                    
                    if data and data.get('url'):
                        results.append(f"✅ **Method {method + 1}:** SUCCESS")
                        results.append(f"   📺 `{data.get('title', 'N/A')[:40]}`")
                        results.append(f"   ⏱️ Duration: {data.get('duration', 'N/A')}s")
                        success = True
                        break
                    else:
                        results.append(f"⚠️ **Method {method + 1}:** No stream URL")
                else:
                    results.append(f"⚠️ **Method {method + 1}:** No data")
                    
            except Exception as e:
                err = str(e)[:50]
                results.append(f"❌ **Method {method + 1}:** {err}")
        
        # Final result
        if success:
            results.appe

#!/usr/bin/env python3
"""
Spotify Playlist Analyzer

Scans a Spotify user's public playlists and generates a beautiful report
of most frequently appearing songs, favorite albums, and top artists.

With --self flag, authenticates as the user to access private listening data
including top tracks and artists over different time periods.
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

# Rich imports for beautiful CLI output
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    from rich.text import Text
    from rich.columns import Columns
    from rich import box
    from rich.style import Style
    from rich.markdown import Markdown
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

try:
    import spotipy
    from spotipy.oauth2 import SpotifyClientCredentials, SpotifyOAuth
except ImportError:
    print("Error: spotipy not installed. Run: pip install spotipy")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv is optional


# Initialize Rich console
console = Console() if RICH_AVAILABLE else None


# Keywords that suggest a playlist contains the user's favorites
FAVORITES_KEYWORDS = [
    "favorite", "favourit", "best", "top", "loved", "likes", "all time",
    "essential", "perfect", "goat", "greatest", "classic", "forever"
]


# Styles for different fan levels
FAN_LEVEL_STYLES = {
    "SUPER FAN": Style(color="bright_green", bold=True),
    "Big Fan": Style(color="green"),
    "Fan": Style(color="yellow"),
    "Casual": Style(color="white", dim=True),
}

# Time range descriptions for self-analysis
TIME_RANGE_LABELS = {
    "short_term": "Last 4 Weeks",
    "medium_term": "Last 6 Months", 
    "long_term": "All Time",
}


def is_favorites_playlist(name: str) -> bool:
    """Check if a playlist name suggests it contains favorites."""
    name_lower = name.lower()
    return any(kw in name_lower for kw in FAVORITES_KEYWORDS)


def parse_horizon(horizon_str: str) -> datetime:
    """Parse a horizon string like '1y', '6m', '30d' into a cutoff datetime.
    
    Supported formats:
    - Ny: N years ago (e.g., '1y', '2y')
    - Nm: N months ago (e.g., '6m', '12m')
    - Nd: N days ago (e.g., '30d', '90d')
    """
    match = re.match(r'^(\d+)([ymd])$', horizon_str.lower().strip())
    if not match:
        raise ValueError(
            f"Invalid horizon format: '{horizon_str}'. "
            "Use format like '1y' (1 year), '6m' (6 months), '30d' (30 days)"
        )
    
    value = int(match.group(1))
    unit = match.group(2)
    
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    
    if unit == 'y':
        cutoff = now - timedelta(days=value * 365)
    elif unit == 'm':
        cutoff = now - timedelta(days=value * 30)
    elif unit == 'd':
        cutoff = now - timedelta(days=value)
    else:
        raise ValueError(f"Unknown time unit: {unit}")
    
    return cutoff


@dataclass
class TrackInfo:
    """Stores information about a track and which playlists contain it."""
    track_id: str
    name: str
    artists: list[str]
    artist_ids: list[str]
    album: str
    album_id: str
    spotify_url: str
    playlists: list[str] = field(default_factory=list)
    in_favorites_playlist: bool = False
    
    @property
    def count(self) -> int:
        return len(self.playlists)
    
    @property
    def artists_str(self) -> str:
        return ", ".join(self.artists)
    
    @property
    def favorites_weight(self) -> int:
        """Score that weights appearances in favorites playlists higher."""
        base = self.count
        if self.in_favorites_playlist:
            base += 2  # Bonus for being in a favorites playlist
        return base


@dataclass
class AlbumStats:
    """Aggregated statistics for an album."""
    album_id: str
    name: str
    artist: str
    tracks: list[str] = field(default_factory=list)
    total_appearances: int = 0


@dataclass 
class ArtistStats:
    """Aggregated statistics for an artist."""
    artist_id: str
    name: str
    unique_tracks: int = 0
    total_appearances: int = 0
    tracks: list[str] = field(default_factory=list)
    
    @property
    def fan_level(self) -> str:
        """Categorize fan dedication level."""
        if self.unique_tracks >= 15:
            return "SUPER FAN"
        elif self.unique_tracks >= 8:
            return "Big Fan"
        elif self.unique_tracks >= 4:
            return "Fan"
        else:
            return "Casual"


@dataclass
class TopTrack:
    """A track from the user's top tracks."""
    rank: int
    name: str
    artists: list[str]
    album: str
    spotify_url: str
    
    @property
    def artists_str(self) -> str:
        return ", ".join(self.artists)


@dataclass
class TopArtist:
    """An artist from the user's top artists."""
    rank: int
    name: str
    genres: list[str]
    popularity: int
    spotify_url: str
    
    @property
    def genres_str(self) -> str:
        return ", ".join(self.genres[:3]) if self.genres else "No genres"


class SpotifyAnalyzer:
    """Analyzes a Spotify user's public playlists."""
    
    def __init__(self, horizon_cutoff: Optional[datetime] = None, use_oauth: bool = False):
        client_id = os.getenv("SPOTIPY_CLIENT_ID")
        client_secret = os.getenv("SPOTIPY_CLIENT_SECRET")
        
        if not client_id or not client_secret:
            if console:
                console.print("[bold red]Error:[/] Missing Spotify credentials.")
                console.print("Set [cyan]SPOTIPY_CLIENT_ID[/] and [cyan]SPOTIPY_CLIENT_SECRET[/] environment variables.")
                console.print("Get credentials at: [link]https://developer.spotify.com/dashboard[/link]")
            else:
                print("Error: Missing Spotify credentials.")
                print("Set SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET environment variables.")
            sys.exit(1)
        
        self.use_oauth = use_oauth
        
        if use_oauth:
            # OAuth flow for self-analysis (opens browser)
            redirect_uri = os.getenv("SPOTIPY_REDIRECT_URI", "http://localhost:8000/callback")
            auth_manager = SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scope="user-top-read",
                open_browser=True,
            )
            if console and RICH_AVAILABLE:
                console.print("[dim]Opening browser for Spotify authentication...[/]")
        else:
            # Client credentials for public data only
            auth_manager = SpotifyClientCredentials(
                client_id=client_id,
                client_secret=client_secret
            )
        
        self.sp = spotipy.Spotify(auth_manager=auth_manager)
        self.tracks: dict[str, TrackInfo] = {}
        self.playlist_names: list[str] = []
        self.horizon_cutoff = horizon_cutoff
        self.tracks_filtered = 0  # Count of tracks filtered out by horizon
    
    def get_current_user_info(self) -> dict:
        """Fetch the authenticated user's profile information."""
        try:
            user = self.sp.current_user()
            return {
                "id": user["id"],
                "display_name": user.get("display_name", user["id"]),
                "followers": user.get("followers", {}).get("total", 0),
                "profile_url": user.get("external_urls", {}).get("spotify", ""),
                "email": user.get("email", ""),
                "country": user.get("country", ""),
                "product": user.get("product", "free"),  # premium, free, etc.
            }
        except spotipy.SpotifyException as e:
            if console:
                console.print(f"[bold red]Error fetching user info:[/] {e}")
            else:
                print(f"Error fetching user info: {e}")
            sys.exit(1)
    
    def get_user_info(self, user_id: str) -> dict:
        """Fetch user profile information."""
        try:
            user = self.sp.user(user_id)
            return {
                "id": user["id"],
                "display_name": user.get("display_name", user["id"]),
                "followers": user.get("followers", {}).get("total", 0),
                "profile_url": user.get("external_urls", {}).get("spotify", ""),
            }
        except spotipy.SpotifyException as e:
            if console:
                console.print(f"[bold red]Error fetching user info:[/] {e}")
            else:
                print(f"Error fetching user info: {e}")
            sys.exit(1)
    
    def get_user_playlists(self, user_id: str) -> list[dict]:
        """Fetch all public playlists for a user."""
        playlists = []
        offset = 0
        limit = 50
        
        while True:
            try:
                results = self.sp.user_playlists(user_id, limit=limit, offset=offset)
            except spotipy.SpotifyException as e:
                if console:
                    console.print(f"[yellow]Warning:[/] Error fetching playlists: {e}")
                break
            
            if not results["items"]:
                break
            
            for playlist in results["items"]:
                if playlist and playlist.get("public", False):
                    playlists.append({
                        "id": playlist["id"],
                        "name": playlist["name"],
                        "track_count": playlist.get("tracks", {}).get("total", 0),
                        "owner": playlist.get("owner", {}).get("id", ""),
                        "is_favorites": is_favorites_playlist(playlist["name"]),
                    })
            
            if results["next"] is None:
                break
            
            offset += limit
        
        return playlists
    
    def get_playlist_tracks(self, playlist_id: str, playlist_name: str, is_favorites: bool) -> None:
        """Fetch all tracks from a playlist and add to aggregate."""
        offset = 0
        limit = 100
        
        while True:
            try:
                results = self.sp.playlist_tracks(
                    playlist_id,
                    limit=limit,
                    offset=offset,
                    # Include added_at for time horizon filtering
                    fields="items(added_at,track(id,name,artists(id,name),album(id,name),external_urls)),next"
                )
            except spotipy.SpotifyException:
                break  # Silently skip problematic playlists during progress
            
            if not results.get("items"):
                break
            
            for item in results["items"]:
                track = item.get("track")
                if not track or not track.get("id"):
                    continue  # Skip local files or unavailable tracks
                
                # Check if track is within the time horizon
                if self.horizon_cutoff:
                    added_at_str = item.get("added_at")
                    if added_at_str:
                        try:
                            # Parse ISO format timestamp (e.g., "2023-01-15T12:30:00Z")
                            added_at = datetime.fromisoformat(added_at_str.replace('Z', '+00:00'))
                            added_at = added_at.replace(tzinfo=None)  # Make naive for comparison
                            if added_at < self.horizon_cutoff:
                                self.tracks_filtered += 1
                                continue  # Skip tracks outside the horizon
                        except ValueError:
                            pass  # If parsing fails, include the track
                
                track_id = track["id"]
                
                if track_id in self.tracks:
                    # Track already seen, add this playlist to its list
                    if playlist_name not in self.tracks[track_id].playlists:
                        self.tracks[track_id].playlists.append(playlist_name)
                    if is_favorites:
                        self.tracks[track_id].in_favorites_playlist = True
                else:
                    # New track
                    artists = [a["name"] for a in track.get("artists", [])]
                    artist_ids = [a["id"] for a in track.get("artists", []) if a.get("id")]
                    album_data = track.get("album", {})
                    album = album_data.get("name", "Unknown Album")
                    album_id = album_data.get("id", "")
                    spotify_url = track.get("external_urls", {}).get("spotify", "")
                    
                    self.tracks[track_id] = TrackInfo(
                        track_id=track_id,
                        name=track["name"],
                        artists=artists,
                        artist_ids=artist_ids,
                        album=album,
                        album_id=album_id,
                        spotify_url=spotify_url,
                        playlists=[playlist_name],
                        in_favorites_playlist=is_favorites
                    )
            
            if results.get("next") is None:
                break
            
            offset += limit
    
    def get_top_tracks(self, time_range: str = "medium_term", limit: int = 20) -> list[TopTrack]:
        """Fetch user's top tracks for a given time range.
        
        time_range: short_term (4 weeks), medium_term (6 months), long_term (years)
        """
        try:
            results = self.sp.current_user_top_tracks(time_range=time_range, limit=limit)
            tracks = []
            for i, item in enumerate(results.get("items", []), 1):
                tracks.append(TopTrack(
                    rank=i,
                    name=item["name"],
                    artists=[a["name"] for a in item.get("artists", [])],
                    album=item.get("album", {}).get("name", "Unknown Album"),
                    spotify_url=item.get("external_urls", {}).get("spotify", ""),
                ))
            return tracks
        except spotipy.SpotifyException as e:
            if console:
                console.print(f"[yellow]Warning:[/] Could not fetch top tracks: {e}")
            return []
    
    def get_top_artists(self, time_range: str = "medium_term", limit: int = 20) -> list[TopArtist]:
        """Fetch user's top artists for a given time range.
        
        time_range: short_term (4 weeks), medium_term (6 months), long_term (years)
        """
        try:
            results = self.sp.current_user_top_artists(time_range=time_range, limit=limit)
            artists = []
            for i, item in enumerate(results.get("items", []), 1):
                artists.append(TopArtist(
                    rank=i,
                    name=item["name"],
                    genres=item.get("genres", []),
                    popularity=item.get("popularity", 0),
                    spotify_url=item.get("external_urls", {}).get("spotify", ""),
                ))
            return artists
        except spotipy.SpotifyException as e:
            if console:
                console.print(f"[yellow]Warning:[/] Could not fetch top artists: {e}")
            return []
    
    def aggregate_albums(self) -> list[AlbumStats]:
        """Aggregate track data by album."""
        albums: dict[str, AlbumStats] = {}
        
        for track in self.tracks.values():
            if not track.album_id:
                continue
            
            if track.album_id not in albums:
                albums[track.album_id] = AlbumStats(
                    album_id=track.album_id,
                    name=track.album,
                    artist=track.artists[0] if track.artists else "Unknown"
                )
            
            album = albums[track.album_id]
            if track.name not in album.tracks:
                album.tracks.append(track.name)
            album.total_appearances += track.count
        
        # Sort by number of unique tracks, then by total appearances
        sorted_albums = sorted(
            albums.values(),
            key=lambda a: (-len(a.tracks), -a.total_appearances)
        )
        
        return sorted_albums
    
    def aggregate_artists(self) -> list[ArtistStats]:
        """Aggregate track data by artist."""
        artists: dict[str, ArtistStats] = {}
        
        for track in self.tracks.values():
            for i, artist_id in enumerate(track.artist_ids):
                if not artist_id:
                    continue
                
                artist_name = track.artists[i] if i < len(track.artists) else "Unknown"
                
                if artist_id not in artists:
                    artists[artist_id] = ArtistStats(
                        artist_id=artist_id,
                        name=artist_name
                    )
                
                artist = artists[artist_id]
                if track.name not in artist.tracks:
                    artist.tracks.append(track.name)
                    artist.unique_tracks += 1
                artist.total_appearances += track.count
        
        # Sort by unique tracks, then by total appearances
        sorted_artists = sorted(
            artists.values(),
            key=lambda a: (-a.unique_tracks, -a.total_appearances)
        )
        
        return sorted_artists
    
    def get_likely_favorites(self) -> list[TrackInfo]:
        """Get tracks most likely to be all-time favorites."""
        # Tracks that appear in multiple playlists AND/OR in a favorites playlist
        candidates = [
            t for t in self.tracks.values()
            if t.count > 1 or t.in_favorites_playlist
        ]
        
        # Sort by weighted score
        return sorted(
            candidates,
            key=lambda t: (-t.favorites_weight, -t.count, t.name.lower())
        )
    
    def analyze_self(self) -> dict:
        """Analyze the authenticated user's listening data."""
        user_info = self.get_current_user_info()
        
        if console and RICH_AVAILABLE:
            console.print(f"[green]✓[/] Authenticated as: [cyan]{user_info['display_name']}[/]\n")
            console.print("[dim]Fetching your top tracks and artists...[/]")
        
        # Fetch top tracks for all time ranges
        top_tracks = {}
        top_artists = {}
        
        for time_range in ["short_term", "medium_term", "long_term"]:
            top_tracks[time_range] = self.get_top_tracks(time_range=time_range, limit=20)
            top_artists[time_range] = self.get_top_artists(time_range=time_range, limit=20)
        
        # Analyze listening trends (compare short vs long term)
        trends = self._analyze_trends(top_tracks, top_artists)
        
        return {
            "user": user_info,
            "is_self_analysis": True,
            "top_tracks": top_tracks,
            "top_artists": top_artists,
            "trends": trends,
        }
    
    def _analyze_trends(self, top_tracks: dict, top_artists: dict) -> dict:
        """Analyze listening trends by comparing time ranges."""
        trends = {
            "rising_artists": [],
            "consistent_favorites": [],
            "new_discoveries": [],
        }
        
        # Get artist names for each time range
        short_artists = {a.name for a in top_artists.get("short_term", [])}
        long_artists = {a.name for a in top_artists.get("long_term", [])}
        
        # Rising artists: in short-term but not long-term (or ranked much higher)
        for artist in top_artists.get("short_term", [])[:10]:
            if artist.name not in long_artists:
                trends["rising_artists"].append(artist.name)
        
        # Consistent favorites: in both short and long term top 10
        short_top10 = {a.name for a in top_artists.get("short_term", [])[:10]}
        long_top10 = {a.name for a in top_artists.get("long_term", [])[:10]}
        trends["consistent_favorites"] = list(short_top10 & long_top10)
        
        # New discoveries: tracks in short-term that aren't in long-term
        short_tracks = {t.name for t in top_tracks.get("short_term", [])}
        long_tracks = {t.name for t in top_tracks.get("long_term", [])}
        trends["new_discoveries"] = list(short_tracks - long_tracks)[:5]
        
        return trends
    
    def analyze_user(self, user_id: str) -> dict:
        """Analyze all public playlists for a user."""
        user_info = self.get_user_info(user_id)
        playlists = self.get_user_playlists(user_id)
        
        favorites_playlists = [p for p in playlists if p["is_favorites"]]
        
        if console and RICH_AVAILABLE:
            # Use Rich progress bar
            console.print()
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(bar_width=40),
                TaskProgressColumn(),
                TextColumn("[cyan]{task.fields[current]}[/]"),
                console=console,
            ) as progress:
                task = progress.add_task(
                    f"[green]Scanning {len(playlists)} playlists...",
                    total=len(playlists),
                    current=""
                )
                
                for i, playlist in enumerate(playlists, 1):
                    marker = " ⭐" if playlist["is_favorites"] else ""
                    progress.update(task, current=f"{playlist['name'][:30]}{marker}")
                    self.get_playlist_tracks(playlist["id"], playlist["name"], playlist["is_favorites"])
                    self.playlist_names.append(playlist["name"])
                    progress.advance(task)
            
            console.print()
            
            # Show filtered count if horizon was applied
            if self.horizon_cutoff and self.tracks_filtered > 0:
                console.print(f"[dim]⏱️  Filtered out {self.tracks_filtered:,} tracks outside time horizon[/]\n")
        else:
            # Fallback to plain output
            print(f"Found {len(playlists)} public playlists")
            for i, playlist in enumerate(playlists, 1):
                print(f"  [{i}/{len(playlists)}] {playlist['name']}")
                self.get_playlist_tracks(playlist["id"], playlist["name"], playlist["is_favorites"])
                self.playlist_names.append(playlist["name"])
            
            if self.horizon_cutoff and self.tracks_filtered > 0:
                print(f"\nFiltered out {self.tracks_filtered:,} tracks outside time horizon")
        
        # Sort tracks by frequency (number of playlists they appear in)
        sorted_tracks = sorted(
            self.tracks.values(),
            key=lambda t: (-t.count, t.name.lower())
        )
        
        # Aggregate data
        albums = self.aggregate_albums()
        artists = self.aggregate_artists()
        likely_favorites = self.get_likely_favorites()
        
        return {
            "user": user_info,
            "is_self_analysis": False,
            "total_playlists": len(playlists),
            "favorites_playlists": [p["name"] for p in favorites_playlists],
            "total_unique_tracks": len(self.tracks),
            "tracks_filtered": self.tracks_filtered,
            "horizon_cutoff": self.horizon_cutoff.isoformat() if self.horizon_cutoff else None,
            "tracks": sorted_tracks,
            "albums": albums,
            "artists": artists,
            "likely_favorites": likely_favorites,
        }


def print_self_report_rich(analysis: dict, top_n: int = 20) -> None:
    """Print a beautifully formatted self-analysis report using Rich."""
    user = analysis["user"]
    
    # ===== HEADER =====
    console.print()
    
    account_type = "Premium" if user.get("product") == "premium" else "Free"
    header_content = f"""[bold cyan]{user['display_name']}[/]
[dim]{user['profile_url']}[/]

[white]Account:[/] [green]{account_type}[/]
[white]Country:[/] [green]{user.get('country', 'Unknown')}[/]
[white]Followers:[/] [green]{user['followers']:,}[/]"""
    
    console.print(Panel(
        header_content,
        title="[bold white]🎧 YOUR SPOTIFY LISTENING ANALYSIS[/]",
        subtitle="[dim]Based on your actual listening history[/]",
        border_style="bright_magenta",
        padding=(1, 2),
    ))
    
    # ===== TOP TRACKS BY TIME RANGE =====
    for time_range in ["short_term", "medium_term", "long_term"]:
        tracks = analysis["top_tracks"].get(time_range, [])
        label = TIME_RANGE_LABELS[time_range]
        
        if time_range == "short_term":
            icon = "🔥"
            color = "red"
        elif time_range == "medium_term":
            icon = "💜"
            color = "magenta"
        else:
            icon = "👑"
            color = "yellow"
        
        console.print(Panel(
            f"[bold]Your most played tracks - {label}[/]",
            title=f"[bold {color}]{icon} TOP TRACKS ({label.upper()})[/]",
            border_style=color,
        ))
        
        if tracks:
            track_table = Table(box=box.ROUNDED, show_header=True, header_style=f"bold {color}")
            track_table.add_column("#", style="dim", width=4, justify="right")
            track_table.add_column("Track", style="white", max_width=35)
            track_table.add_column("Artist", style="cyan", max_width=25)
            track_table.add_column("Album", style="dim", max_width=25)
            
            for track in tracks[:top_n]:
                track_table.add_row(
                    str(track.rank),
                    track.name[:35],
                    track.artists_str[:25],
                    track.album[:25],
                )
            
            console.print(track_table)
        else:
            console.print("[dim]No data available.[/]")
        
        console.print()
    
    # ===== TOP ARTISTS BY TIME RANGE =====
    for time_range in ["short_term", "medium_term", "long_term"]:
        artists = analysis["top_artists"].get(time_range, [])
        label = TIME_RANGE_LABELS[time_range]
        
        if time_range == "short_term":
            icon = "🔥"
            color = "red"
        elif time_range == "medium_term":
            icon = "💜"
            color = "magenta"
        else:
            icon = "👑"
            color = "yellow"
        
        console.print(Panel(
            f"[bold]Your most listened artists - {label}[/]",
            title=f"[bold {color}]{icon} TOP ARTISTS ({label.upper()})[/]",
            border_style=color,
        ))
        
        if artists:
            artist_table = Table(box=box.ROUNDED, show_header=True, header_style=f"bold {color}")
            artist_table.add_column("#", style="dim", width=4, justify="right")
            artist_table.add_column("Artist", style="white", max_width=25)
            artist_table.add_column("Genres", style="cyan", max_width=35)
            artist_table.add_column("Popularity", justify="right", width=12)
            
            for artist in artists[:top_n]:
                # Create popularity bar
                pop_bar = "█" * (artist.popularity // 10) + "░" * (10 - artist.popularity // 10)
                
                artist_table.add_row(
                    str(artist.rank),
                    artist.name[:25],
                    artist.genres_str[:35],
                    f"{pop_bar} {artist.popularity}",
                )
            
            console.print(artist_table)
        else:
            console.print("[dim]No data available.[/]")
        
        console.print()
    
    # ===== LISTENING TRENDS =====
    trends = analysis.get("trends", {})
    
    console.print(Panel(
        "[bold]How your taste is evolving[/]",
        title="[bold green]📈 LISTENING TRENDS[/]",
        border_style="green",
    ))
    
    # Rising artists
    rising = trends.get("rising_artists", [])
    if rising:
        console.print(f"[bold green]🚀 Rising Artists[/] (new in your recent rotation):")
        console.print(f"   [cyan]{', '.join(rising[:5])}[/]\n")
    
    # Consistent favorites
    consistent = trends.get("consistent_favorites", [])
    if consistent:
        console.print(f"[bold yellow]💛 Consistent Favorites[/] (always in your top 10):")
        console.print(f"   [cyan]{', '.join(consistent[:5])}[/]\n")
    
    # New discoveries
    discoveries = trends.get("new_discoveries", [])
    if discoveries:
        console.print(f"[bold magenta]✨ Recent Discoveries[/] (new tracks you're loving):")
        console.print(f"   [cyan]{', '.join(discoveries[:5])}[/]\n")
    
    if not rising and not consistent and not discoveries:
        console.print("[dim]Not enough data to analyze trends yet.[/]\n")
    
    # ===== FOOTER =====
    console.print(Panel(
        "[dim]This analysis is based on your actual Spotify listening history[/]",
        title="[bold white]✅ ANALYSIS COMPLETE[/]",
        border_style="bright_black",
    ))
    console.print()


def print_self_report_plain(analysis: dict, top_n: int = 20) -> None:
    """Print a plain text self-analysis report."""
    user = analysis["user"]
    
    print("\n" + "=" * 70)
    print("YOUR SPOTIFY LISTENING ANALYSIS")
    print("=" * 70)
    
    print(f"\nUser: {user['display_name']}")
    print(f"Account: {user.get('product', 'free').title()}")
    
    for time_range in ["short_term", "medium_term", "long_term"]:
        label = TIME_RANGE_LABELS[time_range]
        
        print(f"\n" + "-" * 70)
        print(f"TOP TRACKS - {label.upper()}")
        print("-" * 70)
        
        tracks = analysis["top_tracks"].get(time_range, [])
        for track in tracks[:top_n]:
            print(f"{track.rank:3}. {track.name} - {track.artists_str}")
        
        print(f"\n" + "-" * 70)
        print(f"TOP ARTISTS - {label.upper()}")
        print("-" * 70)
        
        artists = analysis["top_artists"].get(time_range, [])
        for artist in artists[:top_n]:
            print(f"{artist.rank:3}. {artist.name} ({artist.genres_str})")
    
    print("\n" + "=" * 70)
    print("END OF REPORT")
    print("=" * 70)


def print_report_rich(analysis: dict, top_n: int = 50) -> None:
    """Print a beautifully formatted report using Rich."""
    user = analysis["user"]
    
    # ===== HEADER =====
    console.print()
    
    # Build header content with optional horizon info
    horizon_line = ""
    if analysis.get("horizon_cutoff"):
        cutoff_date = datetime.fromisoformat(analysis["horizon_cutoff"]).strftime("%Y-%m-%d")
        horizon_line = f"\n[white]Time Horizon:[/] [yellow]Since {cutoff_date}[/]"
        if analysis.get("tracks_filtered", 0) > 0:
            horizon_line += f" [dim]({analysis['tracks_filtered']:,} older tracks filtered)[/]"
    
    header_content = f"""[bold cyan]{user['display_name']}[/]
[dim]{user['profile_url']}[/]

[white]Followers:[/] [green]{user['followers']:,}[/]
[white]Public Playlists:[/] [green]{analysis['total_playlists']}[/]
[white]Unique Tracks:[/] [green]{analysis['total_unique_tracks']:,}[/]{horizon_line}"""
    
    console.print(Panel(
        header_content,
        title="[bold white]🎵 SPOTIFY PLAYLIST ANALYSIS[/]",
        subtitle=f"[dim]Analyzed {analysis['total_playlists']} playlists[/]",
        border_style="bright_green",
        padding=(1, 2),
    ))
    
    # Show detected favorites playlists
    if analysis["favorites_playlists"]:
        fav_text = ", ".join(analysis["favorites_playlists"][:5])
        if len(analysis["favorites_playlists"]) > 5:
            fav_text += f" (+{len(analysis['favorites_playlists']) - 5} more)"
        console.print(f"[dim]⭐ Detected favorites playlists: {fav_text}[/]\n")
    
    # ===== LIKELY ALL-TIME FAVORITES =====
    console.print(Panel(
        "[bold]Songs in multiple playlists or in 'favorites' playlists[/]",
        title="[bold yellow]⭐ LIKELY ALL-TIME FAVORITES[/]",
        border_style="yellow",
    ))
    
    likely_favorites = analysis["likely_favorites"][:top_n]
    
    if likely_favorites:
        fav_table = Table(box=box.ROUNDED, show_header=True, header_style="bold magenta")
        fav_table.add_column("#", style="dim", width=4, justify="right")
        fav_table.add_column("Song", style="white", max_width=35)
        fav_table.add_column("Artist", style="cyan", max_width=25)
        fav_table.add_column("Album", style="dim", max_width=25)
        fav_table.add_column("📋", justify="center", width=4)
        fav_table.add_column("⭐", justify="center", width=3)
        
        for i, track in enumerate(likely_favorites[:15], 1):
            fav_marker = "⭐" if track.in_favorites_playlist else ""
            fav_table.add_row(
                str(i),
                track.name[:35],
                track.artists_str[:25],
                track.album[:25],
                str(track.count),
                fav_marker,
            )
        
        console.print(fav_table)
    else:
        console.print("[dim]No clear favorites detected.[/]")
    
    console.print()
    
    # ===== FAVORITE ALBUMS =====
    console.print(Panel(
        "[bold]Albums with the most tracks added across playlists[/]",
        title="[bold magenta]💿 FAVORITE ALBUMS[/]",
        border_style="magenta",
    ))
    
    albums = analysis["albums"][:20]
    multi_track_albums = [a for a in albums if len(a.tracks) > 1]
    
    if multi_track_albums:
        album_table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
        album_table.add_column("#", style="dim", width=4, justify="right")
        album_table.add_column("Album", style="magenta", max_width=30)
        album_table.add_column("Artist", style="white", max_width=20)
        album_table.add_column("Tracks", justify="right", width=8)
        album_table.add_column("Appearances", justify="right", width=12)
        album_table.add_column("Sample Tracks", style="dim", max_width=40)
        
        for i, album in enumerate(multi_track_albums[:15], 1):
            sample = ", ".join(album.tracks[:2])
            if len(album.tracks) > 2:
                sample += f" (+{len(album.tracks) - 2})"
            
            album_table.add_row(
                str(i),
                album.name[:30],
                album.artist[:20],
                str(len(album.tracks)),
                str(album.total_appearances),
                sample[:40],
            )
        
        console.print(album_table)
    else:
        console.print("[dim]No albums with multiple tracks found.[/]")
    
    console.print()
    
    # ===== TOP ARTISTS =====
    console.print(Panel(
        "[bold]Artists ranked by track count with dedication level[/]",
        title="[bold green]🎤 TOP ARTISTS BY DEDICATION[/]",
        border_style="green",
    ))
    
    artists = analysis["artists"][:20]
    
    if artists:
        artist_table = Table(box=box.ROUNDED, show_header=True, header_style="bold yellow")
        artist_table.add_column("#", style="dim", width=4, justify="right")
        artist_table.add_column("Artist", style="white", max_width=25)
        artist_table.add_column("Fan Level", width=12, justify="center")
        artist_table.add_column("Tracks", justify="right", width=8)
        artist_table.add_column("Appearances", justify="right", width=12)
        
        for i, artist in enumerate(artists[:15], 1):
            # Style the fan level
            level_style = FAN_LEVEL_STYLES.get(artist.fan_level, Style())
            level_text = Text(artist.fan_level, style=level_style)
            
            artist_table.add_row(
                str(i),
                artist.name[:25],
                level_text,
                str(artist.unique_tracks),
                str(artist.total_appearances),
            )
        
        console.print(artist_table)
    
    console.print()
    
    # ===== TOP SONGS BY FREQUENCY =====
    console.print(Panel(
        "[bold]Songs appearing in the most playlists[/]",
        title="[bold cyan]🔁 TOP SONGS BY PLAYLIST FREQUENCY[/]",
        border_style="cyan",
    ))
    
    tracks = analysis["tracks"][:top_n]
    multi_playlist_tracks = [t for t in tracks if t.count > 1]
    
    if multi_playlist_tracks:
        track_table = Table(box=box.ROUNDED, show_header=True, header_style="bold green")
        track_table.add_column("#", style="dim", width=4, justify="right")
        track_table.add_column("Song", style="white", max_width=30)
        track_table.add_column("Artist", style="cyan", max_width=20)
        track_table.add_column("In Playlists", justify="right", width=12)
        track_table.add_column("Playlists", style="dim", max_width=40)
        
        for i, track in enumerate(multi_playlist_tracks[:15], 1):
            playlists_preview = ", ".join(track.playlists[:2])
            if len(track.playlists) > 2:
                playlists_preview += f" (+{len(track.playlists) - 2})"
            
            track_table.add_row(
                str(i),
                track.name[:30],
                track.artists_str[:20],
                str(track.count),
                playlists_preview[:40],
            )
        
        console.print(track_table)
    else:
        console.print("[dim]No songs appear in multiple playlists.[/]")
        
        # Show single-playlist tracks
        single_table = Table(box=box.SIMPLE, show_header=True, header_style="dim")
        single_table.add_column("#", width=4)
        single_table.add_column("Song")
        single_table.add_column("Artist")
        
        for i, track in enumerate(tracks[:10], 1):
            single_table.add_row(str(i), track.name[:40], track.artists_str[:30])
        
        console.print("[dim]Most common tracks (1 playlist each):[/]")
        console.print(single_table)
    
    console.print()
    
    # ===== FOOTER =====
    footer_text = f"[dim]Analyzed [green]{analysis['total_unique_tracks']:,}[/] unique tracks across [green]{analysis['total_playlists']}[/] playlists[/]"
    if analysis.get("tracks_filtered", 0) > 0:
        footer_text += f"\n[dim]({analysis['tracks_filtered']:,} tracks filtered by time horizon)[/]"
    
    console.print(Panel(
        footer_text,
        title="[bold white]✅ ANALYSIS COMPLETE[/]",
        border_style="bright_black",
    ))
    console.print()


def print_report_plain(analysis: dict, top_n: int = 50) -> None:
    """Print a plain text report (fallback when Rich is not available)."""
    user = analysis["user"]
    
    print("\n" + "=" * 70)
    print("SPOTIFY PLAYLIST ANALYSIS REPORT")
    print("=" * 70)
    
    print(f"\nUser: {user['display_name']}")
    print(f"Profile: {user['profile_url']}")
    print(f"Followers: {user['followers']:,}")
    print(f"\nTotal Public Playlists: {analysis['total_playlists']}")
    print(f"Total Unique Tracks: {analysis['total_unique_tracks']:,}")
    
    if analysis.get("horizon_cutoff"):
        cutoff_date = datetime.fromisoformat(analysis["horizon_cutoff"]).strftime("%Y-%m-%d")
        print(f"Time Horizon: Since {cutoff_date}")
        if analysis.get("tracks_filtered", 0) > 0:
            print(f"  ({analysis['tracks_filtered']:,} older tracks filtered)")
    
    if analysis["favorites_playlists"]:
        print(f"\nDetected 'Favorites' Playlists:")
        for name in analysis["favorites_playlists"][:5]:
            print(f"  - {name}")
    
    # Favorites
    print("\n" + "-" * 70)
    print("LIKELY ALL-TIME FAVORITES")
    print("-" * 70)
    
    for i, track in enumerate(analysis["likely_favorites"][:15], 1):
        marker = " [FAV]" if track.in_favorites_playlist else ""
        print(f"{i:3}. {track.name}{marker} - {track.artists_str}")
    
    # Albums
    print("\n" + "-" * 70)
    print("FAVORITE ALBUMS")
    print("-" * 70)
    
    multi_albums = [a for a in analysis["albums"][:20] if len(a.tracks) > 1]
    for i, album in enumerate(multi_albums[:15], 1):
        print(f"{i:3}. {album.name} - {album.artist} ({len(album.tracks)} tracks)")
    
    # Artists
    print("\n" + "-" * 70)
    print("TOP ARTISTS")
    print("-" * 70)
    
    for i, artist in enumerate(analysis["artists"][:15], 1):
        level = f" [{artist.fan_level}]" if artist.fan_level != "Casual" else ""
        print(f"{i:3}. {artist.name}{level} ({artist.unique_tracks} tracks)")
    
    print("\n" + "=" * 70)
    print("END OF REPORT")
    print("=" * 70)


def print_report(analysis: dict, top_n: int = 50) -> None:
    """Print a formatted report to console."""
    is_self = analysis.get("is_self_analysis", False)
    
    if RICH_AVAILABLE and console:
        if is_self:
            print_self_report_rich(analysis, top_n)
        else:
            print_report_rich(analysis, top_n)
    else:
        if is_self:
            print_self_report_plain(analysis, top_n)
        else:
            print_report_plain(analysis, top_n)


def export_to_json(analysis: dict, filepath: str) -> None:
    """Export analysis results to a JSON file."""
    is_self = analysis.get("is_self_analysis", False)
    
    if is_self:
        # Self-analysis export format
        export_data = {
            "user": analysis["user"],
            "is_self_analysis": True,
            "top_tracks": {
                time_range: [
                    {
                        "rank": t.rank,
                        "name": t.name,
                        "artists": t.artists,
                        "album": t.album,
                        "spotify_url": t.spotify_url,
                    }
                    for t in tracks
                ]
                for time_range, tracks in analysis["top_tracks"].items()
            },
            "top_artists": {
                time_range: [
                    {
                        "rank": a.rank,
                        "name": a.name,
                        "genres": a.genres,
                        "popularity": a.popularity,
                        "spotify_url": a.spotify_url,
                    }
                    for a in artists
                ]
                for time_range, artists in analysis["top_artists"].items()
            },
            "trends": analysis.get("trends", {}),
        }
    else:
        # Standard playlist analysis export format
        export_data = {
            "user": analysis["user"],
            "is_self_analysis": False,
            "total_playlists": analysis["total_playlists"],
            "favorites_playlists": analysis["favorites_playlists"],
            "total_unique_tracks": analysis["total_unique_tracks"],
            "horizon_cutoff": analysis.get("horizon_cutoff"),
            "tracks_filtered": analysis.get("tracks_filtered", 0),
            "likely_favorites": [
                {
                    "rank": i,
                    "name": t.name,
                    "artists": t.artists,
                    "album": t.album,
                    "spotify_url": t.spotify_url,
                    "playlist_count": t.count,
                    "in_favorites_playlist": t.in_favorites_playlist,
                    "favorites_score": t.favorites_weight,
                    "playlists": t.playlists,
                }
                for i, t in enumerate(analysis["likely_favorites"][:100], 1)
            ],
            "favorite_albums": [
                {
                    "rank": i,
                    "name": a.name,
                    "artist": a.artist,
                    "track_count": len(a.tracks),
                    "total_appearances": a.total_appearances,
                    "tracks": a.tracks,
                }
                for i, a in enumerate(analysis["albums"][:50], 1)
                if len(a.tracks) > 1
            ],
            "top_artists": [
                {
                    "rank": i,
                    "name": a.name,
                    "unique_tracks": a.unique_tracks,
                    "total_appearances": a.total_appearances,
                    "fan_level": a.fan_level,
                    "tracks": a.tracks,
                }
                for i, a in enumerate(analysis["artists"][:50], 1)
            ],
            "all_tracks": [
                {
                    "rank": i,
                    "name": t.name,
                    "artists": t.artists,
                    "album": t.album,
                    "spotify_url": t.spotify_url,
                    "playlist_count": t.count,
                    "playlists": t.playlists,
                }
                for i, t in enumerate(analysis["tracks"], 1)
            ]
        }
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(export_data, f, indent=2, ensure_ascii=False)
    
    if console:
        console.print(f"\n[green]✓[/] Results exported to: [cyan]{filepath}[/]")
    else:
        print(f"\nResults exported to: {filepath}")


def main():
    parser = argparse.ArgumentParser(
        description="Analyze a Spotify user's public playlists to find favorite songs, albums, and artists.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s 1234567890                    # Analyze another user's public playlists
  %(prog)s 1234567890 --top 20           # Show top 20 items per category
  %(prog)s 1234567890 --output report.json
  %(prog)s 1234567890 --horizon 1y       # Only tracks added in the last year
  %(prog)s --self                        # Analyze YOUR listening history (requires login)
  %(prog)s --self --output my_stats.json

Environment Variables:
  SPOTIPY_CLIENT_ID      Your Spotify app client ID
  SPOTIPY_CLIENT_SECRET  Your Spotify app client secret
  SPOTIPY_REDIRECT_URI   Redirect URI for OAuth (default: http://localhost:8080/callback)

Get credentials at: https://developer.spotify.com/dashboard

Note: For --self mode, add http://localhost:8080/callback as a Redirect URI in your Spotify app settings.
        """
    )
    
    parser.add_argument(
        "user_id",
        nargs="?",
        help="Spotify user ID to analyze (e.g., '1234567890'). Not required with --self."
    )
    parser.add_argument(
        "--self",
        action="store_true",
        dest="self_mode",
        help="Analyze your own listening history (opens browser for authentication)"
    )
    parser.add_argument(
        "--top", "-t",
        type=int,
        default=50,
        metavar="N",
        help="Show top N items per category (default: 50)"
    )
    parser.add_argument(
        "--output", "-o",
        metavar="FILE",
        help="Export results to JSON file"
    )
    parser.add_argument(
        "--horizon",
        metavar="PERIOD",
        help="Only include tracks added within this time period (e.g., '1y', '6m', '30d'). Not used with --self."
    )
    
    args = parser.parse_args()
    
    # Validate arguments
    if not args.self_mode and not args.user_id:
        parser.error("Either provide a user_id or use --self flag")
    
    if args.self_mode:
        # Self-analysis mode using OAuth
        if console and RICH_AVAILABLE:
            console.print(Panel(
                "[bold green]Self-Analysis Mode[/]\n[dim]Analyzing your personal Spotify listening data[/]",
                title="[bold white]🎧 Spotify Playlist Analyzer[/]",
                border_style="bright_magenta",
            ))
        
        analyzer = SpotifyAnalyzer(use_oauth=True)
        analysis = analyzer.analyze_self()
    else:
        # Standard playlist analysis mode
        user_id = args.user_id
        if "spotify.com/user/" in user_id:
            user_id = user_id.split("spotify.com/user/")[-1].split("?")[0].strip("/")
        
        # Parse time horizon if provided
        horizon_cutoff = None
        if args.horizon:
            try:
                horizon_cutoff = parse_horizon(args.horizon)
            except ValueError as e:
                if console and RICH_AVAILABLE:
                    console.print(f"[bold red]Error:[/] {e}")
                else:
                    print(f"Error: {e}")
                sys.exit(1)
        
        # Show welcome banner
        if console and RICH_AVAILABLE:
            horizon_info = ""
            if horizon_cutoff:
                horizon_info = f"\n[dim]Time horizon: Since {horizon_cutoff.strftime('%Y-%m-%d')}[/]"
            
            console.print(Panel(
                f"[bold green]Analyzing user:[/] [cyan]{user_id}[/]{horizon_info}",
                title="[bold white]🎵 Spotify Playlist Analyzer[/]",
                border_style="bright_blue",
            ))
        
        analyzer = SpotifyAnalyzer(horizon_cutoff=horizon_cutoff)
        analysis = analyzer.analyze_user(user_id)
    
    print_report(analysis, top_n=args.top)
    
    if args.output:
        export_to_json(analysis, args.output)


if __name__ == "__main__":
    main()

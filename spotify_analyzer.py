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
from pathlib import Path
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

# Active playlist threshold: playlists with additions in the last N days are "active"
ACTIVE_PLAYLIST_RECENCY_DAYS = 365 * 2  # 6 months


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

# Cache configuration
CACHE_DIR = Path(__file__).parent / ".spotify_cache"
DEFAULT_CACHE_TTL_HOURS = 24  # Default cache expiration


def get_cache_path(user_id: str) -> Path:
    """Get the cache file path for a given user ID."""
    # Sanitize user ID for filesystem
    safe_id = re.sub(r'[^\w\-]', '_', user_id)
    return CACHE_DIR / f"{safe_id}.json"


def load_cache(user_id: str) -> Optional[dict]:
    """Load cached data for a user if it exists and is not expired."""
    cache_path = get_cache_path(user_id)
    
    if not cache_path.exists():
        return None
    
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cached = json.load(f)
        
        # Check if cache is expired
        cached_at = datetime.fromisoformat(cached.get("cached_at", "1970-01-01T00:00:00"))
        ttl_hours = cached.get("ttl_hours", DEFAULT_CACHE_TTL_HOURS)
        
        if datetime.now() - cached_at > timedelta(hours=ttl_hours):
            if console and RICH_AVAILABLE:
                console.print(f"[dim]Cache expired for user {user_id}[/]")
            return None
        
        return cached
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        if console and RICH_AVAILABLE:
            console.print(f"[yellow]Warning:[/] Could not load cache: {e}")
        return None


def save_cache(user_id: str, data: dict, ttl_hours: int = DEFAULT_CACHE_TTL_HOURS) -> None:
    """Save data to cache for a user."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = get_cache_path(user_id)
    
    cache_data = {
        "cached_at": datetime.now().isoformat(),
        "ttl_hours": ttl_hours,
        "user_id": user_id,
        **data
    }
    
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2, ensure_ascii=False)
        
        if console and RICH_AVAILABLE:
            console.print(f"[dim]💾 Cached data for user {user_id}[/]")
    except OSError as e:
        if console and RICH_AVAILABLE:
            console.print(f"[yellow]Warning:[/] Could not save cache: {e}")


def clear_cache(user_id: Optional[str] = None) -> None:
    """Clear cache for a specific user or all users."""
    if user_id:
        cache_path = get_cache_path(user_id)
        if cache_path.exists():
            cache_path.unlink()
            if console and RICH_AVAILABLE:
                console.print(f"[green]✓[/] Cleared cache for user {user_id}")
    else:
        if CACHE_DIR.exists():
            for cache_file in CACHE_DIR.glob("*.json"):
                cache_file.unlink()
            if console and RICH_AVAILABLE:
                console.print("[green]✓[/] Cleared all cached data")


def is_favorites_playlist(name: str) -> bool:
    """Check if a playlist name suggests it contains favorites."""
    name_lower = name.lower()
    return any(kw in name_lower for kw in FAVORITES_KEYWORDS)


def classify_playlist_activity(name: str, track_count: int, 
                                newest_add: Optional[datetime] = None) -> tuple[bool, str]:
    """Classify playlist as active rotation vs archive based on recency.
    
    A playlist is considered "active" if it has had tracks added within
    the recency threshold (default 6 months). This is a simple, reliable
    heuristic that doesn't depend on naming conventions.
    
    Returns:
        tuple of (is_active: bool, reason: str)
    """
    # Purely recency-based: if playlist has recent additions, it's active
    if newest_add and newest_add > datetime.now() - timedelta(days=ACTIVE_PLAYLIST_RECENCY_DAYS):
        return True, "recent_additions"
    
    # No recent additions = archive/inactive
    return False, "no_recent_additions"


def get_newest_add_date(tracks: list[dict]) -> Optional[datetime]:
    """Get the most recent added_at date from a list of track items."""
    dates = []
    for item in tracks:
        added_at_str = item.get("added_at")
        if added_at_str:
            try:
                added_at = datetime.fromisoformat(added_at_str.replace('Z', '+00:00'))
                added_at = added_at.replace(tzinfo=None)
                dates.append(added_at)
            except ValueError:
                pass
    return max(dates) if dates else None


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
    popularity: Optional[int] = None
    duration_ms: Optional[int] = None
    release_date: Optional[str] = None
    release_date_precision: Optional[str] = None
    album_type: Optional[str] = None
    album_total_tracks: Optional[int] = None
    added_dates: dict = field(default_factory=dict)  # playlist_name -> datetime
    is_evergreen: bool = False  # Set by temporal analysis
    # Playlist metadata for scoring (set at analysis time, not per-track)
    playlist_sizes: dict = field(default_factory=dict)  # playlist_name -> track_count
    active_playlists: set = field(default_factory=set)  # set of active playlist names
    # Aggregate stats for affinity scoring (injected after all tracks processed)
    artist_track_counts: dict = field(default_factory=dict)  # artist_id -> unique_track_count
    album_track_counts: dict = field(default_factory=dict)   # album_id -> track_count_in_playlists
    
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
    
    @property
    def affinity_score(self) -> int:
        """Enhanced scoring that considers multiple signals of track affinity.
        
        Unlike versatility_score which rewards appearing in many playlists,
        affinity_score tries to identify tracks the user actually loves by
        combining artist dedication, album depth, playlist presence, and other signals.
        """
        score = 0
        
        # Playlist count (exponential scaling)
        if self.count >= 3:
            score += 35
        elif self.count >= 2:
            score += 20
        else:
            score += 10
        
        if self.in_favorites_playlist:
            score += 25
        
        # Cross-context: favorites + multiple playlists = strong signal
        if self.in_favorites_playlist and self.count >= 2:
            score += 10
        
        # Artist dedication bonus
        max_artist_tracks = 0
        for artist_id in self.artist_ids:
            if artist_id and artist_id in self.artist_track_counts:
                max_artist_tracks = max(max_artist_tracks, self.artist_track_counts[artist_id])
        
        if max_artist_tracks >= 20:
            score += 10
        elif max_artist_tracks >= 15:
            score += 8
        elif max_artist_tracks >= 10:
            score += 6
        elif max_artist_tracks >= 6:
            score += 4
        elif max_artist_tracks >= 3:
            score += 2
        
        # Album depth bonus
        album_tracks = self.album_track_counts.get(self.album_id, 0) if self.album_id else 0
        if album_tracks >= 5:
            score += 15
        elif album_tracks >= 3:
            score += 8
        
        # Obscurity bonus / popularity penalty
        if self.popularity is not None:
            if self.popularity < 30:
                score += 8
            elif self.popularity < 50:
                score += 4
            elif self.popularity >= 85:
                score -= 8
            elif self.popularity >= 75:
                score -= 4
        
        # Recency bonus
        if self.latest_added:
            days_ago = (datetime.now() - self.latest_added).days
            if days_ago < 180:
                score += 10
            elif days_ago < 365:
                score += 5
        
        # Early adopter bonus
        if self.added_dates and self.release_date:
            try:
                if self.release_date_precision == "day":
                    release_dt = datetime.strptime(self.release_date, "%Y-%m-%d")
                elif self.release_date_precision == "month":
                    release_dt = datetime.strptime(self.release_date + "-01", "%Y-%m-%d")
                else:
                    release_dt = datetime.strptime(self.release_date + "-01-01", "%Y-%m-%d")
                
                earliest_add = min(self.added_dates.values()) if self.added_dates else None
                if earliest_add:
                    days_after_release = (earliest_add - release_dt).days
                    if 0 <= days_after_release < 7:
                        score += 15
                    elif 0 <= days_after_release < 30:
                        score += 8
            except (ValueError, TypeError):
                pass
        
        if self.is_evergreen:
            score += 15
        
        # Small playlist bonus (focused curation)
        if self.playlist_sizes:
            for playlist_name in self.playlists:
                playlist_size = self.playlist_sizes.get(playlist_name, 100)
                if playlist_size < 30:
                    score += 12
                    break
                elif playlist_size < 50:
                    score += 6
                    break
        
        if self.active_playlists:
            active_count = sum(1 for p in self.playlists if p in self.active_playlists)
            score += active_count * 5
        
        return score
    
    @property
    def earliest_added(self) -> Optional[datetime]:
        """Get the earliest date this track was added to any playlist."""
        if self.added_dates:
            return min(self.added_dates.values())
        return None
    
    @property
    def latest_added(self) -> Optional[datetime]:
        """Get the latest date this track was added to any playlist."""
        if self.added_dates:
            return max(self.added_dates.values())
        return None
    
    @property
    def versatility_score(self) -> int:
        """Score measuring how many contexts this track fits (high = universal appeal).
        
        Unlike affinity_score which tries to identify actual favorites,
        versatility_score measures how well a track fits different contexts.
        A high versatility score means the track appears in many playlists
        and is globally popular - a "crowd pleaser" that works everywhere.
        """
        score = self.count * 10  # Base: raw playlist count
        
        # Bonus for high global popularity (mainstream appeal)
        if self.popularity is not None and self.popularity >= 60:
            score += 10
        elif self.popularity is not None and self.popularity >= 40:
            score += 5
        
        # Bonus for appearing in diverse playlist types
        # Detected by keyword variety in playlist names
        if len(self.playlists) >= 2:
            playlist_keywords = set()
            keyword_categories = {
                "mood": ["chill", "relax", "happy", "sad", "angry", "hype", "calm"],
                "activity": ["workout", "gym", "drive", "work", "study", "sleep", "party"],
                "time": ["morning", "night", "evening", "summer", "winter"],
            }
            for playlist in self.playlists:
                pl_lower = playlist.lower()
                for category, keywords in keyword_categories.items():
                    if any(kw in pl_lower for kw in keywords):
                        playlist_keywords.add(category)
            
            # Bonus for appearing in diverse contexts
            score += len(playlist_keywords) * 5
        
        return score


@dataclass
class AlbumStats:
    """Aggregated statistics for an album."""
    album_id: str
    name: str
    artist: str
    tracks: list[str] = field(default_factory=list)
    total_appearances: int = 0
    total_tracks_in_album: Optional[int] = None
    album_type: Optional[str] = None
    release_date: Optional[str] = None
    
    @property
    def completion_ratio(self) -> float:
        """Ratio of album tracks in user's playlists."""
        if self.total_tracks_in_album and self.total_tracks_in_album > 0:
            return len(self.tracks) / self.total_tracks_in_album
        return 0.0
    
    @property
    def is_likely_favorite_album(self) -> bool:
        """Album is likely a favorite if >50% of tracks are playlisted and at least 3 tracks."""
        return self.completion_ratio > 0.5 and len(self.tracks) >= 3
    
    @property
    def completion_percentage(self) -> int:
        """Completion ratio as a percentage for display."""
        return int(self.completion_ratio * 100)


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
    
    def __init__(
        self,
        horizon_cutoff: Optional[datetime] = None,
        use_oauth: bool = False,
        use_cache: bool = True,
        refresh_cache: bool = False,
        cache_ttl_hours: int = DEFAULT_CACHE_TTL_HOURS,
    ):
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
        self.use_cache = use_cache
        self.refresh_cache = refresh_cache
        self.cache_ttl_hours = cache_ttl_hours
        
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
        self.tracks_missing_added_at = 0  # Count of tracks with no added_at date
        self.playlists_skipped_owner = 0  # Count of playlists not owned by target user
    
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
                    })
            
            if results["next"] is None:
                break
            
            offset += limit
        
        return playlists
    
    def fetch_all_playlist_tracks_raw(self, playlists: list[dict]) -> dict[str, list[dict]]:
        """Fetch all tracks from all playlists and return raw data for caching."""
        all_tracks: dict[str, list[dict]] = {}
        
        if console and RICH_AVAILABLE:
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
                    f"[green]Fetching tracks from {len(playlists)} playlists...",
                    total=len(playlists),
                    current=""
                )
                
                for playlist in playlists:
                    marker = " ⭐" if is_favorites_playlist(playlist["name"]) else ""
                    progress.update(task, current=f"{playlist['name'][:30]}{marker}")
                    
                    tracks = self._fetch_playlist_tracks_raw(playlist["id"])
                    all_tracks[playlist["id"]] = tracks
                    
                    progress.advance(task)
            console.print()
        else:
            print(f"Fetching tracks from {len(playlists)} playlists")
            for i, playlist in enumerate(playlists, 1):
                print(f"  [{i}/{len(playlists)}] {playlist['name']}")
                tracks = self._fetch_playlist_tracks_raw(playlist["id"])
                all_tracks[playlist["id"]] = tracks
        
        return all_tracks
    
    def _fetch_playlist_tracks_raw(self, playlist_id: str) -> list[dict]:
        """Fetch all tracks from a single playlist as raw data."""
        tracks = []
        offset = 0
        limit = 100
        
        while True:
            try:
                results = self.sp.playlist_tracks(
                    playlist_id,
                    limit=limit,
                    offset=offset,
                    fields="items(added_at,added_by.id,is_local,track(id,name,popularity,duration_ms,explicit,disc_number,track_number,artists(id,name),album(id,name,album_type,release_date,release_date_precision,total_tracks),external_urls)),next"
                )
            except spotipy.SpotifyException:
                break
            
            if not results.get("items"):
                break
            
            for item in results["items"]:
                track = item.get("track")
                if track and track.get("id"):
                    album_data = track.get("album", {})
                    tracks.append({
                        "added_at": item.get("added_at"),
                        "added_by_id": item.get("added_by", {}).get("id"),
                        "is_local": item.get("is_local", False),
                        "track": {
                            "id": track["id"],
                            "name": track["name"],
                            "popularity": track.get("popularity"),
                            "duration_ms": track.get("duration_ms"),
                            "explicit": track.get("explicit"),
                            "disc_number": track.get("disc_number"),
                            "track_number": track.get("track_number"),
                            "artists": [{"id": a.get("id"), "name": a["name"]} for a in track.get("artists", [])],
                            "album": {
                                "id": album_data.get("id", ""),
                                "name": album_data.get("name", "Unknown Album"),
                                "album_type": album_data.get("album_type"),
                                "release_date": album_data.get("release_date"),
                                "release_date_precision": album_data.get("release_date_precision"),
                                "total_tracks": album_data.get("total_tracks"),
                            },
                            "external_urls": track.get("external_urls", {}),
                        }
                    })
            
            if results.get("next") is None:
                break
            
            offset += limit
        
        return tracks
    
    def fetch_raw_data(self, user_id: str) -> dict:
        """Fetch all raw Spotify data for a user (playlists + tracks)."""
        user_info = self.get_user_info(user_id)
        playlists = self.get_user_playlists(user_id)
        playlist_tracks = self.fetch_all_playlist_tracks_raw(playlists)
        
        return {
            "user_info": user_info,
            "playlists": playlists,
            "playlist_tracks": playlist_tracks,
        }
    
    def fetch_raw_self_data(self) -> dict:
        """Fetch all raw Spotify data for the authenticated user."""
        user_info = self.get_current_user_info()
        
        if console and RICH_AVAILABLE:
            console.print("[dim]Fetching your top tracks and artists...[/]")
        
        top_tracks_raw = {}
        top_artists_raw = {}
        
        for time_range in ["short_term", "medium_term", "long_term"]:
            try:
                tracks_result = self.sp.current_user_top_tracks(time_range=time_range, limit=20)
                top_tracks_raw[time_range] = tracks_result.get("items", [])
            except spotipy.SpotifyException:
                top_tracks_raw[time_range] = []
            
            try:
                artists_result = self.sp.current_user_top_artists(time_range=time_range, limit=20)
                top_artists_raw[time_range] = artists_result.get("items", [])
            except spotipy.SpotifyException:
                top_artists_raw[time_range] = []
        
        return {
            "user_info": user_info,
            "top_tracks_raw": top_tracks_raw,
            "top_artists_raw": top_artists_raw,
        }
    
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
                    if not added_at_str:
                        self.tracks_missing_added_at += 1
                        continue  # Exclude tracks with no added_at when horizon is set
                    try:
                        # Parse ISO format timestamp (e.g., "2023-01-15T12:30:00Z")
                        added_at = datetime.fromisoformat(added_at_str.replace('Z', '+00:00'))
                        added_at = added_at.replace(tzinfo=None)  # Make naive for comparison
                        if added_at < self.horizon_cutoff:
                            self.tracks_filtered += 1
                            continue  # Skip tracks outside the horizon
                    except ValueError:
                        self.tracks_missing_added_at += 1
                        continue  # Exclude tracks with unparseable added_at
                
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
                    artist=track.artists[0] if track.artists else "Unknown",
                    total_tracks_in_album=track.album_total_tracks,
                    album_type=track.album_type,
                    release_date=track.release_date,
                )
            
            album = albums[track.album_id]
            if track.name not in album.tracks:
                album.tracks.append(track.name)
            album.total_appearances += track.count
            
            # Update total_tracks_in_album if we have it from this track
            # (in case first track didn't have it but later ones do)
            if track.album_total_tracks and not album.total_tracks_in_album:
                album.total_tracks_in_album = track.album_total_tracks
        
        # Sort by completion ratio (for albums with known totals), then by unique tracks
        sorted_albums = sorted(
            albums.values(),
            key=lambda a: (-a.completion_ratio, -len(a.tracks), -a.total_appearances)
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
        
        # Sort by affinity score (enhanced scoring)
        return sorted(
            candidates,
            key=lambda t: (-t.affinity_score, -t.count, t.name.lower())
        )
    
    def analyze_temporal_patterns(self) -> dict:
        """Analyze temporal patterns to identify evergreen favorites and early adopter behavior.
        
        Returns a dict with:
        - evergreen_track_ids: list of track IDs that were re-added over 6+ months apart
        - early_adopter_tracks: list of track IDs added within first week of release
        - first_month_tracks: list of track IDs added within first month of release
        """
        evergreen_track_ids = []
        early_adopter_tracks = []
        first_month_tracks = []
        
        for track_id, track in self.tracks.items():
            # Check for evergreen favorites: added to multiple playlists over long time span
            if len(track.added_dates) > 1:
                dates = list(track.added_dates.values())
                date_span = max(dates) - min(dates)
                if date_span.days >= 180:  # 6+ months apart
                    evergreen_track_ids.append(track_id)
                    track.is_evergreen = True
            
            # Check for early adopter behavior
            if track.release_date and track.added_dates:
                try:
                    # Parse release date
                    if track.release_date_precision == "day":
                        release_dt = datetime.strptime(track.release_date, "%Y-%m-%d")
                    elif track.release_date_precision == "month":
                        release_dt = datetime.strptime(track.release_date + "-01", "%Y-%m-%d")
                    else:  # year
                        release_dt = datetime.strptime(track.release_date + "-01-01", "%Y-%m-%d")
                    
                    earliest_add = min(track.added_dates.values())
                    days_after_release = (earliest_add - release_dt).days
                    
                    if 0 <= days_after_release < 7:
                        early_adopter_tracks.append(track_id)
                    elif 0 <= days_after_release < 30:
                        first_month_tracks.append(track_id)
                except (ValueError, TypeError):
                    pass
        
        return {
            "evergreen_track_ids": evergreen_track_ids,
            "early_adopter_tracks": early_adopter_tracks,
            "first_month_tracks": first_month_tracks,
            "evergreen_count": len(evergreen_track_ids),
            "early_adopter_count": len(early_adopter_tracks),
            "first_month_count": len(first_month_tracks),
        }
    
    def _process_raw_self_data(self, raw_data: dict) -> tuple[dict, dict]:
        """Process raw cached self data into TopTrack/TopArtist objects."""
        top_tracks = {}
        top_artists = {}
        
        for time_range in ["short_term", "medium_term", "long_term"]:
            # Process tracks
            raw_tracks = raw_data.get("top_tracks_raw", {}).get(time_range, [])
            tracks = []
            for i, item in enumerate(raw_tracks, 1):
                tracks.append(TopTrack(
                    rank=i,
                    name=item["name"],
                    artists=[a["name"] for a in item.get("artists", [])],
                    album=item.get("album", {}).get("name", "Unknown Album"),
                    spotify_url=item.get("external_urls", {}).get("spotify", ""),
                ))
            top_tracks[time_range] = tracks
            
            # Process artists
            raw_artists = raw_data.get("top_artists_raw", {}).get(time_range, [])
            artists = []
            for i, item in enumerate(raw_artists, 1):
                artists.append(TopArtist(
                    rank=i,
                    name=item["name"],
                    genres=item.get("genres", []),
                    popularity=item.get("popularity", 0),
                    spotify_url=item.get("external_urls", {}).get("spotify", ""),
                ))
            top_artists[time_range] = artists
        
        return top_tracks, top_artists
    
    def analyze_self(self) -> dict:
        """Analyze the authenticated user's listening data."""
        # For self-analysis, we first need to authenticate to get the user ID
        # Then we can check the cache
        raw_data = None
        from_cache = False
        user_id = None
        
        # First, authenticate and get user ID (needed for cache key)
        # This is a lightweight call that we always make
        try:
            user_info = self.get_current_user_info()
            user_id = f"self_{user_info['id']}"  # Prefix with 'self_' to distinguish from public analysis
        except Exception:
            # If we can't get user info, we can't use cache either
            pass
        
        if console and RICH_AVAILABLE:
            console.print(f"[green]✓[/] Authenticated as: [cyan]{user_info['display_name']}[/]\n")
        
        # Try to load from cache
        if user_id and self.use_cache and not self.refresh_cache:
            cached = load_cache(user_id)
            if cached:
                raw_data = cached
                from_cache = True
                if console and RICH_AVAILABLE:
                    cached_at = cached.get("cached_at", "unknown")
                    console.print(f"[green]✓[/] Using cached listening data (cached: {cached_at})\n")
                else:
                    print(f"Using cached listening data")
        
        # Fetch fresh data if not cached
        if raw_data is None:
            if self.refresh_cache and console and RICH_AVAILABLE:
                console.print("[dim]Refreshing cache...[/]")
            
            raw_data = self.fetch_raw_self_data()
            raw_data["user_info"] = user_info  # Add user info to raw data
            
            # Save to cache
            if user_id and self.use_cache:
                save_cache(user_id, raw_data, ttl_hours=self.cache_ttl_hours)
        
        # Process raw data
        user_info = raw_data["user_info"]
        
        if from_cache:
            if console and RICH_AVAILABLE:
                console.print("[dim]Processing cached listening data...[/]\n")
        
        top_tracks, top_artists = self._process_raw_self_data(raw_data)
        
        # Analyze listening trends (compare short vs long term)
        trends = self._analyze_trends(top_tracks, top_artists)
        
        return {
            "user": user_info,
            "is_self_analysis": True,
            "top_tracks": top_tracks,
            "top_artists": top_artists,
            "trends": trends,
            "from_cache": from_cache,
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
    
    def _process_raw_tracks(self, playlists: list[dict], playlist_tracks: dict[str, list[dict]], target_user_id: str) -> None:
        """Process raw cached track data into TrackInfo objects.
        
        Args:
            playlists: List of playlist metadata dicts
            playlist_tracks: Dict mapping playlist_id to list of track items
            target_user_id: Only process playlists owned by this user
        """
        # Filter to only playlists owned by target user
        owned_playlists = []
        for p in playlists:
            if p.get("owner") != target_user_id:
                self.playlists_skipped_owner += 1
                continue
            owned_playlists.append(p)
        
        # Build playlist metadata maps for scoring (only from owned playlists)
        playlist_sizes = {p["name"]: p.get("track_count", 0) for p in owned_playlists}
        active_playlists = set()
        
        for p in owned_playlists:
            # Get newest add date for this playlist to help classify activity
            newest_add = get_newest_add_date(playlist_tracks.get(p["id"], []))
            is_active, _ = classify_playlist_activity(
                p["name"], 
                p.get("track_count", 0), 
                newest_add
            )
            if is_active:
                active_playlists.add(p["name"])
        
        # Store for use in analysis output
        self._playlist_sizes = playlist_sizes
        self._active_playlists = active_playlists
        
        for playlist in owned_playlists:
            playlist_id = playlist["id"]
            playlist_name = playlist["name"]
            # Compute is_favorites at runtime (not cached) so logic changes apply to cached data
            is_favorites = is_favorites_playlist(playlist_name)
            
            tracks = playlist_tracks.get(playlist_id, [])
            
            for item in tracks:
                track = item.get("track")
                if not track or not track.get("id"):
                    continue
                
                # Skip local files (no useful Spotify metadata)
                if item.get("is_local", False):
                    continue
                
                # Parse added_at timestamp
                added_at_str = item.get("added_at")
                added_at = None
                if added_at_str:
                    try:
                        added_at = datetime.fromisoformat(added_at_str.replace('Z', '+00:00'))
                        added_at = added_at.replace(tzinfo=None)
                    except ValueError:
                        pass
                
                # Check if track is within the time horizon
                if self.horizon_cutoff:
                    if added_at is None:
                        self.tracks_missing_added_at += 1
                        continue  # Exclude tracks with no added_at when horizon is set
                    if added_at < self.horizon_cutoff:
                        self.tracks_filtered += 1
                        continue
                
                track_id = track["id"]
                
                if track_id in self.tracks:
                    # Track already seen, update with this playlist's info
                    if playlist_name not in self.tracks[track_id].playlists:
                        self.tracks[track_id].playlists.append(playlist_name)
                    if is_favorites:
                        self.tracks[track_id].in_favorites_playlist = True
                    # Add this playlist's added_at to the track's added_dates
                    if added_at:
                        self.tracks[track_id].added_dates[playlist_name] = added_at
                else:
                    # New track - extract all fields with backward compatibility
                    artists = [a["name"] for a in track.get("artists", [])]
                    artist_ids = [a["id"] for a in track.get("artists", []) if a.get("id")]
                    album_data = track.get("album", {})
                    album = album_data.get("name", "Unknown Album")
                    album_id = album_data.get("id", "")
                    spotify_url = track.get("external_urls", {}).get("spotify", "")
                    
                    # New fields (with defaults for backward compat with old cache)
                    popularity = track.get("popularity")
                    duration_ms = track.get("duration_ms")
                    release_date = album_data.get("release_date")
                    release_date_precision = album_data.get("release_date_precision")
                    album_type = album_data.get("album_type")
                    album_total_tracks = album_data.get("total_tracks")
                    
                    # Initialize added_dates dict
                    added_dates = {}
                    if added_at:
                        added_dates[playlist_name] = added_at
                    
                    self.tracks[track_id] = TrackInfo(
                        track_id=track_id,
                        name=track["name"],
                        artists=artists,
                        artist_ids=artist_ids,
                        album=album,
                        album_id=album_id,
                        spotify_url=spotify_url,
                        playlists=[playlist_name],
                        in_favorites_playlist=is_favorites,
                        popularity=popularity,
                        duration_ms=duration_ms,
                        release_date=release_date,
                        release_date_precision=release_date_precision,
                        album_type=album_type,
                        album_total_tracks=album_total_tracks,
                        added_dates=added_dates,
                        playlist_sizes=playlist_sizes,
                        active_playlists=active_playlists,
                    )
            
            self.playlist_names.append(playlist_name)
    
    def _inject_aggregate_stats(self) -> None:
        """Compute artist/album stats and inject into TrackInfo for affinity scoring.
        
        This must be called after _process_raw_tracks() and before get_likely_favorites()
        so that affinity_score has access to aggregate data.
        """
        # Build artist track counts (how many unique tracks per artist)
        artist_counts: dict[str, int] = defaultdict(int)
        for track in self.tracks.values():
            for artist_id in track.artist_ids:
                if artist_id:
                    artist_counts[artist_id] += 1
        
        # Build album track counts (how many tracks per album in user's playlists)
        album_counts: dict[str, int] = defaultdict(int)
        for track in self.tracks.values():
            if track.album_id:
                album_counts[track.album_id] += 1
        
        # Inject into each track for use in affinity_score
        artist_counts_dict = dict(artist_counts)
        album_counts_dict = dict(album_counts)
        for track in self.tracks.values():
            track.artist_track_counts = artist_counts_dict
            track.album_track_counts = album_counts_dict
    
    def analyze_user(self, user_id: str) -> dict:
        """Analyze all public playlists for a user."""
        raw_data = None
        from_cache = False
        
        # Try to load from cache
        if self.use_cache and not self.refresh_cache:
            cached = load_cache(user_id)
            if cached:
                raw_data = cached
                from_cache = True
                if console and RICH_AVAILABLE:
                    cached_at = cached.get("cached_at", "unknown")
                    console.print(f"[green]✓[/] Using cached data for user [cyan]{user_id}[/] (cached: {cached_at})\n")
                else:
                    print(f"Using cached data for user {user_id}")
        
        # Fetch fresh data if not cached
        if raw_data is None:
            if self.refresh_cache and console and RICH_AVAILABLE:
                console.print("[dim]Refreshing cache...[/]")
            
            raw_data = self.fetch_raw_data(user_id)
            
            # Save to cache
            if self.use_cache:
                save_cache(user_id, raw_data, ttl_hours=self.cache_ttl_hours)
        
        # Extract data from raw
        user_info = raw_data["user_info"]
        playlists = raw_data["playlists"]
        playlist_tracks = raw_data["playlist_tracks"]
        
        # Compute favorites at runtime (not cached) so logic changes apply to cached data
        favorites_playlists = [p for p in playlists if is_favorites_playlist(p["name"])]
        
        # Process raw tracks into TrackInfo objects
        if from_cache:
            if console and RICH_AVAILABLE:
                console.print(f"[dim]Processing {len(playlists)} playlists from cache...[/]\n")
            else:
                print(f"Processing {len(playlists)} playlists from cache")
        
        self._process_raw_tracks(playlists, playlist_tracks, user_id)
        
        # Inject aggregate stats for affinity scoring
        self._inject_aggregate_stats()
        
        # Show filtering stats
        if self.playlists_skipped_owner > 0:
            if console and RICH_AVAILABLE:
                console.print(f"[dim]👤 Skipped {self.playlists_skipped_owner} playlists not owned by user[/]")
            else:
                print(f"Skipped {self.playlists_skipped_owner} playlists not owned by user")
        
        if self.horizon_cutoff:
            filter_parts = []
            if self.tracks_filtered > 0:
                filter_parts.append(f"{self.tracks_filtered:,} outside time horizon")
            if self.tracks_missing_added_at > 0:
                filter_parts.append(f"{self.tracks_missing_added_at:,} missing add date")
            if filter_parts:
                filter_msg = ", ".join(filter_parts)
                if console and RICH_AVAILABLE:
                    console.print(f"[dim]⏱️  Filtered out {filter_msg}[/]\n")
                else:
                    print(f"\nFiltered out {filter_msg}")
        
        # Sort tracks by frequency (number of playlists they appear in)
        sorted_tracks = sorted(
            self.tracks.values(),
            key=lambda t: (-t.count, t.name.lower())
        )
        
        # Analyze temporal patterns (evergreen favorites, early adopter behavior)
        temporal_patterns = self.analyze_temporal_patterns()
        
        # Aggregate data
        albums = self.aggregate_albums()
        artists = self.aggregate_artists()
        likely_favorites = self.get_likely_favorites()
        
        # Get versatile tracks (sorted by versatility_score)
        versatile_tracks = sorted(
            [t for t in self.tracks.values() if t.count > 1],
            key=lambda t: (-t.versatility_score, -t.count, t.name.lower())
        )
        
        # Identify albums with high completion ratio
        favorite_albums = [a for a in albums if a.is_likely_favorite_album]
        
        # Get playlist classification stats (only from owned playlists)
        active_playlist_names = list(self._active_playlists) if hasattr(self, '_active_playlists') else []
        owned_playlist_names = list(self._playlist_sizes.keys()) if hasattr(self, '_playlist_sizes') else []
        archive_playlist_names = [name for name in owned_playlist_names if name not in active_playlist_names]
        
        # Count owned playlists (total minus skipped)
        owned_playlists_count = len(playlists) - self.playlists_skipped_owner
        
        return {
            "user": user_info,
            "is_self_analysis": False,
            "total_playlists": len(playlists),
            "playlists_analyzed": owned_playlists_count,
            "playlists_skipped_owner": self.playlists_skipped_owner,
            "favorites_playlists": [p["name"] for p in favorites_playlists if p.get("owner") == user_id],
            "total_unique_tracks": len(self.tracks),
            "tracks_filtered": self.tracks_filtered,
            "tracks_missing_added_at": self.tracks_missing_added_at,
            "horizon_cutoff": self.horizon_cutoff.isoformat() if self.horizon_cutoff else None,
            "tracks": sorted_tracks,
            "albums": albums,
            "artists": artists,
            "likely_favorites": likely_favorites,
            "versatile_tracks": versatile_tracks,
            "favorite_albums": favorite_albums,
            "temporal_patterns": temporal_patterns,
            "playlist_classification": {
                "active": active_playlist_names,
                "archive": archive_playlist_names,
            },
            "from_cache": from_cache,
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
        filter_parts = []
        if analysis.get("tracks_filtered", 0) > 0:
            filter_parts.append(f"{analysis['tracks_filtered']:,} outside horizon")
        if analysis.get("tracks_missing_added_at", 0) > 0:
            filter_parts.append(f"{analysis['tracks_missing_added_at']:,} missing date")
        filter_info = f" [dim]({', '.join(filter_parts)} filtered)[/]" if filter_parts else ""
        horizon_line = f"\n[white]Time Horizon:[/] [yellow]Since {cutoff_date}[/]{filter_info}"
    
    # Build playlists info showing analyzed vs skipped
    playlists_analyzed = analysis.get("playlists_analyzed", analysis["total_playlists"])
    playlists_skipped = analysis.get("playlists_skipped_owner", 0)
    playlists_info = f"[green]{playlists_analyzed}[/]"
    if playlists_skipped > 0:
        playlists_info += f" [dim]({playlists_skipped} non-owned skipped)[/]"
    
    header_content = f"""[bold cyan]{user['display_name']}[/]
[dim]{user['profile_url']}[/]

[white]Followers:[/] [green]{user['followers']:,}[/]
[white]Playlists Analyzed:[/] {playlists_info}
[white]Unique Tracks:[/] [green]{analysis['total_unique_tracks']:,}[/]{horizon_line}"""
    
    console.print(Panel(
        header_content,
        title="[bold white]🎵 SPOTIFY PLAYLIST ANALYSIS[/]",
        subtitle=f"[dim]Analyzed {playlists_analyzed} playlists[/]",
        border_style="bright_green",
        padding=(1, 2),
    ))
    
    # Show detected favorites playlists
    if analysis["favorites_playlists"]:
        fav_text = ", ".join(analysis["favorites_playlists"][:5])
        if len(analysis["favorites_playlists"]) > 5:
            fav_text += f" (+{len(analysis['favorites_playlists']) - 5} more)"
        console.print(f"[dim]⭐ Detected favorites playlists: {fav_text}[/]\n")
    
    # ===== LIKELY ALL-TIME FAVORITES (Affinity Score) =====
    console.print(Panel(
        "[bold]Tracks you probably actually love - ranked by affinity score[/]",
        title="[bold yellow]⭐ LIKELY FAVORITES (Affinity)[/]",
        border_style="yellow",
    ))
    
    likely_favorites = analysis["likely_favorites"][:top_n]
    
    if likely_favorites:
        fav_table = Table(box=box.ROUNDED, show_header=True, header_style="bold magenta")
        fav_table.add_column("#", style="dim", width=4, justify="right")
        fav_table.add_column("Song", style="white", max_width=30)
        fav_table.add_column("Artist", style="cyan", max_width=22)
        fav_table.add_column("Affinity", justify="right", width=8)
        fav_table.add_column("📋", justify="center", width=3)
        fav_table.add_column("Pop", justify="right", width=4)
        fav_table.add_column("⭐", justify="center", width=2)
        
        for i, track in enumerate(likely_favorites[:15], 1):
            fav_marker = "⭐" if track.in_favorites_playlist else ""
            pop_str = str(track.popularity) if track.popularity is not None else "-"
            
            fav_table.add_row(
                str(i),
                track.name[:30],
                track.artists_str[:22],
                str(track.affinity_score),
                str(track.count),
                pop_str,
                fav_marker,
            )
        
        console.print(fav_table)
        console.print("[dim]Affinity = artist dedication + album depth + recency + cross-context + focused playlists[/]")
    else:
        console.print("[dim]No clear favorites detected.[/]")
    
    console.print()
    
    # ===== VERSATILE TRACKS (Context-Fitting) =====
    console.print(Panel(
        "[bold]Tracks that fit many contexts - may not be your most-played[/]",
        title="[bold cyan]🎭 VERSATILE TRACKS (Context-Fitting)[/]",
        border_style="cyan",
    ))
    
    versatile_tracks = analysis.get("versatile_tracks", [])[:top_n]
    
    if versatile_tracks:
        vers_table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
        vers_table.add_column("#", style="dim", width=4, justify="right")
        vers_table.add_column("Song", style="white", max_width=30)
        vers_table.add_column("Artist", style="cyan", max_width=22)
        vers_table.add_column("Versatility", justify="right", width=10)
        vers_table.add_column("📋", justify="center", width=3)
        vers_table.add_column("Pop", justify="right", width=4)
        
        for i, track in enumerate(versatile_tracks[:15], 1):
            pop_str = str(track.popularity) if track.popularity is not None else "-"
            
            vers_table.add_row(
                str(i),
                track.name[:30],
                track.artists_str[:22],
                str(track.versatility_score),
                str(track.count),
                pop_str,
            )
        
        console.print(vers_table)
        console.print("[dim]Versatility = playlist count + popularity + context diversity (crowd pleasers)[/]")
    else:
        console.print("[dim]No versatile tracks detected.[/]")
    
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
    
    # ===== METHODOLOGY NOTE =====
    methodology_text = """[bold]How to interpret these results:[/]

[yellow]Affinity Score[/] estimates actual favorites using:
  • Artist dedication (tracks from artists you add frequently)
  • Album depth (multiple tracks from same album)
  • Playlist presence (exponential bonus for 2+ playlists)
  • Favorites + cross-context (in favorites AND other playlists)
  • Recency (recently added tracks score higher)
  • Early adopter bonus (added soon after release)
  • Small playlist bonus (focused curation signal)
  • Obscurity bonus / popularity penalty (mainstream hits penalized)

[cyan]Versatility Score[/] measures context-fitting:
  • High playlist count = fits many moods/situations
  • Popular tracks get a bonus (mainstream appeal)
  • May not reflect actual listening frequency

[dim]Limitation: This analysis sees playlist curation, not play counts.
Songs in a single playlist you play daily won't rank as highly.
Your Spotify Wrapped may differ significantly from these results.[/]"""
    
    console.print(Panel(
        methodology_text,
        title="[bold white]📊 METHODOLOGY NOTE[/]",
        border_style="dim",
    ))
    
    console.print()
    
    # ===== FOOTER =====
    footer_text = f"[dim]Analyzed [green]{analysis['total_unique_tracks']:,}[/] unique tracks across [green]{analysis['total_playlists']}[/] playlists[/]"
    if analysis.get("tracks_filtered", 0) > 0:
        footer_text += f"\n[dim]({analysis['tracks_filtered']:,} tracks filtered by time horizon)[/]"
    
    # Show playlist classification summary
    playlist_class = analysis.get("playlist_classification", {})
    active_count = len(playlist_class.get("active", []))
    archive_count = len(playlist_class.get("archive", []))
    if active_count or archive_count:
        footer_text += f"\n[dim]Playlists: {active_count} active rotation, {archive_count} archive/compilation[/]"
    
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
    
    playlists_analyzed = analysis.get("playlists_analyzed", analysis["total_playlists"])
    playlists_skipped = analysis.get("playlists_skipped_owner", 0)
    print(f"\nPlaylists Analyzed: {playlists_analyzed}")
    if playlists_skipped > 0:
        print(f"  ({playlists_skipped} non-owned playlists skipped)")
    print(f"Total Unique Tracks: {analysis['total_unique_tracks']:,}")
    
    if analysis.get("horizon_cutoff"):
        cutoff_date = datetime.fromisoformat(analysis["horizon_cutoff"]).strftime("%Y-%m-%d")
        print(f"Time Horizon: Since {cutoff_date}")
        filter_parts = []
        if analysis.get("tracks_filtered", 0) > 0:
            filter_parts.append(f"{analysis['tracks_filtered']:,} outside horizon")
        if analysis.get("tracks_missing_added_at", 0) > 0:
            filter_parts.append(f"{analysis['tracks_missing_added_at']:,} missing date")
        if filter_parts:
            print(f"  ({', '.join(filter_parts)} filtered)")
    
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
        playlist_class = analysis.get("playlist_classification", {})
        active_playlists_set = set(playlist_class.get("active", []))
        
        export_data = {
            "user": analysis["user"],
            "is_self_analysis": False,
            "total_playlists": analysis["total_playlists"],
            "playlists_analyzed": analysis.get("playlists_analyzed", analysis["total_playlists"]),
            "playlists_skipped_owner": analysis.get("playlists_skipped_owner", 0),
            "favorites_playlists": analysis["favorites_playlists"],
            "total_unique_tracks": analysis["total_unique_tracks"],
            "horizon_cutoff": analysis.get("horizon_cutoff"),
            "tracks_filtered": analysis.get("tracks_filtered", 0),
            "tracks_missing_added_at": analysis.get("tracks_missing_added_at", 0),
            "playlist_classification": playlist_class,
            "likely_favorites": [
                {
                    "rank": i,
                    "name": t.name,
                    "artists": t.artists,
                    "album": t.album,
                    "spotify_url": t.spotify_url,
                    "playlist_count": t.count,
                    "in_favorites_playlist": t.in_favorites_playlist,
                    "affinity_score": t.affinity_score,
                    "versatility_score": t.versatility_score,
                    "popularity": t.popularity,
                    "playlists": t.playlists,
                    "in_active_playlists": [p for p in t.playlists if p in active_playlists_set],
                }
                for i, t in enumerate(analysis["likely_favorites"][:100], 1)
            ],
            "versatile_tracks": [
                {
                    "rank": i,
                    "name": t.name,
                    "artists": t.artists,
                    "album": t.album,
                    "spotify_url": t.spotify_url,
                    "playlist_count": t.count,
                    "affinity_score": t.affinity_score,
                    "versatility_score": t.versatility_score,
                    "popularity": t.popularity,
                    "playlists": t.playlists,
                }
                for i, t in enumerate(analysis.get("versatile_tracks", [])[:100], 1)
            ],
            "favorite_albums": [
                {
                    "rank": i,
                    "name": a.name,
                    "artist": a.artist,
                    "track_count": len(a.tracks),
                    "total_appearances": a.total_appearances,
                    "completion_ratio": a.completion_ratio,
                    "is_likely_favorite": a.is_likely_favorite_album,
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
                    "affinity_score": t.affinity_score,
                    "versatility_score": t.versatility_score,
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
  %(prog)s 1234567890 --refresh-cache    # Force refresh cached data
  %(prog)s 1234567890 --no-cache         # Disable caching, always fetch fresh
  %(prog)s --self                        # Analyze YOUR listening history (requires login)
  %(prog)s --self --output my_stats.json

Caching:
  By default, Spotify data is cached locally in .spotify_cache/ to speed up
  repeated analyses. Cache is keyed by user ID and expires after 24 hours.
  Use --no-cache to disable caching or --refresh-cache to force a refresh.

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
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable cache and always fetch fresh data from Spotify API"
    )
    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Force refresh the cached data for this user"
    )
    parser.add_argument(
        "--cache-ttl",
        type=int,
        default=DEFAULT_CACHE_TTL_HOURS,
        metavar="HOURS",
        help=f"Cache time-to-live in hours (default: {DEFAULT_CACHE_TTL_HOURS})"
    )
    
    args = parser.parse_args()
    
    # Validate arguments
    if not args.self_mode and not args.user_id:
        parser.error("Either provide a user_id or use --self flag")
    
    # Cache settings
    use_cache = not args.no_cache
    refresh_cache = args.refresh_cache
    cache_ttl = args.cache_ttl
    
    if args.self_mode:
        # Self-analysis mode using OAuth
        if console and RICH_AVAILABLE:
            console.print(Panel(
                "[bold green]Self-Analysis Mode[/]\n[dim]Analyzing your personal Spotify listening data[/]",
                title="[bold white]🎧 Spotify Playlist Analyzer[/]",
                border_style="bright_magenta",
            ))
        
        analyzer = SpotifyAnalyzer(
            use_oauth=True,
            use_cache=use_cache,
            refresh_cache=refresh_cache,
            cache_ttl_hours=cache_ttl,
        )
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
            
            cache_info = ""
            if not use_cache:
                cache_info = "\n[dim]Cache: disabled[/]"
            elif refresh_cache:
                cache_info = "\n[dim]Cache: refreshing[/]"
            
            console.print(Panel(
                f"[bold green]Analyzing user:[/] [cyan]{user_id}[/]{horizon_info}{cache_info}",
                title="[bold white]🎵 Spotify Playlist Analyzer[/]",
                border_style="bright_blue",
            ))
        
        analyzer = SpotifyAnalyzer(
            horizon_cutoff=horizon_cutoff,
            use_cache=use_cache,
            refresh_cache=refresh_cache,
            cache_ttl_hours=cache_ttl,
        )
        analysis = analyzer.analyze_user(user_id)
    
    print_report(analysis, top_n=args.top)
    
    if args.output:
        export_to_json(analysis, args.output)


if __name__ == "__main__":
    main()

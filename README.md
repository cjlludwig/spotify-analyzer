# Spotify Playlist Analyzer

A Python CLI tool that scans a Spotify user's public playlists and generates a comprehensive report of their favorite songs, albums, and artists.

<p align="center">
  <img src="https://github.com/user-attachments/assets/11f1cb1d-fc17-4687-ad37-9de31af599af" alt="Spotify Playlist Analyzer demo" />
</p>

## Features

- **Favorite Song Detection** - Identifies songs that appear across multiple playlists
- **Favorites Playlist Detection** - Automatically detects playlists with names like "favorites", "best of", "all time" and weights those songs higher
- **Album Analysis** - Shows which albums have the most tracks added across playlists
- **Artist Dedication Levels** - Categorizes artists as "SUPER FAN", "Big Fan", "Fan", or "Casual" based on track counts
- **Beautiful CLI Output** - Rich tables, progress bars, and colored output
- **JSON Export** - Full results exportable for further analysis
- **Handles Large Libraries** - Pagination support for users with many playlists

## Setup

### 1. Install uv (if not already installed)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Install Dependencies

```bash
uv sync
```

### 3. Get Spotify API Credentials

1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Log in with your Spotify account
3. Click "Create app"
4. Fill in the app details (name, description)
5. Copy the **Client ID** and **Client Secret**

### 4. Set Environment Variables

Create a `.env` file in the project directory:

```env
SPOTIPY_CLIENT_ID=your_client_id_here
SPOTIPY_CLIENT_SECRET=your_client_secret_here
```

Or export them directly:

```bash
export SPOTIPY_CLIENT_ID=your_client_id_here
export SPOTIPY_CLIENT_SECRET=your_client_secret_here
```

## Usage

### Basic Usage

Analyze a user by their Spotify ID:

```bash
uv run python spotify_analyzer.py 1234567890
```

You can also pass a full profile URL:

```bash
uv run python spotify_analyzer.py https://open.spotify.com/user/1234567890
```

### Options

```
usage: spotify_analyzer.py [-h] [--top N] [--output FILE] user_id

Analyze a Spotify user's public playlists to find favorite songs, albums, and artists.

positional arguments:
  user_id               Spotify user ID to analyze (e.g., '1234567890')

options:
  -h, --help            show this help message and exit
  --top N, -t N         Show top N items per category (default: 50)
  --output FILE, -o FILE
                        Export results to JSON file
```

### Examples

Show top 20 in each category:

```bash
uv run python spotify_analyzer.py 1234567890 --top 20
```

Export full results to JSON:

```bash
uv run python spotify_analyzer.py 1234567890 --output report.json
```

## Output

The tool generates a beautiful console report with multiple sections:

### 1. Likely All-Time Favorites
Songs that appear in multiple playlists OR in playlists with "favorites" in the name, weighted by a favorites score.

### 2. Favorite Albums
Albums ranked by number of unique tracks added across all playlists. Shows which albums the user has deep-dived into.

### 3. Top Artists by Dedication
Artists ranked by unique track count, with fan level indicators:
- **SUPER FAN** - 15+ unique tracks
- **Big Fan** - 8-14 unique tracks
- **Fan** - 4-7 unique tracks
- **Casual** - 1-3 unique tracks

### 4. Top Songs by Playlist Frequency
Songs that appear in the most playlists, with a list of which playlists contain each song.

## JSON Export Format

```json
{
  "user": {
    "id": "1234567890",
    "display_name": "Example User",
    "followers": 42,
    "profile_url": "https://open.spotify.com/user/1234567890"
  },
  "total_playlists": 182,
  "favorites_playlists": ["likes", "all time favorites", "best songs ever"],
  "total_unique_tracks": 5432,
  "likely_favorites": [
    {
      "rank": 1,
      "name": "Song Name",
      "artists": ["Artist"],
      "album": "Album",
      "playlist_count": 5,
      "in_favorites_playlist": true,
      "favorites_score": 7
    }
  ],
  "favorite_albums": [
    {
      "rank": 1,
      "name": "Album Name",
      "artist": "Artist",
      "track_count": 12,
      "total_appearances": 18,
      "tracks": ["Track 1", "Track 2", "..."]
    }
  ],
  "top_artists": [
    {
      "rank": 1,
      "name": "Artist Name",
      "unique_tracks": 34,
      "total_appearances": 47,
      "fan_level": "SUPER FAN",
      "tracks": ["Track 1", "Track 2", "..."]
    }
  ],
  "all_tracks": [...]
}
```

## How It Works

1. **Fetches all public playlists** for the given user ID
2. **Detects "favorites" playlists** by scanning playlist names for keywords like "favorite", "best", "top", "loved", etc.
3. **Scans each playlist** for tracks, collecting artist and album metadata
4. **Aggregates data** to identify:
   - Songs appearing in multiple playlists
   - Albums with the most tracks represented
   - Artists with the highest track counts
5. **Applies weighting** to songs in favorites playlists for the "likely favorites" ranking

## Limitations

- Only scans **public** playlists (private playlists require user authentication)
- Cannot access liked songs, listening history, or top tracks of other users (these are private to each user)
- Rate limited by Spotify API (the tool handles pagination automatically)

## License

MIT

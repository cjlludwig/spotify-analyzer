# Spotify Playlist Analyzer

A Python CLI tool that scans a Spotify user's public playlists and generates a comprehensive report of their favorite songs, albums, and artists.

<p align="center">
  <img src="https://github.com/user-attachments/assets/11f1cb1d-fc17-4687-ad37-9de31af599af" alt="Spotify Playlist Analyzer demo" />
</p>

<details>
<summary> Example CLI Output </summary>

```console
spotify-analysis git:main*  
❯ uv run python spotify_analyzer.py 1234567890 --horizon 5y
╭─────────────────────────────────────────────────────── 🎵 Spotify Playlist Analyzer ────────────────────────────────────────────────────────╮
│ Analyzing user: 1234567890                                                                                                                   │
│ Time horizon: Since 2021-01-26                                                                                                              │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
✓ Using cached data for user 1234567890 (cached: 2026-01-25T11:01:59.928271)

Processing 121 playlists from cache...

👤 Skipped 12 playlists not owned by user
⏱️  Filtered out 8,095 outside time horizon


╭─────────────────────────────────────────────────────── 🎵 SPOTIFY PLAYLIST ANALYSIS ────────────────────────────────────────────────────────╮
│                                                                                                                                             │
│  Connor Ludwig                                                                                                                              │
│  https://open.spotify.com/user/1234567890                                                                                                    │
│                                                                                                                                             │
│  Followers: 45                                                                                                                              │
│  Playlists Analyzed: 109 (12 non-owned skipped)                                                                                             │
│  Unique Tracks: 1,800                                                                                                                       │
│  Time Horizon: Since 2021-01-26 (8,095 outside horizon filtered)                                                                            │
│                                                                                                                                             │
╰────────────────────────────────────────────────────────── Analyzed 109 playlists ───────────────────────────────────────────────────────────╯

╭────────────────────────────────────────────────────── ⭐ LIKELY FAVORITES (Affinity) ───────────────────────────────────────────────────────╮
│ Tracks you probably actually love - ranked by affinity score                                                                                │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭──────┬────────────────────────────────┬────────────────────────┬──────────┬─────┬──────┬────╮
│    # │ Song                           │ Artist                 │ Affinity │ 📋  │  Pop │ ⭐ │
├──────┼────────────────────────────────┼────────────────────────┼──────────┼─────┼──────┼────┤
│    1 │ The City of New Orleans        │ Johnny Cash            │      119 │  3  │   32 │ ⭐ │
│    2 │ Come On Over                   │ Royal Blood            │      118 │  2  │    0 │ ⭐ │
│    3 │ DOA                            │ Foo Fighters           │      112 │  2  │   56 │ ⭐ │
│    4 │ In Bloom                       │ Nirvana                │      111 │  3  │   72 │ ⭐ │
│    5 │ Chelsea Dagger                 │ The Fratellis          │      106 │  2  │   64 │ ⭐ │
│    6 │ No Good                        │ KALEO                  │      106 │  2  │   68 │ ⭐ │
│    7 │ Safari Song                    │ Greta Van Fleet        │      106 │  2  │   66 │ ⭐ │
│    8 │ Waiting For Stevie             │ Pearl Jam              │      106 │  2  │   43 │ ⭐ │
│    9 │ Homecoming                     │ Kanye West, Chris Mart │      105 │  2  │   83 │ ⭐ │
│   10 │ Ramble On - 1990 Remaster      │ Led Zeppelin           │      105 │  2  │   70 │ ⭐ │
│   11 │ Thunderstruck                  │ AC/DC                  │      102 │  3  │   87 │ ⭐ │
│   12 │ Can't Keep No Good Boy Down    │ The Parlor Mob         │      102 │  2  │   41 │ ⭐ │
│   13 │ Everything You're Breathing Fo │ The Parlor Mob         │      102 │  2  │   48 │ ⭐ │
│   14 │ Figure It Out                  │ Royal Blood            │      102 │  2  │   58 │ ⭐ │
│   15 │ Little Monster                 │ Royal Blood            │      102 │  2  │   58 │ ⭐ │
╰──────┴────────────────────────────────┴────────────────────────┴──────────┴─────┴──────┴────╯
Affinity = artist dedication + album depth + recency + cross-context + focused playlists

╭─────────────────────────────────────────────────── 🎭 VERSATILE TRACKS (Context-Fitting) ───────────────────────────────────────────────────╮
│ Tracks that fit many contexts - may not be your most-played                                                                                 │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭──────┬────────────────────────────────┬──────────────────────┬────────────┬─────┬──────╮
│    # │ Song                           │ Artist               │ Versatili… │ 📋  │  Pop │
├──────┼────────────────────────────────┼──────────────────────┼────────────┼─────┼──────┤
│    1 │ End of Beginning               │ Djo                  │         45 │  3  │  100 │
│    2 │ Hurricane                      │ The Band Of Heathens │         40 │  3  │   67 │
│    3 │ In Bloom                       │ Nirvana              │         40 │  3  │   72 │
│    4 │ Pump Up The Jam                │ Technotronic         │         40 │  3  │   73 │
│    5 │ Space Jam                      │ Quad City DJ's       │         40 │  3  │   62 │
│    6 │ Thunderstruck                  │ AC/DC                │         40 │  3  │   87 │
│    7 │ The City of New Orleans        │ Johnny Cash          │         35 │  3  │   32 │
│    8 │ (Sittin' On) the Dock of the B │ Otis Redding         │         35 │  2  │   79 │
│    9 │ Black Water                    │ The Doobie Brothers  │         35 │  2  │   63 │
│   10 │ Can I Call You Rose?           │ Thee Sacred Souls    │         35 │  2  │   75 │
│   11 │ Casey Jones - 2013 Remaster    │ Grateful Dead        │         35 │  2  │   60 │
│   12 │ Check the Rhime                │ A Tribe Called Quest │         35 │  2  │   65 │
│   13 │ Chicago                        │ Sufjan Stevens       │         35 │  2  │   61 │
│   14 │ Electric Relaxation            │ A Tribe Called Quest │         35 │  2  │   66 │
│   15 │ Feelin' Alright                │ Joe Cocker           │         35 │  2  │   62 │
╰──────┴────────────────────────────────┴──────────────────────┴────────────┴─────┴──────╯
Versatility = playlist count + popularity + context diversity (crowd pleasers)

╭──────────────────────────────────────────────────────────── 💿 FAVORITE ALBUMS ─────────────────────────────────────────────────────────────╮
│ Albums with the most tracks added across playlists                                                                                          │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭──────┬───────────────────────────┬──────────────────────┬──────────┬──────────────┬──────────────────────────────────────────╮
│    # │ Album                     │ Artist               │   Tracks │  Appearances │ Sample Tracks                            │
├──────┼───────────────────────────┼──────────────────────┼──────────┼──────────────┼──────────────────────────────────────────┤
│    1 │ Higher                    │ Chris Stapleton      │       14 │           14 │ What Am I Gonna Do, South Dakota (+12)   │
│    2 │ Stick Season              │ Noah Kahan           │       14 │           14 │ Northern Attitude, Stick Season (+12)    │
│    3 │ Monarch                   │ The Ghost of Paul Re │       11 │           11 │ Wild Child, Montreal (+9)                │
│    4 │ Believe                   │ The Ghost of Paul Re │       11 │           11 │ After Many Miles, San Antone (+9)        │
│    5 │ Little Neon Limelight     │ Houndmouth           │       11 │           11 │ Sedona, Darlin' (+9)                     │
│    6 │ I Fall in Love Too Easily │ Andrew Bird          │        2 │            2 │ I’ve Grown Accustomed to Her Face, I Fal │
╰──────┴───────────────────────────┴──────────────────────┴──────────┴──────────────┴──────────────────────────────────────────╯

╭──────────────────────────────────────────────────────────── 📊 METHODOLOGY NOTE ────────────────────────────────────────────────────────────╮
│ How to interpret these results:                                                                                                             │
│                                                                                                                                             │
│ Affinity Score estimates actual favorites using:                                                                                            │
│   • Artist dedication (tracks from artists you add frequently)                                                                              │
│   • Album depth (multiple tracks from same album)                                                                                           │
│   • Playlist presence (exponential bonus for 2+ playlists)                                                                                  │
│   • Favorites + cross-context (in favorites AND other playlists)                                                                            │
│   • Recency (recently added tracks score higher)                                                                                            │
│   • Early adopter bonus (added soon after release)                                                                                          │
│   • Small playlist bonus (focused curation signal)                                                                                          │
│   • Obscurity bonus / popularity penalty (mainstream hits penalized)                                                                        │
│                                                                                                                                             │
│ Versatility Score measures context-fitting:                                                                                                 │
│   • High playlist count = fits many moods/situations                                                                                        │
│   • Popular tracks get a bonus (mainstream appeal)                                                                                          │
│   • May not reflect actual listening frequency                                                                                              │
│                                                                                                                                             │
│ Limitation: This analysis sees playlist curation, not play counts.                                                                          │
│ Songs in a single playlist you play daily won't rank as highly.                                                                             │
│ Your Spotify Wrapped may differ significantly from these results.                                                                           │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

╭─────────────────────────────────────────────────────────── ✅ ANALYSIS COMPLETE ────────────────────────────────────────────────────────────╮
│ Analyzed 1,800 unique tracks across 121 playlists                                                                                           │
│ (8,095 tracks filtered by time horizon)                                                                                                     │
│ Playlists: 8 active rotation, 98 archive/compilation                                                                                        │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```
</details>

## Features

- **Dual Ranking System** - Separates "Affinity" (likely actual favorites) from "Versatility" (context-fitting songs)
- **Smart Affinity Scoring** - Identifies true favorites using artist dedication, album depth, playlist patterns, and more
- **Playlist Classification** - Automatically categorizes playlists as "active rotation" vs "archive" based on size and naming
- **Favorites Playlist Detection** - Automatically detects playlists with names like "favorites", "best of", "all time"
- **Album Analysis** - Shows which albums have the most tracks added, with completion ratios
- **Artist Dedication Levels** - Categorizes artists as "SUPER FAN", "Big Fan", "Fan", or "Casual" based on track counts
- **Beautiful CLI Output** - Rich tables, progress bars, and colored output
- **JSON Export** - Full results exportable for further analysis
- **Handles Large Libraries** - Pagination support for users with many playlists
- **Local Caching** - Caches Spotify data locally per user for fast repeated analyses

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
usage: spotify_analyzer.py [-h] [--self] [--top N] [--output FILE] [--horizon PERIOD]
                           [--no-cache] [--refresh-cache] [--cache-ttl HOURS] [user_id]

Analyze a Spotify user's public playlists to find favorite songs, albums, and artists.

positional arguments:
  user_id               Spotify user ID to analyze (e.g., '1234567890'). Not required with --self.

options:
  -h, --help            show this help message and exit
  --self                Analyze your own listening history (opens browser for authentication)
  --top N, -t N         Show top N items per category (default: 50)
  --output FILE, -o FILE
                        Export results to JSON file
  --horizon PERIOD      Only include tracks added within this time period (e.g., '1y', '6m', '30d').
                        Tracks without add dates are excluded when this option is used.
  --no-cache            Disable cache and always fetch fresh data from Spotify API
  --refresh-cache       Force refresh the cached data for this user
  --cache-ttl HOURS     Cache time-to-live in hours (default: 24)
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

Only analyze tracks added in the last year:

```bash
uv run python spotify_analyzer.py 1234567890 --horizon 1y
```

Force refresh cached data:

```bash
uv run python spotify_analyzer.py 1234567890 --refresh-cache
```

## Caching

The analyzer caches Spotify API data locally to speed up repeated analyses of the same user.

- **Cache location**: `.spotify_cache/` directory (created automatically)
- **Cache key**: Each user's data is stored in a separate JSON file keyed by their Spotify user ID
- **Default TTL**: 24 hours (configurable via `--cache-ttl`)

### How it works

1. **First run**: Data is fetched from the Spotify API and saved to cache
2. **Subsequent runs**: Cached data is loaded instantly if still valid (within TTL)
3. **Horizon filtering**: Works on cached data, so you can re-run with different `--horizon` values without re-fetching

### Cache control

```bash
# Use cached data (default behavior)
uv run python spotify_analyzer.py 1234567890

# Force refresh the cache
uv run python spotify_analyzer.py 1234567890 --refresh-cache

# Disable caching entirely
uv run python spotify_analyzer.py 1234567890 --no-cache

# Set custom TTL (48 hours)
uv run python spotify_analyzer.py 1234567890 --cache-ttl 48
```

To clear the cache manually, delete the `.spotify_cache/` directory.

## Output

The tool generates a beautiful console report with multiple sections:

### 1. Likely Favorites (Affinity Score)
Tracks ranked by **affinity score**, which estimates actual favorites by combining multiple signals:

| Signal | Bonus | Description |
|--------|-------|-------------|
| Artist Dedication | +2 to +10 | More tracks from same artist = stronger signal |
| Album Depth | +8 to +15 | Multiple tracks from same album |
| Playlist Count | +10 to +35 | Exponential bonus for 2+ playlists |
| Favorites Playlist | +25 | In a playlist named "favorites", "best", etc. |
| Cross-Context | +10 | In favorites AND multiple other playlists |
| Recency | +5 to +10 | Added in last 6-12 months |
| Early Adopter | +8 to +15 | Added within first month of release |
| Small Playlist | +6 to +12 | In a focused playlist (<50 tracks) |
| Active Rotation | +5 each | In workout/daily/drive playlists |
| Obscurity | +4 to +8 | Less popular tracks (personal choice) |
| Popularity Penalty | -4 to -8 | Very popular tracks penalized (likely thematic) |
| Evergreen | +15 | Re-added to playlists over 6+ months |

### 2. Versatile Tracks (Context-Fitting)
Tracks ranked by **versatility score**, which measures how well a track fits different contexts:
- High playlist count = fits many moods/situations
- Popular tracks get a bonus (mainstream appeal)
- Appears in diverse playlist categories (mood, activity, time-based)

**Note**: High versatility ≠ actual favorite. A song like "Africa" by Toto might rank high in versatility because it fits many playlists, but may not be something you actually listen to frequently.

### 3. Favorite Albums
Albums ranked by completion ratio and track count. Shows which albums the user has deep-dived into.

### 4. Top Artists by Dedication
Artists ranked by unique track count, with fan level indicators:
- **SUPER FAN** - 15+ unique tracks
- **Big Fan** - 8-14 unique tracks
- **Fan** - 4-7 unique tracks
- **Casual** - 1-3 unique tracks

### 5. Top Songs by Playlist Frequency
Songs that appear in the most playlists, with a list of which playlists contain each song.

### 6. Methodology Note
The report includes a methodology explanation that clarifies:
- How affinity and versatility scores differ
- The key limitation: playlist curation ≠ play counts
- Why your Spotify Wrapped may differ from these results

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
  "playlists_analyzed": 175,
  "playlists_skipped_owner": 7,
  "favorites_playlists": ["likes", "all time favorites", "best songs ever"],
  "total_unique_tracks": 5432,
  "playlist_classification": {
    "active": ["workout 2024", "daily rotation", "driving"],
    "archive": ["throwback hits", "2010s collection"]
  },
  "likely_favorites": [
    {
      "rank": 1,
      "name": "Song Name",
      "artists": ["Artist"],
      "album": "Album",
      "playlist_count": 5,
      "in_favorites_playlist": true,
      "affinity_score": 85,
      "versatility_score": 60,
      "popularity": 45,
      "in_active_playlists": ["workout 2024", "daily rotation"]
    }
  ],
  "versatile_tracks": [
    {
      "rank": 1,
      "name": "Crowd Pleaser Song",
      "artists": ["Artist"],
      "playlist_count": 8,
      "affinity_score": 50,
      "versatility_score": 95,
      "popularity": 78
    }
  ],
  "favorite_albums": [
    {
      "rank": 1,
      "name": "Album Name",
      "artist": "Artist",
      "track_count": 12,
      "total_appearances": 18,
      "completion_ratio": 0.85,
      "is_likely_favorite": true,
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
2. **Filters to owned playlists only** - Playlists created by other users (followed playlists) are excluded from analysis to focus on the user's own curation
3. **Classifies playlists** as "active rotation" or "archive" based on:
   - Keywords (workout, daily, drive = active; throwback, archive = archive)
   - Size (smaller playlists are more likely active rotation)
   - Recency of additions
4. **Detects "favorites" playlists** by scanning playlist names for keywords like "favorite", "best", "top", "loved", etc.
5. **Scans each playlist** for tracks, collecting artist and album metadata
6. **Aggregates data** to compute:
   - Artist dedication (how many tracks per artist)
   - Album depth (how many tracks per album)
   - Playlist patterns (count, favorites, active rotation)
7. **Calculates dual scores** for each track:
   - **Affinity score**: Estimates actual favorites using artist dedication, album depth, recency, and other signals
   - **Versatility score**: Measures how well a track fits different contexts
8. **Presents both perspectives** so users can understand the difference between "songs I add everywhere" and "songs I actually love"

### Time Horizon Filtering

When using `--horizon`, the analyzer filters tracks based on when they were added to playlists:

- Tracks added before the horizon cutoff are excluded
- Tracks without an `added_at` timestamp are excluded (these are rare but can occur in very old playlists)
- The filter applies to the `added_at` date, not the track's release date

This allows you to focus on recent listening habits rather than historical playlist additions.

## Limitations

### Data Access
- Only scans **public** playlists (private playlists require user authentication)
- Cannot access liked songs, listening history, or top tracks of other users (these are private to each user)
- Rate limited by Spotify API (the tool handles pagination automatically)

### Methodology
- **Playlist curation ≠ play counts**: This tool sees what tracks you add to playlists, not how often you actually listen to them
- A song in a single playlist you play daily won't rank as high as a song in 5 playlists you rarely open
- Your Spotify Wrapped results may differ significantly from these rankings
- The **affinity score** attempts to correct for this by rewarding signals like artist dedication, album depth, and focused curation, but it's still an estimate based on playlist behavior

### The "Versatility Problem"
A song like "Africa" by Toto might appear in many playlists (road trip, 80s, party, etc.) because it fits many contexts, not because it's a personal favorite. The tool addresses this by:
1. Separating **Versatility Score** (context-fitting) from **Affinity Score** (likely actual favorite)
2. Giving obscure tracks a bonus (mainstream hits are less indicative of personal taste)
3. Rewarding tracks from artists/albums you've added many times

## License

MIT

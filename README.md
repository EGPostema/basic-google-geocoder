# Smart Geocoding with Google Maps API

Bulk geocoding tool with automatic directional offset correction and quality flagging. Built for geocoding location data from insect specimen labels.

## Features

- Automatic directional offset correction (e.g., "5mi NW of X")
- Smart flagging system for quality control
- Batch processing with rate limiting
- Dual coordinate output (base + offset-corrected)

## Installation

```bash
git clone https://github.com/yourusername/smart-geocoding.git
cd smart-geocoding

python3 -m venv geocode_env
source geocode_env/bin/activate  # Windows: geocode_env\Scripts\activate

pip install -r requirements.txt
```

## Setup

### Get Google API Key

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project and enable the Geocoding API
3. Create an API Key
4. Set up billing (free tier: 40,000 requests/month)

### Configure API Key

```bash
export GOOGLE_API_KEY='your-api-key-here'
```

## Usage

```bash
python geocode_locations_google.py input.csv output.csv
```

### Input Format

CSV with these columns (all optional except `province_state` recommended):

| Column | Description |
|--------|-------------|
| `province_state` | State/province (e.g., "California") |
| `county` | County name |
| `city` | City name |
| `prec_location` | Precise location (e.g., "5mi NW of Niland") |
| `latitude` | Leave blank to geocode |
| `longitude` | Leave blank to geocode |

### Output Format

The script adds these columns:

| Column | Description |
|--------|-------------|
| `latitude` | Base coordinates from Google |
| `longitude` | Base coordinates from Google |
| `latitude_shifted` | Offset-corrected coordinates (if applicable) |
| `longitude_shifted` | Offset-corrected coordinates (if applicable) |
| `offset_applied` | Details of offset calculation |
| `google_formatted_address` | Google's standardized address |
| `location_type` | Accuracy level (ROOFTOP, APPROXIMATE, etc.) |
| `flag_status` | Quality flag (OK, REVIEW, WARNING) |
| `flag_reason` | Explanation of issues |

## Directional Offset Correction

The script automatically handles directional offsets:

**Input:** `5mi NW of Niland, Imperial County, California`

**Process:**
1. Extracts base location: `Niland, Imperial County, California`
2. Geocodes base location
3. Calculates offset mathematically (5 miles at 315° bearing)
4. Returns both base and shifted coordinates

**Supported patterns:**
- `5mi NW of X`
- `10 mi E of Y`
- `3.5mi S of Z`
- `50 miles west of A`

**Supported directions:** N, NE, E, SE, S, SW, W, NW, NNE, ENE, ESE, SSE, SSW, WSW, WNW, NNW

## Quality Flags

**WARNING:** Requires manual verification
- County/state only (no city)
- Missing state

**REVIEW:** Double-check recommended
- Directional offsets
- Vague reference points ("behind X", "near Y")
- Water features
- Parks/natural areas
- Abbreviated names

**OK:** No issues detected

## Configuration

Edit script to customize:

```python
INPUT_FILE = "locations.csv"
OUTPUT_FILE = "geocoded_locations.csv"
RATE_LIMIT_DELAY = 0.1  # seconds between requests
```

## License

MIT License

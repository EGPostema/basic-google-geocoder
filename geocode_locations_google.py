#!/usr/bin/env python3
"""
Geocode location data using Google Geocoding API
Handles location data with varying levels of specificity
Includes automatic directional offset calculation
"""

import pandas as pd
import requests
import time
import re
import math
from typing import Optional, Tuple
import sys

# ============================================================================
# CONFIGURATION - EDIT THESE VALUES
# ============================================================================

import os

# Your Google API key - reads from environment variable
# Set with: export GOOGLE_API_KEY="your-key-here"
# Or create a .env file (see setup instructions)
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "YOUR_GOOGLE_API_KEY_HERE")

# Input/Output file paths (edit these!)
INPUT_FILE = "locations.csv"           # Path to your input CSV file
OUTPUT_FILE = "geocoded_locations.csv" # Path for output file

# API configuration
GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
RATE_LIMIT_DELAY = 0.1  # seconds between requests (Google allows ~50 requests/sec)

# ============================================================================

def construct_address(row: pd.Series) -> Optional[str]:
    """
    Construct an address string from available location data.
    Prioritizes more specific location information.
    """
    parts = []
    
    # Add precise location if available
    if pd.notna(row.get('prec_location')) and str(row['prec_location']).strip():
        parts.append(str(row['prec_location']).strip())
    
    # Add city
    if pd.notna(row.get('city')) and str(row['city']).strip():
        parts.append(str(row['city']).strip())
    
    # Add county
    if pd.notna(row.get('county')) and str(row['county']).strip():
        county = str(row['county']).strip()
        if not county.lower().endswith('county'):
            county = county + " County"
        parts.append(county)
    
    # Add state/province
    if pd.notna(row.get('province_state')) and str(row['province_state']).strip():
        parts.append(str(row['province_state']).strip())
    
    # Add country if available (default to USA if not specified)
    if pd.notna(row.get('country')) and str(row['country']).strip():
        parts.append(str(row['country']).strip())
    else:
        # Default to USA for US states
        parts.append("USA")
    
    if parts:
        return ", ".join(parts)
    return None

def extract_base_location(address: str) -> str:
    """
    Extract the base location from an address with directional offset.
    
    Example: "5mi NW of Colorado Springs, CO" -> "Colorado Springs, CO"
    
    This allows Google to geocode the base location correctly,
    then we apply the offset afterward.
    """
    if not address:
        return address
    
    # Patterns that indicate directional offset
    directional_patterns = [
        r'\d+\.?\d*\s*mi[les]*\s+[NSEW]{1,3}\s+of\s+',  # "5mi NW of "
        r'\d+\.?\d*\s*mi[les]*\s+(north|south|east|west|ne|nw|se|sw)\s+of\s+',  # "5 miles west of "
    ]
    
    for pattern in directional_patterns:
        match = re.search(pattern, address, re.IGNORECASE)
        if match:
            # Remove everything up to and including "of "
            base_location = address[match.end():]
            return base_location.strip()
    
    # No directional offset found, return original
    return address

def geocode_address_google(address: str, api_key: str) -> Tuple[Optional[float], Optional[float], Optional[str], Optional[str]]:
    """
    Geocode an address using Google's Geocoding API.
    
    Returns:
        Tuple of (latitude, longitude, location_type, formatted_address)
    """
    params = {
        "address": address,
        "key": api_key
    }
    
    try:
        response = requests.get(GOOGLE_GEOCODE_URL, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        if data.get("status") == "OK" and data.get("results"):
            # Get the first (best) result
            result = data["results"][0]
            
            location = result["geometry"]["location"]
            lat = float(location["lat"])
            lon = float(location["lng"])
            
            # Get location type (ROOFTOP, RANGE_INTERPOLATED, GEOMETRIC_CENTER, APPROXIMATE)
            location_type = result["geometry"].get("location_type", "UNKNOWN")
            
            # Get formatted address
            formatted_address = result.get("formatted_address", "")
            
            return lat, lon, location_type, formatted_address
            
        elif data.get("status") == "ZERO_RESULTS":
            print(f"  📍 No results found for this address")
            return None, None, None, None
            
        elif data.get("status") == "REQUEST_DENIED":
            print(f"  🔐 API request denied - check your API key and billing")
            print(f"  Error: {data.get('error_message', 'No error message')}")
            return None, None, None, None
            
        elif data.get("status") == "OVER_QUERY_LIMIT":
            print(f"  ⚠️  Query limit exceeded - slow down requests")
            return None, None, None, None
            
        else:
            print(f"  ⚠️  API returned status: {data.get('status')}")
            return None, None, None, None
            
    except requests.exceptions.RequestException as e:
        print(f"  ❌ Request error: {e}")
        return None, None, None, None
    except (KeyError, ValueError) as e:
        print(f"  ❌ Error parsing response: {e}")
        return None, None, None, None

def parse_directional_offset(text: str) -> Tuple[Optional[float], Optional[float]]:
    """
    Parse directional offset from text like "5mi NW of X" or "50 mi WSW of Y"
    
    Returns:
        Tuple of (distance_miles, bearing_degrees) or (None, None)
    """
    if not text:
        return None, None
    
    # Pattern to match various directional formats
    patterns = [
        r'(\d+\.?\d*)\s*mi[les]*\s+([NSEW]{1,3})\s+of',  # "5mi NW of"
        r'(\d+\.?\d*)\s*mi[les]*\s+(north|south|east|west|ne|nw|se|sw)\s+of',  # "5 miles west of"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            distance = float(match.group(1))
            direction = match.group(2).upper()
            
            # Convert spelled-out directions to abbreviations
            direction_map = {
                'NORTH': 'N', 'SOUTH': 'S', 'EAST': 'E', 'WEST': 'W',
                'NORTHEAST': 'NE', 'NORTHWEST': 'NW', 'SOUTHEAST': 'SE', 'SOUTHWEST': 'SW'
            }
            direction = direction_map.get(direction, direction)
            
            # Convert direction to bearing (degrees from North, clockwise)
            direction_bearings = {
                'N': 0, 'NNE': 22.5, 'NE': 45, 'ENE': 67.5,
                'E': 90, 'ESE': 112.5, 'SE': 135, 'SSE': 157.5,
                'S': 180, 'SSW': 202.5, 'SW': 225, 'WSW': 247.5,
                'W': 270, 'WNW': 292.5, 'NW': 315, 'NNW': 337.5
            }
            
            bearing = direction_bearings.get(direction)
            if bearing is not None:
                return distance, bearing
    
    return None, None

def apply_offset(lat: float, lon: float, distance_miles: float, bearing_degrees: float) -> Tuple[float, float]:
    """
    Calculate new lat/lon given a starting point, distance, and bearing.
    
    Uses the Haversine formula to calculate the destination point.
    
    Args:
        lat: Starting latitude (degrees)
        lon: Starting longitude (degrees)
        distance_miles: Distance to travel (miles)
        bearing_degrees: Direction to travel (0-360, where 0=North, 90=East, clockwise)
    
    Returns:
        Tuple of (new_lat, new_lon)
    """
    # Earth's radius in miles
    R = 3959
    
    # Convert to radians
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    bearing_rad = math.radians(bearing_degrees)
    
    # Distance as angular distance
    distance_rad = distance_miles / R
    
    # Calculate new position using forward azimuth formula
    new_lat_rad = math.asin(
        math.sin(lat_rad) * math.cos(distance_rad) +
        math.cos(lat_rad) * math.sin(distance_rad) * math.cos(bearing_rad)
    )
    
    new_lon_rad = lon_rad + math.atan2(
        math.sin(bearing_rad) * math.sin(distance_rad) * math.cos(lat_rad),
        math.cos(distance_rad) - math.sin(lat_rad) * math.sin(new_lat_rad)
    )
    
    # Convert back to degrees
    new_lat = math.degrees(new_lat_rad)
    new_lon = math.degrees(new_lon_rad)
    
    return new_lat, new_lon

def flag_potential_issues(row: pd.Series) -> Tuple[str, str]:
    """
    Analyze a location record and flag potential geocoding issues.
    
    Returns:
        Tuple of (flag_status, flag_reason)
        flag_status: "OK", "REVIEW", "WARNING"
    """
    flags = []
    
    # Get location components
    has_city = pd.notna(row.get('city')) and str(row['city']).strip()
    has_prec_location = pd.notna(row.get('prec_location')) and str(row['prec_location']).strip()
    has_county = pd.notna(row.get('county')) and str(row['county']).strip()
    has_state = pd.notna(row.get('province_state')) and str(row['province_state']).strip()
    
    # Get text to analyze
    prec_loc_text = str(row.get('prec_location', '')).strip()
    city_text = str(row.get('city', '')).strip()
    location_text = (prec_loc_text + ' ' + city_text).lower()
    
    # === CRITICAL FLAGS (WARNING level) ===
    
    # Flag 1: County/State only (too vague)
    if not has_city and not has_prec_location:
        flags.append("County/state only - very vague")
    
    # Flag 2: Missing state (ambiguous)
    if not has_state:
        flags.append("Missing state - may be ambiguous")
    
    # Note: Single word locations are OK if they have state context (which they should)
    
    # === MODERATE FLAGS (REVIEW level) ===
    
    # Flag 4: Directional descriptions with distance
    if has_prec_location:
        # Matches patterns like "5mi NW of", "10 mi E", "3.5mi S of"
        directional_patterns = [
            r'\d+\.?\d*\s*mi[les]*\s+[NSEW]{1,3}\s+of',  # "5mi NW of"
            r'\d+\.?\d*\s*mi[les]*\s+[NSEW]{1,3}$',      # "10 mi E"
            r'\d+\.?\d*\s*mi[les]*\s+(north|south|east|west|ne|nw|se|sw)\s+of',  # "5 miles west of"
        ]
        if any(re.search(pattern, location_text) for pattern in directional_patterns):
            flags.append("Directional offset - API may ignore distance/direction")
    
    # Flag 5: "Behind/At/Vic./Near" vague reference points
    if has_prec_location:
        vague_refs = [r'\bbehind\b', r'\bat\b', r'\bvic\.?\b', r'\bnear\b']
        if any(re.search(pattern, location_text) for pattern in vague_refs):
            flags.append("Vague reference point (behind/at/vic/near)")
    
    # Flag 6: Water features (may use centroid)
    if has_prec_location or has_city:
        water_features = [
            r'\briver\b', r'\blake\b', r'\bcreek\b', r'\bbay\b', 
            r'\bbeach\b', r'\bshore\b', r'\bfalls\b', r'\bpond\b'
        ]
        if any(re.search(pattern, location_text) for pattern in water_features):
            flags.append("Water feature - may use centerline/centroid")
    
    # Flag 7: Park/wilderness area names
    park_keywords = [
        r'\bpark\b', r'\bforest\b', r'\bwilderness\b', r'\bpreserve\b', 
        r'\brefuge\b', r'\bnational\b', r'\bstate park\b', r'\bgrove\b', 
        r'\bseashore\b', r'\bmonument\b', r'\bstation\b', r'\bdunes\b'
    ]
    if any(re.search(pattern, location_text) for pattern in park_keywords):
        # Check if it's detailed or just park name
        word_count = len(location_text.split())
        if word_count <= 3:
            flags.append("Park/natural area (just name - may use geometric center)")
        else:
            flags.append("Park/natural area with detail (may still use center)")
    
    # Flag 8: Multiple counties (ambiguous)
    if has_county:
        county_text = str(row['county'])
        if '/' in county_text or ' or ' in county_text.lower():
            flags.append("Multiple counties listed")
    
    # Flag 9: Abbreviated location names
    if has_prec_location:
        # Very short with periods (I.S.B, Vic., etc.)
        if len(prec_loc_text) <= 6 and '.' in prec_loc_text:
            flags.append("Abbreviated location name")
        # All caps short acronym
        elif len(prec_loc_text) <= 4 and prec_loc_text.isupper() and not prec_loc_text.isdigit():
            flags.append("Possible acronym/abbreviation")
    
    # Flag 10: Parenthetical/bracketed information
    if has_prec_location:
        if '(' in prec_loc_text or '[' in prec_loc_text or ')' in prec_loc_text or ']' in prec_loc_text:
            flags.append("Contains parenthetical info - may confuse geocoder")
    
    # === POSITIVE INDICATORS (good for accuracy) ===
    
    # Highway references (usually good)
    if has_prec_location:
        highway_patterns = [
            r'highway\s+\d+', r'hwy\.?\s+\d+', r'hy\.\s+\d+', 
            r'route\s+\d+', r'rt\.?\s+\d+', r'us-\d+', r'i-\d+'
        ]
        if any(re.search(pattern, location_text) for pattern in highway_patterns):
            # This is actually good, but note it
            pass  # Don't flag as negative
    
    # Detailed location (comma-separated, many words)
    if has_prec_location:
        if ',' in prec_loc_text and len(prec_loc_text.split()) >= 4:
            # This is good! Don't add negative flags
            pass
    
    # === DETERMINE OVERALL FLAG STATUS ===
    
    if not flags:
        return "OK", ""
    
    # Count severity
    critical_keywords = ["county/state only", "missing state"]
    moderate_keywords = ["directional offset", "vague reference", "just name"]
    
    has_critical = any(any(keyword in flag.lower() for keyword in critical_keywords) for flag in flags)
    
    # WARNING: Only critical issues
    if has_critical:
        return "WARNING", "; ".join(flags)
    
    # REVIEW: Multiple issues OR high-risk single issue
    # But NOT for informational flags like parks/water features alone
    if len(flags) >= 2:
        # Check if all flags are just informational (parks, water, parenthetical)
        informational_only = all(
            any(keyword in flag.lower() for keyword in ['park', 'water feature', 'parenthetical'])
            for flag in flags
        )
        if informational_only:
            return "OK", "; ".join(flags)
        else:
            return "REVIEW", "; ".join(flags)
    elif len(flags) == 1:
        flag = flags[0].lower()
        # Only flag as REVIEW if it's a concerning issue
        if "directional offset" in flag or "vague reference" in flag or "abbreviated" in flag:
            return "REVIEW", "; ".join(flags)
        # Single informational flags (park, water feature, parenthetical) -> OK but still shown
        else:
            return "OK", "; ".join(flags)
    
    return "OK", "; ".join(flags)

def should_geocode(row: pd.Series) -> bool:
    """
    Determine if a row needs geocoding.
    Returns True if latitude or longitude is missing.
    """
    lat = row.get('latitude')
    lon = row.get('longitude')
    
    # Check if either is NaN, None, or empty string
    lat_missing = pd.isna(lat) or (isinstance(lat, str) and not lat.strip())
    lon_missing = pd.isna(lon) or (isinstance(lon, str) and not lon.strip())
    
    return lat_missing or lon_missing

def is_too_vague(row: pd.Series) -> bool:
    """
    Check if location is too vague (county-only or state-only).
    For ~20mi accuracy (10mi radius), we need at least city-level data.
    """
    has_city = pd.notna(row.get('city')) and str(row['city']).strip()
    has_prec_location = pd.notna(row.get('prec_location')) and str(row['prec_location']).strip()
    
    # If we have city or precise location, it's specific enough
    return not (has_city or has_prec_location)

def main():
    # Check if command line arguments are provided, otherwise use configured paths
    if len(sys.argv) >= 2:
        input_file = sys.argv[1]
        output_file = sys.argv[2] if len(sys.argv) > 2 else "geocoded_" + input_file
    else:
        # Use configured file paths from top of script
        input_file = INPUT_FILE
        output_file = OUTPUT_FILE
        print("Using configured file paths from script:")
        print(f"  Input:  {input_file}")
        print(f"  Output: {output_file}")
        print()
    
    print(f"📂 Reading data from: {input_file}")
    
    try:
        df = pd.read_csv(input_file)
    except FileNotFoundError:
        print(f"❌ Error: File '{input_file}' not found")
        sys.exit(1)
    
    print(f"✅ Loaded {len(df)} rows")
    
    # Convert latitude and longitude columns to numeric type
    if 'latitude' in df.columns:
        df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
    else:
        df['latitude'] = pd.NA
    
    if 'longitude' in df.columns:
        df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
    else:
        df['longitude'] = pd.NA
    
    # Add columns for tracking geocoding results if they don't exist
    if 'geocoded_address' not in df.columns:
        df['geocoded_address'] = ''
    if 'google_formatted_address' not in df.columns:
        df['google_formatted_address'] = ''
    if 'location_type' not in df.columns:
        df['location_type'] = ''
    if 'flag_status' not in df.columns:
        df['flag_status'] = ''
    if 'flag_reason' not in df.columns:
        df['flag_reason'] = ''
    
    # Add columns for offset-corrected coordinates
    if 'latitude_shifted' not in df.columns:
        df['latitude_shifted'] = pd.NA
    if 'longitude_shifted' not in df.columns:
        df['longitude_shifted'] = pd.NA
    if 'offset_applied' not in df.columns:
        df['offset_applied'] = ''
    
    # PRE-PROCESSING: Flag all rows for potential issues
    print("\n🔍 Pre-processing: Flagging potential issues...")
    for idx, row in df.iterrows():
        flag_status, flag_reason = flag_potential_issues(row)
        df.at[idx, 'flag_status'] = flag_status
        df.at[idx, 'flag_reason'] = flag_reason
    
    # Show flagging summary
    flag_counts = df['flag_status'].value_counts()
    print("\n📋 Flagging Summary:")
    for status in ['WARNING', 'REVIEW', 'OK']:
        count = flag_counts.get(status, 0)
        if status == 'WARNING':
            emoji = "⚠️ "
        elif status == 'REVIEW':
            emoji = "📌"
        else:
            emoji = "✅"
        print(f"  {emoji} {status}: {count} locations")
    
    if flag_counts.get('WARNING', 0) > 0:
        print("\n⚠️  WARNING flagged locations:")
        warning_rows = df[df['flag_status'] == 'WARNING']
        for idx, row in warning_rows.iterrows():
            location_desc = construct_address(row) or "No address"
            print(f"    Row {idx}: {location_desc}")
            print(f"           {row['flag_reason']}")
    
    if flag_counts.get('REVIEW', 0) > 0:
        print(f"\n📌 {flag_counts.get('REVIEW', 0)} locations flagged for REVIEW (see output CSV for details)")
    
    print()
    
    # Count how many need geocoding
    needs_geocoding = df.apply(should_geocode, axis=1)
    total_to_geocode = needs_geocoding.sum()
    
    print(f"\n🎯 Found {total_to_geocode} locations that need geocoding")
    
    if total_to_geocode == 0:
        print("✨ All locations already have coordinates!")
        return
    
    # Check API key
    if GOOGLE_API_KEY == "YOUR_GOOGLE_API_KEY_HERE" or not GOOGLE_API_KEY:
        print("\n⚠️  WARNING: Google API key not set!")
        print("   Set your API key using one of these methods:")
        print("")
        print("   Option 1 - Environment variable (recommended):")
        print("     export GOOGLE_API_KEY='your-api-key-here'")
        print("     python geocode_locations_google.py")
        print("")
        print("   Option 2 - Create .env file:")
        print("     echo 'GOOGLE_API_KEY=your-api-key-here' > .env")
        print("     python geocode_locations_google.py")
        print("")
        print("   Option 3 - Edit the script:")
        print("     Edit geocode_locations_google.py and set GOOGLE_API_KEY")
        print("")
        sys.exit(1)
    
    # Process each row
    geocoded_count = 0
    skipped_vague = 0
    failed_count = 0
    
    for idx, row in df[needs_geocoding].iterrows():
        # Check if too vague
        if is_too_vague(row):
            print(f"\n⏭️  Row {idx}: Skipping (too vague - county/state only)")
            skipped_vague += 1
            continue
        
        # Construct address
        address = construct_address(row)
        
        if not address:
            print(f"\n⏭️  Row {idx}: Skipping (no address data)")
            skipped_vague += 1
            continue
        
        print(f"\n🔍 Row {idx}: Geocoding '{address}'")
        
        # Extract base location (remove directional offset for geocoding)
        base_address = extract_base_location(address)
        if base_address != address:
            print(f"  📍 Extracted base location: '{base_address}'")
        
        # Geocode the base location
        lat, lon, location_type, formatted_address = geocode_address_google(base_address, GOOGLE_API_KEY)
        
        if lat and lon:
            df.at[idx, 'latitude'] = lat
            df.at[idx, 'longitude'] = lon
            df.at[idx, 'geocoded_address'] = address
            df.at[idx, 'google_formatted_address'] = formatted_address
            df.at[idx, 'location_type'] = location_type
            
            # Check for directional offset and apply if found
            prec_location = str(row.get('prec_location', '')).strip()
            if prec_location:
                distance, bearing = parse_directional_offset(prec_location)
                if distance and bearing:
                    # Calculate shifted coordinates
                    lat_shifted, lon_shifted = apply_offset(lat, lon, distance, bearing)
                    df.at[idx, 'latitude_shifted'] = lat_shifted
                    df.at[idx, 'longitude_shifted'] = lon_shifted
                    df.at[idx, 'offset_applied'] = f"{distance}mi at {bearing}°"
                    
                    print(f"  🧭 Directional offset detected: {distance}mi at {bearing}° bearing")
                    print(f"     Base coords: {lat:.6f}, {lon:.6f}")
                    print(f"     Shifted coords: {lat_shifted:.6f}, {lon_shifted:.6f}")
            
            # Add post-geocoding flags
            post_flags = []
            
            # Only flag GEOMETRIC_CENTER (not APPROXIMATE - that's very common and fine)
            if location_type == "GEOMETRIC_CENTER":
                post_flags.append("Geometric center of area")
            
            # Check if Google returned a very different location
            if formatted_address:
                formatted_lower = formatted_address.lower()
                
                # Check if state matches (if we have one)
                if pd.notna(row.get('province_state')):
                    expected_state = str(row['province_state']).strip()
                    expected_state_lower = expected_state.lower()
                    
                    # State abbreviation mapping
                    state_abbrev = {
                        'alabama': 'al', 'alaska': 'ak', 'arizona': 'az', 'arkansas': 'ar',
                        'california': 'ca', 'colorado': 'co', 'connecticut': 'ct', 'delaware': 'de',
                        'florida': 'fl', 'georgia': 'ga', 'hawaii': 'hi', 'idaho': 'id',
                        'illinois': 'il', 'indiana': 'in', 'iowa': 'ia', 'kansas': 'ks',
                        'kentucky': 'ky', 'louisiana': 'la', 'maine': 'me', 'maryland': 'md',
                        'massachusetts': 'ma', 'michigan': 'mi', 'minnesota': 'mn', 'mississippi': 'ms',
                        'missouri': 'mo', 'montana': 'mt', 'nebraska': 'ne', 'nevada': 'nv',
                        'new hampshire': 'nh', 'new jersey': 'nj', 'new mexico': 'nm', 'new york': 'ny',
                        'north carolina': 'nc', 'north dakota': 'nd', 'ohio': 'oh', 'oklahoma': 'ok',
                        'oregon': 'or', 'pennsylvania': 'pa', 'rhode island': 'ri', 'south carolina': 'sc',
                        'south dakota': 'sd', 'tennessee': 'tn', 'texas': 'tx', 'utah': 'ut',
                        'vermont': 'vt', 'virginia': 'va', 'washington': 'wa', 'west virginia': 'wv',
                        'wisconsin': 'wi', 'wyoming': 'wy'
                    }
                    
                    # Check if either full name or abbreviation appears in result
                    state_found = (
                        expected_state_lower in formatted_lower or
                        state_abbrev.get(expected_state_lower, '') in formatted_lower
                    )
                    
                    if expected_state and not state_found:
                        post_flags.append(f"State mismatch (expected {expected_state})")
                
                # Check if country is unexpected
                if 'india' in formatted_lower or 'uk' in formatted_lower or 'canada' in formatted_lower:
                    if 'usa' not in formatted_lower and 'united states' not in formatted_lower:
                        post_flags.append("UNEXPECTED COUNTRY - verify result!")
            
            # Update flags if we found post-geocoding issues
            if post_flags:
                existing_flags = df.at[idx, 'flag_reason']
                if existing_flags:
                    df.at[idx, 'flag_reason'] = existing_flags + "; " + "; ".join(post_flags)
                else:
                    df.at[idx, 'flag_reason'] = "; ".join(post_flags)
                
                # Upgrade status if we found serious issues
                if any("UNEXPECTED COUNTRY" in f or "State mismatch" in f for f in post_flags):
                    df.at[idx, 'flag_status'] = "WARNING"
                elif df.at[idx, 'flag_status'] == "OK":
                    df.at[idx, 'flag_status'] = "REVIEW"
            
            print(f"  ✅ Success: {lat}, {lon}")
            print(f"  📍 Google says: {formatted_address}")
            print(f"  🎯 Accuracy: {location_type}")
            if post_flags:
                print(f"  🚩 Post-geocoding flags: {'; '.join(post_flags)}")
            geocoded_count += 1
        else:
            print(f"  ❌ Failed to geocode")
            failed_count += 1
        
        # Rate limiting
        time.sleep(RATE_LIMIT_DELAY)
    
    # Save results
    print(f"\n💾 Saving results to: {output_file}")
    df.to_csv(output_file, index=False)
    
    # Summary
    print("\n" + "="*50)
    print("📊 GEOCODING SUMMARY")
    print("="*50)
    print(f"Total rows:              {len(df)}")
    print(f"Successfully geocoded:   {geocoded_count}")
    print(f"Skipped (too vague):     {skipped_vague}")
    print(f"Failed:                  {failed_count}")
    print(f"Already had coordinates: {len(df) - total_to_geocode}")
    
    # Count offset applications
    offset_count = df['offset_applied'].notna().sum() if 'offset_applied' in df.columns else 0
    if offset_count > 0:
        print(f"\n🧭 Directional offsets applied: {offset_count}")
        print(f"   (See latitude_shifted/longitude_shifted columns)")
    
    print("="*50)
    
    # Flag summary
    final_flag_counts = df['flag_status'].value_counts()
    print("\n🚩 FLAGGING SUMMARY")
    print("="*50)
    for status in ['WARNING', 'REVIEW', 'OK']:
        count = final_flag_counts.get(status, 0)
        if status == 'WARNING':
            emoji = "⚠️ "
            print(f"{emoji} {status}: {count} locations - VERIFY THESE MANUALLY")
        elif status == 'REVIEW':
            emoji = "📌"
            print(f"{emoji} {status}: {count} locations - double-check recommended")
        else:
            emoji = "✅"
            print(f"{emoji} {status}: {count} locations - look good")
    print("="*50)
    
    if final_flag_counts.get('WARNING', 0) > 0:
        print("\n⚠️  WARNING LOCATIONS (check these carefully!):")
        warning_df = df[df['flag_status'] == 'WARNING']
        for idx, row in warning_df.iterrows():
            print(f"\n  Row {idx}:")
            if pd.notna(row.get('google_formatted_address')) and row['google_formatted_address']:
                print(f"    Google result: {row['google_formatted_address']}")
            print(f"    Flags: {row['flag_reason']}")
    
    print(f"\n✅ Done! Results saved to: {output_file}")
    print(f"\n💡 TIP: Sort by 'flag_status' column to review flagged locations")
    print(f"   - WARNING: Definitely verify these manually")
    print(f"   - REVIEW: Double-check if precision matters")
    print(f"   - OK: Should be good to go")

if __name__ == "__main__":
    main()

import secrets
import hashlib
import base64
import requests

from urllib.parse import urlencode, urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler


# ============================================================
# CONFIGURATION
# ============================================================

CLIENT_ID = "9f523aea5eff41ccb5d88f2f8c36eaae"

REDIRECT_URI = "http://127.0.0.1:3000"

SOURCE_PLAYLIST_ID = "62VdEoLoxeplqEANkqDfUH"

NEW_PLAYLIST_NAME = "organized"

SCOPES = [
    "playlist-read-private",
    "playlist-modify-private"
]


# ============================================================
# 1. CREATE PKCE VALUES
# ============================================================

def Connect():

    code_verifier = secrets.token_urlsafe(64)

    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).decode().rstrip("=")

    return code_verifier, code_challenge


# ============================================================
# 2. CALLBACK SERVER
# ============================================================

class CallbackHandler(BaseHTTPRequestHandler):

    def do_GET(self):

        parsed_url = urlparse(self.path)
        params = parse_qs(parsed_url.query)

        print("\nRequest received:")
        print(self.path)

        # Spotify returned an authorization code
        if "code" in params:

            code = params["code"][0]

            returned_state = params.get("state", [None])[0]

            self.server.authorization_code = code
            self.server.returned_state = returned_state

            self.send_response(200)
            self.end_headers()

            self.wfile.write(
                b"Authorization successful! You can close this window."
            )

        # Spotify returned an error
        elif "error" in params:

            error = params["error"][0]

            self.server.authorization_error = error

            self.send_response(400)
            self.end_headers()

            self.wfile.write(
                b"Authorization failed. You can close this window."
            )

        else:

            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return


# ============================================================
# 3. CREATE SPOTIFY AUTHORIZATION URL
# ============================================================

def CreateAuthorizationURL(code_challenge, state):

    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(SCOPES),
        "state": state,
        "code_challenge_method": "S256",
        "code_challenge": code_challenge
    }

    return (
        "https://accounts.spotify.com/authorize?"
        + urlencode(params)
    )


# ============================================================
# 4. WAIT FOR SPOTIFY CALLBACK
# ============================================================

def WaitForAuthorization(expected_state):

    server = HTTPServer(
        ("127.0.0.1", 3000),
        CallbackHandler
    )

    server.authorization_code = None
    server.authorization_error = None
    server.returned_state = None

    print("\nWaiting for Spotify authorization...")

    while (
        server.authorization_code is None
        and server.authorization_error is None
    ):
        server.handle_request()

    if server.authorization_error:
        error = server.authorization_error
        server.server_close()

        raise Exception(
            f"Spotify authorization failed: {error}"
        )

    # Check that Spotify returned the same state we sent
    if server.returned_state != expected_state:

        server.server_close()

        raise Exception(
            "State mismatch. Authorization was rejected."
        )

    code = server.authorization_code

    server.server_close()

    return code


# ============================================================
# 5. EXCHANGE AUTHORIZATION CODE FOR ACCESS TOKEN
# ============================================================

def GetAccessToken(code, code_verifier):

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "code_verifier": code_verifier
    }

    response = requests.post(
        "https://accounts.spotify.com/api/token",
        data=data
    )

    response.raise_for_status()

    token_data = response.json()

    return token_data


# ============================================================
# 6. GENERIC SPOTIFY API REQUEST
# ============================================================

def SpotifyRequest(
    access_token,
    method,
    url,
    json_data=None
):

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    response = requests.request(
        method,
        url,
        headers=headers,
        json=json_data
    )

    response.raise_for_status()

    if response.status_code == 204:
        return None

    return response.json()


# ============================================================
# 7. GET ALL TRACKS FROM SOURCE PLAYLIST
# ============================================================

def GetPlaylistTracks(access_token, playlist_id):

    tracks = []

    url = (
        f"https://api.spotify.com/v1/playlists/"
        f"{playlist_id}/items?limit=50"
    )

    while url:

        data = SpotifyRequest(
            access_token,
            "GET",
            url
        )

        for item in data.get("items", []):

            track = item.get("item")

            if not track:
                continue

            # Ignore anything that isn't a normal track
            if track.get("type") != "track":
                continue

            if not track.get("uri"):
                continue

            tracks.append({
                "id": track["id"],
                "uri": track["uri"],
                "title": track["name"],
                "artist": ", ".join(
                    artist["name"]
                    for artist in track["artists"]
                )
            })

        # Get the next page
        url = data.get("next")

    return tracks


# ============================================================
# 8. GET ALPHABETICAL GROUP
# ============================================================

def GetLetter(title):

    title = title.strip()

    if not title:
        return "#"

    first_character = title[0].casefold()

    if first_character.isalpha():
        return first_character.upper()

    return "#"


# ============================================================
# 9. SORT TRACKS
# ============================================================

def SortTracks(tracks):

    def SortKey(track):

        title = track["title"].strip()

        letter = GetLetter(title)

        return (
            letter == "#",
            letter,
            -len(title),
            title.casefold()
        )

    return sorted(
        tracks,
        key=SortKey
    )


# ============================================================
# 10. DISPLAY ORGANIZED TRACKS
# ============================================================

def DisplayTracks(tracks):

    current_letter = None

    print("\n================================")
    print("       ORGANIZED TRACKS")
    print("================================")

    for track in tracks:

        letter = GetLetter(track["title"])

        if letter != current_letter:

            current_letter = letter

            print(f"\n{letter}:")
            print("----------------------------")

        print(
            f"{track['title']} - {track['artist']}"
        )


# ============================================================
# 11. CREATE NEW PLAYLIST
# ============================================================

def CreatePlaylist(access_token, playlist_name):

    data = {
        "name": playlist_name,
        "public": False,
        "description": "Organized alphabetically and by title length"
    }

    playlist = SpotifyRequest(
        access_token,
        "POST",
        "https://api.spotify.com/v1/me/playlists",
        data
    )

    return playlist


# ============================================================
# 12. ADD TRACKS TO NEW PLAYLIST
# ============================================================

def AddTracksToPlaylist(
    access_token,
    playlist_id,
    tracks
):

    batch_size = 100

    for i in range(0, len(tracks), batch_size):

        batch = tracks[i:i + batch_size]

        data = {
            "uris": [
                track["uri"]
                for track in batch
            ]
        }

        SpotifyRequest(
            access_token,
            "POST",
            f"https://api.spotify.com/v1/playlists/"
            f"{playlist_id}/items",
            data
        )

        print(
            f"Added "
            f"{min(i + batch_size, len(tracks))}"
            f"/{len(tracks)} tracks"
        )


# ============================================================
# 13. MAIN
# ============================================================

def main():

    print("Starting Spotify Organizer...")

    # --------------------------------------------------------
    # PKCE
    # --------------------------------------------------------

    code_verifier, code_challenge = Connect()

    print("\nPKCE generated.")

    # --------------------------------------------------------
    # OAuth state
    # --------------------------------------------------------

    state = secrets.token_urlsafe(32)

    # --------------------------------------------------------
    # Create Spotify authorization URL
    # --------------------------------------------------------

    spotify_url = CreateAuthorizationURL(
        code_challenge,
        state
    )

    print("\nOpen this URL in your browser:")
    print(spotify_url)

    # --------------------------------------------------------
    # Wait for authorization
    # --------------------------------------------------------

    code = WaitForAuthorization(state)

    print("\nAuthorization code received.")

    # --------------------------------------------------------
    # Get access token
    # --------------------------------------------------------

    token_data = GetAccessToken(
        code,
        code_verifier
    )

    access_token = token_data["access_token"]

    print("Access token received.")

    # --------------------------------------------------------
    # Get original playlist
    # --------------------------------------------------------

    print("\nGetting playlist tracks...")

    tracks = GetPlaylistTracks(
        access_token,
        SOURCE_PLAYLIST_ID
    )

    print(
        f"Found {len(tracks)} tracks."
    )

    # --------------------------------------------------------
    # Sort
    # --------------------------------------------------------

    print("\nSorting tracks...")

    sorted_tracks = SortTracks(tracks)

    # --------------------------------------------------------
    # Display result in terminal
    # --------------------------------------------------------

    DisplayTracks(sorted_tracks)

    # --------------------------------------------------------
    # Create new playlist
    # --------------------------------------------------------

    print("\nCreating 'organized' playlist...")

    new_playlist = CreatePlaylist(
        access_token,
        NEW_PLAYLIST_NAME
    )

    print(
        f"Created playlist: {new_playlist['name']}"
    )

    # --------------------------------------------------------
    # Add tracks
    # --------------------------------------------------------

    print("\nAdding tracks...")

    AddTracksToPlaylist(
        access_token,
        new_playlist["id"],
        sorted_tracks
    )

    # --------------------------------------------------------
    # Finished
    # --------------------------------------------------------

    print("\n================================")
    print("          COMPLETE")
    print("================================")

    print(
        "\nYour organized playlist:"
    )

    print(
        new_playlist["external_urls"]["spotify"]
    )


# ============================================================
# RUN PROGRAM
# ============================================================

if __name__ == "__main__":
    main()
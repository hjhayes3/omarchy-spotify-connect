# Omarchy Spotify Connect

A small Omarchy shell plugin for choosing the Spotify Connect device that is
currently playing. Click the bar icon, see the devices Spotify reports, and
select a laptop, Chromecast, Google Home speaker, or speaker group to transfer
the current playback session.

This is an output selector, not a Spotify client. It does not search, browse
playlists, control tracks or volume, play audio, or discover Cast devices. A
Chromecast appears only when Spotify exposes it as a Spotify Connect device.

## Requirements

- Omarchy 4.0 or newer with the current Quickshell-based shell plugin system
- Python 3.11 or newer (standard library only)
- `libsecret`, including the `secret-tool` command
- A Secret Service provider available in the desktop session
- A Spotify developer application and its Client ID
- Spotify Premium for playback transfer. Spotify currently documents the
  transfer-playback endpoint as Premium-only.

No Spotify client secret is needed or used.

## Create the Spotify application

1. Sign in to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard).
2. Choose **Create app**.
3. Give the app a name and description and select the Web API.
4. In the app settings, add this exact Redirect URI:

   ```text
   http://127.0.0.1:43821/callback
   ```

   Do not substitute `localhost`. Spotify requires an explicit loopback IP
   literal and the redirect must match exactly.
5. Save the settings and copy the app's **Client ID**. Do not copy or configure
   the Client Secret.

The plugin requests only:

- `user-read-playback-state` to list devices and read the active device
- `user-modify-playback-state` to transfer playback

## Install and enable

From GitHub:

```bash
omarchy plugin add https://github.com/hjhayes3/omarchy-spotify-connect.git
omarchy plugin enable hjhayes3.spotify-connect --section right
```

For local development, install a checkout manually:

```bash
mkdir -p ~/.config/omarchy/plugins
cp -a /path/to/omarchy-spotify-connect ~/.config/omarchy/plugins/hjhayes3.spotify-connect
omarchy-shell shell rescanPlugins
omarchy plugin enable hjhayes3.spotify-connect --section right
```

Disable or re-enable it with:

```bash
omarchy plugin disable hjhayes3.spotify-connect
omarchy plugin enable hjhayes3.spotify-connect --section right
```

## Configure and authenticate

The helper can run from the repository or installed plugin directory:

```bash
./spotify-connect configure YOUR_SPOTIFY_CLIENT_ID
./spotify-connect auth
```

`auth` opens the Spotify consent page in the default browser and listens only
on `127.0.0.1:43821` for the callback. On success, access and refresh tokens are
stored in the desktop Secret Service keyring. Expired access tokens are
refreshed automatically.

If browser launching is undesirable, print the authorization URL and open it
yourself:

```bash
./spotify-connect auth --no-browser
```

The bar popup also offers an authentication button after the Client ID has
been configured.

## Usage

Click the Spotify icon in the Omarchy bar. The filled dot marks the active
device. Click another available device to transfer playback while preserving
the current play/pause state. Restricted devices are displayed but disabled.
Use the refresh button to retrieve a new device list.

Device rows include a remember button. Remembering a device caches its current
Spotify device ID so the plugin can continue showing it when Spotify
later omits it from the available-devices response. A remembered device is
marked `remembered` while live or `unavailable — activate in Spotify first`
while absent; use its trash button to forget it. Cached-only entries cannot be
selected because Spotify does not guarantee that device IDs remain valid.
Activate the device in an official Spotify client and refresh the plugin to
obtain a current transferable ID.

The widget refreshes when opened, after a transfer, and periodically (30
seconds by default). Spotify device IDs are never persisted. The backend
resolves a name against a newly fetched device list, and the UI transfers by
the freshly returned ID.

## Backend CLI

All normal output is JSON, making the helper independently scriptable:

```bash
./spotify-connect status
./spotify-connect devices
./spotify-connect transfer "Whole House"
./spotify-connect transfer --id CURRENT_DEVICE_ID
./spotify-connect remember --id CURRENT_DEVICE_ID --name "Whole House" --type speaker
./spotify-connect forget --id CURRENT_DEVICE_ID
./spotify-connect logout
```

Device-name matching is case-insensitive. If names are duplicated, name-based
transfer fails with an ambiguity error; inspect `devices` and use `--id` for
that invocation. IDs should not be cached because Spotify does not guarantee
their permanence.

## Security

- Authorization Code with PKCE (S256) is used; no client secret exists in the
  plugin.
- OAuth tokens are stored only through Secret Service using `secret-tool`.
- Tokens, authorization codes, PKCE verifiers, and OAuth state are never
  logged or written to repository files.
- The Client ID is non-secret and is stored at
  `~/.config/omarchy-spotify-connect/config.json` with mode `0600`.
- Remembered device IDs are not OAuth credentials. They are stored at
  `~/.local/state/omarchy-spotify-connect/devices.json` with mode `0600`.
- `logout` removes the keyring entry.
- Omarchy plugins execute unsandboxed inside `omarchy-shell`; review third-party
  plugin code before enabling it.

The repository `.gitignore` excludes common credential and environment-file
names as defense in depth.

## Dependencies

Runtime dependencies are limited to software already present in a standard
Omarchy installation: Quickshell, Python's standard library, and `libsecret`.
There is no Spotify SDK, Python package, daemon, or direct Cast dependency.

On another Arch installation, `secret-tool` is supplied by:

```bash
sudo pacman -S libsecret
```

The plugin deliberately refuses to save tokens to plaintext if Secret Service
is unavailable.

## Troubleshooting

- **Client ID is not configured:** run `./spotify-connect configure CLIENT_ID`.
- **Redirect URI mismatch:** confirm the dashboard contains exactly
  `http://127.0.0.1:43821/callback`.
- **Authentication expired:** run `./spotify-connect logout`, then
  `./spotify-connect auth`.
- **No active session:** start playback in an official Spotify client, then
  refresh. A device list can exist without an active session.
- **No devices:** open Spotify on the intended device and ensure it is visible
  in Spotify's own Connect picker. Some device models may not be returned by
  the Web API.
- **Restricted device:** Spotify reports that device as unable to accept Web
  API commands; select it from an official client if possible.
- **Selected device disappeared:** refresh and select it again. Device IDs are
  intentionally not cached.
- **Rate limited:** wait for Spotify's cooldown, then refresh.
- **Network/API error:** run `./spotify-connect status` in a terminal to see the
  same structured error independently of the shell.
- **Keyring error:** verify `secret-tool` is installed and a Secret Service is
  available in the graphical session.
- **Widget does not appear:** run `omarchy plugin validate .`,
  `omarchy-shell shell rescanPlugins`, and then enable the plugin again.

## Development and testing

No account or credentials are needed for unit tests:

```bash
python3 -m unittest discover -v
python3 -m py_compile spotify-connect spotify_connect/*.py tests/*.py
omarchy plugin validate .
```

For live backend testing:

```bash
./spotify-connect configure YOUR_SPOTIFY_CLIENT_ID
./spotify-connect auth
./spotify-connect status | jq .
./spotify-connect devices | jq .
./spotify-connect transfer "Whole House" | jq .
```

To test in Omarchy without changing the packaged shell source, copy the checkout
to `~/.config/omarchy/plugins/hjhayes3.spotify-connect`, rescan, enable it, and
watch shell diagnostics while opening and using the popup:

```bash
omarchy-shell shell rescanPlugins
omarchy plugin enable hjhayes3.spotify-connect --section right
journalctl --user -f | grep -i omarchy-shell
```

Changes under the installed user plugin directory hot-reload. If they do not,
run `omarchy restart shell`.

## API references

- [Authorization Code with PKCE](https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow)
- [Redirect URI requirements](https://developer.spotify.com/documentation/web-api/concepts/redirect_uri)
- [Get Available Devices](https://developer.spotify.com/documentation/web-api/reference/get-a-users-available-devices)
- [Get Playback State](https://developer.spotify.com/documentation/web-api/reference/get-information-about-the-users-current-playback)
- [Transfer Playback](https://developer.spotify.com/documentation/web-api/reference/transfer-a-users-playback)

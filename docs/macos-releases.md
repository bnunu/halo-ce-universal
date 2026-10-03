# Mac downloads and updates

The **macOS DMG** workflow builds an Apple Silicon app from the repository and
uploads `halo-macos-arm64-dmg` to the workflow run. It runs on branch pushes,
pull requests, and manual dispatches without signing secrets. GitHub retains
these artifacts for 14 days; downloading an Actions artifact requires a GitHub
account. Game data and local data paths are excluded.

These ordinary downloads are ad-hoc signed and are not notarized. Automatic
installation of updates is disabled even if the checkout contains release keys'
public configuration. **Download Mac Builds…** in the Halo menu opens the Mac
workflow in the repository recorded by the build. CI passes its actual
`GITHUB_REPOSITORY`; a local build defaults to the repository in
`port/macos/release-config.json`, or accepts `--repository owner/name`.

The separate **Publish signed macOS update** workflow is manually dispatched
from `main`. Once a maintainer configures it, it builds a Developer ID signed
app, notarizes the app and DMG, and signs both the update archive and appcast
with Sparkle. It has no push or pull-request publication trigger.

## GitHub release layout

Signed archives are published at immutable versioned URLs:

```text
https://github.com/OWNER/REPOSITORY/releases/download/macos-build-BUILD/Halo-CE-Universal-VERSION-macos-arm64.dmg
```

The update feed has a stable URL in a dedicated prerelease:

```text
https://github.com/OWNER/REPOSITORY/releases/download/macos-updates/appcast.xml
```

Every Mac release explicitly uses GitHub's `make_latest: false`. The feed tag is
also a prerelease. Neither the existing Windows launcher's latest-release link
nor the main Linux/Windows/Android build workflow is changed. The `macos-build-*`
prefix is separate from that workflow's `build-*` retention policy. Mac archives
are not automatically deleted; retained appcast entries must remain downloadable.

No GitHub Pages site, S3 bucket, or additional update server is required.

## Maintainer setup

The checked-in configuration starts with `feed_url` and `public_update_key` set
to `null`, so it does not claim an update service is already deployed. In the
target repository, set these non-secret values in
`port/macos/release-config.json`:

```json
{
  "github_repository": "OWNER/REPOSITORY",
  "channel_tag": "macos-updates",
  "feed_url": "https://github.com/OWNER/REPOSITORY/releases/download/macos-updates/appcast.xml",
  "public_update_key": "YOUR_EXISTING_SPARKLE_PUBLIC_KEY"
}
```

Use the actual repository receiving the contribution. The signed workflow
refuses a mismatch between this configuration and `GITHUB_REPOSITORY`, and
refuses a branch other than `main`. The appcast URL must exactly match that
repository's dedicated Mac channel.

Configure these GitHub Actions secrets in the `macos-release` environment or
repository. Environment protection rules can restrict who publishes updates.

| Secret | Existing credential supplied by the maintainer |
| --- | --- |
| `MACOS_CERTIFICATE_BASE64` | Base64 export of the Developer ID Application certificate and its private key in a password-protected `.p12`. |
| `MACOS_CERTIFICATE_PASSWORD` | Password for that `.p12`. |
| `MACOS_SIGN_IDENTITY` | Exact `Developer ID Application: …` signing identity. |
| `MACOS_NOTARY_KEY_ID` | App Store Connect API key ID authorized for notarization. |
| `MACOS_NOTARY_ISSUER_ID` | Issuer ID for that API key. |
| `MACOS_NOTARY_PRIVATE_KEY` | Contents of the existing `.p8` API private key. |
| `SPARKLE_PRIVATE_KEY` | Base64 **32-byte seed** exported by Sparkle 2.10's key tool, matching the committed public key. Legacy expanded key formats are not accepted by this CI path. |

Use Sparkle's documented key setup and an approved secret manager to establish
and back up the key before configuring CI. No script in this contribution
generates, replaces, prints, or commits private signing keys. CI validates the
Sparkle public key derived with Apple's CryptoKit before signing, supplies the
seed to Sparkle over standard input, and suppresses credential-tool output.
Certificate and notary files are created with owner-only access outside the
checkout, imported into a temporary keychain, and removed. An `always()` cleanup
step restores the runner's keychain settings and deletes that temporary keychain.

After configuration, dispatch **Publish signed macOS update** on `main` with a
numeric display version such as `0.1.0`. Build numbers use that workflow's run
number and attempt, for example `12.1`. They must increase relative to the feed.
Rerunning an older workflow after a newer release is published will be rejected
by the feed's downgrade check; dispatch a new run instead.

For a local maintainer release, use existing Developer ID and notary Keychain
credentials, and an existing Sparkle key under account `local.halo.ce-universal`:

```sh
python3 tools/macos_release.py check-config --repository OWNER/REPOSITORY
python3 tools/macos_release.py build --version 0.1.0 --build-number 12.1 \
  --sign-identity 'Developer ID Application: YOUR IDENTITY' \
  --notary-profile YOUR_EXISTING_PROFILE --repository OWNER/REPOSITORY
```

This prepares files under `build/macos/releases/12.1/`; it does not publish them.
Publication is a separate explicit command using an authenticated GitHub CLI:

```sh
python3 tools/macos_release.py publish-github build/macos/releases/12.1 \
  --repository OWNER/REPOSITORY
```

## Verification and interrupted publication

The release tool checks the archive hash and size, its code signature and
stapled notarization ticket, the configured Sparkle key, and the archive's EdDSA
signature before publishing. It creates a draft versioned release, uploads the
archive and public verification records, then publishes it without changing
GitHub's latest release. It downloads and hashes the public archive before
changing the feed.

Only then does it replace `appcast.xml`. The feed is signed and verified, and the
signed app requires both `SURequireSignedFeed` and
`SUVerifyUpdateBeforeExtraction`. Before extending a previous feed, the tool
verifies its signature, rejects older build numbers and conflicting archives for
an existing build, and keeps up to ten entries for clients on older macOS versions.
The app defers installation until the game quits normally.

Retries reuse an existing versioned asset only when GitHub reports the same
SHA-256 and size; they never overwrite an archive. A release tag pointing at
another source commit is rejected. An interrupted draft feed can be recovered
through the authenticated assets API. Replacing a GitHub asset is not atomic:
the feed can briefly return 404 while its previous asset is removed and the new
one is uploaded. Clients fail closed and can check again; the immutable archive
is already available. If final public feed verification is stale or fails, rerun
`publish-github` for the same prepared release instead of deleting its archive.

## Tests and current limits

```sh
python3 -m unittest tools.test_macos_release tools.test_macos_menu.ReleaseBoundary tools.test_macos_build
```

These tests use authored files and mocked signing/GitHub services to cover
repository checks, key matching and secret redaction, archive tampering, signed
feed handling, downgrade refusal, immutable retries, publication order, and
preservation of GitHub's latest release. Mac native preference/import tests cover
the download URL validator separately. No production signing key, Apple
notarization submission, live release, or successful client update is established
by those tests. A maintainer must validate the signed workflow and an actual
old-to-new application update after configuring real credentials.

The implementation follows [Sparkle's publishing instructions](https://sparkle-project.org/documentation/publishing/),
its [signed-feed documentation](https://sparkle-project.org/documentation/customization/),
and [GitHub's release API](https://docs.github.com/en/rest/releases/releases).

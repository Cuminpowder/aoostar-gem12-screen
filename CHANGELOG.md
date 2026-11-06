# Changelog

All notable changes to this project. Format follows
[Keep a Changelog](https://keepachangelog.com/); versions are SemVer-ish.

## [0.2.0] — 2026-11-06

### Added

- **Appearance editor in the web UI** — header, tagline and the three colours can
  now be changed from the page instead of a text editor. `GET/POST /api/settings`
  persists exactly those five keys into `config.json` (credentials untouched) and
  re-pushes the panel. A failed push is reported, not swallowed.
- **`lang` config key** (`en` / `zh`) and a complete Chinese interface. One
  template serves both languages; only visible labels change.

### Changed

- Branding is fully config-driven: `header`, `tagline`, `header_color`,
  `label_color`, `caption_color`. The default header is the neutral `GEM12`, and
  the README diagram no longer shows one person's theme.
- README gained a **Make it yours** section (English + 中文) documenting every
  appearance key, and states plainly that no artwork is bundled — the screenshot
  is just one user's personal setup.

### Security

- Removed the vendor agent's factory credentials from the README, the example
  config and the code defaults. Empty credentials now raise a clear error instead
  of silently logging in with a known default.
- Added a note that `:5123` should stay on localhost or the LAN.

### Fixed

- The live deployment runs this repository's code again (config-driven) rather
  than a private fork, so updates are a `git pull` away.

## [0.1.0] — 2026-11-05

- First public release: three layouts, avatar-style cropping, WYSIWYG preview,
  rotation, two backends (asterctl / vendor), reverse-engineered protocol notes.

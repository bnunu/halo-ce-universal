# App icon source

`AppIcon.png` reuses the 1024 × 1024 image originally created for the Apple port
on September 27, 2026. It was adapted with the image-generation tool from
Halo artwork supplied by the user, preserving the green helmet, gold visor
and blue ring background, with no typography or pre-rendered rounded corners.

The Mac packaging tool creates the standard and Retina icon sizes from this
file and embeds them in `AppIcon.icns`. Keeping this source under `port/macos/`
allows Mac builds without an iOS source tree. `Helmet.svg` is the separate,
editable monochrome menu-bar icon.

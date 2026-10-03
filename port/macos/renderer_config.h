#ifndef HALO_MACOS_RENDERER_CONFIG_H
#define HALO_MACOS_RENDERER_CONFIG_H

/* Content verification prevents stale map geometry, but the measured cache
   did not improve frame time. Keep streaming as the stable default. Set this
   to 1 for a local cache experiment and rerun the upload/map-change checks. */
#ifndef HALO_MACOS_GEOMETRY_CACHE
#define HALO_MACOS_GEOMETRY_CACHE 0
#endif

#endif

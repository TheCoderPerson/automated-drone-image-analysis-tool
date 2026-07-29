# Vendored Leaflet 1.9.4

`leaflet.js`, `leaflet.css`, and `images/`, copied verbatim from
`https://unpkg.com/leaflet@1.9.4/dist/`. Leaflet is BSD-2-Clause licensed;
the upstream copyright header is preserved inside `leaflet.js`.

`images/` holds the icons `leaflet.css` references relatively
(`layers.png`, `layers-2x.png`, `marker-icon.png`). Because the stylesheet
is *inlined* into the map page, those relative URLs would resolve against
the page's base URL and 404 — which blanked the basemap-selector button.
`FlightMapView._inline_css_images` rewrites them to `data:` URIs at load
time, so keep the directory populated when updating.

## Why these are in the repo

The map widget used to pull Leaflet from unpkg.com at runtime. That makes a
core piece of UI depend on a CDN round-trip *every time a map is opened* —
and ADIAT is used in the field, on hotspots and marginal connectivity. When
the fetch failed the whole widget was replaced by an error message, even
though everything else about the map (aircraft marker, flight path,
detection pins) would have worked fine.

These files are inlined into the map page at build time by
`core.views.components.FlightMapView`, so the widget always renders.

## What this does and does not fix

Basemap **tiles** still come from OpenStreetMap / Esri over the network — an
offline machine gets a dark canvas rather than imagery. But the map itself
initializes, the controls work, and the aircraft marker, flight path, and
detection pins all draw. That is a large functional difference from "no map
at all".

## Updating

Replace both files from the same upstream version and update the version in
this README and in `FlightMapView.LEAFLET_VERSION`. No build step or
minification is applied — the files are used exactly as downloaded.

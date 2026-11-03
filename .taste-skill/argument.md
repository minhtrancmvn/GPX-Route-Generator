# App-screen argument: GPX Route Generator

## Screen question
How do I turn this GPX track into a route video, and is render progressing?

## Claims and proof
- This workspace converts a GPX upload to a rendered MP4 — product title and action-focused intro.
- A route-specific image can be checked before committing map requests — first-frame preview and updating format badge.
- Output framing, duration, and frame rate are selectable — existing landscape/portrait radios and numeric inputs.
- Optional appearance and overlay settings remain available without crowding the primary path — collapsed customization details.
- Render is in progress, complete, or failed — status heading, accessible progress bar, request estimate, live message, and final video/download.

## Subject inventory
- GPX track file.
- First-frame preview from `/api/preview`.
- Google Static Maps image request estimate.
- Landscape 1280 × 720 output.
- Portrait 720 × 1280 output.
- Duration 5–30 seconds.
- FPS range 1–60.
- Trail color, width, avatar, and avatar size.
- Progress, distance, speed, and elevation overlays.
- Render job status, final MP4 video, and download link.

## Idea
On this page, a GPX track becomes a route proof sheet: choose file, inspect the actual first frame, then render.

## Design direction
Route Atlas Studio. Calm route-editor surfaces around a dark, focused preview stage. Real preview itself provides visual richness; no synthetic map or fake status data. Mobile order places preview first. DM Sans supplies headings and Source Sans 3 supplies body, labels, and tabular figures. One muted survey-paper ground, one blue action hue, and restrained data/action color outside the preview.

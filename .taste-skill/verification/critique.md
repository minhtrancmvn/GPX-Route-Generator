# Production UI visual verification

## Screen question
How do I turn this GPX track into a route video, and is rendering progressing?

## Final screenshot review
- Desktop: settings occupy 380px, gap 24px, preview occupies remaining 836px of 1240px shell at 1440px viewport. Header and workspace share edges. Upload, format, duration, FPS, customization disclosure, and Render MP4 remain visible at 1440 × 900.
- Tablet and phone: preview precedes settings. Both panels keep equal gutters; 390px screenshot shows complete preview and start of upload workflow. Lower settings remain available by vertical scrolling, not horizontal scrolling.
- Subject-specific element: actual first-frame PNG and completed MP4 occupy selected output aspect ratio. No fabricated map, render counts, or route data inserted into production page.
- Color: survey-paper ground, flat light panels, dark preview, one route-blue action/selection hue. Dark variant uses neutral surfaces, not blue panels. No resting shadows or ornamental gradients.
- Numbers: zero progress and map requests remain zero in empty state. Format badge agrees with landscape/portrait controls. Numeric metadata uses tabular figures.
- Repeated panels are functional settings/preview containers, not a row of decorative cards. Their heights follow content.
- Screen contains no chart or legend; chart palette/legend checks do not apply.

## Browser assertions
- Widths 1440, 768, 390, and 320: both landscape 16:9 and portrait 9:16 stage geometry pass, no document horizontal overflow, empty-state content fits stage.
- Widths 390 and 320: numeric fields and customization summary have minimum 44px targets.
- Long synthetic filename wraps at 390px; upload focus outline is visible, solid, 3px.
- System dark, explicit light overriding dark, and explicit dark overriding light all select correct backgrounds.
- Button contrast: light 6.39:1, dark 7.20:1. Download contrast: light 5.82:1, dark 9.05:1. Panel-label contrast: light 6.07:1, dark 8.79:1.
- Reduced-motion spinner duration becomes 0.00001 seconds; no uncaught browser exceptions in layout checks.

## Findings fixed during verification
1. 320px landscape empty-state content clipped. Hide optional empty-state icon at widths up to 360px; instructions and stage ratio retained. Recheck passes.
2. Dark action backgrounds originally paired with white foregrounds. Explicit action foreground tokens now give contrast ratios above 4.5:1.
3. Portrait stage previously inherited landscape responsive ratio. Landscape-only responsive selector now excludes portrait; all eight width/format combinations pass.

## Source lint warnings retained
- Three eyebrow source matches represent two sentence-case panel labels plus their shared style. Labels identify settings and route preview while adjacent preview heading changes with job status. No marketing kicker or uppercase ornament.
- One box-shadow match is focus-only outline feedback, not resting elevation. Keyboard focus is intentional.

## Limits
Layout checks simulate long filename without uploading route data. Separate browser smoke owns actual upload, preview, render, polling, playback, download, and invalid-file recovery. Local offline map client substitutes map provider imagery only; production provider integration is unchanged and not live-tested here. Screenshots under before/ captured corrupt intermediate template and must not be treated as clean baseline.

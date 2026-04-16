# MATLAB API Notes

## Construction and Lifecycle

```matlab
cine = Cine(fullfile('<repo>', 'sample_data', 'TrimmedCine.cine'), ...
    'RemoveDeadPixels', false, 'Debayer', false);
first = cine.FileHeader.FirstImageNo;
cine.LoadFrame(first);
img = cine.PixelArray;
```

- `Cine(filename, 'RemoveDeadPixels', false, 'Debayer', false, 'DeadValue', [], 'BayerPattern', 'auto')`
  - `'RemoveDeadPixels'`: repair dead pixels on every `LoadFrame`.
  - `'Debayer'`: debayer raw CFA/Bayer frames on every `LoadFrame`.
- `OpenCineFile(filename)`
- `LoadFrame(frame_no)`
  - raw CFA/Bayer payloads stay 2D unless `'Debayer', true` or `DebayerFrame` is used.
- `NextFrame(increment)`
- `CloseFile()`
- `RedPixels` / `GreenPixels` / `BluePixels`
  - empty for mono frames.
  - for raw CFA/Bayer color frames, `[H x W]` single arrays with actual sensor samples at that color's sites and `NaN` elsewhere.

## Processing

- `ReplaceDeadPixels(dead_value)`
  - repairs mono frames directly
  - repairs raw CFA/Bayer frames by 2x2 phase before demosaic
  - repairs RGB frames channel-wise
- `DebayerFrame(bayer_pattern)`
  - mutates the current raw CFA/Bayer `PixelArray` into RGB `[H x W x 3]`.
- `GetFrameRGB(frame_no, bayer_pattern)`

## Statistics

- `AverageFrames(start_frame, end_frame, replace, chunk_size)`
  - Chunked accumulation for improved performance.
- `ModeFrames(start_frame, end_frame, replace, 'name', value, ...)`
  - `'method'`: `'auto' | 'mad' | 'topk'`
  - `'q_bg'`: bright quantile baseline
  - `'k_sigma'`: MAD scale (mad path)
  - `'min_keep'`, `'max_keep'`, `'stack_limit'`

## Batch and Trim

- `LoadFramesBatch(start_frame, count)`
- `SaveFramesToNewFile(output_filename, start_frame, end_frame)`

## Private Helper Files

`Matlab/private/` contains split helpers used by `Cine.m`:
- `cine_replace_dead_pixels.m`
- `cine_demosaic_bilinear.m`
- `cine_mode_mad_stack.m`

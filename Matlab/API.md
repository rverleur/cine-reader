# MATLAB API Notes

## Construction and Lifecycle

```matlab
cine = Cine(fullfile('<repo>', 'sample_data', 'TrimmedCine.cine'));
first = cine.FileHeader.FirstImageNo;
cine.LoadFrame(first);
img = cine.PixelArray;
```

- `OpenCineFile(filename)`
- `LoadFrame(frame_no)`
- `NextFrame(increment)`
- `CloseFile()`

## Processing

- `ReplaceDeadPixels(dead_value)`
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

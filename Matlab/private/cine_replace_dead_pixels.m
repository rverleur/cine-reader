function out = cine_replace_dead_pixels(frame, dead_value, bayer_raw)
%CINE_REPLACE_DEAD_PIXELS Repair dead pixels through the Rust backend.
if nargin < 2, dead_value = 4095; end
if nargin < 3, bayer_raw = false; end
op = 1;
if bayer_raw && ismatrix(frame), op = 2; end
out = cine_backend('process', frame, op, 256, double(dead_value));
end

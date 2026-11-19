function rgb = cine_demosaic_bilinear(frame, pattern)
%CINE_DEMOSAIC_BILINEAR Bilinear demosaic through the shared Rust backend.
if nargin < 2 || isempty(pattern), pattern = 'RGGB'; end
patterns = ["RGGB", "BGGR", "GRBG", "GBRG"];
code = find(patterns == upper(string(pattern)), 1) - 1;
if isempty(code), error('cine:pattern', 'Unsupported Bayer pattern.'); end
rgb = cine_backend('process', frame, 3, code + 256, 0);
end

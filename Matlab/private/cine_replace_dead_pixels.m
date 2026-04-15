function out = cine_replace_dead_pixels(frame, dead_value, bayer_raw)
% CINE_REPLACE_DEAD_PIXELS Replace dead pixels in mono, Bayer, or RGB frames.
%   out = cine_replace_dead_pixels(frame, dead_value, bayer_raw)

if nargin < 2
    dead_value = uint16(4095);
end
if nargin < 3
    bayer_raw = false;
end

if ndims(frame) == 3
    out = frame;
    for ch = 1:size(frame, 3)
        out(:,:,ch) = cine_replace_dead_pixels(frame(:,:,ch), dead_value, false);
    end
    return;
end

if ndims(frame) ~= 2
    out = frame;
    return;
end

origClass = class(frame);
deadMask = frame == dead_value;
if ~any(deadMask, 'all')
    out = frame;
    return;
end

if bayer_raw
    out = frame;
    for rowPhase = 1:2
        for colPhase = 1:2
            rows = rowPhase:2:size(frame, 1);
            cols = colPhase:2:size(frame, 2);
            out(rows, cols) = cine_replace_dead_pixels(frame(rows, cols), dead_value, false);
        end
    end
    return;
end

frameF = single(frame);
valid = ~deadMask;
values = frameF;
values(~valid) = 0;
validF = single(valid);

pv = padarray(values, [1 1], 0, 'both');
pm = padarray(validF, [1 1], 0, 'both');

nbrSum = ...
    pv(1:end-2,1:end-2) + pv(1:end-2,2:end-1) + pv(1:end-2,3:end) + ...
    pv(2:end-1,1:end-2) +                         pv(2:end-1,3:end) + ...
    pv(3:end,  1:end-2) + pv(3:end,  2:end-1) + pv(3:end,  3:end);

nbrCnt = ...
    pm(1:end-2,1:end-2) + pm(1:end-2,2:end-1) + pm(1:end-2,3:end) + ...
    pm(2:end-1,1:end-2) +                         pm(2:end-1,3:end) + ...
    pm(3:end,  1:end-2) + pm(3:end,  2:end-1) + pm(3:end,  3:end);

outF = frameF;
repMask = deadMask & (nbrCnt > 0);
outF(repMask) = nbrSum(repMask) ./ nbrCnt(repMask);
out = cast(outF, origClass);
end

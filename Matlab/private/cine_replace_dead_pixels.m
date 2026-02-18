function out = cine_replace_dead_pixels(frame, dead_value)
% CINE_REPLACE_DEAD_PIXELS Replace dead pixels in a mono frame.
%   out = cine_replace_dead_pixels(frame, dead_value)

if nargin < 2
    dead_value = uint16(4095);
end

if ndims(frame) ~= 2
    out = frame;
    return;
end

origClass = class(frame);
frameF = single(frame);
deadMask = frame == dead_value;
if ~any(deadMask, 'all')
    out = frame;
    return;
end

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

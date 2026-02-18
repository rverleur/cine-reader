function rgb = cine_demosaic_bilinear(frame, pattern)
% CINE_DEMOSAIC_BILINEAR Bilinear Bayer demosaic.
%   rgb = cine_demosaic_bilinear(frame, pattern)

if nargin < 2 || isempty(pattern)
    pattern = "RGGB";
end

inClass = class(frame);
frame = single(frame);
[h,w] = size(frame);
[yy,xx] = ndgrid(0:h-1, 0:w-1);
evenR = mod(yy,2)==0;
evenC = mod(xx,2)==0;

pad = frame([1,1:h,h], [1,1:w,w]);
c  = pad(2:end-1, 2:end-1);
up = pad(1:end-2, 2:end-1);
dn = pad(3:end  , 2:end-1);
lf = pad(2:end-1, 1:end-2);
rt = pad(2:end-1, 3:end  );
ul = pad(1:end-2, 1:end-2);
ur = pad(1:end-2, 3:end  );
dl = pad(3:end  , 1:end-2);
dr = pad(3:end  , 3:end  );

p = upper(string(pattern));
if p=="RGGB"
    rMask = evenR & evenC;
    bMask = ~evenR & ~evenC;
    gRMask = evenR & ~evenC;
    gBMask = ~evenR & evenC;
elseif p=="BGGR"
    bMask = evenR & evenC;
    rMask = ~evenR & ~evenC;
    gBMask = evenR & ~evenC;
    gRMask = ~evenR & evenC;
elseif p=="GRBG"
    gRMask = evenR & evenC;
    rMask = evenR & ~evenC;
    bMask = ~evenR & evenC;
    gBMask = ~evenR & ~evenC;
elseif p=="GBRG"
    gBMask = evenR & evenC;
    bMask = evenR & ~evenC;
    rMask = ~evenR & evenC;
    gRMask = ~evenR & ~evenC;
else
    error('Unsupported Bayer pattern: %s', char(p));
end

r = zeros(h,w,'single'); g = r; b = r;
gCross = (up + dn + lf + rt) * 0.25;
rbDiag = (ul + ur + dl + dr) * 0.25;
lr = (lf + rt) * 0.5;
ud = (up + dn) * 0.5;

r(rMask) = c(rMask);   g(rMask) = gCross(rMask); b(rMask) = rbDiag(rMask);
b(bMask) = c(bMask);   g(bMask) = gCross(bMask); r(bMask) = rbDiag(bMask);
g(gRMask) = c(gRMask); r(gRMask) = lr(gRMask);   b(gRMask) = ud(gRMask);
g(gBMask) = c(gBMask); r(gBMask) = ud(gBMask);   b(gBMask) = lr(gBMask);

rgb = cat(3, r, g, b);
rgb = cast(round(rgb), inClass);
end

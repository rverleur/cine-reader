function rgb = cine_demosaic_bilinear(frame, pattern)
% CINE_DEMOSAIC_BILINEAR Bilinear Bayer demosaic.
%   rgb = cine_demosaic_bilinear(frame, pattern)

if nargin < 2 || isempty(pattern)
    pattern = "RGGB";
end

inClass = class(frame);
frame = single(frame);
[h,w] = size(frame);

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
switch p
    case "RGGB"
        phases = {1, 1, 'R'; 1, 2, 'G_R'; 2, 1, 'G_B'; 2, 2, 'B'};
    case "BGGR"
        phases = {1, 1, 'B'; 1, 2, 'G_B'; 2, 1, 'G_R'; 2, 2, 'R'};
    case "GRBG"
        phases = {1, 1, 'G_R'; 1, 2, 'R'; 2, 1, 'B'; 2, 2, 'G_B'};
    case "GBRG"
        phases = {1, 1, 'G_B'; 1, 2, 'B'; 2, 1, 'R'; 2, 2, 'G_R'};
    otherwise
        error('Unsupported Bayer pattern: %s', char(p));
end

gCross = (up + dn + lf + rt) * 0.25;
rbDiag = (ul + ur + dl + dr) * 0.25;
lr = (lf + rt) * 0.5;
ud = (up + dn) * 0.5;

rgb = zeros(h, w, 3, 'single');
for k = 1:size(phases, 1)
    rows = phases{k, 1}:2:h;
    cols = phases{k, 2}:2:w;
    role = phases{k, 3};

    switch role
        case 'R'
            rgb(rows, cols, 1) = c(rows, cols);
            rgb(rows, cols, 2) = gCross(rows, cols);
            rgb(rows, cols, 3) = rbDiag(rows, cols);
        case 'B'
            rgb(rows, cols, 1) = rbDiag(rows, cols);
            rgb(rows, cols, 2) = gCross(rows, cols);
            rgb(rows, cols, 3) = c(rows, cols);
        case 'G_R'
            rgb(rows, cols, 1) = lr(rows, cols);
            rgb(rows, cols, 2) = c(rows, cols);
            rgb(rows, cols, 3) = ud(rows, cols);
        case 'G_B'
            rgb(rows, cols, 1) = ud(rows, cols);
            rgb(rows, cols, 2) = c(rows, cols);
            rgb(rows, cols, 3) = lr(rows, cols);
    end
end

rgb = cast(round(rgb), inClass);
end

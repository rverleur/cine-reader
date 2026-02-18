function out = cine_mode_mad_stack(stack, q_bg, k_sigma, min_keep)
% CINE_MODE_MAD_STACK Quantile/MAD robust background from frame stack.
%   stack shape: [T H W] (single/double)

if nargin < 2 || isempty(q_bg), q_bg = 0.80; end
if nargin < 3 || isempty(k_sigma), k_sigma = 2.5; end
if nargin < 4 || isempty(min_keep), min_keep = 3; end

bg = prctile(stack, q_bg * 100, 1);
med = median(stack, 1);
mad = median(abs(stack - med), 1);
sigma = max(1.4826 * mad, 1e-6);
keep = stack >= (bg - k_sigma * sigma);

num = sum(stack .* keep, 1);
den = sum(keep, 1);
out = squeeze(bg);
num2 = squeeze(num);
den2 = squeeze(den);
mask = den2 >= min_keep;
out(mask) = num2(mask) ./ den2(mask);
out = uint16(max(0, min(double(intmax('uint16')), round(out))));
end

function build_mex_unpack10bit_cached
% Build private/mex_unpack10bit_cached.c for current platform.
% Linux links libdl automatically.

try, mex('-setup','C'); catch, end
src = fullfile('private','mex_unpack10bit_cached.c');
args = {'-v', src, 'CFLAGS=$CFLAGS -O3 -fPIC'};

if isunix && ~ismac, args{end+1} = '-ldl'; end
mex(args{:});
end

% Smoke test for MATLAB Cine reader

repoRoot = fileparts(mfilename('fullpath'));
cinePath = fullfile(repoRoot, '..', 'sample_data', 'TrimmedCine.cine');
cine = Cine(cinePath);
first = cine.FileHeader.FirstImageNo;
last  = first + int32(cine.FileHeader.ImageCount) - 1;

cine.LoadFrame(first);
assert(~isempty(cine.PixelArray), 'PixelArray should not be empty');

avg = cine.AverageFrames(first, min(first + 5, last), false);
assert(~isempty(avg), 'AverageFrames failed');

bg = cine.ModeFrames(first, min(first + 5, last), false);
assert(~isempty(bg), 'ModeFrames failed');

disp('MATLAB cine smoke test passed.');

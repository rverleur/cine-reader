% Basic MATLAB usage for Cine.m

repoRoot = fileparts(fileparts(fileparts(mfilename('fullpath'))));
cinePath = fullfile(repoRoot, 'sample_data', 'TrimmedCine.cine');
cine = Cine(cinePath);
first = cine.FileHeader.FirstImageNo;
last  = first + int32(cine.FileHeader.ImageCount) - 1;

fprintf('Frames: %d (%d..%d)\n', cine.FileHeader.ImageCount, first, last);
fprintf('Resolution: %d x %d\n', cine.ImageHeader.biWidth, abs(cine.ImageHeader.biHeight));

cine.LoadFrame(first);
imshow(cine.PixelArray, [], 'Border', 'tight');

avg = cine.AverageFrames(first, min(first + 10, last), false);
bg  = cine.ModeFrames(first, min(first + 20, last), false);
rgb = cine.GetFrameRGB(first, 'RGGB');

cine.SaveFramesToNewFile('trimmed_out.cine', first, min(first + 20, last));

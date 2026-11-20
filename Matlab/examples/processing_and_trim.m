% Stream statistics, estimate a background, and trim without re-encoding.
% Leave inputFile empty for a generated mono recording, or select your file.
inputFile = '';
maximumFrames = 20;
maximumBackgroundSamples = 8;
outputFile = [tempname '.cine']; % Existing destinations are never overwritten.

addpath(fileparts(fileparts(mfilename('fullpath'))));
if isempty(inputFile)
    inputFile = [tempname '.cine'];
    base = uint16(reshape(0:3071, 48, 64));
    write_cine(inputFile, {base, base + 10, base + 20, base + 30}, 'FirstFrame', -2);
end
cine = Cine(inputFile, 'RemoveDeadPixels', false);
cleanupReader = onCleanup(@() delete(cine));
first = double(cine.FileHeader.FirstImageNo);
last = first + min(maximumFrames, double(cine.FileHeader.ImageCount)) - 1;
meanImage = cine.AverageFrames(first, last); % One running accumulator.
fprintf('Mean image: %s\n', mat2str(size(meanImage)));
if size(meanImage, 3) == 1
    % ModeFrames is a robust bright-background estimate, not an exact histogram mode.
    % topk bounds retained samples per pixel; mad retains the selected stack.
    background = cine.ModeFrames(first, last, false, 'method', 'topk', ...
                                 'max_keep', maximumBackgroundSamples);
    cine.LoadFrame(first);
    difference = double(cine.PixelArray) - double(background);
    fprintf('Background-subtracted range: %.1f..%.1f\n', min(difference, [], 'all'), ...
            max(difference, [], 'all'));
end
cine.SaveFramesToNewFile(outputFile, first, last); % Inclusive global frame range.
cine.CloseFile();
clear cleanupReader;
fprintf('Trimmed recording: %s\n', outputFile);

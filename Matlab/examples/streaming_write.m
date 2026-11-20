% Encode synthetic frames one at a time in normal and packed10 formats.
% A new directory avoids replacing files from earlier example runs.
outputDirectory = tempname;
width = 64;
height = 48;
frameCount = 12;
frameRate = 1000;

addpath(fileparts(fileparts(mfilename('fullpath'))));
mkdir(outputDirectory);
for packed10 = [false true]
    outputFile = fullfile(outputDirectory, sprintf('mono_packed_%d.cine', packed10));
    writer = CineWriter(outputFile, width, height, 'BitDepth', 12, ...
                        'Packed10', packed10, 'FrameRate', frameRate, ...
                        'FrameCount', frameCount, 'FirstFrame', -3);
    cleanupWriter = onCleanup(@() delete(writer)); % Abort if an error interrupts the loop.
    for index = 1:frameCount
        frame = uint16(mod(reshape(0:width * height - 1, height, width) + index * 20, 4096));
        writer.WriteFrame(frame); % Top-down rows; only this frame is retained here.
    end
    writer.Close(); % Finalizes and publishes; required for successful output.
    clear cleanupWriter;
    fprintf('Wrote %d frames: %s\n', frameCount, outputFile);
end

% Unknown lengths use FrameCount=0 and a temporary disk spool, not a RAM stack.
% Normal RGB keeps all channels; packed10 RGB samples a Bayer mosaic and is lossy.
writer = CineWriter(fullfile(outputDirectory, 'rgb_unknown_length.cine'), width, height, ...
                    'Channels', 3, 'BitDepth', 8, 'FrameCount', 0, 'FrameRate', frameRate);
cleanupWriter = onCleanup(@() delete(writer));
for index = 1:frameCount
    plane = uint8(mod(reshape(0:width * height - 1, height, width) + index, 256));
    writer.WriteFrame(cat(3, plane, fliplr(plane), flipud(plane))); % RGB input.
end
writer.Close();
clear cleanupWriter;
fprintf('Examples saved in %s\n', outputDirectory);

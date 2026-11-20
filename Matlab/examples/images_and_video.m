% Stream an ordered image list or an existing video into normal/packed10 CINE.
% Empty inputs generate a short demo; set imageFiles/videoFile to your own paths.
imageFiles = {};
videoFile = '';
outputDirectory = tempname;
frameRate = 25;
packed10 = false;

addpath(fileparts(fileparts(mfilename('fullpath'))));
mkdir(outputDirectory);
if isempty(imageFiles)
    imageFiles = cell(1, 3);
    for index = 1:3
        plane = uint8(mod(reshape(0:3071, 48, 64) + index * 20, 256));
        imageFiles{index} = fullfile(outputDirectory, sprintf('input_%04d.png', index));
        imwrite(cat(3, plane, fliplr(plane), flipud(plane)), imageFiles{index});
    end
end
% Supply paths in the intended frame order; uint8/uint16 types are inferred.
write_cine(fullfile(outputDirectory, 'from_images.cine'), imageFiles, ...
           'FrameRate', frameRate, 'Packed10', packed10);

if isempty(videoFile)
    videoFile = fullfile(outputDirectory, 'input.avi');
    videoWriter = VideoWriter(videoFile, 'Motion JPEG AVI');
    videoWriter.FrameRate = frameRate;
    open(videoWriter);
    cleanupVideo = onCleanup(@() close(videoWriter));
    for index = 1:numel(imageFiles)
        writeVideo(videoWriter, imread(imageFiles{index}));
    end
    close(videoWriter);
    clear cleanupVideo;
end
% Uses MATLAB's installed video codecs and preserves VideoReader.FrameRate.
write_cine(fullfile(outputDirectory, 'from_video.cine'), VideoReader(videoFile), ...
           'Packed10', packed10);
fprintf('Image/video examples saved in %s\n', outputDirectory);

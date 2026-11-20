% Read metadata and individual frames; run this script from the MATLAB Editor.
% Leave inputFile empty for a small generated recording, or set a camera file.
inputFile = '';
showFigure = true;

matlabDirectory = fileparts(fileparts(mfilename('fullpath')));
addpath(matlabDirectory);
if isempty(inputFile)
    inputFile = [tempname '.cine'];
    demo = uint16(reshape(0:3071, 48, 64));
    write_cine(inputFile, {demo, demo + 1, demo + 2}, 'FirstFrame', -1, 'FrameRate', 1000);
    fprintf('Generated demonstration file: %s\n', inputFile);
end

cine = Cine(inputFile); % Opens metadata only; no frame stack is loaded.
cleanupReader = onCleanup(@() delete(cine));
first = double(cine.FileHeader.FirstImageNo);
count = double(cine.FileHeader.ImageCount);
last = first + count - 1;
fprintf('%d frames (%d..%d), %dx%d pixels, %.3f fps\n', count, first, last, ...
        cine.ImageHeader.biWidth, abs(cine.ImageHeader.biHeight), cine.CameraSetup.FrameRate);

cine.KeepAnnotations = true;
cine.LoadFrame(first); % Global frame numbers may be negative.
firstRawFrame = cine.RawPixelArray;
fprintf('First raw frame: %s, %s; annotation bytes: %d\n', ...
        mat2str(size(firstRawFrame)), class(firstRawFrame), numel(cine.AnnotationData));
if count > 1
    cine.NextFrame(); % Retains only the new current frame internally.
end

% Explicit batching allocates the requested stack: mono HxWxN, RGB HxWx3xN.
smallBatch = cine.LoadFramesBatch(first, min(3, count));
fprintf('Three-frame-or-smaller batch: %s\n', mat2str(size(smallBatch)));

% PixelArray preserves legacy storage rows and BGR channels. GetFrameRGB
% converts color order/demosaics raw Bayer; it does not change row orientation.
cine.LoadFrame(first);
if cine.CameraSetup.CFA ~= 0 || size(cine.PixelArray, 3) == 3
    preview = cine.GetFrameRGB();
else
    preview = cine.PixelArray;
end
if cine.ImageHeader.biHeight > 0
    preview = flipud(preview); % Positive height means stored bottom-up.
end
if showFigure
    figure;
    if ismatrix(preview)
        imagesc(preview);
        colormap(gray);
    else
        image(double(preview) / max(1, double(max(preview, [], 'all'))));
    end
    axis image;
    title('First frame, top-down display');
end
cine.CloseFile();
clear cleanupReader;

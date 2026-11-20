% Demonstrate raw Bayer repair, channel samples and demosaicing without toolboxes.
% Set inputFile to a raw Bayer camera recording, or use the generated RGGB file.
inputFile = '';
bayerPattern = 'auto'; % Also accepts RGGB, GRBG, GBRG, BGGR.
deadValue = 4095; % Only use a value known to identify defects in your recording.

addpath(fileparts(fileparts(mfilename('fullpath'))));
if isempty(inputFile)
    inputFile = [tempname '.cine'];
    sensor = uint16(ones(48, 64) * 800);
    sensor(1:2:end, 1:2:end) = 2400; % Red photosites in RGGB.
    sensor(2:2:end, 2:2:end) = 400; % Blue photosites.
    sensor(11, 11) = deadValue;
    write_cine(inputFile, {sensor}, 'CFA', 4, 'Packed10', true);
end
cine = Cine(inputFile, 'BayerPattern', bayerPattern);
cleanupReader = onCleanup(@() delete(cine));
assert(cine.CameraSetup.CFA ~= 0 && ismatrix(cine.PixelArray), 'Select a raw Bayer recording.');
raw = cine.RawPixelArray; % Preserved decoded input before processing.
cine.ReplaceDeadPixels(deadValue); % Uses same-color neighbors for raw CFA.
redSensorSamples = cine.RedPixels; % NaN at non-red sensor sites.
cine.DebayerFrame(); % Bilinear interpolation; no white balance or gamma applied.
rgb = cine.GetFrameRGB();
fprintf('Raw %s -> RGB %s; red sensor samples: %d\n', ...
        mat2str(size(raw)), mat2str(size(rgb)), nnz(~isnan(redSensorSamples)));
cine.CloseFile();
clear cleanupReader;

% To apply these steps on every read instead, construct with:
% Cine(inputFile, 'RemoveDeadPixels', true, 'DeadValue', deadValue, ...
%      'Debayer', true, 'BayerPattern', bayerPattern)

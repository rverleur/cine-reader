function write_cine(filename, frames, varargin)
    % WRITE_CINE Encode image paths, a cell array, or a VideoReader as CINE.
    %   write_cine('out.cine', {'a.png','b.png'}, 'FrameRate',100)
    %   write_cine('out.cine', VideoReader('input.mp4'))
    % Uses at most one decoded frame plus the Rust encoder buffers.
    if isa(frames, 'VideoReader')
        if ~hasFrame(frames)
            error('Input video contains no frames.');
        end
        first = readFrame(frames);
        if ~any(strcmpi(string(varargin(1:2:end)), 'FrameRate'))
            varargin = [{'FrameRate', frames.FrameRate}, varargin];
        end
        count = 0;
    elseif iscell(frames) || isstring(frames)
        if isempty(frames)
            error('At least one input image is required.');
        end
        first = loadImage(frames, 1);
        count = numel(frames);
    else
        error('Use a cell array of images or paths, a string array of paths, or a VideoReader.');
    end
    args = {'Channels', size(first, 3), 'BitDepth', 8 + 8 * isa(first, 'uint16'), 'FrameCount', count};
    writer = CineWriter(filename, size(first, 2), size(first, 1), args{:}, varargin{:});
    cleanup = onCleanup(@() delete(writer));
    writer.WriteFrame(first);
    if isa(frames, 'VideoReader')
        while hasFrame(frames)
            writer.WriteFrame(readFrame(frames));
        end
    else
        for k = 2:count
            writer.WriteFrame(loadImage(frames, k));
        end
    end
    writer.Close();
end

function image = loadImage(frames, k)
    if iscell(frames)
        image = frames{k};
    else
        image = frames(k);
    end
    if ischar(image) || isstring(image)
        [image, palette] = imread(image);
        if ~isempty(palette)
            image = uint8(255 * ind2rgb(image, palette));
        end
    end
end

classdef CineWriter < handle
    % CINEWRITER Streaming normal or packed10 CINE encoder using Rust.
    % writer = CineWriter(path, width, height, 'FrameRate', 1000, ...
    %     'FrameCount', 10, 'BitDepth', 12, 'Packed10', true);
    % writer.WriteFrame(uint16(image)); writer.Close();
    % Frames are top-down mono/Bayer or RGB uint8/uint16 arrays. Packed10
    % accepts linear 12-bit mono/Bayer samples and applies the Phantom LUT.
    % FrameCount=0 supports unknown-length streams. Close publishes output;
    % Abort and deleting an unfinished writer discard the temporary file.
    properties (SetAccess = private)
        filename string
        FramesWritten double = 0
    end
    properties (Access = private)
        Backend uint64 = uint64(0)
    end
    methods

        function obj = CineWriter(filename, width, height, varargin)
            opts = struct('Channels', 1, 'BitDepth', 8, 'Packed10', false, ...
                          'FrameCount', 0, 'FirstFrame', 0, 'CFA', 0, 'FrameRate', 30);
            if mod(numel(varargin), 2)
                error('CineWriter options must be name/value pairs.');
            end
            names = fieldnames(opts);
            for i = 1:2:numel(varargin)
                idx = find(strcmpi(string(varargin{i}), names), 1);
                if isempty(idx)
                    error('Unknown CineWriter option: %s', string(varargin{i}));
                end
                opts.(names{idx}) = varargin{i + 1};
            end
            if opts.Packed10
                opts.BitDepth = 12;
                if opts.Channels == 3
                    opts.Channels = 1;
                    if opts.CFA == 0
                        opts.CFA = 4;
                    end
                end
            end
            obj.filename = string(filename);
            values = double([width, height, opts.Channels, opts.BitDepth, opts.Packed10, ...
                             opts.FrameCount, opts.FirstFrame, opts.CFA, opts.FrameRate]);
            obj.Backend = cine_backend('writer_open', char(obj.filename), values);
        end

        function WriteFrame(obj, frame)
            if obj.Backend == 0
                error('CineWriter is closed.');
            end
            cine_backend('writer_write', obj.Backend, frame);
            obj.FramesWritten = obj.FramesWritten + 1;
        end

        function Close(obj)
            if obj.Backend ~= 0
                cine_backend('writer_finish', obj.Backend);
                obj.Backend = uint64(0);
            end
        end

        function Abort(obj)
            if obj.Backend ~= 0
                cine_backend('writer_close', obj.Backend);
                obj.Backend = uint64(0);
            end
        end

        function delete(obj)
            obj.Abort();
        end

    end
end

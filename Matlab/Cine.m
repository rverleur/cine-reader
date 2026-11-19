classdef Cine < handle
    %Cine Frame-wise Phantom CINE reader backed by the shared Rust library.
    % Construction reads metadata only; accessing the initial frame decodes it.
    % PixelArray preserves the legacy storage-row / BGR conventions.

    %% Public config
    properties
        filename          (1,1) string
        UseMemMap         (1,1) logical = true
        KeepAnnotations   (1,1) logical = false   % if true, stores AnnotationData each frame
        AssumeConstAnn    (1,1) logical = true    % assume constant annotation size (fast path)
        Debug             (1,1) logical = false   % extra checks (slower)
        RemoveDeadPixels  (1,1) logical = false   % repair pixels on every LoadFrame
        Debayer           (1,1) logical = false   % debayer raw CFA frames on every LoadFrame
        DeadValue                         = []     % [] means use default uint16(4095)
        BayerPattern      (1,1) string  = "auto"
    end

    %% Public state
    properties
        fid               (1,1) double = -1
        mm                                 % memmapfile
        FileHeader        struct
        ImageHeader       struct
        CurrentFrame      int32  = int32(0)

    end

    properties (Dependent)
        CameraSetup
        ImageLocations
        PixelArray
        RawPixelArray
        RedPixels
        GreenPixels
        BluePixels
        AnnotationSize
        AnnotationData
        Annotation
        ImageSize
    end

    properties (Access=private)
        SetupCache struct
        SetupDataPending logical = false
        Backend uint64 = uint64(0)
        PendingFrame logical = false
        LoadingFrame logical = false
        LocationsCache uint64 = uint64([])
        Pixels
        RawPixels
        Red
        Green
        Blue
        ColorSampleFrame
        ColorSamplesPending logical = false
        PixelsAreRGB logical = false
        AnnSize uint32 = uint32(0)
        AnnData uint8 = uint8([])
        Ann uint8 = uint8([])
        PayloadSize uint32 = uint32(0)
    end

    %% Lifecycle
    methods
        function obj = Cine(filename, varargin)
            if mod(numel(varargin), 2) ~= 0
                error('Cine name/value options must be pairs.');
            end
            for i = 1:2:numel(varargin)
                key = lower(string(varargin{i}));
                val = varargin{i+1};
                switch key
                    case "removedeadpixels"
                        obj.RemoveDeadPixels = logical(val);
                    case "debayer"
                        obj.Debayer = logical(val);
                    case "deadvalue"
                        obj.DeadValue = val;
                    case "bayerpattern"
                        obj.BayerPattern = string(val);
                    otherwise
                        error('Unknown Cine option: %s', char(key));
                end
            end
            if nargin
                obj.OpenCineFile(filename);
            end
        end
        function delete(obj)
            obj.releaseBackend();
        end
    end

    %% Public API
    methods
        function OpenCineFile(obj, filename)
            obj.releaseBackend();
            obj.filename = string(filename);
            [obj.Backend, obj.FileHeader, obj.ImageHeader, obj.SetupCache] = ...
                cine_backend('open', char(obj.filename));
            obj.SetupDataPending = true;
            obj.CurrentFrame = int32(obj.FileHeader.FirstImageNo);
            obj.LocationsCache = uint64([]);
            obj.Pixels = []; obj.RawPixels = [];
            obj.Red = []; obj.Green = []; obj.Blue = [];
            obj.ColorSampleFrame = []; obj.ColorSamplesPending = false;
            obj.AnnSize = uint32(0); obj.AnnData = uint8([]);
            obj.Ann = uint8([]); obj.PayloadSize = uint32(0);
            obj.PendingFrame = obj.FileHeader.ImageCount > 0;
        end

        function CloseFile(obj)
            % Preserve legacy post-close state, including deferred metadata.
            if obj.Backend == 0, return; end
            cleanup = onCleanup(@() obj.releaseBackend());
            obj.ensureFrame();
            if obj.SetupDataPending
                obj.SetupCache.SetupData = cine_backend('setup_data', obj.Backend);
                obj.SetupDataPending = false;
            end
            if isempty(obj.LocationsCache)
                obj.LocationsCache = cine_backend('offsets', obj.Backend);
            end
        end

        function NextFrame(obj, increment)
            if nargin<2, increment = 1; end
            validateattributes(increment, {'numeric'}, {'scalar','integer','finite'});
            obj.LoadFrame(double(obj.CurrentFrame) + double(increment));
        end

        function LoadFrame(obj, ImageNo)
            obj.requireOpen();
            [frame, obj.AnnSize, obj.PayloadSize, obj.AnnData] = ...
                cine_backend('read', obj.Backend, double(ImageNo), obj.KeepAnnotations);
            obj.CurrentFrame = int32(ImageNo);
            obj.PendingFrame = false;
            obj.LoadingFrame = true;
            cleanup = onCleanup(@() obj.endLoading());
            if numel(obj.AnnData) >= 8
                obj.Ann = obj.AnnData(5:end-4);
            else
                obj.Ann = uint8([]);
            end
            obj.RawPixels = frame;
            obj.PixelsAreRGB = false;
            if obj.RemoveDeadPixels
                frame = cine_replace_dead_pixels(frame, obj.resolveDeadValue(), obj.isRawColorCfaFrame(frame));
            end
            obj.updateColorSampleArrays(frame);
            if obj.Debayer && obj.isRawColorCfaFrame(frame)
                frame = cine_demosaic_bilinear(frame, obj.resolveBayerPattern());
                obj.PixelsAreRGB = true;
            end
            obj.Pixels = frame;
        end

        function avgImg = AverageFrames(obj, start_frame, end_frame, replace, chunk_size)
            %AVERAGEFRAMES Streaming mean; the Rust accumulator holds one frame.
            if nargin < 4, replace = false; end
            if nargin < 5 || isempty(chunk_size), chunk_size = 8; end
            validateattributes(chunk_size, {'numeric'}, {'scalar','integer','positive'});
            obj.validateRange(start_frame, end_frame);
            accumulator = uint64(0);
            for fr = double(start_frame):double(end_frame)
                obj.LoadFrame(fr);
                pix = obj.PixelArray;
                if replace && ~obj.RemoveDeadPixels
                    pix = cine_replace_dead_pixels(pix, 4095, obj.isRawColorCfaFrame(pix));
                end
                if accumulator == 0
                    accumulator = cine_backend('stats_open', double(numel(pix)), 256, 0, 0.8, 2.5, 3);
                    cleanup = onCleanup(@() cine_backend('stats_close', accumulator));
                end
                cine_backend('stats_push', accumulator, double(pix));
            end
            values = cine_backend('stats_finish', accumulator, double(numel(pix)));
            avgImg = cast(round(reshape(values, size(pix))), class(pix));
        end

        function SaveFramesToNewFile(obj, output_filename, start_frame, end_frame)
            obj.requireOpen();
            cine_backend('trim', obj.Backend, char(output_filename), ...
                double(start_frame), double(end_frame));
        end

        function out = ModeFrames(obj, start_frame, end_frame, replace, varargin)
            %MODEFRAMES Robust bright background estimate over frame range.
            %
            % Name/value options:
            %   "method"      : "auto" (default), "mad", "topk"
            %   "q_bg"        : bright baseline quantile (default 0.80)
            %   "k_sigma"     : MAD rejection scale for method=mad (default 2.5)
            %   "min_keep"    : minimum kept samples per pixel (default 3)
            %   "max_keep"    : cap for top-k memory (default 96, [] for unlimited)
            %   "stack_limit" : auto->mad threshold (default 128 frames)
            if nargin<4, replace = false; end
            obj.validateRange(start_frame, end_frame);

            opts = struct( ...
                "method", "auto", ...
                "q_bg", 0.80, ...
                "k_sigma", 2.5, ...
                "min_keep", 3, ...
                "max_keep", 96, ...
                "stack_limit", 128 ...
            );
            if mod(numel(varargin),2) ~= 0
                error('ModeFrames name/value options must be pairs.');
            end
            for i = 1:2:numel(varargin)
                key = lower(string(varargin{i}));
                val = varargin{i+1};
                switch key
                    case "method",      opts.method = lower(string(val));
                    case "q_bg",        opts.q_bg = double(val);
                    case "k_sigma",     opts.k_sigma = double(val);
                    case "min_keep",    opts.min_keep = double(val);
                    case "max_keep",    opts.max_keep = val;
                    case "stack_limit", opts.stack_limit = double(val);
                    otherwise, error('Unknown ModeFrames option: %s', char(key));
                end
            end

            obj.validateRange(start_frame, end_frame);
            validateattributes(opts.q_bg, {'numeric'}, {'scalar','finite','>=',0,'<=',1});
            validateattributes(opts.k_sigma, {'numeric'}, {'scalar','finite','nonnegative'});
            validateattributes(opts.min_keep, {'numeric'}, {'scalar','integer','positive'});
            validateattributes(opts.stack_limit, {'numeric'}, {'scalar','integer','nonnegative'});
            if ~isempty(opts.max_keep)
                validateattributes(opts.max_keep, {'numeric'}, {'scalar','integer','positive'});
            end
            frameCount = double(end_frame - start_frame + 1);
            method = opts.method;
            if method == "auto"
                if frameCount <= opts.stack_limit, method = "mad"; else, method = "topk"; end
            end
            if method == "mad"
                mode = 2; kKeep = 0;
            elseif method == "topk"
                mode = 1;
                kKeep = max(opts.min_keep, ceil((1 - opts.q_bg) * frameCount));
                if ~isempty(opts.max_keep), kKeep = min(kKeep, double(opts.max_keep)); end
                kKeep = max(1, kKeep);
            else
                error('ModeFrames method must be auto, mad, or topk.');
            end
            accumulator = uint64(0);
            for fr = double(start_frame):double(end_frame)
                obj.LoadFrame(fr);
                pix = obj.PixelArray;
                if ~ismatrix(pix), error('ModeFrames supports mono frames only.'); end
                if replace && ~obj.RemoveDeadPixels
                    pix = cine_replace_dead_pixels(pix, 4095, obj.isRawColorCfaFrame(pix));
                end
                if accumulator == 0
                    accumulator = cine_backend('stats_open', double(numel(pix)), mode + 256, ...
                        double(kKeep), opts.q_bg, opts.k_sigma, double(opts.min_keep));
                    cleanup = onCleanup(@() cine_backend('stats_close', accumulator));
                end
                cine_backend('stats_push', accumulator, double(pix));
            end
            values = cine_backend('stats_finish', accumulator, double(numel(pix)));
            out = uint16(round(reshape(values, size(pix))));
        end

        function rgb = GetFrameRGB(obj, frame_no, bayer_pattern)
            if nargin>=2 && ~isempty(frame_no)
                obj.LoadFrame(int32(frame_no));
            end
            if nargin<3 || isempty(bayer_pattern)
                bayer_pattern = obj.resolveBayerPattern();
            end

            if ndims(obj.PixelArray)==3
                if obj.PixelsAreRGB
                    rgb = obj.PixelArray;
                else
                    rgb = obj.PixelArray(:,:,[3 2 1]);
                end
                return;
            end
            if ismatrix(obj.PixelArray)
                rgb = cine_demosaic_bilinear(obj.PixelArray, bayer_pattern);
                return;
            end
            error('Unsupported frame shape for RGB conversion.');
        end

        function ReplaceDeadPixels(obj, dead_value)
            if nargin<2, dead_value = obj.resolveDeadValue(); end
            obj.PixelArray = cine_replace_dead_pixels( ...
                obj.PixelArray, dead_value, obj.isRawColorCfaFrame(obj.PixelArray));
            if ~obj.isRawColorCfaFrame(obj.RawPixelArray) || ndims(obj.PixelArray) ~= 3
                obj.updateColorSampleArrays(obj.PixelArray);
            end
        end

        function DebayerFrame(obj, bayer_pattern)
            if nargin<2 || isempty(bayer_pattern)
                bayer_pattern = obj.resolveBayerPattern();
            end
            if ndims(obj.PixelArray)==3
                return;
            end
            if ~obj.isRawColorCfaFrame(obj.PixelArray)
                error('Current frame is not a raw color CFA/Bayer frame.');
            end
            obj.updateColorSampleArrays(obj.PixelArray);
            obj.PixelArray = cine_demosaic_bilinear(obj.PixelArray, bayer_pattern);
            obj.PixelsAreRGB = true;
        end

        function out = LoadFramesBatch(obj, start_frame, count)
            % Minimal batch API: loads count frames into a 3-D array.
            % Mono/raw CFA returns [H x W x count].
            % Debayered/interpolated RGB returns [H x W x 3 x count].
            validateattributes(count, {'numeric'}, {'scalar','integer','positive','finite'});
            stop_frame = double(start_frame) + double(count) - 1;
            obj.validateRange(start_frame, stop_frame);

            h = abs(double(obj.ImageHeader.biHeight));
            w = double(obj.ImageHeader.biWidth);
            bc = double(obj.ImageHeader.biBitCount);
            colorBatch = (obj.Debayer && obj.isRawColorCfa()) || bc==24 || bc==48;

            if bc==8
                if colorBatch
                    out = zeros(h,w,3,count,'uint8');
                else
                    out = zeros(h,w,count,'uint8');
                end
            elseif bc==16
                if colorBatch
                    out = zeros(h,w,3,count,'uint16');
                else
                    out = zeros(h,w,count,'uint16');
                end
            elseif bc==24
                out = zeros(h,w,3,count,'uint8');
            elseif bc==48
                out = zeros(h,w,3,count,'uint16');
            else
                error('Unsupported biBitCount for batch: %d', bc);
            end

            for i = 0:count-1
                obj.LoadFrame(double(start_frame) + double(i));
                if colorBatch
                    out(:,:,:,i+1) = obj.PixelArray;
                else
                    out(:,:,i+1) = obj.PixelArray;
                end
            end
        end
    end

    %% Private helpers
    methods (Access=private)
        function releaseBackend(obj)
            if obj.Backend ~= 0
                handle = obj.Backend;
                obj.Backend = uint64(0);
                cine_backend('close', handle);
            end
            obj.PendingFrame = false;
            obj.fid = -1; obj.mm = [];
        end

        function validateRange(obj, first, last)
            validateattributes(first, {'numeric'}, {'scalar','integer','finite'});
            validateattributes(last, {'numeric'}, {'scalar','integer','finite'});
            firstNo = double(obj.FileHeader.FirstImageNo);
            lastNo = firstNo + double(obj.FileHeader.ImageCount) - 1;
            if first < firstNo || last > lastNo || last < first
                error('cine:range', 'Frame range out of bounds.');
            end
        end

        function requireOpen(obj)
            if obj.Backend == 0
                error('cine:closed', 'CINE reader is closed.');
            end
        end

        function ensureFrame(obj)
            if obj.PendingFrame && ~obj.LoadingFrame
                obj.LoadFrame(obj.CurrentFrame);
            end
        end

        function endLoading(obj)
            obj.LoadingFrame = false;
        end

        function tf = isRawColorCfa(obj)
            bitCount = double(obj.ImageHeader.biBitCount);
            tf = (bitCount == 8 || bitCount == 16) && ...
                isfield(obj.SetupCache, 'bEnableColor') && logical(obj.SetupCache.bEnableColor) && ...
                isfield(obj.SetupCache, 'CFA') && double(obj.SetupCache.CFA) ~= 0;
        end

        function tf = isRawColorCfaFrame(obj, frame)
            tf = obj.isRawColorCfa() && ismatrix(frame);
        end

        function pattern = resolveBayerPattern(obj)
            if obj.BayerPattern ~= "auto"
                pattern = upper(obj.BayerPattern);
                return;
            end
            if ~isfield(obj.SetupCache, 'CFA')
                pattern = "RGGB";
                return;
            end

            switch double(obj.SetupCache.CFA)
                case 1
                    pattern = "GBRG";
                case 2
                    pattern = "BGGR";
                case 3
                    pattern = "GBRG";
                case 4
                    pattern = "RGGB";
                case 5
                    pattern = "GRBG";
                case 6
                    pattern = "BGGR";
                otherwise
                    pattern = "RGGB";
            end
        end

        function deadValue = resolveDeadValue(obj)
            if ~isempty(obj.DeadValue)
                deadValue = obj.DeadValue;
            else
                deadValue = uint16(4095);
            end
        end

        function updateColorSampleArrays(obj, frame)
            obj.ColorSampleFrame = frame;
            obj.ColorSamplesPending = true;
        end

        function ensureColorSampleArrays(obj)
            obj.ensureFrame();
            if ~obj.ColorSamplesPending, return; end
            obj.ColorSamplesPending = false;
            frame = obj.ColorSampleFrame;
            if obj.isRawColorCfaFrame(frame)
                obj.ensureRawColorSampleArrays(size(frame));
                frameF = single(frame);
                phases = obj.bayerColorPhases(obj.resolveBayerPattern());
                for k = 1:size(phases, 1)
                    rows = phases{k, 1}:2:size(frame, 1);
                    cols = phases{k, 2}:2:size(frame, 2);
                    switch phases{k, 3}
                        case 'R'
                            obj.RedPixels(rows, cols) = frameF(rows, cols);
                        case 'G'
                            obj.GreenPixels(rows, cols) = frameF(rows, cols);
                        case 'B'
                            obj.BluePixels(rows, cols) = frameF(rows, cols);
                    end
                end
                return;
            end

            obj.RedPixels = [];
            obj.GreenPixels = [];
            obj.BluePixels = [];

            if ndims(frame) == 3 && size(frame, 3) >= 3
                if obj.PixelsAreRGB
                    rgb = frame;
                else
                    rgb = frame(:,:,[3 2 1]);
                end
                obj.RedPixels = single(rgb(:,:,1));
                obj.GreenPixels = single(rgb(:,:,2));
                obj.BluePixels = single(rgb(:,:,3));
            end
        end

        function ensureRawColorSampleArrays(obj, frameSize)
            if ~isa(obj.RedPixels, 'single') || ~isequal(size(obj.RedPixels), frameSize)
                obj.RedPixels = nan(frameSize, 'single');
            else
                obj.RedPixels(:) = NaN;
            end
            if ~isa(obj.GreenPixels, 'single') || ~isequal(size(obj.GreenPixels), frameSize)
                obj.GreenPixels = nan(frameSize, 'single');
            else
                obj.GreenPixels(:) = NaN;
            end
            if ~isa(obj.BluePixels, 'single') || ~isequal(size(obj.BluePixels), frameSize)
                obj.BluePixels = nan(frameSize, 'single');
            else
                obj.BluePixels(:) = NaN;
            end
        end

        function phases = bayerColorPhases(~, pattern)
            switch upper(string(pattern))
                case "RGGB"
                    phases = {1, 1, 'R'; 1, 2, 'G'; 2, 1, 'G'; 2, 2, 'B'};
                case "BGGR"
                    phases = {1, 1, 'B'; 1, 2, 'G'; 2, 1, 'G'; 2, 2, 'R'};
                case "GRBG"
                    phases = {1, 1, 'G'; 1, 2, 'R'; 2, 1, 'B'; 2, 2, 'G'};
                case "GBRG"
                    phases = {1, 1, 'G'; 1, 2, 'B'; 2, 1, 'R'; 2, 2, 'G'};
                otherwise
                    error('Unsupported Bayer pattern: %s', char(pattern));
            end
        end

    end

    methods
        function value = get.CameraSetup(obj)
            if obj.SetupDataPending
                obj.requireOpen();
                obj.SetupCache.SetupData = cine_backend('setup_data', obj.Backend);
                obj.SetupDataPending = false;
            end
            value = obj.SetupCache;
        end
        function set.CameraSetup(obj, value)
            obj.SetupCache = value;
            obj.SetupDataPending = false;
        end
        function value = get.ImageLocations(obj)
            if isempty(obj.LocationsCache)
                obj.requireOpen();
                obj.LocationsCache = cine_backend('offsets', obj.Backend);
            end
            value = obj.LocationsCache;
        end
        function set.ImageLocations(obj, value)
            obj.LocationsCache = uint64(value);
        end
        function value = get.PixelArray(obj)
            obj.ensureFrame(); value = obj.Pixels;
        end
        function set.PixelArray(obj, value)
            obj.PendingFrame = false;
            obj.Pixels = value;
        end
        function value = get.RawPixelArray(obj)
            obj.ensureFrame(); value = obj.RawPixels;
        end
        function set.RawPixelArray(obj, value)
            obj.RawPixels = value;
        end
        function value = get.RedPixels(obj)
            obj.ensureColorSampleArrays(); value = obj.Red;
        end
        function set.RedPixels(obj, value)
            obj.Red = value;
        end
        function value = get.GreenPixels(obj)
            obj.ensureColorSampleArrays(); value = obj.Green;
        end
        function set.GreenPixels(obj, value)
            obj.Green = value;
        end
        function value = get.BluePixels(obj)
            obj.ensureColorSampleArrays(); value = obj.Blue;
        end
        function set.BluePixels(obj, value)
            obj.Blue = value;
        end
        function value = get.AnnotationSize(obj)
            obj.ensureFrame(); value = obj.AnnSize;
        end
        function set.AnnotationSize(obj, value)
            obj.AnnSize = value;
        end
        function value = get.AnnotationData(obj)
            obj.ensureFrame(); value = obj.AnnData;
        end
        function set.AnnotationData(obj, value)
            obj.AnnData = value;
        end
        function value = get.Annotation(obj)
            obj.ensureFrame(); value = obj.Ann;
        end
        function set.Annotation(obj, value)
            obj.Ann = value;
        end
        function value = get.ImageSize(obj)
            obj.ensureFrame(); value = obj.PayloadSize;
        end
        function set.ImageSize(obj, value)
            obj.PayloadSize = value;
        end
    end
end

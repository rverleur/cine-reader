classdef Cine < handle
    %Cine  Fast reader for Phantom .cine files (MATLAB)
    %
    % Highlights:
    %  - memmapfile I/O (fewer syscalls)
    %  - vectorized padding removal (8/24/16/48-bit)
    %  - packed 10-bit via cached MEX (one-time init)
    %  - buffer reuse to avoid repeated allocations
    %  - optional annotation skipping for speed
    %
    % Requirements for RealBPP==10:
    %   private/mex_unpack10bit_cached.(mex*)
    %   C_Files/<platform unpack library> exporting:
    %     uint16_t* unpack_data_<plat>(const uint8_t*, size_t, size_t*);
    %     void      free_pixel_data(uint16_t*);
    %
    % Usage:
    %   cine = Cine('file.cine');
    %   cine.LoadFrame(cine.CurrentFrame+1);
    %   img = cine.PixelArray;  % reused buffer (no copy)

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
        CameraSetup       struct
        ImageLocations    uint64 = uint64([])   % N+1 entries; last = file size sentinel
        CurrentFrame      int32  = int32(0)

        % last-loaded frame results
        PixelArray
        RawPixelArray
        RedPixels
        GreenPixels
        BluePixels
        AnnotationSize    uint32 = uint32(0)
        AnnotationData    uint8  = uint8([])
        Annotation        uint8  = uint8([])
        ImageSize         uint32 = uint32(0)
    end

    %% Private constants / state
    properties (Access=private, Constant)
        FN_WIN64 = 'unpack_data_win64';
        FN_WIN32 = 'unpack_data_win32';
        FN_MAC   = 'unpack_data_arm64';
        FN_ELF64 = 'unpack_data_elf64';
        FN_FREE  = 'free_pixel_data';
    end
    properties (Access=private)
        % decoder cache
        UnpackInit  (1,1) logical = false
        UnpackFn    (1,1) string  = ""
        UnpackLib   (1,1) string  = ""

        % fast-path helpers
        ConstAnnSize   uint32 = uint32(0)
        HasConstAnn    (1,1) logical = false
        IsTopDown      (1,1) logical = false

        % reusable output buffers (avoid per-frame allocations)
        BufferU8
        BufferU8RGB
        BufferU16
        BufferU16RGB
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
            obj.CloseFile();
        end
    end

    %% Public API
    methods
        function OpenCineFile(obj, filename)
            obj.filename = string(filename);

            % Open, read headers, offsets
            obj.fid = fopen(obj.filename, 'rb');
            assert(obj.fid>0, "Could not open file: %s", obj.filename);

            obj.FileHeader  = obj.readCineHeader();
            obj.ImageHeader = obj.readBitmapHeader(obj.FileHeader.OffImageHeader);
            obj.CameraSetup = obj.readSetupBlock(obj.FileHeader.OffSetup, obj.FileHeader.OffImageOffsets);
            obj.ImageLocations = obj.readImageOffsets(obj.FileHeader);

            % orientation (top-down DIB if negative)
            obj.IsTopDown = obj.ImageHeader.biHeight < 0;

            % memmap for fast slicing
            if obj.UseMemMap
                fclose(obj.fid); obj.fid = -1;
                obj.mm = memmapfile(obj.filename, 'Format', 'uint8');
            end

            % Estimate constant annotation size (optional fast path)
            if obj.AssumeConstAnn
                obj.ConstAnnSize = obj.peekAnnSize(int32(obj.FileHeader.FirstImageNo));
                if obj.FileHeader.ImageCount >= 2
                    s2 = obj.peekAnnSize(int32(obj.FileHeader.FirstImageNo)+1);
                    obj.HasConstAnn = (s2 == obj.ConstAnnSize) && obj.ConstAnnSize > 0;
                else
                    obj.HasConstAnn = obj.ConstAnnSize > 0;
                end
            else
                obj.HasConstAnn = false;
            end

            % One-time MEX init for 10-bit
            if obj.CameraSetup.RealBPP == 10
                obj.initializeUnpacker();
            end

            obj.CurrentFrame = int32(obj.FileHeader.FirstImageNo);
            obj.LoadFrame(obj.CurrentFrame);
        end

        function CloseFile(obj)
            if obj.fid>0, fclose(obj.fid); obj.fid = -1; end
            % obj.mm = [];  % keep mapped unless you want to free explicitly
        end

        function NextFrame(obj, increment)
            if nargin<2, increment = 1; end
            obj.LoadFrame(obj.CurrentFrame + int32(increment));
        end

        function LoadFrame(obj, ImageNo)
            % bounds
            firstNo  = int32(obj.FileHeader.FirstImageNo);
            imgCount = int32(obj.FileHeader.ImageCount);
            idx = int32(ImageNo) - firstNo;
            if idx < 0 || idx >= imgCount, error('ImageNo out of bounds'); end
            obj.CurrentFrame = int32(ImageNo);

            % ---- Locate bytes ----
            startOff = obj.ImageLocations(uint64(idx)+1);
            nextOff  = obj.ImageLocations(uint64(idx)+2);

            if obj.UseMemMap
                a0 = double(startOff) + 1;  % 1-based indexing
                % AnnotationSize (LE uint32)
                if obj.HasConstAnn
                    obj.AnnotationSize = obj.ConstAnnSize;
                else
                    obj.AnnotationSize = typecast(uint8(obj.mm.Data(a0 + (0:3))), 'uint32');
                end
                % Payload bounds / size
                if obj.HasConstAnn
                    imgBytes = double(nextOff - startOff) - double(obj.AnnotationSize);
                else
                    % Trailing image-size field starts four bytes before the payload.
                    imgBytes = typecast( ...
                        uint8(obj.mm.Data(a0 + double(obj.AnnotationSize) - 4 + (0:3))), ...
                        'uint32');
                end
                obj.ImageSize = uint32(imgBytes);

                raw = obj.mm.Data(a0 + double(obj.AnnotationSize) + (0:double(obj.ImageSize)-1));
                raw = uint8(raw);

                if obj.KeepAnnotations
                    A = obj.mm.Data(a0 + (0:double(obj.AnnotationSize)-1));
                    obj.AnnotationData = uint8(A);
                    obj.Annotation     = obj.AnnotationData(5:end-4);
                else
                    obj.AnnotationData = uint8([]); obj.Annotation = uint8([]);
                end
            else
                % Fallback (file I/O)
                fseek(obj.fid, startOff, 'bof');
                obj.AnnotationSize = fread(obj.fid, 1, 'uint32=>uint32', 0, 'l');
                fseek(obj.fid, startOff, 'bof');
                if obj.KeepAnnotations
                    obj.AnnotationData = fread(obj.fid, double(obj.AnnotationSize), 'uint8=>uint8');
                    obj.Annotation     = obj.AnnotationData(5:end-4);
                    obj.ImageSize      = typecast(obj.AnnotationData(end-3:end), 'uint32');
                else
                    fseek(obj.fid, 4, 'cof'); % skip first 4 bytes (size)
                    fseek(obj.fid, double(obj.AnnotationSize)-4, 'cof'); % jump to trailing size
                    obj.ImageSize      = fread(obj.fid,1,'uint32=>uint32',0,'l');
                    fseek(obj.fid, startOff + obj.AnnotationSize, 'bof');
                end
                raw = fread(obj.fid, double(obj.ImageSize), 'uint8=>uint8');
            end

            % ---- Decode ----
            bitCount = double(obj.ImageHeader.biBitCount);  % 8/24/16/48
            h        = abs(double(obj.ImageHeader.biHeight));
            w        = double(obj.ImageHeader.biWidth);

            bytesPerPixel = bitCount/8;              % 1,3,2,6
            rowBytes      = w * bytesPerPixel;
            rowStride     = 4 * ceil(rowBytes/4);    % DWORD-aligned

            if bitCount == 8
                img = obj.readPadded8_vec(raw, h, w, rowBytes, rowStride, 1);
                frame = obj.intoU8(img, h, w);

            elseif bitCount == 24
                img = obj.readPadded8_vec(raw, h, w, rowBytes, rowStride, 3);
                frame = obj.intoU8RGB(img, h, w);

            elseif bitCount == 16 || bitCount == 48
                if obj.CameraSetup.RealBPP == 10
                    % unpack packed 10-bit via cached MEX
                    if ~obj.UnpackInit, obj.initializeUnpacker(); end
                    pix = mex_unpack10bit_cached(raw);  % uint16 vector

                    if bitCount == 16
                        if obj.Debug && numel(pix) ~= w*h
                            error('Unpacked count %d != w*h %d', numel(pix), w*h);
                        end
                        frame = obj.intoU16_fromVec(pix, h, w);
                    else
                        if obj.Debug && numel(pix) ~= 3*w*h
                            error('Unpacked RGB16 %d != 3*w*h %d', numel(pix), 3*w*h);
                        end
                        frame = obj.intoU16RGB_fromVec(pix, h, w);
                    end
                else
                    % unpadded or row-padded 16/48-bit container
                    if bitCount == 16
                        img = obj.readPadded16_vec(raw, h, w, rowBytes, rowStride, 1);
                        frame = obj.intoU16(img, h, w);
                    else
                        img = obj.readPadded16_vec(raw, h, w, rowBytes, rowStride, 3);
                        frame = obj.intoU16RGB(img, h, w);
                    end
                end
            else
                error('Unsupported biBitCount: %d', bitCount);
            end

            obj.RawPixelArray = frame;
            if obj.RemoveDeadPixels
                frame = cine_replace_dead_pixels(frame, obj.resolveDeadValue(), obj.isRawColorCfaFrame(frame));
            end
            obj.updateColorSampleArrays(frame);
            if obj.Debayer && obj.isRawColorCfaFrame(frame)
                frame = cine_demosaic_bilinear(frame, obj.resolveBayerPattern());
            end
            obj.PixelArray = frame;

            % orientation (top-down means first row is top)
            % If you prefer bottom-up arrays, enable:
            % if obj.IsTopDown, obj.PixelArray = flipud(obj.PixelArray); end
        end

        function avgImg = AverageFrames(obj, start_frame, end_frame, replace, chunk_size)
            %AVERAGEFRAMES Mean frame with chunked accumulation for speed/memory.
            if nargin<4, replace = false; end
            if nargin<5 || isempty(chunk_size), chunk_size = 8; end
            firstNo = int32(obj.FileHeader.FirstImageNo);
            lastNo  = firstNo + int32(obj.FileHeader.ImageCount)-1;
            if start_frame < firstNo || end_frame > lastNo, error('Frame range out of bounds.'); end

            acc = [];
            totalCount = 0;
            fr = int32(start_frame);
            bc = double(obj.ImageHeader.biBitCount);
            colorBatch = (obj.Debayer && obj.isRawColorCfa()) || bc==24 || bc==48;
            while fr <= int32(end_frame)
                n = min(int32(chunk_size), int32(end_frame) - fr + 1);
                batch = obj.LoadFramesBatch(fr, double(n));

                if replace && ~obj.RemoveDeadPixels && ~colorBatch
                    for k = 1:double(n)
                        batch(:,:,k) = cine_replace_dead_pixels(batch(:,:,k), uint16(4095), obj.isRawColorCfa());
                    end
                end

                if colorBatch
                    sumDim = 4;
                else
                    sumDim = 3;
                end
                chunkSum = sum(double(batch), sumDim);
                if colorBatch
                    chunkSum = reshape(chunkSum, size(batch,1), size(batch,2), size(batch,3));
                end
                if isempty(acc)
                    acc = zeros(size(chunkSum), 'double');
                end
                acc = acc + chunkSum;
                totalCount = totalCount + double(n);
                fr = fr + n;
            end

            avgImg = cast(round(acc / totalCount), class(obj.PixelArray));
        end

        function SaveFramesToNewFile(obj, output_filename, start_frame, end_frame)
            firstNo = int32(obj.FileHeader.FirstImageNo);
            lastNo  = firstNo + int32(obj.FileHeader.ImageCount)-1;
            if start_frame < firstNo || end_frame > lastNo || end_frame < start_frame
                error('Frame range out of bounds.');
            end

            newCount = uint32(end_frame - start_frame + 1);
            bytesPerOffset = 4;
            if obj.FileHeader.Version == 1, bytesPerOffset = 8; end

            inFid = fopen(obj.filename, 'rb');
            if inFid < 0, error('Could not open source file for trimming.'); end
            cleanIn = onCleanup(@() fclose(inFid)); %#ok<NASGU>

            outFid = fopen(output_filename, 'wb');
            if outFid < 0, error('Could not open output file: %s', output_filename); end
            cleanOut = onCleanup(@() fclose(outFid)); %#ok<NASGU>

            hdr = obj.FileHeader.FileHeaderData;
            hdr(13:16) = typecast(uint32(newCount), 'uint8');
            hdr(17:20) = typecast(int32(start_frame), 'uint8');
            hdr(21:24) = typecast(uint32(newCount), 'uint8');
            fwrite(outFid, hdr, 'uint8');
            fwrite(outFid, obj.ImageHeader.ImageHeaderData, 'uint8');
            fwrite(outFid, obj.CameraSetup.SetupData, 'uint8');

            offsetBase = uint64(ftell(outFid)) + uint64(double(newCount) * bytesPerOffset);
            offsOut = zeros(double(newCount), 1, 'uint64');
            cursor = offsetBase;
            for i = 1:double(newCount)
                fr = int32(start_frame) + int32(i-1);
                idx = double(fr - firstNo) + 1;
                frameBytes = obj.ImageLocations(idx+1) - obj.ImageLocations(idx);
                offsOut(i) = cursor;
                cursor = cursor + frameBytes;
            end

            if bytesPerOffset == 8
                fwrite(outFid, offsOut, 'uint64');
            else
                fwrite(outFid, uint32(offsOut), 'uint32');
            end

            for i = 1:double(newCount)
                fr = int32(start_frame) + int32(i-1);
                idx = double(fr - firstNo) + 1;
                startOff = obj.ImageLocations(idx);
                frameBytes = obj.ImageLocations(idx+1) - startOff;
                fseek(inFid, double(startOff), 'bof');
                chunk = fread(inFid, double(frameBytes), 'uint8=>uint8');
                fwrite(outFid, chunk, 'uint8');
            end
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
            firstNo = int32(obj.FileHeader.FirstImageNo);
            lastNo  = firstNo + int32(obj.FileHeader.ImageCount)-1;
            if start_frame < firstNo || end_frame > lastNo || end_frame < start_frame
                error('Frame range out of bounds.');
            end

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

            frameCount = double(end_frame - start_frame + 1);
            method = opts.method;
            if method == "auto"
                if frameCount <= opts.stack_limit
                    method = "mad";
                else
                    method = "topk";
                end
            end

            if method == "mad"
                frames = [];
                for fr = int32(start_frame):int32(end_frame)
                    obj.LoadFrame(fr);
                    if ndims(obj.PixelArray) ~= 2
                        error('ModeFrames supports mono frames only.');
                    end
                    pix = obj.PixelArray;
                    if replace && ~obj.RemoveDeadPixels
                        pix = cine_replace_dead_pixels(pix, uint16(4095), obj.isRawColorCfaFrame(pix));
                    end
                    frames = cat(3, frames, single(pix)); %#ok<AGROW>
                end
                stack = permute(frames, [3 1 2]); % [T H W]
                out = cine_mode_mad_stack(stack, opts.q_bg, opts.k_sigma, opts.min_keep);
                return;
            end

            if method == "topk"
                kKeep = max(opts.min_keep, ceil((1 - opts.q_bg) * frameCount));
                if ~isempty(opts.max_keep)
                    kKeep = min(kKeep, double(opts.max_keep));
                end
                kKeep = max(1, kKeep);

                topk = [];
                rr = []; cc = [];
                loaded = 0;
                for fr = int32(start_frame):int32(end_frame)
                    obj.LoadFrame(fr);
                    if ndims(obj.PixelArray) ~= 2
                        error('ModeFrames supports mono frames only.');
                    end
                    pix = obj.PixelArray;
                    if replace && ~obj.RemoveDeadPixels
                        pix = cine_replace_dead_pixels(pix, uint16(4095), obj.isRawColorCfaFrame(pix));
                    end
                    frame = single(pix);

                    if isempty(topk)
                        [h,w] = size(frame);
                        topk = -inf(kKeep, h, w, 'single');
                        [rr,cc] = ndgrid(1:h, 1:w);
                    end

                    if loaded < kKeep
                        topk(loaded+1,:,:) = frame;
                    else
                        [minVals, minIdx] = min(topk, [], 1);
                        minVals = squeeze(minVals);
                        minIdx = squeeze(minIdx);
                        replaceMask = frame > minVals;
                        if any(replaceMask, 'all')
                            rrSub = rr(replaceMask);
                            ccSub = cc(replaceMask);
                            idxSub = minIdx(replaceMask);
                            lin = sub2ind(size(topk), idxSub, rrSub, ccSub);
                            topk(lin) = frame(replaceMask);
                        end
                    end
                    loaded = loaded + 1;
                end

                used = min(loaded, kKeep);
                out = squeeze(mean(topk(1:used,:,:), 1));
                out = uint16(max(0, min(double(intmax('uint16')), round(out))));
                return;
            end

            error('ModeFrames method must be auto, mad, or topk.');
        end

        function rgb = GetFrameRGB(obj, frame_no, bayer_pattern)
            if nargin>=2 && ~isempty(frame_no)
                obj.LoadFrame(int32(frame_no));
            end
            if nargin<3 || isempty(bayer_pattern)
                bayer_pattern = obj.resolveBayerPattern();
            end

            if ndims(obj.PixelArray)==3
                if obj.isRawColorCfa() && obj.Debayer
                    rgb = obj.PixelArray;
                else
                    rgb = obj.PixelArray(:,:,[3 2 1]);
                end
                return;
            end
            if ndims(obj.PixelArray)==2
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
        end

        function out = LoadFramesBatch(obj, start_frame, count)
            % Minimal batch API: loads count frames into a 3-D array.
            % Mono/raw CFA returns [H x W x count].
            % Debayered/interpolated RGB returns [H x W x 3 x count].
            firstNo = int32(obj.FileHeader.FirstImageNo);
            lastNo  = firstNo + int32(obj.FileHeader.ImageCount)-1;
            stop_frame = start_frame + count - 1;
            if start_frame < firstNo || stop_frame > lastNo
                error('Frame range out of bounds.');
            end

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
                obj.LoadFrame(start_frame + int32(i));
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
        function s = peekAnnSize(obj, frameNo)
            idx = int32(frameNo) - int32(obj.FileHeader.FirstImageNo);
            if idx < 0 || idx >= int32(obj.FileHeader.ImageCount)
                s = uint32(0); return;
            end
            off = obj.ImageLocations(uint64(idx)+1);
            if obj.UseMemMap
                a0 = double(off)+1;
                s = typecast(uint8(obj.mm.Data(a0 + (0:3))), 'uint32');
            else
                fseek(obj.fid, off, 'bof');
                s = fread(obj.fid, 1, 'uint32=>uint32', 0, 'l');
            end
        end

        function img8 = readPadded8_vec(~, raw, h, w, rowBytes, rowStride, ch)
            if numel(raw) == h*rowStride
                M = reshape(raw, rowStride, h).';
                M = M(:, 1:rowBytes);
                if ch==1
                    img8 = reshape(M.', w, h).';
                else
                    M = reshape(M.', ch, w, h);
                    img8 = permute(M, [3 2 1]); % [h w 3]
                end
            elseif numel(raw) == h*rowBytes
                if ch==1, img8 = reshape(raw, [w,h]).';
                else,     img8 = permute(reshape(raw,[ch,w,h]), [3 2 1]); end
            else
                error('8/24-bit size mismatch: raw=%d, expected %d or %d.', ...
                      numel(raw), h*rowBytes, h*rowStride);
            end
        end

        function img16 = readPadded16_vec(~, raw, h, w, rowBytes, rowStride, ch)
            if numel(raw) == h*rowStride
                M = reshape(raw, rowStride, h).';
                M = M(:, 1:rowBytes);
                u16 = typecast(M.', 'uint16');
                if ch==1
                    img16 = reshape(u16, w, h).';
                else
                    img16 = permute(reshape(u16, [ch,w,h]), [3 2 1]);
                end
            elseif numel(raw) == h*rowBytes
                u16 = typecast(raw, 'uint16');
                if ch==1, img16 = reshape(u16, [w,h]).';
                else,     img16 = permute(reshape(u16,[ch,w,h]), [3 2 1]); end
            else
                if mod(numel(raw), ch*2)==0 && (numel(raw)/(ch*2)) == w*h
                    u16 = typecast(raw, 'uint16');
                    if ch==1, img16 = reshape(u16, [w,h]).';
                    else,     img16 = permute(reshape(u16,[ch,w,h]), [3 2 1]); end
                else
                    error('16/48-bit size mismatch: raw=%d, expected %d or %d.', ...
                          numel(raw), h*rowBytes, h*rowStride);
                end
            end
        end

        % ---------- buffer reuse writers ----------
        function out = intoU8(obj, src, h, w)
            if isempty(obj.BufferU8) || ~isequal(size(obj.BufferU8), [h w])
                obj.BufferU8 = zeros(h,w,'uint8');
            end
            obj.BufferU8(:) = src;
            out = obj.BufferU8;
        end
        function out = intoU8RGB(obj, src, h, w)
            if isempty(obj.BufferU8RGB) || ~isequal(size(obj.BufferU8RGB), [h w 3])
                obj.BufferU8RGB = zeros(h,w,3,'uint8');
            end
            obj.BufferU8RGB(:) = src;
            out = obj.BufferU8RGB;
        end
        function out = intoU16(obj, src, h, w)
            if isempty(obj.BufferU16) || ~isequal(size(obj.BufferU16), [h w])
                obj.BufferU16 = zeros(h,w,'uint16');
            end
            obj.BufferU16(:) = src;
            out = obj.BufferU16;
        end
        function out = intoU16_fromVec(obj, vec, h, w)
            % vec is a row-major stream from C; fix ordering for MATLAB.
            if isempty(obj.BufferU16) || ~isequal(size(obj.BufferU16), [h w])
                obj.BufferU16 = zeros(h,w,'uint16');
            end
            % Correct reshape: [w h].' → [h x w]
            obj.BufferU16(:) = reshape(vec, [w, h]).';
            out = obj.BufferU16;
        end
        function out = intoU16RGB(obj, src, h, w)
            if isempty(obj.BufferU16RGB) || ~isequal(size(obj.BufferU16RGB), [h w 3])
                obj.BufferU16RGB = zeros(h,w,3,'uint16');
            end
            obj.BufferU16RGB(:) = src;
            out = obj.BufferU16RGB;
        end
        function out = intoU16RGB_fromVec(obj, vec, h, w)
            % vec is row-major interleaved [R G B] per pixel
            if isempty(obj.BufferU16RGB) || ~isequal(size(obj.BufferU16RGB), [h w 3])
                obj.BufferU16RGB = zeros(h,w,3,'uint16');
            end
            tmp = permute(reshape(vec, [3, w, h]), [3 2 1]); % [h x w x 3]
            obj.BufferU16RGB(:) = tmp;
            out = obj.BufferU16RGB;
        end

        function tf = isRawColorCfa(obj)
            bitCount = double(obj.ImageHeader.biBitCount);
            tf = (bitCount == 8 || bitCount == 16) && ...
                isfield(obj.CameraSetup, 'bEnableColor') && logical(obj.CameraSetup.bEnableColor) && ...
                isfield(obj.CameraSetup, 'CFA') && double(obj.CameraSetup.CFA) ~= 0;
        end

        function tf = isRawColorCfaFrame(obj, frame)
            tf = obj.isRawColorCfa() && ndims(frame) == 2;
        end

        function pattern = resolveBayerPattern(obj)
            if obj.BayerPattern ~= "auto"
                pattern = upper(obj.BayerPattern);
                return;
            end
            if ~isfield(obj.CameraSetup, 'CFA')
                pattern = "RGGB";
                return;
            end

            switch double(obj.CameraSetup.CFA)
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
                if obj.isRawColorCfa() && obj.Debayer
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

        % ---------- parsing helpers ----------
        function H = readCineHeader(obj)
            fseek(obj.fid, 0, 'bof');
            raw = fread(obj.fid, 44, 'uint8=>uint8');
            H.FileHeaderData = raw;

            leU16 = @(a,b) typecast(uint8(raw(a:b)), 'uint16');
            leI32 = @(a,b) typecast(uint8(raw(a:b)), 'int32');
            leU32 = @(a,b) typecast(uint8(raw(a:b)), 'uint32');
            leU64 = @(a,b) typecast(uint8(raw(a:b)), 'uint64');

            H.Type            = raw(1:2);
            H.Headersize      = leU16(3,4);
            H.Compression     = leU16(5,6);
            H.Version         = leU16(7,8);          % 0 or 1
            H.FirstMovieImage = leI32(9,12);
            H.TotalImageCount = leU32(13,16);
            H.FirstImageNo    = leI32(17,20);
            H.ImageCount      = leU32(21,24);
            H.OffImageHeader  = leU32(25,28);
            H.OffSetup        = leU32(29,32);
            H.OffImageOffsets = leU32(33,36);
            H.TriggerTime     = leU64(37,44);
        end

        function B = readBitmapHeader(obj, offImageHeader)
            fseek(obj.fid, offImageHeader, 'bof');
            raw = fread(obj.fid, 40, 'uint8=>uint8');
            B.ImageHeaderData = raw;

            leU16 = @(a,b) typecast(uint8(raw(a:b)), 'uint16');
            leI32 = @(a,b) typecast(uint8(raw(a:b)), 'int32');
            leU32 = @(a,b) typecast(uint8(raw(a:b)), 'uint32');

            B.biSize          = leU32(1,4);
            B.biWidth         = leI32(5,8);
            B.biHeight        = leI32(9,12);
            B.biPlanes        = leU16(13,14);
            B.biBitCount      = leU16(15,16);
            B.biCompression   = leU32(17,20);
            B.biSizeImage     = leU32(21,24);
            B.biXPelsPerMeter = leI32(25,28);
            B.biYPelsPerMeter = leI32(29,32);
            B.biClrUsed       = leU32(33,36);
            B.biClrImportant  = leU32(37,40);
        end

        function S = readSetupBlock(obj, offSetup, offImageOffsets)
            fseek(obj.fid, offSetup, 'bof');
            nbytes = double(offImageOffsets - offSetup);
            S.SetupData = fread(obj.fid, nbytes, 'uint8=>uint8');

            % little-endian fields
            S.RealBPP = uint32(0);
            if numel(S.SetupData) >= 900
                S.RealBPP = typecast(uint8(S.SetupData(897:900)), 'uint32');
            end
            S.FrameRate = uint32(0);
            if numel(S.SetupData) >= 772
                S.FrameRate = typecast(uint8(S.SetupData(769:772)), 'uint32');
            end
            S.bEnableColor = false;
            if numel(S.SetupData) >= 792
                S.bEnableColor = logical(typecast(uint8(S.SetupData(789:792)), 'uint32'));
            end
            S.CFA = uint32(0);
            if numel(S.SetupData) >= 812
                S.CFA = typecast(uint8(S.SetupData(809:812)), 'uint32');
            end
        end

        function offs = readImageOffsets(obj, H)
            fseek(obj.fid, H.OffImageOffsets, 'bof');
            if H.Version==0
                raw = fread(obj.fid, double(H.ImageCount)*4, 'uint8=>uint8');
                offs = uint64(typecast(uint8(raw.'), 'uint32'));
            elseif H.Version==1
                raw = fread(obj.fid, double(H.ImageCount)*8, 'uint8=>uint8');
                offs = typecast(uint8(raw.'), 'uint64');
            else
                error('Invalid file version: %d', H.Version);
            end
            fseek(obj.fid, 0, 'eof');
            fileSize = uint64(ftell(obj.fid));
            offs = [offs(:); fileSize];
            if obj.Debug && any(diff(double(offs))<0)
                error('Image offset table not monotonic.');
            end
        end

        function [libPath, fnName] = getLibPathAndSymbol(obj)
            here  = fileparts(mfilename('fullpath'));
            libdir = fullfile(here, 'C_Files');
            arch = computer('arch');  % 'maca64','maci64','glnxa64','win64',...

            cands = {};
            fnName = '';
            if ispc
                if contains(arch,'64'), cands = {'unpack_data_win64.dll'}; fnName = obj.FN_WIN64;
                else,                   cands = {'unpack_data_win32.dll'}; fnName = obj.FN_WIN32; end
            elseif ismac
                cands = {'unpack_data_arm64.dylib'}; fnName = obj.FN_MAC;
            else % Linux
                cands = {'unpack_data_elf64.so'};   fnName = obj.FN_ELF64;
            end

            libPath = "";
            for i = 1:numel(cands)
                p = fullfile(libdir, cands{i});
                if isfile(p), libPath = p; break; end
            end
            if libPath == ""
                d = dir(libdir); names = string({d.name});
                error("No suitable unpack library found for arch '%s'. Looked for: %s\nC_Files contains: %s", ...
                      arch, strjoin(cands, ", "), strjoin(names, ", "));
            end
            libPath = char(libPath); fnName = char(fnName);
        end

        function initializeUnpacker(obj)
            if obj.UnpackInit, return; end
            [libPath, fnName] = obj.getLibPathAndSymbol();
            mex_unpack10bit_cached('init', libPath, fnName, obj.FN_FREE);
            obj.UnpackInit = true;
            obj.UnpackFn   = string(fnName);
            obj.UnpackLib  = string(libPath);
        end
    end
end

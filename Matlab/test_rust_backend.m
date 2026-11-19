function test_rust_backend(fixture_directory)
%TEST_RUST_BACKEND Round-trip, lifecycle, processing and real-file smoke tests.
% Pass the directory of camera CINEs to also test first/middle/last frames.
if nargin < 1, fixture_directory = ''; end
folder = tempname; mkdir(folder);
cleanup = onCleanup(@() rmdir(folder,'s')); %#ok<NASGU>
for bitDepth = [8 16]
    if bitDepth==8, frame=uint8(reshape(0:34,5,7)); else, frame=uint16(reshape(0:34,5,7)*1000); end
    for channels = [1 3]
        if channels==3, input=cat(3,frame,frame+1,frame+2); else, input=frame; end
        name=fullfile(folder,sprintf('normal_%d_%d.cine',bitDepth,channels));
        writer=CineWriter(name,7,5,'Channels',channels,'BitDepth',bitDepth,'FrameCount',2,'FirstFrame',-1);
        writer.WriteFrame(input); writer.WriteFrame(input); writer.Close();
        cine=Cine(name);
        assert(cine.FileHeader.FirstImageNo==-1 && cine.FileHeader.ImageCount==2);
        assert(isa(cine.FileHeader.ImageCount,'uint32'));
        expected=input;
        % Reader intentionally preserves file storage orientation/BGR.
        if cine.ImageHeader.biHeight>0, expected=flipud(expected); end
        if channels==3, expected=expected(:,:,[3 2 1]); end
        assert(isequal(cine.PixelArray,expected));
        assert(isequal(cine.AverageFrames(-1,0),expected));
        if channels==1
            assert(isequal(cine.ModeFrames(-1,0,false,'method','topk'),uint16(expected)));
            assert(isequal(cine.ModeFrames(-1,0,false,'method','mad'),uint16(expected)));
        end
        cine.KeepAnnotations=true;cine.LoadFrame(0);assert(cine.AnnotationSize==8);
        assert(numel(cine.AnnotationData)==8 && isempty(cine.Annotation));
        assert(numel(cine.ImageLocations)==3);
        trimmed=fullfile(folder,sprintf('trim_%d_%d.cine',bitDepth,channels));
        cine.SaveFramesToNewFile(trimmed,0,0);trim=Cine(trimmed);
        assert(trim.FileHeader.ImageCount==1 && isequal(trim.PixelArray,expected));
        trim.CloseFile();cine.CloseFile();
        failed=false;try,cine.LoadFrame(0);catch,failed=true;end;assert(failed);
    end
end
name=fullfile(folder,'packed.cine');
frame=uint16(reshape(0:63,8,8)*60);
writer=CineWriter(name,8,8,'Packed10',true,'CFA',4);
writer.WriteFrame(frame);writer.WriteFrame(frame);writer.Close();
cine=Cine(name);expected=frame; % Phantom packed data is top-down.
assert(max(abs(double(cine.PixelArray(:))-double(expected(:))))<=5);
assert(cine.ImageHeader.biCompression==256);
assert(isequal(size(cine.GetFrameRGB()),[8 8 3]));
assert(isequal(size(cine.RedPixels),[8 8]));
cine.ReplaceDeadPixels();cine.DebayerFrame();assert(size(cine.PixelArray,3)==3);cine.CloseFile();
name=fullfile(folder,'aborted.cine');writer=CineWriter(name,8,8);writer.Abort();assert(~isfile(name));
% Failed writes leave the existing destination untouched.
existing=fullfile(folder,'existing.cine');fid=fopen(existing,'w');fwrite(fid,'keep');fclose(fid);
failed=false;try,w=CineWriter(existing,8,8);catch,failed=true;end
if ~failed, w.Abort(); end
assert(strcmp(fileread(existing),'keep'));
% Series-of-images entry point streams frames and infers dimensions/type.
write_cine(fullfile(folder,'images.cine'),{uint8(ones(4,4)),uint8(ones(4,4)*2)});
cine=Cine(fullfile(folder,'images.cine'));assert(cine.FileHeader.ImageCount==2);cine.CloseFile();
assert(isequal(cine.PixelArray,uint8(ones(4,4))));
assert(numel(cine.ImageLocations)==3);
assert(numel(cine.CameraSetup.SetupData)==double(cine.FileHeader.OffImageOffsets-cine.FileHeader.OffSetup));
cine=Cine(fullfile(folder,'images.cine'));cine.PixelArray=uint8(ones(4,4)*99);
assert(all(cine.PixelArray==99,'all'));delete(cine);
% RGB/8-bit packed10 uses backend scaling and CFA sampling.
rgb=cat(3,uint8(ones(8,8)*255),uint8(ones(8,8)*128),uint8(zeros(8,8)));
write_cine(fullfile(folder,'rgb_packed.cine'),{rgb,rgb},'Packed10',true);
cine=Cine(fullfile(folder,'rgb_packed.cine'));
assert(cine.CameraSetup.CFA==4 && cine.ImageHeader.biCompression==256);
assert(isequal(size(cine.PixelArray),[8 8]));
assert(all(cine.PixelArray(1:2:end,1:2:end)==4095,'all'));
assert(max(abs(double(cine.PixelArray(2:2:end,2:2:end))),[],'all')<=2);
cine.DebayerFrame(); assert(isequal(cine.GetFrameRGB(),cine.PixelArray)); cine.CloseFile();
% Exercise MATLAB's video decoder and unknown-length writer path.
video=VideoWriter(fullfile(folder,'input.avi'),'Motion JPEG AVI');video.FrameRate=24;
open(video);writeVideo(video,repmat(rgb,[2 2 1]));writeVideo(video,repmat(rgb,[2 2 1]));close(video);
write_cine(fullfile(folder,'video.cine'),VideoReader(fullfile(folder,'input.avi')));
cine=Cine(fullfile(folder,'video.cine'));assert(cine.FileHeader.ImageCount==2 && cine.CameraSetup.FrameRate==24);cine.CloseFile();
if ~isempty(fixture_directory)
    files=dir(fullfile(fixture_directory,'*.cine'));
    assert(~isempty(files),'No fixture CINE files were found.');
    for k=1:numel(files)
        tic; cine=Cine(fullfile(files(k).folder,files(k).name)); openTime=toc;
        first=double(cine.FileHeader.FirstImageNo); n=double(cine.FileHeader.ImageCount);
        for frameNo=unique([first,first+floor((n-1)/2),first+n-1])
            cine.LoadFrame(frameNo);assert(~isempty(cine.PixelArray));
        end
        fprintf('%s: %d frames, %dx%d, open %.3f ms\n',files(k).name,n,cine.ImageHeader.biWidth,abs(cine.ImageHeader.biHeight),1000*openTime);
        cine.CloseFile();
    end
end
fprintf('MATLAB Rust backend tests passed.\n');
end

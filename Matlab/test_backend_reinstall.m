function test_backend_reinstall(installer)
    % TEST_BACKEND_REINSTALL Reopen after native errors and same-session updates.
    % Pass @build_cine_backend to test a staged developer build without prebuilts.
    if nargin < 1
        installer = @install_cine_backend;
    end
    folder = tempname;
    mkdir(folder);
    cleanup = onCleanup(@() rmdir(folder, 's'));
    filename = fullfile(folder, 'reinstall.cine');
    pixels = uint16(reshape(0:34, 5, 7));
    write_cine(filename, {pixels});
    cine = Cine(filename);
    expected = cine.PixelArray;
    rejected = false;
    try
        installer();
    catch exception
        assert(any(strcmp(exception.identifier, {'cine:prebuilt', 'cine:build'})), ...
               'Unexpected live-reader reinstall error: %s', exception.message);
        rejected = true;
    end
    assert(rejected, 'Reinstallation accepted a live reader.');
    cine.CloseFile();
    delete(cine);

    % A native error initializes Rust TLS; glibc can then retain the shared
    % library even after clearing the MEX and closing every reader/writer.
    rejected = false;
    try
        invalid = Cine(fullfile(folder, 'missing.cine'));
        delete(invalid);
    catch exception
        assert(strcmp(exception.identifier, 'cine:backend'), 'Unexpected error: %s', exception.message);
        rejected = true;
    end
    assert(rejected, 'Missing input was accepted.');
    installer();
    cine = Cine(filename);
    assert(isequal(cine.PixelArray, expected), 'Decoded samples changed after reinstallation.');
    cine.CloseFile();
    delete(cine);

    if isunix && ~ismac
        here = fileparts(mfilename('fullpath'));
        destination = fullfile(here, 'private', 'lib', computer('arch'), 'libcine_core.so');
        mappings = splitlines(fileread('/proc/self/maps'));
        if any(endsWith(mappings, [' ' destination]) | endsWith(mappings, [' ' destination ' (deleted)']))
            changed = fullfile(folder, 'changed.so');
            copyfile(destination, changed);
            fid = fopen(changed, 'r+b');
            assert(fid ~= -1);
            first = fread(fid, 1, '*uint8');
            fseek(fid, 0, 'bof');
            fwrite(fid, bitxor(first, uint8(1)), 'uint8');
            fclose(fid);
            rejected = false;
            try
                cine_copy_binary(changed, destination);
            catch exception
                assert(strcmp(exception.identifier, 'cine:restart'), 'Unexpected error: %s', exception.message);
                rejected = true;
            end
            assert(rejected, 'Changed mapped code was replaced without requiring a restart.');
            backup = fullfile(folder, 'installed.so');
            movefile(destination, backup);
            cleanupBinary = onCleanup(@() restoreBinary(backup, destination));
            rejected = false;
            try
                cine_copy_binary(backup, destination);
            catch exception
                assert(strcmp(exception.identifier, 'cine:restart'), 'Unexpected error: %s', exception.message);
                rejected = true;
            end
            assert(rejected, 'A removed mapped binary was reinstalled without requiring a restart.');
            clear cleanupBinary;
            cine = Cine(filename);
            assert(isequal(cine.PixelArray, expected), 'Rejected update damaged the installed backend.');
            cine.CloseFile();
            delete(cine);
        end
    end
    fprintf('MATLAB backend reinstallation tests passed.\n');
end

function restoreBinary(source, destination)
    if isfile(source)
        movefile(source, destination, 'f');
    end
end

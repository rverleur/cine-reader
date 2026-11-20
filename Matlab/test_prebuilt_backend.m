function test_prebuilt_backend
    % TEST_PREBUILT_BACKEND Validate collected binaries and installer rejection paths.
    % Run after collecting current binaries, before distributing a checkout.
    root = fileparts(fileparts(mfilename('fullpath')));
    [info, source, library, gateway] = cine_prebuilt_info(root, computer('arch'));
    folder = [tempname ' quoted '' $() %']; % Paths must remain literal in hash commands.
    mkdir(folder);
    cleanup = onCleanup(@() rmdir(folder, 's'));
    copyfile(fullfile(root, 'Cargo.toml'), fullfile(folder, 'Cargo.toml'));
    copyfile(fullfile(root, 'Cargo.lock'), fullfile(folder, 'Cargo.lock'));
    copyfile(fullfile(root, 'rust'), fullfile(folder, 'rust'));
    copyfile(fullfile(root, '.cargo'), fullfile(folder, '.cargo'));
    for name = {'rust-toolchain', 'rust-toolchain.toml'}
        if isfile(fullfile(root, name{1}))
            copyfile(fullfile(root, name{1}), fullfile(folder, name{1}));
        end
    end
    target = fullfile(folder, 'binaries', info.target);
    mkdir(fullfile(folder, 'binaries'));
    copyfile(source, target);
    cine_prebuilt_info(folder, computer('arch'));

    % A checkout's CRLF conversion must not invalidate the source fingerprint.
    sourceFile = fullfile(folder, 'rust', 'cine-core', 'Cargo.toml');
    original = fileread(sourceFile);
    normalized = strrep(original, sprintf('\r\n'), newline);
    writeBytes(sourceFile, uint8(strrep(normalized, newline, sprintf('\r\n'))));
    cine_prebuilt_info(folder, computer('arch'));
    writeBytes(sourceFile, uint8([original, sprintf('\n# changed Rust build input\n')]));
    expectRejected(folder);
    writeBytes(sourceFile, uint8(original));

    % Size checks alone are insufficient: alter one byte without changing size.
    artifact = fullfile(target, library);
    fid = fopen(artifact, 'r+b');
    first = fread(fid, 1, '*uint8');
    fseek(fid, 0, 'bof');
    fwrite(fid, bitxor(first, uint8(1)), 'uint8');
    fclose(fid);
    expectRejected(folder);
    copyfile(fullfile(source, library), artifact);
    delete(fullfile(target, gateway));
    expectRejected(folder);
    copyfile(fullfile(source, gateway), fullfile(target, gateway));

    manifest = fullfile(target, 'build-info.json');
    incompatible = info;
    incompatible.abi_version = 99;
    writeBytes(manifest, unicode2native(jsonencode(incompatible), 'UTF-8'));
    expectRejected(folder);
    copyfile(fullfile(source, 'build-info.json'), manifest);
    cine_prebuilt_info(folder, computer('arch'));
    fprintf('MATLAB prebuilt validation and rejection tests passed.\n');
end

function expectRejected(root)
    rejected = false;
    try
        cine_prebuilt_info(root, computer('arch'));
    catch exception
        assert(strcmp(exception.identifier, 'cine:prebuilt'), 'Unexpected error: %s', exception.message);
        rejected = true;
    end
    assert(rejected, 'Invalid binaries or sources were accepted.');
end

function writeBytes(filename, bytes)
    fid = fopen(filename, 'wb');
    assert(fid ~= -1, 'Cannot write test input.');
    cleanup = onCleanup(@() fclose(fid));
    fwrite(fid, bytes, 'uint8');
end

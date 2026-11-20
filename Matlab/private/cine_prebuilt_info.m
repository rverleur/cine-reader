function [info, source, library, gateway] = cine_prebuilt_info(root, architecture)
    % CINE_PREBUILT_INFO Validate collected artifacts without loading native code.
    switch architecture
        case 'maca64'
            target = 'aarch64-apple-darwin';
            library = 'libcine_core.dylib';
            gateway = 'cine_mex.mexmaca64';
        case 'maci64'
            target = 'x86_64-apple-darwin';
            library = 'libcine_core.dylib';
            gateway = 'cine_mex.mexmaci64';
        case 'win64'
            target = 'x86_64-pc-windows-msvc';
            library = 'cine_core.dll';
            gateway = 'cine_mex.mexw64';
        case 'glnxa64'
            target = 'x86_64-unknown-linux-gnu';
            library = 'libcine_core.so';
            gateway = 'cine_mex.mexa64';
        otherwise
            error('cine:prebuilt', 'No collected backend supports MATLAB architecture %s.', architecture);
    end
    source = fullfile(root, 'binaries', target);
    manifest = fullfile(source, 'build-info.json');
    assert(isfile(manifest), 'cine:prebuilt', ...
           'No collected backend exists for %s. Obtain matching binaries or use build_cine_backend.', target);
    info = jsondecode(fileread(manifest));
    fields = {'schema_version', 'abi_version', 'target', 'source_fingerprint', 'artifacts', 'matlab_release'};
    assert(isstruct(info) && isscalar(info) && all(isfield(info, fields)), ...
           'cine:prebuilt', 'Invalid or incomplete MATLAB binary manifest.');
    assert(info.schema_version == 1 && info.abi_version == 1 && strcmp(info.target, target), ...
           'cine:prebuilt', 'Collected backend schema, ABI or target is incompatible.');
    assert(strcmp(info.source_fingerprint, sourceFingerprint(root)), 'cine:prebuilt', ...
           'Collected binaries are stale: Rust source inputs have changed. Rebuild before installing.');
    for name = {library, gateway}
        key = matlab.lang.makeValidName(name{1});
        assert(isfield(info.artifacts, key), 'cine:prebuilt', 'Manifest does not describe %s.', name{1});
        record = info.artifacts.(key);
        file = fullfile(source, name{1});
        details = dir(file);
        assert(isfile(file) && isfield(record, 'size') && details.bytes == record.size, ...
               'cine:prebuilt', 'Missing or incorrect-size binary: %s.', file);
        assert(isfield(record, 'sha256') && strcmp(fileDigest(file), record.sha256), ...
               'cine:prebuilt', 'Binary checksum mismatch: %s.', file);
    end
end

function result = sourceFingerprint(root)
    files = {'Cargo.toml', 'Cargo.lock', 'rust/cine-core/Cargo.toml'};
    for directory = {'rust/cine-core/src', 'rust/cine-core/include'}
        folder = fullfile(root, directory{1});
        assert(isfolder(folder), 'cine:prebuilt', 'Missing Rust source directory: %s.', folder);
        entries = dir(fullfile(folder, '**', '*'));
        for index = 1:numel(entries)
            if ~entries(index).isdir
                absolute = fullfile(entries(index).folder, entries(index).name);
                files{end + 1} = strrep(absolute(numel(root) + 2:end), filesep, '/'); %#ok<AGROW>
            end
        end
    end
    optional = {'rust/cine-core/build.rs', 'rust-toolchain', 'rust-toolchain.toml', ...
                '.cargo/config', '.cargo/config.toml'};
    for index = 1:numel(optional)
        if isfile(fullfile(root, optional{index}))
            files{end + 1} = optional{index}; %#ok<AGROW>
        end
    end
    files = sort(unique(files));
    combined = tempname;
    cleanupFile = onCleanup(@() delete(combined));
    fid = fopen(combined, 'wb');
    assert(fid ~= -1, 'cine:prebuilt', 'Cannot create a temporary source-fingerprint file.');
    cleanupStream = onCleanup(@() fclose(fid));
    for index = 1:numel(files)
        relative = files{index};
        data = readBytes(fullfile(root, relative));
        [~, name, extension] = fileparts(relative);
        if any(strcmp(extension, {'.rs', '.h', '.toml', '.lock'})) || any(strcmp(name, {'config', 'rust-toolchain'}))
            data([data(1:end - 1) == 13 & data(2:end) == 10; false]) = [];
        end
        prefix = [unicode2native(relative, 'UTF-8'), uint8(0)];
        lengthBytes = uint8(bitand(bitshift(uint64(numel(data)), -56:8:0), uint64(255)));
        fwrite(fid, prefix, 'uint8');
        fwrite(fid, lengthBytes, 'uint8');
        fwrite(fid, data, 'uint8');
    end
    clear cleanupStream;
    result = fileDigest(combined);
end

function result = fileDigest(filename)
    if ispc
        executable = fullfile(getenv('SystemRoot'), 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
        literal = strrep(filename, '''', '''''');
        % Module-loading progress must not prefix the digest with CLIXML.
        script = sprintf(['$ProgressPreference = ''SilentlyContinue''; ' ...
                          '$ErrorActionPreference = ''Stop''; ' ...
                          '(Get-FileHash -Algorithm SHA256 -LiteralPath ''%s'').Hash'], literal);
        encoded = matlab.net.base64encode(unicode2native(script, 'UTF-16LE'));
        command = sprintf('"%s" -NoProfile -NonInteractive -OutputFormat Text -EncodedCommand %s', executable, encoded);
    else
        % POSIX single-quote escaping keeps spaces and shell metacharacters literal.
        literal = ['''', strrep(filename, '''', '''"''"'''), ''''];
        if ismac
            command = ['/usr/bin/shasum -a 256 -- ' literal];
        else
            command = ['/usr/bin/sha256sum -- ' literal];
        end
    end
    [status, output] = system(command);
    result = lower(regexp(strtrim(output), '^[0-9a-fA-F]{64}', 'match', 'once'));
    assert(status == 0 && ~isempty(result), 'cine:prebuilt', 'Cannot compute SHA256 for %s.', filename);
end

function data = readBytes(filename)
    fid = fopen(filename, 'rb');
    assert(fid ~= -1, 'cine:prebuilt', 'Cannot read Rust source input: %s.', filename);
    cleanup = onCleanup(@() fclose(fid));
    data = fread(fid, Inf, '*uint8');
end

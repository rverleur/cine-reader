function cine_copy_binary(source, destination)
    % CINE_COPY_BINARY Publish native code without truncating a mapped Linux file.
    if ~isunix || ismac
        copyfile(source, destination);
        return
    end
    % Resolve symlinks even when the destination was removed. Use the Linux OS
    % utility to avoid release-dependent MATLAB fileattrib diagnostics.
    literal = ['''', strrep(destination, '''', '''"''"'''), ''''];
    [status, path] = system(['/usr/bin/readlink -f -- ' literal]);
    assert(status == 0 && numel(path) > 1 && path(end) == newline, ...
           'cine:install', 'Cannot resolve installed binary path: %s.', destination);
    path = path(1:end - 1); % Remove only the utility's newline, preserving filename whitespace.
    path = strrep(path, newline, '\012');
    mappings = splitlines(fileread('/proc/self/maps'));
    mapped = any(endsWith(mappings, [' ' path]) | endsWith(mappings, [' ' path ' (deleted)']));
    if mapped && (~isfile(destination) || ~isequal(readBytes(source), readBytes(destination)))
        error('cine:restart', ...
              'Restart MATLAB before installing a changed or removed backend that is still loaded: %s.', destination);
    end
    % Rust thread-local destructors can retain mappings after dlclose. Replacing
    % the directory entry preserves those mappings; copyfile in place does not.
    temporary = tempname(fileparts(destination));
    cleanup = onCleanup(@() removeTemporary(temporary));
    copyfile(source, temporary);
    movefile(temporary, destination, 'f');
end

function data = readBytes(filename)
    fid = fopen(filename, 'rb');
    assert(fid ~= -1, 'cine:install', 'Cannot read native binary: %s.', filename);
    cleanup = onCleanup(@() fclose(fid));
    data = fread(fid, Inf, '*uint8');
end

function removeTemporary(filename)
    if isfile(filename)
        delete(filename);
    end
end

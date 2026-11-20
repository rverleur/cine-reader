function cine_copy_binary(source, destination)
    % CINE_COPY_BINARY Publish native code without truncating a mapped Linux file.
    if ~isunix || ismac
        copyfile(source, destination);
        return
    end
    % fileattrib resolves symlinks on older MATLAB releases too; the newer
    % permission APIs do not provide this canonical path for loader matching.
    if isfile(destination)
        [status, attributes] = fileattrib(destination); %#ok<FILEATTRIB>
        assert(status, 'cine:install', 'Cannot inspect installed binary: %s.', destination);
        path = attributes.Name;
    else
        [parent, name, extension] = fileparts(destination);
        [status, attributes] = fileattrib(parent); %#ok<FILEATTRIB>
        assert(status, 'cine:install', 'Cannot inspect binary directory: %s.', parent);
        path = fullfile(attributes.Name, [name extension]);
    end
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

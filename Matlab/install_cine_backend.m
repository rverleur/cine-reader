function install_cine_backend
    % INSTALL_CINE_BACKEND Install verified binaries from this repository.
    % Requires MATLAB and OS hashing utilities, but no Rust, Python or C compiler. Run again
    % after updating the checkout. Close/delete all CINE objects first.
    if mislocked('cine_mex')
        error('cine:prebuilt', 'Close/delete all Cine and CineWriter objects before installing the backend.');
    end
    here = fileparts(mfilename('fullpath'));
    [info, source, library, gateway] = cine_prebuilt_info(fileparts(here), computer('arch'));
    checkRequirements(info);
    destination = fullfile(here, 'private', 'lib', computer('arch'));
    if ~isfolder(destination)
        mkdir(destination);
    end
    clear cine_mex cine_backend;
    cine_copy_binary(fullfile(source, library), fullfile(destination, library));
    cine_copy_binary(fullfile(source, gateway), fullfile(here, 'private', gateway));
    rehash;
    fprintf('Installed verified %s backend and %s gateway.\n', info.target, gateway);
    fprintf('Gateway built/tested with MATLAB R%s; running R%s.\n', info.matlab_release, version('-release'));
end

function checkRequirements(info)
    if ismac
        [status, output] = system('/usr/bin/sw_vers -productVersion');
        assert(status == 0 && versionAtLeast(strtrim(output), info.macos_deployment_target), ...
               'cine:prebuilt', 'This Rust backend requires macOS %s or newer.', info.macos_deployment_target);
    elseif isunix
        [status, output] = system('/usr/bin/getconf GNU_LIBC_VERSION');
        match = regexp(strtrim(output), '^glibc ([0-9.]+)$', 'tokens', 'once');
        assert(status == 0 && ~isempty(match) && strcmp(info.libc.name, 'glibc'), ...
               'cine:prebuilt', 'Cannot verify the required glibc runtime on this Linux system.');
        required = info.libc.minimum_version;
        if isfield(info, 'artifact_requirements')
            gateway = info.artifact_requirements.cine_mex_mexa64;
            if ~versionAtLeast(required, gateway.required_glibc_symbols_max)
                required = gateway.required_glibc_symbols_max;
            end
        end
        assert(versionAtLeast(match{1}, required), 'cine:prebuilt', ...
               'This MATLAB backend requires glibc %s or newer.', required);
    end
end

function yes = versionAtLeast(actual, required)
    pattern = '^\d+\.\d+(?:\.\d+)?$';
    assert(~isempty(regexp(actual, pattern, 'once')) && ~isempty(regexp(required, pattern, 'once')), ...
           'cine:prebuilt', 'Invalid system compatibility version in binary manifest or host runtime.');
    actualParts = sscanf(actual, '%d.%d.%d');
    requiredParts = sscanf(required, '%d.%d.%d');
    actualParts(end + 1:3) = 0;
    requiredParts(end + 1:3) = 0;
    difference = actualParts - requiredParts;
    first = find(difference ~= 0, 1);
    yes = isempty(first) || difference(first) > 0;
end

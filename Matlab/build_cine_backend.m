function build_cine_backend
    % BUILD_CINE_BACKEND Build the portable Rust library and thin MATLAB MEX bridge.
    % Run from any directory. Requires Rust/Cargo and a configured C MEX compiler.
    if mislocked('cine_mex')
        error('cine:build', 'Close/delete all Cine and CineWriter objects before rebuilding the loaded backend.');
    end
    here = fileparts(mfilename('fullpath'));
    root = fileparts(here);
    manifest = fullfile(root, 'rust', 'cine-core', 'Cargo.toml');
    cargo = 'cargo';
    if isunix
        candidate = fullfile(getenv('HOME'), '.cargo', 'bin', 'cargo');
        if isfile(candidate)
            cargo = candidate;
        end
    end
    command = sprintf('"%s" build --release --locked --offline --manifest-path "%s"', cargo, manifest);
    [status, output] = system(command);
    fprintf('%s', output);
    assert(status == 0, 'cine:build', 'Cargo build failed. Install Rust and put cargo on PATH.');
    if ispc
        library = 'cine_core.dll';
    elseif ismac
        library = 'libcine_core.dylib';
    else
        library = 'libcine_core.so';
    end
    targetDirectory = getenv('CARGO_TARGET_DIR');
    if isempty(targetDirectory)
        targetDirectory = fullfile(root, 'target');
    end
    librarySource = fullfile(targetDirectory, 'release', library);
    assert(isfile(librarySource), 'cine:build', 'Cannot locate the Cargo shared library output.');
    destination = fullfile(here, 'private', 'lib', computer('arch'));
    if ~isfolder(destination)
        mkdir(destination);
    end
    clear cine_mex cine_backend;
    copyfile(librarySource, fullfile(destination, library));
    args = {'-R2018a', ['-I' fullfile(root, 'rust', 'cine-core', 'include')], ...
            fullfile(here, 'private', 'cine_mex.c'), '-outdir', fullfile(here, 'private')};
    if isunix && ~ismac
        args{end + 1} = '-ldl';
    end
    mex(args{:});
    fprintf('Built the Rust CINE backend and %s adapter.\n', mexext);
end

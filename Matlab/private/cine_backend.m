function varargout = cine_backend(varargin)
    % CINE_BACKEND Locate and initialize the platform Rust backend once.
    persistent lib
    if isempty(lib)
        here = fileparts(mfilename('fullpath'));
        if ispc
            name = 'cine_core.dll';
        elseif ismac
            name = 'libcine_core.dylib';
        else
            name = 'libcine_core.so';
        end
        lib = fullfile(here, 'lib', computer('arch'), name);
        if ~isfile(lib) || ~isfile(fullfile(here, ['cine_mex.' mexext]))
            lib = [];
            error('cine:build', ...
                  ['Backend not installed for %s. Run install_cine_backend to use the collected binaries, ' ...
                   'or build_cine_backend to compile from source.'], computer('arch'));
        end
    end
    cine_mex('init', lib);
    [varargout{1:nargout}] = cine_mex(varargin{:});
end

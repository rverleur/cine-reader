function check_commit
    % CHECK_COMMIT Build and validate MATLAB code before a Git commit.
    % This runs inside the staged snapshot prepared by scripts/check_commit.py.
    % CINE_TEST_CORPUS optionally enables the external camera-file tests.

    here = fileparts(mfilename('fullpath'));
    files = dir(fullfile(here, '**', '*.m'));
    issueCount = 0;
    for index = 1:numel(files)
        filename = fullfile(files(index).folder, files(index).name);
        issues = checkcode(filename, '-id');
        for item = 1:numel(issues)
            fprintf(2, '%s:%d: %s\n', filename, issues(item).line, issues(item).message);
        end
        issueCount = issueCount + numel(issues);
    end
    assert(issueCount == 0, 'cine:quality', ...
           'MATLAB Code Analyzer reported %d issue(s).', issueCount);
    build_cine_backend;
    test_rust_backend(getenv('CINE_TEST_CORPUS'));
    fprintf('MATLAB compilation, Code Analyzer and tests passed.\n');
end

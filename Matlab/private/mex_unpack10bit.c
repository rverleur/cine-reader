// private/mex_unpack10bit.c
// Build: see instructions below.
// Usage (from MATLAB):
//    pix = mex_unpack10bit(uint8_raw, libPath, unpackFuncName, freeFuncName);
//
// Where:
//   - uint8_raw:   raw packed 10-bit image bytes (uint8 vector)
//   - libPath:     full path to .dll/.dylib/.so (string)
//   - unpackFuncName: symbol name in that lib (e.g., "unpack_data_arm64")
//   - freeFuncName:   symbol name for freeing the returned pointer (e.g., "free_pixel_data")

#include "mex.h"
#include <stdint.h>
#include <string.h>

#if defined(_WIN32)
  #include <windows.h>
  typedef HMODULE lib_handle_t;
  #define LOAD_LIB(path) LoadLibraryA(path)
  #define GET_SYM(lib, name) GetProcAddress(lib, name)
  #define CLOSE_LIB(lib) FreeLibrary(lib)
#elif defined(__APPLE__) || defined(__linux__)
  #include <dlfcn.h>
  typedef void* lib_handle_t;
  #define LOAD_LIB(path) dlopen(path, RTLD_NOW | RTLD_LOCAL)
  #define GET_SYM(lib, name) dlsym(lib, name)
  #define CLOSE_LIB(lib) dlclose(lib)
#else
  #error "Unsupported platform"
#endif

typedef uint16_t* (*unpack_fn_t)(const uint8_t*, size_t, size_t*);
typedef void      (*free_fn_t)(uint16_t*);

static void die(const char* msg) {
    mexErrMsgIdAndTxt("mex_unpack10bit:error", "%s", msg);
}

void mexFunction(int nlhs, mxArray *plhs[], int nrhs, const mxArray *prhs[])
{
    if (nrhs != 4)
        die("Expected 4 inputs: (uint8_raw, libPath, unpackFuncName, freeFuncName)");
    if (nlhs != 1)
        die("One output (uint16 vector) is required.");

    // Input 0: raw bytes
    if (!mxIsUint8(prhs[0]) || mxIsComplex(prhs[0]))
        die("First input must be uint8 vector.");
    size_t nbytes = mxGetNumberOfElements(prhs[0]);
    const uint8_t* raw = (const uint8_t*)mxGetData(prhs[0]);

    // Input 1: libPath
    if (!mxIsChar(prhs[1])) die("libPath must be a string.");
    char libPath[4096]; mxGetString(prhs[1], libPath, sizeof(libPath));

    // Input 2: unpack function name
    if (!mxIsChar(prhs[2])) die("unpackFuncName must be a string.");
    char unpackName[256]; mxGetString(prhs[2], unpackName, sizeof(unpackName));

    // Input 3: free function name
    if (!mxIsChar(prhs[3])) die("freeFuncName must be a string.");
    char freeName[256]; mxGetString(prhs[3], freeName, sizeof(freeName));

    // Load the shared library
    lib_handle_t lib = LOAD_LIB(libPath);
    if (!lib) {
    #if defined(__APPLE__) || defined(__linux__)
        const char* err = dlerror();
        mexErrMsgIdAndTxt("mex_unpack10bit:loadlib", "Failed to load %s: %s", libPath, err ? err : "(no detail)");
    #else
        mexErrMsgIdAndTxt("mex_unpack10bit:loadlib", "Failed to load %s", libPath);
    #endif
    }

    // Resolve symbols
    unpack_fn_t unpack_fn = (unpack_fn_t) GET_SYM(lib, unpackName);
    if (!unpack_fn) {
        CLOSE_LIB(lib);
        mexErrMsgIdAndTxt("mex_unpack10bit:getsym", "Could not find symbol '%s' in %s", unpackName, libPath);
    }
    free_fn_t free_fn = (free_fn_t) GET_SYM(lib, freeName);
    if (!free_fn) {
        CLOSE_LIB(lib);
        mexErrMsgIdAndTxt("mex_unpack10bit:getsym", "Could not find symbol '%s' in %s", freeName, libPath);
    }

    // Call unpack
    size_t outCount = 0;
    uint16_t* outPtr = unpack_fn(raw, nbytes, &outCount);
    if (!outPtr) {
        CLOSE_LIB(lib);
        die("unpack function returned NULL.");
    }

    // Copy into MATLAB array
    plhs[0] = mxCreateUninitNumericMatrix((mwSize)outCount, 1, mxUINT16_CLASS, mxREAL);
    uint16_t* dst = (uint16_t*) mxGetData(plhs[0]);
    memcpy(dst, outPtr, outCount * sizeof(uint16_t));

    // Free C buffer and close lib
    free_fn(outPtr);
    CLOSE_LIB(lib);
}

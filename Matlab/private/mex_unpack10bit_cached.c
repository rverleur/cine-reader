// private/mex_unpack10bit_cached.c
// Cached loader for your unpack shared library.
// Commands:
//   mex_unpack10bit_cached('init', libPath, unpackSymbol, freeSymbol)
//   pix = mex_unpack10bit_cached(uint8_raw)
//   mex_unpack10bit_cached('close')   % optional
//
// Linux needs -ldl at link time.

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

static lib_handle_t g_lib = NULL;
static unpack_fn_t  g_unpack = NULL;
static free_fn_t    g_free   = NULL;

static void die(const char* id, const char* msg){ mexErrMsgIdAndTxt(id, "%s", msg); }

void mexFunction(int nlhs, mxArray *plhs[], int nrhs, const mxArray *prhs[])
{
    // Command mode if first arg is char
    if (nrhs >= 1 && mxIsChar(prhs[0])) {
        char cmd[16]; mxGetString(prhs[0], cmd, sizeof(cmd));
        if (!strcmp(cmd,"init")) {
            if (nrhs != 4) die("unpack:init", "Usage: mex_unpack10bit_cached('init', libPath, unpackName, freeName)");
            if (g_lib) { return; } // already init
            char libPath[4096], unpackName[256], freeName[256];
            mxGetString(prhs[1], libPath, sizeof(libPath));
            mxGetString(prhs[2], unpackName, sizeof(unpackName));
            mxGetString(prhs[3], freeName, sizeof(freeName));
            g_lib = LOAD_LIB(libPath);
            if (!g_lib) die("unpack:init", "Failed to load library.");
            g_unpack = (unpack_fn_t)GET_SYM(g_lib, unpackName);
            g_free   = (free_fn_t)  GET_SYM(g_lib, freeName);
            if (!g_unpack || !g_free) {
                CLOSE_LIB(g_lib); g_lib=NULL; g_unpack=NULL; g_free=NULL;
                die("unpack:init", "Failed to resolve symbols.");
            }
            return;
        } else if (!strcmp(cmd,"close")) {
            if (g_lib) { CLOSE_LIB(g_lib); g_lib=NULL; g_unpack=NULL; g_free=NULL; }
            return;
        } else {
            die("unpack:cmd", "Unknown command.");
        }
    }

    if (!g_unpack || !g_free) die("unpack:use", "Not initialized. Call init first.");

    if (nrhs != 1 || !mxIsUint8(prhs[0])) die("unpack:args", "Provide a uint8 vector of packed data.");
    size_t nbytes = mxGetNumberOfElements(prhs[0]);
    const uint8_t* raw = (const uint8_t*)mxGetData(prhs[0]);

    size_t outCount = 0;
    uint16_t* outPtr = g_unpack(raw, nbytes, &outCount);
    if (!outPtr) die("unpack:call", "unpack returned NULL.");

    plhs[0] = mxCreateUninitNumericMatrix((mwSize)outCount, 1, mxUINT16_CLASS, mxREAL);
    memcpy(mxGetData(plhs[0]), outPtr, outCount*sizeof(uint16_t));
    g_free(outPtr);
}

/* Thin MATLAB allocation, lifetime and array-layout adapter. Decoding and
 * processing are implemented by the portable Rust library. */
#include "mex.h"
#include "cine_core.h"
#include <string.h>
#include <stdlib.h>
#include <math.h>
#ifdef _WIN32
#include <windows.h>
static HMODULE library;
#define SYM(n) GetProcAddress(library, n)
#else
#include <dlfcn.h>
static void *library;
#define SYM(n) dlsym(library, n)
#endif
static uint32_t (*p_cine_abi_version)(void);
#define cine_abi_version p_cine_abi_version
static const char *(*p_cine_last_error)(void);
#define cine_last_error p_cine_last_error
static void *(*p_cine_reader_open)(const char *path);
#define cine_reader_open p_cine_reader_open
static void (*p_cine_reader_close)(void *reader);
#define cine_reader_close p_cine_reader_close
static int32_t (*p_cine_reader_info)(void *reader, CineInfo *info);
#define cine_reader_info p_cine_reader_info
static int32_t (*p_cine_reader_offset)(void *reader, uint32_t index, uint64_t *offset);
#define cine_reader_offset p_cine_reader_offset
static int32_t (*p_cine_reader_block)(void *reader, uint32_t kind, uint8_t *out, size_t capacity, size_t *written);
#define cine_reader_block p_cine_reader_block
static int32_t (*p_cine_reader_read_at)(void *reader, uint64_t offset, uint8_t *out, size_t length);
#define cine_reader_read_at p_cine_reader_read_at
static int32_t (*p_cine_reader_read_frame)(void *reader, uint32_t index, uint32_t flags, uint8_t *out, size_t capacity, CineFrameInfo *info);
#define cine_reader_read_frame p_cine_reader_read_frame
static int32_t (*p_cine_reader_trim)(void *reader, const char *path, uint32_t start_index, uint32_t count);
#define cine_reader_trim p_cine_reader_trim
static int32_t (*p_cine_decode)(const uint8_t *data, size_t length, uint32_t width, int32_t height, uint32_t bit_count, uint32_t compression, uint32_t flags, uint8_t *out, size_t capacity);
#define cine_decode p_cine_decode
static int32_t (*p_cine_unpack10)(const uint8_t *data, size_t length, uint16_t *out, size_t samples);
#define cine_unpack10 p_cine_unpack10
static void *(*p_cine_writer_create)(const char *path, const CineWriterOptions *options);
#define cine_writer_create p_cine_writer_create
static int32_t (*p_cine_writer_write)(void *writer, const uint8_t *data, size_t length);
#define cine_writer_write p_cine_writer_write
static int32_t (*p_cine_writer_write_image)(void *writer, const uint8_t *data, size_t length, uint32_t sample_bytes, uint32_t channels);
#define cine_writer_write_image p_cine_writer_write_image
static int32_t (*p_cine_writer_finish)(void *writer);
#define cine_writer_finish p_cine_writer_finish
static void (*p_cine_writer_close)(void *writer);
#define cine_writer_close p_cine_writer_close
static int32_t (*p_cine_process)(const void *src, void *dst, uint32_t width, uint32_t height, uint32_t channels, uint32_t sample_type, uint32_t op, uint32_t param, double value);
#define cine_process p_cine_process
static void *(*p_cine_stats_create)(size_t samples, uint32_t mode, uint32_t k, double q, double sigma, uint32_t min_keep);
#define cine_stats_create p_cine_stats_create
static int32_t (*p_cine_stats_push)(void *stats, const double *values, size_t samples);
#define cine_stats_push p_cine_stats_push
static int32_t (*p_cine_stats_finish)(void *stats, double *out, size_t samples, uint64_t *count);
#define cine_stats_finish p_cine_stats_finish
static void (*p_cine_stats_close)(void *stats);
#define cine_stats_close p_cine_stats_close
#define LOAD(n) do { *(void **)(&p_##n) = (void *)SYM(#n); if (!p_##n) mexErrMsgIdAndTxt("cine:abi", "Missing Rust symbol: %s", #n); } while(0)

typedef struct Handle {
    uint64_t id; void *ptr; int kind;
    CineInfo info; CineWriterOptions options;
    struct Handle *next;
} Handle;
static Handle *handles;
static uint64_t next_id = 1;
static void cleanup(void) {
    while (handles) {
        Handle *h = handles; handles = h->next;
        if (h->kind == 0) cine_reader_close(h->ptr);
        else if (h->kind == 1) cine_writer_close(h->ptr);
        else cine_stats_close(h->ptr);
        free(h);
    }
    if (library) {
#ifdef _WIN32
        FreeLibrary(library);
#else
        dlclose(library);
#endif
        library = NULL;
    }
}
static void init(const mxArray *path) {
    char *name = mxArrayToUTF8String(path);
    if (!name) mexErrMsgIdAndTxt("cine:path", "Expected library path.");
    if (library) { mxFree(name); return; }
#ifdef _WIN32
    int wide_len = MultiByteToWideChar(CP_UTF8, 0, name, -1, NULL, 0);
    wchar_t *wide = (wchar_t *)mxMalloc(wide_len * sizeof(wchar_t));
    MultiByteToWideChar(CP_UTF8, 0, name, -1, wide, wide_len);
    library = LoadLibraryW(wide); mxFree(wide);
#else
    library = dlopen(name, RTLD_NOW | RTLD_LOCAL);
#endif
    mxFree(name);
    if (!library) mexErrMsgIdAndTxt("cine:library", "Unable to load Rust backend.");
    LOAD(cine_abi_version);
    LOAD(cine_last_error);
    LOAD(cine_reader_open);
    LOAD(cine_reader_close);
    LOAD(cine_reader_info);
    LOAD(cine_reader_offset);
    LOAD(cine_reader_block);
    LOAD(cine_reader_read_at);
    LOAD(cine_reader_read_frame);
    LOAD(cine_reader_trim);
    LOAD(cine_decode);
    LOAD(cine_unpack10);
    LOAD(cine_writer_create);
    LOAD(cine_writer_write);
    LOAD(cine_writer_write_image);
    LOAD(cine_writer_finish);
    LOAD(cine_writer_close);
    LOAD(cine_process);
    LOAD(cine_stats_create);
    LOAD(cine_stats_push);
    LOAD(cine_stats_finish);
    LOAD(cine_stats_close);
    if (cine_abi_version() != 1) mexErrMsgIdAndTxt("cine:abi", "Unsupported Rust ABI.");
    mexAtExit(cleanup);
}
static void check(int status) {
    if (status) mexErrMsgIdAndTxt("cine:backend", "%s", cine_last_error());
}
static Handle *lookup(const mxArray *a, int kind) {
    if (!mxIsUint64(a) || mxGetNumberOfElements(a) != 1) mexErrMsgIdAndTxt("cine:handle", "Invalid backend handle.");
    uint64_t id = *(uint64_t *)mxGetData(a);
    for (Handle *h = handles; h; h = h->next) if (h->id == id && h->kind == kind) return h;
    mexErrMsgIdAndTxt("cine:handle", "Closed or invalid backend handle."); return NULL;
}
static mxArray *scalar_u64(uint64_t v) {
    mxArray *a = mxCreateNumericMatrix(1, 1, mxUINT64_CLASS, mxREAL); *(uint64_t *)mxGetData(a) = v; return a;
}
static mxArray *register_handle(void *p, int kind, Handle **registered) {
    if (!p) mexErrMsgIdAndTxt("cine:backend", "%s", cine_last_error());
    Handle *h = (Handle *)calloc(1, sizeof(Handle));
    if (!h) mexErrMsgIdAndTxt("cine:memory", "Cannot allocate handle.");
    h->ptr = p; h->kind = kind; h->id = next_id++; h->next = handles; handles = h;
    mexLock(); *registered = h; return scalar_u64(h->id);
}
static void remove_handle(Handle *h) {
    Handle **previous = &handles;
    while (*previous != h) previous = &(*previous)->next;
    *previous = h->next;
    if (h->kind == 0) cine_reader_close(h->ptr);
    else if (h->kind == 1) cine_writer_close(h->ptr);
    else cine_stats_close(h->ptr);
    free(h); mexUnlock();
}
static uint32_t u32(const unsigned char *p) { return (uint32_t)p[0] | ((uint32_t)p[1]<<8) | ((uint32_t)p[2]<<16) | ((uint32_t)p[3]<<24); }
static uint16_t u16(const unsigned char *p) { return (uint16_t)p[0] | ((uint16_t)p[1]<<8); }
static uint64_t u64(const unsigned char *p) { return (uint64_t)u32(p) | ((uint64_t)u32(p+4)<<32); }
static mxArray *block(void *h, uint32_t kind) {
    size_t n = 0; check(cine_reader_block(h, kind, NULL, 0, &n));
    mxArray *a = mxCreateNumericMatrix(n, 1, mxUINT8_CLASS, mxREAL);
    check(cine_reader_block(h, kind, (uint8_t *)mxGetData(a), n, &n)); return a;
}
static void field(mxArray *a, const char *name, double value) {
    mxClassID cls = mxUINT32_CLASS;
    if (!strcmp(name,"dFrameRate")) cls = mxDOUBLE_CLASS;
    else if (!strcmp(name,"Headersize") || !strcmp(name,"Compression") || !strcmp(name,"Version") || !strcmp(name,"biPlanes") || !strcmp(name,"biBitCount") || !strcmp(name,"Length")) cls = mxUINT16_CLASS;
    else if (!strcmp(name,"FirstMovieImage") || !strcmp(name,"FirstImageNo") || !strcmp(name,"biWidth") || !strcmp(name,"biHeight") || !strcmp(name,"biXPelsPerMeter") || !strcmp(name,"biYPelsPerMeter") || !strcmp(name,"WhiteLevel") || !strcmp(name,"BlackLevel")) cls = mxINT32_CLASS;
    mxArray *v = mxCreateNumericMatrix(1,1,cls,mxREAL);
    if(cls==mxDOUBLE_CLASS) *(double *)mxGetData(v)=value;
    else if(cls==mxINT32_CLASS) *(int32_t *)mxGetData(v)=(int32_t)value;
    else if(cls==mxUINT16_CLASS) *(uint16_t *)mxGetData(v)=(uint16_t)value;
    else *(uint32_t *)mxGetData(v)=(uint32_t)value;
    mxSetField(a,0,name,v);
}
static mxArray *file_header(void *h) {
    const char *fields[] = {"FileHeaderData","Type","Headersize","Compression","Version","FirstMovieImage","TotalImageCount","FirstImageNo","ImageCount","OffImageHeader","OffSetup","OffImageOffsets","TriggerTime"};
    mxArray *s = mxCreateStructMatrix(1,1,13,fields), *raw = block(h,0);
    const uint8_t *b = (const uint8_t *)mxGetData(raw);
    mxSetField(s,0,"FileHeaderData",raw);
    mxArray *type = mxCreateNumericMatrix(2,1,mxUINT8_CLASS,mxREAL); memcpy(mxGetData(type),b,2); mxSetField(s,0,"Type",type);
    field(s,"Headersize",u16(b+2)); field(s,"Compression",u16(b+4)); field(s,"Version",u16(b+6));
    field(s,"FirstMovieImage",(int32_t)u32(b+8)); field(s,"TotalImageCount",u32(b+12));
    field(s,"FirstImageNo",(int32_t)u32(b+16)); field(s,"ImageCount",u32(b+20));
    field(s,"OffImageHeader",u32(b+24)); field(s,"OffSetup",u32(b+28)); field(s,"OffImageOffsets",u32(b+32));
    mxSetField(s,0,"TriggerTime",scalar_u64(u64(b+36))); return s;
}
static mxArray *bitmap_header(void *h) {
    const char *fields[] = {"ImageHeaderData","biSize","biWidth","biHeight","biPlanes","biBitCount","biCompression","biSizeImage","biXPelsPerMeter","biYPelsPerMeter","biClrUsed","biClrImportant"};
    mxArray *s=mxCreateStructMatrix(1,1,12,fields), *raw=block(h,1); const uint8_t *b=mxGetData(raw);
    mxSetField(s,0,"ImageHeaderData",raw);
    field(s,"biSize",u32(b)); field(s,"biWidth",(int32_t)u32(b+4)); field(s,"biHeight",(int32_t)u32(b+8));
    field(s,"biPlanes",u16(b+12)); field(s,"biBitCount",u16(b+14)); field(s,"biCompression",u32(b+16));
    field(s,"biSizeImage",u32(b+20)); field(s,"biXPelsPerMeter",(int32_t)u32(b+24)); field(s,"biYPelsPerMeter",(int32_t)u32(b+28));
    field(s,"biClrUsed",u32(b+32)); field(s,"biClrImportant",u32(b+36)); return s;
}
static mxArray *setup(void *h) {
    const char *fields[]={"SetupData","RealBPP","FrameRate","bEnableColor","CFA","Length","WhiteLevel","BlackLevel","ShutterNs","dFrameRate"};
    mxArray *s=mxCreateStructMatrix(1,1,10,fields), *raw=block(h,2); const uint8_t *b=mxGetData(raw); size_t n=mxGetNumberOfElements(raw);
    mxSetField(s,0,"SetupData",raw);
    field(s,"RealBPP",n>=900?u32(b+896):0); field(s,"FrameRate",n>=772?u32(b+768):0);
    mxSetField(s,0,"bEnableColor",mxCreateLogicalScalar(n>=792 && u32(b+788)));
    field(s,"CFA",n>=812?u32(b+808):0); field(s,"Length",n>=144?u16(b+142):0);
    field(s,"WhiteLevel",n>=5740?(int32_t)u32(b+5736):0); field(s,"BlackLevel",n>=5736?(int32_t)u32(b+5732):0);
    field(s,"ShutterNs",n>=1572?u32(b+1568):0);
    double rate=0; if(n>=10408){uint64_t bits=u64(b+10400);memcpy(&rate,&bits,8);} field(s,"dFrameRate",rate); return s;
}
/* Small tiles keep both row-major input and MATLAB columns cache-friendly.
 * Typed assignments avoid one dynamic memcpy call for every pixel sample. */
#define COPY_LAYOUT(T) do { \
    T *d=(T *)dst; const T *s=(const T *)src; \
    for(size_t ch=0;ch<c;ch++) for(size_t xb=0;xb<w;xb+=32) for(size_t yb=0;yb<h;yb+=32) \
    for(size_t x=xb;x<w&&x<xb+32;x++) for(size_t y=yb;y<h&&y<yb+32;y++) { \
        size_t m=y+h*(x+w*ch),r=ch+c*(x+w*y); \
        if(to_matlab)d[m]=s[r];else d[r]=s[m]; \
    } \
} while(0)
static void layout(void *dst,const void *src,size_t h,size_t w,size_t c,size_t bytes,int to_matlab) {
    switch(bytes) {
        case 1: COPY_LAYOUT(uint8_t); break;
        case 2: COPY_LAYOUT(uint16_t); break;
        case 4: COPY_LAYOUT(uint32_t); break;
        case 8: COPY_LAYOUT(uint64_t); break;
        default: mexErrMsgIdAndTxt("cine:type","Unsupported sample width.");
    }
}
#undef COPY_LAYOUT
static mxArray *array(size_t h,size_t w,size_t c,mxClassID cls) {
    mwSize dims[3]={(mwSize)h,(mwSize)w,(mwSize)c}; return mxCreateNumericArray(c==1?2:3,dims,cls,mxREAL);
}
static uint32_t sample_type(const mxArray *a) {
    if(mxIsComplex(a)) mexErrMsgIdAndTxt("cine:type","Complex arrays are unsupported.");
    switch(mxGetClassID(a)) {case mxUINT8_CLASS:return 1;case mxUINT16_CLASS:return 2;case mxSINGLE_CLASS:return 4;case mxDOUBLE_CLASS:return 8;default:mexErrMsgIdAndTxt("cine:type","Use uint8, uint16, single or double arrays.");} return 0;
}
static double number(const mxArray *a) {
    if(!a || !mxIsNumeric(a) || mxGetNumberOfElements(a)!=1 || mxIsComplex(a) || !isfinite(mxGetScalar(a))) mexErrMsgIdAndTxt("cine:argument","Expected a finite numeric scalar.");
    return mxGetScalar(a);
}
static void arity(int nrhs,int wanted,int nlhs,int outputs) {
    if(nrhs!=wanted || nlhs!=outputs) mexErrMsgIdAndTxt("cine:argument","Wrong number of command arguments or results.");
}

void mexFunction(int nlhs,mxArray *plhs[],int nrhs,const mxArray *prhs[]) {
    if(nrhs<1 || !mxIsChar(prhs[0])) mexErrMsgIdAndTxt("cine:command","Expected command text.");
    char command[32]; mxGetString(prhs[0],command,sizeof(command));
    if(!strcmp(command,"init")){arity(nrhs,2,nlhs,0);init(prhs[1]);return;}
    if(!library) mexErrMsgIdAndTxt("cine:init","Rust backend is not initialized.");
    if(!strcmp(command,"open")) {
        arity(nrhs,2,nlhs,4); char *path=mxArrayToUTF8String(prhs[1]);
        if(!path) mexErrMsgIdAndTxt("cine:path","Expected filename.");
        void *p=cine_reader_open(path);mxFree(path);Handle *h;
        plhs[0]=register_handle(p,0,&h);check(cine_reader_info(p,&h->info));
        plhs[1]=file_header(p);plhs[2]=bitmap_header(p);plhs[3]=setup(p);return;
    }
    if(!strcmp(command,"close")){arity(nrhs,2,nlhs,0);remove_handle(lookup(prhs[1],0));return;}
    if(!strcmp(command,"read")) {
        arity(nrhs,4,nlhs,4);Handle *h=lookup(prhs[1],0);CineInfo *i=&h->info;
        double frame=number(prhs[2]), index=frame-i->first_frame;
        if(index<0 || index>=i->frame_count || floor(index)!=index) mexErrMsgIdAndTxt("cine:frame","Frame number out of bounds.");
        size_t height=(size_t)abs(i->height); uint8_t *raw=mxMalloc((size_t)i->decoded_bytes);CineFrameInfo fi;
        int status=cine_reader_read_frame(h->ptr,(uint32_t)index,0,raw,(size_t)i->decoded_bytes,&fi);
        if(status){mxFree(raw);check(status);}
        plhs[0]=array(height,i->width,i->channels,i->sample_bytes==1?mxUINT8_CLASS:mxUINT16_CLASS);
        layout(mxGetData(plhs[0]),raw,height,i->width,i->channels,i->sample_bytes,1);mxFree(raw);
        plhs[1]=mxCreateNumericMatrix(1,1,mxUINT32_CLASS,mxREAL);*(uint32_t*)mxGetData(plhs[1])=fi.annotation_size;
        plhs[2]=mxCreateNumericMatrix(1,1,mxUINT32_CLASS,mxREAL);*(uint32_t*)mxGetData(plhs[2])=fi.image_size;
        plhs[3]=mxIsLogicalScalarTrue(prhs[3])?block(h->ptr,3):mxCreateNumericMatrix(0,1,mxUINT8_CLASS,mxREAL);return;
    }
    if(!strcmp(command,"setup_data")){arity(nrhs,2,nlhs,1);plhs[0]=block(lookup(prhs[1],0)->ptr,5);return;}
    if(!strcmp(command,"offsets")) {
        arity(nrhs,2,nlhs,1);Handle *h=lookup(prhs[1],0);mxArray *raw=block(h->ptr,6);
        size_t n=h->info.frame_count;plhs[0]=mxCreateNumericMatrix(n+1,1,mxUINT64_CLASS,mxREAL);
        uint64_t *out=mxGetData(plhs[0]);const uint8_t *p=mxGetData(raw);size_t bytes=n?mxGetNumberOfElements(raw)/n:8;
        for(size_t j=0;j<n;j++)out[j]=bytes==8?u64(p+j*8):u32(p+j*4);
        out[n]=h->info.file_size;mxDestroyArray(raw);return;
    }
    if(!strcmp(command,"trim")) {
        arity(nrhs,5,nlhs,0);Handle *h=lookup(prhs[1],0);double first=number(prhs[3])-h->info.first_frame, last=number(prhs[4])-h->info.first_frame;
        if(first<0 || last<first || last>=h->info.frame_count || floor(first)!=first || floor(last)!=last) mexErrMsgIdAndTxt("cine:range","Frame range out of bounds.");
        char *path=mxArrayToUTF8String(prhs[2]);if(!path)mexErrMsgIdAndTxt("cine:path","Expected output filename.");
        int status=cine_reader_trim(h->ptr,path,(uint32_t)first,(uint32_t)(last-first+1));mxFree(path);check(status);return;
    }
    if(!strcmp(command,"process")) {
        arity(nrhs,5,nlhs,1);const mxArray *input=prhs[1];uint32_t st=sample_type(input),op=(uint32_t)number(prhs[2]),param=(uint32_t)number(prhs[3]);
        const mwSize *dims=mxGetDimensions(input);size_t h=dims[0],w=dims[1],c=mxGetNumberOfDimensions(input)>2?dims[2]:1;
        if(mxGetNumberOfDimensions(input)>3 || h==0 || w==0 || h>UINT32_MAX || w>UINT32_MAX || (c!=1&&c!=3))mexErrMsgIdAndTxt("cine:shape","Expected a nonempty HxW or HxWx3 array.");
        if(op==3 && c!=1)mexErrMsgIdAndTxt("cine:shape","Demosaic requires a mono/Bayer array.");
        size_t outc=op==3?3:c,bytes=h*w*c*st;
        void *src=mxMalloc(bytes),*dst=mxMalloc(h*w*outc*st);layout(src,mxGetData(input),h,w,c,st,0);
        int status=cine_process(src,dst,(uint32_t)w,(uint32_t)h,(uint32_t)c,st,op,param,number(prhs[4]));mxFree(src);
        if(status){mxFree(dst);check(status);}
        plhs[0]=array(h,w,outc,mxGetClassID(input));layout(mxGetData(plhs[0]),dst,h,w,outc,st,1);mxFree(dst);return;
    }
    if(!strcmp(command,"writer_open")) {
        arity(nrhs,3,nlhs,1);const mxArray *a=prhs[2];
        if(!mxIsDouble(a)||mxGetNumberOfElements(a)!=9)mexErrMsgIdAndTxt("cine:options","Expected writer options vector.");
        const double *v=mxGetDoubles(a);for(size_t j=0;j<9;j++)if(!isfinite(v[j]))mexErrMsgIdAndTxt("cine:options","Writer options must be finite.");
        for(size_t j=0;j<8;j++)if(floor(v[j])!=v[j] || (j!=6 && (v[j]<0 || v[j]>UINT32_MAX)))mexErrMsgIdAndTxt("cine:options","Invalid integer writer option.");
        if(v[6]<INT32_MIN||v[6]>INT32_MAX)mexErrMsgIdAndTxt("cine:options","Invalid first frame.");
        CineWriterOptions options={(uint32_t)v[0],(uint32_t)v[1],(uint32_t)v[2],(uint32_t)v[3],(uint32_t)v[4],(uint32_t)v[5],(int32_t)v[6],(uint32_t)v[7],v[8]};
        char *path=mxArrayToUTF8String(prhs[1]);if(!path)mexErrMsgIdAndTxt("cine:path","Expected output filename.");
        void *p=cine_writer_create(path,&options);mxFree(path);Handle *h;plhs[0]=register_handle(p,1,&h);h->options=options;return;
    }
    if(!strcmp(command,"writer_write")) {
        arity(nrhs,3,nlhs,0);Handle *h=lookup(prhs[1],1);const mxArray *a=prhs[2];CineWriterOptions *o=&h->options;
        uint32_t st=sample_type(a),wanted=o->bit_depth<=8&&!o->packed10?1:2;
        const mwSize *d=mxGetDimensions(a);size_t c=mxGetNumberOfDimensions(a)>2?d[2]:1;
        if((st!=1&&st!=2)||(!o->packed10 && st!=wanted)||mxGetNumberOfDimensions(a)>3||d[0]!=o->height||d[1]!=o->width||(c!=1&&c!=3)||(!o->packed10&&c!=o->channels))mexErrMsgIdAndTxt("cine:shape","Frame shape or uint8/uint16 type differs from writer options.");
        size_t bytes=mxGetNumberOfElements(a)*st;void *raw=mxMalloc(bytes);layout(raw,mxGetData(a),o->height,o->width,c,st,0);
        int status=cine_writer_write_image(h->ptr,raw,bytes,st,(uint32_t)c);mxFree(raw);check(status);return;
    }
    if(!strcmp(command,"writer_finish")){arity(nrhs,2,nlhs,0);Handle *h=lookup(prhs[1],1);check(cine_writer_finish(h->ptr));remove_handle(h);return;}
    if(!strcmp(command,"writer_close")){arity(nrhs,2,nlhs,0);remove_handle(lookup(prhs[1],1));return;}
    if(!strcmp(command,"stats_open")) {
        arity(nrhs,7,nlhs,1);double samples=number(prhs[1]);if(samples<1||floor(samples)!=samples)mexErrMsgIdAndTxt("cine:shape","Statistics need at least one sample.");
        Handle *h;plhs[0]=register_handle(cine_stats_create((size_t)samples,(uint32_t)number(prhs[2]),(uint32_t)number(prhs[3]),number(prhs[4]),number(prhs[5]),(uint32_t)number(prhs[6])),2,&h);return;
    }
    if(!strcmp(command,"stats_push")){arity(nrhs,3,nlhs,0);Handle *h=lookup(prhs[1],2);if(!mxIsDouble(prhs[2])||mxIsComplex(prhs[2]))mexErrMsgIdAndTxt("cine:type","Statistics require real double input.");check(cine_stats_push(h->ptr,mxGetDoubles(prhs[2]),mxGetNumberOfElements(prhs[2])));return;}
    if(!strcmp(command,"stats_finish")) {
        arity(nrhs,3,nlhs,1);Handle *h=lookup(prhs[1],2);size_t n=(size_t)number(prhs[2]);plhs[0]=mxCreateDoubleMatrix(n,1,mxREAL);uint64_t count=0;
        check(cine_stats_finish(h->ptr,mxGetDoubles(plhs[0]),n,&count));return;
    }
    if(!strcmp(command,"stats_close")){arity(nrhs,2,nlhs,0);remove_handle(lookup(prhs[1],2));return;}
    mexErrMsgIdAndTxt("cine:command","Unknown command: %s",command);
}
